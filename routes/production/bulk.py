from flask import render_template, request, jsonify
from datetime import datetime
import sqlite3

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_bulk_routes(bp):
    @bp.route('/production/bulk', methods=['GET'])
    def bulk_production_page():
        today_date = datetime.now().strftime('%Y-%m-%d')
        return render_template('item_bulk_production.html', today_date=today_date)

    @bp.route('/production/bulk/data', methods=['GET'])
    def api_bulk_production_data():
        db = get_db()
        query = """
            SELECT 
                i.ITEMID, i.ITMNAME, i.ITMIMG, i.ITMGRP, i.ONEOFF, i.CURRENT, i.VARIAT, i.PARENT, i.ISACTIVE,
                c.IPID, 
                COALESCE(c.IPCUT, 0) AS IPCUT,
                COALESCE(c.IPGRND, 0) AS IPGRND,
                COALESCE(c.IPWASH, 0) AS IPWASH,
                COALESCE(c.IPFOIL, 0) AS IPFOIL,
                COALESCE(c.IPSLDR, 0) AS IPSLDR,
                COALESCE(c.IPPOLISH, 0) AS IPPOLISH,
                COALESCE(c.IPDONE, 0) AS IPDONE,
                (SELECT ITMSTOCK FROM ITMINV WHERE ITEMID = i.ITEMID ORDER BY ITMTRNID DESC LIMIT 1) AS CURRENT_STOCK
            FROM ITM i
            LEFT JOIN ICC c ON i.ITEMID = c.ITEMID
            ORDER BY i.ITMNAME ASC
        """
        items = db.execute(query).fetchall()
        items_list = []
        for row in items:
            item_dict = dict(row)
            if item_dict.get('CURRENT_STOCK') is None: item_dict['CURRENT_STOCK'] = 0
            items_list.append(item_dict)
        return jsonify({'items': items_list})

    @bp.route('/production/bulk/submit', methods=['POST'])
    def bulk_production_submit():
        db = get_db()
        data = request.get_json()
        if not data: return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400
        
        date_val, state_val, items = data.get('date'), data.get('state'), data.get('items', [])
        if not date_val or not state_val: return jsonify({'status': 'error', 'message': 'Missing date or state selection'}), 400
        
        timestamp = f"{date_val} 00:00:00" if len(date_val) == 10 else date_val
        valid_stages = {'cut': 'IPCUT', 'grnd': 'IPGRND', 'wash': 'IPWASH', 'foil': 'IPFOIL', 'sldr': 'IPSLDR', 'polish': 'IPPOLISH', 'done': 'IPDONE'}
        
        try:
            if state_val == 'in_stock':
                for item in items:
                    item_id, qty = item.get('ITEMID'), int(item.get('quantity', 0))
                    if qty == 0: continue
                    
                    exact_inv = db.execute("SELECT ITMTRNID FROM ITMINV WHERE ITEMID = ? AND TS = ?", (item_id, timestamp)).fetchone()
                    if exact_inv:
                        db.execute("UPDATE ITMINV SET ITMSTOCK = ITMSTOCK + ? WHERE ITEMID = ? AND TS >= ?", (qty, item_id, timestamp))
                    else:
                        prior_inv = db.execute("SELECT ITMSTOCK FROM ITMINV WHERE ITEMID = ? AND TS < ? ORDER BY TS DESC, ITMTRNID DESC LIMIT 1", (item_id, timestamp)).fetchone()
                        base_stock = prior_inv['ITMSTOCK'] if prior_inv and prior_inv['ITMSTOCK'] is not None else 0
                        db.execute("INSERT INTO ITMINV (ITEMID, ITMSTOCK, TS) VALUES (?, ?, ?)", (item_id, base_stock + qty, timestamp))
                        db.execute("UPDATE ITMINV SET ITMSTOCK = ITMSTOCK + ? WHERE ITEMID = ? AND TS > ?", (qty, item_id, timestamp))
                        
            elif state_val in valid_stages:
                col_name = valid_stages[state_val]
                for item in items:
                    item_id, qty = item.get('ITEMID'), int(item.get('quantity', 0))
                    if qty != 0:
                        existing = db.execute("SELECT IPID, * FROM ICC WHERE ITEMID = ?", (item_id,)).fetchone()
                        if existing:
                            new_val = max(0, (existing[col_name] or 0) + qty)
                            db.execute(f"UPDATE ICC SET {col_name} = ?, IPTS = ? WHERE ITEMID = ?", (new_val, timestamp, item_id))
                        else:
                            vals = {v: 0 for v in valid_stages.values()}
                            vals[col_name] = max(0, qty)
                            db.execute("""
                                INSERT INTO ICC (ITEMID, IPCUT, IPGRND, IPWASH, IPFOIL, IPSLDR, IPPOLISH, IPDONE, IPTS)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (item_id, vals['IPCUT'], vals['IPGRND'], vals['IPWASH'], vals['IPFOIL'], vals['IPSLDR'], vals['IPPOLISH'], vals['IPDONE'], timestamp))
            else:
                return jsonify({'status': 'error', 'message': 'Invalid state selection'}), 400
                
            db.commit()
            return jsonify({'status': 'success', 'message': 'Production bulk update saved successfully!'})
        except Exception as e:
            db.rollback()
            return jsonify({'status': 'error', 'message': str(e)}), 500