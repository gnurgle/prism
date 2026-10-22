import os
import xml.etree.ElementTree as ET
from flask import flash, redirect, render_template, request, url_for, current_app
import sqlite3
from utils import convert_image_to_svg
from .trace import process_trace_outline

UPLOAD_FOLDER_TEMPLATES = 'static/images/templates'
UPLOAD_FOLDER_SVG = 'static/images/svg'

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_upload_routes(bp):
    @bp.route("/template/upload", methods=["GET", "POST"])
    @bp.route("/template/upload/<int:item_id>", methods=["GET", "POST"])
    def upload_template(item_id=None):
        db = get_db()
        if request.method == "POST":
            selected_item_id = item_id or request.form.get("ITEMID")
            file = request.files.get("template_image")
            is_full_sheet = request.form.get("full_sheet")
            if not selected_item_id or not file:
                flash("Please select an item and upload an image.", "danger")
                return redirect(request.url)
            
            item = db.execute("SELECT * FROM ITM WHERE ITEMID = ?", (selected_item_id,)).fetchone()
            if not item:
                flash("Selected item not found.", "danger")
                return redirect(url_for("index"))
                
            safe_item_name = "".join(c for c in item['ITMNAME'] if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
            file_ext = os.path.splitext(file.filename)[1] or '.png'
            filename = f"{selected_item_id}_{safe_item_name}{file_ext}"
            
            img_path = os.path.join(current_app.root_path, UPLOAD_FOLDER_TEMPLATES, filename)
            os.makedirs(os.path.dirname(img_path), exist_ok=True)
            file.save(img_path)
            
            db.execute("UPDATE ITM SET ITMPTRN = ? WHERE ITEMID = ?", (f"images/templates/{filename}", selected_item_id))
            db.commit()
            
            svg_filename = f"{selected_item_id}_{safe_item_name}.svg"
            svg_path = os.path.join(current_app.root_path, UPLOAD_FOLDER_SVG, svg_filename)
            os.makedirs(os.path.dirname(svg_path), exist_ok=True)
            
            success = convert_image_to_svg(img_path, svg_path)
            if success:
                db.execute("UPDATE ITM SET ITMSVG = ? WHERE ITEMID = ?", (f"images/svg/{svg_filename}", selected_item_id))
                db.commit()
                trace_result = process_trace_outline(selected_item_id)
                
                if is_full_sheet:
                    try:
                        svg_data = trace_result.get('outline_content') or trace_result.get('svg_content')
                        if svg_data:
                            if isinstance(svg_data, bytes): svg_data = svg_data.decode('utf-8')
                            root = ET.fromstring(svg_data)
                            width_px, height_px = None, None
                            view_box = root.attrib.get('viewBox')
                            if view_box:
                                parts = [float(p) for p in view_box.replace(',', ' ').split() if p.strip()]
                                if len(parts) == 4: width_px, height_px = parts[2], parts[3]
                            if not width_px or not height_px:
                                w_attr = root.attrib.get('width', '').replace('px', '').strip()
                                h_attr = root.attrib.get('height', '').replace('px', '').strip()
                                if w_attr and h_attr: width_px, height_px = float(w_attr), float(h_attr)
                            if width_px and height_px:
                                raw_width_in, raw_height_in = width_px / 225.0, height_px / 225.0
                                length_in, width_in = round(round(raw_height_in / 0.125) * 0.125, 3), round(round(raw_width_in / 0.125) * 0.125, 3)
                                db.execute("UPDATE ITM SET ITMLEN = ?, ITMWID = ? WHERE ITEMID = ?", (str(length_in), str(width_in), selected_item_id))
                                db.commit()
                    except Exception as e:
                        print(f"Error calculating dimensions from SVG outline: {e}")
                flash("Template uploaded, converted to SVG, and outline traced successfully!", "success")
            else:
                flash("Template uploaded, but SVG conversion failed.", "warning")
            return redirect(url_for('templates_bp.edit_template', item_id=selected_item_id))
            
        items = db.execute("SELECT ITEMID, ITMNAME FROM ITM").fetchall()
        return render_template("template_upload.html", items=items, selected_item_id=item_id)