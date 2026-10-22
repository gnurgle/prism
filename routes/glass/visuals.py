from datetime import date
from flask import render_template, request, redirect, url_for, flash
import sqlite3

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_visual_routes(bp):
    @bp.route('/glass/<int:glass_id>/visuals')
    def glass_visuals(glass_id):
        db = get_db()
        glass = db.execute('''
            SELECT g.*, p.GLSPRICE, c.CHEX,
                   COALESCE((SELECT i.GLSSTOCK FROM GLSINV i WHERE i.GLASSID = g.GLASSID ORDER BY i.TS DESC, i.GLSTRNID DESC LIMIT 1), 0) AS CURRENT_STOCK
            FROM GSI g LEFT JOIN GPC p ON g.GLASSID = p.GLASSID LEFT JOIN COLOR c ON g.COLOR = c.COLOR WHERE g.GLASSID = ?
        ''', (glass_id,)).fetchone()
        
        if not glass:
            flash('Glass sheet record not found.', 'danger')
            return redirect(url_for('glass_bp.list_glass'))

        price_history = db.execute('SELECT GLSPRICE, STDATE, ENDDATE FROM GPC WHERE GLASSID = ? ORDER BY STDATE ASC', (glass_id,)).fetchall()
        inventory_history = db.execute('SELECT GLSSTOCK, TS FROM GLSINV WHERE GLASSID = ? ORDER BY TS ASC, GLSTRNID ASC', (glass_id,)).fetchall()
        item_components = db.execute('SELECT c.ITEMID, c.COMPLEN, c.COMPWID, i.ITMNAME, i.ITMIMG, i.ITMGRP FROM IGC c JOIN ITM i ON c.ITEMID = i.ITEMID WHERE c.GLASSID = ?', (glass_id,)).fetchall()

        item_areas = {}
        for comp in item_components:
            iid = comp['ITEMID']
            item_areas[iid] = item_areas.get(iid, 0.0) + ((comp['COMPLEN'] or 0.0) * (comp['COMPWID'] or 0.0))

        item_inv_history = []
        if item_areas:
            placeholders = ','.join(['?'] * len(item_areas))
            item_inv_history = db.execute(f'SELECT ITMTRNID, ITEMID, ITMSTOCK, TS FROM ITMINV WHERE ITEMID IN ({placeholders}) ORDER BY ITEMID, TS ASC, ITMTRNID ASC', list(item_areas.keys())).fetchall()

        total_sheets, total_money_spent, prev_stock = 0, 0.0, 0
        def get_price_on_date(date_str):
            if not price_history: return glass['GLSPRICE'] or 0.0
            active_price = price_history[0]['GLSPRICE']
            for p in price_history:
                if (p['STDATE'] or '') <= date_str <= (p['ENDDATE'] or '9999-12-31'):
                    active_price = p['GLSPRICE']
            return active_price or 0.0

        for idx, inv in enumerate(inventory_history):
            stock_val = inv['GLSSTOCK'] or 0
            added = stock_val if idx == 0 else stock_val - prev_stock
            if added > 0:
                total_sheets += added
                total_money_spent += added * get_price_on_date((inv['TS'] or '').split(' ')[0])
            prev_stock = stock_val

        item_histories = {}
        for row in item_inv_history:
            item_histories.setdefault(row['ITEMID'], []).append(dict(row))

        total_items_made, total_sqinches, distinct_items_set = 0, 0.0, set()
        for iid, rows in item_histories.items():
            p_stock, area_per_unit = 0, item_areas.get(iid, 0.0)
            for idx, r in enumerate(rows):
                stock = r['ITMSTOCK'] or 0
                added = stock if idx == 0 else stock - p_stock
                if added > 0:
                    total_items_made += added
                    total_sqinches += (added * area_per_unit)
                    distinct_items_set.add(iid)
                p_stock = stock

        metrics = {
            'total_sheets': total_sheets, 'total_money_spent': total_money_spent,
            'total_sqft_used': total_sqinches / 144.0, 'total_items_made': total_items_made,
            'total_distinct_items': len(distinct_items_set)
        }

        return render_template(
            'glass_visuals.html', glass=glass, price_history=[dict(row) for row in price_history],
            inventory_history=[dict(row) for row in inventory_history], item_inv_history=[dict(row) for row in item_inv_history],
            item_areas=item_areas, metrics=metrics, today_date=date.today().isoformat()
        )