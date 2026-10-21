import os
import sqlite3
from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from werkzeug.utils import secure_filename
from square_hook.utils.upsert_item import upsert_item_in_square

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

SOLDER_CONVERSION = 0.3776
CAME_CONVERSION = 0.1652

def register_crud_routes(bp):
    @bp.route('/item/<int:item_id>', methods=['GET'])
    def item_detail(item_id):
        db = get_db()
        raw_item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()
        if not raw_item:
            flash('Item record not found.', 'danger')
            return redirect(url_for('index'))
        item = dict(raw_item)
        components = db.execute('''
            SELECT c.*, g.GLSNAME 
            FROM IGC c
            LEFT JOIN GSI g ON c.GLASSID = g.GLASSID
            WHERE c.ITEMID = ?
            ORDER BY c.COMPNUM ASC
        ''', (item_id,)).fetchall()
        
        current_price = db.execute('''
            SELECT ITMPRICE AS PRICE FROM IPC 
            WHERE ITEMID = ? AND (ENDDATE IS NULL OR ENDDATE >= DATE('now'))
            ORDER BY STDATE DESC LIMIT 1
        ''', (item_id,)).fetchone()
        
        lowest_price = db.execute('SELECT ITMPRICE AS PRICE, STDATE AS START_DATE, ENDDATE AS END_DATE FROM IPC WHERE ITEMID = ? ORDER BY ITMPRICE ASC LIMIT 1', (item_id,)).fetchone()
        highest_price = db.execute('SELECT ITMPRICE AS PRICE, STDATE AS START_DATE, ENDDATE AS END_DATE FROM IPC WHERE ITEMID = ? ORDER BY ITMPRICE DESC LIMIT 1', (item_id,)).fetchone()
        
        group_siblings = []
        if not item['ONEOFF'] and item['ITMGRP']:
            group_siblings = db.execute('SELECT ITEMID, ITMNAME FROM ITM WHERE ITMGRP = ? AND ONEOFF = 0 ORDER BY ITMNAME ASC', (item['ITMGRP'],)).fetchall()
        
        components_with_cost = db.execute('''
            SELECT c.COMPLEN, c.COMPWID, g.GLSLEN, g.GLSWID, 
                   (SELECT gp.GLSPRICE FROM GPC gp 
                    WHERE gp.GLASSID = g.GLASSID AND (gp.ENDDATE IS NULL OR gp.ENDDATE >= DATE('now'))
                    ORDER BY gp.STDATE DESC LIMIT 1) AS LATEST_GLSPRICE
            FROM IGC c
            JOIN GSI g ON c.GLASSID = g.GLASSID
            WHERE c.ITEMID = ? AND c.COMPLEN IS NOT NULL AND c.COMPWID IS NOT NULL
                  AND g.GLSLEN IS NOT NULL AND g.GLSWID IS NOT NULL AND g.GLSLEN > 0 AND g.GLSWID > 0
        ''', (item_id,)).fetchall()
        
        materials_cost = 0.0
        for comp in components_with_cost:
            comp_sqin = (comp['COMPLEN'] or 0) * (comp['COMPWID'] or 0)
            glass_sheet_area = (comp['GLSLEN'] or 1) * (comp['GLSWID'] or 1)
            glass_sheet_price = comp['LATEST_GLSPRICE'] or 0.0
            if glass_sheet_area > 0:
                cost_per_sqin = glass_sheet_price / glass_sheet_area
                materials_cost += comp_sqin * cost_per_sqin

        associated_supplies_rows = db.execute('''
            SELECT msi.MSIID, msi.MSINAME, msi.MSITYPE, imi.IMIAMT, msi.MSIUNIT, u.CFACTOR
            FROM IMI imi
            JOIN MSI msi ON imi.MSIID = msi.MSIID
            LEFT JOIN UNTS u ON msi.UNTTYPE = u.UNTTYPE
            WHERE imi.ITEMID = ?
        ''', (item_id,)).fetchall()
        
        supplies_map = {row['MSITYPE']: row for row in associated_supplies_rows}
        associated_decorations = db.execute('''
            SELECT m.MSIID, m.MSINAME, i.IMIAMT, m.MSIUNIT, u.CFACTOR
            FROM IMI i
            JOIN MSI m ON i.MSIID = m.MSIID
            LEFT JOIN UNTS u ON m.UNTTYPE = u.UNTTYPE
            WHERE i.ITEMID = ? AND m.MSITYPE = 'Decoration'
            ORDER BY m.MSINAME ASC
        ''', (item_id,)).fetchall()

        raw_sldr = float(supplies_map['Solder']['IMIAMT']) if 'Solder' in supplies_map and supplies_map['Solder']['IMIAMT'] is not None else 0.0
        raw_came = float(supplies_map['Came']['IMIAMT']) if 'Came' in supplies_map and supplies_map['Came']['IMIAMT'] is not None else 0.0
        itm_supplies = {
            'ITMSLDR': (raw_sldr * SOLDER_CONVERSION * 2) + (raw_came * CAME_CONVERSION * 2),
            'ITMCAME': raw_came,
            'ITMFOIL': float(supplies_map['Foil']['IMIAMT']) if 'Foil' in supplies_map and supplies_map['Foil']['IMIAMT'] is not None else 0.0,
            'ITMCHAIN': float(supplies_map['Chain']['IMIAMT']) if 'Chain' in supplies_map and supplies_map['Chain']['IMIAMT'] is not None else 0.0,
            'ITMRING': float(supplies_map['Rings']['IMIAMT']) if 'Rings' in supplies_map and supplies_map['Rings']['IMIAMT'] is not None else 0,
            'ITMWIRE': float(supplies_map['Wire']['IMIAMT']) if 'Wire' in supplies_map and supplies_map['Wire']['IMIAMT'] is not None else 0.0
        }

        return render_template(
            'item_detail.html', item=item, components=components,
            current_price=current_price, lowest_price=lowest_price, highest_price=highest_price,
            materials_cost=materials_cost, group_siblings=group_siblings,
            itm_supplies=itm_supplies, associated_supplies=associated_supplies_rows,
            associated_decorations=associated_decorations
        )

    @bp.route('/item/new', methods=['GET', 'POST'])
    def create_item():
        db = get_db()
        if request.method == 'POST':
            itmname = request.form.get('ITMNAME')
            itmgrp = request.form.get('ITMGRP') or None
            new_itmgrp = request.form.get('NEW_ITMGRP')
            if new_itmgrp and new_itmgrp.strip():
                itmgrp = new_itmgrp.strip()
                db.execute("INSERT OR IGNORE INTO IGP (ITMGRP, ISACTIVE) VALUES (?, 1)", (itmgrp,))
            
            itmlen = request.form.get('ITMLEN')
            itmwid = request.form.get('ITMWID')
            oneoff = 1 if request.form.get('ONEOFF') else 0
            current = 1 if request.form.get('CURRENT') else 0
            itmnote = request.form.get('ITMNOTE')

            itmimg_path = None
            file = request.files.get('ITMIMG_FILE')
            if file and file.filename:
                filename = secure_filename(file.filename)
                upload_folder = os.path.join(current_app.root_path, 'static', 'images', 'item')
                os.makedirs(upload_folder, exist_ok=True)
                file.save(os.path.join(upload_folder, filename))
                itmimg_path = f"images/item/{filename}"

            cursor = db.execute('''
                INSERT INTO ITM (ITMNAME, ITMGRP, ITMLEN, ITMWID, ONEOFF, CURRENT, ITMNOTE, ITMIMG, ISACTIVE)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (itmname, itmgrp, itmlen or None, itmwid or None, oneoff, current, itmnote, itmimg_path))
            new_item_id = cursor.lastrowid
            db.commit()

            try:
                upsert_item_in_square(new_item_id)
            except Exception as e:
                print(f"Square sync error: {e}")

            flash('Item created successfully!', 'success')
            return redirect(url_for('templates_bp.upload_template', item_id=new_item_id))

        all_groups = db.execute('SELECT DISTINCT ITMGRP FROM ITM WHERE ITMGRP IS NOT NULL ORDER BY ITMGRP ASC').fetchall()
        all_msi = db.execute('SELECT MSIID, MSINAME, MSITYPE FROM MSI WHERE ISACTIVE = 1 ORDER BY MSINAME ASC').fetchall()
        return render_template('item_form.html', action='Create', item={}, groups=all_groups,
                               msi_solder=[m for m in all_msi if m['MSITYPE'] == 'Solder'],
                               msi_foil=[m for m in all_msi if m['MSITYPE'] == 'Foil'],
                               msi_came=[m for m in all_msi if m['MSITYPE'] == 'Came'],
                               msi_chain=[m for m in all_msi if m['MSITYPE'] == 'Chain'],
                               msi_rings=[m for m in all_msi if m['MSITYPE'] == 'Rings'],
                               msi_wire=[m for m in all_msi if m['MSITYPE'] == 'Wire'])

    @bp.route('/item/<int:item_id>/edit', methods=['GET', 'POST'])
    def edit_item(item_id):
        db = get_db()
        item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()
        if not item:
            flash('Item not found.', 'danger')
            return redirect(url_for('index'))
        
        if request.method == 'POST':
            itmname = request.form.get('ITMNAME')
            itmgrp = request.form.get('ITMGRP') or None
            new_itmgrp = request.form.get('NEW_ITMGRP')
            if new_itmgrp and new_itmgrp.strip():
                itmgrp = new_itmgrp.strip()
                db.execute("INSERT OR IGNORE INTO IGP (ITMGRP, ISACTIVE) VALUES (?, 1)", (itmgrp,))
            
            itmlen = request.form.get('ITMLEN')
            itmwid = request.form.get('ITMWID')
            oneoff = 1 if request.form.get('ONEOFF') else 0
            current = 1 if request.form.get('CURRENT') else 0
            itmnote = request.form.get('ITMNOTE')

            file = request.files.get('ITMIMG_FILE')
            if file and file.filename:
                filename = secure_filename(file.filename)
                upload_folder = os.path.join(current_app.root_path, 'static', 'images', 'item')
                os.makedirs(upload_folder, exist_ok=True)
                file.save(os.path.join(upload_folder, filename))
                db.execute("UPDATE ITM SET ITMIMG = ? WHERE ITEMID = ?", (f"images/item/{filename}", item_id))

            db.execute('''
                UPDATE ITM SET ITMNAME = ?, ITMGRP = ?, ITMLEN = ?, ITMWID = ?, ONEOFF = ?, CURRENT = ?, ITMNOTE = ?
                WHERE ITEMID = ?
            ''', (itmname, itmgrp, itmlen or None, itmwid or None, oneoff, current, itmnote, item_id))
            db.commit()

            try:
                upsert_item_in_square(item_id)
            except Exception as e:
                print(f"Square sync error: {e}")

            flash('Item updated successfully!', 'success')
            return redirect(url_for('item_bp.item_detail', item_id=item_id))

        all_groups = db.execute('SELECT DISTINCT ITMGRP FROM ITM WHERE ITMGRP IS NOT NULL ORDER BY ITMGRP ASC').fetchall()
        return render_template('item_form.html', action='Edit', item=item, groups=all_groups)

    @bp.route("/item/<int:item_id>/process_workflow", methods=["GET", "POST"])
    def process_workflow(item_id):
        db = get_db()
        item = db.execute("SELECT * FROM ITM WHERE ITEMID = ?", (item_id,)).fetchone()
        if not item:
            flash("Item not found.", "danger")
            return redirect(url_for("index"))
        if request.method == "POST":
            try:
                from routes.component_routes import process_build_components as build_components_for_item
                build_components_for_item(item_id)
                from routes.template_routes import process_trace_outline
                trace_result = process_trace_outline(item_id)
                if not trace_result['success']:
                    return jsonify({'success': False, 'message': trace_result['message']}), 500
                return jsonify({'success': True, 'redirect_url': url_for('component_bp.edit_components', item_id=item_id)})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)}), 500
        return render_template("process_workflow.html", item=item)

    @bp.route('/item/color-variation', methods=['GET', 'POST'])
    def color_variation_select():
        db = get_db()
        if request.method == 'POST':
            source_item_id = request.form.get('source_item_id')
            new_item_name = request.form.get('new_item_name')
            if not source_item_id or not new_item_name or not new_item_name.strip():
                flash('Please select an item and provide a valid new item name.', 'warning')
                return redirect(url_for('item_bp.color_variation_select'))
            
            source_item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (source_item_id,)).fetchone()
            if not source_item:
                flash('Source item record not found.', 'danger')
                return redirect(url_for('item_bp.color_variation_select'))
            
            source_dict = dict(source_item)
            cursor = db.execute('''
                INSERT INTO ITM (ITMNAME, ONEOFF, VARIAT, ITMGRP, CURRENT, ITMPTRN, ITMSVG, ITMNOTE, ITMLEN, ITMWID, PARENT, PATINA, ISACTIVE)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                new_item_name.strip(), source_dict['ONEOFF'], source_dict.get('VARIAT', 1),
                source_dict['ITMGRP'], source_dict['CURRENT'], source_dict['ITMPTRN'],
                source_dict['ITMSVG'], source_dict['ITMNOTE'], source_dict['ITMLEN'],
                source_dict['ITMWID'], source_item_id, source_dict['PATINA'], source_dict['ISACTIVE']
            ))
            new_item_id = cursor.lastrowid
            
            components = db.execute('SELECT * FROM IGC WHERE ITEMID = ?', (source_item_id,)).fetchall()
            for comp in components:
                c = dict(comp)
                db.execute('''
                    INSERT INTO IGC (COMPNAME, ITEMID, COMPNUM, SVGREG, GLASSID, COMPLEN, COMPWID, COMPNOTE, ISSCRap, ISGRAIN, ISACTIVE)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (c['COMPNAME'], new_item_id, c['COMPNUM'], c['SVGREG'], c['GLASSID'], c['COMPLEN'], c['COMPWID'], c['COMPNOTE'], c['ISSCRAP'], c['ISGRAIN'], c['ISACTIVE']))
            
            db.commit()
            flash('Color variation created successfully!', 'success')
            return redirect(url_for('component_bp.edit_components', item_id=new_item_id))

        groups = db.execute('SELECT DISTINCT ITMGRP FROM ITM WHERE ITMGRP IS NOT NULL ORDER BY ITMGRP ASC').fetchall()
        items = db.execute('SELECT ITEMID, ITMNAME, ITMGRP, ITMIMG FROM ITM ORDER BY ITMGRP ASC, ITMNAME ASC').fetchall()
        return render_template('item_color_variation_select.html', groups=groups, items=items)

    @bp.route('/item/list', methods=['GET'])
    def item_list():
        db = get_db()
        sort_by = request.args.get('sort_by', 'ITMNAME')
        order = request.args.get('order', 'asc').lower()
        if order not in ['asc', 'desc']: order = 'asc'
        q = request.args.get('q', '').strip()
        itmgrp = request.args.get('itmgrp', '').strip()
        oneoff = request.args.get('oneoff', '').strip()
        is_active = request.args.get('is_active', '1').strip()
        actively_selling = request.args.get('actively_selling', '').strip()

        sql_sort_column = {
            'ITMNAME': 'i.ITMNAME COLLATE NOCASE',
            'ITMGRP': 'i.ITMGRP COLLATE NOCASE',
            'ONEOFF': 'i.ONEOFF',
            'ITMPRICE': 'p.ITMPRICE',
            'ISACTIVE': 'i.ISACTIVE'
        }.get(sort_by, 'i.ITMNAME COLLATE NOCASE')

        where_clauses, params = [], []
        if is_active != 'all':
            where_clauses.append("i.ISACTIVE = ?")
            params.append(1 if is_active == '1' else 0)
        if q:
            where_clauses.append("(i.ITMNAME LIKE ? OR i.ITMNOTE LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if itmgrp:
            where_clauses.append("i.ITMGRP = ?")
            params.append(itmgrp)
        if oneoff:
            where_clauses.append("i.ONEOFF = ?")
            params.append(oneoff)
        if actively_selling == '1':
            where_clauses.append("i.CURRENT = 1")
        elif actively_selling == '0':
            where_clauses.append("i.CURRENT = 0")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query = f"""
            SELECT DISTINCT i.*, p.ITMPRICE
            FROM ITM i
            LEFT JOIN (SELECT ITEMID, ITMPRICE FROM IPC WHERE ENDDATE IS NULL OR ENDDATE >= DATE('now')) p ON i.ITEMID = p.ITEMID
            {where_sql}
            ORDER BY {sql_sort_column} {order.upper()}
        """
        items = [dict(row) for row in db.execute(query, params).fetchall()]
        groups = db.execute("SELECT DISTINCT ITMGRP FROM ITM WHERE ITMGRP IS NOT NULL AND ITMGRP != '' ORDER BY ITMGRP COLLATE NOCASE").fetchall()
        return render_template('item_list.html', items=items, groups=groups, current_sort=sort_by, current_order=order, filters={'q': q, 'itmgrp': itmgrp, 'oneoff': oneoff, 'is_active': is_active, 'actively_selling': actively_selling})