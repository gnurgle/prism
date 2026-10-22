from datetime import datetime, date, timedelta
from flask import render_template, request, redirect, url_for, flash
import sqlite3

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_pricing_routes(bp):
    @bp.route('/prices/misc/<int:misc_id>/edit', methods=['GET', 'POST'])
    def edit_misc_prices(misc_id):
        db = get_db()
        misc = db.execute('SELECT * FROM MSI WHERE MSIID = ?', (misc_id,)).fetchone()
        if not misc:
            flash('Misc Item record not found.', 'danger')
            return redirect(url_for('misc_bp.list_misc'))
        
        if request.method == 'POST':
            try:
                new_price = float(request.form.get('MSIPRICE'))
            except (TypeError, ValueError):
                flash('Invalid price value provided.', 'danger')
                return redirect(url_for('misc_bp.edit_misc_prices', misc_id=misc_id))
            
            new_st_str = request.form.get('STDATE')
            is_current = 1 if request.form.get('is_current') else 0
            new_end_str = None if is_current else request.form.get('ENDDATE')
            new_st = datetime.strptime(new_st_str, '%Y-%m-%d').date()
            new_end = datetime.strptime(new_end_str, '%Y-%m-%d').date() if new_end_str else None
            
            if new_end and new_st > new_end:
                flash('Start date cannot be after the end date.', 'danger')
                return redirect(url_for('misc_bp.edit_misc_prices', misc_id=misc_id))
            
            cursor = db.cursor()
            existing_prices = cursor.execute('SELECT rowid, MSIPRICE, STDATE, ENDDATE FROM MSP WHERE MSIID = ?', (misc_id,)).fetchall()
            
            for row in existing_prices:
                row_id = row['rowid']
                ex_st = datetime.strptime(row['STDATE'], '%Y-%m-%d').date() if row['STDATE'] else None
                ex_end = datetime.strptime(row['ENDDATE'], '%Y-%m-%d').date() if row['ENDDATE'] else None
                
                if ex_st and new_st <= ex_st and (new_end is None or (ex_end and new_end >= ex_end)):
                    cursor.execute('DELETE FROM MSP WHERE rowid = ?', (row_id,))
                    continue
                if ex_st and ex_end and new_st > ex_st and new_end and new_end < ex_end:
                    cursor.execute('UPDATE MSP SET ENDDATE = ? WHERE rowid = ?', ((new_st - timedelta(days=1)).strftime('%Y-%m-%d'), row_id))
                    cursor.execute('INSERT INTO MSP (MSIID, MSIPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, ?)', (misc_id, row['MSIPRICE'], (new_end + timedelta(days=1)).strftime('%Y-%m-%d'), row['ENDDATE']))
                    continue
                if ex_st and new_st > ex_st and (ex_end is None or new_st <= ex_end):
                    cursor.execute('UPDATE MSP SET ENDDATE = ? WHERE rowid = ?', ((new_st - timedelta(days=1)).strftime('%Y-%m-%d'), row_id))
                if new_end and ex_end and new_end >= ex_st and new_end < ex_end:
                    cursor.execute('UPDATE MSP SET STDATE = ? WHERE rowid = ?', ((new_end + timedelta(days=1)).strftime('%Y-%m-%d'), row_id))
                if is_current and ex_st and ex_st >= new_st:
                    cursor.execute('DELETE FROM MSP WHERE rowid = ?', (row_id,))
            
            cursor.execute('INSERT INTO MSP (MSIID, MSIPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, ?)', (misc_id, new_price, new_st_str, new_end_str))
            db.commit()
            flash('Misc price range successfully saved and overlapping intervals adjusted.', 'success')
            return redirect(url_for('misc_bp.edit_misc_prices', misc_id=misc_id))

        prices = db.execute('SELECT rowid, MSIPRICE, STDATE, ENDDATE FROM MSP WHERE MSIID = ? ORDER BY STDATE DESC', (misc_id,)).fetchall()
        return render_template('misc_edit_prices.html', misc=misc, prices=prices)

    @bp.route('/prices/misc/<int:misc_id>/delete/<int:price_id>', methods=['POST'])
    def delete_misc_price(misc_id, price_id):
        db = get_db()
        db.execute('DELETE FROM MSP WHERE rowid = ? AND MSIID = ?', (price_id, misc_id))
        db.commit()
        flash('Misc price tier removed.', 'success')
        return redirect(url_for('misc_bp.edit_misc_prices', misc_id=misc_id))

    @bp.route('/misc_items/<int:misc_id>/history')
    def misc_price_history(misc_id):
        db = get_db()
        misc = db.execute('SELECT * FROM MSI WHERE MSIID = ?', (misc_id,)).fetchone()
        if not misc:
            flash('Misc Item record not found.', 'danger')
            return redirect(url_for('misc_bp.list_misc'))
        
        prices = db.execute('SELECT rowid, MSIPRICE, STDATE, ENDDATE FROM MSP WHERE MSIID = ? ORDER BY STDATE DESC, rowid DESC', (misc_id,)).fetchall()
        history, prices_list = [], [dict(p) for p in prices]
        
        for i, current in enumerate(prices_list):
            current_price = float(current['MSIPRICE'])
            current['change'] = current_price - float(prices_list[i + 1]['MSIPRICE']) if i < len(prices_list) - 1 else None
            
            st_date_str, end_date_str = current['STDATE'], current['ENDDATE']
            if st_date_str:
                days = (datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else date.today() - datetime.strptime(st_date_str, '%Y-%m-%d').date()).days
                current['duration_str'] = 'Invalid range' if days < 0 else ('1 day' if days == 0 else f"{days} days")
            else:
                current['duration_str'] = 'N/A'
            history.append(current)
            
        return render_template('misc_price_history.html', misc=misc, history=history)