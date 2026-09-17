from flask import Blueprint, render_template, request, jsonify

from datetime import datetime, date

import sqlite3

visuals_bp = Blueprint('visuals_bp', __name__)



def get_db():

    conn = sqlite3.connect("inventory.db")

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON;")

    return conn



@visuals_bp.route('/visuals/sales', methods=['GET'])

def sales_visuals():

    """Render the interactive item sales visualization dashboard."""

    db = get_db()

    venues = db.execute("SELECT VENUEID, VENNAME FROM VENUE WHERE ISACTIVE = 1 ORDER BY VENNAME ASC").fetchall()

    return render_template(

        'item_sales_visuals.html',

        venues=venues,

        today_date=date.today().isoformat()

    )



@visuals_bp.route('/visuals/api/venue-date-bounds', methods=['POST'])

def api_venue_date_bounds():

    """Return min start date and max end date for selected venues based on VSDATE and VEDATE."""

    try:

        db = get_db()

        req_data = request.get_json() or {}

        venue_ids = req_data.get('venue_ids', [])

        

        if not venue_ids:

            return jsonify({'status': 'success', 'min_date': None, 'max_date': None})

            

        placeholders = ','.join(['?'] * len(venue_ids))

        query = f"""

            SELECT MIN(VSDATE) as min_date, MAX(VEDATE) as max_date 

            FROM VENUE 

            WHERE VENUEID IN ({placeholders})

        """

        row = db.execute(query, venue_ids).fetchone()

        return jsonify({

            'status': 'success', 

            'min_date': row['min_date'] if row and row['min_date'] else None, 

            'max_date': row['max_date'] if row and row['max_date'] else None

        })

    except Exception as e:

        return jsonify({'status': 'error', 'message': str(e)}), 500



@visuals_bp.route('/visuals/api/filter-options', methods=['POST'])

def api_filter_options():

    """Return dynamic item groups and items based on active date range and venues."""

    try:

        db = get_db()

        req_data = request.get_json() or {}

        

        start_date = req_data.get('start_date')

        end_date = req_data.get('end_date')

        venue_ids = req_data.get('venue_ids', [])

        actively_selling = req_data.get('actively_selling', '1')



        where_clauses = ["1=1"]

        params = []



        if start_date:

            where_clauses.append("s.SDATE >= ?")

            params.append(start_date)

        if end_date:

            where_clauses.append("s.SDATE <= ?")

            params.append(end_date)

        if venue_ids:

            placeholders = ','.join(['?'] * len(venue_ids))

            where_clauses.append(f"s.VENUEID IN ({placeholders})")

            params.extend(venue_ids)

        if actively_selling is not None and actively_selling != 'all':

            where_clauses.append("i.CURRENT = ?")

            params.append(int(actively_selling))



        where_str = " AND ".join(where_clauses)



        groups_query = f"""

            SELECT DISTINCT i.ITMGRP 

            FROM ITMSALE s

            JOIN ITM i ON s.ITEMID = i.ITEMID

            WHERE {where_str} AND i.ITMGRP IS NOT NULL AND i.ITMGRP != ''

            ORDER BY i.ITMGRP ASC

        """

        groups = [row['ITMGRP'] for row in db.execute(groups_query, params).fetchall()]



        items_query = f"""

            SELECT DISTINCT i.ITEMID, i.ITMNAME, i.ITMGRP, i.ITMIMG AS IMAGE_URL 

            FROM ITMSALE s

            JOIN ITM i ON s.ITEMID = i.ITEMID

            WHERE {where_str}

            ORDER BY i.ITMNAME ASC

        """

        items = [dict(row) for row in db.execute(items_query, params).fetchall()]



        return jsonify({'status': 'success', 'groups': groups, 'items': items})

    except Exception as e:

        return jsonify({'status': 'error', 'message': str(e)}), 500



@visuals_bp.route('/visuals/api/sales-data', methods=['POST'])

def api_sales_data():

    """API endpoint returning filtered sales records with date-matched historical pricing from IPC."""

    try:

        db = get_db()

        req_data = request.get_json() or {}

        

        start_date = req_data.get('start_date')

        end_date = req_data.get('end_date')

        venue_ids = req_data.get('venue_ids', [])

        item_ids = req_data.get('item_ids', [])

        item_groups = req_data.get('item_groups', [])

        actively_selling = req_data.get('actively_selling')



        query = """

            SELECT s.SALEID, s.SUNITS, s.SDATE, s.VENUEID, 

                   i.ITEMID, i.ITMNAME, i.ITMIMG AS IMAGE_URL, i.ITMGRP, i.CURRENT, i.ISACTIVE,

                   COALESCE(v.VENNAME, 'Direct / Studio Sale') AS VENNAME,

                   COALESCE(ipc.ITMPRICE, 0.0) AS SPRICE

            FROM ITMSALE s

            JOIN ITM i ON s.ITEMID = i.ITEMID

            LEFT JOIN VENUE v ON s.VENUEID = v.VENUEID

            LEFT JOIN IPC ipc ON s.ITEMID = ipc.ITEMID 

                 AND s.SDATE >= ipc.STDATE 

                 AND (ipc.ENDDATE IS NULL OR s.SDATE <= ipc.ENDDATE)

            WHERE 1=1

        """

        params = []



        if start_date:

            query += " AND s.SDATE >= ?"

            params.append(start_date)

        if end_date:

            query += " AND s.SDATE <= ?"

            params.append(end_date)

        if venue_ids:

            placeholders = ','.join(['?'] * len(venue_ids))

            query += f" AND s.VENUEID IN ({placeholders})"

            params.extend(venue_ids)

        if item_ids:

            placeholders = ','.join(['?'] * len(item_ids))

            query += f" AND s.ITEMID IN ({placeholders})"

            params.extend(item_ids)

        if item_groups:

            placeholders = ','.join(['?'] * len(item_groups))

            query += f" AND i.ITMGRP IN ({placeholders})"

            params.extend(item_groups)

        if actively_selling is not None and actively_selling != 'all':

            query += " AND i.CURRENT = ?"

            params.append(int(actively_selling))



        query += " ORDER BY s.SDATE ASC"



        rows = db.execute(query, params).fetchall()

        sales = [dict(row) for row in rows]



        return jsonify({'status': 'success', 'sales': sales})

    except Exception as e:

        return jsonify({'status': 'error', 'message': str(e)}), 500

