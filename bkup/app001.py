import os
import sqlite3
from flask import Flask, flash, redirect, render_template, request, url_for

app = Flask(__name__)
app.secret_key = "changethislatertoaenv"
DATABASE = "inventory.db"


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    """Initializes full schema and sets up automated SQLite Audit Triggers."""
    with app.app_context():
        db = get_db()
        if os.path.exists("schema.sql"):
            with open("schema.sql", "r") as f:
                db.cursor().executescript(f.read())

        # Seed Lookup tables if empty
        db.execute(
            "INSERT OR IGNORE INTO GTL (GLSTEX) VALUES ('Smooth'), ('Wispy'),  ('Waterglass')"
        )
        db.execute(
            "INSERT OR IGNORE INTO GSL (GLSOURCE, SRCWEB) VALUES ('Colorado Glass Co', 1), ('Hobby Lobby', 0), ('Charlotte Glass', 0)"
        )
        db.execute(
            "INSERT OR IGNORE INTO IGP (ITMGRP) VALUES ('Potions'), ('Fruit Slices'), ('Mushrooms')"
        )

        # Setup automated AUDIT trigger on ITM table changes
        db.executescript("""
            CREATE TRIGGER IF NOT EXISTS audit_itm_insert AFTER INSERT ON ITM BEGIN
                INSERT INTO AUDIT (TRNOP, TRNNEW, TRNTBL, TRNTS) 
                VALUES ('INSERT', NEW.ITMNAME, 'ITM', CURRENT_TIMESTAMP);
            END;
            CREATE TRIGGER IF NOT EXISTS audit_itm_delete AFTER DELETE ON ITM BEGIN
                INSERT INTO AUDIT (TRNOP, TRNOLD, TRNTBL, TRNTS) 
                VALUES ('DELETE', OLD.ITMNAME, 'ITM', CURRENT_TIMESTAMP);
            END;
        """)
        db.commit()


init_db()


# ============================================================================
# 1. NAVIGATION INDEX & SYSTEM DASHBOARD
# ============================================================================


@app.route("/")
def index():
    db = get_db()
    stats = {
        "items": db.execute("SELECT COUNT(*) FROM ITM").fetchone()[0],
        "glass": db.execute("SELECT COUNT(*) FROM GSI").fetchone()[0],
        "sales": db.execute("SELECT COUNT(*) FROM ITMSALE").fetchone()[0],
        "venues": db.execute("SELECT COUNT(*) FROM VENUE").fetchone()[0],
    }
    recent_audits = db.execute(
        "SELECT * FROM AUDIT ORDER BY TRANSID DESC LIMIT 10"
    ).fetchall()
    return render_template(
        "dashboard.html", stats=stats, recent_audits=recent_audits
    )


# --- CREATE (Add New Item) ---


@app.route("/item/new", methods=["GET", "POST"])
def create_item():
    db = get_db()

    if request.method == "POST":
        itmname = request.form.get("ITMNAME")
        itmgrp = request.form.get("ITMGRP") or None
        variid = request.form.get("VARIID") or None
        oneoff = 1 if request.form.get("ONEOFF") else 0
        variat = 1 if request.form.get("VARIAT") else 0
        current = 1 if request.form.get("CURRENT") else 0
        itmimg = request.form.get("ITMIMG")
        itmptrn = request.form.get("ITMPTRN")
        itmnote = request.form.get("ITMNOTE")

        db.execute(
            """
            INSERT INTO ITM (ITMNAME, ITMGRP, VARIID, ONEOFF, VARIAT, CURRENT, ITMIMG, ITMPTRN, ITMNOTE)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                itmname,
                itmgrp,
                variid,
                oneoff,
                variat,
                current,
                itmimg,
                itmptrn,
                itmnote,
            ),
        )
        db.commit()
        flash(f"Item '{itmname}' created successfully!", "success")
        return redirect(url_for("index"))

    groups = db.execute("SELECT * FROM IGP").fetchall()
    variants = db.execute("SELECT * FROM IVR").fetchall()
    return render_template(
        "item_form.html", action="Create", groups=groups, variants=variants
    )


# --- UPDATE (Edit Existing Item) ---


@app.route("/item/edit/<int:item_id>", methods=["GET", "POST"])
def edit_item(item_id):
    db = get_db()

    item = db.execute(
        "SELECT * FROM ITM WHERE ITEMID = ?", (item_id,)
    ).fetchone()
    if not item:
        flash("Item not found.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        itmname = request.form.get("ITMNAME")
        itmgrp = request.form.get("ITMGRP") or None
        variid = request.form.get("VARIID") or None
        oneoff = 1 if request.form.get("ONEOFF") else 0
        variat = 1 if request.form.get("VARIAT") else 0
        current = 1 if request.form.get("CURRENT") else 0
        itmimg = request.form.get("ITMIMG")
        itmptrn = request.form.get("ITMPTRN")
        itmnote = request.form.get("ITMNOTE")

        db.execute(
            """
            UPDATE ITM 
            SET ITMNAME = ?, ITMGRP = ?, VARIID = ?, ONEOFF = ?, VARIAT = ?, CURRENT = ?, ITMIMG = ?, ITMPTRN = ?, ITMNOTE = ?
            WHERE ITEMID = ?
        """,
            (
                itmname,
                itmgrp,
                variid,
                oneoff,
                variat,
                current,
                itmimg,
                itmptrn,
                itmnote,
                item_id,
            ),
        )
        db.commit()
        flash(f"Item #{item_id} updated successfully!", "success")
        return redirect(url_for("index"))

    groups = db.execute("SELECT * FROM IGP").fetchall()
    variants = db.execute("SELECT * FROM IVR").fetchall()
    return render_template(
        "item_form.html",
        action="Edit",
        item=item,
        groups=groups,
        variants=variants,
    )


# --- DELETE (Remove Item) ---


@app.route("/item/delete/<int:item_id>", methods=["POST"])
def delete_item(item_id):
    db = get_db()
    db.execute("DELETE FROM ITM WHERE ITEMID = ?", (item_id,))
    db.commit()
    flash(f"Item #{item_id} deleted successfully.", "warning")
    return redirect(url_for("index"))


# ============================================================================
# 2. GLASS SHEET INVENTORY MANAGEMENT (GSI, GTL, GSL, GPC)
# ============================================================================

@app.route('/glass')

def list_glass():

    db = get_db()

    # --- Capture Sort & Filter Parameters ---
    sort_by = request.args.get('sort_by', 'GLASSID')
    order = request.args.get('order', 'asc').lower()
    if order not in ['asc', 'desc']:
        order = 'asc'

    q = request.args.get('q', '').strip()
    manf = request.args.get('manf', '').strip()
    tex = request.args.get('tex', '').strip()
    color = request.args.get('color', '').strip()
    source = request.args.get('source', '').strip()
    min_price = request.args.get('min_price', '').strip()
    max_price = request.args.get('max_price', '').strip()

    # New Item Filters
    item_id = request.args.get('item_id', '').strip()
    item_name = request.args.get('item_name', '').strip()
    active_only = request.args.get('active_only', '')  # '1' if active/for sale only

    # Allowed sorting columns
    allowed_sorts = {
        'GLASSID': 'g.GLASSID',
        'GLSNAME': 'g.GLSNAME',
        'GLSMANF': 'g.GLSMANF',
        'GLSTEX': 'g.GLSTEX',
        'GLSOURCE': 'g.GLSOURCE',
        'GLSLEN': 'g.GLSLEN',
        'GLSPRICE': 'p.GLSPRICE'
    }
    sort_column = allowed_sorts.get(sort_by, 'g.GLASSID')

    # Build dynamic WHERE clause
    where_clauses = []
    params = []

    if q:
        where_clauses.append("(g.GLSNAME LIKE ? OR g.GLSMANF LIKE ? OR g.GLSNOTE LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if manf:
        where_clauses.append("g.GLSMANF = ?")
        params.append(manf)
    if tex:
        where_clauses.append("g.GLSTEX = ?")
        params.append(tex)
    if color:
        where_clauses.append("g.COLOR = ?")
        params.append(color)
    if source:
        where_clauses.append("g.GLSOURCE = ?")
        params.append(source)
    if min_price:
        where_clauses.append("p.GLSPRICE >= ?")
        params.append(min_price)
    if max_price:
        where_clauses.append("p.GLSPRICE <= ?")
        params.append(max_price)

    # Filter by specific Item ID (Glass used in components of selected Item)
    join_igc = ""
    if item_id:
        join_igc = "INNER JOIN IGC c ON g.GLASSID = c.GLASSID"
        where_clauses.append("c.ITEMID = ?")
        params.append(item_id)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # Execute main query
    query = f"""
        SELECT DISTINCT g.*, p.GLSPRICE
        FROM GSI g
        LEFT JOIN GPC p ON g.GLASSID = p.GLASSID
        {join_igc}
        {where_sql}
        ORDER BY {sort_column} {order.upper()}
    """
    glasses = db.execute(query, params).fetchall()

    # --- Fetch Lookups for Modal Dropdowns ---
    textures = db.execute("SELECT DISTINCT GLSTEX FROM GSI WHERE GLSTEX IS NOT NULL AND GLSTEX != '' ORDER BY GLSTEX").fetchall()
    colors = db.execute("SELECT DISTINCT COLOR FROM GSI WHERE COLOR IS NOT NULL AND COLOR != '' ORDER BY COLOR").fetchall()
    sources = db.execute("SELECT DISTINCT GLSOURCE FROM GSI WHERE GLSOURCE IS NOT NULL AND GLSOURCE != '' ORDER BY GLSOURCE").fetchall()
    manufacturers = db.execute("SELECT DISTINCT GLSMANF FROM GSI WHERE GLSMANF IS NOT NULL AND GLSMANF != '' ORDER BY GLSMANF").fetchall()

    # Fetch Item List: Ordered by Item Group Name (igp.ITMGRP), falling back to Item Name (ITM.ITMNAME)
    # COALESCE pick ITMGRP first; if NULL or empty, defaults to ITMNAME
    item_where = "WHERE i.CURRENT = 1" if active_only == '1' else ""
    items_query = f"""
        SELECT 
            i.ITEMID, 
            i.ITMNAME, 
            i.CURRENT,
            g.ITMGRP,
            COALESCE(NULLIF(g.ITMGRP, ''), i.ITMNAME) AS group_or_name
        FROM ITM i
        LEFT JOIN IGP g ON i.ITMGRP = g.ITMGRP
        {item_where}
        ORDER BY group_or_name ASC, i.ITMNAME ASC
    """
    items = db.execute(items_query).fetchall()
    # Resolve the human-readable item name if an item_id was selected
    item_name = ""
    if item_id:
        for item in items:
            if str(item['ITEMID']) == str(item_id):
               item_name = item['ITMNAME']
               break

    return render_template(
        'glass_list.html',
        glasses=glasses,
        textures=textures,
        colors=colors,
        sources=sources,
        manufacturers=manufacturers,
        items=items,
        current_sort=sort_by,
        current_order=order,
        filters={
            'q': q, 'manf': manf, 'tex': tex, 'source': source,
            'min_price': min_price, 'max_price': max_price,
            'item_id': item_id, 'item_name': item_name, 'active_only': active_only
        }
    )

@app.route("/glass/new", methods=["GET", "POST"])
def create_glass():
    db = get_db()
    if request.method == "POST":
        glsname = request.form.get("GLSNAME")
        glsmanf = request.form.get("GLSMANF")
        glstex = request.form.get("GLSTEX") or None
        glsource = request.form.get("GLSOURCE") or None
        price = request.form.get("GLSPRICE")

        cursor = db.execute(
            """
            INSERT INTO GSI (GLSNAME, GLSMANF, GLSTEX, GLSOURCE)
            VALUES (?, ?, ?, ?)
        """,
            (glsname, glsmanf, glstex, glsource),
        )
        glass_id = cursor.lastrowid

        if price:
            db.execute(
                """
                INSERT INTO GPC (GLASSID, GLSPRICE, STDATE) VALUES (?, ?, DATE('now'))
            """,
                (glass_id, price),
            )

        db.commit()
        flash("Glass sheet recorded successfully!", "success")
        return redirect(url_for("list_glass"))

    textures = db.execute("SELECT * FROM GTL").fetchall()
    sources = db.execute("SELECT * FROM GSL").fetchall()
    return render_template(
        "glass_form.html", textures=textures, sources=sources
    )

# --- GLASS DETAIL SUMMARY PAGE ---
@app.route('/glass/<int:glass_id>')
def glass_detail(glass_id):
    db = get_db()
    # Fetch glass details with its pricing history and supplier details
    glass = db.execute('''
        SELECT g.*, p.GLSPRICE, s.SRCWEB, s.GLSLOGO
        FROM GSI g
        LEFT JOIN GPC p ON g.GLASSID = p.GLASSID
        LEFT JOIN GSL s ON g.GLSOURCE = s.GLSOURCE
        WHERE g.GLASSID = ?
    ''', (glass_id,)).fetchone()

    if not glass:
        flash('Glass sheet record not found.', 'danger')
        return redirect(url_for('list_glass'))

    # Fetch any items that utilize this glass as a component (IGC)
    components = db.execute('''
        SELECT c.*, i.ITMNAME 
        FROM IGC c
        JOIN ITM i ON c.ITEMID = i.ITEMID
        WHERE c.GLASSID = ?
    ''', (glass_id,)).fetchall()

    return render_template(
        'glass_detail.html', glass=glass, components=components
    )


# --- EDIT GLASS SHEET ---
@app.route('/glass/edit/<int:glass_id>', methods=['GET', 'POST'])
def edit_glass(glass_id):
    db = get_db()
    glass = db.execute(
        'SELECT g.*, p.GLSPRICE FROM GSI g LEFT JOIN GPC p ON g.GLASSID ='
        ' p.GLASSID WHERE g.GLASSID = ?',
        (glass_id,),
    ).fetchone()

    if not glass:
        flash('Glass sheet record not found.', 'danger')
        return redirect(url_for('list_glass'))

    if request.method == 'POST':
        glsname = request.form.get('GLSNAME')
        glsmanf = request.form.get('GLSMANF')
        glstex = request.form.get('GLSTEX') or None
        glsource = request.form.get('GLSOURCE') or None
        glslen = request.form.get('GLSLEN') or None
        glswid = request.form.get('GLSWID') or None
        glsthk = request.form.get('GLSTHK') or None
        glsiri = 1 if request.form.get('GLSIRI') else 0
        glsopal = 1 if request.form.get('GLSOPAL') else 0
        gllink = request.form.get('GLLINK') or ""
        glsimg = request.form.get('GLSIMG')
        glsnote = request.form.get('GLSNOTE')
        price = request.form.get('GLSPRICE')

        # Update GSI table
        db.execute(
            '''
            UPDATE GSI 
            SET GLSNAME = ?, GLSMANF = ?, GLSTEX = ?, GLSOURCE = ?, 
                GLSLEN = ?, GLSWID = ?, GLSTHK = ?, GLSIRI = ?, 
                GLSOPAL = ?, GLLINK = ?, GLSIMG = ?, GLSNOTE = ?
            WHERE GLASSID = ?
        ''',
            (
                glsname,
                glsmanf,
                glstex,
                glsource,
                glslen,
                glswid,
                glsthk,
                glsiri,
                glsopal,
                gllink,
                glsimg,
                glsnote,
                glass_id,
            ),
        )

        # Update or Insert pricing into GPC
        if price:
            existing_price = db.execute(
                'SELECT * FROM GPC WHERE GLASSID = ?', (glass_id,)
            ).fetchone()
            if existing_price:
                db.execute(
                    '''
                    UPDATE GPC SET GLSPRICE = ?, STDATE = DATE('now') WHERE GLASSID = ?
                ''',
                    (price, glass_id),
                )
            else:
                db.execute(
                    '''
                    INSERT INTO GPC (GLASSID, GLSPRICE, STDATE) VALUES (?, ?, DATE('now'))
                ''',
                    (glass_id, price),
                )

        db.commit()
        flash('Glass details updated successfully!', 'success')
        return redirect(url_for('glass_detail', glass_id=glass_id))

    textures = db.execute('SELECT * FROM GTL').fetchall()
    sources = db.execute('SELECT * FROM GSL').fetchall()
    return render_template(
        'glass_form.html',
        glass=glass,
        textures=textures,
        sources=sources,
        action='Edit',
    )

# --- DELETE GLASS SHEET ---
@app.route('/glass/delete/<int:glass_id>', methods=['POST'])
def delete_glass(glass_id):
    db = get_db()
    # Delete related pricing records first (or let SQLite CASCADE handle it if foreign keys are configured)
    db.execute("DELETE FROM GPC WHERE GLASSID = ?", (glass_id,))
    db.execute("DELETE FROM GSI WHERE GLASSID = ?", (glass_id,))
    db.commit()
    flash(f"Glass sheet #{glass_id} deleted successfully.", "warning")
    return redirect(url_for('list_glass'))
# ============================================================================
# 3. INVENTORY & WORK-IN-PROGRESS TRACKING (ICC, ITR)
# ============================================================================


@app.route("/inventory")
def inventory_status():
    db = get_db()
    counts = db.execute("""
        SELECT i.ITMNAME, c.* 
        FROM ICC c
        JOIN ITM i ON c.ITEMID = i.ITEMID
    """).fetchall()
    return render_template("inventory_status.html", counts=counts)


@app.route("/inventory/update/<int:item_id>", methods=["POST"])
def update_inventory(item_id):
    db = get_db()
    ipcut = int(request.form.get("IPCUT", 0))
    ipgrnd = int(request.form.get("IPGRND", 0))
    ipfoil = int(request.form.get("IPFOIL", 0))
    ipsldr = int(request.form.get("IPSLDR", 0))
    ipdone = int(request.form.get("IPDONE", 0))

    # Update Current Inventory Level (ICC)
    db.execute(
        """
        INSERT INTO ICC (ITEMID, IPCUT, IPGRND, IPFOIL, IPSLDR, IPDONE, IPTS)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(ITEMID) DO UPDATE SET
            IPCUT=excluded.IPCUT, IPGRND=excluded.IPGRND, 
            IPFOIL=excluded.IPFOIL, IPSLDR=excluded.IPSLDR, 
            IPDONE=excluded.IPDONE, IPTS=CURRENT_TIMESTAMP
    """,
        (item_id, ipcut, ipgrnd, ipfoil, ipsldr, ipdone),
    )

    # Log Transaction Record (ITR)
    db.execute(
        """
        INSERT INTO ITR (ITEMID, IPCUT, IPGRND, IPFOIL, IPSLDR, IPDONE)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (item_id, ipcut, ipgrnd, ipfoil, ipsldr, ipdone),
    )

    db.commit()
    flash("Inventory metrics updated and logged to ITR.", "info")
    return redirect(url_for("inventory_status"))


# ============================================================================
# 4. SALES AND VENUE MANAGEMENT (ITMSALE, TIMESALE, VENUE)
# ============================================================================


@app.route("/sales")
def list_sales():
    db = get_db()
    sales = db.execute("""
        SELECT s.SALEID, i.ITMNAME, s.SUNITS, s.SDATE, v.VENUELOC 
        FROM ITMSALE s
        JOIN ITM i ON s.ITEMID = i.ITEMID
        LEFT JOIN VENUE v ON s.VENUEID = v.VENUEID
        ORDER BY s.SDATE DESC
    """).fetchall()
    return render_template("sales_list.html", sales=sales)


@app.route("/sales/new", methods=["GET", "POST"])
def record_sale():
    db = get_db()
    if request.method == "POST":
        itemid = request.form.get("ITEMID")
        sunits = request.form.get("SUNITS")
        venueid = request.form.get("VENUEID") or None

        db.execute(
            """
            INSERT INTO ITMSALE (ITEMID, SUNITS, SDATE, VENUEID)
            VALUES (?, ?, DATE('now'), ?)
        """,
            (itemid, sunits, venueid),
        )

        db.commit()
        flash("Sale logged successfully!", "success")
        return redirect(url_for("list_sales"))

    items = db.execute("SELECT ITEMID, ITMNAME FROM ITM").fetchall()
    venues = db.execute("SELECT VENUEID, VENUELOC FROM VENUE").fetchall()
    return render_template("sale_form.html", items=items, venues=venues)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7665, debug=True)
