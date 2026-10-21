from datetime import date
from flask import render_template, request, redirect, url_for, flash
import sqlite3

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_inventory_routes(bp):
    @bp.route("/inventory")
    def inventory_status():
        db = get_db()
        counts = db.execute('SELECT i.ITMNAME, c.* FROM ICC c JOIN ITM i ON c.ITEMID = i.ITEMID').fetchall()
        return render_template("inventory_status.html", counts=counts)

    @bp.route("/inventory/update/<int:item_id>", methods=["POST"])
    def update_inventory(item_id):
        db = get_db()
        ipcut = int(request.form.get("IPCUT", 0))
        ipgrnd = int(request.form.get("IPGRND", 0))
        ipfoil = int(request.form.get("IPFOIL", 0))
        ipsldr = int(request.form.get("IPSLDR", 0))
        ipdone = int(request.form.get("IPDONE", 0))
        
        db.execute('''
            INSERT INTO ICC (ITEMID, IPCUT, IPGRND, IPFOIL, IPSLDR, IPDONE, IPTS)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(ITEMID) DO UPDATE SET
                IPCUT=excluded.IPCUT, IPGRND=excluded.IPGRND, 
                IPFOIL=excluded.IPFOIL, IPSLDR=excluded.IPSLDR, 
                IPDONE=excluded.IPDONE, IPTS=CURRENT_TIMESTAMP
        ''', (item_id, ipcut, ipgrnd, ipfoil, ipsldr, ipdone))
        db.execute('''
            INSERT INTO ITR (ITEMID, IPCUT, IPGRND, IPFOIL, IPSLDR, IPDONE)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (item_id, ipcut, ipgrnd, ipfoil, ipsldr, ipdone))
        db.commit()
        flash("Inventory metrics updated successfully.", "info")
        return redirect(url_for("item_bp.inventory_status"))

    @bp.route('/item/inventory', methods=['GET'])
    def item_inventory():
        db = get_db()
        sort_by = request.args.get('sort_by', 'ITMNAME')
        order = request.args.get('order', 'asc').lower()
        if order not in ['asc', 'desc']: order = 'asc'
        q = request.args.get('q', '').strip()
        itmgrp = request.args.get('itmgrp', '').strip()
        stock_filter = request.args.get('stock_filter', '').strip()
        stock_display_mode = request.args.get('stock_display', 'selling')
        is_active = request.args.get('is_active', '1').strip()
        oneoff = request.args.get('oneoff', '').strip()

        sql_sort_column = {'ITEMID': 'ITEMID', 'ITMNAME': 'ITMNAME', 'ITMGRP': 'ITMGRP', 'CURRENT_STOCK': 'CURRENT_STOCK', 'CURRENT': 'CURRENT', 'LAST_UPDATED': 'LAST_UPDATED'}.get(sort_by, 'ITMNAME')

        where_clauses, params = [], []
        if is_active != 'all':
            where_clauses.append("i.ISACTIVE = ?")
            params.append(1 if is_active == '1' else 0)
        if stock_display_mode == 'selling':
            where_clauses.append("i.CURRENT = 1")
        elif stock_display_mode == 'inactive_selling':
            where_clauses.append("i.CURRENT = 0")
        if q:
            where_clauses.append("(i.ITMNAME LIKE ? OR i.ITMNOTE LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if itmgrp:
            where_clauses.append("i.ITMGRP = ?")
            params.append(itmgrp)
        if oneoff:
            where_clauses.append("i.ONEOFF = ?")
            params.append(1 if oneoff == '1' else 0)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query = f"""
            SELECT ITEMID, ITMNAME, ITMGRP, ITMLEN, ITMWID, ONEOFF, CURRENT, ITMIMG, ITMNOTE, ISACTIVE, ITMPRICE, CURRENT_STOCK, LAST_UPDATED
            FROM (
                SELECT i.ITEMID, i.ITMNAME, i.ITMGRP, i.ITMLEN, i.ITMWID, i.ONEOFF, i.CURRENT, i.ITMIMG, i.ITMNOTE, i.ISACTIVE, p.ITMPRICE,
                       COALESCE((SELECT ii.ITMSTOCK FROM ITMINV ii WHERE ii.ITEMID = i.ITEMID ORDER BY ii.TS DESC, ii.ITMTRNID DESC LIMIT 1), 0) AS CURRENT_STOCK,
                       (SELECT ii.TS FROM ITMINV ii WHERE ii.ITEMID = i.ITEMID ORDER BY ii.TS DESC, ii.ITMTRNID DESC LIMIT 1) AS LAST_UPDATED
                FROM ITM i
                LEFT JOIN (SELECT ITEMID, ITMPRICE FROM IPC WHERE ENDDATE IS NULL OR ENDDATE >= DATE('now')) p ON i.ITEMID = p.ITEMID
                {where_sql}
            ) sub
            ORDER BY {sql_sort_column} {order.upper()}
        """
        inventory_items = db.execute(query, params).fetchall()
        groups = db.execute("SELECT DISTINCT ITMGRP FROM ITM WHERE ITMGRP IS NOT NULL AND ITMGRP != '' ORDER BY ITMGRP ASC").fetchall()
        return render_template('item_inventory.html', inventory_items=inventory_items, groups=groups, current_sort=sort_by, current_order=order, today_date=date.today().isoformat(), filters={'q': q, 'itmgrp': itmgrp, 'stock_filter': stock_filter, 'stock_display': stock_display_mode, 'is_active': is_active, 'oneoff': oneoff})