import os
from io import BytesIO
from flask import flash, render_template, request, render_template_string, jsonify
import sqlite3
from utils import (
    trace_stencil_to_single_path_svg,
    compute_total_path_length,
    trace_stencil_to_outline_svg,
    trace_stencil_to_filled_outline_svg
)

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def process_trace_outline(selected_item_id):
    """
    Core reusable logic to process and save trace measurements for a given item_id.
    Can be called internally by other Python methods or APIs without frontend requirements.
    """
    db = get_db()
    try:
        item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (selected_item_id,)).fetchone()
        if not item:
            return {'success': False, 'message': 'Selected item not found.', 'status_code': 404}
        if not item['ITMPTRN']:
            return {'success': False, 'message': 'Selected item does not have a pattern template uploaded.', 'status_code': 400}
        
        try:
            width_in = float(item['ITMLEN']) if item['ITMLEN'] else 10.0
            height_in = float(item['ITMWID']) if item['ITMWID'] else 10.0
        except (ValueError, TypeError):
            width_in, height_in = 10.0, 10.0
            
        img_path = os.path.join('static', item['ITMPTRN'])
        if not os.path.exists(img_path):
            return {'success': False, 'message': f'Template image file not found at static/{item["ITMPTRN"]}', 'status_code': 404}
            
        with open(img_path, 'rb') as f:
            file_bytes = f.read()
            
        svg_content = trace_stencil_to_single_path_svg(BytesIO(file_bytes))
        outline_content = trace_stencil_to_outline_svg(BytesIO(file_bytes))
        foil_content = trace_stencil_to_filled_outline_svg(BytesIO(file_bytes))
        
        total_len = compute_total_path_length(svg_content, width_in, height_in)
        outline_len = compute_total_path_length(outline_content, width_in, height_in)
        foil_len = compute_total_path_length(foil_content, width_in, height_in) - outline_len
        
        supply_updates = [
            {'itm_column': 'IMISLDR', 'msi_type': 'Solder', 'amount': total_len},
            {'itm_column': 'IMIFOIL', 'msi_type': 'Foil', 'amount': foil_len},
            {'itm_column': 'IMICAME', 'msi_type': 'Came', 'amount': outline_len}
        ]
        created_imi_ids, updated_imi_ids = [], []
        
        for supply in supply_updates:
            itm_column, msi_type, amount = supply['itm_column'], supply['msi_type'], float(supply['amount'] or 0)
            current_imi_id = item[itm_column]
            imi_row = None
            
            if current_imi_id:
                imi_row = db.execute("""
                    SELECT i.IMIID, i.ITEMID, i.MSIID, i.IMIAMT, m.MSITYPE
                    FROM IMI i JOIN MSI m ON m.MSIID = i.MSIID
                    WHERE i.IMIID = ? AND i.ITEMID = ?
                """, (current_imi_id, selected_item_id)).fetchone()
                if not imi_row or imi_row['MSITYPE'] != msi_type: imi_row = None
                
            if not imi_row:
                imi_row = db.execute("""
                    SELECT i.IMIID, i.ITEMID, i.MSIID, i.IMIAMT, m.MSITYPE
                    FROM IMI i JOIN MSI m ON m.MSIID = i.MSIID
                    WHERE i.ITEMID = ? AND m.MSITYPE = ? ORDER BY i.IMIID LIMIT 1
                """, (selected_item_id, msi_type)).fetchone()
                
            if not imi_row:
                msi_row = db.execute("SELECT MSIID FROM MSI WHERE MSITYPE = ? AND ISACTIVE = 1 ORDER BY MSIID LIMIT 1", (msi_type,)).fetchone()
                if not msi_row: continue
                cursor = db.execute("INSERT INTO IMI (ITEMID, MSIID, IMIAMT) VALUES (?, ?, ?)", (selected_item_id, msi_row['MSIID'], amount))
                new_imi_id = cursor.lastrowid
                db.execute(f"UPDATE ITM SET {itm_column} = ? WHERE ITEMID = ?", (new_imi_id, selected_item_id))
                created_imi_ids.append(new_imi_id)
            else:
                db.execute("UPDATE IMI SET IMIAMT = ? WHERE IMIID = ? AND ITEMID = ?", (amount, imi_row['IMIID'], selected_item_id))
                updated_imi_ids.append(imi_row['IMIID'])
                
        db.commit()
        return {
            'success': True, 'message': 'Trace measurements successfully calculated and saved!',
            'created_imi_ids': created_imi_ids, 'updated_imi_ids': updated_imi_ids,
            'svg_content': svg_content, 'outline_content': outline_content, 'foil_content': foil_content,
            'total_len': total_len, 'outline_len': outline_len, 'foil_len': foil_len
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': f'Unable to save trace measurements: {e}', 'status_code': 500}

def register_trace_routes(bp):
    @bp.route('/test_outline', methods=['GET', 'POST'])
    def test_outline():
        svg_content, outline_content, filled_content, foil_content = None, None, None, None
        total_len, outline_len, foil_len, width_in, height_in = 0.0, 0.0, 0.0, 10.0, 10.0
        if request.method == 'POST' and 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                try: width_in, height_in = float(request.form.get('width_in', 10.0)), float(request.form.get('height_in', 10.0))
                except ValueError: width_in, height_in = 10.0, 10.0
                svg_content = trace_stencil_to_single_path_svg(file)
                file.stream.seek(0)
                outline_content = trace_stencil_to_outline_svg(file)
                file.stream.seek(0)
                foil_content = trace_stencil_to_filled_outline_svg(file)
                total_len = compute_total_path_length(svg_content, width_in, height_in)
                outline_len = compute_total_path_length(outline_content, width_in, height_in)
                foil_len = compute_total_path_length(foil_content, width_in, height_in) - outline_len
                
        return render_template_string(
            globals().get('HTML_PAGE', ''), svg_content=svg_content, outline_content=outline_content,
            filled_content=filled_content, foil_content=foil_content, total_len=total_len,
            outline_len=outline_len, foil_len=foil_len, width_in=width_in, height_in=height_in
        )

    @bp.route('/trace_outline', methods=['GET', 'POST'])
    @bp.route('/trace_outline/<int:item_id>', methods=['GET', 'POST'])
    def trace_outline(item_id=None):
        db = get_db()
        svg_content, outline_content, filled_content, foil_content = None, None, None, None
        total_len, outline_len, foil_len, width_in, height_in = 0.0, 0.0, 0.0, 10.0, 10.0
        selected_item_id = item_id
        
        if request.method == 'POST':
            selected_item_id = item_id or request.form.get('item_id')
            if selected_item_id:
                result = process_trace_outline(selected_item_id)
                if result['success']:
                    svg_content, outline_content, foil_content = result.get('svg_content'), result.get('outline_content'), result.get('foil_content')
                    total_len, outline_len, foil_len = result.get('total_len', 0.0), result.get('outline_len', 0.0), result.get('foil_len', 0.0)
                    if result.get('created_imi_ids'): flash(f"Created IMI record(s): {', '.join(map(str, result['created_imi_ids']))}", 'success')
                    if result.get('updated_imi_ids'): flash(f"Updated IMI record(s): {', '.join(map(str, result['updated_imi_ids']))}", 'success')
                else:
                    flash(result['message'], 'danger')
                    
        items = db.execute("SELECT ITEMID, ITMNAME, ITMLEN, ITMWID, ITMPTRN FROM ITM WHERE ISACTIVE = 1 AND ITMPTRN IS NOT NULL AND ITMPTRN != '' ORDER BY ITMNAME ASC").fetchall()
        return render_template(
            'trace_outline.html', items=items, selected_item_id=int(selected_item_id) if selected_item_id else None,
            svg_content=svg_content, outline_content=outline_content, filled_content=filled_content, foil_content=foil_content,
            total_len=total_len, outline_len=outline_len, foil_len=foil_len, width_in=width_in, height_in=height_in
        )

    @bp.route('/api/trace_outline/<int:item_id>', methods=['POST'])
    def api_trace_outline(item_id):
        """API endpoint to trigger outline tracing for a specific item programmatically."""
        result = process_trace_outline(item_id)
        status_code = result.pop('status_code', 200 if result['success'] else 400)
        return jsonify(result), status_code