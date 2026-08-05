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


app = Flask(__name__, static_folder='static')
app.secret_key = "changethislatertoaenv"
DATABASE = "inventory.db"

app.jinja_env.filters['inch_format'] = format_fractional_inches

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
            "INSERT OR IGNORE INTO COLOR (COLOR, CHEX) VALUES ('Red', 'FF0000'), ('Orange', 'FF8000'), ('Yellow', 'FFFF00'), ('Chartreuse Green', '80FF00'), ('Green', '00FF00'), ('Spring Green', '00FF80'), ('Azure', '0080FF'), ('Blue', '0000FF'), ('Violet', '8000FF'), ('Magenta', 'FF00FF'), ('Rose', 'FF0080'), ('White', 'FFFFFF'), ('Black', '000000'), ('Grey', '808080'), ('Transparent', 'FFFFFF')"
        )
        db.execute(
            "INSERT OR IGNORE INTO GTRNS (GTRNSN, GTRNSV) VALUES ('Transparent', 60), ('Translucent', 75), ('Opaque', 95)"
        )
        db.execute(
            "INSERT OR IGNORE INTO UNTS (UNTTYPE, CFACTOR) VALUES ('inches', 1), ('feet', 12), ('yards', 36), ('pounds', 454)"
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

@app.route('/item/<int:item_id>')

def item_detail(item_id):

  """Display full details, pricing metrics, components, and group siblings."""

  db = get_db()



  # Conversion Constants

  SOLDER_CONVERSION = 0.3776

  CAME_CONVERSION = 0.1652



  # Fetch core item record with joined MSI info for linked supplies

  item = db.execute(

      """

        SELECT i.*, 

               s_sldr.MSINAME AS MSLDR_NAME, s_sldr.UNTTYPE AS MSLDR_UNIT,

               s_foil.MSINAME AS MFOIL_NAME, s_foil.UNTTYPE AS MFOIL_UNIT,

               s_came.MSINAME AS MCAME_NAME, s_came.UNTTYPE AS MCAME_UNIT,

               s_chain.MSINAME AS MCHAIN_NAME, s_chain.UNTTYPE AS MCHAIN_UNIT,

               s_ring.MSINAME AS MRING_NAME, s_ring.UNTTYPE AS MRING_UNIT,

               s_wire.MSINAME AS MWIRE_NAME, s_wire.UNTTYPE AS MWIRE_UNIT

        FROM ITM i

        LEFT JOIN MSI s_sldr ON i.IMISLDR = s_sldr.MSIID

        LEFT JOIN MSI s_foil ON i.IMIFOIL = s_foil.MSIID

        LEFT JOIN MSI s_came ON i.IMICAME = s_came.MSIID

        LEFT JOIN MSI s_chain ON i.IMICHAIN = s_chain.MSIID

        LEFT JOIN MSI s_ring ON i.IMIRING = s_ring.MSIID

        LEFT JOIN MSI s_wire ON i.IMIWIRE = s_wire.MSIID

        WHERE i.ITEMID = ?

      """,

      (item_id,),

  ).fetchone()



  if not item:

    flash('Item record not found.', 'danger')

    return redirect(url_for('index'))



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






  # Calculate metrics directly from ITM fields, applying SOLDER_CONVERSION and CAME_CONVERSION

  raw_sldr = float(item['ITMSLDR'] or 0.0)

  raw_came = float(item['ITMCAME'] or 0.0)
  

  itm_supplies = {

      'ITMSLDR': (raw_sldr * SOLDER_CONVERSION * 2) + (raw_came * CAME_CONVERSION * 2),

      'ITMCAME': float(item['ITMCAME'] or 0.0),

      'ITMFOIL': float(item['ITMFOIL'] or 0.0),

      'ITMCHAIN': float(item['ITMCHAIN'] or 0.0),

      'ITMRING': float(item['ITMRING'] or 0),

      'ITMWIRE': float(item['ITMWIRE'] or 0.0)

  }

# Fetch associated MSIIDs, CFACTORs, and MSIUNITs by joining MSI and UNTS tables

  supply_links = db.execute(

      """

        SELECT 

            i.IMISLDR AS sldr_id, u_sldr.CFACTOR as sldr_cfactor, m_sldr.MSIUNIT as sldr_msiunit,

            i.IMIFOIL AS foil_id, u_foil.CFACTOR as foil_cfactor, m_foil.MSIUNIT as foil_msiunit,

            i.IMICAME AS came_id, u_came.CFACTOR as came_cfactor, m_came.MSIUNIT as came_msiunit,

            i.IMICHAIN AS chain_id, u_chain.CFACTOR as chain_cfactor, m_chain.MSIUNIT as chain_msiunit,

            i.IMIRING AS ring_id, u_ring.CFACTOR as ring_cfactor, m_ring.MSIUNIT as ring_msiunit,

            i.IMIWIRE AS wire_id, u_wire.CFACTOR as wire_cfactor, m_wire.MSIUNIT as wire_msiunit

        FROM ITM i

        LEFT JOIN MSI m_sldr ON i.IMISLDR = m_sldr.MSIID

        LEFT JOIN UNTS u_sldr ON m_sldr.UNTTYPE = u_sldr.UNTTYPE

        LEFT JOIN MSI m_foil ON i.IMIFOIL = m_foil.MSIID

        LEFT JOIN UNTS u_foil ON m_foil.UNTTYPE = u_foil.UNTTYPE

        LEFT JOIN MSI m_came ON i.IMICAME = m_came.MSIID

        LEFT JOIN UNTS u_came ON m_came.UNTTYPE = u_came.UNTTYPE

        LEFT JOIN MSI m_chain ON i.IMICHAIN = m_chain.MSIID

        LEFT JOIN UNTS u_chain ON m_chain.UNTTYPE = u_chain.UNTTYPE

        LEFT JOIN MSI m_ring ON i.IMIRING = m_ring.MSIID

        LEFT JOIN UNTS u_ring ON m_ring.UNTTYPE = u_ring.UNTTYPE

        LEFT JOIN MSI m_wire ON i.IMIWIRE = m_wire.MSIID

        LEFT JOIN UNTS u_wire ON m_wire.UNTTYPE = u_wire.UNTTYPE

        WHERE i.ITEMID = ?

      """,

      (item_id,),

  ).fetchone()



  estimated_supplies_core_cost = 0.0



  if supply_links:

      supplies_to_calc = [

          (itm_supplies['ITMSLDR'], supply_links['sldr_id'], supply_links['sldr_cfactor'], supply_links['sldr_msiunit']),

          (itm_supplies['ITMFOIL'], supply_links['foil_id'], supply_links['foil_cfactor'], supply_links['foil_msiunit']),

          (itm_supplies['ITMCAME'], supply_links['came_id'], supply_links['came_cfactor'], supply_links['came_msiunit']),

          (itm_supplies['ITMCHAIN'], supply_links['chain_id'], supply_links['chain_cfactor'], supply_links['chain_msiunit']),

          (itm_supplies['ITMRING'], supply_links['ring_id'], supply_links['ring_cfactor'], supply_links['ring_msiunit']),

          (itm_supplies['ITMWIRE'], supply_links['wire_id'], supply_links['wire_cfactor'], supply_links['wire_msiunit'])

      ]



      for qty, misc_id, cfactor, msiunit in supplies_to_calc:

          if qty and qty > 0 and misc_id:

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

                  valid_msiunit = float(msiunit) if msiunit and float(msiunit) > 0 else 1.0

                  

                  divisor = valid_cfactor * valid_msiunit

                  if divisor > 0 and unit_price > 0:

                      estimated_supplies_core_cost += qty * (unit_price / divisor)



  estimated_supplies_cost = estimated_supplies_core_cost

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

  )

# -----------------------------------------------------------------------------
# CREATE ITEM ROUTE
# -----------------------------------------------------------------------------


@app.route('/item/create', methods=['GET', 'POST'])
def create_item():
    """Create a new Item record and handle group/image inputs."""
    db = get_db()

    if request.method == 'POST':
        itm_name = request.form.get('ITMNAME', '').strip()
        itm_grp = request.form.get('ITMGRP', '').strip()
        new_grp = request.form.get('NEW_ITMGRP', '').strip()
        
        # Parse dimensions securely
        itm_len_val = request.form.get('ITMLEN')
        itm_wid_val = request.form.get('ITMWID')
        itm_len = float(itm_len_val) if itm_len_val else None
        itm_wid = float(itm_wid_val) if itm_wid_val else None

        oneoff = 1 if request.form.get('ONEOFF') else 0
        current = 1 if request.form.get('CURRENT') else 0
        itm_note = request.form.get('ITMNOTE', '').strip()

        # Group safeguard: if no option selected and new input is blank, assign None
        selected_group = None
        if new_grp:
            selected_group = new_grp
            existing_grp = db.execute(
                'SELECT 1 FROM IGP WHERE ITMGRP = ?', (new_grp,)
            ).fetchone()
            if not existing_grp:
                db.execute(
                    'INSERT INTO IGP (ITMGRP, ISACTIVE) VALUES (?, 1)', (new_grp,)
                )
        elif itm_grp:
            selected_group = itm_grp

        # Save initial record to get the item_id for naming the image file
        cursor = db.cursor()
        cursor.execute(
            """
                INSERT INTO ITM (ITMNAME, ITMGRP, ITMLEN, ITMWID, ONEOFF, CURRENT, ITMNOTE, ITMIMG)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (itm_name, selected_group, itm_len, itm_wid, oneoff, current, itm_note, None),
        )
        item_id = cursor.lastrowid
        db.commit()

        # Handle image upload using the modular helper signature
        image_path = None
        if 'ITMIMG_FILE' in request.files:
            file = request.files['ITMIMG_FILE']
            if file and file.filename != '':
                image_path = process_and_save_image(
                    file,
                    upload_subfolder='images/items',
                    custom_filename_base=f'{item_id}_{itm_name}',
                    target_size=(1024, 1024),
                )
                cursor.execute(
                    'UPDATE ITM SET ITMIMG = ? WHERE ITEMID = ?', (image_path, item_id)
                )
                db.commit()

        flash(f'Item "{itm_name}" successfully created.', 'success')
        return redirect(url_for('item_detail', item_id=item_id))

    groups = db.execute(
        'SELECT DISTINCT ITMGRP FROM ITM WHERE ITMGRP IS NOT NULL AND ITMGRP !='
        " '' ORDER BY ITMGRP"
    ).fetchall()
    return render_template('item_form.html', action='Create', groups=groups)


@app.route('/item/<int:item_id>/edit', methods=['GET', 'POST'])

def edit_item(item_id):

    """Edit an existing Item record, matching glass image upload handling."""

    db = get_db()



    item = db.execute(

        'SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)

    ).fetchone()



    if not item:

        flash('Item record not found.', 'danger')

        return redirect(url_for('index'))



    if request.method == 'POST':

        itm_name = request.form.get('ITMNAME', '').strip()

        itm_grp = request.form.get('ITMGRP', '').strip()

        new_grp = request.form.get('NEW_ITMGRP', '').strip()

        

        # Parse dimensions securely

        itm_len_val = request.form.get('ITMLEN')

        itm_wid_val = request.form.get('ITMWID')

        itm_len = float(itm_len_val) if itm_len_val else None

        itm_wid = float(itm_wid_val) if itm_wid_val else None



        # Parse supply metrics and selected linked MSI IDs

        itm_sldr = float(request.form.get('ITMSLDR')) if request.form.get('ITMSLDR') else None

        itm_foil = float(request.form.get('ITMFOIL')) if request.form.get('ITMFOIL') else None

        itm_came = float(request.form.get('ITMCAME')) if request.form.get('ITMCAME') else None

        itm_chain = int(request.form.get('ITMCHAIN')) if request.form.get('ITMCHAIN') else None

        itm_ring = int(request.form.get('ITMRING')) if request.form.get('ITMRING') else None

        itm_wire = int(request.form.get('ITMWIRE')) if request.form.get('ITMWIRE') else None



        imi_sldr = int(request.form.get('IMISLDR')) if request.form.get('IMISLDR') else None

        imi_foil = int(request.form.get('IMIFOIL')) if request.form.get('IMIFOIL') else None

        imi_came = int(request.form.get('IMICAME')) if request.form.get('IMICAME') else None

        imi_chain = int(request.form.get('IMICHAIN')) if request.form.get('IMICHAIN') else None

        imi_ring = int(request.form.get('IMIRING')) if request.form.get('IMIRING') else None

        imi_wire = int(request.form.get('IMIWIRE')) if request.form.get('IMIWIRE') else None



        oneoff = 1 if request.form.get('ONEOFF') else 0

        current = 1 if request.form.get('CURRENT') else 0

        itm_note = request.form.get('ITMNOTE', '').strip()



        selected_group = None

        if new_grp:

            selected_group = new_grp

            existing_grp = db.execute(

                'SELECT 1 FROM IGP WHERE ITMGRP = ?', (new_grp,)

            ).fetchone()

            if not existing_grp:

                db.execute(

                    'INSERT INTO IGP (ITMGRP, ISACTIVE) VALUES (?, 1)', (new_grp,)

                )

        elif itm_grp:

            selected_group = itm_grp



        # Keep existing image unless a new file is uploaded

        image_path = item['ITMIMG']

        if 'ITMIMG_FILE' in request.files:

            file = request.files['ITMIMG_FILE']

            if file and file.filename != '':

                image_path = process_and_save_image(

                    file,

                    upload_subfolder='images/items',

                    custom_filename_base=f'{item_id}_{itm_name}',

                    target_size=(1024, 1024),

                )



        db.execute(

            """

                UPDATE ITM 

                SET ITMNAME = ?, 

                    ITMGRP = ?, 

                    ITMLEN = ?,

                    ITMWID = ?,

                    ITMSLDR = ?,

                    ITMFOIL = ?,

                    ITMCAME = ?,

                    ITMCHAIN = ?,

                    ITMRING = ?,

                    ITMWIRE = ?,

                    IMISLDR = ?,

                    IMIFOIL = ?,

                    IMICAME = ?,

                    IMICHAIN = ?,

                    IMIRING = ?,

                    IMIWIRE = ?,

                    ONEOFF = ?, 

                    CURRENT = ?, 

                    ITMNOTE = ?, 

                    ITMIMG = ?

                WHERE ITEMID = ?

            """,

            (

                itm_name,

                selected_group,

                itm_len,

                itm_wid,

                itm_sldr,

                itm_foil,

                itm_came,

                itm_chain,

                itm_ring,

                itm_wire,

                imi_sldr,

                imi_foil,

                imi_came,

                imi_chain,

                imi_ring,

                imi_wire,

                oneoff,

                current,

                itm_note,

                image_path,

                item_id,

            ),

        )

        db.commit()



        flash(f'Item "{itm_name}" updated successfully.', 'success')

        return redirect(url_for('item_detail', item_id=item_id))



    groups = db.execute(

        'SELECT DISTINCT ITMGRP FROM ITM WHERE ITMGRP IS NOT NULL AND ITMGRP !='

        " '' ORDER BY ITMGRP"

    ).fetchall()



    # Fetch type-matched MSI lists for the edit dropdown cells

    msi_solder = db.execute("SELECT MSIID, MSINAME FROM MSI WHERE MSITYPE = 'Solder' AND ISACTIVE = 1").fetchall()

    msi_foil = db.execute("SELECT MSIID, MSINAME FROM MSI WHERE MSITYPE = 'Foil' AND ISACTIVE = 1").fetchall()

    msi_came = db.execute("SELECT MSIID, MSINAME FROM MSI WHERE MSITYPE = 'Came' AND ISACTIVE = 1").fetchall()

    msi_chain = db.execute("SELECT MSIID, MSINAME FROM MSI WHERE MSITYPE = 'Chain' AND ISACTIVE = 1").fetchall()

    msi_rings = db.execute("SELECT MSIID, MSINAME FROM MSI WHERE MSITYPE = 'Rings' AND ISACTIVE = 1").fetchall()

    msi_wire = db.execute("SELECT MSIID, MSINAME FROM MSI WHERE MSITYPE = 'Wire' AND ISACTIVE = 1").fetchall()



    return render_template(

        'item_form.html', 

        action='Edit', 

        item=item, 

        groups=groups,

        msi_solder=msi_solder,

        msi_foil=msi_foil,

        msi_came=msi_came,

        msi_chain=msi_chain,

        msi_rings=msi_rings,

        msi_wire=msi_wire

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
# 2. GLASS SHEET INVENTORY MANAGEMENT (GSI, GTL, GSL, GPC)
# ============================================================================

@app.route('/glass')
def list_glass():
    db = get_db()

    # --- Capture Sort & Filter Parameters ---
    sort_by = request.args.get('sort_by', 'GLASSID')
    order = request.args.get('order', 'asc').lower()
    if order not in ['asc', 'desc']:
        order = 'asc'

    q = request.args.get('q', '').strip()
    manf = request.args.get('manf', '').strip()
    tex = request.args.get('tex', '').strip()
    color = request.args.get('color', '').strip()
    source = request.args.get('source', '').strip()
    min_price = request.args.get('min_price', '').strip()
    max_price = request.args.get('max_price', '').strip()

    # Filter parameter for Glass active status (Defaults to showing active glass '1')
    is_active = request.args.get('is_active', '1').strip()

    item_id = request.args.get('item_id', '').strip()
    item_name = request.args.get('item_name', '').strip()
    active_only = request.args.get('active_only', '')  # '1' if active items only

    allowed_sorts = {
        'GLASSID': 'g.GLASSID',
        'GLSNAME': 'g.GLSNAME',
        'GLSMANF': 'g.GLSMANF',
        'GLSTEX': 'g.GLSTEX',
        'COLOR': 'g.COLOR',
        'GLSOURCE': 'g.GLSOURCE',
        'GLSLEN': 'g.GLSLEN',
        'GLSPRICE': 'p.GLSPRICE'
    }
    sort_column = allowed_sorts.get(sort_by, 'g.GLASSID')

    # Build dynamic WHERE clause for GSI table
    where_clauses = []
    params = []

    # Filter Glass by ISACTIVE integer flag
    if is_active != 'all':
        where_clauses.append("g.ISACTIVE = ?")
        params.append(1 if is_active == '1' else 0)

    if q:
        where_clauses.append("(g.GLSNAME LIKE ? OR g.GLSMANF LIKE ? OR g.GLSNOTE LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if manf:
        where_clauses.append("g.GLSMANF = ?")
        params.append(manf)
    if tex:
        where_clauses.append("g.GLSTEX = ?")
        params.append(tex)
    if color:
        where_clauses.append("g.COLOR = ?")
        params.append(color)
    if source:
        where_clauses.append("g.GLSOURCE = ?")
        params.append(source)
    if min_price:
        where_clauses.append("p.GLSPRICE >= ?")
        params.append(min_price)
    if max_price:
        where_clauses.append("p.GLSPRICE <= ?")
        params.append(max_price)

    # Filter by specific Item ID (Glass used in components of selected Item)
    join_igc = ""
    if item_id:
        join_igc = "INNER JOIN IGC c ON g.GLASSID = c.GLASSID"
        where_clauses.append("c.ITEMID = ?")
        params.append(item_id)
        
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

# Execute main query
    query = f"""
        SELECT DISTINCT g.*, p.GLSPRICE, c.CHEX
        FROM GSI g
        LEFT JOIN GPC p ON g.GLASSID = p.GLASSID
        LEFT JOIN COLOR c ON g.COLOR = c.COLOR
        {join_igc}
        {where_sql}
        ORDER BY {sort_column} {order.upper()}
    """
    glasses = db.execute(query, params).fetchall()

    # --- Fetch Active Lookups for Modal Dropdowns ---
    textures = db.execute(
        "SELECT DISTINCT GLSTEX FROM GSI WHERE ISACTIVE = 1 AND GLSTEX IS NOT NULL AND GLSTEX != '' ORDER BY GLSTEX"
    ).fetchall()
    
    colors = db.execute(
        "SELECT * FROM COLOR ORDER BY COLOR"
    ).fetchall()
    
    sources = db.execute(
        "SELECT DISTINCT GLSOURCE FROM GSI WHERE ISACTIVE = 1 AND GLSOURCE IS NOT NULL AND GLSOURCE != '' ORDER BY GLSOURCE"
    ).fetchall()
    
    manufacturers = db.execute(
        "SELECT DISTINCT GLSMANF FROM GSI WHERE ISACTIVE = 1 AND GLSMANF IS NOT NULL AND GLSMANF != '' ORDER BY GLSMANF"
    ).fetchall()

    item_where = "WHERE i.ISACTIVE = 1" if active_only == '1' else ""
    items_query = f"""
        SELECT 
            i.ITEMID, 
            i.ITMNAME, 
            i.ISACTIVE,
            i.CURRENT,
            g.ITMGRP,
            COALESCE(NULLIF(g.ITMGRP, ''), i.ITMNAME) AS group_or_name
        FROM ITM i
        LEFT JOIN IGP g ON i.ITMGRP = g.ITMGRP
        {item_where}
        ORDER BY group_or_name ASC, i.ITMNAME ASC
    """
    items = db.execute(items_query).fetchall()

    # Resolve human-readable item name if item_id was passed
    item_name = ""
    if item_id:
        for item in items:
            if str(item['ITEMID']) == str(item_id):
                item_name = item['ITMNAME']
                break

    return render_template(
        'glass_list.html',
        glasses=glasses,
        textures=textures,
        colors=colors,
        sources=sources,
        manufacturers=manufacturers,
        items=items,
        current_sort=sort_by,
        current_order=order,
        filters={
            'q': q, 
            'manf': manf, 
            'tex': tex, 
            'color': color, 
            'source': source,
            'min_price': min_price, 
            'max_price': max_price,
            'is_active': is_active,
            'item_id': item_id, 
            'item_name': item_name, 
            'active_only': active_only
        }
    )
@app.route("/glass/new", methods=["GET", "POST"])
def create_glass():

    db = get_db()
    if request.method == "POST":

        glsname = request.form.get('GLSNAME')
        glsmanf = request.form.get('GLSMANF')
        glstex = request.form.get('GLSTEX') or None
        gtrnsn = request.form.get('GTRNSN') or None
        color = request.form.get('COLOR') or None
        glsource = request.form.get('GLSOURCE') or None
        glslen = request.form.get('GLSLEN') or None
        glswid = request.form.get('GLSWID') or None
        glsthk = request.form.get('GLSTHK') or None
        glsiri = 1 if request.form.get('GLSIRI') else 0
        glsopal = 1 if request.form.get('GLSOPAL') else 0
        gllink = request.form.get('GLLINK') or None
        glsimg = request.form.get('GLSIMG')
        glsnote = request.form.get('GLSNOTE')
        price = request.form.get('GLSPRICE')
        isactive = 1

        cursor = db.execute(
            """
            INSERT INTO GSI (GLSNAME, GLSMANF, GLSTEX, GTRNSN, COLOR, GLSOURCE, 
                GLSLEN, GLSWID, GLSTHK, GLSIRI,GLSOPAL, GLLINK, 
                GLSIMG, GLSNOTE, ISACTIVE)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            (
                glsname, glsmanf, glstex, gtrnsn, color, glsource, glslen,
                glswid, glsthk, glsiri, glsopal, gllink, glsimg,
                glsnote, isactive
            ),
        )

        glass_id = cursor.lastrowid

        glsimg_path = None
        file = request.files.get("GLSIMG_FILE")
        if file and file.filename != '':
            pattern_name = f"{glass_id}_{glsname}"
            glsimg_path = process_and_save_image(
                file_obj=file,
                upload_subfolder='images/glass',
                custom_filename_base=pattern_name,
                target_size=(256, 256)
            )
            # Update GLSIMG field in GSI table
            db.execute("UPDATE GSI SET GLSIMG = ? WHERE GLASSID = ?", (glsimg_path, glass_id))

        if price:
            db.execute(
                """
                INSERT INTO GPC (GLASSID, GLSPRICE, STDATE) VALUES (?, ?, DATE('now'))
            """,
                (glass_id, price),
            )

        db.commit()
        flash("Glass sheet recorded successfully!", "success")

        return redirect(url_for("list_glass"))



    textures = db.execute("SELECT * FROM GTL").fetchall()
    colors = db.execute("SELECT * FROM COLOR").fetchall()
    sources = db.execute("SELECT * FROM GSL").fetchall()
    transparency = db.execute("SELECT * FROM GTRNS").fetchall()
    return render_template(
        "glass_form.html", textures=textures, transparency=transparency, colors=colors, sources=sources
    )
# --- GLASS DETAIL SUMMARY PAGE ---
@app.route('/glass/<int:glass_id>')
def glass_detail(glass_id):
    db = get_db()
    # Fetch glass details with pricing history, supplier details, and hex color code
    glass = db.execute('''
        SELECT g.*, p.GLSPRICE, s.SRCWEB, s.GLSLOGO, c.CHEX
        FROM GSI g
        LEFT JOIN GPC p ON g.GLASSID = p.GLASSID
        LEFT JOIN GSL s ON g.GLSOURCE = s.GLSOURCE
        LEFT JOIN COLOR c ON g.COLOR = c.COLOR
        WHERE g.GLASSID = ?
    ''', (glass_id,)).fetchone()

    if not glass:
        flash('Glass sheet record not found.', 'danger')
        return redirect(url_for('list_glass'))

    # Fetch any items that utilize this glass as a component (IGC)
    components = db.execute('''
        SELECT c.*, i.ITMNAME 
        FROM IGC c
        JOIN ITM i ON c.ITEMID = i.ITEMID
        WHERE c.GLASSID = ?
    ''', (glass_id,)).fetchall()

    return render_template(
        'glass_detail.html', glass=glass, components=components
    )

@app.route('/glass/edit/<int:glass_id>', methods=['GET', 'POST'])

def edit_glass(glass_id):

    db = get_db()

    glass = db.execute('''
        SELECT g.*, p.GLSPRICE, c.CHEX 
        FROM GSI g 
        LEFT JOIN GPC p ON g.GLASSID = p.GLASSID 
        LEFT JOIN COLOR c ON g.COLOR = c.COLOR 
        LEFT JOIN GTRNS t ON g.GTRNSN = t.GTRNSN
        WHERE g.GLASSID = ?

    ''', (glass_id,)).fetchone()

    if not glass:
        flash('Glass sheet record not found.', 'danger')
        return redirect(url_for('list_glass'))

    if request.method == 'POST':
        glsname = request.form.get('GLSNAME')
        glsmanf = request.form.get('GLSMANF')
        glstex = request.form.get('GLSTEX') or None
        gtrnsn = request.form.get('GTRNSN') or None
        color = request.form.get('COLOR') or None
        glsource = request.form.get('GLSOURCE') or None
        glslen = request.form.get('GLSLEN') or None
        glswid = request.form.get('GLSWID') or None
        glsthk = request.form.get('GLSTHK') or None
        glsiri = 1 if request.form.get('GLSIRI') else 0
        glsopal = 1 if request.form.get('GLSOPAL') else 0
        gllink = request.form.get('GLLINK') or None
        glsnote = request.form.get('GLSNOTE')
        price = request.form.get('GLSPRICE')



        # Handle File Upload or maintain manual text string entry
        file = request.files.get('GLSIMG_FILE')
        if file and file.filename != '':
            pattern_name = f"{glass_id}_{glsname}"
            glsimg = process_and_save_image(
                file_obj=file,
                upload_subfolder='images/glass',
                custom_filename_base=pattern_name,
                target_size=(256, 256)
            )
        else:
            # Fall back to existing field value or manual input string
            glsimg = request.form.get('GLSIMG') or glass['GLSIMG']

        # Update GSI table
        db.execute(
            '''
            UPDATE GSI 
            SET GLSNAME = ?, GLSMANF = ?, GLSTEX = ?, GTRNSN = ?, COLOR = ?, GLSOURCE = ?, 
                GLSLEN = ?, GLSWID = ?, GLSTHK = ?, GLSIRI = ?, 
                GLSOPAL = ?, GLLINK = ?, GLSIMG = ?, GLSNOTE = ?
            WHERE GLASSID = ?
        ''',
            (
                glsname,
                glsmanf,
                glstex,
                gtrnsn,
                color,
                glsource,
                glslen,
                glswid,
                glsthk,
                glsiri,
                glsopal,
                gllink,
                glsimg,
                glsnote,
                glass_id,
            ),
        )

        # Update or Insert pricing into GPC
        if price:
            existing_price = db.execute(
                'SELECT * FROM GPC WHERE GLASSID = ?', (glass_id,)
            ).fetchone()
            if existing_price:
                db.execute(
                    '''
                    UPDATE GPC SET GLSPRICE = ?, STDATE = DATE('now') WHERE GLASSID = ?
                ''',
                    (price, glass_id),
                )
            else:
                db.execute(
                    '''
                    INSERT INTO GPC (GLASSID, GLSPRICE, STDATE) VALUES (?, ?, DATE('now'))
                ''',
                    (glass_id, price),
                )

        db.commit()
        flash('Glass details updated successfully!', 'success')
        return redirect(url_for('glass_detail', glass_id=glass_id))

    textures = db.execute('SELECT * FROM GTL').fetchall()
    transparency = db.execute('SELECT * FROM GTRNS').fetchall()
    colors = db.execute('SELECT * FROM COLOR').fetchall()
    sources = db.execute('SELECT * FROM GSL').fetchall()

    return render_template(
        'glass_form.html',
        glass=glass,
        textures=textures,
        transparency=transparency,
        colors=colors,
        sources=sources,
        action='Edit',

    )

@app.route('/glass/delete/<int:glass_id>', methods=['POST'])
def delete_glass(glass_id):
    db = get_db()
    
    # Perform a soft delete by setting ISACTIVE flag to 0
    db.execute("UPDATE GSI SET ISACTIVE = 0 WHERE GLASSID = ?", (glass_id,))
    db.commit()
    
    flash(f"Glass sheet #{glass_id} deactivated successfully.", "warning")
    return redirect(url_for('list_glass'))

@app.route('/glass/inventory', methods=['GET', 'POST'])
def glass_inventory():

    db = get_db()

    if request.method == 'POST':
        glass_id = request.form.get('GLASSID')
        adjustment = request.form.get('GLSSTOCK')
        trans_date = request.form.get('TS') or date.today().isoformat()

        if glass_id and adjustment:
            db.execute(
                """
                INSERT INTO GLSINV (GLASSID, GLSSTOCK, TS)
                VALUES (?, ?, ?)
                """,
                (glass_id, int(adjustment), trans_date)
            )
            db.commit()
            flash("Inventory level adjusted successfully!", "success")
        else:
            flash("Invalid input parameters for stock adjustment.", "danger")
            
        return redirect(url_for('glass_inventory'))

    # --- Capture Sort & Filter Parameters ---
    sort_by = request.args.get('sort_by', 'GLSNAME')
    order = request.args.get('order', 'asc').lower()
    if order not in ['asc', 'desc']:
        order = 'asc'

    q = request.args.get('q', '').strip()
    manf = request.args.get('manf', '').strip()
    tex = request.args.get('tex', '').strip()
    color = request.args.get('color', '').strip()
    source = request.args.get('source', '').strip()
    min_price = request.args.get('min_price', '').strip()
    max_price = request.args.get('max_price', '').strip()
    stock_filter = request.args.get('stock_filter', '').strip()
    iridescent_filter = request.args.get('iridescent')
    opalescent_filter = request.args.get('opalescent')
    stock_display_mode = request.args.get('stock_display', 'all')

    allowed_sorts = {
        'GLASSID': 'GLASSID',
        'GLSNAME': 'GLSNAME',
        'GLSMANF': 'GLSMANF',
        'GLSTEX': 'GLSTEX',
        'COLOR': 'COLOR',
        'COLOR_HSV': 'COLOR_HSV',
        'GLSIRI': 'GLSIRI',
        'GLSOPAL': 'GLSOPAL',
        'GLSLEN': 'GLSLEN',
        'CURRENT_STOCK': 'CURRENT_STOCK',
        'LAST_UPDATED': 'LAST_UPDATED'
    }
    
    # If sorting by COLOR_HSV, fetch sorted by secondary or default column from SQL, then sort in Python
    sql_sort_column = 'GLSNAME' if sort_by == 'COLOR_HSV' else allowed_sorts.get(sort_by, 'GLSNAME')

    # Build dynamic WHERE clause for base query
    where_clauses = ["g.ISACTIVE = 1"]
    params = []

    if q:
        where_clauses.append("(g.GLSNAME LIKE ? OR g.GLSMANF LIKE ? OR g.GLSNOTE LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if manf:
        where_clauses.append("g.GLSMANF = ?")
        params.append(manf)
    if tex:
        where_clauses.append("g.GLSTEX = ?")
        params.append(tex)
    if color:
        where_clauses.append("g.COLOR = ?")
        params.append(color)
    if iridescent_filter:
        where_clauses.append("g.GLSIRI = ?")
        params.append(iridescent_filter)
    if opalescent_filter:
        where_clauses.append("g.GLSOPAL = ?")
        params.append(opalescent_filter)
    if source:
        where_clauses.append("g.GLSOURCE = ?")
        params.append(source)
    if min_price:
        where_clauses.append("p.GLSPRICE >= ?")
        params.append(min_price)
    if max_price:
        where_clauses.append("p.GLSPRICE <= ?")
        params.append(max_price)

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

    # Add GROUP BY GLASSID so the HAVING clause is valid syntax in SQLite
    stock_having_sql = f"GROUP BY GLASSID HAVING {' AND '.join(having_conditions)}" if having_conditions else ""

    query = f"""
        SELECT GLASSID, GLSNAME, GLSMANF, GLSLEN, GLSWID, GLSTHK, GLSTEX, 
               GLSIRI, GLSOPAL, GLSOURCE, GLLINK, GLSIMG, GLSNOTE, COLOR, 
               ISACTIVE, CHEX, GLSPRICE, SRCWEB, CURRENT_STOCK, LAST_UPDATED
        FROM (
            SELECT g.GLASSID, g.GLSNAME, g.GLSMANF, g.GLSLEN, g.GLSWID, g.GLSTHK, 
                   g.GLSTEX, g.GLSIRI, g.GLSOPAL, g.GLSOURCE, g.GLLINK, g.GLSIMG, 
                   g.GLSNOTE, g.COLOR, g.ISACTIVE, c.CHEX, p.GLSPRICE, l.SRCWEB,
                   COALESCE((
                       SELECT i.GLSSTOCK 
                       FROM GLSINV i 
                       WHERE i.GLASSID = g.GLASSID 
                       ORDER BY i.TS DESC, i.GLSTRNID DESC 
                       LIMIT 1
                   ), 0) AS CURRENT_STOCK,
                   (
                       SELECT i.TS 
                       FROM GLSINV i 
                       WHERE i.GLASSID = g.GLASSID 
                       ORDER BY i.TS DESC, i.GLSTRNID DESC 
                       LIMIT 1
                   ) AS LAST_UPDATED
            FROM GSI g
            LEFT JOIN COLOR c ON g.COLOR = c.COLOR
            LEFT JOIN GPC p ON g.GLASSID = p.GLASSID
            LEFT JOIN GSL l ON g.GLSOURCE = l.GLSOURCE
            {where_sql}
        ) sub
        {stock_having_sql}
        ORDER BY {sql_sort_column} {order.upper()}
    """
    raw_items = db.execute(query, params).fetchall()

    # Post-process items to attach HSV values and handle numeric sort cleanly if requested
    inventory_items = []
    for row in raw_items:
        item = dict(row)
        item['COLOR_HSV'] = hex_to_hsv(item.get('CHEX'))
        inventory_items.append(item)

    if sort_by == 'COLOR_HSV':
        inventory_items.sort(
            key=lambda x: x['COLOR_HSV'],
            reverse=(order == 'desc')
        )

    # --- Fetch Lookups for Filter Dropdowns ---
    textures = db.execute("SELECT DISTINCT GLSTEX FROM GSI WHERE ISACTIVE = 1 AND GLSTEX IS NOT NULL AND GLSTEX != '' ORDER BY GLSTEX").fetchall()
    colors = db.execute("SELECT * FROM COLOR ORDER BY COLOR").fetchall()
    sources = db.execute("SELECT DISTINCT GLSOURCE FROM GSI WHERE ISACTIVE = 1 AND GLSOURCE IS NOT NULL AND GLSOURCE != '' ORDER BY GLSOURCE").fetchall()
    manufacturers = db.execute("SELECT DISTINCT GLSMANF FROM GSI WHERE ISACTIVE = 1 AND GLSMANF IS NOT NULL AND GLSMANF != '' ORDER BY GLSMANF").fetchall()
    iridescent_options = db.execute("SELECT DISTINCT GLSIRI FROM GSI WHERE ISACTIVE = 1 AND GLSIRI = 1").fetchall()
    opalescent_options = db.execute("SELECT DISTINCT GLSOPAL FROM GSI WHERE ISACTIVE = 1 AND GLSOPAL = 1").fetchall()

    return render_template(
        'glass_inventory.html',
        inventory_items=inventory_items,
        textures=textures,
        colors=colors,
        sources=sources,
        manufacturers=manufacturers,
        iridescent_options=iridescent_options,
        opalescent_options=opalescent_options,
        current_sort=sort_by,
        current_order=order,
        today_date=date.today().isoformat(),
        filters={
            'q': request.args.get('q', ''),
            'manf': request.args.get('manf', ''),
            'tex': request.args.get('tex', ''),
            'color': request.args.get('color', ''),
            'source': request.args.get('source', ''),
            'min_price': request.args.get('min_price', ''),
            'max_price': request.args.get('max_price', ''),
            'stock_filter': request.args.get('stock_filter', ''),
            'stock_display': stock_display_mode,
            'iridescent': request.args.get('iridescent', ''),
            'opalescent': request.args.get('opalescent', '')
        }
    )

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


@app.route('/misc_items')
def list_misc():
    db = get_db()

    # --- Capture Sort & Filter Parameters ---
    sort_by = request.args.get('sort_by', 'MSIID')
    order = request.args.get('order', 'asc').lower()
    if order not in ['asc', 'desc']:
        order = 'asc'

    q = request.args.get('q', '').strip()
    min_price = request.args.get('min_price', '').strip()
    max_price = request.args.get('max_price', '').strip()

    # Filter parameter for Misc active status (Defaults to showing active glass '1')
    is_active = request.args.get('is_active', '1').strip()

    item_id = request.args.get('item_id', '').strip()
    item_name = request.args.get('item_name', '').strip()
    msi_type = request.args.get('msi_type', '').strip()
    active_only = request.args.get('active_only', '')  # '1' if active items only

    allowed_sorts = {
        'MSIID': 'm.MSIID',
        'MSINAME': 'm.MSINAME',
        'MSIPRICE': 'p.MSIPRICE',
        'MSITYPE': 'm.MSITYPE'
    }
    sort_column = allowed_sorts.get(sort_by, 'm.MSIID')

    # Build dynamic WHERE clause for MSI table
    where_clauses = []
    params = []

    # Filter Glass by ISACTIVE integer flag
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

    # Filter by specific Item ID (Misc item  used in selected Item)
    join_igc = ""
    if item_id:
        join_igc = "INNER JOIN MSL l ON m.MSIID = l.MSIID"
        where_clauses.append("l.ITEMID = ?")
        params.append(item_id)
       

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

# Execute main query
    query = f"""
        SELECT DISTINCT m.*, p.MSIPRICE 
        FROM MSI m
        LEFT JOIN MSP p ON m.MSIID = p.MSIID
        {join_igc}
        {where_sql}
        ORDER BY {sort_column} {order.upper()}
    """
    misc_items = db.execute(query, params).fetchall()


    # Resolve human-readable item name if item_id was passed
    item_name = ""
    if item_id:
        for item in items:
            if str(item['ITEMID']) == str(item_id):
                item_name = item['ITMNAME']
                break

    misc_types = db.execute('SELECT * FROM MST').fetchall()


    return render_template(
        'misc_list.html',
        misc_items=misc_items,
        current_sort=sort_by,
        current_order=order,
        misc_types=misc_types,
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
@app.route("/misc_items/new", methods=["GET", "POST"])
def create_misc():

    db = get_db()
    if request.method == "POST":

        msiname = request.form.get('MSINAME')
        msiimg = request.form.get('MSIIMG')
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
                msiname, msiimg, msistock, msiurl,
                msinote, msiunit, unttype, msitype, isactive
            ),
        )

        misc_id = cursor.lastrowid

        msiimg_path = None
        file = request.files.get("MSIIMG_FILE")
        if file and file.filename != '':
            pattern_name = f"{misc_id}_{msiname}"
            glsimg_path = process_and_save_image(
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

        return redirect(url_for("list_misc"))



    unit_types = db.execute("SELECT * FROM UNTS").fetchall()
    misc_types = db.execute("SELECT * FROM MST").fetchall()

    return render_template(
        "misc_form.html", unit_types=unit_types, misc_types=misc_types
    )
# --- MISC DETAIL SUMMARY PAGE ---
@app.route('/misc_item/<int:misc_id>')
def misc_detail(misc_id):
    db = get_db()

    misc = db.execute('''
        SELECT m.*, u.UNTTYPE, u.CFACTOR
        FROM MSI m
        JOIN UNTS u ON m.UNTTYPE = u.UNTTYPE
        WHERE m.MSIID = ?
    ''', (misc_id,)).fetchone()

    if not misc:
        flash('Misc Item record not found.', 'danger')
        return redirect(url_for('list_misc'))

    # Fetch any items that utilize this misc item
    items = db.execute('''
        SELECT m.*, i.IMIAMT, t.ITMNAME
        FROM MSI m
        LEFT JOIN UNTS u ON m.UNTTYPE = u.UNTTYPE
        LEFT JOIN IMI i on m.MSIID = i.MSIID
        LEFT JOIN ITM t ON i.ITEMID = t.ITEMID

        WHERE m.MSIID = ?
    ''', (misc_id,)).fetchall()

    # Fetch Pricing Metrics from IPC table using correct columns (ITMPRICE, STDATE, ENDDATE)
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

@app.route('/misc_items/edit/<int:misc_id>', methods=['GET', 'POST'])

def edit_misc(misc_id):

    db = get_db()

    misc = db.execute('''
        SELECT m.*, p.MSIPRICE 
        FROM MSI m 
        LEFT JOIN MSP p ON m.MSIID = p.MSIID 
        WHERE m.MSIID = ?

    ''', (misc_id,)).fetchone()

    if not misc:
        flash('Misc Item record not found.', 'danger')
        return redirect(url_for('list_misc'))

    if request.method == 'POST':
        msiname = request.form.get('MSINAME')
        msiimg = request.form.get('MSIIMG')
        msistock = request.form.get('MSISTOCK') or 0
        msiurl = request.form.get('MSIURL')
        msinote = request.form.get('MSINOTE')
        msiunit = request.form.get('MSIUNIT') or 0
        unttype = request.form.get('UNTTYPE') or None
        msitype = request.form.get('MSITYPE') or None
        msiprice = request.form.get('MSIPRICE')

        # Handle File Upload or maintain manual text string entry
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
            # Fall back to existing field value or manual input string
            msiimg = request.form.get('MSIIMG') or misc['MSIIMG']

        # Update MSI table
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

        # Update or Insert pricing into MSP
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
        flash('Glass details updated successfully!', 'success')
        return redirect(url_for('misc_detail', misc_id=misc_id))

    unit_types = db.execute("SELECT * FROM UNTS").fetchall()
    misc_types = db.execute("SELECT * FROM MST").fetchall()



    return render_template(
        'misc_form.html', misc=misc, unit_types=unit_types, misc_types=misc_types,
        action='Edit',

    )

@app.route('/misc_items/delete/<int:misc_id>', methods=['POST'])
def delete_misc(misc_id):
    db = get_db()
    
    # Perform a soft delete by setting ISACTIVE flag to 0
    db.execute("UPDATE MSI SET ISACTIVE = 0 WHERE MSIID = ?", (misc_id,))
    db.commit()
    
    flash(f"Misc Item #{misc_id} deactivated successfully.", "warning")
    return redirect(url_for('list_misc'))

@app.route('/misc_items/inventory', methods=['GET', 'POST'])
def misc_inventory():

    db = get_db()
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
            
        return redirect(url_for('misc_inventory'))

# --- Capture Sort & Filter Parameters ---
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
    sort_column = allowed_sorts.get(sort_by, 'MSIID')
    sql_sort_column = 'MSINAME' if sort_by == 'MSITYPE' else allowed_sorts.get(sort_by, 'MSINAME')

    # Build dynamic WHERE clause for base query
    where_clauses = ["m.ISACTIVE = 1"]
    params = []

    if q:
        where_clauses.append("(m.MSINAME LIKE ? OR m.MSIMANF LIKE ? OR m.MSINOTE LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

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

    # Group by MSIID and other selected columns to satisfy SQLite constraints
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

    # --- Fetch Lookups for Filter Dropdowns ---
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
            'q': request.args.get('q', ''),
            'min_price': request.args.get('min_price', ''),
            'max_price': request.args.get('max_price', ''),
            'stock_filter': request.args.get('stock_filter', ''),
            'stock_display': stock_display_mode,
            'misc_type': misc_type_filter,
        }
    )


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


@app.route('/prices/misc/<int:misc_id>/edit', methods=['GET', 'POST'])
def edit_misc_prices(misc_id):
  """Manage and insert prices with automated date shuffling and interval overlap adjustments."""
  db = get_db()
  item = db.execute(
      'SELECT * FROM MSI WHERE MSIID = ?', (misc_id,)
  ).fetchone()

  if not item:
    flash('Item record not found.', 'danger')
    return redirect(url_for('index'))

  if request.method == 'POST':
    try:
      new_price = float(request.form.get('MSIPRICE'))
    except (TypeError, ValueError):
      flash('Invalid price value provided.', 'danger')
      return redirect(url_for('edit_misc_prices', misc_id=misc_id))

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
      return redirect(url_for('edit_misc_prices', misc_id=misc_id))

    cursor = db.cursor()

    # Fetch existing price intervals for this item
    existing_prices = cursor.execute(
        """
        SELECT rowid, MSIPRICE, STDATE, ENDDATE FROM MSP 
        WHERE MSIID = ?
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
        cursor.execute('DELETE FROM MSP WHERE rowid = ?', (row_id,))
        continue

      # Case B: New range is completely inside an existing range -> Split the existing range into two
      if ex_st and ex_end and new_st > ex_st and new_end and new_end < ex_end:
        # Update existing record to end right before new range starts (or day before)
        split_end_date = (new_st - timedelta(days=1)).strftime('%Y-%m-%d')
        cursor.execute(
            'UPDATE MSP SET ENDDATE = ? WHERE rowid = ?',
            (split_end_date, row_id)
        )

        # Insert the remaining tail piece of the old range
        tail_start_date = (new_end + timedelta(days=1)).strftime('%Y-%m-%d')

        cursor.execute(
            'INSERT INTO MSP (MSIID, MSIPRICE, STDATE, ENDDATE) VALUES (?, ?, ?, ?)',
            (item_id, row['MSIPRICE'], tail_start_date, ex_end_str)
        )
        continue

      # Case C: Overlap on the tail end of existing range (New start cuts into old range)
      if ex_st and new_st > ex_st and (ex_end is None or new_st <= ex_end):
        new_ex_end = (new_st - timedelta(days=1)).strftime('%Y-%m-%d')
        cursor.execute(
            'UPDATE MSP SET ENDDATE = ? WHERE rowid = ?',
            (new_ex_end, row_id)
        )

      # Case D: Overlap on the front end of existing range (New end cuts into old range)
      if new_end and ex_end and new_end >= ex_st and new_end < ex_end:
        new_ex_st = (new_end + timedelta(days=1)).strftime('%Y-%m-%d')
        cursor.execute(
            'UPDATE MSP SET STDATE = ? WHERE rowid = ?',
            (new_ex_st, row_id)
        )

      # Case E: If new range is ongoing (current), truncate any old ranges that overlap forward
      if is_current and ex_st and ex_st >= new_st:
        cursor.execute('DELETE FROM MSP WHERE rowid = ?', (row_id,))

    # Insert the new price record cleanly
    cursor.execute(
        """
        INSERT INTO MSP (MSIID, MSIPRICE, STDATE, ENDDATE)
        VALUES (?, ?, ?, ?)
    """,
        (misc_id, new_price, new_st_str, new_end_str),
    )

    db.commit()
    flash('Price range successfully saved and overlapping intervals adjusted.', 'success')
    return redirect(url_for('edit_misc_prices', misc_id=misc_id))

  # GET Request: fetch all price rows ordered by start date descending
  prices = db.execute(
      """
        SELECT rowid, MSIPRICE, STDATE, ENDDATE FROM IPC 
        WHERE MSIID = ? 
        ORDER BY STDATE DESC
    """,
      (item_id,),
  ).fetchall()

  return render_template(
      'misc_edit_prices.html', misc=misc, prices=prices
  )



@app.route('/prices/misc/<int:misc_id>/delete/<int:price_id>', methods=['POST'])
def delete_misc_price(misc_id, price_id):
  """Delete a specific price entry row."""
  db = get_db()
  db.execute('DELETE FROM MSP WHERE rowid = ? AND MSIID = ?', (price_id, misc_id))
  db.commit()
  flash('Price tier removed.', 'success')
  return redirect(url_for('edit_misc_prices', misc_id=misc_id))

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

            item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (selected_item_id,)).fetchone()

            if item and item['ITMPTRN']:

                try:

                    width_in = float(item['ITMLEN']) if item['ITMLEN'] else 10.0

                    height_in = float(item['ITMWID']) if item['ITMWID'] else 10.0

                except (ValueError, TypeError):

                    width_in, height_in = 10.0, 10.0



                img_path = os.path.join(app.root_path, 'static', item['ITMPTRN'])

                if os.path.exists(img_path):

                    with open(img_path, 'rb') as f:

                        file_bytes = f.read()

                    

                    # Wrap bytes in a BytesIO stream for processing functions

                    from io import BytesIO

                    

                    stream1 = BytesIO(file_bytes)

                    svg_content = trace_stencil_to_single_path_svg(stream1)



                    stream2 = BytesIO(file_bytes)

                    outline_content = trace_stencil_to_outline_svg(stream2)



                    stream3 = BytesIO(file_bytes)

                    foil_content = trace_stencil_to_filled_outline_svg(stream3)



                    total_len = compute_total_path_length(svg_content, width_in, height_in)

                    outline_len = compute_total_path_length(outline_content, width_in, height_in)

                    foil_len = compute_total_path_length(foil_content, width_in, height_in) - outline_len

                    total_len = round_to_eighth(total_len)
                    outline_len = round_to_eighth(outline_len)
                    foil_len = round_to_eighth(foil_len)
                    # Write the results to the DB

                    db.execute('''

                        UPDATE ITM 

                        SET ITMSLDR = ?, ITMCAME = ?, ITMFOIL = ?

                        WHERE ITEMID = ?

                    ''', (total_len, outline_len, foil_len, selected_item_id))

                    db.commit()

                    flash('Outline trace measurements successfully updated!', 'success')



    # Fetch active items where ISACTIVE = 1 and ITMPTRN is not null/empty for the dropdown

    items = db.execute('''

        SELECT ITEMID, ITMNAME, ITMLEN, ITMWID, ITMPTRN 

        FROM ITM 

        WHERE ISACTIVE = 1 AND ITMPTRN IS NOT NULL AND ITMPTRN != ''

        ORDER BY ITMNAME ASC

    ''').fetchall()



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






if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7665, debug=True)
