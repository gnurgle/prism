from datetime import date
from flask import render_template, request, flash, redirect, url_for
import sqlite3

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_inventory_routes(bp):
    @bp.route('/misc_items/inventory', methods=['GET', 'POST'])
    def misc_inventory():
        db = get_db()
        if request.method == 'POST':
            misc_id, adjustment, trans_date = request.form.get('MSIID'), request.form.get('MSISTOCK'), request.form.get('TS') or date.today().isoformat()
            if misc_id and adjustment:
                db.execute("INSERT INTO MSIINV (MSIID, MSISTOCK, TS) VALUES (?, ?, ?)", (misc_id, int(adjustment), trans_date))
                db.commit()
                flash("Inventory level adjusted successfully!", "success")
            else:
                flash("Invalid input parameters for stock adjustment.", "danger")
            return redirect(url_for('misc_bp.misc_inventory'))

        sort_by = request.args.get('sort_by', 'MSINAME')
        order = request.args.get('order', 'asc').lower()
        if order not in ['asc', 'desc']: order = 'asc'
        
        q = request.args.get('q', '').strip()
        min_price, max_price = request.args.get('min_price', '').strip(), request.args.get('max_price', '').strip()
        stock_filter, stock_display_mode = request.args.get('stock_filter', '').strip(), request.args.get('stock_display', 'all')
        misc_type_filter = request.args.get('misc_type', '').strip()

        allowed_sorts = {
            'MSIID': 'MSIID', 'MSINAME': 'MSINAME', 'MSIPRICE': 'MSIPRICE',
            'MSITYPE': 'MSITYPE', 'CURRENT_STOCK': 'CURRENT_STOCK', 'LAST_UPDATED': 'LAST_UPDATED'
        }
        sql_sort_column = 'MSINAME' if sort_by == 'MSITYPE' else allowed_sorts.get(sort_by, 'MSINAME')
        where_clauses, params = ["m.ISACTIVE = 1"], []

        if q:
            where_clauses.append("(m.MSINAME LIKE ? OR m.MSINOTE LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if misc_type_filter:
            where_clauses.append("m.MSITYPE = ?")
            params.append(misc_type_filter)

        where_sql = f"WHERE {' AND '.join(where_clauses)}"
        having_conditions = []
        if stock_filter == 'out': having_conditions.append("CURRENT_STOCK = 0")
        elif stock_filter == 'low': having_conditions.append("CURRENT_STOCK <= LOWSTOCK AND CURRENT_STOCK > 0")
        elif stock_filter == 'in': having_conditions.append("CURRENT_STOCK > LOWSTOCK")
        if stock_display_mode == 'out': having_conditions.append("CURRENT_STOCK <= 0")
        elif stock_display_mode == 'hide': having_conditions.append("CURRENT_STOCK > 0")

        stock_having_sql = f"GROUP BY MSIID HAVING {' AND '.join(having_conditions)}" if having_conditions else ""
        query = f"""
            SELECT MSIID, MSINAME, MSIURL, MSIIMG, MSINOTE, MSITYPE, UNTTYPE, ISACTIVE, MSIPRICE, LOWSTOCK, CURRENT_STOCK, LAST_UPDATED
            FROM (
                SELECT m.MSIID, m.MSINAME, m.MSIURL, m.MSIIMG, m.MSINOTE, m.MSITYPE, m.UNTTYPE, m.ISACTIVE, p.MSIPRICE,
                       COALESCE(m.LOWSTOCK, 1) AS LOWSTOCK,
                       COALESCE((SELECT i.MSISTOCK FROM MSIINV i WHERE i.MSIID = m.MSIID ORDER BY i.TS DESC, i.MSITRNID DESC LIMIT 1), 0) AS CURRENT_STOCK,
                       (SELECT i.TS FROM MSIINV i WHERE i.MSIID = m.MSIID ORDER BY i.TS DESC, i.MSITRNID DESC LIMIT 1) AS LAST_UPDATED
                FROM MSI m LEFT JOIN UNTS u ON m.UNTTYPE = u.UNTTYPE LEFT JOIN MSP p ON m.MSIID = p.MSIID
                {where_sql}
            ) sub
            {stock_having_sql}
            ORDER BY {sql_sort_column} {order.upper()}
        """
        inventory_items = db.execute(query, params).fetchall()
        return render_template(
            'misc_inventory.html', inventory_items=inventory_items, unit_types=db.execute("SELECT * FROM UNTS").fetchall(),
            misc_types=db.execute("SELECT * FROM MST").fetchall(), current_sort=sort_by, current_order=order,
            today_date=date.today().isoformat(), filters={'q': q, 'min_price': min_price, 'max_price': max_price, 'stock_filter': stock_filter, 'stock_display': stock_display_mode, 'misc_type': misc_type_filter}
        )