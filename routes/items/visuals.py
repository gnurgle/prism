from datetime import date
from flask import render_template, request, jsonify, redirect, url_for
import sqlite3

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

SOLDER_CONVERSION = 0.3776
CAME_CONVERSION = 0.1652

def register_visual_routes(bp):
    @bp.route('/item/<int:item_id>/visuals', methods=['GET'])
    def item_visuals(item_id):
        db = get_db()
        raw_item = db.execute('''
            SELECT i.*, (SELECT inv.ITMSTOCK FROM ITMINV inv WHERE inv.ITEMID = i.ITEMID ORDER BY inv.TS DESC, inv.ITMTRNID DESC LIMIT 1) AS CURRENT_STOCK
            FROM ITM i WHERE i.ITEMID = ?
        ''', (item_id,)).fetchone()
        if not raw_item:
            flash('Item record not found.', 'danger')
            return redirect(url_for('index'))
        
        item = dict(raw_item)
        item['CURRENT_STOCK'] = item.get('CURRENT_STOCK') or 0
        
        current_price = db.execute('SELECT ITMPRICE AS PRICE FROM IPC WHERE ITEMID = ? AND (ENDDATE IS NULL OR ENDDATE >= DATE("now")) ORDER BY STDATE DESC LIMIT 1', (item_id,)).fetchone()
        item['ITMPRICE'] = current_price['PRICE'] if current_price and current_price['PRICE'] else 0.0

        price_history = [dict(row) for row in db.execute('SELECT STDATE, ENDDATE, ITMPRICE AS PRICE FROM IPC WHERE ITEMID = ? ORDER BY STDATE ASC', (item_id,)).fetchall()]
        inventory_history = [dict(row) for row in db.execute('SELECT ITMSTOCK, TS FROM ITMINV WHERE ITEMID = ? ORDER BY TS ASC, ITMTRNID ASC', (item_id,)).fetchall()]
        sales_records = db.execute('SELECT SUNITS, SDATE FROM ITMSALE WHERE ITEMID = ?', (item_id,)).fetchall()
        sales_over_time = [dict(row) for row in db.execute('SELECT SDATE as date, SUNITS as quantity_sold FROM ITMSALE WHERE ITEMID = ? ORDER BY SDATE ASC', (item_id,)).fetchall()]

        # Calculation logic for costs and metrics
        components_with_cost = db.execute('''
            SELECT c.COMPLEN, c.COMPWID, g.GLSLEN, g.GLSWID, 
                   (SELECT gp.GLSPRICE FROM GPC gp WHERE gp.GLASSID = g.GLASSID AND (gp.ENDDATE IS NULL OR gp.ENDDATE >= DATE("now")) ORDER BY gp.STDATE DESC LIMIT 1) AS LATEST_GLSPRICE
            FROM IGC c JOIN GSI g ON c.GLASSID = g.GLASSID
            WHERE c.ITEMID = ? AND c.COMPLEN IS NOT NULL AND c.COMPWID IS NOT NULL AND g.GLSLEN > 0 AND g.GLSWID > 0
        ''', (item_id,)).fetchall()

        materials_cost = sum(((comp['COMPLEN'] or 0) * (comp['COMPWID'] or 0)) * ((comp['LATEST_GLSPRICE'] or 0.0) / ((comp['GLSLEN'] or 1) * (comp['GLSWID'] or 1))) for comp in components_with_cost)
        
        metrics = {'unit_cost': materials_cost, 'materials_cost': materials_cost, 'estimated_supplies_cost': 0.0, 'total_earned': 0.0, 'total_cost': 0.0, 'total_made': 0, 'total_sold': 0}
        return render_template('item_visuals.html', item=item, current_price=current_price, price_history=price_history, inventory_history=inventory_history, sales_over_time=sales_over_time, metrics=metrics, start_date='', end_date='')

    @bp.route('/visuals/hourly')
    def hourly_visuals():
        db = get_db()
        venues = db.execute('SELECT VENUEID, VENNAME FROM VENUE ORDER BY VENNAME').fetchall()
        return render_template('hourly_visuals.html', venues=venues, today_date=date.today().strftime('%Y-%m-%d'))

    @bp.route('/visuals/hourly/api/date-bounds', methods=['POST'])
    def api_venue_date_bounds():
        db = get_db()
        req_data = request.get_json() or {}
        venue_ids = req_data.get('venue_ids', [])
        if venue_ids:
            res = db.execute(f'SELECT MIN(TSDATE) as min_date, MAX(TSDATE) as max_date FROM TIMESALE WHERE VENUEID IN ({",".join(["?"] * len(venue_ids))})', venue_ids).fetchone()
        else:
            res = db.execute('SELECT MIN(TSDATE) as min_date, MAX(TSDATE) as max_date FROM TIMESALE').fetchone()
        
        dt = res['min_date'] if res and res['min_date'] else date.today().strftime('%Y-%m-%d')
        return jsonify({'status': 'success', 'min_date': dt, 'max_date': res['max_date'] or dt})

    @bp.route('/visuals/hourly/api/data', methods=['POST'])
    def api_hourly_sales_data():
        db = get_db()
        req_data = request.get_json() or {}
        start_date, end_date, venue_ids = req_data.get('start_date'), req_data.get('end_date'), req_data.get('venue_ids', [])
        
        query = "SELECT TS.VENUEID, V.VENNAME, TS.TSDATE as SDATE, TS.TSTIME as STIME, TS.TSUNITS as SUNITS FROM TIMESALE TS LEFT JOIN VENUE V ON TS.VENUEID = V.VENUEID WHERE 1=1"
        params = []
        if start_date: query += ' AND TS.TSDATE >= ?'; params.append(start_date)
        if end_date: query += ' AND TS.TSDATE <= ?'; params.append(end_date)
        if venue_ids:
            query += f' AND TS.VENUEID IN ({",".join(["?"] * len(venue_ids))})'
            params.extend(venue_ids)
            
        records = db.execute(f'{query} ORDER BY TS.TSDATE ASC, TS.TSTIME ASC', params).fetchall()
        formatted = [{'VENUEID': r['VENUEID'], 'VENNAME': r['VENNAME'] or 'Unknown Venue', 'SDATE': r['SDATE'], 'STIME': r['STIME'], 'SUNITS': r['SUNITS']} for r in records]
        return jsonify({'status': 'success', 'sales': formatted})