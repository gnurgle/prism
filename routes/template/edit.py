import os
import xml.etree.ElementTree as ET
from flask import flash, redirect, render_template, request, url_for, current_app
import sqlite3
from lxml import etree

UPLOAD_FOLDER_SVG = 'static/images/svg'

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_edit_routes(bp):
    

    @bp.route('/template/<int:item_id>/edit', methods=['GET', 'POST'])
    def edit_template(item_id):
        conn = get_db()
        came_from_upload = bool(request.referrer and '/template/upload' in request.referrer)
        item = conn.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()
        if not item:
            conn.close()
            flash('Template not found.', 'danger')
            return redirect(url_for('index'))
            
        svg_file_field = item['ITMSVG'] or f"{item_id}.svg"
        svg_path = os.path.join(current_app.root_path, 'static', svg_file_field)
        
        if request.method == 'POST':
            target_region_num = request.form.get('region_id')
            if not os.path.exists(svg_path):
                flash(f"Error: File does not exist at absolute path: {svg_path}", "danger")
            else:
                try:
                    parser = etree.XMLParser(remove_blank_text=True, recover=True)
                    tree = etree.parse(svg_path, parser)
                    path_elements = tree.xpath('//*[local-name()="path"]')
                    removed = False
                    for elem in path_elements:
                        region_val, elem_id = elem.get('data-region-id'), elem.get('id', '')
                        if (region_val and str(region_val).strip() == str(target_region_num)) or (elem_id in [f"region-{target_region_num}", str(target_region_num)]):
                            parent = elem.getparent()
                            if parent is not None:
                                parent.remove(elem)
                                removed = True
                            break
                    if removed:
                        for new_idx, elem in enumerate(tree.xpath('//*[local-name()="path"]'), start=1):
                            elem.set('id', f'region-{new_idx}')
                            elem.set('data-region-id', str(new_idx))
                            if elem.get('data-number') is not None: elem.set('data-number', str(new_idx))
                        xml_bytes = etree.tostring(tree.getroot(), pretty_print=True, xml_declaration=True, encoding='utf-8')
                        with open(svg_path, 'wb') as f: f.write(xml_bytes)
                        flash(f"Success! Region {target_region_num} deleted and file updated on disk.", "success")
                    else:
                        flash(f"Warning: Could not find any path matching region ID '{target_region_num}' in {svg_file_field}.", "warning")
                except Exception as e:
                    flash(f"Exception occurred during processing: {str(e)}", "danger")
            conn.close()
            return redirect(url_for('templates_bp.edit_template', item_id=item_id))
            
        svg_mtime = int(os.path.getmtime(svg_path)) if os.path.exists(svg_path) else 0
        conn.close()
        paths_list = []
        if os.path.exists(svg_path):
            try:
                parser = etree.XMLParser(remove_blank_text=True, recover=True)
                tree = etree.parse(svg_path, parser)
                for idx, elem in enumerate(tree.xpath('//*[local-name()="path"]')):
                    region_label = elem.get('data-region-id') or elem.get('data-number') or str(idx + 1)
                    paths_list.append({'index': idx, 'id': elem.get('id', f'path-{idx+1}'), 'label': region_label, 'data_region_id': region_label})
            except Exception as e:
                print(f"Error reading paths for template view: {e}")
                
        return render_template('edit_template.html', item=item, paths_list=paths_list, came_from_upload=came_from_upload, svg_mtime=svg_mtime)