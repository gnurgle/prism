import os

import sqlite3

import xml.etree.ElementTree as ET

from io import BytesIO

from flask import Blueprint, flash, redirect, render_template, request, url_for, render_template_string, current_app

from lxml import etree

from utils import (

    convert_image_to_svg,

    trace_stencil_to_single_path_svg,

    compute_total_path_length,

    trace_stencil_to_outline_svg,

    trace_stencil_to_filled_outline_svg

)



templates_bp = Blueprint('templates_bp', __name__)



DATABASE = "inventory.db"

UPLOAD_FOLDER_TEMPLATES = 'static/images/templates'

UPLOAD_FOLDER_SVG = 'static/images/svg'



def get_db():

    conn = sqlite3.connect(DATABASE)

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON;")

    return conn





@templates_bp.route("/template/upload", methods=["GET", "POST"])

@templates_bp.route("/template/upload/<int:item_id>", methods=["GET", "POST"])

def upload_template(item_id=None):

    db = get_db()

    if request.method == "POST":

        selected_item_id = item_id or request.form.get("ITEMID")

        file = request.files.get("template_image")



        if not selected_item_id or not file:

            flash("Please select an item and upload an image.", "danger")

            return redirect(request.url)

            

        item = db.execute("SELECT * FROM ITM WHERE ITEMID = ?", (selected_item_id,)).fetchone()



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

        db.execute("UPDATE ITM SET ITMPTRN = ? WHERE ITEMID = ?", (relative_img_path, selected_item_id))

        db.commit()

        

        # Automatically convert to SVG using the reusable method

        svg_filename = f"{item['ITEMID']}_{safe_item_name}.svg"

        svg_path = os.path.join(UPLOAD_FOLDER_SVG, svg_filename)

        

        success = convert_image_to_svg(img_path, svg_path)

        if success:

            relative_svg_path = f"images/svg/{svg_filename}"

            db.execute("UPDATE ITM SET ITMSVG = ? WHERE ITEMID = ?", (relative_svg_path, selected_item_id))

            db.commit()

            flash("Template uploaded and converted to SVG via pyautotrace successfully!", "success")

        else:

            flash("Template uploaded, but SVG conversion failed.", "warning")

            

        return redirect(url_for('templates_bp.edit_template', item_id=selected_item_id))

        

    items = db.execute("SELECT ITEMID, ITMNAME FROM ITM").fetchall()

    return render_template("template_upload.html", items=items, selected_item_id=item_id)




@templates_bp.route("/template/whitespaces/<int:item_id>")

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

    

    clickable_regions = []

    if os.path.exists(svg_path):

        try:

            ET.register_namespace('', "http://www.w3.org/2000/svg")

            tree = ET.parse(svg_path)

            root = tree.getroot()

            

            elements = []

            for elem in root.iter():

                tag_name = elem.tag.split('}')[-1].lower()

                if tag_name in ['path', 'rect', 'polygon', 'circle', 'polyline']:

                    elements.append(elem)

            

            parsed_elements = []

            for idx, el in enumerate(elements):

                x_val = 0.0

                if el.tag.endswith('rect'):

                    x_val = float(el.attrib.get('x', 0))

                elif el.tag.endswith('circle'):

                    x_val = float(el.attrib.get('cx', 0)) - float(el.attrib.get('r', 0))

                else:

                    x_val = float(idx * 10)

                

                parsed_elements.append((x_val, idx, el))

            

            parsed_elements.sort(key=lambda item: item[0])

            

            for index, (x, orig_idx, el) in enumerate(parsed_elements, start=1):

                region_id = f"region_{index}"

                el.set('id', region_id)

                el.set('data-number', str(index))

                existing_class = el.attrib.get('class', '')

                el.set('class', f"{existing_class} whitespace-area".strip())

                el.set('style', 'cursor: pointer; fill-opacity: 0.2; stroke: #007bff; stroke-width: 2px;')

                

                clickable_regions.append({

                    "number": index,

                    "id": region_id

                })

                

            tree.write(svg_path)

            

        except Exception as e:

            print(f"Error parsing SVG for whitespaces: {e}")



    return render_template("template_whitespaces.html", item=item, svg_url=svg_url, regions=clickable_regions)





@templates_bp.route('/template/<int:item_id>/edit', methods=['GET', 'POST'])

def edit_template(item_id):

    conn = get_db()

    item = conn.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()

    

    if not item:

        conn.close()

        flash('Template not found.', 'danger')

        return redirect(url_for('index'))



    svg_file_field = item['ITMSVG'] or f"{item_id}.svg"

    svg_path = os.path.join(current_app.root_path, 'static', svg_file_field)



    message = None



    if request.method == 'POST':

        target_region_num = request.form.get('region_id')

        print(f"ROUTE CONSOLE WRITE ---> Target File: '{svg_path}' | Region to Delete: '{target_region_num}'")



        if not os.path.exists(svg_path):

            message = f"Error: File does not exist at absolute path: {svg_path}"

        else:

            try:

                parser = etree.XMLParser(remove_blank_text=True, recover=True)

                tree = etree.parse(svg_path, parser)

                path_elements = tree.xpath('//*[local-name()="path"]')



                removed = False

                for elem in path_elements:

                    region_val = elem.get('data-region-id')

                    elem_id = elem.get('id', '')



                    if (region_val and str(region_val).strip() == str(target_region_num)) or (elem_id in [f"region-{target_region_num}", str(target_region_num)]):

                        parent = elem.getparent()

                        if parent is not None:

                            parent.remove(elem)

                            removed = True

                            print(f"ROUTE SUCCESS: Removed element ID '{elem_id}', data-region-id '{region_val}'")

                        break



                if removed:

                    remaining_paths = tree.xpath('//*[local-name()="path"]')

                    for new_idx, elem in enumerate(remaining_paths, start=1):

                        elem.set('id', f'region-{new_idx}')

                        elem.set('data-region-id', str(new_idx))

                        if elem.get('data-number') is not None:

                            elem.set('data-number', str(new_idx))



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

        return redirect(url_for('templates_bp.edit_template', item_id=item_id))



    conn.close()



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





@templates_bp.route('/test_outline', methods=['GET', 'POST'])

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



    html_page = globals().get('HTML_PAGE', '')



    return render_template_string(

        html_page, 

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



def process_trace_outline(selected_item_id):

    """

    Core reusable logic to process and save trace measurements for a given item_id.

    Can be called internally by other Python methods or APIs without frontend requirements.

    """

    db = get_db()

    

    try:

        item = db.execute(

            'SELECT * FROM ITM WHERE ITEMID = ?',

            (selected_item_id,)

        ).fetchone()



        if not item:

            return {'success': False, 'message': 'Selected item not found.', 'status_code': 404}



        if not item['ITMPTRN']:

            return {'success': False, 'message': 'Selected item does not have a pattern template uploaded.', 'status_code': 400}



        try:

            width_in = float(item['ITMLEN']) if item['ITMLEN'] else 10.0

            height_in = float(item['ITMWID']) if item['ITMWID'] else 10.0

        except (ValueError, TypeError):

            width_in = 10.0

            height_in = 10.0



        img_path = os.path.join(

            current_app.root_path,

            'static',

            item['ITMPTRN']

        )



        if not os.path.exists(img_path):

            return {'success': False, 'message': f'Template image file not found at static/{item["ITMPTRN"]}', 'status_code': 404}



        with open(img_path, 'rb') as f:

            file_bytes = f.read()



        stream1 = BytesIO(file_bytes)

        svg_content = trace_stencil_to_single_path_svg(stream1)



        stream2 = BytesIO(file_bytes)

        outline_content = trace_stencil_to_outline_svg(stream2)



        stream3 = BytesIO(file_bytes)

        foil_content = trace_stencil_to_filled_outline_svg(stream3)



        total_len = compute_total_path_length(svg_content, width_in, height_in)

        outline_len = compute_total_path_length(outline_content, width_in, height_in)

        foil_len = compute_total_path_length(foil_content, width_in, height_in) - outline_len



        solder_amount = total_len

        foil_amount = foil_len

        came_amount = outline_len



        supply_updates = [

            {'itm_column': 'IMISLDR', 'msi_type': 'Solder', 'amount': solder_amount},

            {'itm_column': 'IMIFOIL', 'msi_type': 'Foil', 'amount': foil_amount},

            {'itm_column': 'IMICAME', 'msi_type': 'Came', 'amount': came_amount}

        ]



        created_imi_ids = []

        updated_imi_ids = []



        for supply in supply_updates:

            itm_column = supply['itm_column']

            msi_type = supply['msi_type']

            amount = float(supply['amount'] or 0)



            current_imi_id = item[itm_column]

            imi_row = None



            if current_imi_id:

                imi_row = db.execute(

                    """

                    SELECT i.IMIID, i.ITEMID, i.MSIID, i.IMIAMT, m.MSITYPE

                    FROM IMI i

                    JOIN MSI m ON m.MSIID = i.MSIID

                    WHERE i.IMIID = ? AND i.ITEMID = ?

                    """,

                    (current_imi_id, selected_item_id)

                ).fetchone()



                if not imi_row or imi_row['MSITYPE'] != msi_type:

                    imi_row = None



            if not imi_row:

                imi_row = db.execute(

                    """

                    SELECT i.IMIID, i.ITEMID, i.MSIID, i.IMIAMT, m.MSITYPE

                    FROM IMI i

                    JOIN MSI m ON m.MSIID = i.MSIID

                    WHERE i.ITEMID = ? AND m.MSITYPE = ?

                    ORDER BY i.IMIID LIMIT 1

                    """,

                    (selected_item_id, msi_type)

                ).fetchone()



            if not imi_row:

                msi_row = db.execute(

                    "SELECT MSIID FROM MSI WHERE MSITYPE = ? AND ISACTIVE = 1 ORDER BY MSIID LIMIT 1",

                    (msi_type,)

                ).fetchone()



                if not msi_row:

                    continue



                cursor = db.execute(

                    "INSERT INTO IMI (ITEMID, MSIID, IMIAMT) VALUES (?, ?, ?)",

                    (selected_item_id, msi_row['MSIID'], amount)

                )

                new_imi_id = cursor.lastrowid

                db.execute(f"UPDATE ITM SET {itm_column} = ? WHERE ITEMID = ?", (new_imi_id, selected_item_id))

                created_imi_ids.append(new_imi_id)

            else:

                db.execute(

                    "UPDATE IMI SET IMIAMT = ? WHERE IMIID = ? AND ITEMID = ?",

                    (amount, imi_row['IMIID'], selected_item_id)

                )

                updated_imi_ids.append(imi_row['IMIID'])



        db.commit()

        return {

            'success': True,

            'message': 'Trace measurements successfully calculated and saved!',

            'created_imi_ids': created_imi_ids,

            'updated_imi_ids': updated_imi_ids,

            'svg_content': svg_content,

            'outline_content': outline_content,

            'foil_content': foil_content,

            'total_len': total_len,

            'outline_len': outline_len,

            'foil_len': foil_len

        }

    except Exception as e:

        db.rollback()

        return {'success': False, 'message': f'Unable to save trace measurements: {e}', 'status_code': 500}





@templates_bp.route('/trace_outline', methods=['GET', 'POST'])

@templates_bp.route('/trace_outline/<int:item_id>', methods=['GET', 'POST'])

def trace_outline(item_id=None):

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

    selected_item_id = item_id



    if request.method == 'POST':

        selected_item_id = item_id or request.form.get('item_id')



        if selected_item_id:

            result = process_trace_outline(selected_item_id)

            if result['success']:

                svg_content = result.get('svg_content')

                outline_content = result.get('outline_content')

                foil_content = result.get('foil_content')

                total_len = result.get('total_len', 0.0)

                outline_len = result.get('outline_len', 0.0)

                foil_len = result.get('foil_len', 0.0)

                

                if result.get('created_imi_ids'):

                    flash(f"Created IMI record(s): {', '.join(map(str, result['created_imi_ids']))}", 'success')

                if result.get('updated_imi_ids'):

                    flash(f"Updated IMI record(s): {', '.join(map(str, result['updated_imi_ids']))}", 'success')

            else:

                flash(result['message'], 'danger')



    items = db.execute(

        '''

        SELECT ITEMID, ITMNAME, ITMLEN, ITMWID, ITMPTRN

        FROM ITM

        WHERE ISACTIVE = 1 AND ITMPTRN IS NOT NULL AND ITMPTRN != ''

        ORDER BY ITMNAME ASC

        '''

    ).fetchall()



    return render_template(

        'trace_outline.html',

        items=items,

        selected_item_id=int(selected_item_id) if selected_item_id else None,

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





@templates_bp.route('/api/trace_outline/<int:item_id>', methods=['POST'])

def api_trace_outline(item_id):

    """API endpoint to trigger outline tracing for a specific item programmatically."""

    result = process_trace_outline(item_id)

    status_code = result.pop('status_code', 200 if result['success'] else 400)

    return jsonify(result), status_code
