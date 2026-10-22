from flask import render_template, request, redirect, url_for, flash
from datetime import date
from utils import hex_to_hsv, process_and_save_image
import sqlite3

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_crud_routes(bp):
    @bp.route('/glass')
    def list_glass():
        db = get_db()
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
            'GLSNAME': 'g.GLSNAME', 'GLSMANF': 'g.GLSMANF', 'GLSTEX': 'g.GLSTEX',
            'COLOR': 'g.COLOR', 'GLSOURCE': 'g.GLSOURCE', 'GLSLEN': 'g.GLSLEN', 'GLSPRICE': 'p.GLSPRICE'
        }.get(sort_by, 'g.GLSNAME')

        where_clauses, params = [], []
        if is_active != 'all':
            where_clauses.append("g.ISACTIVE = ?")
            params.append(1 if is_active == '1' else 0)
        
        iri_op_clauses = []
        if glsiri == '1': iri_op_clauses.append("g.GLSIRI = 1")
        if glsopal == '1': iri_op_clauses.append("g.GLSOPAL = 1")
        if iri_op_clauses:
            where_clauses.append(f"({' OR '.join(iri_op_clauses)})")
        if q:
            where_clauses.append("(g.GLSNAME LIKE ? OR g.GLSMANF LIKE ? OR g.GLSNOTE LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
        if manf: where_clauses.append("g.GLSMANF = ?"); params.append(manf)
        if tex: where_clauses.append("g.GLSTEX = ?"); params.append(tex)
        if color: where_clauses.append("g.COLOR = ?"); params.append(color)
        if source: where_clauses.append("g.GLSOURCE = ?"); params.append(source)
        if min_price: where_clauses.append("p.GLSPRICE >= ?"); params.append(min_price)
        if max_price: where_clauses.append("p.GLSPRICE <= ?"); params.append(max_price)

        join_igc = ""
        if item_id:
            join_igc = "INNER JOIN IGC c ON g.GLASSID = c.GLASSID"
            where_clauses.append("c.ITEMID = ?")
            params.append(item_id)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query = f"""
            SELECT DISTINCT g.*, p.GLSPRICE, c.CHEX
            FROM GSI g
            LEFT JOIN (SELECT GLASSID, GLSPRICE FROM GPC WHERE ENDDATE IS NULL OR ENDDATE >= DATE('now')) p ON g.GLASSID = p.GLASSID
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
            item_dict['COLOR_HSV'] = hex_to_hsv(hex_val) if hex_val else 999999.0
            glasses.append(item_dict)

        if sort_by == 'COLOR_HSV':
            def color_sort_key(x):
                val = x.get('COLOR_HSV')
                if val is None: return (1, 1.0, 0, 0)
                if isinstance(val, tuple):
                    h, s, v = val[:3] if len(val) >= 3 else (0, 0, 0)
                    return (1 if s < 0.05 else 0, -v if s < 0.05 else h, s, v)
                if val >= 999999.0: return (1, 1.0, 0, val)
                h, rem = divmod(val, 1000)
                s, v = divmod(rem, 100)
                is_greyscale = 1 if s < 0.05 else 0
                return (is_greyscale, -v if is_greyscale else h, s, v)
            glasses.sort(key=color_sort_key, reverse=(order == 'desc'))

        textures = db.execute("SELECT DISTINCT GLSTEX FROM GSI WHERE ISACTIVE = 1 AND GLSTEX IS NOT NULL AND GLSTEX != '' ORDER BY GLSTEX").fetchall()
        raw_colors = db.execute("SELECT * FROM COLOR").fetchall()
        colors = []
        for col in raw_colors:
            c_dict = dict(col)
            combined_val = hex_to_hsv(c_dict.get('CHEX')) if c_dict.get('CHEX') else 999999.0
            h, rem = divmod(combined_val, 1000)
            s, v = divmod(rem, 100)
            c_dict['COLOR_HSV'] = combined_val
            c_dict['_sort_key'] = (1 if s < 0.05 else 0, -v if s < 0.05 else h, s, v)
            colors.append(c_dict)
        colors.sort(key=lambda x: x['_sort_key'])

        sources = db.execute("SELECT DISTINCT GLSOURCE FROM GSI WHERE ISACTIVE = 1 AND GLSOURCE IS NOT NULL AND GLSOURCE != '' ORDER BY GLSOURCE").fetchall()
        manufacturers = db.execute("SELECT DISTINCT GLSMANF FROM GSI WHERE ISACTIVE = 1 AND GLSMANF IS NOT NULL AND GLSMANF != '' ORDER BY GLSMANF").fetchall()
        items = db.execute(f"SELECT i.ITEMID, i.ITMNAME, i.ISACTIVE, i.CURRENT, g.ITMGRP, COALESCE(NULLIF(g.ITMGRP, ''), i.ITMNAME) AS group_or_name FROM ITM i LEFT JOIN IGP g ON i.ITMGRP = g.ITMGRP {'WHERE i.ISACTIVE = 1' if active_only == '1' else ''} ORDER BY group_or_name ASC, i.ITMNAME ASC").fetchall()
        
        item_name = next((itm['ITMNAME'] for itm in items if str(itm['ITEMID']) == str(item_id)), "") if item_id else ""

        return render_template(
            'glass_list.html', glasses=glasses, textures=textures, colors=colors,
            sources=sources, manufacturers=manufacturers, items=items, current_sort=sort_by,
            current_order=order, filters={
                'q': q, 'manf': manf, 'tex': tex, 'color': color, 'source': source,
                'min_price': min_price, 'max_price': max_price, 'is_active': is_active,
                'item_id': item_id, 'item_name': item_name, 'active_only': active_only,
                'glsiri': glsiri, 'glsopal': glsopal
            }
        )

    @bp.route("/glass/new", methods=["GET", "POST"])
    def create_glass():
        db = get_db()
        if request.method == "POST":
            glsname, glsmanf = request.form.get('GLSNAME'), request.form.get('GLSMANF')
            glstex = request.form.get('GLSTEX') or None
            gtrnsn = request.form.get('GTRNSN') or None
            color = request.form.get('COLOR') or None
            glsource = request.form.get('GLSOURCE') or None
            glslen, glswid, glsthk = request.form.get('GLSLEN') or None, request.form.get('GLSWID') or None, request.form.get('GLSTHK') or None
            glsiri = 1 if request.form.get('GLSIRI') else 0
            glsopal = 1 if request.form.get('GLSOPAL') else 0
            gllink = request.form.get('GLLINK') or None
            glsimg, glsnote = request.form.get('GLSIMG'), request.form.get('GLSNOTE')
            price = request.form.get('GLSPRICE')
            lowstock = request.form.get('LOWSTOCK') or None

            cursor = db.execute('''
                INSERT INTO GSI (GLSNAME, GLSMANF, GLSTEX, GTRNSN, COLOR, GLSOURCE, GLSLEN, GLSWID, GLSTHK, GLSIRI, GLSOPAL, GLLINK, GLSIMG, GLSNOTE, LOWSTOCK, ISACTIVE)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
            ''', (glsname, glsmanf, glstex, gtrnsn, color, glsource, glslen, glswid, glsthk, glsiri, glsopal, gllink, glsimg, glsnote, lowstock))
            glass_id = cursor.lastrowid

            file = request.files.get("GLSIMG_FILE")
            if file and file.filename != '':
                glsimg_path = process_and_save_image(file_obj=file, upload_subfolder='images/glass', custom_filename_base=f"{glass_id}_{glsname}", target_size=(512, 512))
                db.execute("UPDATE GSI SET GLSIMG = ? WHERE GLASSID = ?", (glsimg_path, glass_id))
            if price:
                db.execute("INSERT INTO GPC (GLASSID, GLSPRICE, STDATE) VALUES (?, ?, DATE('now'))", (glass_id, price))
            db.commit()
            flash("Glass sheet recorded successfully!", "success")
            return redirect(url_for("glass_bp.list_glass"))

        return render_template("glass_form.html", textures=db.execute("SELECT * FROM GTL").fetchall(), transparency=db.execute("SELECT * FROM GTRNS").fetchall(), colors=db.execute("SELECT * FROM COLOR").fetchall(), sources=db.execute("SELECT * FROM GSL").fetchall())

    @bp.route('/glass/<int:glass_id>', methods=['GET', 'POST'])
    def glass_detail(glass_id):
        db = get_db()
        if request.method == 'POST':
            glsstock, ts = request.form.get('GLSSTOCK'), request.form.get('TS', date.today().isoformat())
            if glsstock is not None:
                try:
                    db.execute('INSERT INTO GLSINV (GLASSID, GLSSTOCK, TS) VALUES (?, ?, ?)', (glass_id, int(glsstock), ts))
                    db.commit()
                    flash('Stock level updated successfully!', 'success')
                except Exception as e:
                    db.rollback()
                    flash(f'Error updating stock: {e}', 'danger')
            return redirect(url_for('glass_bp.glass_detail', glass_id=glass_id))

        glass = db.execute('''
            SELECT g.*, p.GLSPRICE, s.SRCWEB, s.GLSLOGO, c.CHEX,
                   COALESCE((SELECT i.GLSSTOCK FROM GLSINV i WHERE i.GLASSID = g.GLASSID ORDER BY i.TS DESC, i.GLSTRNID DESC LIMIT 1), 0) AS CURRENT_STOCK
            FROM GSI g LEFT JOIN GPC p ON g.GLASSID = p.GLASSID LEFT JOIN GSL s ON g.GLSOURCE = s.GLSOURCE LEFT JOIN COLOR c ON g.COLOR = c.COLOR
            WHERE g.GLASSID = ?
        ''', (glass_id,)).fetchone()
        if not glass:
            flash('Glass sheet record not found.', 'danger')
            return redirect(url_for('glass_bp.list_glass'))
        
        components = db.execute('SELECT c.*, i.ITMNAME FROM IGC c JOIN ITM i ON c.ITEMID = i.ITEMID WHERE c.GLASSID = ?', (glass_id,)).fetchall()
        return render_template('glass_detail.html', glass=glass, components=components, today_date=date.today().isoformat())

    @bp.route('/glass/edit/<int:glass_id>', methods=['GET', 'POST'])
    def edit_glass(glass_id):
        db = get_db()
        glass = db.execute('SELECT g.*, p.GLSPRICE, c.CHEX FROM GSI g LEFT JOIN GPC p ON g.GLASSID = p.GLASSID LEFT JOIN COLOR c ON g.COLOR = c.COLOR WHERE g.GLASSID = ?', (glass_id,)).fetchone()
        if not glass:
            flash('Glass sheet record not found.', 'danger')
            return redirect(url_for('glass_bp.list_glass'))
        
        if request.method == 'POST':
            glsname, glsmanf = request.form.get('GLSNAME'), request.form.get('GLSMANF')
            glstex, gtrnsn, color, glsource = request.form.get('GLSTEX') or None, request.form.get('GTRNSN') or None, request.form.get('COLOR') or None, request.form.get('GLSOURCE') or None
            glslen, glswid, glsthk = request.form.get('GLSLEN') or None, request.form.get('GLSWID') or None, request.form.get('GLSTHK') or None
            glsiri, glsopal = (1 if request.form.get('GLSIRI') else 0), (1 if request.form.get('GLSOPAL') else 0)
            gllink, glsnote, price = request.form.get('GLLINK') or None, request.form.get('GLSNOTE'), request.form.get('GLSPRICE')
            
            file = request.files.get('GLSIMG_FILE')
            if file and file.filename != '':
                glsimg = process_and_save_image(file_obj=file, upload_subfolder='images/glass', custom_filename_base=f"{glass_id}_{glsname}", target_size=(512, 512))
            else:
                glsimg = request.form.get('GLSIMG') or glass['GLSIMG']
            
            db.execute('''
                UPDATE GSI SET GLSNAME = ?, GLSMANF = ?, GLSTEX = ?, GTRNSN = ?, COLOR = ?, GLSOURCE = ?, GLSLEN = ?, GLSWID = ?, GLSTHK = ?, GLSIRI = ?, GLSOPAL = ?, GLLINK = ?, GLSIMG = ?, GLSNOTE = ?, LOWSTOCK = ?
                WHERE GLASSID = ?
            ''', (glsname, glsmanf, glstex, gtrnsn, color, glsource, glslen, glswid, glsthk, glsiri, glsopal, gllink, glsimg, glsnote, request.form.get('LOWSTOCK') or None, glass_id))
            
            if price:
                if db.execute('SELECT * FROM GPC WHERE GLASSID = ?', (glass_id,)).fetchone():
                    db.execute('UPDATE GPC SET GLSPRICE = ?, STDATE = DATE(\'now\') WHERE GLASSID = ?', (price, glass_id))
                else:
                    db.execute('INSERT INTO GPC (GLASSID, GLSPRICE, STDATE) VALUES (?, ?, DATE(\'now\'))', (glass_id, price))
            db.commit()
            flash('Glass details updated successfully!', 'success')
            return redirect(url_for('glass_bp.glass_detail', glass_id=glass_id))

        return render_template('glass_form.html', glass=glass, textures=db.execute('SELECT * FROM GTL').fetchall(), transparency=db.execute('SELECT * FROM GTRNS').fetchall(), colors=db.execute('SELECT * FROM COLOR').fetchall(), sources=db.execute('SELECT * FROM GSL').fetchall(), action='Edit')

    @bp.route('/glass/delete/<int:glass_id>', methods=['POST'])
    def delete_glass(glass_id):
        db = get_db()
        db.execute("UPDATE GSI SET ISACTIVE = 0 WHERE GLASSID = ?", (glass_id,))
        db.commit()
        flash(f"Glass sheet #{glass_id} deactivated successfully.", "warning")
        return redirect(url_for('glass_bp.list_glass'))