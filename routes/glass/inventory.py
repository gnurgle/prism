from datetime import date, datetime, timedelta
from flask import render_template, request, flash, redirect, url_for
from utils import hex_to_hsv
import sqlite3

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_inventory_routes(bp):
    @bp.route('/glass/inventory', methods=['GET', 'POST'])
    def glass_inventory():
        db = get_db()
        if request.method == 'POST':
            glass_id, adjustment, trans_date = request.form.get('GLASSID'), request.form.get('GLSSTOCK'), request.form.get('TS') or date.today().isoformat()
            if glass_id and adjustment:
                db.execute("INSERT INTO GLSINV (GLASSID, GLSSTOCK, TS) VALUES (?, ?, ?)", (glass_id, int(adjustment), trans_date))
                db.commit()
                flash("Inventory level adjusted successfully!", "success")
            else:
                flash("Invalid input parameters for stock adjustment.", "danger")
            return redirect(url_for('glass_bp.glass_inventory'))

        sort_by = request.args.get('sort_by', 'GLSNAME')
        order = request.args.get('order', 'asc').lower()
        if order not in ['asc', 'desc']: order = 'asc'
        
        q, manf, tex, color, source = request.args.get('q', '').strip(), request.args.get('manf', '').strip(), request.args.get('tex', '').strip(), request.args.get('color', '').strip(), request.args.get('source', '').strip()
        min_price, max_price = request.args.get('min_price', '').strip(), request.args.get('max_price', '').strip()
        stock_filter, iridescent_filter, opalescent_filter = request.args.get('stock_filter', '').strip(), request.args.get('iridescent'), request.args.get('opalescent')
        stock_display_mode, is_active = request.args.get('stock_display', 'all'), request.args.get('is_active', '1').strip()
        online_only = 1 if request.args.get('online_only') == '1' else 0
        item_id, active_only = request.args.get('item_id', '').strip(), request.args.get('active_only', '')

        sql_sort_column = 'GLSNAME' if sort_by == 'COLOR_HSV' else {
            'GLASSID': 'GLASSID', 'GLSNAME': 'GLSNAME', 'GLSMANF': 'GLSMANF', 'GLSTEX': 'GLSTEX',
            'COLOR': 'COLOR', 'GLSIRI': 'GLSIRI', 'GLSOPAL': 'GLSOPAL', 'GLSLEN': 'GLSLEN',
            'CURRENT_STOCK': 'CURRENT_STOCK', 'LAST_UPDATED': 'LAST_UPDATED'
        }.get(sort_by, 'GLSNAME')

        where_clauses, params = [], []
        if is_active != 'all':
            where_clauses.append("g.ISACTIVE = ?")
            params.append(1 if is_active == '1' else 0)
        if q: where_clauses.append("(g.GLSNAME LIKE ? OR g.GLSMANF LIKE ? OR g.GLSNOTE LIKE ?)"); params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
        if manf: where_clauses.append("g.GLSMANF = ?"); params.append(manf)
        if tex: where_clauses.append("g.GLSTEX = ?"); params.append(tex)
        if color: where_clauses.append("g.COLOR = ?"); params.append(color)
        if iridescent_filter: where_clauses.append("g.GLSIRI = ?"); params.append(iridescent_filter)
        if opalescent_filter: where_clauses.append("g.GLSOPAL = ?"); params.append(opalescent_filter)
        if source: where_clauses.append("g.GLSOURCE = ?"); params.append(source)
        if min_price: where_clauses.append("p.GLSPRICE >= ?"); params.append(min_price)
        if max_price: where_clauses.append("p.GLSPRICE <= ?"); params.append(max_price)
        if online_only: where_clauses.append("(l.SRCWEB = 1 AND (g.GLLINK IS NOT NULL AND g.GLLINK != ''))")
        
        join_igc = ""
        if item_id:
            join_igc = "INNER JOIN IGC c_item ON g.GLASSID = c_item.GLASSID"
            where_clauses.append("c_item.ITEMID = ?")
            params.append(item_id)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        having_conditions = []
        if stock_filter == 'out': having_conditions.append("CURRENT_STOCK = 0")
        elif stock_filter == 'low': having_conditions.append("CURRENT_STOCK > 0 AND CURRENT_STOCK <= COALESCE(LOWSTOCK, 1)")
        elif stock_filter == 'in': having_conditions.append("CURRENT_STOCK > COALESCE(LOWSTOCK, 1)")
        if stock_display_mode == 'out': having_conditions.append("CURRENT_STOCK <= 0")
        elif stock_display_mode == 'hide': having_conditions.append("CURRENT_STOCK > 0")
        
        stock_having_sql = f"GROUP BY GLASSID HAVING {' AND '.join(having_conditions)}" if having_conditions else ""
        query = f"""
            SELECT DISTINCT GLASSID, GLSNAME, GLSMANF, GLSLEN, GLSWID, GLSTHK, GLSTEX, GLSIRI, GLSOPAL, GLSOURCE, GLLINK, GLSIMG, GLSNOTE, COLOR, ISACTIVE, CHEX, GLSPRICE, SRCWEB, LOWSTOCK, CURRENT_STOCK, LAST_UPDATED
            FROM (
                SELECT g.GLASSID, g.GLSNAME, g.GLSMANF, g.GLSLEN, g.GLSWID, g.GLSTHK, g.GLSTEX, g.GLSIRI, g.GLSOPAL, g.GLSOURCE, g.GLLINK, g.GLSIMG, g.GLSNOTE, g.COLOR, g.ISACTIVE, c.CHEX, p.GLSPRICE, l.SRCWEB, g.LOWSTOCK,
                       COALESCE((SELECT i.GLSSTOCK FROM GLSINV i WHERE i.GLASSID = g.GLASSID ORDER BY i.TS DESC, i.GLSTRNID DESC LIMIT 1), 0) AS CURRENT_STOCK,
                       (SELECT i.TS FROM GLSINV i WHERE i.GLASSID = g.GLASSID ORDER BY i.TS DESC, i.GLSTRNID DESC LIMIT 1) AS LAST_UPDATED
                FROM GSI g
                LEFT JOIN COLOR c ON g.COLOR = c.COLOR
                LEFT JOIN (SELECT GLASSID, GLSPRICE FROM GPC WHERE ENDDATE IS NULL OR ENDDATE >= DATE('now')) p ON g.GLASSID = p.GLASSID
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
                val = x.get('COLOR_HSV')
                if val is None: return (1, 1.0, 0, 0)
                if isinstance(val, tuple):
                    h, s, v = val[:3] if len(val) >= 3 else (0, 0, 0)
                    return (1 if s < 0.05 else 0, -v if s < 0.05 else h, s, v)
                if val >= 999999.0: return (1, 1.0, 0, val)
                h, rem = divmod(val, 1000)
                s, v = divmod(rem, 100)
                return (1 if s < 0.05 else 0, -v if s < 0.05 else h, s, v)
            inventory_items.sort(key=color_sort_key, reverse=(order == 'desc'))

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
            'glass_inventory.html', inventory_items=inventory_items, textures=textures, colors=colors,
            sources=sources, manufacturers=manufacturers, iridescent_options=db.execute("SELECT DISTINCT GLSIRI FROM GSI WHERE ISACTIVE = 1 AND GLSIRI = 1").fetchall(),
            opalescent_options=db.execute("SELECT DISTINCT GLSOPAL FROM GSI WHERE ISACTIVE = 1 AND GLSOPAL = 1").fetchall(), items=items, current_sort=sort_by,
            current_order=order, today_date=date.today().isoformat(), filters={
                'q': request.args.get('q', ''), 'manf': request.args.get('manf', ''), 'tex': request.args.get('tex', ''),
                'color': color, 'source': source, 'min_price': request.args.get('min_price', ''), 'max_price': request.args.get('max_price', ''),
                'stock_filter': request.args.get('stock_filter', ''), 'stock_display': stock_display_mode, 'iridescent': request.args.get('iridescent', ''),
                'opalescent': request.args.get('opalescent', ''), 'online_only': online_only, 'is_active': is_active, 'item_id': item_id,
                'item_name': item_name, 'active_only': active_only
            }
        )

    @bp.route('/glass/bulk-adjustment', methods=['GET', 'POST'])
    def bulk_inventory_adjustment():
        db = get_db()
        if request.is_json or request.method == 'POST' and request.headers.get('Content-Type') == 'application/json':
            data = request.get_json()
            adjust_date = data.get('date', date.today().isoformat())
            items = data.get('items', [])
            try:
                adjust_dt = datetime.strptime(adjust_date, '%Y-%m-%d')
                prev_day = (adjust_dt - timedelta(days=1)).strftime('%Y-%m-%d')
                for item in items:
                    glass_id, stock, price = item.get('GLASSID'), item.get('stock'), item.get('price')
                    if glass_id is not None:
                        if stock is not None:
                            db.execute("INSERT INTO GLSINV (GLASSID, GLSSTOCK, TS) VALUES (?, ?, ?)", (glass_id, int(stock), adjust_date))
                        if price is not None and price != '':
                            new_price = float(price)
                            exact_match = db.execute("SELECT rowid FROM GPC WHERE GLASSID = ? AND STDATE = ?", (glass_id, adjust_date)).fetchone()
                            if exact_match:
                                db.execute("UPDATE GPC SET GLSPRICE = ? WHERE rowid = ?", (new_price, exact_match['rowid']))
                            else:
                                next_price = db.execute("SELECT STDATE FROM GPC WHERE GLASSID = ? AND STDATE > ? ORDER BY STDATE ASC LIMIT 1", (glass_id, adjust_date)).fetchone()
                                new_end_date = (datetime.strptime(next_price['STDATE'], '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d') if next_price and next_price['STDATE'] else None
                                
                                prev_price = db.execute("SELECT rowid, ENDDATE FROM GPC WHERE GLASSID = ? AND STDATE < ? ORDER BY STDATE DESC LIMIT 1", (glass_id, adjust_date)).fetchone()
                                if prev_price and (not prev_price['ENDDATE'] or prev_price['ENDDATE'] >= adjust_date):
                                    db.execute("UPDATE GPC SET ENDDATE = ? WHERE rowid = ?", (prev_day, prev_price['rowid']))
                                
                                db.execute("INSERT INTO GPC (GLASSID, GLSPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, ?)", (glass_id, new_price, adjust_date, new_end_date))
                db.commit()
                return {"status": "success", "message": "Bulk adjustments and price tiers saved successfully!"}, 200
            except Exception as e:
                db.rollback()
                return {"status": "error", "message": str(e)}, 400

        sources = db.execute("SELECT DISTINCT GLSOURCE FROM GSI WHERE ISACTIVE = 1 AND GLSOURCE IS NOT NULL AND GLSOURCE != '' ORDER BY GLSOURCE").fetchall()
        return render_template('glass_bulk_adjustment.html', sources=sources, today_date=date.today().isoformat())

    @bp.route('/glass/api/by-source', methods=['GET'])
    def api_glass_by_source():
        db = get_db()
        source = request.args.get('source', '').strip()
        if not source: return {"items": []}, 200
        
        query = """
            SELECT g.GLASSID, g.GLSNAME, g.GLSMANF, g.GLSLEN, g.GLSWID, g.GLSTEX, g.GLSOURCE, g.GLSIMG, g.COLOR, c.CHEX, p.GLSPRICE,
                   COALESCE((SELECT i.GLSSTOCK FROM GLSINV i WHERE i.GLASSID = g.GLASSID ORDER BY i.TS DESC, i.GLSTRNID DESC LIMIT 1), 0) AS CURRENT_STOCK
            FROM GSI g LEFT JOIN COLOR c ON g.COLOR = c.COLOR LEFT JOIN (SELECT GLASSID, GLSPRICE FROM GPC WHERE ENDDATE IS NULL OR ENDDATE >= DATE('now')) p ON g.GLASSID = p.GLASSID
            WHERE g.ISACTIVE = 1 AND g.GLSOURCE = ? ORDER BY g.GLSNAME ASC
        """
        raw_items = db.execute(query, (source,)).fetchall()
        items = [dict(row, COLOR_HSV=hex_to_hsv(row['CHEX']) if row['CHEX'] else 999999.0) for row in raw_items]
        return {"items": items}, 200