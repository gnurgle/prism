from datetime import datetime, date
from flask import render_template, request, flash, jsonify, redirect, url_for
import sqlite3

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_sales_routes(bp):
    @bp.route("/sales/new", methods=["GET", "POST"])
    def record_sale():
        db = get_db()
        if request.method == "POST":
            itemid = request.form.get("ITEMID")
            sunits = request.form.get("SUNITS")
            venueid = request.form.get("VENUEID") or None
            sdate = request.form.get("SDATE") or date.today().strftime('%Y-%m-%d')
            db.execute("INSERT INTO ITMSALE (ITEMID, SUNITS, SDATE, VENUEID) VALUES (?, ?, ?, ?)", (itemid, sunits, sdate, venueid))
            db.commit()
            flash("Sale logged successfully!", "success")
            return redirect(url_for("item_bp.list_sales"))
        items = db.execute("SELECT ITEMID, ITMNAME FROM ITM").fetchall()
        venues = db.execute("SELECT VENUEID, VENUELOC FROM VENUE").fetchall()
        return render_template("sale_form.html", items=items, venues=venues)

    @bp.route('/item/bulk-sales', methods=['GET'])
    def item_bulk_sales():
        db = get_db()
        venues = db.execute("SELECT VENUEID, VENNAME FROM VENUE WHERE ISACTIVE = 1 ORDER BY VENNAME ASC").fetchall()
        return render_template('item_bulk_sales.html', venues=venues, today_date=datetime.today().strftime('%Y-%m-%d'))

    @bp.route('/item/api/bulk-sales-data', methods=['GET'])
    def api_item_bulk_sales_data():
        db = get_db()
        items = db.execute('''
            SELECT i.ITEMID, i.ITMNAME, i.ITMGRP, i.ONEOFF, i.ITMIMG, i.ISACTIVE, i.CURRENT,
                   (SELECT ii.ITMSTOCK FROM ITMINV ii WHERE ii.ITEMID = i.ITEMID ORDER BY ii.TS DESC LIMIT 1) AS CURRENT_STOCK,
                   (SELECT ipc.ITMPRICE FROM IPC ipc WHERE ipc.ITEMID = i.ITEMID ORDER BY ipc.STDATE DESC LIMIT 1) AS ITMPRICE
            FROM ITM i ORDER BY i.ITMGRP ASC, i.ITMNAME ASC
        ''').fetchall()
        return {'items': [dict(row) for row in items]}

    @bp.route('/item/api/bulk-sales-adjustment', methods=['POST'])
    def bulk_sales_adjustment():
        db = get_db()
        data = request.get_json()
        sale_date = data.get('date')
        venue_id = data.get('venue_id') or None
        items = data.get('items', [])
        if not sale_date:
            return {'status': 'error', 'message': 'Adjustment date is required.'}, 400
        try:
            for entry in items:
                item_id = entry.get('ITEMID')
                amt_sold = entry.get('amt_sold', 0)
                new_price = entry.get('price')
                if amt_sold > 0:
                    db.execute("INSERT INTO ITMSALE (ITEMID, SUNITS, SDATE, VENUEID) VALUES (?, ?, ?, ?)", (item_id, amt_sold, sale_date, venue_id))
                    inv_rows = db.execute("SELECT ITMTRNID, ITMSTOCK, TS FROM ITMINV WHERE ITEMID = ? ORDER BY TS ASC, ITMTRNID ASC", (item_id,)).fetchall()
                    exact_match, latest_before, future_rows = None, None, []
                    for row in inv_rows:
                        if row['TS'] == sale_date: exact_match = row
                        elif row['TS'] < sale_date: latest_before = row
                        elif row['TS'] > sale_date: future_rows.append(row)
                    
                    if exact_match:
                        db.execute("UPDATE ITMINV SET ITMSTOCK = ? WHERE ITMTRNID = ?", (max(0, exact_match['ITMSTOCK'] - amt_sold), exact_match['ITMTRNID']))
                    else:
                        baseline = latest_before['ITMSTOCK'] if latest_before else 0
                        db.execute("INSERT INTO ITMINV (ITEMID, ITMSTOCK, TS) VALUES (?, ?, ?)", (item_id, max(0, baseline - amt_sold), sale_date))
                    
                    for f_row in future_rows:
                        db.execute("UPDATE ITMINV SET ITMSTOCK = ? WHERE ITMTRNID = ?", (max(0, f_row['ITMSTOCK'] - amt_sold), f_row['ITMTRNID']))
                
                if new_price is not None:
                    db.execute("UPDATE IPC SET ENDDATE = DATE(?, '-1 day') WHERE ITEMID = ? AND (ENDDATE IS NULL OR ENDDATE >= DATE('now'))", (sale_date, item_id))
                    db.execute("INSERT INTO IPC (ITEMID, ITMPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, NULL)", (item_id, new_price, sale_date))
            db.commit()
            return {'status': 'success', 'message': 'Sales recorded and inventory updated successfully!'}
        except Exception as e:
            db.rollback()
            return {'status': 'error', 'message': str(e)}, 500

    @bp.route("/sales")
    def list_sales():
        db = get_db()
        sales = db.execute('''
            SELECT s.SALEID, s.ITEMID, i.ITMNAME, i.ITMGRP, s.SUNITS, s.SDATE, v.VENNAME 
            FROM ITMSALE s JOIN ITM i ON s.ITEMID = i.ITEMID LEFT JOIN VENUE v ON s.VENUEID = v.VENUEID
            ORDER BY s.SDATE DESC
        ''').fetchall()
        items = db.execute("SELECT DISTINCT ITEMID, ITMNAME, ITMGRP FROM ITM ORDER BY ITMNAME ASC").fetchall()
        item_groups = db.execute("SELECT DISTINCT ITMGRP FROM ITM WHERE ITMGRP IS NOT NULL AND ITMGRP != '' ORDER BY ITMGRP ASC").fetchall()
        venues = db.execute("SELECT VENUEID, VENNAME FROM VENUE WHERE ISACTIVE = 1 ORDER BY VENNAME ASC").fetchall()
        return render_template("sales_list.html", sales=sales, items=items, item_groups=item_groups, venues=venues)

    @bp.route('/sales/hourly', methods=['GET'])
    def hourly_sales():
        db = get_db()
        venues = db.execute("SELECT VENUEID, VENNAME FROM VENUE WHERE ISACTIVE = 1 ORDER BY VENNAME ASC").fetchall()
        return render_template('hourly_sales.html', venues=venues)

    @bp.route('/sales/api/venue-config/<int:venue_id>', methods=['GET'])
    def api_venue_config(venue_id):
        venue = get_db().execute("SELECT * FROM VENUE WHERE VENUEID = ?", (venue_id,)).fetchone()
        return dict(venue) if venue else ({'status': 'error', 'message': 'Venue not found'}, 404)

    @bp.route('/sales/api/hourly-sales', methods=['GET'])
    def api_get_hourly_sales():
        sales = get_db().execute("SELECT TSTIME, TSUNITS FROM TIMESALE WHERE VENUEID = ? AND TSDATE = ?", (request.args.get('venue_id'), request.args.get('date'))).fetchall()
        return {'sales': {row['TSTIME']: row['TSUNITS'] for row in sales}}

    @bp.route('/sales/hourly/save', methods=['POST'])
    def save_hourly_sales():
        db = get_db()
        data = request.get_json()
        venue_id, date_str, hourly_data = data.get('venue_id'), data.get('date'), data.get('hourly_data', {})
        if not venue_id or not date_str: return {'status': 'error', 'message': 'Venue and Date are required.'}, 400
        try:
            for tstime, units in hourly_data.items():
                units_int = int(units) if str(units).isdigit() else 0
                existing = db.execute("SELECT TSALEID FROM TIMESALE WHERE VENUEID = ? AND TSDATE = ? AND TSTIME = ?", (venue_id, date_str, tstime)).fetchone()
                if existing:
                    db.execute("UPDATE TIMESALE SET TSUNITS = ? WHERE TSALEID = ?", (units_int, existing['TSALEID']))
                elif units_int > 0:
                    db.execute("INSERT INTO TIMESALE (VENUEID, TSDATE, TSTIME, TSUNITS) VALUES (?, ?, ?, ?)", (venue_id, date_str, tstime, units_int))
            db.commit()
            return {'status': 'success', 'message': 'Hourly sales saved successfully!'}
        except Exception as e:
            db.rollback()
            return {'status': 'error', 'message': str(e)}, 500