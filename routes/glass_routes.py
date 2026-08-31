from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import date
from utils import hex_to_hsv, process_and_save_image
from datetime import datetime, date, timedelta

glass_bp = Blueprint('glass_bp', __name__)

def get_db_from_app():
    # Import get_db from your main app context or pass connection handling appropriately
    from __main__ import get_db
    return get_db()

@glass_bp.route('/glass')
def list_glass():
    db = get_db_from_app()

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
    glsiri = request.args.get('glsiri')
    glsopal = request.args.get('glsopal')
    is_active = request.args.get('is_active', '1').strip()

    item_id = request.args.get('item_id', '').strip()
    active_only = request.args.get('active_only', '')

    sql_sort_column = 'g.GLSNAME' if sort_by == 'COLOR_HSV' else {
        'GLSNAME': 'g.GLSNAME',
        'GLSMANF': 'g.GLSMANF',
        'GLSTEX': 'g.GLSTEX',
        'COLOR': 'g.COLOR',
        'GLSOURCE': 'g.GLSOURCE',
        'GLSLEN': 'g.GLSLEN',
        'GLSPRICE': 'p.GLSPRICE'
    }.get(sort_by, 'g.GLSNAME')

    where_clauses = []
    params = []

    if is_active != 'all':
        where_clauses.append("g.ISACTIVE = ?")
        params.append(1 if is_active == '1' else 0)

    iri_op_clauses = []
    if glsiri == '1':
        iri_op_clauses.append("g.GLSIRI = 1")
    if glsopal == '1':
        iri_op_clauses.append("g.GLSOPAL = 1")
    if iri_op_clauses:
        where_clauses.append(f"({' OR '.join(iri_op_clauses)})")

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

    join_igc = ""
    if item_id:
        join_igc = "INNER JOIN IGC c ON g.GLASSID = c.GLASSID"
        where_clauses.append("c.ITEMID = ?")
        params.append(item_id)
        
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    query = f"""
        SELECT DISTINCT g.*, p.GLSPRICE, c.CHEX
        FROM GSI g
        LEFT JOIN (
            SELECT GLASSID, GLSPRICE 
            FROM GPC 
            WHERE ENDDATE IS NULL OR ENDDATE >= DATE('now')
        ) p ON g.GLASSID = p.GLASSID
        LEFT JOIN COLOR c ON g.COLOR = c.COLOR
        {join_igc}
        {where_sql}
        ORDER BY {sql_sort_column} {order.upper()}
    """
    raw_glasses = db.execute(query, params).fetchall()

    glasses = []
    for row in raw_glasses:
        item_dict = dict(row)
        hex_val = item_dict.get('CHEX')
        combined_val = hex_to_hsv(hex_val) if hex_val else 999999.0
        item_dict['COLOR_HSV'] = combined_val
        glasses.append(item_dict)

    if sort_by == 'COLOR_HSV':
        def color_sort_key(x):
            val = x['COLOR_HSV']
            if val >= 999999.0:
                return (1, 1.0, 0, val)
            h = val // 1000
            rem = val % 1000
            s = rem // 100
            v = rem % 100
            is_greyscale = 1 if s < 0.05 else 0
            return (is_greyscale, -v if is_greyscale else h, s, v)

        glasses.sort(key=color_sort_key, reverse=(order == 'desc'))

    textures = db.execute("SELECT DISTINCT GLSTEX FROM GSI WHERE ISACTIVE = 1 AND GLSTEX IS NOT NULL AND GLSTEX != '' ORDER BY GLSTEX").fetchall()
    raw_colors = db.execute("SELECT * FROM COLOR").fetchall()
    
    colors = []
    for col in raw_colors:
        c_dict = dict(col)
        hex_val = c_dict.get('CHEX')
        combined_val = hex_to_hsv(hex_val) if hex_val else 999999.0
        h = combined_val // 1000
        rem = combined_val % 1000
        s = rem // 100
        v = rem % 100
        c_dict['COLOR_HSV'] = combined_val
        c_dict['_sort_key'] = (1 if s < 0.05 else 0, -v if s < 0.05 else h, s, v)
        colors.append(c_dict)
    colors.sort(key=lambda x: x['_sort_key'])

    sources = db.execute("SELECT DISTINCT GLSOURCE FROM GSI WHERE ISACTIVE = 1 AND GLSOURCE IS NOT NULL AND GLSOURCE != '' ORDER BY GLSOURCE").fetchall()
    manufacturers = db.execute("SELECT DISTINCT GLSMANF FROM GSI WHERE ISACTIVE = 1 AND GLSMANF IS NOT NULL AND GLSMANF != '' ORDER BY GLSMANF").fetchall()

    item_where = "WHERE i.ISACTIVE = 1" if active_only == '1' else ""
    items_query = f"""
        SELECT i.ITEMID, i.ITMNAME, i.ISACTIVE, i.CURRENT, g.ITMGRP,
               COALESCE(NULLIF(g.ITMGRP, ''), i.ITMNAME) AS group_or_name
        FROM ITM i
        LEFT JOIN IGP g ON i.ITMGRP = g.ITMGRP
        {item_where}
        ORDER BY group_or_name ASC, i.ITMNAME ASC
    """
    items = db.execute(items_query).fetchall()

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
            'q': q, 'manf': manf, 'tex': tex, 'color': color, 'source': source,
            'min_price': min_price, 'max_price': max_price, 'is_active': is_active,
            'item_id': item_id, 'item_name': item_name, 'active_only': active_only,
            'glsiri': glsiri, 'glsopal': glsopal
        }
    )

@glass_bp.route("/glass/new", methods=["GET", "POST"])
def create_glass():
    db = get_db_from_app()
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
                GLSLEN, GLSWID, GLSTHK, GLSIRI, GLSOPAL, GLLINK, 
                GLSIMG, GLSNOTE, ISACTIVE)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (glsname, glsmanf, glstex, gtrnsn, color, glsource, glslen,
             glswid, glsthk, glsiri, glsopal, gllink, glsimg, glsnote, isactive),
        )

        glass_id = cursor.lastrowid
        file = request.files.get("GLSIMG_FILE")
        if file and file.filename != '':
            pattern_name = f"{glass_id}_{glsname}"
            glsimg_path = process_and_save_image(
                file_obj=file,
                upload_subfolder='images/glass',
                custom_filename_base=pattern_name,
                target_size=(512, 512)
            )
            db.execute("UPDATE GSI SET GLSIMG = ? WHERE GLASSID = ?", (glsimg_path, glass_id))

        if price:
            db.execute(
                "INSERT INTO GPC (GLASSID, GLSPRICE, STDATE) VALUES (?, ?, DATE('now'))",
                (glass_id, price),
            )

        db.commit()
        flash("Glass sheet recorded successfully!", "success")
        return redirect(url_for("glass_bp.list_glass"))

    textures = db.execute("SELECT * FROM GTL").fetchall()
    colors = db.execute("SELECT * FROM COLOR").fetchall()
    sources = db.execute("SELECT * FROM GSL").fetchall()
    transparency = db.execute("SELECT * FROM GTRNS").fetchall()
    return render_template(
        "glass_form.html", textures=textures, transparency=transparency, colors=colors, sources=sources
    )

@glass_bp.route('/glass/<int:glass_id>', methods=['GET', 'POST'])

def glass_detail(glass_id):
    db = get_db_from_app()
    
    # Handle stock adjustment submission on the same page
    if request.method == 'POST':
        glsstock = request.form.get('GLSSTOCK')
        ts = request.form.get('TS', date.today().isoformat())
        
        if glsstock is not None:
            try:
                db.execute('''
                    INSERT INTO GLSINV (GLASSID, GLSSTOCK, TS)
                    VALUES (?, ?, ?)
                ''', (glass_id, int(glsstock), ts))
                db.commit()
                flash('Stock level updated successfully!', 'success')
            except Exception as e:
                db.rollback()
                flash(f'Error updating stock: {e}', 'danger')
                
        return redirect(url_for('glass_bp.glass_detail', glass_id=glass_id))

    glass = db.execute('''
        SELECT g.*, p.GLSPRICE, s.SRCWEB, s.GLSLOGO, c.CHEX,
               COALESCE((
                   SELECT i.GLSSTOCK FROM GLSINV i 
                   WHERE i.GLASSID = g.GLASSID 
                   ORDER BY i.TS DESC, i.GLSTRNID DESC LIMIT 1
               ), 0) AS CURRENT_STOCK
        FROM GSI g
        LEFT JOIN GPC p ON g.GLASSID = p.GLASSID
        LEFT JOIN GSL s ON g.GLSOURCE = s.GLSOURCE
        LEFT JOIN COLOR c ON g.COLOR = c.COLOR
        WHERE g.GLASSID = ?
    ''', (glass_id,)).fetchone()

    if not glass:
        flash('Glass sheet record not found.', 'danger')
        return redirect(url_for('glass_bp.list_glass'))

    components = db.execute('''
        SELECT c.*, i.ITMNAME 
        FROM IGC c
        JOIN ITM i ON c.ITEMID = i.ITEMID
        WHERE c.GLASSID = ?
    ''', (glass_id,)).fetchall()
    return render_template('glass_detail.html', glass=glass, components=components, today_date=date.today().isoformat())


@glass_bp.route('/glass/edit/<int:glass_id>', methods=['GET', 'POST'])
def edit_glass(glass_id):
    db = get_db_from_app()
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
        return redirect(url_for('glass_bp.list_glass'))

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

        file = request.files.get('GLSIMG_FILE')
        if file and file.filename != '':
            pattern_name = f"{glass_id}_{glsname}"
            glsimg = process_and_save_image(
                file_obj=file,
                upload_subfolder='images/glass',
                custom_filename_base=pattern_name,
                target_size=(512, 512)
            )
        else:
            glsimg = request.form.get('GLSIMG') or glass['GLSIMG']

        db.execute(
            '''
            UPDATE GSI 
            SET GLSNAME = ?, GLSMANF = ?, GLSTEX = ?, GTRNSN = ?, COLOR = ?, GLSOURCE = ?, 
                GLSLEN = ?, GLSWID = ?, GLSTHK = ?, GLSIRI = ?, 
                GLSOPAL = ?, GLLINK = ?, GLSIMG = ?, GLSNOTE = ?
            WHERE GLASSID = ?
            ''',
            (glsname, glsmanf, glstex, gtrnsn, color, glsource, glslen, glswid,
             glsthk, glsiri, glsopal, gllink, glsimg, glsnote, glass_id),
        )

        if price:
            existing_price = db.execute('SELECT * FROM GPC WHERE GLASSID = ?', (glass_id,)).fetchone()
            if existing_price:
                db.execute('UPDATE GPC SET GLSPRICE = ?, STDATE = DATE(\'now\') WHERE GLASSID = ?', (price, glass_id))
            else:
                db.execute('INSERT INTO GPC (GLASSID, GLSPRICE, STDATE) VALUES (?, ?, DATE(\'now\'))', (glass_id, price))

        db.commit()
        flash('Glass details updated successfully!', 'success')
        return redirect(url_for('glass_bp.glass_detail', glass_id=glass_id))

    textures = db.execute('SELECT * FROM GTL').fetchall()
    transparency = db.execute('SELECT * FROM GTRNS').fetchall()
    colors = db.execute('SELECT * FROM COLOR').fetchall()
    sources = db.execute('SELECT * FROM GSL').fetchall()

    return render_template(
        'glass_form.html', glass=glass, textures=textures,
        transparency=transparency, colors=colors, sources=sources, action='Edit'
    )

@glass_bp.route('/glass/delete/<int:glass_id>', methods=['POST'])
def delete_glass(glass_id):
    db = get_db_from_app()
    db.execute("UPDATE GSI SET ISACTIVE = 0 WHERE GLASSID = ?", (glass_id,))
    db.commit()
    flash(f"Glass sheet #{glass_id} deactivated successfully.", "warning")
    return redirect(url_for('glass_bp.list_glass'))

@glass_bp.route('/glass/inventory', methods=['GET', 'POST'])
def glass_inventory():
    db = get_db_from_app()

    if request.method == 'POST':
        glass_id = request.form.get('GLASSID')
        adjustment = request.form.get('GLSSTOCK')
        trans_date = request.form.get('TS') or date.today().isoformat()

        if glass_id and adjustment:
            db.execute(
                "INSERT INTO GLSINV (GLASSID, GLSSTOCK, TS) VALUES (?, ?, ?)",
                (glass_id, int(adjustment), trans_date)
            )
            db.commit()
            flash("Inventory level adjusted successfully!", "success")
        else:
            flash("Invalid input parameters for stock adjustment.", "danger")
            
        return redirect(url_for('glass_bp.glass_inventory'))

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
    is_active = request.args.get('is_active', '1').strip()
    online_only = 1 if request.args.get('online_only') == '1' else 0

    item_id = request.args.get('item_id', '').strip()
    active_only = request.args.get('active_only', '')

    sql_sort_column = 'GLSNAME' if sort_by == 'COLOR_HSV' else {
        'GLASSID': 'GLASSID', 'GLSNAME': 'GLSNAME', 'GLSMANF': 'GLSMANF',
        'GLSTEX': 'GLSTEX', 'COLOR': 'COLOR', 'GLSIRI': 'GLSIRI',
        'GLSOPAL': 'GLSOPAL', 'GLSLEN': 'GLSLEN', 'CURRENT_STOCK': 'CURRENT_STOCK',
        'LAST_UPDATED': 'LAST_UPDATED'
    }.get(sort_by, 'GLSNAME')

    where_clauses = []
    params = [1 if is_active == '1' else 0] if is_active != 'all' else []
    
    if is_active != 'all':
        where_clauses.append("g.ISACTIVE = ?")

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
    if online_only:
        where_clauses.append("(l.SRCWEB = 1 AND (g.GLLINK IS NOT NULL AND g.GLLINK != ''))")

    join_igc = ""
    if item_id:
        join_igc = "INNER JOIN IGC c_item ON g.GLASSID = c_item.GLASSID"
        where_clauses.append("c_item.ITEMID = ?")
        params.append(item_id)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

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

    stock_having_sql = f"GROUP BY GLASSID HAVING {' AND '.join(having_conditions)}" if having_conditions else ""

    query = f"""
        SELECT DISTINCT GLASSID, GLSNAME, GLSMANF, GLSLEN, GLSWID, GLSTHK, GLSTEX, 
               GLSIRI, GLSOPAL, GLSOURCE, GLLINK, GLSIMG, GLSNOTE, COLOR, 
               ISACTIVE, CHEX, GLSPRICE, SRCWEB, CURRENT_STOCK, LAST_UPDATED
        FROM (
            SELECT g.GLASSID, g.GLSNAME, g.GLSMANF, g.GLSLEN, g.GLSWID, g.GLSTHK, 
                   g.GLSTEX, g.GLSIRI, g.GLSOPAL, g.GLSOURCE, g.GLLINK, g.GLSIMG, 
                   g.GLSNOTE, g.COLOR, g.ISACTIVE, c.CHEX, p.GLSPRICE, l.SRCWEB,
                   COALESCE((
                       SELECT i.GLSSTOCK FROM GLSINV i 
                       WHERE i.GLASSID = g.GLASSID 
                       ORDER BY i.TS DESC, i.GLSTRNID DESC LIMIT 1
                   ), 0) AS CURRENT_STOCK,
                   (
                       SELECT i.TS FROM GLSINV i 
                       WHERE i.GLASSID = g.GLASSID 
                       ORDER BY i.TS DESC, i.GLSTRNID DESC LIMIT 1
                   ) AS LAST_UPDATED
            FROM GSI g
            LEFT JOIN COLOR c ON g.COLOR = c.COLOR
            LEFT JOIN (
                SELECT GLASSID, GLSPRICE 
                FROM GPC 
                WHERE ENDDATE IS NULL OR ENDDATE >= DATE('now')
            ) p ON g.GLASSID = p.GLASSID
            LEFT JOIN GSL l ON g.GLSOURCE = l.GLSOURCE
            {join_igc}
            {where_sql}
        ) sub
        {stock_having_sql}
        ORDER BY {sql_sort_column} {order.upper()}
    """
    raw_items = db.execute(query, params).fetchall()

    inventory_items = []
    for row in raw_items:
        item = dict(row)
        item['COLOR_HSV'] = hex_to_hsv(item.get('CHEX'))
        inventory_items.append(item)

    if sort_by == 'COLOR_HSV':

        def color_sort_key(x):
            val = x['COLOR_HSV']
            if val >= 999999.0:
                return (1, 1.0, 0, val)
            h = val // 1000
            rem = val % 1000
            s = rem // 100
            v = rem % 100
            is_greyscale = 1 if s < 0.05 else 0
            return (is_greyscale, -v if is_greyscale else h, s, v)

        inventory_items.sort(key=color_sort_key, reverse=(order == 'desc'))


    textures = db.execute("SELECT DISTINCT GLSTEX FROM GSI WHERE ISACTIVE = 1 AND GLSTEX IS NOT NULL AND GLSTEX != '' ORDER BY GLSTEX").fetchall()
    raw_colors = db.execute("SELECT * FROM COLOR").fetchall()
    
    colors = []
    for col in raw_colors:
        c_dict = dict(col)
        hex_val = c_dict.get('CHEX')
        combined_val = hex_to_hsv(hex_val) if hex_val else 999999.0
        h = combined_val // 1000
        rem = combined_val % 1000
        s = rem // 100
        v = rem % 100
        c_dict['COLOR_HSV'] = combined_val
        c_dict['_sort_key'] = (1 if s < 0.05 else 0, -v if s < 0.05 else h, s, v)
        colors.append(c_dict)
    colors.sort(key=lambda x: x['_sort_key'])

    sources = db.execute("SELECT DISTINCT GLSOURCE FROM GSI WHERE ISACTIVE = 1 AND GLSOURCE IS NOT NULL AND GLSOURCE != '' ORDER BY GLSOURCE").fetchall()
    manufacturers = db.execute("SELECT DISTINCT GLSMANF FROM GSI WHERE ISACTIVE = 1 AND GLSMANF IS NOT NULL AND GLSMANF != '' ORDER BY GLSMANF").fetchall()
    iridescent_options = db.execute("SELECT DISTINCT GLSIRI FROM GSI WHERE ISACTIVE = 1 AND GLSIRI = 1").fetchall()
    opalescent_options = db.execute("SELECT DISTINCT GLSOPAL FROM GSI WHERE ISACTIVE = 1 AND GLSOPAL = 1").fetchall()

    item_where = "WHERE i.ISACTIVE = 1" if active_only == '1' else ""
    items_query = f"""
        SELECT i.ITEMID, i.ITMNAME, i.ISACTIVE, i.CURRENT, g.ITMGRP,
               COALESCE(NULLIF(g.ITMGRP, ''), i.ITMNAME) AS group_or_name
        FROM ITM i
        LEFT JOIN IGP g ON i.ITMGRP = g.ITMGRP
        {item_where}
        ORDER BY group_or_name ASC, i.ITMNAME ASC
    """
    items = db.execute(items_query).fetchall()

    item_name = ""
    if item_id:
        for itm in items:
            if str(itm['ITEMID']) == str(item_id):
                item_name = itm['ITMNAME']
                break

    return render_template(
        'glass_inventory.html',
        inventory_items=inventory_items, textures=textures, colors=colors,
        sources=sources, manufacturers=manufacturers, iridescent_options=iridescent_options,
        opalescent_options=opalescent_options, items=items, current_sort=sort_by,
        current_order=order, today_date=date.today().isoformat(),
        filters={
            'q': request.args.get('q', ''), 'manf': request.args.get('manf', ''),
            'tex': request.args.get('tex', ''), 'color': color, 'source': source,
            'min_price': request.args.get('min_price', ''), 'max_price': request.args.get('max_price', ''),
            'stock_filter': request.args.get('stock_filter', ''), 'stock_display': stock_display_mode,
            'iridescent': request.args.get('iridescent', ''), 'opalescent': request.args.get('opalescent', ''),
            'online_only': online_only, 'is_active': is_active, 'item_id': item_id,
            'item_name': item_name, 'active_only': active_only
        }
    )

@glass_bp.route('/glass/<int:glass_id>/history')

def glass_price_history(glass_id):

    """Display historical price list for glass in descending order with calculated price changes and durations."""
    db = get_db_from_app()
    glass = db.execute(
        'SELECT * FROM GSI WHERE GLASSID = ?', (glass_id,)
    ).fetchone()

    if not glass:
        flash('Glass sheet record not found.', 'danger')
        return redirect(url_for('glass_bp.list_glass'))

    # Fetch all prices ordered chronologically ascending to compute deltas and durations easily
    rows = db.execute(
        """
        SELECT rowid, GLSPRICE, STDATE, ENDDATE FROM GPC 
        WHERE GLASSID = ? 
        ORDER BY STDATE ASC
        """,
        (glass_id,),
    ).fetchall()

    history_processed = []
    prev_price = None

    for row in rows:
        price = row['GLSPRICE']
        change = price - prev_price if prev_price is not None else None
        prev_price = price

        # Calculate duration
        start_dt = (
            datetime.strptime(row['STDATE'], '%Y-%m-%d').date()
            if row['STDATE']
            else None
        )
        end_dt = (
            datetime.strptime(row['ENDDATE'], '%Y-%m-%d').date()
            if row['ENDDATE']
            else date.today()
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
            'GLSPRICE': price,
            'change': change,
            'STDATE': row['STDATE'],
            'ENDDATE': row['ENDDATE'],
            'duration_str': duration_str,
        })

    # Reverse to have descending order starting from present
    history_processed.reverse()

    return render_template(
        'glass_price_history.html', glass=glass, history=history_processed
    )


@glass_bp.route('/prices/glass/<int:glass_id>/edit', methods=['GET', 'POST'])
def edit_glass_prices(glass_id):
    """Manage and insert glass prices with automated date shuffling and interval overlap adjustments."""
    db = get_db_from_app()
    glass = db.execute(
        'SELECT * FROM GSI WHERE GLASSID = ?', (glass_id,)
    ).fetchone()

    if not glass:
        flash('Glass sheet record not found.', 'danger')
        return redirect(url_for('glass_bp.list_glass'))

    if request.method == 'POST':
        try:
            new_price = float(request.form.get('GLSPRICE'))
        except (TypeError, ValueError):
            flash('Invalid price value provided.', 'danger')
            return redirect(url_for('glass_bp.edit_glass_prices', glass_id=glass_id))

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
            return redirect(url_for('glass_bp.edit_glass_prices', glass_id=glass_id))

        cursor = db.cursor()

        # Fetch existing price intervals for this glass item
        existing_prices = cursor.execute(
            """
            SELECT rowid, GLSPRICE, STDATE, ENDDATE FROM GPC 
            WHERE GLASSID = ?
            """,
            (glass_id,),
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
                cursor.execute('DELETE FROM GPC WHERE rowid = ?', (row_id,))
                continue

            # Case B: New range is completely inside an existing range -> Split the existing range into two
            if ex_st and ex_end and new_st > ex_st and new_end and new_end < ex_end:
                split_end_date = (new_st - timedelta(days=1)).strftime('%Y-%m-%d')
                cursor.execute(
                    'UPDATE GPC SET ENDDATE = ? WHERE rowid = ?',
                    (split_end_date, row_id)
                )
                tail_start_date = (new_end + timedelta(days=1)).strftime('%Y-%m-%d')
                cursor.execute(
                    'INSERT INTO GPC (GLASSID, GLSPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, ?)',
                    (glass_id, row['GLSPRICE'], tail_start_date, ex_end_str)
                )
                continue

            # Case C: Overlap on the tail end of existing range
            if ex_st and new_st > ex_st and (ex_end is None or new_st <= ex_end):
                new_ex_end = (new_st - timedelta(days=1)).strftime('%Y-%m-%d')
                cursor.execute(
                    'UPDATE GPC SET ENDDATE = ? WHERE rowid = ?',
                    (new_ex_end, row_id)
                )

            # Case D: Overlap on the front end of existing range
            if new_end and ex_end and new_end >= ex_st and new_end < ex_end:
                new_ex_st = (new_end + timedelta(days=1)).strftime('%Y-%m-%d')
                cursor.execute(
                    'UPDATE GPC SET STDATE = ? WHERE rowid = ?',
                    (new_ex_st, row_id)
                )

            # Case E: If new range is ongoing (current), truncate any old ranges that overlap forward
            if is_current and ex_st and ex_st >= new_st:
                cursor.execute('DELETE FROM GPC WHERE rowid = ?', (row_id,))

        # Insert the new price record cleanly
        cursor.execute(
            """
            INSERT INTO GPC (GLASSID, GLSPRICE, STDATE, ENDDATE)
            VALUES (?, ?, ?, ?)
            """,
            (glass_id, new_price, new_st_str, new_end_str),
        )

        db.commit()
        flash('Glass price range successfully saved and overlapping intervals adjusted.', 'success')
        return redirect(url_for('glass_bp.edit_glass_prices', glass_id=glass_id))

    # GET Request: fetch all price rows ordered by start date descending
    prices = db.execute(
        """
        SELECT rowid, GLSPRICE, STDATE, ENDDATE FROM GPC 
        WHERE GLASSID = ? 
        ORDER BY STDATE DESC
        """,
        (glass_id,),
    ).fetchall()

    return render_template(
        'glass_edit_prices.html', glass=glass, prices=prices
    )

@glass_bp.route('/prices/glass/<int:glass_id>/delete/<int:price_id>', methods=['POST'])

def delete_glass_price(glass_id, price_id):
    """Delete a specific glass price entry row."""
    db = get_db_from_app()
    db.execute('DELETE FROM GPC WHERE rowid = ? AND GLASSID = ?', (price_id, glass_id))
    db.commit()
    flash('Glass price tier removed.', 'success')
    return redirect(url_for('glass_bp.edit_glass_prices', glass_id=glass_id))

@glass_bp.route('/glass/bulk-adjustment', methods=['GET', 'POST'])

def bulk_inventory_adjustment():

    db = get_db_from_app()

    

    if request.is_json or request.method == 'POST' and request.headers.get('Content-Type') == 'application/json':

        data = request.get_json()

        adjust_date = data.get('date', date.today().isoformat())

        items = data.get('items', [])

        

        try:

            from datetime import datetime, timedelta

            adjust_dt = datetime.strptime(adjust_date, '%Y-%m-%d')

            prev_day = (adjust_dt - timedelta(days=1)).strftime('%Y-%m-%d')



            for item in items:

                glass_id = item.get('GLASSID')

                stock = item.get('stock')

                price = item.get('price')

                

                if glass_id is not None:

                    # 1. Update stock if provided

                    if stock is not None:

                        db.execute(

                            "INSERT INTO GLSINV (GLASSID, GLSSTOCK, TS) VALUES (?, ?, ?)",

                            (glass_id, int(stock), adjust_date)

                        )

                    

                    # 2. Update price using date-shuffling logic

                    if price is not None and price != '':

                        new_price = float(price)

                        

                        # Check if a price already exists starting exactly on this date

                        exact_match = db.execute(

                            "SELECT rowid FROM GPC WHERE GLASSID = ? AND STDATE = ?", 

                            (glass_id, adjust_date)

                        ).fetchone()

                        

                        if exact_match:

                            # Just update the price for this exact date to avoid duplicates

                            db.execute(

                                "UPDATE GPC SET GLSPRICE = ? WHERE rowid = ?",

                                (new_price, exact_match['rowid'])

                            )

                        else:

                            # Find the chronologically NEXT interval to determine our new end date

                            next_price = db.execute(

                                "SELECT STDATE FROM GPC WHERE GLASSID = ? AND STDATE > ? ORDER BY STDATE ASC LIMIT 1",

                                (glass_id, adjust_date)

                            ).fetchone()

                            

                            new_end_date = None

                            if next_price and next_price['STDATE']:

                                next_st_dt = datetime.strptime(next_price['STDATE'], '%Y-%m-%d')

                                new_end_date = (next_st_dt - timedelta(days=1)).strftime('%Y-%m-%d')

                            

                            # Find the chronologically PREVIOUS interval to cap its end date

                            prev_price = db.execute(

                                "SELECT rowid, ENDDATE FROM GPC WHERE GLASSID = ? AND STDATE < ? ORDER BY STDATE DESC LIMIT 1",

                                (glass_id, adjust_date)

                            ).fetchone()

                            

                            if prev_price:

                                prev_end_date = prev_price['ENDDATE']

                                # If the previous price is ongoing or overlaps our new date, cap it to the day before

                                if not prev_end_date or prev_end_date >= adjust_date:

                                    db.execute(

                                        "UPDATE GPC SET ENDDATE = ? WHERE rowid = ?",

                                        (prev_day, prev_price['rowid'])

                                    )

                            

                            # Insert the new price interval

                            db.execute(

                                "INSERT INTO GPC (GLASSID, GLSPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, ?)",

                                (glass_id, new_price, adjust_date, new_end_date)

                            )

                        

            db.commit()

            return {"status": "success", "message": "Bulk adjustments and price tiers saved successfully!"}, 200

        except Exception as e:

            db.rollback()

            return {"status": "error", "message": str(e)}, 400



    sources = db.execute("SELECT DISTINCT GLSOURCE FROM GSI WHERE ISACTIVE = 1 AND GLSOURCE IS NOT NULL AND GLSOURCE != '' ORDER BY GLSOURCE").fetchall()

    

    return render_template(

        'glass_bulk_adjustment.html',

        sources=sources,

        today_date=date.today().isoformat()

    )

@glass_bp.route('/glass/api/by-source', methods=['GET'])

def api_glass_by_source():

    db = get_db_from_app()

    source = request.args.get('source', '').strip()

    

    if not source:

        return {"items": []}, 200

        

    query = """

        SELECT g.GLASSID, g.GLSNAME, g.GLSMANF, g.GLSLEN, g.GLSWID, g.GLSTEX, 

               g.GLSOURCE, g.GLSIMG, g.COLOR, c.CHEX, p.GLSPRICE,

               COALESCE((

                   SELECT i.GLSSTOCK FROM GLSINV i 

                   WHERE i.GLASSID = g.GLASSID 

                   ORDER BY i.TS DESC, i.GLSTRNID DESC LIMIT 1

               ), 0) AS CURRENT_STOCK

        FROM GSI g

        LEFT JOIN COLOR c ON g.COLOR = c.COLOR

        LEFT JOIN (

            SELECT GLASSID, GLSPRICE 

            FROM GPC 

            WHERE ENDDATE IS NULL OR ENDDATE >= DATE('now')

        ) p ON g.GLASSID = p.GLASSID

        WHERE g.ISACTIVE = 1 AND g.GLSOURCE = ?

        ORDER BY g.GLSNAME ASC

    """

    raw_items = db.execute(query, (source,)).fetchall()

    

    items = []

    for row in raw_items:

        item = dict(row)

        hex_val = item.get('CHEX')

        combined_val = hex_to_hsv(hex_val) if hex_val else 999999.0

        item['COLOR_HSV'] = combined_val

        items.append(item)

        

    return {"items": items}, 200
