from datetime import datetime, date, timedelta
from flask import render_template, request, redirect, url_for, flash
import sqlite3

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_pricing_routes(bp):
    @bp.route('/glass/<int:glass_id>/history')
    def glass_price_history(glass_id):
        db = get_db()
        glass = db.execute('SELECT * FROM GSI WHERE GLASSID = ?', (glass_id,)).fetchone()
        if not glass:
            flash('Glass sheet record not found.', 'danger')
            return redirect(url_for('glass_bp.list_glass'))
        
        rows = db.execute('SELECT rowid, GLSPRICE, STDATE, ENDDATE FROM GPC WHERE GLASSID = ? ORDER BY STDATE ASC', (glass_id,)).fetchall()
        history_processed = []
        prev_price = None
        for row in rows:
            price = row['GLSPRICE']
            change = price - prev_price if prev_price is not None else None
            prev_price = price
            start_dt = datetime.strptime(row['STDATE'], '%Y-%m-%d').date() if row['STDATE'] else None
            end_dt = datetime.strptime(row['ENDDATE'], '%Y-%m-%d').date() if row['ENDDATE'] else date.today()
            
            duration_str = 'N/A'
            if start_dt:
                delta = end_dt - start_dt
                days = delta.days
                years, rem_days = divmod(days, 365)
                duration_str = f'{years} yr{"s" if years != 1 else ""} {rem_days} day{"s" if rem_days != 1 else ""}' if years > 0 else f'{days} day{"s" if days != 1 else ""}'
            
            history_processed.append({'GLSPRICE': price, 'change': change, 'STDATE': row['STDATE'], 'ENDDATE': row['ENDDATE'], 'duration_str': duration_str})
        
        history_processed.reverse()
        return render_template('glass_price_history.html', glass=glass, history=history_processed)

    @bp.route('/prices/glass/<int:glass_id>/edit', methods=['GET', 'POST'])
    def edit_glass_prices(glass_id):
        db = get_db()
        glass = db.execute('SELECT * FROM GSI WHERE GLASSID = ?', (glass_id,)).fetchone()
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
            new_end = datetime.strptime(new_end_str, '%Y-%m-%d').date() if new_end_str else None
            
            if new_end and new_st > new_end:
                flash('Start date cannot be after the end date.', 'danger')
                return redirect(url_for('glass_bp.edit_glass_prices', glass_id=glass_id))
            
            cursor = db.cursor()
            existing_prices = cursor.execute('SELECT rowid, GLSPRICE, STDATE, ENDDATE FROM GPC WHERE GLASSID = ?', (glass_id,)).fetchall()
            
            for row in existing_prices:
                row_id = row['rowid']
                ex_st = datetime.strptime(row['STDATE'], '%Y-%m-%d').date() if row['STDATE'] else None
                ex_end = datetime.strptime(row['ENDDATE'], '%Y-%m-%d').date() if row['ENDDATE'] else None
                
                if ex_st and new_st <= ex_st and (new_end is None or (ex_end and new_end >= ex_end)):
                    cursor.execute('DELETE FROM GPC WHERE rowid = ?', (row_id,))
                    continue
                if ex_st and ex_end and new_st > ex_st and new_end and new_end < ex_end:
                    cursor.execute('UPDATE GPC SET ENDDATE = ? WHERE rowid = ?', ((new_st - timedelta(days=1)).strftime('%Y-%m-%d'), row_id))
                    cursor.execute('INSERT INTO GPC (GLASSID, GLSPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, ?)', (glass_id, row['GLSPRICE'], (new_end + timedelta(days=1)).strftime('%Y-%m-%d'), row['ENDDATE']))
                    continue
                if ex_st and new_st > ex_st and (ex_end is None or new_st <= ex_end):
                    cursor.execute('UPDATE GPC SET ENDDATE = ? WHERE rowid = ?', ((new_st - timedelta(days=1)).strftime('%Y-%m-%d'), row_id))
                if new_end and ex_end and new_end >= ex_st and new_end < ex_end:
                    cursor.execute('UPDATE GPC SET STDATE = ? WHERE rowid = ?', ((new_end + timedelta(days=1)).strftime('%Y-%m-%d'), row_id))
                if is_current and ex_st and ex_st >= new_st:
                    cursor.execute('DELETE FROM GPC WHERE rowid = ?', (row_id,))
            
            cursor.execute('INSERT INTO GPC (GLASSID, GLSPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, ?)', (glass_id, new_price, new_st_str, new_end_str))
            db.commit()
            flash('Glass price range successfully saved and overlapping intervals adjusted.', 'success')
            return redirect(url_for('glass_bp.edit_glass_prices', glass_id=glass_id))

        prices = db.execute('SELECT rowid, GLSPRICE, STDATE, ENDDATE FROM GPC WHERE GLASSID = ? ORDER BY STDATE DESC', (glass_id,)).fetchall()
        return render_template('glass_edit_prices.html', glass=glass, prices=prices)

    @bp.route('/prices/glass/<int:glass_id>/delete/<int:price_id>', methods=['POST'])
    def delete_glass_price(glass_id, price_id):
        db = get_db()
        db.execute('DELETE FROM GPC WHERE rowid = ? AND GLASSID = ?', (price_id, glass_id))
        db.commit()
        flash('Glass price tier removed.', 'success')
        return redirect(url_for('glass_bp.edit_glass_prices', glass_id=glass_id))