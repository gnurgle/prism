from flask import Blueprint, render_template, request, redirect, url_for, flash

from datetime import date, datetime, timedelta

from utils import process_and_save_image



misc_bp = Blueprint('misc_bp', __name__)



def get_db_from_app():

    from __main__ import get_db

    return get_db()



@misc_bp.route('/misc_items')

def list_misc():

    db = get_db_from_app()



    sort_by = request.args.get('sort_by', 'MSITYPE')

    order = request.args.get('order', 'asc').lower()

    if order not in ['asc', 'desc']:

        order = 'asc'



    q = request.args.get('q', '').strip()

    min_price = request.args.get('min_price', '').strip()

    max_price = request.args.get('max_price', '').strip()

    is_active = request.args.get('is_active', '1').strip()

    item_id = request.args.get('item_id', '').strip()

    item_name = request.args.get('item_name', '').strip()

    msi_type = request.args.get('msi_type', '').strip()

    active_only = request.args.get('active_only', '')



    allowed_sorts = {

        'MSIID': 'm.MSIID',

        'MSINAME': 'm.MSINAME',

        'MSIPRICE': 'p.MSIPRICE',

        'MSITYPE': 'm.MSITYPE',

        'UNTS': 'm.MSIUNIT'

    }

    sort_column = allowed_sorts.get(sort_by, 'm.MSITYPE')



    where_clauses = []

    params = []



    if is_active != 'all':

        where_clauses.append("m.ISACTIVE = ?")

        params.append(1 if is_active == '1' else 0)



    if q:

        where_clauses.append("(m.MSINAME LIKE ? OR m.MSINOTE LIKE ?)")

        params.extend([f"%{q}%", f"%{q}%"])

    if min_price:

        where_clauses.append("p.MSIPRICE >= ?")

        params.append(min_price)

    if max_price:

        where_clauses.append("p.MSIPRICE <= ?")

        params.append(max_price)

    if msi_type:

        where_clauses.append("m.MSITYPE = ?")

        params.append(msi_type)



    join_igc = ""

    if item_id:

        # Use the IMI table (Item to Misc Item Link) which contains ITEMID and MSIID

        join_igc = "INNER JOIN IMI l ON m.MSIID = l.MSIID"

        where_clauses.append("l.ITEMID = ?")

        params.append(item_id)

       

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""



    query = f"""

        SELECT DISTINCT m.*, p.MSIPRICE, u.UNTTYPE AS UNIT_LABEL 

        FROM MSI m

        LEFT JOIN MSP p ON m.MSIID = p.MSIID

        LEFT JOIN UNTS u ON m.UNTTYPE = u.UNTTYPE

        {join_igc}

        {where_sql}

        ORDER BY {sort_column} {order.upper()}

    """

    misc_items = db.execute(query, params).fetchall()

    misc_types = db.execute('SELECT * FROM MST').fetchall()



    # Fetch items list for the filter modal dropdown (matching glass inventory implementation)

    items = db.execute("""

        SELECT ITEMID, ITMNAME, ITMGRP AS itmgrp, CURRENT 

        FROM ITM 

        ORDER BY ITMGRP ASC, ITMNAME ASC

    """).fetchall()



    return render_template(

        'misc_list.html',

        misc_items=misc_items,

        current_sort=sort_by,

        current_order=order,

        misc_types=misc_types,

        items=items,

        filters={

            'q': q, 

            'min_price': min_price, 

            'max_price': max_price,

            'is_active': is_active,

            'item_id': item_id, 

            'item_name': item_name,

            'msi_type': msi_type, 

            'active_only': active_only

        }

    )


@misc_bp.route("/misc_items/new", methods=["GET", "POST"])

def create_misc():

    db = get_db_from_app()



    if request.method == "POST":

        msiname = request.form.get('MSINAME')

        msistock = request.form.get('MSISTOCK') or 0

        msiurl = request.form.get('MSIURL')

        msinote = request.form.get('MSINOTE')

        msiunit = request.form.get('MSIUNIT') or 0

        unttype = request.form.get('UNTTYPE') or None

        msitype = request.form.get('MSITYPE') or None

        msiprice = request.form.get('MSIPRICE')

        isactive = 1



        cursor = db.execute(

            """

            INSERT INTO MSI (MSINAME, MSIIMG, MSISTOCK, MSIURL, 

                MSINOTE, MSIUNIT, UNTTYPE, MSITYPE, ISACTIVE)

                VALUES (?,?,?,?,?,?,?,?,?)

            """,

            (

                msiname, None, msistock, msiurl,

                msinote, msiunit, unttype, msitype, isactive

            ),

        )



        misc_id = cursor.lastrowid



        file = request.files.get("MSIIMG_FILE")

        if file and file.filename != '':

            pattern_name = f"{misc_id}_{msiname}"

            msiimg_path = process_and_save_image(

                file_obj=file,

                upload_subfolder='images/misc',

                custom_filename_base=pattern_name,

                target_size=(256, 256)

            )

            db.execute("UPDATE MSI SET MSIIMG = ? WHERE MSIID = ?", (msiimg_path, misc_id))



        if msiprice:

            db.execute(

                """

                INSERT INTO MSP (MSIID, MSIPRICE, STDATE) VALUES (?, ?, DATE('now'))

                """,

                (misc_id, msiprice),

            )



        db.commit()

        flash("Misc Item recorded successfully!", "success")

        return redirect(url_for("misc_bp.list_misc"))



    unit_types = db.execute("SELECT * FROM UNTS").fetchall()

    misc_types = db.execute("SELECT * FROM MST").fetchall()



    return render_template(

        "misc_form.html", unit_types=unit_types, misc_types=misc_types

    )



@misc_bp.route('/misc_item/<int:misc_id>')

def misc_detail(misc_id):

    db = get_db_from_app()



    misc = db.execute('''

        SELECT m.*, u.UNTTYPE, u.CFACTOR

        FROM MSI m

        JOIN UNTS u ON m.UNTTYPE = u.UNTTYPE

        WHERE m.MSIID = ?

    ''', (misc_id,)).fetchone()



    if not misc:

        flash('Misc Item record not found.', 'danger')

        return redirect(url_for('misc_bp.list_misc'))



    items = db.execute('''

        SELECT m.*, i.IMIAMT, t.ITMNAME

        FROM MSI m

        LEFT JOIN UNTS u ON m.UNTTYPE = u.UNTTYPE

        LEFT JOIN IMI i on m.MSIID = i.MSIID

        LEFT JOIN ITM t ON i.ITEMID = t.ITEMID

        WHERE m.MSIID = ?

    ''', (misc_id,)).fetchall()



    current_price = db.execute(

        """

          SELECT MSIPRICE AS PRICE FROM MSP 

          WHERE MSIID = ? AND (ENDDATE IS NULL OR ENDDATE >= DATE('now'))

          ORDER BY STDATE DESC LIMIT 1

        """,

        (misc_id,),

    ).fetchone()

  

    lowest_price = db.execute(

        """

          SELECT MSIPRICE AS PRICE, STDATE AS START_DATE, ENDDATE AS END_DATE FROM MSP 

          WHERE MSIID = ? 

          ORDER BY MSIPRICE ASC LIMIT 1

        """,

        (misc_id,),

    ).fetchone()

  

    highest_price = db.execute(

        """

          SELECT MSIPRICE AS PRICE, STDATE AS START_DATE, ENDDATE AS END_DATE FROM MSP 

          WHERE MSIID = ?

          ORDER BY MSIPRICE DESC LIMIT 1

        """,

        (misc_id,),

    ).fetchone()

  

    return render_template(

        'misc_detail.html', misc=misc, items=items, current_price=current_price, lowest_price=lowest_price,

        highest_price=highest_price

    )



@misc_bp.route('/misc_items/edit/<int:misc_id>', methods=['GET', 'POST'])

def edit_misc(misc_id):

    db = get_db_from_app()



    misc = db.execute('''

        SELECT m.*, p.MSIPRICE 

        FROM MSI m 

        LEFT JOIN MSP p ON m.MSIID = p.MSIID 

        WHERE m.MSIID = ?

    ''', (misc_id,)).fetchone()



    if not misc:

        flash('Misc Item record not found.', 'danger')

        return redirect(url_for('misc_bp.list_misc'))



    if request.method == 'POST':

        msiname = request.form.get('MSINAME')

        msistock = request.form.get('MSISTOCK') or 0

        msiurl = request.form.get('MSIURL')

        msinote = request.form.get('MSINOTE')

        msiunit = request.form.get('MSIUNIT') or 0

        unttype = request.form.get('UNTTYPE') or None

        msitype = request.form.get('MSITYPE') or None

        msiprice = request.form.get('MSIPRICE')



        file = request.files.get('MSIIMG_FILE')

        if file and file.filename != '':

            pattern_name = f"{misc_id}_{msiname}"

            msiimg = process_and_save_image(

                file_obj=file,

                upload_subfolder='images/misc',

                custom_filename_base=pattern_name,

                target_size=(256, 256)

            )

        else:

            msiimg = request.form.get('MSIIMG') or misc['MSIIMG']



        db.execute(

            '''

            UPDATE MSI 

            SET MSINAME = ?, MSIIMG = ?, MSISTOCK = ?, MSIURL = ?, 

                MSINOTE = ?, MSIUNIT = ?, UNTTYPE = ?, MSITYPE = ?

            WHERE MSIID = ?

        ''',

            (

                msiname, msiimg, msistock, msiurl,

                msinote, msiunit, unttype, msitype, misc_id

            ),

        )



        if msiprice:

            existing_price = db.execute(

                'SELECT * FROM MSP WHERE MSIID = ?', (misc_id,)

            ).fetchone()

            if existing_price:

                db.execute(

                    '''

                    UPDATE MSP SET MSIPRICE = ?, STDATE = DATE('now') WHERE MSIID = ?

                ''',

                    (msiprice, misc_id),

                )

            else:

                db.execute(

                    '''

                    INSERT INTO MSP (MSIID, MSIPRICE, STDATE) VALUES (?, ?, DATE('now'))

                ''',

                    (misc_id, msiprice),

                )



        db.commit()

        flash('Misc details updated successfully!', 'success')

        return redirect(url_for('misc_bp.misc_detail', misc_id=misc_id))



    unit_types = db.execute("SELECT * FROM UNTS").fetchall()

    misc_types = db.execute("SELECT * FROM MST").fetchall()



    return render_template(

        'misc_form.html', misc=misc, unit_types=unit_types, misc_types=misc_types,

        action='Edit',

    )



@misc_bp.route('/misc_items/delete/<int:misc_id>', methods=['POST'])

def delete_misc(misc_id):

    db = get_db_from_app()

    db.execute("UPDATE MSI SET ISACTIVE = 0 WHERE MSIID = ?", (misc_id,))

    db.commit()

    

    flash(f"Misc Item #{misc_id} deactivated successfully.", "warning")

    return redirect(url_for('misc_bp.list_misc'))



@misc_bp.route('/misc_items/inventory', methods=['GET', 'POST'])

def misc_inventory():

    db = get_db_from_app()

    if request.method == 'POST':

        misc_id = request.form.get('MSIID')

        adjustment = request.form.get('MSISTOCK')

        trans_date = request.form.get('TS') or date.today().isoformat()



        if misc_id and adjustment:

            db.execute(

                """

                INSERT INTO MSIINV (MSIID, MSISTOCK, TS)

                VALUES (?, ?, ?)

                """,

                (misc_id, int(adjustment), trans_date)

            )

            db.commit()

            flash("Inventory level adjusted successfully!", "success")

        else:

            flash("Invalid input parameters for stock adjustment.", "danger")

            

        return redirect(url_for('misc_bp.misc_inventory'))



    sort_by = request.args.get('sort_by', 'MSINAME')

    order = request.args.get('order', 'asc').lower()

    if order not in ['asc', 'desc']:

        order = 'asc'



    q = request.args.get('q', '').strip()

    min_price = request.args.get('min_price', '').strip()

    max_price = request.args.get('max_price', '').strip()

    stock_filter = request.args.get('stock_filter', '').strip()

    stock_display_mode = request.args.get('stock_display', 'all')

    misc_type_filter = request.args.get('misc_type', '').strip()



    allowed_sorts = {

        'MSIID': 'MSIID',

        'MSINAME': 'MSINAME',

        'MSIPRICE': 'MSIPRICE',

        'MSITYPE': 'MSITYPE',

        'CURRENT_STOCK': 'CURRENT_STOCK',

        'LAST_UPDATED': 'LAST_UPDATED'

    }

    sql_sort_column = 'MSINAME' if sort_by == 'MSITYPE' else allowed_sorts.get(sort_by, 'MSINAME')



    where_clauses = ["m.ISACTIVE = 1"]

    params = []



    if q:

        where_clauses.append("(m.MSINAME LIKE ? OR m.MSINOTE LIKE ?)")

        params.extend([f"%{q}%", f"%{q}%"])



    if misc_type_filter:

        where_clauses.append("m.MSITYPE = ?")

        params.append(misc_type_filter)



    where_sql = f"WHERE {' AND '.join(where_clauses)}"



    having_conditions = []

    if stock_filter == 'out':

        having_conditions.append("CURRENT_STOCK = 0")

    elif stock_filter == 'low':

        having_conditions.append("CURRENT_STOCK = 1")

    elif stock_filter == 'in':

        having_conditions.append("CURRENT_STOCK > 1")



    if stock_display_mode == 'out':

        having_conditions.append("CURRENT_STOCK <= 0")

    elif stock_display_mode == 'hide':

        having_conditions.append("CURRENT_STOCK > 0")



    stock_having_sql = f"GROUP BY MSIID, MSINAME, MSIURL, MSIIMG, MSINOTE, MSITYPE, UNTTYPE, ISACTIVE, MSIPRICE, CURRENT_STOCK, LAST_UPDATED HAVING {' AND '.join(having_conditions)}" if having_conditions else ""



    query = f"""

        SELECT MSIID, MSINAME, MSIURL, MSIIMG, MSINOTE, MSITYPE, UNTTYPE, 

               ISACTIVE, MSIPRICE, CURRENT_STOCK, LAST_UPDATED

        FROM (

            SELECT m.MSIID, m.MSINAME, m.MSIURL, m.MSIIMG, 

                   m.MSINOTE, m.MSITYPE, m.UNTTYPE, m.ISACTIVE, p.MSIPRICE,

                   COALESCE((

                       SELECT i.MSISTOCK 

                       FROM MSIINV i 

                       WHERE i.MSIID = m.MSIID 

                       ORDER BY i.TS DESC, i.MSITRNID DESC 

                       LIMIT 1

                   ), 0) AS CURRENT_STOCK,

                   (

                       SELECT i.TS 

                       FROM MSIINV i 

                       WHERE i.MSIID = m.MSIID 

                       ORDER BY i.TS DESC, i.MSITRNID DESC 

                       LIMIT 1

                   ) AS LAST_UPDATED

            FROM MSI m

            LEFT JOIN UNTS u ON m.UNTTYPE = u.UNTTYPE

            LEFT JOIN MSP p ON m.MSIID = p.MSIID

            {where_sql}

        ) sub

        {stock_having_sql}

        ORDER BY {sql_sort_column} {order.upper()}

    """

    inventory_items = db.execute(query, params).fetchall()

    unit_types = db.execute("SELECT * FROM UNTS").fetchall()

    misc_types = db.execute("SELECT * FROM MST").fetchall()



    return render_template(

        'misc_inventory.html',

        inventory_items=inventory_items,

        unit_types=unit_types,

        misc_types=misc_types,

        current_sort=sort_by,

        current_order=order,

        today_date=date.today().isoformat(),

        filters={

            'q': q, 'min_price': min_price, 'max_price': max_price,

            'stock_filter': stock_filter, 'stock_display': stock_display_mode,

            'misc_type': misc_type_filter

        }

    )



@misc_bp.route('/prices/misc/<int:misc_id>/edit', methods=['GET', 'POST'])

def edit_misc_prices(misc_id):

    db = get_db_from_app()

    misc = db.execute('SELECT * FROM MSI WHERE MSIID = ?', (misc_id,)).fetchone()



    if not misc:

        flash('Misc Item record not found.', 'danger')

        return redirect(url_for('misc_bp.list_misc'))



    if request.method == 'POST':

        try:

            new_price = float(request.form.get('MSIPRICE'))

        except (TypeError, ValueError):

            flash('Invalid price value provided.', 'danger')

            return redirect(url_for('misc_bp.edit_misc_prices', misc_id=misc_id))



        new_st_str = request.form.get('STDATE')

        is_current = 1 if request.form.get('is_current') else 0

        new_end_str = None if is_current else request.form.get('ENDDATE')



        new_st = datetime.strptime(new_st_str, '%Y-%m-%d').date()

        new_end = (

            datetime.strptime(new_end_str, '%Y-%m-%d').date()

            if new_end_str

            else None

        )



        if new_end and new_st > new_end:

            flash('Start date cannot be after the end date.', 'danger')

            return redirect(url_for('misc_bp.edit_misc_prices', misc_id=misc_id))



        cursor = db.cursor()

        existing_prices = cursor.execute(

            """

            SELECT rowid, MSIPRICE, STDATE, ENDDATE FROM MSP 

            WHERE MSIID = ?

            """,

            (misc_id,),

        ).fetchall()



        for row in existing_prices:

            row_id = row['rowid']

            ex_st_str = row['STDATE']

            ex_end_str = row['ENDDATE']



            ex_st = datetime.strptime(ex_st_str, '%Y-%m-%d').date() if ex_st_str else None

            ex_end = datetime.strptime(ex_end_str, '%Y-%m-%d').date() if ex_end_str else None



            if ex_st and new_st <= ex_st and (new_end is None or (ex_end and new_end >= ex_end)):

                cursor.execute('DELETE FROM MSP WHERE rowid = ?', (row_id,))

                continue



            if ex_st and ex_end and new_st > ex_st and new_end and new_end < ex_end:

                split_end_date = (new_st - timedelta(days=1)).strftime('%Y-%m-%d')

                cursor.execute(

                    'UPDATE MSP SET ENDDATE = ? WHERE rowid = ?',

                    (split_end_date, row_id)

                )

                tail_start_date = (new_end + timedelta(days=1)).strftime('%Y-%m-%d')

                cursor.execute(

                    'INSERT INTO MSP (MSIID, MSIPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, ?)',

                    (misc_id, row['MSIPRICE'], tail_start_date, ex_end_str)

                )

                continue



            if ex_st and new_st > ex_st and (ex_end is None or new_st <= ex_end):

                new_ex_end = (new_st - timedelta(days=1)).strftime('%Y-%m-%d')

                cursor.execute(

                    'UPDATE MSP SET ENDDATE = ? WHERE rowid = ?',

                    (new_ex_end, row_id)

                )



            if new_end and ex_end and new_end >= ex_st and new_end < ex_end:

                new_ex_st = (new_end + timedelta(days=1)).strftime('%Y-%m-%d')

                cursor.execute(

                    'UPDATE MSP SET STDATE = ? WHERE rowid = ?',

                    (new_ex_st, row_id)

                )



            if is_current and ex_st and ex_st >= new_st:

                cursor.execute('DELETE FROM MSP WHERE rowid = ?', (row_id,))



        cursor.execute(

            """

            INSERT INTO MSP (MSIID, MSIPRICE, STDATE, ENDDATE)

            VALUES (?, ?, ?, ?)

            """,

            (misc_id, new_price, new_st_str, new_end_str),

        )



        db.commit()

        flash('Misc price range successfully saved and overlapping intervals adjusted.', 'success')

        return redirect(url_for('misc_bp.edit_misc_prices', misc_id=misc_id))



    prices = db.execute(

        """

        SELECT rowid, MSIPRICE, STDATE, ENDDATE FROM MSP 

        WHERE MSIID = ? 

        ORDER BY STDATE DESC

        """,

        (misc_id,),

    ).fetchall()



    return render_template(

        'misc_edit_prices.html', misc=misc, prices=prices

    )



@misc_bp.route('/prices/misc/<int:misc_id>/delete/<int:price_id>', methods=['POST'])

def delete_misc_price(misc_id, price_id):

    db = get_db_from_app()

    db.execute('DELETE FROM MSP WHERE rowid = ? AND MSIID = ?', (price_id, misc_id))

    db.commit()

    flash('Misc price tier removed.', 'success')

    return redirect(url_for('misc_bp.edit_misc_prices', misc_id=misc_id))
