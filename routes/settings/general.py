import os
import xml.etree.ElementTree as ET
from flask import render_template, request, redirect, url_for, flash, current_app
import sqlite3

def get_db():
    conn = sqlite3.connect(current_app.config.get('DATABASE', 'inventory.db'))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_general_routes(bp):
    @bp.route('/settings', methods=['GET', 'POST'])
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