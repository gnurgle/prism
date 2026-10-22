from flask import render_template, request, jsonify
from datetime import datetime
import sqlite3

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_board_routes(bp):
    @bp.route('/production', methods=['GET'])
    def production_board():
        db = get_db()
        query = """
            SELECT 
                i.ITEMID, i.ITMNAME, i.ITMIMG, i.ITMGRP, i.ONEOFF, i.CURRENT, i.VARIAT, i.PARENT,
                c.IPID, 
                COALESCE(c.IPCUT, 0) AS IPCUT,
                COALESCE(c.IPGRND, 0) AS IPGRND,
                COALESCE(c.IPWASH, 0) AS IPWASH,
                COALESCE(c.IPFOIL, 0) AS IPFOIL,
                COALESCE(c.IPSLDR, 0) AS IPSLDR,
                COALESCE(c.IPPOLISH, 0) AS IPPOLISH,
                COALESCE(c.IPDONE, 0) AS IPDONE,
                c.IPTS
            FROM ITM i
            LEFT JOIN ICC c ON i.ITEMID = c.ITEMID
            WHERE i.ISACTIVE = 1
            ORDER BY i.ITMNAME ASC
        """
        items = db.execute(query).fetchall()
        item_groups = db.execute("SELECT ITMGRP FROM IGP WHERE ISACTIVE = 1 OR ISACTIVE IS NULL ORDER BY ITMGRP ASC").fetchall()
        master_items = db.execute("""
            SELECT ITEMID, ITMNAME, ITMGRP, ONEOFF, CURRENT, VARIAT, PARENT 
            FROM ITM 
            WHERE ISACTIVE = 1 
            ORDER BY ITMNAME ASC
        """).fetchall()
        
        summary_query = """
            SELECT 
                SUM(COALESCE(IPCUT, 0)) as total_cut,
                SUM(COALESCE(IPGRND, 0)) as total_grind,
                SUM(COALESCE(IPWASH, 0)) as total_wash,
                SUM(COALESCE(IPFOIL, 0)) as total_foil,
                SUM(COALESCE(IPSLDR, 0)) as total_solder,
                SUM(COALESCE(IPPOLISH, 0)) as total_polish,
                SUM(COALESCE(IPDONE, 0)) as total_done
            FROM ICC
        """
        summary = db.execute(summary_query).fetchone()
        return render_template(
            'production_board.html', items=items, summary=summary,
            item_groups=item_groups, master_items=master_items
        )

    @bp.route('/production/add-item', methods=['POST'])
    def add_item_to_production():
        db = get_db()
        data = request.get_json()
        if not data: return jsonify({'success': False, 'error': 'Invalid payload'}), 400
        
        item_id, target_stage, quantity = data.get('item_id'), data.get('stage'), int(data.get('quantity', 1))
        valid_stages = {'cut': 'IPCUT', 'grnd': 'IPGRND', 'wash': 'IPWASH', 'foil': 'IPFOIL', 'sldr': 'IPSLDR', 'polish': 'IPPOLISH', 'done': 'IPDONE'}
        
        if target_stage not in valid_stages or not item_id:
            return jsonify({'success': False, 'error': 'Invalid stage or item selection'}), 400
            
        col_name, timestamp = valid_stages[target_stage], datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        existing = db.execute("SELECT IPID, * FROM ICC WHERE ITEMID = ?", (item_id,)).fetchone()
        
        if existing:
            new_val = (existing[col_name] or 0) + quantity
            db.execute(f"UPDATE ICC SET {col_name} = ?, IPTS = ? WHERE ITEMID = ?", (new_val, timestamp, item_id))
        else:
            vals = {v: 0 for v in valid_stages.values()}
            vals[col_name] = quantity
            db.execute("""
                INSERT INTO ICC (ITEMID, IPCUT, IPGRND, IPWASH, IPFOIL, IPSLDR, IPPOLISH, IPDONE, IPTS)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (item_id, vals['IPCUT'], vals['IPGRND'], vals['IPWASH'], vals['IPFOIL'], vals['IPSLDR'], vals['IPPOLISH'], vals['IPDONE'], timestamp))
        db.commit()
        return jsonify({'success': True})

    @bp.route('/production/update', methods=['POST'])
    def update_production_stage():
        db = get_db()
        data = request.get_json()
        if not data: return jsonify({'success': False, 'error': 'Invalid payload'}), 400
        
        item_id, target_stage, delta = data.get('item_id'), data.get('stage'), int(data.get('delta', 0))
        valid_stages = {'cut': 'IPCUT', 'grnd': 'IPGRND', 'wash': 'IPWASH', 'foil': 'IPFOIL', 'sldr': 'IPSLDR', 'polish': 'IPPOLISH', 'done': 'IPDONE'}
        
        if target_stage not in valid_stages: return jsonify({'success': False, 'error': 'Invalid production stage'}), 400
        
        col_name, timestamp = valid_stages[target_stage], datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        existing = db.execute("SELECT IPID, * FROM ICC WHERE ITEMID = ?", (item_id,)).fetchone()
        
        if existing:
            new_val = max(0, (existing[col_name] or 0) + delta)
            db.execute(f"UPDATE ICC SET {col_name} = ?, IPTS = ? WHERE ITEMID = ?", (new_val, timestamp, item_id))
        else:
            vals = {v: 0 for v in valid_stages.values()}
            vals[col_name] = max(0, delta)
            db.execute("""
                INSERT INTO ICC (ITEMID, IPCUT, IPGRND, IPWASH, IPFOIL, IPSLDR, IPPOLISH, IPDONE, IPTS)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (item_id, vals['IPCUT'], vals['IPGRND'], vals['IPWASH'], vals['IPFOIL'], vals['IPSLDR'], vals['IPPOLISH'], vals['IPDONE'], timestamp))
        db.commit()
        
        summary = db.execute("""
            SELECT SUM(COALESCE(IPCUT, 0)) as total_cut, SUM(COALESCE(IPGRND, 0)) as total_grind,
                   SUM(COALESCE(IPWASH, 0)) as total_wash, SUM(COALESCE(IPFOIL, 0)) as total_foil,
                   SUM(COALESCE(IPSLDR, 0)) as total_solder, SUM(COALESCE(IPPOLISH, 0)) as total_polish,
                   SUM(COALESCE(IPDONE, 0)) as total_done FROM ICC
        """).fetchone()
        return jsonify({'success': True, 'summary': dict(summary)})

    @bp.route('/production/save-finished', methods=['POST'])
    def save_finished_items():
        db = get_db()
        data = request.get_json()
        item_id = data.get('item_id')
        if not item_id: return jsonify({'success': False, 'error': 'No item specified'}), 400
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        icc_record = db.execute("SELECT IPDONE FROM ICC WHERE ITEMID = ?", (item_id,)).fetchone()
        if not icc_record or not icc_record['IPDONE'] or icc_record['IPDONE'] <= 0:
            return jsonify({'success': False, 'error': 'No finished items to save'}), 400
            
        finished_qty = icc_record['IPDONE']
        last_inv = db.execute("SELECT ITMSTOCK FROM ITMINV WHERE ITEMID = ? ORDER BY ITMTRNID DESC LIMIT 1", (item_id,)).fetchone()
        previous_stock = last_inv['ITMSTOCK'] if last_inv and last_inv['ITMSTOCK'] is not None else 0
        new_total_stock = previous_stock + finished_qty
        
        db.execute("INSERT INTO ITMINV (ITEMID, ITMSTOCK, TS) VALUES (?, ?, ?)", (item_id, new_total_stock, timestamp))
        db.execute("UPDATE ICC SET IPDONE = 0, IPTS = ? WHERE ITEMID = ?", (timestamp, item_id))
        db.commit()
        
        summary = db.execute("""
            SELECT SUM(COALESCE(IPCUT, 0)) as total_cut, SUM(COALESCE(IPGRND, 0)) as total_grind,
                   SUM(COALESCE(IPWASH, 0)) as total_wash, SUM(COALESCE(IPFOIL, 0)) as total_foil,
                   SUM(COALESCE(IPSLDR, 0)) as total_solder, SUM(COALESCE(IPPOLISH, 0)) as total_polish,
                   SUM(COALESCE(IPDONE, 0)) as total_done FROM ICC
        """).fetchone()
        return jsonify({'success': True, 'summary': dict(summary)})