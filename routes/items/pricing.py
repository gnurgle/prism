from datetime import datetime, timedelta
from flask import render_template, request, redirect, url_for, flash
import sqlite3
from square_hook.utils.upsert_item import upsert_item_in_square

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_pricing_routes(bp):
    @bp.route('/item/<int:item_id>/history')
    def price_history(item_id):
        db = get_db()
        item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()
        if not item:
            flash('Item record not found.', 'danger')
            return redirect(url_for('index'))
        
        rows = db.execute('SELECT rowid, ITMPRICE, STDATE, ENDDATE FROM IPC WHERE ITEMID = ? ORDER BY STDATE ASC', (item_id,)).fetchall()
        history_processed = []
        prev_price = None
        for row in rows:
            price = row['ITMPRICE']
            change = price - prev_price if prev_price is not None else None
            prev_price = price
            start_dt = datetime.strptime(row['STDATE'], '%Y-%m-%d') if row['STDATE'] else None
            end_dt = datetime.strptime(row['ENDDATE'], '%Y-%m-%d') if row['ENDDATE'] else datetime.today()
            
            duration_str = 'N/A'
            if start_dt:
                delta = end_dt - start_dt
                days = delta.days
                years = days // 365
                rem_days = days % 365
                duration_str = f'{years} yr{"s" if years != 1 else ""} {rem_days} day{"s" if rem_days != 1 else ""}' if years > 0 else f'{days} day{"s" if days != 1 else ""}'
            
            history_processed.append({'ITMPRICE': price, 'change': change, 'STDATE': row['STDATE'], 'ENDDATE': row['ENDDATE'], 'duration_str': duration_str})
        
        history_processed.reverse()
        return render_template('item_price_history.html', item=item, history=history_processed)

    @bp.route('/prices/<int:item_id>/edit', methods=['GET', 'POST'])
    def edit_prices(item_id):
        db = get_db()
        item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()
        if not item:
            flash('Item record not found.', 'danger')
            return redirect(url_for('index'))
        
        if request.method == 'POST':
            try:
                new_price = float(request.form.get('ITMPRICE'))
            except (TypeError, ValueError):
                flash('Invalid price value provided.', 'danger')
                return redirect(url_for('item_bp.edit_prices', item_id=item_id))
            
            new_st_str = request.form.get('STDATE')
            is_current = 1 if request.form.get('is_current') else 0
            new_end_str = None if is_current else request.form.get('ENDDATE')
            new_st = datetime.strptime(new_st_str, '%Y-%m-%d').date()
            new_end = datetime.strptime(new_end_str, '%Y-%m-%d').date() if new_end_str else None
            
            if new_end and new_st > new_end:
                flash('Start date cannot be after the end date.', 'danger')
                return redirect(url_for('item_bp.edit_prices', item_id=item_id))
            
            cursor = db.cursor()
            existing_prices = cursor.execute('SELECT rowid, ITMPRICE, STDATE, ENDDATE FROM IPC WHERE ITEMID = ?', (item_id,)).fetchall()
            
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
                
                # Case B: New range is completely inside an existing range -> Split it
                if ex_st and ex_end and new_st > ex_st and new_end and new_end < ex_end:
                    split_end_date = (new_st - timedelta(days=1)).strftime('%Y-%m-%d')
                    cursor.execute('UPDATE IPC SET ENDDATE = ? WHERE rowid = ?', (split_end_date, row_id))
                    tail_start_date = (new_end + timedelta(days=1)).strftime('%Y-%m-%d')
                    cursor.execute('INSERT INTO IPC (ITEMID, ITMPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, ?)', (item_id, row['ITMPRICE'], tail_start_date, ex_end_str))
                    continue
                
                # Case C: Overlap on the tail end of existing range (New start cuts into existing range)
                if ex_st and new_st > ex_st and (ex_end is None or new_st <= ex_end):
                    new_ex_end = (new_st - timedelta(days=1)).strftime('%Y-%m-%d')
                    cursor.execute('UPDATE IPC SET ENDDATE = ? WHERE rowid = ?', (new_ex_end, row_id))
                
                # Case D: Overlap on the front end of existing range (New end cuts into existing range)
                if new_end and ex_end and new_end >= ex_st and new_end < ex_end:
                    new_ex_st = (new_end + timedelta(days=1)).strftime('%Y-%m-%d')
                    cursor.execute('UPDATE IPC SET STDATE = ? WHERE rowid = ?', (new_ex_st, row_id))

                # Case E: If the new price is ongoing (no end date), truncate or delete any existing ranges starting on/after new start date
                if is_current and ex_st and ex_st >= new_st:
                    cursor.execute('DELETE FROM IPC WHERE rowid = ?', (row_id,))
            
            # Insert the new price record cleanly
            cursor.execute('INSERT INTO IPC (ITEMID, ITMPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, ?)', (item_id, new_price, new_st_str, new_end_str))
            db.commit()
            
            try:
                upsert_item_in_square(item_id)
            except Exception as sq_err:
                print(f"Square price sync error: {sq_err}")

            flash('Price range successfully saved, overlapping intervals adjusted, and synced to Square!', 'success')
            return redirect(url_for('item_bp.edit_prices', item_id=item_id))

        prices = db.execute('SELECT rowid, ITMPRICE, STDATE, ENDDATE FROM IPC WHERE ITEMID = ? ORDER BY STDATE DESC', (item_id,)).fetchall()
        return render_template('item_edit_prices.html', item=item, prices=prices)

    @bp.route('/prices/<int:item_id>/delete/<int:price_id>', methods=['POST'])
    def delete_price(item_id, price_id):
        db = get_db()
        db.execute('DELETE FROM IPC WHERE rowid = ? AND ITEMID = ?', (price_id, item_id))
        db.commit()
        flash('Price tier removed.', 'success')
        return redirect(url_for('item_bp.edit_prices', item_id=item_id))