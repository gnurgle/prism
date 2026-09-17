from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for

from datetime import datetime

import sqlite3

production_bp = Blueprint('production_bp', __name__)



def get_db_from_app():

    conn = sqlite3.connect("inventory.db")

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON;")

    return conn



@production_bp.route('/production', methods=['GET'])

def production_board():

    db = get_db_from_app()

    

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

    

    # Fetch item groups for modal filter dropdowns

    item_groups = db.execute("SELECT ITMGRP FROM IGP WHERE ISACTIVE = 1 OR ISACTIVE IS NULL ORDER BY ITMGRP ASC").fetchall()

    

    # Fetch all items directly, disregarding parent/variant hierarchies for the dropdown selection

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

        'production_board.html',

        items=items,

        summary=summary,

        item_groups=item_groups,

        master_items=master_items

    )


@production_bp.route('/production/add-item', methods=['POST'])

def add_item_to_production():

    db = get_db_from_app()

    data = request.get_json()

    

    if not data:

        return jsonify({'success': False, 'error': 'Invalid payload'}), 400



    item_id = data.get('item_id')

    target_stage = data.get('stage')

    quantity = int(data.get('quantity', 1))



    valid_stages = {

        'cut': 'IPCUT',

        'grnd': 'IPGRND',

        'wash': 'IPWASH',

        'foil': 'IPFOIL',

        'sldr': 'IPSLDR',

        'polish': 'IPPOLISH',

        'done': 'IPDONE'

    }



    if target_stage not in valid_stages or not item_id:

        return jsonify({'success': False, 'error': 'Invalid stage or item selection'}), 400



    col_name = valid_stages[target_stage]

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')



    existing = db.execute("SELECT IPID, * FROM ICC WHERE ITEMID = ?", (item_id,)).fetchone()



    if existing:

        current_val = existing[col_name] or 0

        new_val = current_val + quantity

        db.execute(f"UPDATE ICC SET {col_name} = ?, IPTS = ? WHERE ITEMID = ?", (new_val, timestamp, item_id))

    else:

        vals = {v: 0 for v in valid_stages.values()}

        vals[col_name] = quantity

        db.execute("""

            INSERT INTO ICC (ITEMID, IPCUT, IPGRND, IPWASH, IPFOIL, IPSLDR, IPPOLISH, IPDONE, IPTS)

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

        """, (

            item_id, 

            vals['IPCUT'], vals['IPGRND'], vals['IPWASH'], 

            vals['IPFOIL'], vals['IPSLDR'], vals['IPPOLISH'], vals['IPDONE'], 

            timestamp

        ))



    db.commit()

    return jsonify({'success': True})



@production_bp.route('/production/update', methods=['POST'])

def update_production_stage():

    db = get_db_from_app()

    data = request.get_json()

    

    if not data:

        return jsonify({'success': False, 'error': 'Invalid payload'}), 400



    item_id = data.get('item_id')

    target_stage = data.get('stage')

    delta = int(data.get('delta', 0))



    valid_stages = {

        'cut': 'IPCUT',

        'grnd': 'IPGRND',

        'wash': 'IPWASH',

        'foil': 'IPFOIL',

        'sldr': 'IPSLDR',

        'polish': 'IPPOLISH',

        'done': 'IPDONE'

    }



    if target_stage not in valid_stages:

        return jsonify({'success': False, 'error': 'Invalid production stage'}), 400



    col_name = valid_stages[target_stage]

    existing = db.execute("SELECT IPID, * FROM ICC WHERE ITEMID = ?", (item_id,)).fetchone()

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')



    if existing:

        current_val = existing[col_name] or 0

        new_val = max(0, current_val + delta)

        db.execute(f"UPDATE ICC SET {col_name} = ?, IPTS = ? WHERE ITEMID = ?", (new_val, timestamp, item_id))

    else:

        vals = {v: 0 for v in valid_stages.values()}

        vals[col_name] = max(0, delta)

        db.execute("""

            INSERT INTO ICC (ITEMID, IPCUT, IPGRND, IPWASH, IPFOIL, IPSLDR, IPPOLISH, IPDONE, IPTS)

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

        """, (

            item_id, 

            vals['IPCUT'], vals['IPGRND'], vals['IPWASH'], 

            vals['IPFOIL'], vals['IPSLDR'], vals['IPPOLISH'], vals['IPDONE'], 

            timestamp

        ))



    db.commit()

    

    summary = db.execute("""

        SELECT 

            SUM(COALESCE(IPCUT, 0)) as total_cut,

            SUM(COALESCE(IPGRND, 0)) as total_grind,

            SUM(COALESCE(IPWASH, 0)) as total_wash,

            SUM(COALESCE(IPFOIL, 0)) as total_foil,

            SUM(COALESCE(IPSLDR, 0)) as total_solder,

            SUM(COALESCE(IPPOLISH, 0)) as total_polish,

            SUM(COALESCE(IPDONE, 0)) as total_done

        FROM ICC

    """).fetchone()



    return jsonify({'success': True, 'summary': dict(summary)})


@production_bp.route('/production/save-finished', methods=['POST'])

def save_finished_items():

    db = get_db_from_app()

    data = request.get_json()

    item_id = data.get('item_id')



    if not item_id:

        return jsonify({'success': False, 'error': 'No item specified'}), 400



    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')



    # 1. Fetch current IPDONE amount for the item from ICC

    icc_record = db.execute("SELECT IPDONE FROM ICC WHERE ITEMID = ?", (item_id,)).fetchone()

    if not icc_record or not icc_record['IPDONE'] or icc_record['IPDONE'] <= 0:

        return jsonify({'success': False, 'error': 'No finished items to save'}), 400



    finished_qty = icc_record['IPDONE']



    # 2. Get the latest stock entry from ITMINV to calculate the new total sum

    last_inv = db.execute("""

        SELECT ITMSTOCK FROM ITMINV 

        WHERE ITEMID = ? 

        ORDER BY ITMTRNID DESC LIMIT 1

    """, (item_id,)).fetchone()

    

    previous_stock = last_inv['ITMSTOCK'] if last_inv and last_inv['ITMSTOCK'] is not None else 0

    new_total_stock = previous_stock + finished_qty



    # 3. Create a new entry in ITMINV with the new cumulative total

    db.execute("""

        INSERT INTO ITMINV (ITEMID, ITMSTOCK, TS)

        VALUES (?, ?, ?)

    """, (item_id, new_total_stock, timestamp))



    # 4. Set the Done amount (IPDONE) back to 0 in ICC

    db.execute("""

        UPDATE ICC 

        SET IPDONE = 0, IPTS = ? 

        WHERE ITEMID = ?

    """, (timestamp, item_id))



    # 5. Optional history logging reflection (e.g., tracking entry in IHS or ITH as per schema requirements)

    db.commit()



    # Return refreshed summary stats

    summary = db.execute("""

        SELECT 

            SUM(COALESCE(IPCUT, 0)) as total_cut,

            SUM(COALESCE(IPGRND, 0)) as total_grind,

            SUM(COALESCE(IPWASH, 0)) as total_wash,

            SUM(COALESCE(IPFOIL, 0)) as total_foil,

            SUM(COALESCE(IPSLDR, 0)) as total_solder,

            SUM(COALESCE(IPPOLISH, 0)) as total_polish,

            SUM(COALESCE(IPDONE, 0)) as total_done

        FROM ICC

    """).fetchone()



    return jsonify({'success': True, 'summary': dict(summary)})


@production_bp.route('/production/bulk', methods=['GET'])

def bulk_production_page():

    today_date = datetime.now().strftime('%Y-%m-%d')

    return render_template('item_bulk_production.html', today_date=today_date)



@production_bp.route('/production/bulk/data', methods=['GET'])

def api_bulk_production_data():

    db = get_db_from_app()

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

        if item_dict.get('CURRENT_STOCK') is None:

            item_dict['CURRENT_STOCK'] = 0

        items_list.append(item_dict)

        

    return jsonify({'items': items_list})


@production_bp.route('/production/bulk/submit', methods=['POST'])

def bulk_production_submit():

    db = get_db_from_app()

    data = request.get_json()

    

    if not data:

        return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400

        

    date_val = data.get('date')

    state_val = data.get('state')

    items = data.get('items', [])

    

    if not date_val or not state_val:

        return jsonify({'status': 'error', 'message': 'Missing date or state selection'}), 400

        

    timestamp = f"{date_val} 00:00:00" if len(date_val) == 10 else date_val

    

    valid_stages = {

        'cut': 'IPCUT',

        'grnd': 'IPGRND',

        'wash': 'IPWASH',

        'foil': 'IPFOIL',

        'sldr': 'IPSLDR',

        'polish': 'IPPOLISH',

        'done': 'IPDONE'

    }

    

    try:

        if state_val == 'in_stock':

            for item in items:

                item_id = item.get('ITEMID')

                qty = int(item.get('quantity', 0))

                if qty == 0:

                    continue

                

                # Check if an exact inventory record exists for this timestamp

                exact_inv = db.execute("""

                    SELECT ITMTRNID FROM ITMINV 

                    WHERE ITEMID = ? AND TS = ?

                """, (item_id, timestamp)).fetchone()

                

                if exact_inv:

                    # Update exact record and all subsequent records from this timestamp forward

                    db.execute("""

                        UPDATE ITMINV 

                        SET ITMSTOCK = ITMSTOCK + ? 

                        WHERE ITEMID = ? AND TS >= ?

                    """, (qty, item_id, timestamp))

                else:

                    # Find latest prior record to establish base stock

                    prior_inv = db.execute("""

                        SELECT ITMSTOCK FROM ITMINV 

                        WHERE ITEMID = ? AND TS < ? 

                        ORDER BY TS DESC, ITMTRNID DESC LIMIT 1

                    """, (item_id, timestamp)).fetchone()

                    

                    base_stock = prior_inv['ITMSTOCK'] if prior_inv and prior_inv['ITMSTOCK'] is not None else 0

                    new_stock = base_stock + qty

                    

                    # Insert new record at the selected timestamp

                    db.execute("""

                        INSERT INTO ITMINV (ITEMID, ITMSTOCK, TS)

                        VALUES (?, ?, ?)

                    """, (item_id, new_stock, timestamp))

                    

                    # Update all subsequent records strictly after this timestamp

                    db.execute("""

                        UPDATE ITMINV 

                        SET ITMSTOCK = ITMSTOCK + ? 

                        WHERE ITEMID = ? AND TS > ?

                    """, (qty, item_id, timestamp))

                    

        elif state_val in valid_stages:

            col_name = valid_stages[state_val]

            for item in items:

                item_id = item.get('ITEMID')

                qty = int(item.get('quantity', 0))

                if qty != 0:

                    existing = db.execute("SELECT IPID, * FROM ICC WHERE ITEMID = ?", (item_id,)).fetchone()

                    if existing:

                        current_val = existing[col_name] or 0

                        new_val = max(0, current_val + qty)

                        db.execute(f"UPDATE ICC SET {col_name} = ?, IPTS = ? WHERE ITEMID = ?", (new_val, timestamp, item_id))

                    else:

                        vals = {v: 0 for v in valid_stages.values()}

                        vals[col_name] = max(0, qty)

                        db.execute("""

                            INSERT INTO ICC (ITEMID, IPCUT, IPGRND, IPWASH, IPFOIL, IPSLDR, IPPOLISH, IPDONE, IPTS)

                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

                        """, (

                            item_id, 

                            vals['IPCUT'], vals['IPGRND'], vals['IPWASH'], 

                            vals['IPFOIL'], vals['IPSLDR'], vals['IPPOLISH'], vals['IPDONE'], 

                            timestamp

                        ))

        else:

            return jsonify({'status': 'error', 'message': 'Invalid state selection'}), 400

            

        db.commit()

        return jsonify({'status': 'success', 'message': 'Production bulk update saved successfully!'})

    except Exception as e:

        db.rollback()

        return jsonify({'status': 'error', 'message': str(e)}), 500
