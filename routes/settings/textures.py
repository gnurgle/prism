from flask import render_template, request, redirect, url_for, flash, current_app
import sqlite3

def get_db():
    conn = sqlite3.connect(current_app.config.get('DATABASE', 'inventory.db'))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_texture_routes(bp):
    @bp.route('/settings/textures', methods=['GET', 'POST'])
    def settings_textures():
        """Manage GTL (Glass Textures) table entries."""
        db = get_db()
        if request.method == 'POST':
            glstex = request.form.get('GLSTEX', '').strip()
            isactive = 1 if request.form.get('ISACTIVE') == 'on' else 0
            action = request.form.get('action')
            
            if action == 'add':
                try:
                    db.execute("INSERT INTO GTL (GLSTEX, ISACTIVE) VALUES (?, ?)", (glstex, isactive))
                    db.commit()
                    flash('Glass texture added successfully!', 'success')
                except sqlite3.IntegrityError:
                    flash('Glass texture already exists.', 'danger')
            elif action == 'modify':
                original_tex = request.form.get('ORIG_GLSTEX')
                db.execute("UPDATE GTL SET GLSTEX = ?, ISACTIVE = ? WHERE GLSTEX = ?", (glstex, isactive, original_tex))
                db.commit()
                flash('Glass texture updated successfully!', 'success')
            return redirect(url_for('settings_bp.settings_textures'))
            
        textures = db.execute("SELECT * FROM GTL ORDER BY GLSTEX ASC").fetchall()
        return render_template('settings/textures.html', textures=textures)