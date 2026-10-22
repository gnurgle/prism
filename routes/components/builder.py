import os
import sqlite3
import re
import xml.etree.ElementTree as ET
from flask import flash, redirect, render_template, request, url_for, jsonify, current_app

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def process_build_components(selected_item_id):
    """
    Core reusable logic to build components for a given item_id.
    Can be called internally by other Python methods without frontend requirements.
    Returns a dictionary indicating success status and a message.
    """
    db = get_db()
    try:
        item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (selected_item_id,)).fetchone()
        if not item:
            return {'success': False, 'message': 'Selected item not found.', 'status_code': 404}
        svg_filename = item['ITMSVG'] if 'ITMSVG' in item.keys() else None
        if not svg_filename:
            return {'success': False, 'message': 'Selected item does not have a reference SVG file or ITMSVG is empty.', 'status_code': 400}
        item_keys = item.keys()
        itm_len = item['ITMLEN'] if 'ITMLEN' in item_keys else None
        itm_wid = item['ITMWID'] if 'ITMWID' in item_keys else None
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
        if not os.path.exists(svg_path):
            return {'success': False, 'message': f'SVG file not found at static/{svg_filename}', 'status_code': 404}
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
        return {'success': True, 'message': 'Components successfully built and saved to IGC!'}
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': f'Error parsing SVG file: {str(e)}', 'status_code': 500}

def register_builder_routes(bp):
    @bp.route('/build_components', methods=['GET', 'POST'])
    def build_components():
        db = get_db()
        if request.method == 'POST':
            selected_item_id = request.form.get('item_id')
            if not selected_item_id:
                flash('Please select a valid item.', 'danger')
                return redirect(url_for('component_bp.build_components'))
            result = process_build_components(selected_item_id)
            flash(result['message'], 'success' if result['success'] else 'danger')
            return redirect(url_for('component_bp.build_components'))
        items = db.execute('SELECT ITEMID, ITMNAME FROM ITM').fetchall()
        return render_template('build_components.html', items=items)

    @bp.route('/api/build_components/<int:item_id>', methods=['POST'])
    def api_build_components(item_id):
        """API endpoint to trigger building components for a specific item programmatically."""
        result = process_build_components(item_id)
        status_code = result.pop('status_code', 200 if result['success'] else 400)
        return jsonify(result), status_code