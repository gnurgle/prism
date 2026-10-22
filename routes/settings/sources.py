from flask import render_template, request, redirect, url_for, flash, current_app
import sqlite3

def get_db():
    conn = sqlite3.connect(current_app.config.get('DATABASE', 'inventory.db'))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_source_routes(bp):
    @bp.route('/settings/sources', methods=['GET', 'POST'])
    def settings_sources():
        """Manage GSL (Glass Sources) table entries."""
        db = get_db()
        if request.method == 'POST':
            glsource = request.form.get('GLSOURCE', '').strip()
            srcweb = 1 if request.form.get('SRCWEB') == 'on' else 0
            glsnote = request.form.get('GLSNOTE', '')
            isactive = 1 if request.form.get('ISACTIVE') == 'on' else 0
            action = request.form.get('action')
            
            if action == 'add':
                try:
                    db.execute("INSERT INTO GSL (GLSOURCE, SRCWEB, GLSNOTE, ISACTIVE) VALUES (?, ?, ?, ?)", 
                               (glsource, srcweb, glsnote, isactive))
                    db.commit()
                    flash('Glass source added successfully!', 'success')
                except sqlite3.IntegrityError:
                    flash('Glass source already exists.', 'danger')
            elif action == 'modify':
                original_source = request.form.get('ORIG_GLSOURCE')
                db.execute("UPDATE GSL SET GLSOURCE = ?, SRCWEB = ?, GLSNOTE = ?, ISACTIVE = ? WHERE GLSOURCE = ?", 
                           (glsource, srcweb, glsnote, isactive, original_source))
                db.commit()
                flash('Glass source updated successfully!', 'success')
            return redirect(url_for('settings_bp.settings_sources'))
            
        sources = db.execute("SELECT * FROM GSL ORDER BY GLSOURCE ASC").fetchall()
        return render_template('settings/sources.html', sources=sources)