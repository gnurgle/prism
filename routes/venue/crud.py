import sqlite3
from flask import flash, redirect, render_template, request, url_for

def get_db():
    conn = sqlite3.connect("inventory.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def register_venue_routes(bp):
    @bp.route('/venues')
    def list_venues():
        db = get_db()
        sort_by = request.args.get('sort_by', 'VENNAME')
        order = request.args.get('order', 'asc').lower()
        if order not in ['asc', 'desc']:
            order = 'asc'
            
        q = request.args.get('q', '').strip()
        ven_grp = request.args.get('ven_grp', '').strip()
        app_start = request.args.get('app_start', '').strip()
        app_end = request.args.get('app_end', '').strip()
        state = request.args.get('state', '').strip()
        min_fee = request.args.get('min_fee', '').strip()
        max_fee = request.args.get('max_fee', '').strip()
        multi_wknd = request.args.get('multi_wknd', '').strip()
        occ_start = request.args.get('occ_start', '').strip()
        occ_end = request.args.get('occ_end', '').strip()
        is_active = request.args.get('is_active', '1').strip()
        year = request.args.get('year', '').strip()

        allowed_sorts = {
            'VENNAME': 'v.VENNAME', 'VENGRP': 'v.VENGRP', 'VCITY': 'v.VCITY',
            'VENSTATE': 'v.VENSTATE', 'VENSDATE': 'v.VENSDATE', 'VFEES': 'v.VFEES', 'VENDLINE': 'v.VENDLINE'
        }
        sort_column = allowed_sorts.get(sort_by, 'v.VENNAME')
        where_clauses, params = [], []

        if is_active != 'all':
            where_clauses.append("v.ISACTIVE = ?")
            params.append(1 if is_active == '1' else 0)
        if q:
            where_clauses.append("(v.VENNAME LIKE ? OR v.VENNOTE LIKE ? OR v.VCITY LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
        if ven_grp:
            where_clauses.append("v.VENGRP = ?")
            params.append(ven_grp)
        if app_start:
            where_clauses.append("v.VENDLINE >= ?")
            params.append(app_start)
        if app_end:
            where_clauses.append("v.VENDLINE <= ?")
            params.append(app_end)
        if state:
            where_clauses.append("v.VSTATE = ?")
            params.append(state)
        if min_fee:
            where_clauses.append("v.VFEES >= ?")
            params.append(min_fee)
        if max_fee:
            where_clauses.append("v.VFEES <= ?")
            params.append(max_fee)
        if multi_wknd:
            where_clauses.append("v.VMULTI = ?")
            params.append(multi_wknd)
        if occ_start and occ_end:
            where_clauses.append("v.VSDATE <= ? AND v.VEDATE >= ?")
            params.extend([occ_end, occ_start])
        elif occ_start:
            where_clauses.append("v.VEDATE >= ?")
            params.append(occ_start)
        elif occ_end:
            where_clauses.append("v.VSDATE <= ?")
            params.append(occ_end)
        if year:
            where_clauses.append("strftime('%Y', v.VSDATE) = ?")
            params.append(year)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query = f"SELECT v.* FROM VENUE v {where_sql} ORDER BY {sort_column} {order.upper()}"
        
        venues = db.execute(query, params).fetchall()
        active_venue = db.execute("SELECT VENUEID, VENNAME FROM VENUE WHERE ISCURRENT = 1 LIMIT 1").fetchone()
        venue_groups = db.execute("SELECT DISTINCT VENGRP FROM VENUE WHERE VENGRP IS NOT NULL AND VENGRP != '' ORDER BY VENGRP").fetchall()
        venue_states = [row[0] for row in db.execute("SELECT DISTINCT VSTATE FROM VENUE WHERE VSTATE IS NOT NULL AND VSTATE != '' ORDER BY VSTATE").fetchall() if row[0]]
        available_years = [row[0] for row in db.execute("SELECT DISTINCT strftime('%Y', VSDATE) FROM VENUE WHERE VSDATE IS NOT NULL ORDER BY VSDATE DESC").fetchall() if row[0]]

        return render_template(
            'venue_list.html', venues=venues, active_venue=active_venue, venue_groups=venue_groups,
            venue_states=venue_states, available_years=available_years, current_sort=sort_by,
            current_order=order, filters={
                'q': q, 'ven_grp': ven_grp, 'app_start': app_start, 'app_end': app_end, 'state': state,
                'min_fee': min_fee, 'max_fee': max_fee, 'multi_wknd': multi_wknd, 'occ_start': occ_start,
                'occ_end': occ_end, 'is_active': is_active, 'year': year
            }
        )

    @bp.route('/venue/new', methods=['GET', 'POST'])
    def create_venue():
        db = get_db()
        if request.method == 'POST':
            venname = request.form.get('VENNAME')
            vengrp = request.form.get('VENGRP') or None
            new_vengrp = request.form.get('NEW_VENGRP')
            if new_vengrp and new_vengrp.strip():
                vengrp = new_vengrp.strip()
                db.execute("INSERT OR IGNORE INTO VGP (VENGRP, ISACTIVE) VALUES (?, 1)", (vengrp,))
                
            vcity = request.form.get('VCITY')
            vfees = request.form.get('VFEES') or None
            vendline = request.form.get('VENDLINE') or None
            vsdate = request.form.get('VSDATE') or None
            vedate = request.form.get('VEDATE') or None
            vcampava = 1 if request.form.get('VCAMPAVA') else 0
            vmulti = 1 if request.form.get('VMULTI') else 0
            vennote = request.form.get('VENNOTE')

            db.execute('''
                INSERT INTO VENUE (VENNAME, VENGRP, VCITY, VFEES, VENDLINE, VSDATE, VEDATE, VCAMPAVA, VMULTI, VENNOTE, ISACTIVE)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (venname, vengrp, vcity, vfees, vendline, vsdate, vedate, vcampava, vmulti, vennote))
            db.commit()
            flash('Venue created successfully!', 'success')
            return redirect(url_for('venue_bp.list_venues'))

        all_groups = db.execute('SELECT DISTINCT VENGRP FROM VGP WHERE ISACTIVE = 1 ORDER BY VENGRP ASC').fetchall()
        return render_template('venue_form.html', action='Create', venue={}, groups=all_groups)

    @bp.route('/venues/<int:venue_id>/edit', methods=['GET', 'POST'])
    def edit_venue(venue_id):
        db = get_db()
        cursor = db.cursor()
        if request.method == 'POST':
            venname = request.form.get('VENNAME')
            isactive = 1 if request.form.get('ISACTIVE') else 0
            vurl, vinsta, vfb = request.form.get('VURL'), request.form.get('VINSTA'), request.form.get('VFB')
            vengrp = request.form.get('VENGRP') or None
            new_vengrp = request.form.get('NEW_VENGRP')
            if new_vengrp and new_vengrp.strip():
                vengrp = new_vengrp.strip()
                db.execute("INSERT OR IGNORE INTO VGP (VENGRP, ISACTIVE) VALUES (?, 1)", (vengrp,))
                
            vstreet1, vstreet2, vcity, vstate, vzip = request.form.get('VSTREET1'), request.form.get('VSTREET2'), request.form.get('VCITY'), request.form.get('VSTATE'), request.form.get('VZIP')
            venueloc = request.form.get('VENUELOC')
            vconname, vconphn, vconemail, vconnote = request.form.get('VCONNAME'), request.form.get('VCONPHN'), request.form.get('VCONEMAIL'), request.form.get('VCONNOTE')
            vendline, vsdate, vedate = request.form.get('VENDLINE'), request.form.get('VSDATE'), request.form.get('VEDATE')
            vfees, vfeenote = request.form.get('VFEES') or None, request.form.get('VFEENOTE')
            vmulti, vcampava, vcamped = (1 if request.form.get('VMULTI') else 0), (1 if request.form.get('VCAMPAVA') else 0), (1 if request.form.get('VCAMPED') else 0)
            vcampfee, vcampnt, vennote = request.form.get('VCAMPFEE') or None, request.form.get('VCAMPNT'), request.form.get('VENNOTE')
            
            # Extract day schedule toggles and times
            days_data = []
            for prefix in ['VM', 'VTE', 'VW', 'VR', 'VF', 'VST', 'VSN']:
                active = 1 if request.form.get(prefix) else 0
                st = request.form.get(f'{prefix}ST')
                et = request.form.get(f'{prefix}ET')
                days_data.extend([active, st, et])

            cursor.execute(f"""
                UPDATE VENUE SET
                    VENNAME = ?, VENGRP = ?, ISACTIVE = ?, VURL = ?, VINSTA = ?, VFB = ?,
                    VSTREET1 = ?, VSTREET2 = ?, VCITY = ?, VSTATE = ?, VZIP = ?, VENUELOC = ?,
                    VCONNAME = ?, VCONPHN = ?, VCONEMAIL = ?, VCONNOTE = ?,
                    VENDLINE = ?, VSDATE = ?, VEDATE = ?, VFEES = ?, VFEENOTE = ?, VMULTI = ?,
                    VCAMPAVA = ?, VCAMPED = ?, VCAMPFEE = ?, VCAMPNT = ?, VENNOTE = ?,
                    VM = ?, VMST = ?, VMET = ?, VTE = ?, VTST = ?, VTET = ?,
                    VW = ?, VWST = ?, VWET = ?, VR = ?, VRST = ?, VRET = ?,
                    VF = ?, VFST = ?, VFET = ?, VST = ?, VSTST = ?, VSTET = ?,
                    VSN = ?, VSNST = ?, VSNET = ?
                WHERE VENUEID = ?
            """, (venname, vengrp, isactive, vurl, vinsta, vfb, vstreet1, vstreet2, vcity, vstate, vzip, venueloc,
                  vconname, vconphn, vconemail, vconnote, vendline, vsdate, vedate, vfees, vfeenote, vmulti,
                  vcampava, vcamped, vcampfee, vcampnt, vennote, *days_data, venue_id))
            db.commit()
            return redirect(url_for('venue_bp.venue_detail', venue_id=venue_id))

        cursor.execute("SELECT * FROM VENUE WHERE VENUEID = ?", (venue_id,))
        venue = cursor.fetchone()
        groups = db.execute('SELECT DISTINCT VENGRP FROM VGP WHERE ISACTIVE = 1 ORDER BY VENGRP ASC').fetchall()
        return render_template('venue_form.html', action='Edit', venue=venue, groups=groups)

    @bp.route('/venue/<int:venue_id>')
    def venue_detail(venue_id):
        db = get_db()
        venue = db.execute('SELECT * FROM VENUE WHERE VENUEID = ?', (venue_id,)).fetchone()
        if not venue:
            flash('Venue record not found.', 'danger')
            return redirect(url_for('venue_bp.list_venues'))
        return render_template('venue_detail.html', venue=venue)

    @bp.route('/venue/<int:venue_id>/set-current', methods=['POST'])
    def set_current_venue(venue_id):
        db = get_db()
        venue = db.execute("SELECT VENNAME FROM VENUE WHERE VENUEID = ?", (venue_id,)).fetchone()
        if not venue:
            flash('Venue not found.', 'danger')
            return redirect(url_for('venue_bp.list_venues'))
        
        cursor = db.cursor()
        cursor.execute("UPDATE VENUE SET ISCURRENT = 0")
        cursor.execute("UPDATE VENUE SET ISCURRENT = 1 WHERE VENUEID = ?", (venue_id,))
        db.commit()
        
        flash(f"Current working venue set globally to: {venue['VENNAME']}", 'success')
        return redirect(url_for('venue_bp.list_venues'))

    @bp.route('/venue/clear-current', methods=['POST'])
    def clear_current_venue():
        db = get_db()
        db.execute("UPDATE VENUE SET ISCURRENT = 0")
        db.commit()
        flash("Cleared current working venue.", 'info')
        return redirect(url_for('venue_bp.list_venues'))