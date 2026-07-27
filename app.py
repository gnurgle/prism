import os
import sqlite3
import xml.etree.ElementTree as ET
from lxml import etree
from svgpathtools import svg2paths, wsvg
from utils import process_and_save_image, hex_to_hsv, convert_image_to_svg, remove_svg_region_and_renumber
from flask import Flask, flash, redirect, render_template, request, url_for, render_template_string
from datetime import date, datetime, timedelta

app = Flask(__name__, static_folder='static')
app.secret_key = "changethislatertoaenv"
DATABASE = "inventory.db"

# Ensure these directories exist in your project root
UPLOAD_FOLDER_TEMPLATES = 'static/images/templates'
UPLOAD_FOLDER_SVG = 'static/images/svg'
UPLOAD_FOLDER_GLASS = 'static/images/glass'

os.makedirs(UPLOAD_FOLDER_TEMPLATES, exist_ok=True)
os.makedirs(UPLOAD_FOLDER_SVG, exist_ok=True)
os.makedirs(UPLOAD_FOLDER_GLASS, exist_ok=True)


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
            "INSERT OR IGNORE INTO GTL (GLSTEX) VALUES ('Smooth'), ('Wispy'), ('Waterglass'), ('Muffle'), ('RoughRolled'), ('Hammered'), ('Mottled'), ('Dichroic')"
        )
        db.execute(
            "INSERT OR IGNORE INTO GSL (GLSOURCE, SRCWEB) VALUES ('Colorado Glass Co', 1), ('Hobby Lobby', 0), ('Charlotte Glass', 0)"
        )
        db.execute(
            "INSERT OR IGNORE INTO IGP (ITMGRP) VALUES ('Potions'), ('Fruit Slices'), ('Mushrooms')"
        )
        db.execute(
            "INSERT OR IGNORE INTO COLOR (COLOR, CHEX) VALUES ('Red', 'FF0000'), ('Orange', 'FF8000'), ('Yellow', 'FFFF00'), ('Chartreuse Green', '80FF00'), ('Green', '00FF00'), ('Spring Green', '00FF80'), ('Azure', '0080FF'), ('Blue', '0000FF'), ('Violet', '8000FF'), ('Magenta', 'FF00FF'), ('Rose', 'FF0080'), ('White', '000000'), ('Black', 'FFFFFF'), ('Grey', '808080'), ('Transparent', '000000')"
        )
        db.execute(
            "INSERT OR IGNORE INTO GTRNS (GTRNSN, GTRNSV) VALUES ('Transparent', 60), ('Translucent', 75), ('Opaque', 95)"        )

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


@app.route('/item/<int:item_id>')
def item_detail(item_id):
  """Display full details, pricing metrics, components, and group siblings."""
  db = get_db()

  # Fetch core item record
  item = db.execute(
      'SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)
  ).fetchone()

  if not item:
    flash('Item record not found.', 'danger')
    return redirect(url_for('index'))

  # Fetch associated components (IGC) with joined glass info
  components = db.execute(
      """
        SELECT c.*, g.GLSNAME 
        FROM IGC c
        LEFT JOIN GSI g ON c.GLASSID = g.GLASSID
        WHERE c.ITEMID = ?
        ORDER BY c.COMPNUM ASC
    """,
      (item_id,),
  ).fetchall()

  # Fetch Pricing Metrics from IPC table using correct columns (ITMPRICE, STDATE, ENDDATE)
  current_price = db.execute(
      """
        SELECT ITMPRICE AS PRICE FROM IPC 
        WHERE ITEMID = ? AND (ENDDATE IS NULL OR ENDDATE >= DATE('now'))
        ORDER BY STDATE DESC LIMIT 1
    """,
      (item_id,),
  ).fetchone()

  lowest_price = db.execute(
      """
        SELECT ITMPRICE AS PRICE, STDATE AS START_DATE, ENDDATE AS END_DATE FROM IPC 
        WHERE ITEMID = ? 
        ORDER BY ITMPRICE ASC LIMIT 1
    """,
      (item_id,),
  ).fetchone()

  highest_price = db.execute(
      """
        SELECT ITMPRICE AS PRICE, STDATE AS START_DATE, ENDDATE AS END_DATE FROM IPC 
        WHERE ITEMID = ? 
        ORDER BY ITMPRICE DESC LIMIT 1
    """,
      (item_id,),
  ).fetchone()

  # Fetch group siblings if item is not a one-off and has a group assigned
  group_siblings = []
  if not item['ONEOFF'] and item['ITMGRP']:
    group_siblings = db.execute(
        """
            SELECT ITEMID, ITMNAME FROM ITM 
            WHERE ITMGRP = ? AND ONEOFF = 0
            ORDER BY ITMNAME ASC
        """,
        (item['ITMGRP'],),
    ).fetchall()

  return render_template(
      'item_detail.html',
      item=item,
      components=components,
      current_price=current_price,
      lowest_price=lowest_price,
      highest_price=highest_price,
      group_siblings=group_siblings,
  )
# -----------------------------------------------------------------------------
# CREATE ITEM ROUTE
# -----------------------------------------------------------------------------


@app.route('/item/create', methods=['GET', 'POST'])
def create_item():
  """Create a new Item record and handle group/image inputs."""
  db = get_db()

  if request.method == 'POST':
    itm_name = request.form.get('ITMNAME', '').strip()
    itm_grp = request.form.get('ITMGRP', '').strip()
    new_grp = request.form.get('NEW_ITMGRP', '').strip()
    oneoff = 1 if request.form.get('ONEOFF') else 0
    current = 1 if request.form.get('CURRENT') else 0
    itm_note = request.form.get('ITMNOTE', '').strip()

    # Handle new group insertion if provided
    selected_group = itm_grp
    if new_grp:
      selected_group = new_grp
      existing_grp = db.execute(
          'SELECT 1 FROM IGP WHERE ITMGRP = ?', (new_grp,)
      ).fetchone()
      if not existing_grp:
        db.execute(
            'INSERT INTO IGP (ITMGRP, ISACTIVE) VALUES (?, 1)', (new_grp,)
        )

    # Save initial record to get the item_id for naming the image file
    cursor = db.cursor()
    cursor.execute(
        """
            INSERT INTO ITM (ITMNAME, ITMGRP, ONEOFF, CURRENT, ITMNOTE, ITMIMG)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
        (itm_name, selected_group, oneoff, current, itm_note, None),
    )
    item_id = cursor.lastrowid
    db.commit()

    # Handle image upload using the modular helper signature
    image_path = None
    if 'ITMIMG_FILE' in request.files:
      file = request.files['ITMIMG_FILE']
      if file and file.filename != '':
        image_path = process_and_save_image(
            file,
            upload_subfolder='images/items',
            custom_filename_base=f'{item_id}_{itm_name}',
            target_size=(1024, 1024),
        )
        # Update record with the final image path if uploaded
        cursor.execute(
            'UPDATE ITM SET ITMIMG = ? WHERE ITEMID = ?', (image_path, item_id)
        )
        db.commit()

    flash(f'Item "{itm_name}" successfully created.', 'success')
    return redirect(url_for('item_detail', item_id=item_id))

  groups = db.execute(
      'SELECT DISTINCT ITMGRP FROM ITM WHERE ITMGRP IS NOT NULL AND ITMGRP !='
      " '' ORDER BY ITMGRP"
  ).fetchall()
  return render_template('item_form.html', action='Create', groups=groups)


@app.route('/item/<int:item_id>/edit', methods=['GET', 'POST'])
def edit_item(item_id):
  """Edit an existing Item record, matching glass image upload handling."""
  db = get_db()

  item = db.execute(
      'SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)
  ).fetchone()

  if not item:
    flash('Item record not found.', 'danger')
    return redirect(url_for('index'))

  if request.method == 'POST':
    itm_name = request.form.get('ITMNAME', '').strip()
    itm_grp = request.form.get('ITMGRP', '').strip()
    new_grp = request.form.get('NEW_ITMGRP', '').strip()
    oneoff = 1 if request.form.get('ONEOFF') else 0
    current = 1 if request.form.get('CURRENT') else 0
    itm_note = request.form.get('ITMNOTE', '').strip()

    selected_group = itm_grp
    if new_grp:
      selected_group = new_grp
      existing_grp = db.execute(
          'SELECT 1 FROM IGP WHERE ITMGRP = ?', (new_grp,)
      ).fetchone()
      if not existing_grp:
        db.execute(
            'INSERT INTO IGP (ITMGRP, ISACTIVE) VALUES (?, 1)', (new_grp,)
        )

    # Keep existing image unless a new file is uploaded
    image_path = item['ITMIMG']
    if 'ITMIMG_FILE' in request.files:
      file = request.files['ITMIMG_FILE']
      if file and file.filename != '':
        image_path = process_and_save_image(
            file,
            upload_subfolder='images/items',
            custom_filename_base=f'{item_id}_{itm_name}',
            target_size=(1024, 1024),
        )

    db.execute(
        """
            UPDATE ITM 
            SET ITMNAME = ?, 
                ITMGRP = ?, 
                ONEOFF = ?, 
                CURRENT = ?, 
                ITMNOTE = ?, 
                ITMIMG = ?
            WHERE ITEMID = ?
        """,
        (
            itm_name,
            selected_group,
            oneoff,
            current,
            itm_note,
            image_path,
            item_id,
        ),
    )
    db.commit()

    flash(f'Item "{itm_name}" updated successfully.', 'success')
    return redirect(url_for('item_detail', item_id=item_id))

  groups = db.execute(
      'SELECT DISTINCT ITMGRP FROM ITM WHERE ITMGRP IS NOT NULL AND ITMGRP !='
      " '' ORDER BY ITMGRP"
  ).fetchall()
  return render_template(
      'item_form.html', action='Edit', item=item, groups=groups
  )


@app.route('/item/<int:item_id>/history')
def price_history(item_id):
  """Display historical price list in descending order with calculated price changes and durations."""
  db = get_db()
  item = db.execute(
      'SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)
  ).fetchone()

  if not item:
    flash('Item record not found.', 'danger')
    return redirect(url_for('index'))

  # Fetch all prices ordered chronologically ascending to compute deltas and durations easily
  rows = db.execute(
      """
        SELECT rowid, ITMPRICE, STDATE, ENDDATE FROM IPC 
        WHERE ITEMID = ? 
        ORDER BY STDATE ASC
    """,
      (item_id,),
  ).fetchall()

  history_processed = []
  prev_price = None

  for row in rows:
    price = row['ITMPRICE']
    change = price - prev_price if prev_price is not None else None
    prev_price = price

    # Calculate duration
    start_dt = (
        datetime.strptime(row['STDATE'], '%Y-%m-%d')
        if row['STDATE']
        else None
    )
    end_dt = (
        datetime.strptime(row['ENDDATE'], '%Y-%m-%d')
        if row['ENDDATE']
        else datetime.today()
    )

    duration_str = 'N/A'
    if start_dt:
      delta = end_dt - start_dt
      days = delta.days
      years = days // 365
      rem_days = days % 365
      if years > 0:
        duration_str = f'{years} yr{"" if years == 1 else "s"} {rem_days} day{"" if rem_days == 1 else "s"}'
      else:
        duration_str = f'{days} day{"" if days == 1 else ""}'

    history_processed.append({
        'ITMPRICE': price,
        'change': change,
        'STDATE': row['STDATE'],
        'ENDDATE': row['ENDDATE'],
        'duration_str': duration_str,
    })

  # Reverse to have descending order starting from present
  history_processed.reverse()

  return render_template(
      'item_price_history.html', item=item, history=history_processed
  )


@app.route('/prices/<int:item_id>/edit', methods=['GET', 'POST'])
def edit_prices(item_id):
  """Manage and insert prices with automated date shuffling and interval overlap adjustments."""
  db = get_db()
  item = db.execute(
      'SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)
  ).fetchone()

  if not item:
    flash('Item record not found.', 'danger')
    return redirect(url_for('index'))

  if request.method == 'POST':
    try:
      new_price = float(request.form.get('ITMPRICE'))
    except (TypeError, ValueError):
      flash('Invalid price value provided.', 'danger')
      return redirect(url_for('edit_prices', item_id=item_id))

    new_st_str = request.form.get('STDATE')
    is_current = 1 if request.form.get('is_current') else 0
    new_end_str = None if is_current else request.form.get('ENDDATE')

    new_st = datetime.strptime(new_st_str, '%Y-%m-%d').date()
    new_end = (
        datetime.strptime(new_end_str, '%Y-%m-%d').date()
        if new_end_str
        else None
    )

    if new_end and new_st > new_end:
      flash('Start date cannot be after the end date.', 'danger')
      return redirect(url_for('edit_prices', item_id=item_id))

    cursor = db.cursor()

    # Fetch existing price intervals for this item
    existing_prices = cursor.execute(
        """
        SELECT rowid, ITMPRICE, STDATE, ENDDATE FROM IPC 
        WHERE ITEMID = ?
    """,
        (item_id,),
    ).fetchall()

    # Process and adjust overlapping intervals
    for row in existing_prices:
      row_id = row['rowid']
      ex_st_str = row['STDATE']
      ex_end_str = row['ENDDATE']

      ex_st = datetime.strptime(ex_st_str, '%Y-%m-%d').date() if ex_st_str else None
      ex_end = datetime.strptime(ex_end_str, '%Y-%m-%d').date() if ex_end_str else None

      # Case A: Existing range is completely inside the new range -> Delete it
      if ex_st and new_st <= ex_st and (new_end is None or (ex_end and new_end >= ex_end)):
        cursor.execute('DELETE FROM IPC WHERE rowid = ?', (row_id,))
        continue

      # Case B: New range is completely inside an existing range -> Split the existing range into two
      if ex_st and ex_end and new_st > ex_st and new_end and new_end < ex_end:
        # Update existing record to end right before new range starts (or day before)
        split_end_date = (new_st - timedelta(days=1)).strftime('%Y-%m-%d')
        cursor.execute(
            'UPDATE IPC SET ENDDATE = ? WHERE rowid = ?',
            (split_end_date, row_id)
        )
        # Insert the remaining tail piece of the old range
        tail_start_date = (new_end + timedelta(days=1)).strftime('%Y-%m-%d')
        cursor.execute(
            'INSERT INTO IPC (ITEMID, ITMPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, ?)',
            (item_id, row['ITMPRICE'], tail_start_date, ex_end_str)
        )
        continue

      # Case C: Overlap on the tail end of existing range (New start cuts into old range)
      if ex_st and new_st > ex_st and (ex_end is None or new_st <= ex_end):
        new_ex_end = (new_st - timedelta(days=1)).strftime('%Y-%m-%d')
        cursor.execute(
            'UPDATE IPC SET ENDDATE = ? WHERE rowid = ?',
            (new_ex_end, row_id)
        )

      # Case D: Overlap on the front end of existing range (New end cuts into old range)
      if new_end and ex_end and new_end >= ex_st and new_end < ex_end:
        new_ex_st = (new_end + timedelta(days=1)).strftime('%Y-%m-%d')
        cursor.execute(
            'UPDATE IPC SET STDATE = ? WHERE rowid = ?',
            (new_ex_st, row_id)
        )

      # Case E: If new range is ongoing (current), truncate any old ranges that overlap forward
      if is_current and ex_st and ex_st >= new_st:
        cursor.execute('DELETE FROM IPC WHERE rowid = ?', (row_id,))

    # Insert the new price record cleanly
    cursor.execute(
        """
        INSERT INTO IPC (ITEMID, ITMPRICE, STDATE, ENDDATE)
        VALUES (?, ?, ?, ?)
    """,
        (item_id, new_price, new_st_str, new_end_str),
    )

    db.commit()
    flash('Price range successfully saved and overlapping intervals adjusted.', 'success')
    return redirect(url_for('edit_prices', item_id=item_id))

  # GET Request: fetch all price rows ordered by start date descending
  prices = db.execute(
      """
        SELECT rowid, ITMPRICE, STDATE, ENDDATE FROM IPC 
        WHERE ITEMID = ? 
        ORDER BY STDATE DESC
    """,
      (item_id,),
  ).fetchall()

  return render_template(
      'item_edit_prices.html', item=item, prices=prices
  )

@app.route('/prices/<int:item_id>/delete/<int:price_id>', methods=['POST'])
def delete_price(item_id, price_id):
  """Delete a specific price entry row."""
  db = get_db()
  db.execute('DELETE FROM IPC WHERE rowid = ? AND ITEMID = ?', (price_id, item_id))
  db.commit()
  flash('Price tier removed.', 'success')
  return redirect(url_for('edit_prices', item_id=item_id))

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

    # Filter parameter for Glass active status (Defaults to showing active glass '1')
    is_active = request.args.get('is_active', '1').strip()

    item_id = request.args.get('item_id', '').strip()
    item_name = request.args.get('item_name', '').strip()
    active_only = request.args.get('active_only', '')  # '1' if active items only

    allowed_sorts = {
        'GLASSID': 'g.GLASSID',
        'GLSNAME': 'g.GLSNAME',
        'GLSMANF': 'g.GLSMANF',
        'GLSTEX': 'g.GLSTEX',
        'COLOR': 'g.COLOR',
        'GLSOURCE': 'g.GLSOURCE',
        'GLSLEN': 'g.GLSLEN',
        'GLSPRICE': 'p.GLSPRICE'
    }
    sort_column = allowed_sorts.get(sort_by, 'g.GLASSID')

    # Build dynamic WHERE clause for GSI table
    where_clauses = []
    params = []

    # Filter Glass by ISACTIVE integer flag
    if is_active != 'all':
        where_clauses.append("g.ISACTIVE = ?")
        params.append(1 if is_active == '1' else 0)

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
        SELECT DISTINCT g.*, p.GLSPRICE, c.CHEX
        FROM GSI g
        LEFT JOIN GPC p ON g.GLASSID = p.GLASSID
        LEFT JOIN COLOR c ON g.COLOR = c.COLOR
        {join_igc}
        {where_sql}
        ORDER BY {sort_column} {order.upper()}
    """
    glasses = db.execute(query, params).fetchall()

    # --- Fetch Active Lookups for Modal Dropdowns ---
    textures = db.execute(
        "SELECT DISTINCT GLSTEX FROM GSI WHERE ISACTIVE = 1 AND GLSTEX IS NOT NULL AND GLSTEX != '' ORDER BY GLSTEX"
    ).fetchall()
    
    colors = db.execute(
        "SELECT * FROM COLOR ORDER BY COLOR"
    ).fetchall()
    
    sources = db.execute(
        "SELECT DISTINCT GLSOURCE FROM GSI WHERE ISACTIVE = 1 AND GLSOURCE IS NOT NULL AND GLSOURCE != '' ORDER BY GLSOURCE"
    ).fetchall()
    
    manufacturers = db.execute(
        "SELECT DISTINCT GLSMANF FROM GSI WHERE ISACTIVE = 1 AND GLSMANF IS NOT NULL AND GLSMANF != '' ORDER BY GLSMANF"
    ).fetchall()

    # Fetch Item List using ITM.ISACTIVE instead of ITM.CURRENT
    item_where = "WHERE i.ISACTIVE = 1" if active_only == '1' else ""
    items_query = f"""
        SELECT 
            i.ITEMID, 
            i.ITMNAME, 
            i.ISACTIVE,
            g.ITMGRP,
            COALESCE(NULLIF(g.ITMGRP, ''), i.ITMNAME) AS group_or_name
        FROM ITM i
        LEFT JOIN IGP g ON i.ITMGRP = g.ITMGRP
        {item_where}
        ORDER BY group_or_name ASC, i.ITMNAME ASC
    """
    items = db.execute(items_query).fetchall()

    # Resolve human-readable item name if item_id was passed
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
            'q': q, 
            'manf': manf, 
            'tex': tex, 
            'color': color, 
            'source': source,
            'min_price': min_price, 
            'max_price': max_price,
            'is_active': is_active,
            'item_id': item_id, 
            'item_name': item_name, 
            'active_only': active_only
        }
    )
@app.route("/glass/new", methods=["GET", "POST"])
def create_glass():

    db = get_db()
    if request.method == "POST":

        glsname = request.form.get('GLSNAME')
        glsmanf = request.form.get('GLSMANF')
        glstex = request.form.get('GLSTEX') or None
        gtrnsn = request.form.get('GTRNSN') or None
        color = request.form.get('COLOR') or None
        glsource = request.form.get('GLSOURCE') or None
        glslen = request.form.get('GLSLEN') or None
        glswid = request.form.get('GLSWID') or None
        glsthk = request.form.get('GLSTHK') or None
        glsiri = 1 if request.form.get('GLSIRI') else 0
        glsopal = 1 if request.form.get('GLSOPAL') else 0
        gllink = request.form.get('GLLINK') or None
        glsimg = request.form.get('GLSIMG')
        glsnote = request.form.get('GLSNOTE')
        price = request.form.get('GLSPRICE')
        isactive = 1

        cursor = db.execute(
            """
            INSERT INTO GSI (GLSNAME, GLSMANF, GLSTEX, GTRNSN, COLOR, GLSOURCE, 
                GLSLEN, GLSWID, GLSTHK, GLSIRI,GLSOPAL, GLLINK, 
                GLSIMG, GLSNOTE, ISACTIVE)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            (
                glsname, glsmanf, glstex, gtrnsn, color, glsource, glslen,
                glswid, glsthk, glsiri, glsopal, gllink, glsimg,
                glsnote, isactive
            ),
        )

        glass_id = cursor.lastrowid

        glsimg_path = None
        file = request.files.get("GLSIMG_FILE")
        if file and file.filename != '':
            pattern_name = f"{glass_id}_{glsname}"
            glsimg_path = process_and_save_image(
                file_obj=file,
                upload_subfolder='images/glass',
                custom_filename_base=pattern_name,
                target_size=(256, 256)
            )
            # Update GLSIMG field in GSI table
            db.execute("UPDATE GSI SET GLSIMG = ? WHERE GLASSID = ?", (glsimg_path, glass_id))

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
    colors = db.execute("SELECT * FROM COLOR").fetchall()
    sources = db.execute("SELECT * FROM GSL").fetchall()
    transparency = db.execute("SELECT * FROM GTRNS").fetchall()
    return render_template(
        "glass_form.html", textures=textures, transparency=transparency, colors=colors, sources=sources
    )
# --- GLASS DETAIL SUMMARY PAGE ---
@app.route('/glass/<int:glass_id>')
def glass_detail(glass_id):
    db = get_db()
    # Fetch glass details with pricing history, supplier details, and hex color code
    glass = db.execute('''
        SELECT g.*, p.GLSPRICE, s.SRCWEB, s.GLSLOGO, c.CHEX
        FROM GSI g
        LEFT JOIN GPC p ON g.GLASSID = p.GLASSID
        LEFT JOIN GSL s ON g.GLSOURCE = s.GLSOURCE
        LEFT JOIN COLOR c ON g.COLOR = c.COLOR
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

@app.route('/glass/edit/<int:glass_id>', methods=['GET', 'POST'])

def edit_glass(glass_id):

    db = get_db()

    glass = db.execute('''
        SELECT g.*, p.GLSPRICE, c.CHEX 
        FROM GSI g 
        LEFT JOIN GPC p ON g.GLASSID = p.GLASSID 
        LEFT JOIN COLOR c ON g.COLOR = c.COLOR 
        LEFT JOIN GTRNS t ON g.GTRNSN = t.GTRNSN
        WHERE g.GLASSID = ?

    ''', (glass_id,)).fetchone()

    if not glass:
        flash('Glass sheet record not found.', 'danger')
        return redirect(url_for('list_glass'))

    if request.method == 'POST':
        glsname = request.form.get('GLSNAME')
        glsmanf = request.form.get('GLSMANF')
        glstex = request.form.get('GLSTEX') or None
        gtrnsn = request.form.get('GTRNSN') or None
        color = request.form.get('COLOR') or None
        glsource = request.form.get('GLSOURCE') or None
        glslen = request.form.get('GLSLEN') or None
        glswid = request.form.get('GLSWID') or None
        glsthk = request.form.get('GLSTHK') or None
        glsiri = 1 if request.form.get('GLSIRI') else 0
        glsopal = 1 if request.form.get('GLSOPAL') else 0
        gllink = request.form.get('GLLINK') or None
        glsnote = request.form.get('GLSNOTE')
        price = request.form.get('GLSPRICE')



        # Handle File Upload or maintain manual text string entry
        file = request.files.get('GLSIMG_FILE')
        if file and file.filename != '':
            pattern_name = f"{glass_id}_{glsname}"
            glsimg = process_and_save_image(
                file_obj=file,
                upload_subfolder='images/glass',
                custom_filename_base=pattern_name,
                target_size=(256, 256)
            )
        else:
            # Fall back to existing field value or manual input string
            glsimg = request.form.get('GLSIMG') or glass['GLSIMG']

        # Update GSI table
        db.execute(
            '''
            UPDATE GSI 
            SET GLSNAME = ?, GLSMANF = ?, GLSTEX = ?, GTRNSN = ?, COLOR = ?, GLSOURCE = ?, 
                GLSLEN = ?, GLSWID = ?, GLSTHK = ?, GLSIRI = ?, 
                GLSOPAL = ?, GLLINK = ?, GLSIMG = ?, GLSNOTE = ?
            WHERE GLASSID = ?
        ''',
            (
                glsname,
                glsmanf,
                glstex,
                gtrnsn,
                color,
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
    transparency = db.execute('SELECT * FROM GTRNS').fetchall()
    colors = db.execute('SELECT * FROM COLOR').fetchall()
    sources = db.execute('SELECT * FROM GSL').fetchall()

    return render_template(
        'glass_form.html',
        glass=glass,
        textures=textures,
        transparency=transparency,
        colors=colors,
        sources=sources,
        action='Edit',

    )

@app.route('/glass/delete/<int:glass_id>', methods=['POST'])
def delete_glass(glass_id):
    db = get_db()
    
    # Perform a soft delete by setting ISACTIVE flag to 0
    db.execute("UPDATE GSI SET ISACTIVE = 0 WHERE GLASSID = ?", (glass_id,))
    db.commit()
    
    flash(f"Glass sheet #{glass_id} deactivated successfully.", "warning")
    return redirect(url_for('list_glass'))

@app.route('/glass/inventory', methods=['GET', 'POST'])
def glass_inventory():

    db = get_db()

    if request.method == 'POST':
        glass_id = request.form.get('GLASSID')
        adjustment = request.form.get('GLSSTOCK')
        trans_date = request.form.get('TS') or date.today().isoformat()

        if glass_id and adjustment:
            db.execute(
                """
                INSERT INTO GLSINV (GLASSID, GLSSTOCK, TS)
                VALUES (?, ?, ?)
                """,
                (glass_id, int(adjustment), trans_date)
            )
            db.commit()
            flash("Inventory level adjusted successfully!", "success")
        else:
            flash("Invalid input parameters for stock adjustment.", "danger")
            
        return redirect(url_for('glass_inventory'))

    # --- Capture Sort & Filter Parameters ---
    sort_by = request.args.get('sort_by', 'GLSNAME')
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
    stock_filter = request.args.get('stock_filter', '').strip()
    iridescent_filter = request.args.get('iridescent')
    opalescent_filter = request.args.get('opalescent')
    stock_display_mode = request.args.get('stock_display', 'all')

    allowed_sorts = {
        'GLASSID': 'GLASSID',
        'GLSNAME': 'GLSNAME',
        'GLSMANF': 'GLSMANF',
        'GLSTEX': 'GLSTEX',
        'COLOR': 'COLOR',
        'COLOR_HSV': 'COLOR_HSV',
        'GLSIRI': 'GLSIRI',
        'GLSOPAL': 'GLSOPAL',
        'GLSLEN': 'GLSLEN',
        'CURRENT_STOCK': 'CURRENT_STOCK',
        'LAST_UPDATED': 'LAST_UPDATED'
    }
    
    # If sorting by COLOR_HSV, fetch sorted by secondary or default column from SQL, then sort in Python
    sql_sort_column = 'GLSNAME' if sort_by == 'COLOR_HSV' else allowed_sorts.get(sort_by, 'GLSNAME')

    # Build dynamic WHERE clause for base query
    where_clauses = ["g.ISACTIVE = 1"]
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
    if iridescent_filter:
        where_clauses.append("g.GLSIRI = ?")
        params.append(iridescent_filter)
    if opalescent_filter:
        where_clauses.append("g.GLSOPAL = ?")
        params.append(opalescent_filter)
    if source:
        where_clauses.append("g.GLSOURCE = ?")
        params.append(source)
    if min_price:
        where_clauses.append("p.GLSPRICE >= ?")
        params.append(min_price)
    if max_price:
        where_clauses.append("p.GLSPRICE <= ?")
        params.append(max_price)

    where_sql = f"WHERE {' AND '.join(where_clauses)}"

    having_conditions = []
    if stock_filter == 'out':
        having_conditions.append("CURRENT_STOCK = 0")
    elif stock_filter == 'low':
        having_conditions.append("CURRENT_STOCK = 1")
    elif stock_filter == 'in':
        having_conditions.append("CURRENT_STOCK > 1")

    if stock_display_mode == 'out':
        having_conditions.append("CURRENT_STOCK <= 0")
    elif stock_display_mode == 'hide':
        having_conditions.append("CURRENT_STOCK > 0")

    # Add GROUP BY GLASSID so the HAVING clause is valid syntax in SQLite
    stock_having_sql = f"GROUP BY GLASSID HAVING {' AND '.join(having_conditions)}" if having_conditions else ""

    query = f"""
        SELECT GLASSID, GLSNAME, GLSMANF, GLSLEN, GLSWID, GLSTHK, GLSTEX, 
               GLSIRI, GLSOPAL, GLSOURCE, GLLINK, GLSIMG, GLSNOTE, COLOR, 
               ISACTIVE, CHEX, GLSPRICE, SRCWEB, CURRENT_STOCK, LAST_UPDATED
        FROM (
            SELECT g.GLASSID, g.GLSNAME, g.GLSMANF, g.GLSLEN, g.GLSWID, g.GLSTHK, 
                   g.GLSTEX, g.GLSIRI, g.GLSOPAL, g.GLSOURCE, g.GLLINK, g.GLSIMG, 
                   g.GLSNOTE, g.COLOR, g.ISACTIVE, c.CHEX, p.GLSPRICE, l.SRCWEB,
                   COALESCE((
                       SELECT i.GLSSTOCK 
                       FROM GLSINV i 
                       WHERE i.GLASSID = g.GLASSID 
                       ORDER BY i.TS DESC, i.GLSTRNID DESC 
                       LIMIT 1
                   ), 0) AS CURRENT_STOCK,
                   (
                       SELECT i.TS 
                       FROM GLSINV i 
                       WHERE i.GLASSID = g.GLASSID 
                       ORDER BY i.TS DESC, i.GLSTRNID DESC 
                       LIMIT 1
                   ) AS LAST_UPDATED
            FROM GSI g
            LEFT JOIN COLOR c ON g.COLOR = c.COLOR
            LEFT JOIN GPC p ON g.GLASSID = p.GLASSID
            LEFT JOIN GSL l ON g.GLSOURCE = l.GLSOURCE
            {where_sql}
        ) sub
        {stock_having_sql}
        ORDER BY {sql_sort_column} {order.upper()}
    """
    raw_items = db.execute(query, params).fetchall()

    # Post-process items to attach HSV values and handle numeric sort cleanly if requested
    inventory_items = []
    for row in raw_items:
        item = dict(row)
        item['COLOR_HSV'] = hex_to_hsv(item.get('CHEX'))
        inventory_items.append(item)

    if sort_by == 'COLOR_HSV':
        inventory_items.sort(
            key=lambda x: x['COLOR_HSV'],
            reverse=(order == 'desc')
        )

    # --- Fetch Lookups for Filter Dropdowns ---
    textures = db.execute("SELECT DISTINCT GLSTEX FROM GSI WHERE ISACTIVE = 1 AND GLSTEX IS NOT NULL AND GLSTEX != '' ORDER BY GLSTEX").fetchall()
    colors = db.execute("SELECT * FROM COLOR ORDER BY COLOR").fetchall()
    sources = db.execute("SELECT DISTINCT GLSOURCE FROM GSI WHERE ISACTIVE = 1 AND GLSOURCE IS NOT NULL AND GLSOURCE != '' ORDER BY GLSOURCE").fetchall()
    manufacturers = db.execute("SELECT DISTINCT GLSMANF FROM GSI WHERE ISACTIVE = 1 AND GLSMANF IS NOT NULL AND GLSMANF != '' ORDER BY GLSMANF").fetchall()
    iridescent_options = db.execute("SELECT DISTINCT GLSIRI FROM GSI WHERE ISACTIVE = 1 AND GLSIRI = 1").fetchall()
    opalescent_options = db.execute("SELECT DISTINCT GLSOPAL FROM GSI WHERE ISACTIVE = 1 AND GLSOPAL = 1").fetchall()

    return render_template(
        'glass_inventory.html',
        inventory_items=inventory_items,
        textures=textures,
        colors=colors,
        sources=sources,
        manufacturers=manufacturers,
        iridescent_options=iridescent_options,
        opalescent_options=opalescent_options,
        current_sort=sort_by,
        current_order=order,
        today_date=date.today().isoformat(),
        filters={
            'q': request.args.get('q', ''),
            'manf': request.args.get('manf', ''),
            'tex': request.args.get('tex', ''),
            'color': request.args.get('color', ''),
            'source': request.args.get('source', ''),
            'min_price': request.args.get('min_price', ''),
            'max_price': request.args.get('max_price', ''),
            'stock_filter': request.args.get('stock_filter', ''),
            'stock_display': stock_display_mode,
            'iridescent': request.args.get('iridescent', ''),
            'opalescent': request.args.get('opalescent', '')
        }
    )

# ============================================================================
# COMPONENTS
# ============================================================================

@app.route("/template/upload", methods=["GET", "POST"])



def upload_template():

    db = get_db()

    if request.method == "POST":
        item_id = request.form.get("ITEMID")
        file = request.files.get("template_image")

        if not item_id or not file:
            flash("Please select an item and upload an image.", "danger")
            return redirect(request.url)
            
        item = db.execute("SELECT * FROM ITM WHERE ITEMID = ?", (item_id,)).fetchone()

        if not item:
            flash("Selected item not found.", "danger")
            return redirect(url_for("index"))
            
        # Format filename safely
        safe_item_name = "".join(c for c in item['ITMNAME'] if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
        file_ext = os.path.splitext(file.filename)[1] or '.png'
        filename = f"{item['ITEMID']}_{safe_item_name}{file_ext}"
        
        # Save uploaded raster image
        img_path = os.path.join(UPLOAD_FOLDER_TEMPLATES, filename)
        file.save(img_path)
        
        # Update database path
        relative_img_path = f"images/templates/{filename}"
        db.execute("UPDATE ITM SET ITMPTRN = ? WHERE ITEMID = ?", (relative_img_path, item_id))
        db.commit()
        
        # Automatically convert to SVG using the reusable method
        svg_filename = f"{item['ITEMID']}_{safe_item_name}.svg"
        svg_path = os.path.join(UPLOAD_FOLDER_SVG, svg_filename)
        
        success = convert_image_to_svg(img_path, svg_path)
        if success:
          # Save the SVG path to ITM.ITMSVG after successful conversion
            relative_svg_path = f"images/svg/{svg_filename}"

            db.execute("UPDATE ITM SET ITMSVG = ? WHERE ITEMID = ?", (relative_svg_path, item_id))
            db.commit()
            flash("Template uploaded and converted to SVG via pyautotrace successfully!", "success")
        else:
            flash("Template uploaded, but SVG conversion failed.", "warning")
            
        return redirect(url_for('edit_template', item_id=item_id))
    items = db.execute("SELECT ITEMID, ITMNAME FROM ITM").fetchall()
    return render_template("template_upload.html", items=items)


@app.route("/template/whitespaces/<int:item_id>")

def view_template_whitespaces(item_id):

    db = get_db()
    item = db.execute("SELECT * FROM ITM WHERE ITEMID = ?", (item_id,)).fetchone()
    if not item or not item['ITMPTRN']:
        flash("Template not found or image not uploaded.", "danger")
        return redirect(url_for("index"))
        
    safe_item_name = "".join(c for c in item['ITMNAME'] if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
    svg_filename = f"{item['ITEMID']}_{safe_item_name}.svg"
    svg_path = os.path.join(UPLOAD_FOLDER_SVG, svg_filename)
    svg_url = url_for('static', filename=f"images/svg/{svg_filename}")
    
    # 1. Autoparse the SVG to discover path/shape elements
    clickable_regions = []
    if os.path.exists(svg_path):
        try:
            # Register namespaces to prevent prefix issues with SVG elements
            ET.register_namespace('', "http://www.w3.org/2000/svg")
            tree = ET.parse(svg_path)
            root = tree.getroot()
            
            # Find all path, rect, circle, or polygon elements inside the SVG
            # SVG elements often use namespaces like {http://www.w3.org/2000/svg}path
            elements = []
            for elem in root.iter():
                tag_name = elem.tag.split('}')[-1].lower()
                if tag_name in ['path', 'rect', 'polygon', 'circle', 'polyline']:
                    elements.append(elem)
            
            # 2. Extract bounds/positions to sort them accurately from LEFT to RIGHT
            parsed_elements = []
            for idx, el in enumerate(elements):
                # Basic heuristic fallback bounding extraction or attributes
                # If it's a rect, it has x coordinate
                x_val = 0.0
                if el.tag.endswith('rect'):
                    x_val = float(el.attrib.get('x', 0))
                elif el.tag.endswith('circle'):
                    x_val = float(el.attrib.get('cx', 0)) - float(el.attrib.get('r', 0))
                else:
                    # For paths or polygons, check if we can parse basic attributes or fallback to index
                    x_val = float(idx * 10) # fallback sorting offset
                
                parsed_elements.append((x_val, idx, el))
            
            # Sort elements strictly from left to right based on X coordinate
            parsed_elements.sort(key=lambda item: item[0])
            
            # 3. Assign sequential numbers from left to right and inject clickable properties
            for index, (x, orig_idx, el) in enumerate(parsed_elements, start=1):
                region_id = f"region_{index}"
                el.set('id', region_id)
                el.set('data-number', str(index))
                # Add styling classes for interactive popups and hover cursors
                existing_class = el.attrib.get('class', '')
                el.set('class', f"{existing_class} whitespace-area".strip())
                el.set('style', 'cursor: pointer; fill-opacity: 0.2; stroke: #007bff; stroke-width: 2px;')
                
                clickable_regions.append({
                    "number": index,
                    "id": region_id
                })
                
            # Save modified SVG back or keep it in memory for rendering
            tree.write(svg_path)
            
        except Exception as e:
            print(f"Error parsing SVG for whitespaces: {e}")

    return render_template("template_whitespaces.html", item=item, svg_url=svg_url, regions=clickable_regions)
# ============================================================================
# TEMPLATES
# ============================================================================

@app.route('/template/<int:item_id>/edit', methods=['GET', 'POST'])

def edit_template(item_id):

    conn = get_db()

    item = conn.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()

    

    if not item:

        conn.close()

        flash('Template not found.', 'danger')

        return redirect(url_for('index'))



    svg_file_field = item['ITMSVG'] or f"{item_id}.svg"

    svg_path = os.path.join(app.root_path, 'static', svg_file_field)



    message = None



    if request.method == 'POST':

        target_region_num = request.form.get('region_id')

        print(f"ROUTE CONSOLE WRITE ---> Target File: '{svg_path}' | Region to Delete: '{target_region_num}'")



        if not os.path.exists(svg_path):

            message = f"Error: File does not exist at absolute path: {svg_path}"

        else:

            try:

                # 1. Parse using robust XML parser settings

                parser = etree.XMLParser(remove_blank_text=True, recover=True)

                tree = etree.parse(svg_path, parser)

                

                # 2. Use local-name() wildcard to bypass strict or missing namespace prefix issues

                path_elements = tree.xpath('//*[local-name()="path"]')



                removed = False

                for elem in path_elements:

                    region_val = elem.get('data-region-id')

                    elem_id = elem.get('id', '')



                    # Match by data-region-id or ID string format (e.g., 'region-2' or '2')

                    if (region_val and str(region_val).strip() == str(target_region_num)) or (elem_id in [f"region-{target_region_num}", str(target_region_num)]):

                        

                        parent = elem.getparent()

                        if parent is not None:

                            parent.remove(elem)

                            removed = True

                            print(f"ROUTE SUCCESS: Removed element ID '{elem_id}', data-region-id '{region_val}'")

                        break



                if removed:

                    # 3. Re-fetch remaining paths and re-index attributes sequentially

                    remaining_paths = tree.xpath('//*[local-name()="path"]')

                    for new_idx, elem in enumerate(remaining_paths, start=1):

                        elem.set('id', f'region-{new_idx}')

                        elem.set('data-region-id', str(new_idx))

                        if elem.get('data-number') is not None:

                            elem.set('data-number', str(new_idx))



                    # 4. Explicitly write back out to disk using binary mode

                    root = tree.getroot()

                    xml_bytes = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='utf-8')

                    with open(svg_path, 'wb') as f:

                        f.write(xml_bytes)



                    flash(f"Success! Region {target_region_num} deleted and file updated on disk.", "success")

                else:

                    flash(f"Warning: Could not find any path matching region ID '{target_region_num}' in {svg_file_field}.", "warning")

            except Exception as e:

                flash(f"Exception occurred during processing: {str(e)}", "danger")

                print(f"ROUTE EXCEPTION: {e}")



        conn.close()

        return redirect(url_for('edit_template', item_id=item_id))



    conn.close()



    # Read current state of paths for display on the template interface

    paths_list = []

    if os.path.exists(svg_path):

        try:

            parser = etree.XMLParser(remove_blank_text=True, recover=True)

            tree = etree.parse(svg_path, parser)

            path_elements = tree.xpath('//*[local-name()="path"]')

            for idx, elem in enumerate(path_elements):

                region_label = elem.get('data-region-id') or elem.get('data-number') or str(idx + 1)

                element_id = elem.get('id', f'path-{idx+1}')

                paths_list.append({

                    'index': idx,

                    'id': element_id,

                    'label': region_label,

                    'data_region_id': region_label

                })

        except Exception as e:

            print(f"Error reading paths for template view: {e}")



    return render_template('edit_template.html', item=item, paths_list=paths_list)


# ============================================================================
# COMPONENTS
# =============================================================================
@app.route('/build_components', methods=['GET', 'POST'])
def build_components():
    db = get_db()
    
    if request.method == 'POST':
        selected_item_id = request.form.get('item_id')
        
        if not selected_item_id:
            flash('Please select a valid item.', 'danger')
            return redirect(url_for('build_components'))
            
        # Fetch the selected item
        item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (selected_item_id,)).fetchone()
        
        svg_filename = item['ITMSVG'] if (item and 'ITMSVG' in item.keys()) else None
        
        if item and svg_filename:
            # 1. Do a search first and remove any items from IGC where IGC.ITEMID = selected ITEMID
            db.execute('DELETE FROM IGC WHERE ITEMID = ?', (selected_item_id,))
            
            # 2. Locate and parse the SVG file from static/
            svg_path = os.path.join(app.root_path, 'static', svg_filename)
            
            if os.path.exists(svg_path):
                try:
                    ET.register_namespace('', "http://www.w3.org/2000/svg")
                    tree = ET.parse(svg_path)
                    root = tree.getroot()
                    
                    # Find all path elements
                    paths = root.findall('.//{http://www.w3.org/2000/svg}path')
                    if not paths:
                        paths = root.findall('.//path')
                        
                    comp_counter = 1
                    for path in paths:
                        # Extract data-region-id attribute
                        region_id = None
                        for k, v in path.attrib.items():
                            if 'data-region-id' in k.lower() or k.lower() == 'region-id':
                                region_id = v
                                break
                        
                        if not region_id:
                            region_id = comp_counter
                            
                        try:
                            svg_reg_val = int(region_id)
                        except ValueError:
                            svg_reg_val = comp_counter
                            
                        # 3. Insert into IGC table: Saving ITEMID, SVGREG, COMPNUM, and setting ISACTIVE = 1
                        db.execute('''
                            INSERT INTO IGC (ITEMID, SVGREG, COMPNUM, ISACTIVE)
                            VALUES (?, ?, ?, 1)
                        ''', (selected_item_id, svg_reg_val, comp_counter))
                        
                        comp_counter += 1
                        
                    db.commit()
                    flash('Components successfully built and saved to IGC!', 'success')
                except Exception as e:
                    flash(f'Error parsing SVG file: {str(e)}', 'danger')
            else:
                flash(f'SVG file not found at static/{svg_filename}', 'danger')
        else:
            flash('Selected item does not have a reference SVG file or ITMSVG is empty.', 'warning')
            
        return redirect(url_for('build_components'))

    # GET Request: Fetch all items to populate the dropdown by ITM.ITMNAME
    items = db.execute('SELECT ITEMID, ITMNAME FROM ITM').fetchall()
    return render_template('build_components.html', items=items)


@app.route('/edit_components/<int:item_id>', methods=['GET'])

def edit_components(item_id):

    db = get_db()

    # Fetch Item and its SVG
    item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()
    if not item:
        flash('Item not found.', 'danger')
        return redirect(url_for('index'))

    svg_filename = item['ITMSVG'] if 'ITMSVG' in item.keys() else None
    svg_url = url_for('static', filename=svg_filename) if svg_filename else ''

    # Fetch all glass options for the dropdown (GSI table)
    glass_options = db.execute('SELECT GLASSID, GLSNAME FROM GSI WHERE ISACTIVE = 1').fetchall()

    # Fetch components joined with glass and color info to map svg regions to color hexes and textures
    # IGC -> GSI -> COLOR

    components = db.execute('''
        SELECT 
            i.COMPID, i.COMPNAME, i.ITEMID, i.COMPNUM, i.SVGREG, 
            i.GLASSID, i.COMPLEN, i.COMPWID, i.COMPNOTE,
            i.ISSCRAP, i.ISGRAIN, i.ISACTIVE,
            c.CHEX, g.GLSTEX, g.GTRNSN, g.GLSIMG, t.GTRNSV
        FROM IGC i
        LEFT JOIN GSI g ON i.GLASSID = g.GLASSID
        LEFT JOIN COLOR c ON g.COLOR = c.COLOR
        LEFT JOIN GTRNS t ON g.GTRNSN = t.GTRNSN
        WHERE i.ITEMID = ?

    ''', (item_id,)).fetchall()



    # Convert components to a dictionary keyed by SVGREG for easy lookup in the template

    comp_map = {}

    for comp in components:
        comp_map[comp['SVGREG']] = {
            'COMPID': comp['COMPID'],
            'COMPNAME': comp['COMPNAME'] or '',
            'COMPNUM': comp['COMPNUM'] or '',
            'SVGREG': comp['SVGREG'],
            'GLASSID': comp['GLASSID'] or '',
            'COMPLEN': comp['COMPLEN'] or '',
            'COMPWID': comp['COMPWID'] or '',
            'ISSCRAP': 1 if comp['ISSCRAP'] else 0,
            'ISGRAIN': 1 if comp['ISGRAIN'] else 0,
            'CHEX': comp['CHEX'] or 'cccccc', # default grey if no color assigned
            'GLSIMG': comp['GLSIMG'] or '',
            'GLSTEX': comp['GLSTEX'] or '',
            'GTRNSV': comp['GTRNSV']
        }

    return render_template(
        'edit_components.html', 
        item=item, 
        svg_url=svg_url, 
        glass_options=glass_options, 

        components_json=comp_map

    )




@app.route('/edit_componentsb/<int:item_id>', methods=['GET'])

def edit_componentsb(item_id):

    db = get_db()

    

    # Fetch item details

    item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()

    if not item:

        flash('Item not found.', 'danger')

        return redirect(url_for('index'))

    

    # Fetch available glass options for the dropdown

    glass_options = db.execute('SELECT GLASSID, GLSNAME FROM GSI ORDER BY GLSNAME').fetchall()

    

    # Fetch components joined with glass inventory (GSI/GLS) and color data, including GLTRS and GLSTEX

    query = '''

        SELECT 

            c.COMPID,

            c.COMPNUM,

            c.COMPNAME,

            c.COMPLEN,

            c.COMPWID,

            c.GLASSID,

            c.ISSCRAP,

            c.ISGRAIN,

            g.GLSNAME,

            g.GLSTEX,

            g.GLTRS,

            clr.CHEX

        FROM IGC c

        LEFT JOIN GSI gsi ON c.GLASSID = gsi.GLASSID


        LEFT JOIN COLOR clr ON gsi.COLORID = clr.COLORID

        WHERE c.ITEMID = ?

    '''

    components = db.execute(query, (item_id,)).fetchall()

    

    # Map components by COMPNUM (or region identifier) for easy JS lookup

    components_json = {}

    for comp in components:

        # Using COMPNUM as the key to match region IDs in the SVG canvas

        region_key = str(comp['COMPNUM'])

        components_json[region_key] = {

            'COMPID': comp['COMPID'],

            'COMPNUM': comp['COMPNUM'],

            'COMPNAME': comp['COMPNAME'] or '',

            'COMPLEN': comp['COMPLEN'] or 0,

            'COMPWID': comp['COMPWID'] or 0,

            'GLASSID': comp['GLASSID'] or '',

            'GLSNAME': comp['GLSNAME'] or '',

            'GLSTEX': comp['GLSTEX'] or '',

            'GLTRS': comp['GLTRS'] if comp['GLTRS'] is not None else 75, # Fallback to 75 if null

            'CHEX': comp['CHEX'] or 'cccccc',

            'ISSCRAP': comp['ISSCRAP'] or 0,

            'ISGRAIN': comp['ISGRAIN'] or 0

        }

        

    # URL for the SVG file stored in static/svgs/ or similar path based on your app structure

    svg_url = url_for('static', filename=f'svgs/{item["ITMSVG"]}') if 'ITMSVG' in item and item['ITMSVG'] else url_for('static', filename='svgs/default.svg')



    return render_template(

        'edit_components.html',

        item=item,

        glass_options=glass_options,

        components_json=components_json,

        svg_url=svg_url

    )

@app.route('/update_component', methods=['POST'])
def update_component():
    db = get_db()

    comp_id = request.form.get('comp_id')
    item_id = request.form.get('item_id')
    comp_num = request.form.get('comp_num')
    comp_name = request.form.get('comp_name')
    comp_len = request.form.get('comp_len')
    comp_wid = request.form.get('comp_wid')
    glass_id = request.form.get('glass_id') or None
    isscrap = 1 if request.form.get('isscrap') else 0
    isgrain = 1 if request.form.get('isgrain') else 0

    if not comp_id:
        flash('Invalid component selection.', 'danger')
        return redirect(url_for('edit_components', item_id=item_id))

    db.execute('''
        UPDATE IGC 
        SET COMPNUM = ?, COMPNAME = ?, COMPLEN = ?, COMPWID = ?, GLASSID = ?, ISSCRAP = ?, ISGRAIN = ?
        WHERE COMPID = ?
    ''', (comp_num, comp_name, comp_len, comp_wid, glass_id, isscrap, isgrain, comp_id))
    db.commit()

    flash('Component updated successfully!', 'success')
    return redirect(url_for('edit_components', item_id=item_id))


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


@app.route('/test-svg-delete', methods=['GET', 'POST'])

def test_svg_delete():

    """

    Dedicated test page to isolate and verify lxml-based SVG path deletion 

    and sequential renumbering without any database dependencies.

    """

    # Target a specific test file inside your static directory (e.g., 'static/test.svg')

    # Change 'test.svg' to any existing SVG filename in your static folder to test.

    svg_filename = request.args.get('file', 'test.svg')

    svg_path = os.path.join(app.root_path, 'static', svg_filename)



    message = None

    paths_found = []



    if request.method == 'POST':

        target_region_num = request.form.get('region_id')

        print(f"TEST PAGE CONSOLE WRITE ---> Target File: '{svg_path}' | Region to Delete: '{target_region_num}'")



        if not os.path.exists(svg_path):

            message = f"Error: File does not exist at absolute path: {svg_path}"

        else:

            try:

                # 1. Parse using robust XML parser settings

                parser = etree.XMLParser(remove_blank_text=True, recover=True)

                tree = etree.parse(svg_path, parser)

                

                # 2. Use local-name() wildcard to bypass strict or missing namespace prefix issues

                path_elements = tree.xpath('//*[local-name()="path"]')



                removed = False

                for elem in path_elements:

                    region_val = elem.get('data-region-id')

                    elem_id = elem.get('id', '')



                    # Match by data-region-id or ID string format (e.g., 'region-2' or '2')

                    if (region_val and str(region_val).strip() == str(target_region_num)) or (elem_id in [f"region-{target_region_num}", str(target_region_num)]):
                        

                        parent = elem.getparent()

                        if parent is not None:

                            parent.remove(elem)

                            removed = True

                            print(f"TEST SUCCESS: Removed element ID '{elem_id}', data-region-id '{region_val}'")

                        break



                if removed:

                    # 3. Re-fetch remaining paths and re-index attributes sequentially

                    remaining_paths = tree.xpath('//*[local-name()="path"]')

                    for new_idx, elem in enumerate(remaining_paths, start=1):

                        elem.set('id', f'region-{new_idx}')

                        elem.set('data-region-id', str(new_idx))

                        if elem.get('data-number') is not None:

                            elem.set('data-number', str(new_idx))



                    # 4. Explicitly write back out to disk using binary mode

                    root = tree.getroot()

                    xml_bytes = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='utf-8')

                    with open(svg_path, 'wb') as f:

                        f.write(xml_bytes)



                    message = f"Success! Region {target_region_num} deleted and file updated on disk."

                else:

                    message = f"Warning: Could not find any path matching region ID '{target_region_num}' in {svg_filename}."

            except Exception as e:

                message = f"Exception occurred during processing: {str(e)}"

                print(f"TEST EXCEPTION: {e}")



    # Read current state of paths for display on the test interface

    if os.path.exists(svg_path):

        try:

            parser = etree.XMLParser(remove_blank_text=True, recover=True)

            tree = etree.parse(svg_path, parser)

            path_elements = tree.xpath('//*[local-name()="path"]')

            for idx, elem in enumerate(path_elements):

                paths_found.append({

                    'index': idx,

                    'id': elem.get('id', 'N/A'),

                    'data_region_id': elem.get('data-region-id', 'N/A')

                })

        except Exception as e:

            print(f"Error reading paths for test view: {e}")



    # Inline HTML template for quick standalone testing

    html_template = """

    <!doctype html>

    <html lang="en">

    <head>

        <title>SVG Deletion Test Harness</title>

        <style>

            body { font-family: Arial, sans-serif; margin: 40px; background: #f4f4f9; color: #333; }

            .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }

            table { width: 100%; border-collapse: collapse; margin-top: 10px; }

            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }

            th { background-color: #007bff; color: white; }

            .btn { background: #dc3545; color: white; border: none; padding: 6px 12px; cursor: pointer; border-radius: 4px; }

            .btn:hover { background: #c82333; }

            .alert { padding: 10px; background: #e2e3e5; border-left: 5px solid #6c757d; margin-bottom: 15px; }

        </style>

    </head>

    <body>

        <div class="card">

            <h2>SVG Deletion Diagnostic Harness</h2>

            <p>Target File Path: <code>static/{{ filename }}</code></p>

            {% if message %}

                <div class="alert"><strong>Status:</strong> {{ message }}</div>

            {% endif %}

            

            <h3>Paths Currently Inside File:</h3>

            {% if paths %}

                <table>

                    <tr>

                        <th>DOM Index</th>

                        <th>ID Attribute</th>

                        <th>data-region-id</th>

                        <th>Action</th>

                    </tr>

                    {% for p in paths %}

                    <tr>

                        <td>{{ p.index }}</td>

                        <td><code>{{ p.id }}</code></td>

                        <td><code>{{ p.data_region_id }}</code></td>

                        <td>

                            <form method="POST" style="margin: 0;">

                                <input type="hidden" name="region_id" value="{{ p.data_region_id if p.data_region_id != 'N/A' else loop.index }}">

                                <button type="submit" class="btn">Delete This Path</button>

                            </form>

                        </td>

                    </tr>

                    {% endfor %}

                </table>

            {% else %}

                <p style="color: red;">No &lt;path&gt; elements found or file does not exist!</p>

            {% endif %}

        </div>

    </body>

    </html>

    """

    return render_template_string(html_template, filename=svg_filename, message=message, paths=paths_found)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7665, debug=True)
