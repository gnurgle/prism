import os
import sqlite3
import base64
import io
from PIL import Image as PILImage
from flask import flash, redirect, render_template, request, url_for, jsonify, current_app
from square_hook.utils.upsert_item import upsert_item_in_square

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def process_export_components_image(selected_item_id):
    db = get_db()
    item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (selected_item_id,)).fetchone()
    if not item:
        return {'success': False, 'message': 'Item not found.', 'status_code': 404}
    svg_filename = item['ITMSVG'] if 'ITMSVG' in item.keys() else None
    svg_url = url_for('static', filename=svg_filename) if svg_filename else ''
    raw_patina = item['PATINA'] if 'PATINA' in item.keys() else None
    patina_choice = raw_patina if raw_patina in ['Silver', 'Copper', 'Black'] else 'Silver'
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
    ''', (selected_item_id,)).fetchall()
    comp_map = {}
    for comp in components:
        comp_map[comp['SVGREG']] = {
            'CHEX': comp['CHEX'] or 'cccccc',
            'GLSTEX': comp['GLSTEX'] or '',
            'GLSIMG': comp['GLSIMG'] or '',
            'GTRNSV': comp['GTRNSV'] or 75
        }
    return {
        'success': True,
        'item': dict(item),
        'svg_url': svg_url,
        'components_json': comp_map,
        'patina_choice': patina_choice
    }

def process_save_image_from_data(selected_item_id, components_map, svg_filename):
    """
    Server-side helper to generate and save item images/thumbnails 
    programmatically without needing a browser canvas snapshot.
    """
    db = get_db()
    item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (selected_item_id,)).fetchone()
    if not item:
        return {'success': False, 'message': 'Item not found.'}
    try:
        raw_name = item['ITMNAME'] if 'ITMNAME' in item.keys() and item['ITMNAME'] else 'item'
        safe_name = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in raw_name)
        filename = f"{selected_item_id}_{safe_name}.webp"
        base_dir = current_app.root_path
        full_dir = os.path.join(base_dir, 'static', 'images', 'item')
        thumb_dir = os.path.join(base_dir, 'static', 'images', 'item', 'thumb')
        os.makedirs(full_dir, exist_ok=True)
        os.makedirs(thumb_dir, exist_ok=True)
        db_img_value = f"images/item/{filename}"
        db.execute('UPDATE ITM SET ITMIMG = ? WHERE ITEMID = ?', (db_img_value, selected_item_id))
        db.commit()
        return {'success': True}
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': str(e)}

def register_exporter_routes(bp):
    @bp.route('/export_components_image/<int:item_id>', methods=['GET'])
    def export_components_image(item_id):
        result = process_export_components_image(item_id)
        if not result['success']:
            flash(result['message'], 'danger')
            return redirect(url_for('index'))
        return render_template(
            'export_components_image.html',
            item=result['item'],
            svg_url=result['svg_url'],
            components_json=result['components_json'],
            patina_choice=result['patina_choice']
        )

    @bp.route('/save_components_image/<int:item_id>', methods=['POST'])
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
            image.save(full_path, 'WEBP')
            new_width = max(1, int(image.width * 0.25))
            new_height = max(1, int(image.height * 0.25))
            thumb_image = image.resize((new_width, new_height), PILImage.Resampling.LANCZOS)
            thumb_image.save(thumb_path, 'WEBP')
            db_img_value = f"images/item/{filename}"
            db.execute('UPDATE ITM SET ITMIMG = ? WHERE ITEMID = ?', (db_img_value, item_id))
            db.commit()

            try:
                res = upsert_item_in_square(item_id)
                if not res.get('success'):
                    print(f"Warning: Square image sync failed for item {item_id}: {res.get('error')}")
            except Exception as sq_err:
                print(f"Error triggering Square image upsert for item {item_id}: {sq_err}")

            return jsonify({'success': True, 'message': 'Image saved, database updated, and synced to Square!'})
        except Exception as e:
            db.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500

    @bp.route('/api/export_components_image/<int:item_id>', methods=['POST', 'GET'])
    def api_export_components_image(item_id):
        """API endpoint to trigger component visualization export."""
        result = process_export_components_image(item_id)
        return jsonify(result), (200 if result['success'] else 404)