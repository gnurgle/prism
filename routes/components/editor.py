import sqlite3
from flask import flash, redirect, render_template, request, url_for, jsonify

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_editor_routes(bp):
    @bp.route('/update_components_batch', methods=['POST'])
    def update_components_batch():
        db = get_db()
        data = request.get_json()
        item_id = data.get('item_id')
        components = data.get('components', [])
        raw_patina = data.get('patina_choice')
        patina_choice = raw_patina if raw_patina in ['Silver', 'Copper', 'Black'] else 'Silver'
        try:
            db.execute('''
                UPDATE ITM 
                SET PATINA = ? 
                WHERE ITEMID = ?
            ''', (patina_choice, int(item_id)))
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
            return jsonify({'success': True, 'message': 'All components and patina updated successfully!'})
        except Exception as e:
            db.rollback()
            return jsonify({'success': False, 'message': str(e)}), 400

    @bp.route('/edit_components/<int:item_id>', methods=['GET'])
    def edit_components(item_id):
        db = get_db()
        item = db.execute('SELECT * FROM ITM WHERE ITEMID = ?', (item_id,)).fetchone()
        if not item:
            flash('Item not found.', 'danger')
            return redirect(url_for('index'))
        svg_filename = item['ITMSVG'] if 'ITMSVG' in item.keys() else None
        svg_url = url_for('static', filename=svg_filename) if svg_filename else ''
        raw_patina = item['PATINA'] if 'PATINA' in item.keys() else None
        patina_choice = raw_patina if raw_patina in ['Silver', 'Copper', 'Black'] else 'Silver'
        colors = db.execute('SELECT COLOR, CHEX FROM COLOR WHERE ISACTIVE = 1').fetchall()
        glass_options = db.execute('''
            SELECT g.GLASSID, g.GLSNAME, g.GLSTEX, g.GLSIMG, g.COLOR, g.GLSOURCE, 
                   c.CHEX, t.GTRNSV, COALESCE(p.GLSPRICE, 0.00) as GLSPRICE 
            FROM GSI g
            LEFT JOIN COLOR c ON g.COLOR = c.COLOR
            LEFT JOIN GTRNS t ON g.GTRNSN = t.GTRNSN
            LEFT JOIN GPC p ON g.GLASSID = p.GLASSID
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
            colors=colors,
            glass_options=glass_options, 
            components_json=comp_map,
            patina_choice=patina_choice
        )