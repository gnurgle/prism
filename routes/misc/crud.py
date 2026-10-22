from flask import render_template, request, redirect, url_for, flash
from datetime import date
from utils import process_and_save_image
import sqlite3

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_crud_routes(bp):
    @bp.route('/misc_items')
    def list_misc():
        db = get_db()
        sort_by = request.args.get('sort_by', 'MSITYPE')
        order = request.args.get('order', 'asc').lower()
        if order not in ['asc', 'desc']: order = 'asc'
        
        q = request.args.get('q', '').strip()
        min_price = request.args.get('min_price', '').strip()
        max_price = request.args.get('max_price', '').strip()
        is_active = request.args.get('is_active', '1').strip()
        item_id = request.args.get('item_id', '').strip()
        item_name = request.args.get('item_name', '').strip()
        msi_type = request.args.get('msi_type', '').strip()
        active_only = request.args.get('active_only', '')

        allowed_sorts = {
            'MSIID': 'm.MSIID', 'MSINAME': 'm.MSINAME', 'MSIPRICE': 'p.MSIPRICE',
            'MSITYPE': 'm.MSITYPE', 'UNTS': 'm.MSIUNIT'
        }
        sort_column = allowed_sorts.get(sort_by, 'm.MSITYPE')
        where_clauses, params = [], []

        if is_active != 'all':
            where_clauses.append("m.ISACTIVE = ?")
            params.append(1 if is_active == '1' else 0)
        if q:
            where_clauses.append("(m.MSINAME LIKE ? OR m.MSINOTE LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if min_price:
            where_clauses.append("p.MSIPRICE >= ?")
            params.append(min_price)
        if max_price:
            where_clauses.append("p.MSIPRICE <= ?")
            params.append(max_price)
        if msi_type:
            where_clauses.append("m.MSITYPE = ?")
            params.append(msi_type)

        join_igc = ""
        if item_id:
            join_igc = "INNER JOIN IMI l ON m.MSIID = l.MSIID"
            where_clauses.append("l.ITEMID = ?")
            params.append(item_id)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query = f"""
            SELECT DISTINCT m.*, p.MSIPRICE, u.UNTTYPE AS UNIT_LABEL 
            FROM MSI m
            LEFT JOIN MSP p ON m.MSIID = p.MSIID
            LEFT JOIN UNTS u ON m.UNTTYPE = u.UNTTYPE
            {join_igc}
            {where_sql}
            ORDER BY {sort_column} {order.upper()}
        """
        misc_items = db.execute(query, params).fetchall()
        misc_types = db.execute('SELECT * FROM MST').fetchall()
        items = db.execute("SELECT ITEMID, ITMNAME, ITMGRP AS itmgrp, CURRENT FROM ITM ORDER BY ITMGRP ASC, ITMNAME ASC").fetchall()

        return render_template(
            'misc_list.html', misc_items=misc_items, current_sort=sort_by, current_order=order,
            misc_types=misc_types, items=items, filters={
                'q': q, 'min_price': min_price, 'max_price': max_price, 'is_active': is_active,
                'item_id': item_id, 'item_name': item_name, 'msi_type': msi_type, 'active_only': active_only
            }
        )

    @bp.route("/misc_items/new", methods=["GET", "POST"])
    def create_misc():
        db = get_db()
        if request.method == "POST":
            msiname, msistock = request.form.get('MSINAME'), request.form.get('MSISTOCK') or 0
            lowstock, msiurl = request.form.get('LOWSTOCK') or 1, request.form.get('MSIURL')
            msinote, msiunit = request.form.get('MSINOTE'), request.form.get('MSIUNIT') or 0
            unttype, msitype, msiprice = request.form.get('UNTTYPE') or None, request.form.get('MSITYPE') or None, request.form.get('MSIPRICE')

            cursor = db.execute('''
                INSERT INTO MSI (MSINAME, MSIIMG, MSISTOCK, LOWSTOCK, MSIURL, MSINOTE, MSIUNIT, UNTTYPE, MSITYPE, ISACTIVE)
                VALUES (?,?,?,?,?,?,?,?,?,1)
            ''', (msiname, None, msistock, lowstock, msiurl, msinote, msiunit, unttype, msitype))
            misc_id = cursor.lastrowid

            file = request.files.get("MSIIMG_FILE")
            if file and file.filename != '':
                msiimg_path = process_and_save_image(file_obj=file, upload_subfolder='images/misc', custom_filename_base=f"{misc_id}_{msiname}", target_size=(256, 256))
                db.execute("UPDATE MSI SET MSIIMG = ? WHERE MSIID = ?", (msiimg_path, misc_id))
            if msiprice:
                db.execute("INSERT INTO MSP (MSIID, MSIPRICE, STDATE) VALUES (?, ?, DATE('now'))", (misc_id, msiprice))
            db.commit()
            flash("Misc Item recorded successfully!", "success")
            return redirect(url_for("misc_bp.list_misc"))

        return render_template("misc_form.html", unit_types=db.execute("SELECT * FROM UNTS").fetchall(), misc_types=db.execute("SELECT * FROM MST").fetchall())

    @bp.route('/misc_item/<int:misc_id>', methods=['GET', 'POST'])
    def misc_detail(misc_id):
        db = get_db()
        if request.method == 'POST':
            adjustment, trans_date = request.form.get('MSISTOCK'), request.form.get('TS') or date.today().isoformat()
            if adjustment is not None:
                db.execute("INSERT INTO MSIINV (MSIID, MSISTOCK, TS) VALUES (?, ?, ?)", (misc_id, int(adjustment), trans_date))
                db.commit()
                flash("Inventory level adjusted successfully!", "success")
            else:
                flash("Invalid input parameters for stock adjustment.", "danger")
            return redirect(url_for('misc_bp.misc_detail', misc_id=misc_id))

        misc = db.execute('''
            SELECT m.*, u.UNTTYPE, u.CFACTOR,
                   COALESCE((SELECT i.MSISTOCK FROM MSIINV i WHERE i.MSIID = m.MSIID ORDER BY i.TS DESC, i.MSITRNID DESC LIMIT 1), 0) AS CURRENT_STOCK
            FROM MSI m LEFT JOIN UNTS u ON m.UNTTYPE = u.UNTTYPE WHERE m.MSIID = ?
        ''', (misc_id,)).fetchone()
        
        if not misc:
            flash('Misc Item record not found.', 'danger')
            return redirect(url_for('misc_bp.list_misc'))

        raw_items = db.execute('''
            SELECT m.*, i.IMIAMT, t.ITMNAME, t.ITEMID FROM MSI m
            LEFT JOIN UNTS u ON m.UNTTYPE = u.UNTTYPE
            LEFT JOIN IMI i on m.MSIID = i.MSIID
            LEFT JOIN ITM t ON i.ITEMID = t.ITEMID WHERE m.MSIID = ?
        ''', (misc_id,)).fetchall()

        current_price = db.execute("SELECT MSIPRICE AS PRICE FROM MSP WHERE MSIID = ? AND (ENDDATE IS NULL OR ENDDATE >= DATE('now')) ORDER BY STDATE DESC LIMIT 1", (misc_id,)).fetchone()
        lowest_price = db.execute("SELECT MSIPRICE AS PRICE, STDATE AS START_DATE, ENDDATE AS END_DATE FROM MSP WHERE MSIID = ? ORDER BY MSIPRICE ASC LIMIT 1", (misc_id,)).fetchone()
        highest_price = db.execute("SELECT MSIPRICE AS PRICE, STDATE AS START_DATE, ENDDATE AS END_DATE FROM MSP WHERE MSIID = ? ORDER BY MSIPRICE DESC LIMIT 1", (misc_id,)).fetchone()

        unit_price = float(current_price['PRICE']) if current_price and current_price['PRICE'] else 0.0
        cfactor = float(misc['CFACTOR']) if misc['CFACTOR'] and float(misc['CFACTOR']) > 0 else 1.0
        msiunit = float(misc['MSIUNIT']) if misc['MSIUNIT'] is not None and float(misc['MSIUNIT']) > 0 else 1.0
        divisor = cfactor * msiunit

        items = []
        for row in raw_items:
            if row['ITEMID'] is None: continue
            item = dict(row)
            raw_amt = float(item['IMIAMT']) if item['IMIAMT'] is not None else 0.0
            
            if misc['MSITYPE'] == 'Solder':
                came_row = db.execute("SELECT i.IMIAMT FROM IMI i JOIN MSI m ON i.MSIID = m.MSIID WHERE i.ITEMID = ? AND m.MSITYPE = 'Came'", (item['ITEMID'],)).fetchone()
                raw_came = float(came_row['IMIAMT']) if came_row and came_row['IMIAMT'] is not None else 0.0
                calc_amt = (raw_amt * 0.3776 * 2) + (raw_came * 0.1652 * 2)
            elif misc['MSITYPE'] == 'Came':
                calc_amt = raw_amt * 0.1652 * 2
            else:
                calc_amt = raw_amt
            
            item['CALC_AMT'] = calc_amt
            item['CALC_PRICE'] = (calc_amt * (unit_price / divisor)) if divisor > 0 and unit_price > 0 else 0.0
            items.append(item)

        return render_template(
            'misc_detail.html', misc=misc, items=items, current_price=current_price,
            lowest_price=lowest_price, highest_price=highest_price, today_date=date.today().isoformat()
        )

    @bp.route('/misc_items/edit/<int:misc_id>', methods=['GET', 'POST'])
    def edit_misc(misc_id):
        db = get_db()
        misc = db.execute('SELECT m.*, p.MSIPRICE FROM MSI m LEFT JOIN MSP p ON m.MSIID = p.MSIID WHERE m.MSIID = ?', (misc_id,)).fetchone()
        if not misc:
            flash('Misc Item record not found.', 'danger')
            return redirect(url_for('misc_bp.list_misc'))
        
        if request.method == 'POST':
            msiname, msistock = request.form.get('MSINAME'), request.form.get('MSISTOCK') or 0
            lowstock, msiurl = request.form.get('LOWSTOCK') or 1, request.form.get('MSIURL')
            msinote, msiunit = request.form.get('MSINOTE'), request.form.get('MSIUNIT') or 0
            unttype, msitype, msiprice = request.form.get('UNTTYPE') or None, request.form.get('MSITYPE') or None, request.form.get('MSIPRICE')

            file = request.files.get('MSIIMG_FILE')
            if file and file.filename != '':
                msiimg = process_and_save_image(file_obj=file, upload_subfolder='images/misc', custom_filename_base=f"{misc_id}_{msiname}", target_size=(256, 256))
            else:
                msiimg = request.form.get('MSIIMG') or misc['MSIIMG']

            db.execute('''
                UPDATE MSI SET MSINAME = ?, MSIIMG = ?, MSISTOCK = ?, LOWSTOCK = ?, MSIURL = ?, MSINOTE = ?, MSIUNIT = ?, UNTTYPE = ?, MSITYPE = ?
                WHERE MSIID = ?
            ''', (msiname, msiimg, msistock, lowstock, msiurl, msinote, msiunit, unttype, msitype, misc_id))

            if msiprice:
                if db.execute('SELECT * FROM MSP WHERE MSIID = ?', (misc_id,)).fetchone():
                    db.execute("UPDATE MSP SET MSIPRICE = ?, STDATE = DATE('now') WHERE MSIID = ?", (msiprice, misc_id))
                else:
                    db.execute("INSERT INTO MSP (MSIID, MSIPRICE, STDATE) VALUES (?, ?, DATE('now'))", (misc_id, msiprice))
            db.commit()
            flash('Misc details updated successfully!', 'success')
            return redirect(url_for('misc_bp.misc_detail', misc_id=misc_id))

        return render_template('misc_form.html', misc=misc, unit_types=db.execute("SELECT * FROM UNTS").fetchall(), misc_types=db.execute("SELECT * FROM MST").fetchall(), action='Edit')

    @bp.route('/misc_items/delete/<int:misc_id>', methods=['POST'])
    def delete_misc(misc_id):
        db = get_db()
        db.execute("UPDATE MSI SET ISACTIVE = 0 WHERE MSIID = ?", (misc_id,))
        db.commit()
        flash(f"Misc Item #{misc_id} deactivated successfully.", "warning")
        return redirect(url_for('misc_bp.list_misc'))