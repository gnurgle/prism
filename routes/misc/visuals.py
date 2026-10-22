from datetime import date
from flask import render_template, request, redirect, url_for, flash
import sqlite3

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_visual_routes(bp):
    @bp.route('/misc_item/<int:misc_id>/visuals')
    def misc_visuals(misc_id):
        db = get_db()
        misc = db.execute('''
            SELECT m.*, p.MSIPRICE, u.UNTTYPE, u.CFACTOR,
                   COALESCE((SELECT i.MSISTOCK FROM MSIINV i WHERE i.MSIID = m.MSIID ORDER BY i.TS DESC, i.MSITRNID DESC LIMIT 1), 0) AS CURRENT_STOCK
            FROM MSI m LEFT JOIN MSP p ON m.MSIID = p.MSIID LEFT JOIN UNTS u ON m.UNTTYPE = u.UNTTYPE WHERE m.MSIID = ?
        ''', (misc_id,)).fetchone()
        
        if not misc:
            flash('Misc Item record not found.', 'danger')
            return redirect(url_for('misc_bp.list_misc'))

        unttype, cfactor, msitype = (misc['UNTTYPE'] or '').lower(), misc['CFACTOR'] if misc['CFACTOR'] is not None else 1.0, (misc['MSITYPE'] or '').lower()
        price_history = db.execute('SELECT MSIPRICE, STDATE, ENDDATE FROM MSP WHERE MSIID = ? ORDER BY STDATE ASC', (misc_id,)).fetchall()
        inventory_history = db.execute('SELECT MSISTOCK, TS FROM MSIINV WHERE MSIID = ? ORDER BY TS ASC, MSITRNID ASC', (misc_id,)).fetchall()
        item_links = db.execute('SELECT l.ITEMID, l.IMIAMT, t.ITMNAME, t.ITMIMG, t.ITMGRP FROM IMI l JOIN ITM t ON l.ITEMID = t.ITEMID WHERE l.MSIID = ?', (misc_id,)).fetchall()

        item_amounts = {}
        for link in item_links:
            item_amounts[link['ITEMID']] = item_amounts.get(link['ITEMID'], 0.0) + (link['IMIAMT'] or 0.0)

        item_inv_history = []
        if item_amounts:
            placeholders = ','.join(['?'] * len(item_amounts))
            item_inv_history = db.execute(f'SELECT ITMTRNID, ITEMID, ITMSTOCK, TS FROM ITMINV WHERE ITEMID IN ({placeholders}) ORDER BY ITEMID, TS ASC, ITMTRNID ASC', list(item_amounts.keys())).fetchall()

        total_units_acquired, total_money_spent, prev_stock = 0, 0.0, 0
        def get_price_on_date(date_str):
            if not price_history: return misc['MSIPRICE'] or 0.0
            active_price = price_history[0]['MSIPRICE']
            for p in price_history:
                if (p['STDATE'] or '') <= date_str <= (p['ENDDATE'] or '9999-12-31'):
                    active_price = p['MSIPRICE']
            return active_price or 0.0

        for idx, inv in enumerate(inventory_history):
            stock_val = inv['MSISTOCK'] or 0
            added = stock_val if idx == 0 else stock_val - prev_stock
            if added > 0:
                total_units_acquired += added
                total_money_spent += added * get_price_on_date((inv['TS'] or '').split(' ')[0])
            prev_stock = stock_val

        item_histories = {}
        for row in item_inv_history:
            item_histories.setdefault(row['ITEMID'], []).append(dict(row))

        total_items_made, raw_misc_consumed, distinct_items_set = 0, 0.0, set()
        for iid, rows in item_histories.items():
            p_stock, amt_per_unit = 0, item_amounts.get(iid, 0.0)
            for idx, r in enumerate(rows):
                stock = r['ITMSTOCK'] or 0
                added = stock if idx == 0 else stock - p_stock
                if added > 0:
                    total_items_made += added
                    raw_misc_consumed += (added * amt_per_unit)
                    distinct_items_set.add(iid)
                p_stock = stock

        if 'solder' in msitype or 'pounds' in unttype:
            display_total_consumed = f"{(raw_misc_consumed * cfactor) / 454.0:.2f} lbs"
        elif any(t in msitype for t in ['foil', 'came', 'chain']) or any(t in unttype for t in ['inches', 'feet', 'yards']):
            display_total_consumed = f"{(raw_misc_consumed * cfactor) / 12.0:.2f} ft"
        else:
            display_total_consumed = f"{raw_misc_consumed * cfactor:.2f} units"

        metrics = {
            'total_units_acquired': total_units_acquired, 'total_money_spent': total_money_spent,
            'total_misc_consumed': display_total_consumed, 'total_items_made': total_items_made,
            'total_distinct_items': len(distinct_items_set)
        }

        return render_template(
            'misc_visuals.html', misc=misc, price_history=[dict(row) for row in price_history],
            inventory_history=[dict(row) for row in inventory_history], item_inv_history=[dict(row) for row in item_inv_history],
            item_amounts=item_amounts, metrics=metrics, today_date=date.today().isoformat()
        )