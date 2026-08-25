import os
import sqlite3
import re
import xml.etree.ElementTree as ET
from flask import Blueprint, flash, redirect, render_template, request, url_for, jsonify, current_app
import base64
from PIL import Image as PILImage
import io

component_bp = Blueprint('component_bp', __name__)



DATABASE = "inventory.db"



def get_db():

    conn = sqlite3.connect(DATABASE)

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON;")

    return conn





@component_bp.route('/build_components', methods=['GET', 'POST'])

def build_components():

    db = get_db()



    if request.method == 'POST':

        selected_item_id = request.form.get('item_id')



        if not selected_item_id:

            flash('Please select a valid item.', 'danger')

            return redirect(url_for('component_bp.build_components'))



        item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (selected_item_id,)).fetchone()



        svg_filename = item['ITMSVG'] if (item and 'ITMSVG' in item.keys()) else None



        if item and svg_filename:

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



            db.execute('DELETE FROM IGC WHERE ITEMID = ?', (selected_item_id,))



            svg_path = os.path.join(current_app.root_path, 'static', svg_filename)



            if os.path.exists(svg_path):

                try:

                    ET.register_namespace('', "http://www.w3.org/2000/svg")

                    tree = ET.parse(svg_path)

                    root = tree.getroot()



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



                    if not svg_width or not svg_height or svg_width <= 0 or svg_height <= 0:

                        svg_width, svg_height = 100.0, 100.0



                    scale_x = itm_wid_val / svg_width if has_valid_dimensions else 1.0

                    scale_y = itm_len_val / svg_height if has_valid_dimensions else 1.0



                    paths = root.findall('.//{http://www.w3.org/2000/svg}path')

                    if not paths:

                        paths = root.findall('.//path')



                    comp_counter = 1

                    for path in paths:

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

                                    from svgpathtools import parse_path

                                    parsed = parse_path(path_data)

                                    bbox = parsed.bbox()

                                    box_w = bbox[1] - bbox[0]

                                    box_h = bbox[3] - bbox[2]

                                except ImportError:

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



                            raw_wid = box_w * scale_x

                            raw_len = box_h * scale_y



                            comp_len = round(raw_len / 0.125) * 0.125

                            comp_wid = round(raw_wid / 0.125) * 0.125



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



        return redirect(url_for('component_bp.build_components'))



    items = db.execute('SELECT ITEMID, ITMNAME FROM ITM').fetchall()

    return render_template('build_components.html', items=items)





@component_bp.route('/edit_components/<int:item_id>', methods=['GET'])

def edit_components(item_id):

    db = get_db()



    item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()

    if not item:

        flash('Item not found.', 'danger')

        return redirect(url_for('index'))



    svg_filename = item['ITMSVG'] if 'ITMSVG' in item.keys() else None

    svg_url = url_for('static', filename=svg_filename) if svg_filename else ''



    glass_options = db.execute('''

        SELECT g.GLASSID, g.GLSNAME, g.GLSTEX, g.GLSIMG, c.CHEX, t.GTRNSV 

        FROM GSI g

        LEFT JOIN COLOR c ON g.COLOR = c.COLOR

        LEFT JOIN GTRNS t ON g.GTRNSN = t.GTRNSN

        WHERE g.ISACTIVE = 1

    ''').fetchall()



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

            'CHEX': comp['CHEX'] or 'cccccc',

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





@component_bp.route('/update_components_batch', methods=['POST'])

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





@component_bp.route('/export_components_image/<int:item_id>')

def export_components_image(item_id):

    db = get_db()

    item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()

    if not item:

        flash('Item not found.', 'danger')

        return redirect(url_for('index'))



    svg_filename = item['ITMSVG'] if 'ITMSVG' in item.keys() else None

    svg_url = url_for('static', filename=svg_filename) if svg_filename else ''



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



    comp_map = {}

    for comp in components:

        comp_map[comp['SVGREG']] = {

            'CHEX': comp['CHEX'] or 'cccccc',

            'GLSTEX': comp['GLSTEX'] or '',

            'GLSIMG': comp['GLSIMG'] or '',

            'GTRNSV': comp['GTRNSV'] or 75

        }



    return render_template(

        'export_components_image.html',

        item=item,

        svg_url=svg_url,

        components_json=comp_map

    )


@component_bp.route('/save_components_image/<int:item_id>', methods=['POST'])

def save_components_image(item_id):

    db = get_db()

    item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()

    if not item:

        return jsonify({'success': False, 'message': 'Item not found.'}), 404



    data = request.get_json()

    image_data = data.get('image_data')

    if not image_data:

        return jsonify({'success': False, 'message': 'No image data provided.'}), 400



    try:

        if ',' in image_data:

            header, encoded = image_data.split(',', 1)

        else:

            encoded = image_data



        image_bytes = base64.b64decode(encoded)

        

        raw_name = item['ITMNAME'] if 'ITMNAME' in item.keys() and item['ITMNAME'] else 'item'

        safe_name = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in raw_name)

        filename = f"{item_id}_{safe_name}.webp"



        base_dir = current_app.root_path

        full_dir = os.path.join(base_dir, 'static', 'images', 'item')

        thumb_dir = os.path.join(base_dir, 'static', 'images', 'item', 'thumb')



        os.makedirs(full_dir, exist_ok=True)

        os.makedirs(thumb_dir, exist_ok=True)



        full_path = os.path.join(full_dir, filename)

        thumb_path = os.path.join(thumb_dir, filename)



        image = PILImage.open(io.BytesIO(image_bytes))

        

        # Save full size webp image

        image.save(full_path, 'WEBP')



        # Create and save 25% thumbnail

        new_width = max(1, int(image.width * 0.25))

        new_height = max(1, int(image.height * 0.25))

        thumb_image = image.resize((new_width, new_height), PILImage.Resampling.LANCZOS)

        thumb_image.save(thumb_path, 'WEBP')



        db_img_value = f"images/item/{filename}"

        db.execute('UPDATE ITM SET ITMIMG = ? WHERE ITEMID = ?', (db_img_value, item_id))

        db.commit()



        return jsonify({'success': True, 'message': 'Image saved and database updated successfully!'})

    except Exception as e:

        db.rollback()

        return jsonify({'success': False, 'message': str(e)}), 500
