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
from routes.production_routes import production_bp
from routes.item_routes import item_bp
from routes.venue_routes import venue_bp
from routes.template_routes import templates_bp
from routes.component_routes import component_bp


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
        db.execute(
            "INSERT OR IGNORE INTO PATINA (PATINA) VALUES ('Silver'), ('Copper'), ('Black')"
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
app.register_blueprint(production_bp)
app.register_blueprint(item_bp)
app.register_blueprint(venue_bp)
app.register_blueprint(templates_bp)
app.register_blueprint(component_bp)


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
