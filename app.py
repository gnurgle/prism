import os
import sqlite3
import xml.etree.ElementTree as ET
import re
import base64
import cv2
import numpy as np
from PIL import Image
from lxml import etree
from svgpathtools import svg2paths, wsvg
from utils import process_and_save_image, hex_to_hsv, convert_image_to_svg, remove_svg_region_and_renumber, format_fractional_inches, trace_stencil_to_single_path_svg, compute_total_path_length, trace_stencil_to_outline_svg, trace_stencil_to_filled_outline_svg, round_to_eighth
from flask import Flask, flash, redirect, render_template, request, url_for, render_template_string, jsonify
from datetime import date, datetime, timedelta
from routes.glass_routes import glass_bp
from routes.misc_routes import misc_bp


app = Flask(__name__, static_folder='static')
app.secret_key = "changethislatertoaenv"
DATABASE = "inventory.db"

app.jinja_env.filters['inch_format'] = format_fractional_inches

@app.template_filter('datetimeformat')

def datetimeformat(value, format='%m-%d-%y'):
    if not value:
        return ""
    if isinstance(value, str):
        # Parse standard YYYY-MM-DD or similar string formats from SQLite
        for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%m-%d-%y'):
            try:
                dt = datetime.strptime(value.split('T')[0], fmt if fmt != '%Y-%m-%d' else '%Y-%m-%d')
                return dt.strftime(format)
            except ValueError:
                continue
    return value

# Ensure these directories exist in your project root
UPLOAD_FOLDER_TEMPLATES = 'static/images/templates'
UPLOAD_FOLDER_SVG = 'static/images/svg'
UPLOAD_FOLDER_GLASS = 'static/images/glass'

os.makedirs(UPLOAD_FOLDER_TEMPLATES, exist_ok=True)
os.makedirs(UPLOAD_FOLDER_SVG, exist_ok=True)
os.makedirs(UPLOAD_FOLDER_GLASS, exist_ok=True)

app.config['UPLOAD_FOLDER'] = 'static/uploads'

app.config['SVG_FOLDER'] = 'static/svgs'



# Ensure directories exist

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

os.makedirs(app.config['SVG_FOLDER'], exist_ok=True)


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    """Initializes full schema and sets up automated SQLite Audit Triggers."""
    with app.app_context():
        db = get_db()
        if os.path.exists("schema.sql"):
            with open("schema.sql", "r") as f:
                db.cursor().executescript(f.read())

        # Seed Lookup tables if empty
        db.execute(
            "INSERT OR IGNORE INTO GTL (GLSTEX) VALUES ('Smooth'), ('Wispy'), ('Waterglass'), ('Muffle'), ('RoughRolled'), ('Hammered'), ('Mottled'), ('Dichroic')"
        )
        db.execute(
            "INSERT OR IGNORE INTO GSL (GLSOURCE, SRCWEB) VALUES ('Colorado Glass Co', 1), ('Hobby Lobby', 0), ('Charlotte Glass', 0)"
        )
        db.execute(
            "INSERT OR IGNORE INTO IGP (ITMGRP) VALUES ('Potions'), ('Fruit Slices'), ('Mushrooms')"
        )
        db.execute(
            "INSERT OR IGNORE INTO COLOR (COLOR, CHEX) VALUES ('Black', '0E0E11'),( 'Dark Grey', '7D7D7D'),( 'Light Grey','BEBEBE'),( 'White', 'FFF8F1'),( 'Cerulean', '63CCFF'),( 'Blue', '2087F9'),( 'Cobolt', '1F4897'),( 'Emerald', '095337'),( 'Green', '2BD81A'),( 'Chartreuse', '8DFC00'),( 'Yellow', 'FFFD3B'),( 'Goldenrod', 'FED416'),( 'Orange', 'F17700'),( 'Red', 'E41F00'),( 'Burgundy', '7F0E21'),( 'Indigo', '401782'),( 'Amethyst', '7B35BD'),( 'Mauve', 'BE5ABF'),( 'Lavender', 'E69CE6'),( 'Raspberry', 'DE599B'),( 'Pink', 'FF7D93'),( 'Tan', 'B15223'),( 'Brown', '6B2A16'),( 'Transparent', 'FFFFFF')"
        )
        db.execute(
            "INSERT OR IGNORE INTO GTRNS (GTRNSN, GTRNSV) VALUES ('Clear', 35), ('Transparent', 60), ('Translucent', 75), ('Opaque', 95)"
        )
        db.execute(
            "INSERT OR IGNORE INTO UNTS (UNTTYPE, CFACTOR) VALUES ('inches', 1), ('feet', 12), ('yards', 36), ('pounds', 454), ('units', 1)"
        )
        db.execute(
            "INSERT OR IGNORE INTO MST (MSITYPE) VALUES ('Solder'), ('Foil'), ('Came'), ('Rings'), ('Chain'), ('Consumables'), ('Decoration'), ('Other')"
        )

        # Setup automated AUDIT trigger on ITM table changes
        db.executescript("""
            CREATE TRIGGER IF NOT EXISTS audit_itm_insert AFTER INSERT ON ITM BEGIN
                INSERT INTO AUDIT (TRNOP, TRNNEW, TRNTBL, TRNTS) 
                VALUES ('INSERT', NEW.ITMNAME, 'ITM', CURRENT_TIMESTAMP);
            END;
            CREATE TRIGGER IF NOT EXISTS audit_itm_delete AFTER DELETE ON ITM BEGIN
                INSERT INTO AUDIT (TRNOP, TRNOLD, TRNTBL, TRNTS) 
                VALUES ('DELETE', OLD.ITMNAME, 'ITM', CURRENT_TIMESTAMP);
            END;
        """)
        db.commit()


init_db()





# Register the Blueprint

app.register_blueprint(glass_bp)
app.register_blueprint(misc_bp)



# ============================================================================
# 1. NAVIGATION INDEX & SYSTEM DASHBOARD
# ============================================================================


@app.route("/")
def index():
    db = get_db()
    stats = {
        "items": db.execute("SELECT COUNT(*) FROM ITM").fetchone()[0],
        "glass": db.execute("SELECT COUNT(*) FROM GSI").fetchone()[0],
        "sales": db.execute("SELECT COUNT(*) FROM ITMSALE").fetchone()[0],
        "venues": db.execute("SELECT COUNT(*) FROM VENUE").fetchone()[0],
    }
    recent_audits = db.execute(
        "SELECT * FROM AUDIT ORDER BY TRANSID DESC LIMIT 10"
    ).fetchall()
    return render_template(
        "dashboard.html", stats=stats, recent_audits=recent_audits
    )

@app.route('/item/<int:item_id>', methods=['GET'])
def item_detail(item_id):

    """Display full details, pricing metrics, components, and group siblings using IMI mapping table."""
    db = get_db()



    # Conversion Constants

    SOLDER_CONVERSION = 0.3776

    CAME_CONVERSION = 0.1652



    # Fetch core item record and safely convert sqlite3.Row to a standard dictionary

    raw_item = db.execute(

        'SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)

    ).fetchone()



    if not raw_item:

        flash('Item record not found.', 'danger')

        return redirect(url_for('index'))

    

    item = dict(raw_item)



    # Fetch associated components (IGC) with joined glass info

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



    # Fetch Pricing Metrics from IPC table using correct columns (ITMPRICE, STDATE, ENDDATE)

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



    # Fetch group siblings if item is not a one-off and has a group assigned

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



    # Fetch all associated supplies from IMI mapping table for this item

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



    # Fetch display-only decoration items associated via IMI mapping table with full pricing attributes

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



    # Populate template-expected supply name fields onto the item dictionary safely

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
# -----------------------------------------------------------------------------
# CREATE ITEM ROUTE
# -----------------------------------------------------------------------------



@app.route('/item/new', methods=['GET', 'POST'])

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

        

        # Insert core item record using uppercase field names mapping

        cursor = db.execute(

            """

            INSERT INTO ITM (ITMNAME, ITMGRP, ITMLEN, ITMWID, ONEOFF, CURRENT, ITMNOTE, ISACTIVE)

            VALUES (?, ?, ?, ?, ?, ?, ?, 1)

            """,

            (itmname, itmgrp, itmlen or None, itmwid or None, oneoff, current, itmnote)

        )

        new_item_id = cursor.lastrowid



        # Since supplies matrix is hidden on create, check settings.config for defaults

        config_path = os.path.join(app.root_path, 'settings.config')

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

        return redirect(url_for('item_detail', item_id=new_item_id))



    all_groups = db.execute('SELECT DISTINCT ITMGRP FROM ITM WHERE ITMGRP IS NOT NULL ORDER BY ITMGRP ASC').fetchall()

    all_msi = db.execute('SELECT MSIID, MSINAME, MSITYPE FROM MSI WHERE ISACTIVE = 1 ORDER BY MSINAME ASC').fetchall()

    return render_template('item_form.html', action='Create', item={}, groups=all_groups, 

                           msi_solder=[m for m in all_msi if m['MSITYPE'] == 'Solder'],

                           msi_foil=[m for m in all_msi if m['MSITYPE'] == 'Foil'],

                           msi_came=[m for m in all_msi if m['MSITYPE'] == 'Came'],

                           msi_chain=[m for m in all_msi if m['MSITYPE'] == 'Chain'],

                           msi_rings=[m for m in all_msi if m['MSITYPE'] == 'Rings'],

                           msi_wire=[m for m in all_msi if m['MSITYPE'] == 'Wire'])



@app.route('/item/<int:item_id>/edit', methods=['GET', 'POST'])

def edit_item(item_id):

    """Edit an existing item, updating its core details, component layout, and IMI supply associations."""

    db = get_db()

    

    item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()

    if not item:

        flash('Item not found.', 'danger')

        return redirect(url_for('index'))



    if request.method == 'POST':

        itmname = request.form.get('ITMNAME')

        itmgrp = request.form.get('ITMGRP') or None

        new_itmgrp = request.form.get('NEW_ITMGRP')

        

        # If a new group is specified, insert it into IGP first to satisfy foreign key constraints

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

        

        # Update core item fields safely now that IGP value is guaranteed to exist

        db.execute(

            """

            UPDATE ITM 

            SET ITMNAME = ?, ITMGRP = ?, ITMLEN = ?, ITMWID = ?, ONEOFF = ?, CURRENT = ?, ITMNOTE = ?

            WHERE ITEMID = ?

            """,

            (itmname, itmgrp, itmlen or None, itmwid or None, oneoff, current, itmnote, item_id)

        )



        # Clear existing supply associations in IMI (excluding Decoration, handled separately below)

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

                    # Verify MSIID exists in MSI table before insertion

                    exists = db.execute("SELECT 1 FROM MSI WHERE MSIID = ?", (msiid_int,)).fetchone()

                    if exists:

                        db.execute(

                            'INSERT INTO IMI (ITEMID, MSIID, IMIAMT) VALUES (?, ?, ?)',

                            (item_id, msiid_int, float(qty_val))

                        )

                except ValueError:

                    continue



        # Handle saving/updating decoration arrays from POST request

        deco_msiids = request.form.getlist('deco_msiid[]')

        deco_amts = request.form.getlist('deco_amt[]')



        # Clear existing decoration mappings for this item safely

        db.execute("DELETE FROM IMI WHERE ITEMID = ? AND MSIID IN (SELECT MSIID FROM MSI WHERE MSITYPE = 'Decoration')", (item_id,))



        for msiid_val, amt_val in zip(deco_msiids, deco_amts):

            if msiid_val and msiid_val.strip() and amt_val and amt_val.strip():

                try:

                    msiid_int = int(msiid_val)

                    amt_float = float(amt_val)

                    

                    if amt_float > 0:

                        # Double check that the MSI record actually exists to prevent FOREIGN KEY constraints

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

        return redirect(url_for('item_detail', item_id=item_id))



    # Fetch associated supplies from IMI mapping table for form population

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


    # Fetch categorized Misc Supply options for template dropdown lists

    all_msi = db.execute('SELECT MSIID, MSINAME, MSITYPE FROM MSI ORDER BY MSINAME ASC').fetchall()

    

    msi_solder = [m for m in all_msi if m['MSITYPE'] == 'Solder']

    msi_foil = [m for m in all_msi if m['MSITYPE'] == 'Foil']

    msi_came = [m for m in all_msi if m['MSITYPE'] == 'Came']

    msi_chain = [m for m in all_msi if m['MSITYPE'] == 'Chain']

    msi_rings = [m for m in all_msi if m['MSITYPE'] == 'Rings']

    msi_wire = [m for m in all_msi if m['MSITYPE'] == 'Wire']



    all_groups = db.execute('SELECT DISTINCT ITMGRP FROM ITM WHERE ITMGRP IS NOT NULL ORDER BY ITMGRP ASC').fetchall()



    # Fetch filtered decoration choices for template dropdowns

    msi_decorations = db.execute(

        """

        SELECT m.MSIID, m.MSINAME 

        FROM MSI m 

        JOIN MST t ON m.MSITYPE = t.MSITYPE

        WHERE m.MSITYPE = 'Decoration' AND m.ISACTIVE = 1

        ORDER BY m.MSINAME ASC

        """

    ).fetchall()



    # Fetch existing decoration rows associated with this item for GET rendering

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




@app.route('/item/<int:item_id>/history')
def price_history(item_id):
  """Display historical price list in descending order with calculated price changes and durations."""
  db = get_db()
  item = db.execute(
      'SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)
  ).fetchone()

  if not item:
    flash('Item record not found.', 'danger')
    return redirect(url_for('index'))

  # Fetch all prices ordered chronologically ascending to compute deltas and durations easily
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

    # Calculate duration
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

  # Reverse to have descending order starting from present
  history_processed.reverse()

  return render_template(
      'item_price_history.html', item=item, history=history_processed
  )


@app.route('/prices/<int:item_id>/edit', methods=['GET', 'POST'])
def edit_prices(item_id):
  """Manage and insert prices with automated date shuffling and interval overlap adjustments."""
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
      return redirect(url_for('edit_prices', item_id=item_id))

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
      return redirect(url_for('edit_prices', item_id=item_id))

    cursor = db.cursor()

    # Fetch existing price intervals for this item
    existing_prices = cursor.execute(
        """
        SELECT rowid, ITMPRICE, STDATE, ENDDATE FROM IPC 
        WHERE ITEMID = ?
    """,
        (item_id,),
    ).fetchall()

    # Process and adjust overlapping intervals
    for row in existing_prices:
      row_id = row['rowid']
      ex_st_str = row['STDATE']
      ex_end_str = row['ENDDATE']

      ex_st = datetime.strptime(ex_st_str, '%Y-%m-%d').date() if ex_st_str else None
      ex_end = datetime.strptime(ex_end_str, '%Y-%m-%d').date() if ex_end_str else None

      # Case A: Existing range is completely inside the new range -> Delete it
      if ex_st and new_st <= ex_st and (new_end is None or (ex_end and new_end >= ex_end)):
        cursor.execute('DELETE FROM IPC WHERE rowid = ?', (row_id,))
        continue

      # Case B: New range is completely inside an existing range -> Split the existing range into two
      if ex_st and ex_end and new_st > ex_st and new_end and new_end < ex_end:
        # Update existing record to end right before new range starts (or day before)
        split_end_date = (new_st - timedelta(days=1)).strftime('%Y-%m-%d')
        cursor.execute(
            'UPDATE IPC SET ENDDATE = ? WHERE rowid = ?',
            (split_end_date, row_id)
        )
        # Insert the remaining tail piece of the old range
        tail_start_date = (new_end + timedelta(days=1)).strftime('%Y-%m-%d')
        cursor.execute(
            'INSERT INTO IPC (ITEMID, ITMPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, ?)',
            (item_id, row['ITMPRICE'], tail_start_date, ex_end_str)
        )
        continue

      # Case C: Overlap on the tail end of existing range (New start cuts into old range)
      if ex_st and new_st > ex_st and (ex_end is None or new_st <= ex_end):
        new_ex_end = (new_st - timedelta(days=1)).strftime('%Y-%m-%d')
        cursor.execute(
            'UPDATE IPC SET ENDDATE = ? WHERE rowid = ?',
            (new_ex_end, row_id)
        )

      # Case D: Overlap on the front end of existing range (New end cuts into old range)
      if new_end and ex_end and new_end >= ex_st and new_end < ex_end:
        new_ex_st = (new_end + timedelta(days=1)).strftime('%Y-%m-%d')
        cursor.execute(
            'UPDATE IPC SET STDATE = ? WHERE rowid = ?',
            (new_ex_st, row_id)
        )

      # Case E: If new range is ongoing (current), truncate any old ranges that overlap forward
      if is_current and ex_st and ex_st >= new_st:
        cursor.execute('DELETE FROM IPC WHERE rowid = ?', (row_id,))

    # Insert the new price record cleanly
    cursor.execute(
        """
        INSERT INTO IPC (ITEMID, ITMPRICE, STDATE, ENDDATE)
        VALUES (?, ?, ?, ?)
    """,
        (item_id, new_price, new_st_str, new_end_str),
    )

    db.commit()
    flash('Price range successfully saved and overlapping intervals adjusted.', 'success')
    return redirect(url_for('edit_prices', item_id=item_id))

  # GET Request: fetch all price rows ordered by start date descending
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

@app.route('/prices/<int:item_id>/delete/<int:price_id>', methods=['POST'])
def delete_price(item_id, price_id):
  """Delete a specific price entry row."""
  db = get_db()
  db.execute('DELETE FROM IPC WHERE rowid = ? AND ITEMID = ?', (price_id, item_id))
  db.commit()
  flash('Price tier removed.', 'success')
  return redirect(url_for('edit_prices', item_id=item_id))


# ============================================================================
# COMPONENTS
# ============================================================================

@app.route("/template/upload", methods=["GET", "POST"])



def upload_template():

    db = get_db()

    if request.method == "POST":
        item_id = request.form.get("ITEMID")
        file = request.files.get("template_image")

        if not item_id or not file:
            flash("Please select an item and upload an image.", "danger")
            return redirect(request.url)
            
        item = db.execute("SELECT * FROM ITM WHERE ITEMID = ?", (item_id,)).fetchone()

        if not item:
            flash("Selected item not found.", "danger")
            return redirect(url_for("index"))
            
        # Format filename safely
        safe_item_name = "".join(c for c in item['ITMNAME'] if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
        file_ext = os.path.splitext(file.filename)[1] or '.png'
        filename = f"{item['ITEMID']}_{safe_item_name}{file_ext}"
        
        # Save uploaded raster image
        img_path = os.path.join(UPLOAD_FOLDER_TEMPLATES, filename)
        file.save(img_path)
        
        # Update database path
        relative_img_path = f"images/templates/{filename}"
        db.execute("UPDATE ITM SET ITMPTRN = ? WHERE ITEMID = ?", (relative_img_path, item_id))
        db.commit()
        
        # Automatically convert to SVG using the reusable method
        svg_filename = f"{item['ITEMID']}_{safe_item_name}.svg"
        svg_path = os.path.join(UPLOAD_FOLDER_SVG, svg_filename)
        
        success = convert_image_to_svg(img_path, svg_path)
        if success:
          # Save the SVG path to ITM.ITMSVG after successful conversion
            relative_svg_path = f"images/svg/{svg_filename}"

            db.execute("UPDATE ITM SET ITMSVG = ? WHERE ITEMID = ?", (relative_svg_path, item_id))
            db.commit()
            flash("Template uploaded and converted to SVG via pyautotrace successfully!", "success")
        else:
            flash("Template uploaded, but SVG conversion failed.", "warning")
            
        return redirect(url_for('edit_template', item_id=item_id))
    items = db.execute("SELECT ITEMID, ITMNAME FROM ITM").fetchall()
    return render_template("template_upload.html", items=items)


@app.route("/template/whitespaces/<int:item_id>")

def view_template_whitespaces(item_id):

    db = get_db()
    item = db.execute("SELECT * FROM ITM WHERE ITEMID = ?", (item_id,)).fetchone()
    if not item or not item['ITMPTRN']:
        flash("Template not found or image not uploaded.", "danger")
        return redirect(url_for("index"))
        
    safe_item_name = "".join(c for c in item['ITMNAME'] if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
    svg_filename = f"{item['ITEMID']}_{safe_item_name}.svg"
    svg_path = os.path.join(UPLOAD_FOLDER_SVG, svg_filename)
    svg_url = url_for('static', filename=f"images/svg/{svg_filename}")
    
    # 1. Autoparse the SVG to discover path/shape elements
    clickable_regions = []
    if os.path.exists(svg_path):
        try:
            # Register namespaces to prevent prefix issues with SVG elements
            ET.register_namespace('', "http://www.w3.org/2000/svg")
            tree = ET.parse(svg_path)
            root = tree.getroot()
            
            # Find all path, rect, circle, or polygon elements inside the SVG
            # SVG elements often use namespaces like {http://www.w3.org/2000/svg}path
            elements = []
            for elem in root.iter():
                tag_name = elem.tag.split('}')[-1].lower()
                if tag_name in ['path', 'rect', 'polygon', 'circle', 'polyline']:
                    elements.append(elem)
            
            # 2. Extract bounds/positions to sort them accurately from LEFT to RIGHT
            parsed_elements = []
            for idx, el in enumerate(elements):
                # Basic heuristic fallback bounding extraction or attributes
                # If it's a rect, it has x coordinate
                x_val = 0.0
                if el.tag.endswith('rect'):
                    x_val = float(el.attrib.get('x', 0))
                elif el.tag.endswith('circle'):
                    x_val = float(el.attrib.get('cx', 0)) - float(el.attrib.get('r', 0))
                else:
                    # For paths or polygons, check if we can parse basic attributes or fallback to index
                    x_val = float(idx * 10) # fallback sorting offset
                
                parsed_elements.append((x_val, idx, el))
            
            # Sort elements strictly from left to right based on X coordinate
            parsed_elements.sort(key=lambda item: item[0])
            
            # 3. Assign sequential numbers from left to right and inject clickable properties
            for index, (x, orig_idx, el) in enumerate(parsed_elements, start=1):
                region_id = f"region_{index}"
                el.set('id', region_id)
                el.set('data-number', str(index))
                # Add styling classes for interactive popups and hover cursors
                existing_class = el.attrib.get('class', '')
                el.set('class', f"{existing_class} whitespace-area".strip())
                el.set('style', 'cursor: pointer; fill-opacity: 0.2; stroke: #007bff; stroke-width: 2px;')
                
                clickable_regions.append({
                    "number": index,
                    "id": region_id
                })
                
            # Save modified SVG back or keep it in memory for rendering
            tree.write(svg_path)
            
        except Exception as e:
            print(f"Error parsing SVG for whitespaces: {e}")

    return render_template("template_whitespaces.html", item=item, svg_url=svg_url, regions=clickable_regions)
# ============================================================================
# TEMPLATES
# ============================================================================

@app.route('/template/<int:item_id>/edit', methods=['GET', 'POST'])

def edit_template(item_id):
    conn = get_db()
    item = conn.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()
    
    if not item:
        conn.close()
        flash('Template not found.', 'danger')
        return redirect(url_for('index'))

    svg_file_field = item['ITMSVG'] or f"{item_id}.svg"
    svg_path = os.path.join(app.root_path, 'static', svg_file_field)

    message = None

    if request.method == 'POST':
        target_region_num = request.form.get('region_id')
        print(f"ROUTE CONSOLE WRITE ---> Target File: '{svg_path}' | Region to Delete: '{target_region_num}'")

        if not os.path.exists(svg_path):
            message = f"Error: File does not exist at absolute path: {svg_path}"
        else:
            try:
                # 1. Parse using robust XML parser settings
                parser = etree.XMLParser(remove_blank_text=True, recover=True)
                tree = etree.parse(svg_path, parser)
                
                # 2. Use local-name() wildcard to bypass strict or missing namespace prefix issues
                path_elements = tree.xpath('//*[local-name()="path"]')

                removed = False
                for elem in path_elements:
                    region_val = elem.get('data-region-id')
                    elem_id = elem.get('id', '')

                    # Match by data-region-id or ID string format (e.g., 'region-2' or '2')
                    if (region_val and str(region_val).strip() == str(target_region_num)) or (elem_id in [f"region-{target_region_num}", str(target_region_num)]):
                        
                        parent = elem.getparent()
                        if parent is not None:
                            parent.remove(elem)
                            removed = True
                            print(f"ROUTE SUCCESS: Removed element ID '{elem_id}', data-region-id '{region_val}'")
                        break

                if removed:
                    # 3. Re-fetch remaining paths and re-index attributes sequentially
                    remaining_paths = tree.xpath('//*[local-name()="path"]')
                    for new_idx, elem in enumerate(remaining_paths, start=1):
                        elem.set('id', f'region-{new_idx}')
                        elem.set('data-region-id', str(new_idx))
                        if elem.get('data-number') is not None:
                            elem.set('data-number', str(new_idx))

                    # 4. Explicitly write back out to disk using binary mode
                    root = tree.getroot()
                    xml_bytes = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='utf-8')
                    with open(svg_path, 'wb') as f:
                        f.write(xml_bytes)

                    flash(f"Success! Region {target_region_num} deleted and file updated on disk.", "success")
                else:
                    flash(f"Warning: Could not find any path matching region ID '{target_region_num}' in {svg_file_field}.", "warning")
            except Exception as e:
                flash(f"Exception occurred during processing: {str(e)}", "danger")
                print(f"ROUTE EXCEPTION: {e}")

        conn.close()
        return redirect(url_for('edit_template', item_id=item_id))

    conn.close()

    # Read current state of paths for display on the template interface
    paths_list = []
    if os.path.exists(svg_path):
        try:
            parser = etree.XMLParser(remove_blank_text=True, recover=True)
            tree = etree.parse(svg_path, parser)
            path_elements = tree.xpath('//*[local-name()="path"]')
            for idx, elem in enumerate(path_elements):
                region_label = elem.get('data-region-id') or elem.get('data-number') or str(idx + 1)
                element_id = elem.get('id', f'path-{idx+1}')
                paths_list.append({
                    'index': idx,
                    'id': element_id,
                    'label': region_label,
                    'data_region_id': region_label
                })
        except Exception as e:
            print(f"Error reading paths for template view: {e}")

    return render_template('edit_template.html', item=item, paths_list=paths_list)

# ============================================================================
# COMPONENTS
# =============================================================================
@app.route('/build_components', methods=['GET', 'POST'])
def build_components():
    db = get_db()

    if request.method == 'POST':
        selected_item_id = request.form.get('item_id')

        if not selected_item_id:
            flash('Please select a valid item.', 'danger')
            return redirect(url_for('build_components'))

        # Fetch the selected item
        item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (selected_item_id,)).fetchone()

        svg_filename = item['ITMSVG'] if (item and 'ITMSVG' in item.keys()) else None

        if item and svg_filename:
            # Check if ITMLEN and ITMWID are valid (non-zero and non-negative)
            item_keys = item.keys()
            itm_len = item['ITMLEN'] if (item and 'ITMLEN' in item_keys) else None
            itm_wid = item['ITMWID'] if (item and 'ITMWID' in item_keys) else None
            
            has_valid_dimensions = False
            try:
                itm_len_val = float(itm_len) if itm_len is not None else 0.0
                itm_wid_val = float(itm_wid) if itm_wid is not None else 0.0
                if itm_len_val > 0 and itm_wid_val > 0:
                    has_valid_dimensions = True
            except (ValueError, TypeError):
                has_valid_dimensions = False

            # 1. Do a search first and remove any items from IGC where IGC.ITEMID = selected ITEMID
            db.execute('DELETE FROM IGC WHERE ITEMID = ?', (selected_item_id,))

            # 2. Locate and parse the SVG file from static/
            svg_path = os.path.join(app.root_path, 'static', svg_filename)

            if os.path.exists(svg_path):
                try:
                    import re
                    import xml.etree.ElementTree as ET
                    
                    ET.register_namespace('', "http://www.w3.org/2000/svg")
                    tree = ET.parse(svg_path)
                    root = tree.getroot()

                    # Extract overall SVG dimensions (viewBox or width/height attributes)
                    svg_width = None
                    svg_height = None
                    
                    viewBox = root.attrib.get('viewBox')
                    if viewBox:
                        parts = [float(p) for p in viewBox.replace(',', ' ').split() if p.strip()]
                        if len(parts) == 4:
                            svg_width = parts[2]
                            svg_height = parts[3]

                    if svg_width is None or svg_height is None:
                        w_attr = root.attrib.get('width')
                        h_attr = root.attrib.get('height')
                        if w_attr and h_attr:
                            try:
                                svg_width = float(re.sub(r'[^0-9.]', '', w_attr))
                                svg_height = float(re.sub(r'[^0-9.]', '', h_attr))
                            except ValueError:
                                pass

                    # Fallback defaults if SVG scale is missing
                    if not svg_width or not svg_height or svg_width <= 0 or svg_height <= 0:
                        svg_width, svg_height = 100.0, 100.0

                    # Map SVG Height -> ITM.ITMLEN (Length), and SVG Width -> ITM.ITMWID (Width)
                    scale_x = itm_wid_val / svg_width if has_valid_dimensions else 1.0
                    scale_y = itm_len_val / svg_height if has_valid_dimensions else 1.0

                    # Find all path elements
                    paths = root.findall('.//{http://www.w3.org/2000/svg}path')
                    if not paths:
                        paths = root.findall('.//path')

                    comp_counter = 1
                    for path in paths:
                        # Extract data-region-id attribute
                        region_id = None
                        for k, v in path.attrib.items():
                            if 'data-region-id' in k.lower() or k.lower() == 'region-id':
                                region_id = v
                                break

                        if not region_id:
                            region_id = comp_counter

                        try:
                            svg_reg_val = int(region_id)
                        except ValueError:
                            svg_reg_val = comp_counter

                        comp_len = None
                        comp_wid = None

                        if has_valid_dimensions:
                            path_data = path.attrib.get('d', '')
                            try:
                                try:
                                    # Attempt 1: Use svgpathtools if installed (has native bbox)
                                    from svgpathtools import parse_path
                                    parsed = parse_path(path_data)
                                    bbox = parsed.bbox() # (xmin, xmax, ymin, ymax)
                                    box_w = bbox[1] - bbox[0]
                                    box_h = bbox[3] - bbox[2]
                                except ImportError:
                                    # Attempt 2: Fallback to svg.path (requires manual bounds sampling)
                                    from svg.path import parse_path
                                    parsed = parse_path(path_data)
                                    
                                    xmin, xmax, ymin, ymax = float('inf'), float('-inf'), float('inf'), float('-inf')
                                    for seg in parsed:
                                        for i in range(11): 
                                            pt = seg.point(i / 10.0)
                                            xmin = min(xmin, pt.real)
                                            xmax = max(xmax, pt.real)
                                            ymin = min(ymin, pt.imag)
                                            ymax = max(ymax, pt.imag)
                                            
                                    if xmin == float('inf'):
                                        box_w, box_h = svg_width, svg_height
                                    else:
                                        box_w = xmax - xmin
                                        box_h = ymax - ymin
                            except Exception as e:
                                print(f"Warning: Failed to parse bounding box for path {comp_counter}. Error: {e}")
                                box_w, box_h = svg_width, svg_height

                            # Scale down to physical dimensions (Width maps to ITMWID, Height maps to ITMLEN)
                            raw_wid = box_w * scale_x
                            raw_len = box_h * scale_y

                            # Round to the nearest 1/8" (0.125)
                            comp_len = round(raw_len / 0.125) * 0.125
                            comp_wid = round(raw_wid / 0.125) * 0.125

                        # 3. Insert into IGC table: Saving ITEMID, SVGREG, COMPNUM, COMPLEN, COMPWID, and setting ISACTIVE = 1
                        db.execute('''
                            INSERT INTO IGC (ITEMID, SVGREG, COMPNUM, COMPLEN, COMPWID, ISACTIVE)
                            VALUES (?, ?, ?, ?, ?, 1)
                        ''', (selected_item_id, svg_reg_val, comp_counter, comp_len, comp_wid))

                        comp_counter += 1

                    db.commit()
                    flash('Components successfully built and saved to IGC!', 'success')
                except Exception as e:
                    flash(f'Error parsing SVG file: {str(e)}', 'danger')
            else:
                flash(f'SVG file not found at static/{svg_filename}', 'danger')
        else:
            flash('Selected item does not have a reference SVG file or ITMSVG is empty.', 'warning')

        return redirect(url_for('build_components'))





    # GET Request: Fetch all items to populate the dropdown by ITM.ITMNAME
    items = db.execute('SELECT ITEMID, ITMNAME FROM ITM').fetchall()
    return render_template('build_components.html', items=items)


@app.route('/edit_components/<int:item_id>', methods=['GET'])

def edit_components(item_id):

    db = get_db()

    # Fetch Item and its SVG
    item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()
    if not item:
        flash('Item not found.', 'danger')
        return redirect(url_for('index'))

    svg_filename = item['ITMSVG'] if 'ITMSVG' in item.keys() else None
    svg_url = url_for('static', filename=svg_filename) if svg_filename else ''

    # Fetch all glass options for the dropdown (GSI table)
    glass_options = db.execute('''
        SELECT g.GLASSID, g.GLSNAME, g.GLSTEX, g.GLSIMG, c.CHEX, t.GTRNSV 
        FROM GSI g
        LEFT JOIN COLOR c ON g.COLOR = c.COLOR
        LEFT JOIN GTRNS t ON g.GTRNSN = t.GTRNSN
        WHERE g.ISACTIVE = 1
    ''').fetchall()
    # Fetch components joined with glass and color info to map svg regions to color hexes and textures
    # IGC -> GSI -> COLOR

    components = db.execute('''
        SELECT 
            i.COMPID, i.COMPNAME, i.ITEMID, i.COMPNUM, i.SVGREG, 
            i.GLASSID, i.COMPLEN, i.COMPWID, i.COMPNOTE,
            i.ISSCRAP, i.ISGRAIN, i.ISACTIVE,
            c.CHEX, g.GLSTEX, g.GTRNSN, g.GLSIMG, t.GTRNSV
        FROM IGC i
        LEFT JOIN GSI g ON i.GLASSID = g.GLASSID
        LEFT JOIN COLOR c ON g.COLOR = c.COLOR
        LEFT JOIN GTRNS t ON g.GTRNSN = t.GTRNSN
        WHERE i.ITEMID = ?

    ''', (item_id,)).fetchall()



    # Convert components to a dictionary keyed by SVGREG for easy lookup in the template

    comp_map = {}

    for comp in components:
        comp_map[comp['SVGREG']] = {
            'COMPID': comp['COMPID'],
            'COMPNAME': comp['COMPNAME'] or '',
            'COMPNUM': comp['COMPNUM'] or '',
            'SVGREG': comp['SVGREG'],
            'GLASSID': comp['GLASSID'] or '',
            'COMPLEN': comp['COMPLEN'] or '',
            'COMPWID': comp['COMPWID'] or '',
            'ISSCRAP': 1 if comp['ISSCRAP'] else 0,
            'ISGRAIN': 1 if comp['ISGRAIN'] else 0,
            'CHEX': comp['CHEX'] or 'cccccc', # default grey if no color assigned
            'GLSIMG': comp['GLSIMG'] or '',
            'GLSTEX': comp['GLSTEX'] or '',
            'GTRNSV': comp['GTRNSV']
        }

    return render_template(
        'edit_components.html', 
        item=item, 
        svg_url=svg_url, 
        glass_options=glass_options, 

        components_json=comp_map

    )




# ============================================================================
# 3. INVENTORY & WORK-IN-PROGRESS TRACKING (ICC, ITR)
# ============================================================================


@app.route("/inventory")
def inventory_status():
    db = get_db()
    counts = db.execute("""
        SELECT i.ITMNAME, c.* 
        FROM ICC c
        JOIN ITM i ON c.ITEMID = i.ITEMID
    """).fetchall()
    return render_template("inventory_status.html", counts=counts)


@app.route("/inventory/update/<int:item_id>", methods=["POST"])
def update_inventory(item_id):
    db = get_db()
    ipcut = int(request.form.get("IPCUT", 0))
    ipgrnd = int(request.form.get("IPGRND", 0))
    ipfoil = int(request.form.get("IPFOIL", 0))
    ipsldr = int(request.form.get("IPSLDR", 0))
    ipdone = int(request.form.get("IPDONE", 0))

    # Update Current Inventory Level (ICC)
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

    # Log Transaction Record (ITR)
    db.execute(
        """
        INSERT INTO ITR (ITEMID, IPCUT, IPGRND, IPFOIL, IPSLDR, IPDONE)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (item_id, ipcut, ipgrnd, ipfoil, ipsldr, ipdone),
    )

    db.commit()
    flash("Inventory metrics updated and logged to ITR.", "info")
    return redirect(url_for("inventory_status"))


# ============================================================================
# 4. SALES AND VENUE MANAGEMENT (ITMSALE, TIMESALE, VENUE)
# ============================================================================


@app.route("/sales")
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


@app.route("/sales/new", methods=["GET", "POST"])
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
        return redirect(url_for("list_sales"))

    items = db.execute("SELECT ITEMID, ITMNAME FROM ITM").fetchall()
    venues = db.execute("SELECT VENUEID, VENUELOC FROM VENUE").fetchall()
    return render_template("sale_form.html", items=items, venues=venues)


@app.route('/test_outline', methods=['GET', 'POST'])

def test_outline():
    svg_content = None
    outline_content = None
    filled_content = None
    foil_content = None
    total_len = 0.0
    outline_len = 0.0

    foil_len = 0.0
    width_in = 10.0
    height_in = 10.0

    if request.method == 'POST':
        if 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                try:
                    width_in = float(request.form.get('width_in', 10.0))
                    height_in = float(request.form.get('height_in', 10.0))
                except ValueError:
                    width_in, height_in = 10.0, 10.0

                svg_content = trace_stencil_to_single_path_svg(file)
                file.stream.seek(0)
                outline_content = trace_stencil_to_outline_svg(file)

                file.stream.seek(0)
                foil_content = trace_stencil_to_filled_outline_svg(file)                
                total_len = compute_total_path_length(svg_content, width_in, height_in)
                outline_len = compute_total_path_length(outline_content, width_in, height_in)

                foil_len = compute_total_path_length(foil_content, width_in, height_in)
                foil_len = foil_len - outline_len


    return render_template_string(
        HTML_PAGE, 
        svg_content=svg_content, 
        outline_content=outline_content,
        filled_content=filled_content,
        foil_content=foil_content,
        total_len=total_len, 
        outline_len=outline_len,

        foil_len=foil_len,
        width_in=width_in, 
        height_in=height_in
    )

# ============================================================================
# MISC ITEMS
# ============================================================================



@app.route('/misc/<int:misc_id>/history')
def price_history_misc(misc_id):
  """Display historical price list in descending order with calculated price changes and durations."""
  db = get_db()
  item = db.execute(
      'SELECT * FROM MSI WHERE MSIID = ?', (misc_id,)
  ).fetchone()

  if not item:
    flash('Item record not found.', 'danger')
    return redirect(url_for('index'))

  # Fetch all prices ordered chronologically ascending to compute deltas and durations easily
  rows = db.execute(
      """
        SELECT rowid, MSIPRICE, STDATE, ENDDATE FROM MSI 
        WHERE MSIID = ? 
        ORDER BY STDATE ASC
    """,
      (misc_id,),
  ).fetchall()

  history_processed = []
  prev_price = None

  for row in rows:
    price = row['MSIPRICE']
    change = price - prev_price if prev_price is not None else None
    prev_price = price

    # Calculate duration
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
        'MSIPRICE': price,
        'change': change,
        'STDATE': row['STDATE'],
        'ENDDATE': row['ENDDATE'],
        'duration_str': duration_str,
    })

  # Reverse to have descending order starting from present
  history_processed.reverse()

  return render_template(
      'misc_price_history.html', misc=misc, history=history_processed
  )


@app.route('/update_components_batch', methods=['POST'])

def update_components_batch():

    db = get_db()

    data = request.get_json()

    item_id = data.get('item_id')

    components = data.get('components', [])



    try:

        for comp in components:

            comp_id = comp.get('COMPID') if comp.get('COMPID') is not None else comp.get('comp_id')

            if not comp_id:

                continue

            

            comp_num = comp.get('COMPNUM') if comp.get('COMPNUM') is not None else comp.get('comp_num')

            comp_name = comp.get('COMPNAME') if comp.get('COMPNAME') is not None else comp.get('comp_name')

            comp_len = comp.get('COMPLEN') if comp.get('COMPLEN') is not None else comp.get('comp_len')

            comp_wid = comp.get('COMPWID') if comp.get('COMPWID') is not None else comp.get('comp_wid')

            glass_id = comp.get('GLASSID') if comp.get('GLASSID') is not None else comp.get('glass_id')

            

            isscrap_val = comp.get('ISSCRAP') if comp.get('ISSCRAP') is not None else comp.get('isscrap')

            isscrap = 1 if isscrap_val == 1 or isscrap_val is True or isscrap_val == 'true' else 0

            

            isgrain_val = comp.get('ISGRAIN') if comp.get('ISGRAIN') is not None else comp.get('isgrain')

            isgrain = 1 if isgrain_val == 1 or isgrain_val is True or isgrain_val == 'true' else 0



            db.execute('''

                UPDATE IGC 

                SET COMPNUM = ?, COMPNAME = ?, COMPLEN = ?, COMPWID = ?, GLASSID = ?, ISSCRAP = ?, ISGRAIN = ?

                WHERE COMPID = ? AND ITEMID = ?

            ''', (

                comp_num or None, 

                comp_name or None, 

                float(comp_len) if comp_len else None, 

                float(comp_wid) if comp_wid else None, 

                int(glass_id) if glass_id else None, 

                isscrap, 

                isgrain, 

                int(comp_id), 

                int(item_id)

            ))

        

        db.commit()

        return jsonify({'success': True, 'message': 'All components updated successfully!'})

    except Exception as e:

        db.rollback()

        return jsonify({'success': False, 'message': str(e)}), 400


@app.route('/trace_outline', methods=['GET', 'POST'])
def trace_outline():
    db = get_db()

    svg_content = None
    outline_content = None
    filled_content = None
    foil_content = None

    total_len = 0.0
    outline_len = 0.0
    foil_len = 0.0

    width_in = 10.0
    height_in = 10.0
    selected_item_id = None

    if request.method == 'POST':
        selected_item_id = request.form.get('item_id')

        if selected_item_id:
            item = db.execute(
                'SELECT * FROM ITM WHERE ITEMID = ?',
                (selected_item_id,)
            ).fetchone()

            if item and item['ITMPTRN']:
                try:
                    width_in = float(item['ITMLEN']) if item['ITMLEN'] else 10.0
                    height_in = float(item['ITMWID']) if item['ITMWID'] else 10.0
                except (ValueError, TypeError):
                    width_in = 10.0
                    height_in = 10.0

                img_path = os.path.join(
                    app.root_path,
                    'static',
                    item['ITMPTRN']
                )

                if os.path.exists(img_path):
                    with open(img_path, 'rb') as f:
                        file_bytes = f.read()

                    from io import BytesIO

                    # ---------------------------------------------------------
                    # TRACE THE STENCIL
                    # ---------------------------------------------------------
                    stream1 = BytesIO(file_bytes)
                    svg_content = trace_stencil_to_single_path_svg(stream1)

                    stream2 = BytesIO(file_bytes)
                    outline_content = trace_stencil_to_outline_svg(stream2)

                    stream3 = BytesIO(file_bytes)
                    foil_content = trace_stencil_to_filled_outline_svg(stream3)

                    total_len = compute_total_path_length(
                        svg_content,
                        width_in,
                        height_in
                    )

                    outline_len = compute_total_path_length(
                        outline_content,
                        width_in,
                        height_in
                    )

                    foil_len = (
                        compute_total_path_length(
                            foil_content,
                            width_in,
                            height_in
                        ) - outline_len
                    )

                    # ---------------------------------------------------------
                    # SAVE TRACE RESULTS THROUGH IMI
                    #
                    # Do NOT write the calculated quantities into:
                    #     ITMSLDR
                    #     ITMFOIL
                    #     ITMCAME
                    #
                    # Instead:
                    #   1. Use the existing IMI ID stored on ITM when valid.
                    #   2. Otherwise create a new IMI.
                    #   3. Store the new IMI ID on ITM.
                    #   4. Update IMIAMT on the IMI record.
                    # ---------------------------------------------------------

                    try:
                        # Calculated quantities.
                        #
                        # Keep these assignments matching the existing
                        # trace calculation semantics.
                        solder_amount = total_len
                        foil_amount = foil_len
                        came_amount = outline_len

                        supply_updates = [
                            {
                                'itm_column': 'IMISLDR',
                                'msi_type': 'Solder',
                                'amount': solder_amount
                            },
                            {
                                'itm_column': 'IMIFOIL',
                                'msi_type': 'Foil',
                                'amount': foil_amount
                            },
                            {
                                'itm_column': 'IMICAME',
                                'msi_type': 'Came',
                                'amount': came_amount
                            }
                        ]

                        created_imi_ids = []
                        updated_imi_ids = []

                        for supply in supply_updates:
                            itm_column = supply['itm_column']
                            msi_type = supply['msi_type']
                            amount = float(supply['amount'] or 0)

                            # -------------------------------------------------
                            # 1. Get the IMI ID currently stored on ITM
                            # -------------------------------------------------
                            current_imi_id = item[itm_column]

                            imi_row = None

                            if current_imi_id:
                                imi_row = db.execute(
                                    """
                                    SELECT
                                        i.IMIID,
                                        i.ITEMID,
                                        i.MSIID,
                                        i.IMIAMT,
                                        m.MSITYPE
                                    FROM IMI i
                                    JOIN MSI m
                                      ON m.MSIID = i.MSIID
                                    WHERE i.IMIID = ?
                                      AND i.ITEMID = ?
                                    """,
                                    (
                                        current_imi_id,
                                        selected_item_id
                                    )
                                ).fetchone()

                                # Do not reuse an IMI belonging to the wrong
                                # material type.
                                if (
                                    not imi_row
                                    or imi_row['MSITYPE'] != msi_type
                                ):
                                    imi_row = None

                            # -------------------------------------------------
                            # 2. If the ITM IMI ID is missing/invalid,
                            #    find an existing IMI for this item/type.
                            # -------------------------------------------------
                            if not imi_row:
                                imi_row = db.execute(
                                    """
                                    SELECT
                                        i.IMIID,
                                        i.ITEMID,
                                        i.MSIID,
                                        i.IMIAMT,
                                        m.MSITYPE
                                    FROM IMI i
                                    JOIN MSI m
                                      ON m.MSIID = i.MSIID
                                    WHERE i.ITEMID = ?
                                      AND m.MSITYPE = ?
                                    ORDER BY i.IMIID
                                    LIMIT 1
                                    """,
                                    (
                                        selected_item_id,
                                        msi_type
                                    )
                                ).fetchone()

                            # -------------------------------------------------
                            # 3. If no IMI exists, create one.
                            #
                            # Pick an active MSI of the required type.
                            # -------------------------------------------------
                            if not imi_row:
                                msi_row = db.execute(
                                    """
                                    SELECT MSIID
                                    FROM MSI
                                    WHERE MSITYPE = ?
                                      AND ISACTIVE = 1
                                    ORDER BY MSIID
                                    LIMIT 1
                                    """,
                                    (msi_type,)
                                ).fetchone()

                                if not msi_row:
                                    flash(
                                        f'No active MSI exists for '
                                        f'{msi_type}. Trace result was not saved.',
                                        'warning'
                                    )
                                    continue

                                cursor = db.execute(
                                    """
                                    INSERT INTO IMI
                                        (ITEMID, MSIID, IMIAMT)
                                    VALUES
                                        (?, ?, ?)
                                    """,
                                    (
                                        selected_item_id,
                                        msi_row['MSIID'],
                                        amount
                                    )
                                )

                                new_imi_id = cursor.lastrowid

                                # -------------------------------------------------
                                # Store the newly-created IMI ID on ITM.
                                #
                                # IMPORTANT:
                                # This is the only ITM value being changed here.
                                # The measurement columns themselves are NOT
                                # updated.
                                # -------------------------------------------------
                                db.execute(
                                    f"""
                                    UPDATE ITM
                                    SET {itm_column} = ?
                                    WHERE ITEMID = ?
                                    """,
                                    (
                                        new_imi_id,
                                        selected_item_id
                                    )
                                )

                                created_imi_ids.append(new_imi_id)

                            else:
                                # -------------------------------------------------
                                # 4. Existing IMI: update its amount.
                                # -------------------------------------------------
                                db.execute(
                                    """
                                    UPDATE IMI
                                    SET IMIAMT = ?
                                    WHERE IMIID = ?
                                      AND ITEMID = ?
                                    """,
                                    (
                                        amount,
                                        imi_row['IMIID'],
                                        selected_item_id
                                    )
                                )

                                updated_imi_ids.append(imi_row['IMIID'])

                        db.commit()

                        if created_imi_ids:
                            flash(
                                'Created IMI record(s): '
                                + ', '.join(map(str, created_imi_ids)),
                                'success'
                            )

                        if updated_imi_ids:
                            flash(
                                'Updated IMI record(s): '
                                + ', '.join(map(str, updated_imi_ids)),
                                'success'
                            )

                    except Exception as e:
                        db.rollback()
                        flash(
                            f'Unable to save trace measurements: {e}',
                            'danger'
                        )

    # -------------------------------------------------------------
    # Existing item-selection list
    # -------------------------------------------------------------
    items = db.execute(
        '''
        SELECT
            ITEMID,
            ITMNAME,
            ITMLEN,
            ITMWID,
            ITMPTRN
        FROM ITM
        WHERE ISACTIVE = 1
          AND ITMPTRN IS NOT NULL
          AND ITMPTRN != ''
        ORDER BY ITMNAME ASC
        '''
    ).fetchall()

    return render_template(
        'trace_outline.html',
        items=items,
        selected_item_id=selected_item_id,
        svg_content=svg_content,
        outline_content=outline_content,
        filled_content=filled_content,
        foil_content=foil_content,
        total_len=total_len,
        outline_len=outline_len,
        foil_len=foil_len,
        width_in=width_in,
        height_in=height_in
    )

@app.route('/settings', methods=['GET', 'POST'])

def settings():

    """Manage application settings and save them to a local settings.config XML file."""

    db = get_db()

    config_path = os.path.join(app.root_path, 'settings.config')



    # Handle POST submission to save configurations to XML

    if request.method == 'POST':

        root = ET.Element('Settings')

        new_item_elem = ET.SubElement(root, 'NewItemDefaults')

        

        # Grab values from form inputs

        fields = ['Solder', 'Foil', 'Came', 'Chain', 'Rings']

        for field in fields:

            val = request.form.get(f'default_{field.lower()}')

            ET.SubElement(new_item_elem, field).text = val if val else ''



        # Write out to settings.config XML file

        tree = ET.ElementTree(root)

        tree.write(config_path, encoding='utf-8', xml_declaration=True)

        

        flash('Settings saved successfully!', 'success')

        return redirect(url_for('settings'))



    # Load existing settings from XML if the file exists

    defaults = {

        'Solder': '',

        'Foil': '',

        'Came': '',

        'Chain': '',

        'Rings': ''

    }

    

    if os.path.exists(config_path):

        try:

            tree = ET.parse(config_path)

            root = tree.getroot()

            defaults_elem = root.find('NewItemDefaults')

            if defaults_elem is not None:

                for k in defaults.keys():

                    child = defaults_elem.find(k)

                    if child is not None and child.text:

                        defaults[k] = child.text

        except ET.ParseError:

            pass



    # Fetch all active Misc Supplies categorized for dropdown population

    all_msi = db.execute('SELECT MSIID, MSINAME, MSITYPE FROM MSI WHERE ISACTIVE = 1 ORDER BY MSINAME ASC').fetchall()

    

    msi_solder = [m for m in all_msi if m['MSITYPE'] == 'Solder']

    msi_foil = [m for m in all_msi if m['MSITYPE'] == 'Foil']

    msi_came = [m for m in all_msi if m['MSITYPE'] == 'Came']

    msi_chain = [m for m in all_msi if m['MSITYPE'] == 'Chain']

    msi_rings = [m for m in all_msi if m['MSITYPE'] == 'Rings']



    return render_template(

        'settings.html',

        defaults=defaults,

        msi_solder=msi_solder,

        msi_foil=msi_foil,

        msi_came=msi_came,

        msi_chain=msi_chain,

        msi_rings=msi_rings

    )

@app.route('/venues')
def list_venues():
    db = get_db()

    sort_by = request.args.get('sort_by', 'VENNAME')
    order = request.args.get('order', 'asc').lower()
    if order not in ['asc', 'desc']:
        order = 'asc'

    q = request.args.get('q', '').strip()
    ven_grp = request.args.get('ven_grp', '').strip()
    app_start = request.args.get('app_start', '').strip()
    app_end = request.args.get('app_end', '').strip()
    state = request.args.get('state', '').strip()
    min_fee = request.args.get('min_fee', '').strip()
    max_fee = request.args.get('max_fee', '').strip()
    multi_wknd = request.args.get('multi_wknd', '').strip()
    occ_start = request.args.get('occ_start', '').strip()
    occ_end = request.args.get('occ_end', '').strip()
    is_active = request.args.get('is_active', '1').strip()
    year = request.args.get('year', '').strip()

    allowed_sorts = {
        'VENNAME': 'v.VENNAME',
        'VENGRP': 'v.VENGRP',
        'VCITY': 'v.VCITY',
        'VENSTATE': 'v.VENSTATE',
        'VENSDATE': 'v.VENSDATE',
        'VFEES': 'v.VFEES',
        'VENDLINE': 'v.VENDLINE'
    }
    sort_column = allowed_sorts.get(sort_by, 'v.VENNAME')

    where_clauses = []
    params = []

    if is_active != 'all':
        where_clauses.append("v.ISACTIVE = ?")
        params.append(1 if is_active == '1' else 0)

    if q:
        where_clauses.append("(v.VENNAME LIKE ? OR v.VENNOTE LIKE ? OR v.VCITY LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    if ven_grp:
        where_clauses.append("v.VENGRP = ?")
        params.append(ven_grp)

    if app_start:
        where_clauses.append("v.VENDLINE >= ?")
        params.append(app_start)
    if app_end:
        where_clauses.append("v.VENDLINE <= ?")
        params.append(app_end)

    # Replaced camping condition with state condition
    if state:
        where_clauses.append("v.VSTATE = ?")
        params.append(state)

    if min_fee:
        where_clauses.append("v.VFEES >= ?")
        params.append(min_fee)
    if max_fee:
        where_clauses.append("v.VFEES <= ?")
        params.append(max_fee)

    if multi_wknd:
        where_clauses.append("v.VMULTI = ?")
        params.append(multi_wknd)

    if occ_start and occ_end:
        where_clauses.append("v.VSDATE <= ? AND v.VEDATE >= ?")
        params.extend([occ_end, occ_start])
    elif occ_start:
        where_clauses.append("v.VEDATE >= ?")
        params.append(occ_start)
    elif occ_end:
        where_clauses.append("v.VSDATE <= ?")
        params.append(occ_end)

    if year:
        where_clauses.append("strftime('%Y', v.VSDATE) = ?")
        params.append(year)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    query = f"""
        SELECT v.* 
        FROM VENUE v
        {where_sql}
        ORDER BY {sort_column} {order.upper()}
    """
    venues = db.execute(query, params).fetchall()

    venue_groups = db.execute("SELECT DISTINCT VENGRP FROM VENUE WHERE VENGRP IS NOT NULL AND VENGRP != '' ORDER BY VENGRP").fetchall()
    
    # Fetch distinct states for the state filter dropdown
    venue_states = [row[0] for row in db.execute("SELECT DISTINCT VSTATE FROM VENUE WHERE VSTATE IS NOT NULL AND VSTATE != '' ORDER BY VSTATE").fetchall() if row[0]]
    
    available_years = [row[0] for row in db.execute("SELECT DISTINCT strftime('%Y', VSDATE) FROM VENUE WHERE VSDATE IS NOT NULL ORDER BY VSDATE DESC").fetchall() if row[0]]

    return render_template(
        'venue_list.html',
        venues=venues,
        venue_groups=venue_groups,
        venue_states=venue_states,
        available_years=available_years,
        current_sort=sort_by,
        current_order=order,
        filters={
            'q': q,
            'ven_grp': ven_grp,
            'app_start': app_start,
            'app_end': app_end,
            'state': state,  # Replaced camping with state
            'min_fee': min_fee,
            'max_fee': max_fee,
            'multi_wknd': multi_wknd,
            'occ_start': occ_start,
            'occ_end': occ_end,
            'is_active': is_active,
            'year': year
        }
    )

@app.route('/venue/new', methods=['GET', 'POST'])
def create_venue():
    db = get_db()
    
    if request.method == 'POST':
        venname = request.form.get('VENNAME')
        vengrp = request.form.get('VENGRP') or None
        new_vengrp = request.form.get('NEW_VENGRP')
        
        if new_vengrp and new_vengrp.strip():
            vengrp = new_vengrp.strip()
            db.execute("INSERT OR IGNORE INTO VGP (VENGRP, ISACTIVE) VALUES (?, 1)", (vengrp,))

        vcity = request.form.get('VCITY')
        vfees = request.form.get('VFEES') or None
        vendline = request.form.get('VENDLINE') or None
        vsdate = request.form.get('VSDATE') or None
        vedate = request.form.get('VEDATE') or None
        vcampava = 1 if request.form.get('VCAMPAVA') else 0
        vmulti = 1 if request.form.get('VMULTI') else 0
        vennote = request.form.get('VENNOTE')
        isactive = 1

        db.execute(
            """
            INSERT INTO VENUE (VENNAME, VENGRP, VCITY, VFEES, VENDLINE, VSDATE, VEDATE, VCAMPAVA, VMULTI, VENNOTE, ISACTIVE)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (venname, vengrp, vcity, vfees, vendline, vsdate, vedate, vcampava, vmulti, vennote, isactive)
        )
        db.commit()
        
        flash('Venue created successfully!', 'success')
        return redirect(url_for('list_venues'))

    all_groups = db.execute('SELECT DISTINCT VENGRP FROM VGP WHERE ISACTIVE = 1 ORDER BY VENGRP ASC').fetchall()
    return render_template('venue_form.html', action='Create', venue={}, groups=all_groups)


@app.route('/venues/<int:venue_id>/edit', methods=['GET', 'POST'])
def edit_venue(venue_id):
    db = get_db()
    cursor = db.cursor()

    if request.method == 'POST':
        # Retrieve form fields
        venname = request.form.get('VENNAME')
        isactive = 1 if request.form.get('ISACTIVE') else 0
        vurl = request.form.get('VURL')
        vinsta = request.form.get('VINSTA')
        vfb = request.form.get('VFB')
        vengrp = request.form.get('VENGRP') or None
        new_vengrp = request.form.get('NEW_VENGRP')
        
        if new_vengrp and new_vengrp.strip():
            vengrp = new_vengrp.strip()
            db.execute("INSERT OR IGNORE INTO VGP (VENGRP, ISACTIVE) VALUES (?, 1)", (vengrp,))
        
        vstreet1 = request.form.get('VSTREET1')
        vstreet2 = request.form.get('VSTREET2')
        vcity = request.form.get('VCITY')
        vstate = request.form.get('VSTATE')
        vzip = request.form.get('VZIP')
        venueloc = request.form.get('VENUELOC')
        
        vconname = request.form.get('VCONNAME')
        vconphn = request.form.get('VCONPHN')
        vconemail = request.form.get('VCONEMAIL')
        vconnote = request.form.get('VCONNOTE')
        
        vendline = request.form.get('VENDLINE')
        vsdate = request.form.get('VSDATE')
        vedate = request.form.get('VEDATE')
        vfees = request.form.get('VFEES') or None
        vfeenote = request.form.get('VFEENOTE')
        vmulti = 1 if request.form.get('VMULTI') else 0
        
        vcampava = 1 if request.form.get('VCAMPAVA') else 0
        vcamped = 1 if request.form.get('VCAMPED') else 0
        vcampfee = request.form.get('VCAMPFEE') or None
        vcampnt = request.form.get('VCAMPNT')
        vennote = request.form.get('VENNOTE')
        
        # Daily checkboxes and times
        vm = 1 if request.form.get('VM') else 0
        vmst = request.form.get('VMST')
        vmet = request.form.get('VMET')
        
        vte = 1 if request.form.get('VTE') else 0
        vtst = request.form.get('VTST')
        vtet = request.form.get('VTET')
        
        vw = 1 if request.form.get('VW') else 0
        vwst = request.form.get('VWST')
        vwet = request.form.get('VWET')
        
        vr = 1 if request.form.get('VR') else 0
        vrst = request.form.get('VRST')
        vret = request.form.get('VRET')
        
        vf = 1 if request.form.get('VF') else 0
        vfst = request.form.get('VFST')
        vfet = request.form.get('VFET')
        
        vst = 1 if request.form.get('VST') else 0
        vstst = request.form.get('VSTST')
        vstet = request.form.get('VSTET')
        
        vsn = 1 if request.form.get('VSN') else 0
        vsnst = request.form.get('VSNST')
        vsnet = request.form.get('VSNET')

        cursor.execute("""
            UPDATE VENUE SET
                VENNAME = ?, VENGRP = ?, ISACTIVE = ?, VURL = ?, VINSTA = ?, VFB = ?,
                VSTREET1 = ?, VSTREET2 = ?, VCITY = ?, VSTATE = ?, VZIP = ?, VENUELOC = ?,
                VCONNAME = ?, VCONPHN = ?, VCONEMAIL = ?, VCONNOTE = ?,
                VENDLINE = ?, VSDATE = ?, VEDATE = ?, VFEES = ?, VFEENOTE = ?, VMULTI = ?,
                VCAMPAVA = ?, VCAMPED = ?, VCAMPFEE = ?, VCAMPNT = ?, VENNOTE = ?,
                VM = ?, VMST = ?, VMET = ?,
                VTE = ?, VTST = ?, VTET = ?,
                VW = ?, VWST = ?, VWET = ?,
                VR = ?, VRST = ?, VRET = ?,
                VF = ?, VFST = ?, VFET = ?,
                VST = ?, VSTST = ?, VSTET = ?,
                VSN = ?, VSNST = ?, VSNET = ?
            WHERE VENUEID = ?
        """, (
            venname, vengrp, isactive, vurl, vinsta, vfb,
            vstreet1, vstreet2, vcity, vstate, vzip, venueloc,
            vconname, vconphn, vconemail, vconnote,
            vendline, vsdate, vedate, vfees, vfeenote, vmulti,
            vcampava, vcamped, vcampfee, vcampnt, vennote,
            vm, vmst, vmet,
            vte, vtst, vtet,
            vw, vwst, vwet,
            vr, vrst, vret,
            vf, vfst, vfet,
            vst, vstst, vstet,
            vsn, vsnst, vsnet,
            venue_id
        ))

        db.commit()
        return redirect(url_for('venue_detail', venue_id=venue_id))

    # GET request: fetch venue and groups to correctly populate form inputs and dropdowns
    cursor.execute("SELECT * FROM VENUE WHERE VENUEID = ?", (venue_id,))
    venue = cursor.fetchone()
    
    # Fetch active groups from VGP (or distinct venue groups) to display in the dropdown
    groups = db.execute('SELECT DISTINCT VENGRP FROM VGP WHERE ISACTIVE = 1 ORDER BY VENGRP ASC').fetchall()

    return render_template('venue_form.html', action='Edit', venue=venue, groups=groups)

    # GET request: fetch venue to populate form
    cursor.execute("SELECT * FROM VENUE WHERE VENUEID = ?", (venue_id,))
    venue = cursor.fetchone()
    all_groups = db.execute('SELECT DISTINCT VENGRP FROM VGP WHERE ISACTIVE = 1 ORDER BY VENGRP ASC').fetchall()

    return render_template('venue_form.html',action='EDIT', venue=venue, all_groups=all_groups)



@app.route('/venue/<int:venue_id>')

def venue_detail(venue_id):
    db = get_db()
    venue = db.execute('SELECT * FROM VENUE WHERE VENUEID = ?', (venue_id,)).fetchone()
    if not venue:
        flash('Venue record not found.', 'danger')
        return redirect(url_for('list_venues'))

    return render_template('venue_detail.html', venue=venue)


@app.route('/glass/toggle/<int:glass_id>')

def toggle_glass_active(glass_id):

    db = get_db()
    current = db.execute("SELECT ISACTIVE FROM GSI WHERE GLASSID = ?", (glass_id,)).fetchone()
    if current:
        new_status = 0 if current['ISACTIVE'] == 1 else 1
        db.execute("UPDATE GSI SET ISACTIVE = ? WHERE GLASSID = ?", (new_status, glass_id))
        db.commit()
    return redirect(request.referrer or url_for('list_glass'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7665, debug=True)
