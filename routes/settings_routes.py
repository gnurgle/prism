import os

import xml.etree.ElementTree as ET

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, make_response

import sqlite3



settings_bp = Blueprint('settings_bp', __name__, template_folder='templates')



def get_db():

    conn = sqlite3.connect(current_app.config.get('DATABASE', 'inventory.db'))

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON;")

    return conn



@settings_bp.route('/settings', methods=['GET', 'POST'])

def settings_main():

    """Manage application settings and save them to a local settings.config XML file."""

    db = get_db()

    config_path = os.path.join(current_app.root_path, 'settings.config')



    if request.method == 'POST':

        root = ET.Element('Settings')

        new_item_elem = ET.SubElement(root, 'NewItemDefaults')

        

        fields = ['Solder', 'Foil', 'Came', 'Chain', 'Rings']

        for field in fields:

            val = request.form.get(f'default_{field.lower()}')

            ET.SubElement(new_item_elem, field).text = val if val else ''



        tree = ET.ElementTree(root)

        tree.write(config_path, encoding='utf-8', xml_declaration=True)

        

        flash('Settings saved successfully!', 'success')

        return redirect(url_for('settings_bp.settings_main'))



    defaults = {'Solder': '', 'Foil': '', 'Came': '', 'Chain': '', 'Rings': ''}

    if os.path.exists(config_path):

        try:

            tree = ET.parse(config_path)

            root = tree.getroot()

            defaults_elem = root.find('NewItemDefaults')

            if defaults_elem is not None:

                for k in defaults.keys():

                    child = defaults_elem.find(k)

                    if child is not None and child.text:

                        defaults[k] = child.text

        except ET.ParseError:

            pass



    all_msi = db.execute('SELECT MSIID, MSINAME, MSITYPE FROM MSI WHERE ISACTIVE = 1 ORDER BY MSINAME ASC').fetchall()

    msi_solder = [m for m in all_msi if m['MSITYPE'] == 'Solder']

    msi_foil = [m for m in all_msi if m['MSITYPE'] == 'Foil']

    msi_came = [m for m in all_msi if m['MSITYPE'] == 'Came']

    msi_chain = [m for m in all_msi if m['MSITYPE'] == 'Chain']

    msi_rings = [m for m in all_msi if m['MSITYPE'] == 'Rings']



    return render_template(

        'settings/general.html',

        defaults=defaults,

        msi_solder=msi_solder,

        msi_foil=msi_foil,

        msi_came=msi_came,

        msi_chain=msi_chain,

        msi_rings=msi_rings

    )



@settings_bp.route('/settings/textures', methods=['GET', 'POST'])

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



@settings_bp.route('/settings/sources', methods=['GET', 'POST'])

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


@settings_bp.route('/settings/appearance', methods=['GET', 'POST'])

def settings_appearance():

    """Manage application UI themes (Appearance)."""

    if request.method == 'POST':

        selected_theme = request.form.get('theme', 'default')

        # Flash message and set cookie storing the theme choice for 1 year

        flash('Appearance theme updated successfully!', 'success')

        response = make_response(redirect(url_for('settings_bp.settings_appearance')))

        response.set_cookie('app_theme', selected_theme, max_age=60*60*24*365)

        return response



    current_theme = request.cookies.get('app_theme', 'default')

    return render_template('settings/appearance.html', current_theme=current_theme)
