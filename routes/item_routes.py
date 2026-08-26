from flask import Blueprint, render_template, request, redirect, url_for, flash

from datetime import datetime, timedelta

import os

import xml.etree.ElementTree as ET



# Define the Blueprint for items

item_bp = Blueprint('item_bp', __name__)



# Helper function to access the database (assuming it's imported or available from the main app context)

def get_db():

    from __main__ import get_db

    return get_db()



# Conversion Constants

SOLDER_CONVERSION = 0.3776

CAME_CONVERSION = 0.1652



@item_bp.route('/item/<int:item_id>', methods=['GET'])

def item_detail(item_id):

    """Display full details, pricing metrics, components, and group siblings using IMI mapping table."""

    db = get_db()



    raw_item = db.execute(

        'SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)

    ).fetchone()



    if not raw_item:

        flash('Item record not found.', 'danger')

        return redirect(url_for('index'))

    

    item = dict(raw_item)



    components = db.execute(

        """

            SELECT c.*, g.GLSNAME 

            FROM IGC c

            LEFT JOIN GSI g ON c.GLASSID = g.GLASSID

            WHERE c.ITEMID = ?

            ORDER BY c.COMPNUM ASC

        """,

        (item_id,),

    ).fetchall()



    current_price = db.execute(

        """

            SELECT ITMPRICE AS PRICE FROM IPC 

            WHERE ITEMID = ? AND (ENDDATE IS NULL OR ENDDATE >= DATE('now'))

            ORDER BY STDATE DESC LIMIT 1

        """,

        (item_id,),

    ).fetchone()



    lowest_price = db.execute(

        """

            SELECT ITMPRICE AS PRICE, STDATE AS START_DATE, ENDDATE AS END_DATE FROM IPC 

            WHERE ITEMID = ? 

            ORDER BY ITMPRICE ASC LIMIT 1

        """,

        (item_id,),

    ).fetchone()



    highest_price = db.execute(

        """

            SELECT ITMPRICE AS PRICE, STDATE AS START_DATE, ENDDATE AS END_DATE FROM IPC 

            WHERE ITEMID = ? 

            ORDER BY ITMPRICE DESC LIMIT 1

        """,

        (item_id,),

    ).fetchone()



    group_siblings = []

    if not item['ONEOFF'] and item['ITMGRP']:

        group_siblings = db.execute(

            """

                SELECT ITEMID, ITMNAME FROM ITM 

                WHERE ITMGRP = ? AND ONEOFF = 0

                ORDER BY ITMNAME ASC

            """,

            (item['ITMGRP'],),

        ).fetchall()



    components_with_cost = db.execute(

        """

            SELECT c.COMPLEN, c.COMPWID, g.GLSLEN, g.GLSWID, 

                   (SELECT gp.GLSPRICE FROM GPC gp 

                    WHERE gp.GLASSID = g.GLASSID AND (gp.ENDDATE IS NULL OR gp.ENDDATE >= DATE('now'))

                    ORDER BY gp.STDATE DESC LIMIT 1) AS LATEST_GLSPRICE

            FROM IGC c

            JOIN GSI g ON c.GLASSID = g.GLASSID

            WHERE c.ITEMID = ? AND c.COMPLEN IS NOT NULL AND c.COMPWID IS NOT NULL

                  AND g.GLSLEN IS NOT NULL AND g.GLSWID IS NOT NULL AND g.GLSLEN > 0 AND g.GLSWID > 0

        """,

        (item_id,),

    ).fetchall()



    materials_cost = 0.0

    for comp in components_with_cost:

        comp_sqin = (comp['COMPLEN'] or 0) * (comp['COMPWID'] or 0)

        glass_sheet_area = (comp['GLSLEN'] or 1) * (comp['GLSWID'] or 1)

        glass_sheet_price = comp['LATEST_GLSPRICE'] or 0.0

        

        if glass_sheet_area > 0:

            cost_per_sqin = glass_sheet_price / glass_sheet_area

            materials_cost += comp_sqin * cost_per_sqin



    associated_supplies_rows = db.execute(

        """

        SELECT msi.MSIID, msi.MSINAME, msi.MSITYPE, imi.IMIAMT, msi.MSIUNIT, u.CFACTOR

        FROM IMI imi

        JOIN MSI msi ON imi.MSIID = msi.MSIID

        LEFT JOIN UNTS u ON msi.UNTTYPE = u.UNTTYPE

        WHERE imi.ITEMID = ?

        """,

        (item_id,),

    ).fetchall()



    supplies_map = {row['MSITYPE']: row for row in associated_supplies_rows}



    associated_decorations = db.execute(

        """

        SELECT m.MSIID, m.MSINAME, i.IMIAMT, m.MSIUNIT, u.CFACTOR

        FROM IMI i

        JOIN MSI m ON i.MSIID = m.MSIID

        LEFT JOIN UNTS u ON m.UNTTYPE = u.UNTTYPE

        WHERE i.ITEMID = ? AND m.MSITYPE = 'Decoration'

        ORDER BY m.MSINAME ASC

        """,

        (item_id,),

    ).fetchall()



    item['MSLDR_NAME'] = supplies_map['Solder']['MSINAME'] if 'Solder' in supplies_map else ''

    item['MFOIL_NAME'] = supplies_map['Foil']['MSINAME'] if 'Foil' in supplies_map else ''

    item['MCAME_NAME'] = supplies_map['Came']['MSINAME'] if 'Came' in supplies_map else ''

    item['MCHAIN_NAME'] = supplies_map['Chain']['MSINAME'] if 'Chain' in supplies_map else ''

    item['MRING_NAME']  = supplies_map['Rings']['MSINAME'] if 'Rings' in supplies_map else ''

    item['MWIRE_NAME']  = supplies_map['Wire']['MSINAME'] if 'Wire' in supplies_map else ''



    raw_sldr = float(supplies_map['Solder']['IMIAMT']) if 'Solder' in supplies_map and supplies_map['Solder']['IMIAMT'] is not None else 0.0

    raw_came = float(supplies_map['Came']['IMIAMT']) if 'Came' in supplies_map and supplies_map['Came']['IMIAMT'] is not None else 0.0



    itm_supplies = {

        'ITMSLDR': (raw_sldr * SOLDER_CONVERSION * 2) + (raw_came * CAME_CONVERSION * 2),

        'ITMCAME': raw_came,

        'ITMFOIL': float(supplies_map['Foil']['IMIAMT']) if 'Foil' in supplies_map and supplies_map['Foil']['IMIAMT'] is not None else 0.0,

        'ITMCHAIN': float(supplies_map['Chain']['IMIAMT']) if 'Chain' in supplies_map and supplies_map['Chain']['IMIAMT'] is not None else 0.0,

        'ITMRING': float(supplies_map['Rings']['IMIAMT']) if 'Rings' in supplies_map and supplies_map['Rings']['IMIAMT'] is not None else 0,

        'ITMWIRE': float(supplies_map['Wire']['IMIAMT']) if 'Wire' in supplies_map and supplies_map['Wire']['IMIAMT'] is not None else 0.0

    }



    estimated_supplies_core_cost = 0.0



    for msi_type, qty in itm_supplies.items():

        type_lookup_map = {

            'ITMSLDR': 'Solder',

            'ITMFOIL': 'Foil',

            'ITMCAME': 'Came',

            'ITMCHAIN': 'Chain',

            'ITMRING': 'Rings',

            'ITMWIRE': 'Wire'

        }

        actual_type = type_lookup_map.get(msi_type)

        supply_data = supplies_map.get(actual_type)



        if qty and qty > 0 and supply_data and supply_data['MSIID']:

            misc_id = supply_data['MSIID']

            cfactor = supply_data['CFACTOR']

            msiunit = supply_data['MSIUNIT']



            price_row = db.execute(

                """

                    SELECT MSIPRICE AS PRICE FROM MSP 

                    WHERE MSIID = ? AND (ENDDATE IS NULL OR ENDDATE >= DATE('now'))

                    ORDER BY STDATE DESC LIMIT 1

                """,

                (misc_id,),

            ).fetchone()



            if price_row and price_row['PRICE']:

                unit_price = float(price_row['PRICE'])

                valid_cfactor = float(cfactor) if cfactor and float(cfactor) > 0 else 1.0

                valid_msiunit = float(msiunit) if msiunit is not None and float(msiunit) > 0 else 1.0

                

                divisor = valid_cfactor * valid_msiunit

                if divisor > 0 and unit_price > 0:

                    estimated_supplies_core_cost += qty * (unit_price / divisor)



    decorations_cost = 0.0

    for deco in associated_decorations:

        qty = float(deco['IMIAMT']) if deco['IMIAMT'] is not None else 0.0

        if qty > 0 and deco['MSIID']:

            misc_id = deco['MSIID']

            cfactor = deco['CFACTOR']

            msiunit = deco['MSIUNIT']



            price_row = db.execute(

                """

                    SELECT MSIPRICE AS PRICE FROM MSP 

                    WHERE MSIID = ? AND (ENDDATE IS NULL OR ENDDATE >= DATE('now'))

                    ORDER BY STDATE DESC LIMIT 1

                """,

                (misc_id,),

            ).fetchone()



            if price_row and price_row['PRICE']:

                unit_price = float(price_row['PRICE'])

                valid_cfactor = float(cfactor) if cfactor and float(cfactor) > 0 else 1.0

                valid_msiunit = float(msiunit) if msiunit is not None and float(msiunit) > 0 else 1.0

                

                divisor = valid_cfactor * valid_msiunit

                if divisor > 0 and unit_price > 0:

                    decorations_cost += qty * (unit_price / divisor)



    estimated_supplies_cost = estimated_supplies_core_cost + decorations_cost

    total_cost = materials_cost + estimated_supplies_cost



    return render_template(

        'item_detail.html',

        item=item,

        components=components,

        current_price=current_price,

        lowest_price=lowest_price,

        highest_price=highest_price,

        materials_cost=materials_cost,

        estimated_supplies_cost=estimated_supplies_cost,

        total_cost=total_cost,

        group_siblings=group_siblings,

        itm_supplies=itm_supplies,

        associated_supplies=associated_supplies_rows,

        associated_decorations=associated_decorations

    )



@item_bp.route('/item/new', methods=['GET', 'POST'])

def create_item():

    db = get_db()

    

    if request.method == 'POST':

        itmname = request.form.get('ITMNAME')

        itmgrp = request.form.get('ITMGRP') or None

        new_itmgrp = request.form.get('NEW_ITMGRP')

        

        if new_itmgrp and new_itmgrp.strip():

            itmgrp = new_itmgrp.strip()

            db.execute("INSERT OR IGNORE INTO IGP (ITMGRP, ISACTIVE) VALUES (?, 1)", (itmgrp,))



        itmlen = request.form.get('ITMLEN')

        itmwid = request.form.get('ITMWID')

        oneoff = 1 if request.form.get('ONEOFF') else 0

        current = 1 if request.form.get('CURRENT') else 0

        itmnote = request.form.get('ITMNOTE')

        

        cursor = db.execute(

            """

            INSERT INTO ITM (ITMNAME, ITMGRP, ITMLEN, ITMWID, ONEOFF, CURRENT, ITMNOTE, ISACTIVE)

            VALUES (?, ?, ?, ?, ?, ?, ?, 1)

            """,

            (itmname, itmgrp, itmlen or None, itmwid or None, oneoff, current, itmnote)

        )

        new_item_id = cursor.lastrowid



        from flask import current_app

        config_path = os.path.join(current_app.root_path, 'settings.config')

        if os.path.exists(config_path):

            try:

                tree = ET.parse(config_path)

                root = tree.getroot()

                defaults_elem = root.find('NewItemDefaults')

                if defaults_elem is not None:

                    config_field_map = {

                        'Solder': 'Solder',

                        'Foil': 'Foil',

                        'Came': 'Came',

                        'Chain': 'Chain',

                        'Rings': 'Rings'

                    }

                    for xml_tag, msi_type in config_field_map.items():

                        child = defaults_elem.find(xml_tag)

                        if child is not None and child.text and child.text.strip():

                            try:

                                default_msiid = int(child.text.strip())

                                exists = db.execute("SELECT 1 FROM MSI WHERE MSIID = ?", (default_msiid,)).fetchone()

                                if exists:

                                    db.execute(

                                        'INSERT INTO IMI (ITEMID, MSIID, IMIAMT) VALUES (?, ?, 0)',

                                        (new_item_id, default_msiid)

                                    )

                            except ValueError:

                                continue

            except ET.ParseError:

                pass



        db.commit()

        flash('Item created successfully!', 'success')

        return redirect(url_for('item_bp.item_detail', item_id=new_item_id))



    all_groups = db.execute('SELECT DISTINCT ITMGRP FROM ITM WHERE ITMGRP IS NOT NULL ORDER BY ITMGRP ASC').fetchall()

    all_msi = db.execute('SELECT MSIID, MSINAME, MSITYPE FROM MSI WHERE ISACTIVE = 1 ORDER BY MSINAME ASC').fetchall()

    return render_template('item_form.html', action='Create', item={}, groups=all_groups, 

                           msi_solder=[m for m in all_msi if m['MSITYPE'] == 'Solder'],

                           msi_foil=[m for m in all_msi if m['MSITYPE'] == 'Foil'],

                           msi_came=[m for m in all_msi if m['MSITYPE'] == 'Came'],

                           msi_chain=[m for m in all_msi if m['MSITYPE'] == 'Chain'],

                           msi_rings=[m for m in all_msi if m['MSITYPE'] == 'Rings'],

                           msi_wire=[m for m in all_msi if m['MSITYPE'] == 'Wire'])



@item_bp.route('/item/<int:item_id>/edit', methods=['GET', 'POST'])

def edit_item(item_id):

    db = get_db()

    

    item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()

    if not item:

        flash('Item not found.', 'danger')

        return redirect(url_for('index'))



    if request.method == 'POST':

        itmname = request.form.get('ITMNAME')

        itmgrp = request.form.get('ITMGRP') or None

        new_itmgrp = request.form.get('NEW_ITMGRP')

        

        if new_itmgrp and new_itmgrp.strip():

            itmgrp = new_itmgrp.strip()

            db.execute(

                "INSERT OR IGNORE INTO IGP (ITMGRP, ISACTIVE) VALUES (?, 1)",

                (itmgrp,)

            )



        itmlen = request.form.get('ITMLEN')

        itmwid = request.form.get('ITMWID')

        oneoff = 1 if request.form.get('ONEOFF') else 0

        current = 1 if request.form.get('CURRENT') else 0

        itmnote = request.form.get('ITMNOTE')

        

        db.execute(

            """

            UPDATE ITM 

            SET ITMNAME = ?, ITMGRP = ?, ITMLEN = ?, ITMWID = ?, ONEOFF = ?, CURRENT = ?, ITMNOTE = ?

            WHERE ITEMID = ?

            """,

            (itmname, itmgrp, itmlen or None, itmwid or None, oneoff, current, itmnote, item_id)

        )



        db.execute('DELETE FROM IMI WHERE ITEMID = ? AND MSIID NOT IN (SELECT MSIID FROM MSI WHERE MSITYPE = \'Decoration\')', (item_id,))



        supply_inputs = [

            ('Solder', request.form.get('ITMSLDR'), request.form.get('IMISLDR')),

            ('Foil', request.form.get('ITMFOIL'), request.form.get('IMIFOIL')),

            ('Came', request.form.get('ITMCAME'), request.form.get('IMICAME')),

            ('Chain', request.form.get('ITMCHAIN'), request.form.get('IMICHAIN')),

            ('Rings', request.form.get('ITMRING'), request.form.get('IMIRING')),

            ('Wire', request.form.get('ITMWIRE'), request.form.get('IMIWIRE'))

        ]



        for msi_type, qty_val, msi_id_val in supply_inputs:

            if qty_val and float(qty_val) > 0 and msi_id_val:

                try:

                    msiid_int = int(msi_id_val)

                    exists = db.execute("SELECT 1 FROM MSI WHERE MSIID = ?", (msiid_int,)).fetchone()

                    if exists:

                        db.execute(

                            'INSERT INTO IMI (ITEMID, MSIID, IMIAMT) VALUES (?, ?, ?)',

                            (item_id, msiid_int, float(qty_val))

                        )

                except ValueError:

                    continue



        deco_msiids = request.form.getlist('deco_msiid[]')

        deco_amts = request.form.getlist('deco_amt[]')



        db.execute("DELETE FROM IMI WHERE ITEMID = ? AND MSIID IN (SELECT MSIID FROM MSI WHERE MSITYPE = 'Decoration')", (item_id,))



        for msiid_val, amt_val in zip(deco_msiids, deco_amts):

            if msiid_val and msiid_val.strip() and amt_val and amt_val.strip():

                try:

                    msiid_int = int(msiid_val)

                    amt_float = float(amt_val)

                    

                    if amt_float > 0:

                        exists = db.execute("SELECT 1 FROM MSI WHERE MSIID = ?", (msiid_int,)).fetchone()

                        if exists:

                            db.execute(

                                "INSERT INTO IMI (ITEMID, MSIID, IMIAMT) VALUES (?, ?, ?)",

                                (item_id, msiid_int, amt_float)

                            )

                except ValueError:

                    continue



        db.commit()

        flash('Item updated successfully!', 'success')

        return redirect(url_for('item_bp.item_detail', item_id=item_id))



    associated_supplies = db.execute(

        """

        SELECT msi.MSITYPE, msi.MSIID, imi.IMIAMT 

        FROM IMI imi

        JOIN MSI msi ON imi.MSIID = msi.MSIID

        WHERE imi.ITEMID = ?

        """,

        (item_id,)

    ).fetchall()



    supplies_dict = {row['MSITYPE']: {'amt': row['IMIAMT'], 'id': row['MSIID']} for row in associated_supplies}

    

    item_form_data = dict(item)

    item_form_data['ITMSLDR'] = supplies_dict.get('Solder', {}).get('amt', '')

    item_form_data['IMISLDR'] = supplies_dict.get('Solder', {}).get('id', '')

    

    item_form_data['ITMFOIL'] = supplies_dict.get('Foil', {}).get('amt', '')

    item_form_data['IMIFOIL'] = supplies_dict.get('Foil', {}).get('id', '')

    

    item_form_data['ITMCAME'] = supplies_dict.get('Came', {}).get('amt', '')

    item_form_data['IMICAME'] = supplies_dict.get('Came', {}).get('id', '')

    

    item_form_data['ITMCHAIN'] = supplies_dict.get('Chain', {}).get('amt', '')

    item_form_data['IMICHAIN'] = supplies_dict.get('Chain', {}).get('id', '')

    

    item_form_data['ITMRING']  = supplies_dict.get('Rings', {}).get('amt', '')

    item_form_data['IMIRING']  = supplies_dict.get('Rings', {}).get('id', '')

    

    item_form_data['ITMWIRE']  = supplies_dict.get('Wire', {}).get('amt', '')

    item_form_data['IMIWIRE']  = supplies_dict.get('Wire', {}).get('id', '')



    all_msi = db.execute('SELECT MSIID, MSINAME, MSITYPE FROM MSI ORDER BY MSINAME ASC').fetchall()

    

    msi_solder = [m for m in all_msi if m['MSITYPE'] == 'Solder']

    msi_foil = [m for m in all_msi if m['MSITYPE'] == 'Foil']

    msi_came = [m for m in all_msi if m['MSITYPE'] == 'Came']

    msi_chain = [m for m in all_msi if m['MSITYPE'] == 'Chain']

    msi_rings = [m for m in all_msi if m['MSITYPE'] == 'Rings']

    msi_wire = [m for m in all_msi if m['MSITYPE'] == 'Wire']



    all_groups = db.execute('SELECT DISTINCT ITMGRP FROM ITM WHERE ITMGRP IS NOT NULL ORDER BY ITMGRP ASC').fetchall()



    msi_decorations = db.execute(

        """

        SELECT m.MSIID, m.MSINAME 

        FROM MSI m 

        JOIN MST t ON m.MSITYPE = t.MSITYPE

        WHERE m.MSITYPE = 'Decoration' AND m.ISACTIVE = 1

        ORDER BY m.MSINAME ASC

        """

    ).fetchall()



    associated_decorations = db.execute(

        """

        SELECT i.MSIID, i.IMIAMT, m.MSINAME

        FROM IMI i

        JOIN MSI m ON i.MSIID = m.MSIID

        WHERE i.ITEMID = ? AND m.MSITYPE = 'Decoration'

        """,

        (item_id,)

    ).fetchall()



    return render_template(

        'item_form.html',

        action='Edit',

        item=item_form_data,

        groups=all_groups,

        msi_solder=msi_solder,

        msi_foil=msi_foil,

        msi_came=msi_came,

        msi_chain=msi_chain,

        msi_rings=msi_rings,

        msi_wire=msi_wire,

        msi_decorations=msi_decorations,

        associated_decorations=associated_decorations

    )



@item_bp.route('/item/<int:item_id>/history')

def price_history(item_id):

    db = get_db()

    item = db.execute(

        'SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)

    ).fetchone()



    if not item:

        flash('Item record not found.', 'danger')

        return redirect(url_for('index'))



    rows = db.execute(

        """

            SELECT rowid, ITMPRICE, STDATE, ENDDATE FROM IPC 

            WHERE ITEMID = ? 

            ORDER BY STDATE ASC

        """,

        (item_id,),

    ).fetchall()



    history_processed = []

    prev_price = None



    for row in rows:

        price = row['ITMPRICE']

        change = price - prev_price if prev_price is not None else None

        prev_price = price



        start_dt = (

            datetime.strptime(row['STDATE'], '%Y-%m-%d')

            if row['STDATE']

            else None

        )

        end_dt = (

            datetime.strptime(row['ENDDATE'], '%Y-%m-%d')

            if row['ENDDATE']

            else datetime.today()

        )



        duration_str = 'N/A'

        if start_dt:

            delta = end_dt - start_dt

            days = delta.days

            years = days // 365

            rem_days = days % 365

            if years > 0:

                duration_str = f'{years} yr{"" if years == 1 else "s"} {rem_days} day{"" if rem_days == 1 else "s"}'

            else:

                duration_str = f'{days} day{"" if days == 1 else ""}'



        history_processed.append({

            'ITMPRICE': price,

            'change': change,

            'STDATE': row['STDATE'],

            'ENDDATE': row['ENDDATE'],

            'duration_str': duration_str,

        })



    history_processed.reverse()



    return render_template(

        'item_price_history.html', item=item, history=history_processed

    )



@item_bp.route('/prices/<int:item_id>/edit', methods=['GET', 'POST'])

def edit_prices(item_id):

    db = get_db()

    item = db.execute(

        'SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)

    ).fetchone()



    if not item:

        flash('Item record not found.', 'danger')

        return redirect(url_for('index'))



    if request.method == 'POST':

        try:

            new_price = float(request.form.get('ITMPRICE'))

        except (TypeError, ValueError):

            flash('Invalid price value provided.', 'danger')

            return redirect(url_for('item_bp.edit_prices', item_id=item_id))



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

            return redirect(url_for('item_bp.edit_prices', item_id=item_id))



        cursor = db.cursor()



        existing_prices = cursor.execute(

            """

            SELECT rowid, ITMPRICE, STDATE, ENDDATE FROM IPC 

            WHERE ITEMID = ?

        """,

            (item_id,),

        ).fetchall()



        for row in existing_prices:

            row_id = row['rowid']

            ex_st_str = row['STDATE']

            ex_end_str = row['ENDDATE']



            ex_st = datetime.strptime(ex_st_str, '%Y-%m-%d').date() if ex_st_str else None

            ex_end = datetime.strptime(ex_end_str, '%Y-%m-%d').date() if ex_end_str else None



            if ex_st and new_st <= ex_st and (new_end is None or (ex_end and new_end >= ex_end)):

                cursor.execute('DELETE FROM IPC WHERE rowid = ?', (row_id,))

                continue



            if ex_st and ex_end and new_st > ex_st and new_end and new_end < ex_end:

                split_end_date = (new_st - timedelta(days=1)).strftime('%Y-%m-%d')

                cursor.execute(

                    'UPDATE IPC SET ENDDATE = ? WHERE rowid = ?',

                    (split_end_date, row_id)

                )

                tail_start_date = (new_end + timedelta(days=1)).strftime('%Y-%m-%d')

                cursor.execute(

                    'INSERT INTO IPC (ITEMID, ITMPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, ?)',

                    (item_id, row['ITMPRICE'], tail_start_date, ex_end_str)

                )

                continue



            if ex_st and new_st > ex_st and (ex_end is None or new_st <= ex_end):

                new_ex_end = (new_st - timedelta(days=1)).strftime('%Y-%m-%d')

                cursor.execute(

                    'UPDATE IPC SET ENDDATE = ? WHERE rowid = ?',

                    (new_ex_end, row_id)

                )



            if new_end and ex_end and new_end >= ex_st and new_end < ex_end:

                new_ex_st = (new_end + timedelta(days=1)).strftime('%Y-%m-%d')

                cursor.execute(

                    'UPDATE IPC SET STDATE = ? WHERE rowid = ?',

                    (new_ex_st, row_id)

                )



            if is_current and ex_st and ex_st >= new_st:

                cursor.execute('DELETE FROM IPC WHERE rowid = ?', (row_id,))



        cursor.execute(

            """

            INSERT INTO IPC (ITEMID, ITMPRICE, STDATE, ENDDATE)

            VALUES (?, ?, ?, ?)

        """,

            (item_id, new_price, new_st_str, new_end_str),

        )



        db.commit()

        flash('Price range successfully saved and overlapping intervals adjusted.', 'success')

        return redirect(url_for('item_bp.edit_prices', item_id=item_id))



    prices = db.execute(

        """

            SELECT rowid, ITMPRICE, STDATE, ENDDATE FROM IPC 

            WHERE ITEMID = ? 

            ORDER BY STDATE DESC

        """,

        (item_id,),

    ).fetchall()



    return render_template(

        'item_edit_prices.html', item=item, prices=prices

    )



@item_bp.route('/prices/<int:item_id>/delete/<int:price_id>', methods=['POST'])

def delete_price(item_id, price_id):

    db = get_db()

    db.execute('DELETE FROM IPC WHERE rowid = ? AND ITEMID = ?', (price_id, item_id))

    db.commit()

    flash('Price tier removed.', 'success')

    return redirect(url_for('item_bp.edit_prices', item_id=item_id))



@item_bp.route("/inventory")

def inventory_status():

    db = get_db()

    counts = db.execute("""

        SELECT i.ITMNAME, c.* 

        FROM ICC c

        JOIN ITM i ON c.ITEMID = i.ITEMID

    """).fetchall()

    return render_template("inventory_status.html", counts=counts)



@item_bp.route("/inventory/update/<int:item_id>", methods=["POST"])

def update_inventory(item_id):

    db = get_db()

    ipcut = int(request.form.get("IPCUT", 0))

    ipgrnd = int(request.form.get("IPGRND", 0))

    ipfoil = int(request.form.get("IPFOIL", 0))

    ipsldr = int(request.form.get("IPSLDR", 0))

    ipdone = int(request.form.get("IPDONE", 0))



    db.execute(

        """

        INSERT INTO ICC (ITEMID, IPCUT, IPGRND, IPFOIL, IPSLDR, IPDONE, IPTS)

        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)

        ON CONFLICT(ITEMID) DO UPDATE SET

            IPCUT=excluded.IPCUT, IPGRND=excluded.IPGRND, 

            IPFOIL=excluded.IPFOIL, IPSLDR=excluded.IPSLDR, 

            IPDONE=excluded.IPDONE, IPTS=CURRENT_TIMESTAMP

    """,

        (item_id, ipcut, ipgrnd, ipfoil, ipsldr, ipdone),

    )



    db.execute(

        """

        INSERT INTO ITR (ITEMID, IPCUT, IPGRND, IPFOIL, IPSLDR, IPDONE)

        VALUES (?, ?, ?, ?, ?, ?)

    """,

        (item_id, ipcut, ipgrnd, ipfoil, ipsldr, ipdone),

    )



    db.commit()

    flash("Inventory metrics updated and logged to ITR.", "info")

    return redirect(url_for("item_bp.inventory_status"))



@item_bp.route("/sales")

def list_sales():

    db = get_db()

    sales = db.execute("""

        SELECT s.SALEID, i.ITMNAME, s.SUNITS, s.SDATE, v.VENUELOC 

        FROM ITMSALE s

        JOIN ITM i ON s.ITEMID = i.ITEMID

        LEFT JOIN VENUE v ON s.VENUEID = v.VENUEID

        ORDER BY s.SDATE DESC

    """).fetchall()

    return render_template("sales_list.html", sales=sales)



@item_bp.route("/sales/new", methods=["GET", "POST"])

def record_sale():

    db = get_db()

    if request.method == "POST":

        itemid = request.form.get("ITEMID")

        sunits = request.form.get("SUNITS")

        venueid = request.form.get("VENUEID") or None



        db.execute(

            """

            INSERT INTO ITMSALE (ITEMID, SUNITS, SDATE, VENUEID)

            VALUES (?, ?, DATE('now'), ?)

        """,

            (itemid, sunits, venueid),

        )



        db.commit()

        flash("Sale logged successfully!", "success")

        return redirect(url_for("item_bp.list_sales"))



    items = db.execute("SELECT ITEMID, ITMNAME FROM ITM").fetchall()

    venues = db.execute("SELECT VENUEID, VENUELOC FROM VENUE").fetchall()

    return render_template("sale_form.html", items=items, venues=venues)

@item_bp.route('/item/bulk-sales', methods=['GET'])

def item_bulk_sales():

    db = get_db()

    venues = db.execute("SELECT VENUEID, VENNAME FROM VENUE WHERE ISACTIVE = 1 ORDER BY VENNAME ASC").fetchall()

    today_date = datetime.today().strftime('%Y-%m-%d')

    return render_template('item_bulk_sales.html', venues=venues, today_date=today_date)



@item_bp.route('/item/api/bulk-sales-data', methods=['GET'])

def api_item_bulk_sales_data():

    db = get_db()

    items = db.execute(

        """

        SELECT i.ITEMID, i.ITMNAME, i.ITMGRP, i.ONEOFF, i.ITMIMG, i.ISACTIVE, i.CURRENT,

               (SELECT ii.ITMSTOCK FROM ITMINV ii WHERE ii.ITEMID = i.ITEMID ORDER BY ii.TS DESC LIMIT 1) AS CURRENT_STOCK,

               (SELECT ipc.ITMPRICE FROM IPC ipc WHERE ipc.ITEMID = i.ITEMID ORDER BY ipc.STDATE DESC LIMIT 1) AS ITMPRICE

        FROM ITM i

        ORDER BY i.ITMGRP ASC, i.ITMNAME ASC

        """

    ).fetchall()

    

    item_list = [dict(row) for row in items]

    return {'items': item_list}

@item_bp.route('/item/api/bulk-sales-adjustment', methods=['POST'])

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

            

            # Fetch current stock

            stock_row = db.execute(

                "SELECT ITMSTOCK FROM ITMINV WHERE ITEMID = ? ORDER BY TS DESC LIMIT 1",

                (item_id,)

            ).fetchone()

            current_stock = stock_row['ITMSTOCK'] if stock_row and stock_row['ITMSTOCK'] is not None else 0

            

            # 1. If items were sold, record entry in ITMSALE and subtract from stock

            if amt_sold > 0:

                db.execute(

                    """

                    INSERT INTO ITMSALE (ITEMID, SUNITS, SDATE, VENUEID)

                    VALUES (?, ?, ?, ?)

                    """,

                    (item_id, amt_sold, sale_date, venue_id)

                )

                

                new_stock = max(0, current_stock - amt_sold)

                db.execute(

                    """

                    INSERT INTO ITMINV (ITEMID, ITMSTOCK, TS)

                    VALUES (?, ?, CURRENT_TIMESTAMP)

                    """,

                    (item_id, new_stock)

                )

            

            # 2. Update price if changed (using the standard IPC adjustment approach)

            if new_price is not None:

                current_price_row = db.execute(

                    """

                    SELECT ITMPRICE FROM IPC 

                    WHERE ITEMID = ? AND (ENDDATE IS NULL OR ENDDATE >= DATE('now'))

                    ORDER BY STDATE DESC LIMIT 1

                    """,

                    (item_id,)

                ).fetchone()

                

                if not current_price_row or float(current_price_row['ITMPRICE']) != float(new_price):

                    # Close out current price range

                    db.execute(

                        """

                        UPDATE IPC SET ENDDATE = DATE(?, '-1 day')

                        WHERE ITEMID = ? AND (ENDDATE IS NULL OR ENDDATE >= DATE('now'))

                        """,

                        (sale_date, item_id)

                    )

                    # Insert new price tier

                    db.execute(

                        """

                        INSERT INTO IPC (ITEMID, ITMPRICE, STDATE, ENDDATE)

                        VALUES (?, ?, ?, NULL)

                        """,

                        (item_id, new_price, sale_date)

                    )



        db.commit()

        return {'status': 'success', 'message': 'Sales recorded and inventory updated successfully!'}

    except Exception as e:

        db.rollback()

        return {'status': 'error', 'message': str(e)}, 500
