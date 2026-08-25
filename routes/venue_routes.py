import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, url_for



venue_bp = Blueprint('venue_bp', __name__)



DATABASE = "inventory.db"



def get_db():

    conn = sqlite3.connect(DATABASE)

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON;")

    return conn





@venue_bp.route('/venues')

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

        'VENNAME': 'v.VENNAME',

        'VENGRP': 'v.VENGRP',

        'VCITY': 'v.VCITY',

        'VENSTATE': 'v.VENSTATE',

        'VENSDATE': 'v.VENSDATE',

        'VFEES': 'v.VFEES',

        'VENDLINE': 'v.VENDLINE'

    }

    sort_column = allowed_sorts.get(sort_by, 'v.VENNAME')



    where_clauses = []

    params = []



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



    query = f"""

        SELECT v.* 

        FROM VENUE v

        {where_sql}

        ORDER BY {sort_column} {order.upper()}

    """

    venues = db.execute(query, params).fetchall()



    venue_groups = db.execute("SELECT DISTINCT VENGRP FROM VENUE WHERE VENGRP IS NOT NULL AND VENGRP != '' ORDER BY VENGRP").fetchall()

    

    venue_states = [row[0] for row in db.execute("SELECT DISTINCT VSTATE FROM VENUE WHERE VSTATE IS NOT NULL AND VSTATE != '' ORDER BY VSTATE").fetchall() if row[0]]

    

    available_years = [row[0] for row in db.execute("SELECT DISTINCT strftime('%Y', VSDATE) FROM VENUE WHERE VSDATE IS NOT NULL ORDER BY VSDATE DESC").fetchall() if row[0]]



    return render_template(

        'venue_list.html',

        venues=venues,

        venue_groups=venue_groups,

        venue_states=venue_states,

        available_years=available_years,

        current_sort=sort_by,

        current_order=order,

        filters={

            'q': q,

            'ven_grp': ven_grp,

            'app_start': app_start,

            'app_end': app_end,

            'state': state,

            'min_fee': min_fee,

            'max_fee': max_fee,

            'multi_wknd': multi_wknd,

            'occ_start': occ_start,

            'occ_end': occ_end,

            'is_active': is_active,

            'year': year

        }

    )





@venue_bp.route('/venue/new', methods=['GET', 'POST'])

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

        isactive = 1



        db.execute(

            """

            INSERT INTO VENUE (VENNAME, VENGRP, VCITY, VFEES, VENDLINE, VSDATE, VEDATE, VCAMPAVA, VMULTI, VENNOTE, ISACTIVE)

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            """,

            (venname, vengrp, vcity, vfees, vendline, vsdate, vedate, vcampava, vmulti, vennote, isactive)

        )

        db.commit()

        

        flash('Venue created successfully!', 'success')

        return redirect(url_for('venue_bp.list_venues'))



    all_groups = db.execute('SELECT DISTINCT VENGRP FROM VGP WHERE ISACTIVE = 1 ORDER BY VENGRP ASC').fetchall()

    return render_template('venue_form.html', action='Create', venue={}, groups=all_groups)





@venue_bp.route('/venues/<int:venue_id>/edit', methods=['GET', 'POST'])

def edit_venue(venue_id):

    db = get_db()

    cursor = db.cursor()



    if request.method == 'POST':

        venname = request.form.get('VENNAME')

        isactive = 1 if request.form.get('ISACTIVE') else 0

        vurl = request.form.get('VURL')

        vinsta = request.form.get('VINSTA')

        vfb = request.form.get('VFB')

        vengrp = request.form.get('VENGRP') or None

        new_vengrp = request.form.get('NEW_VENGRP')

        

        if new_vengrp and new_vengrp.strip():

            vengrp = new_vengrp.strip()

            db.execute("INSERT OR IGNORE INTO VGP (VENGRP, ISACTIVE) VALUES (?, 1)", (vengrp,))

        

        vstreet1 = request.form.get('VSTREET1')

        vstreet2 = request.form.get('VSTREET2')

        vcity = request.form.get('VCITY')

        vstate = request.form.get('VSTATE')

        vzip = request.form.get('VZIP')

        venueloc = request.form.get('VENUELOC')

        

        vconname = request.form.get('VCONNAME')

        vconphn = request.form.get('VCONPHN')

        vconemail = request.form.get('VCONEMAIL')

        vconnote = request.form.get('VCONNOTE')

        

        vendline = request.form.get('VENDLINE')

        vsdate = request.form.get('VSDATE')

        vedate = request.form.get('VEDATE')

        vfees = request.form.get('VFEES') or None

        vfeenote = request.form.get('VFEENOTE')

        vmulti = 1 if request.form.get('VMULTI') else 0

        

        vcampava = 1 if request.form.get('VCAMPAVA') else 0

        vcamped = 1 if request.form.get('VCAMPED') else 0

        vcampfee = request.form.get('VCAMPFEE') or None

        vcampnt = request.form.get('VCAMPNT')

        vennote = request.form.get('VENNOTE')

        

        vm = 1 if request.form.get('VM') else 0

        vmst = request.form.get('VMST')

        vmet = request.form.get('VMET')

        

        vte = 1 if request.form.get('VTE') else 0

        vtst = request.form.get('VTST')

        vtet = request.form.get('VTET')

        

        vw = 1 if request.form.get('VW') else 0

        vwst = request.form.get('VWST')

        vwet = request.form.get('VWET')

        

        vr = 1 if request.form.get('VR') else 0

        vrst = request.form.get('VRST')

        vret = request.form.get('VRET')

        

        vf = 1 if request.form.get('VF') else 0

        vfst = request.form.get('VFST')

        vfet = request.form.get('VFET')

        

        vst = 1 if request.form.get('VST') else 0

        vstst = request.form.get('VSTST')

        vstet = request.form.get('VSTET')

        

        vsn = 1 if request.form.get('VSN') else 0

        vsnst = request.form.get('VSNST')

        vsnet = request.form.get('VSNET')



        cursor.execute("""

            UPDATE VENUE SET

                VENNAME = ?, VENGRP = ?, ISACTIVE = ?, VURL = ?, VINSTA = ?, VFB = ?,

                VSTREET1 = ?, VSTREET2 = ?, VCITY = ?, VSTATE = ?, VZIP = ?, VENUELOC = ?,

                VCONNAME = ?, VCONPHN = ?, VCONEMAIL = ?, VCONNOTE = ?,

                VENDLINE = ?, VSDATE = ?, VEDATE = ?, VFEES = ?, VFEENOTE = ?, VMULTI = ?,

                VCAMPAVA = ?, VCAMPED = ?, VCAMPFEE = ?, VCAMPNT = ?, VENNOTE = ?,

                VM = ?, VMST = ?, VMET = ?,

                VTE = ?, VTST = ?, VTET = ?,

                VW = ?, VWST = ?, VWET = ?,

                VR = ?, VRST = ?, VRET = ?,

                VF = ?, VFST = ?, VFET = ?,

                VST = ?, VSTST = ?, VSTET = ?,

                VSN = ?, VSNST = ?, VSNET = ?

            WHERE VENUEID = ?

        """, (

            venname, vengrp, isactive, vurl, vinsta, vfb,

            vstreet1, vstreet2, vcity, vstate, vzip, venueloc,

            vconname, vconphn, vconemail, vconnote,

            vendline, vsdate, vedate, vfees, vfeenote, vmulti,

            vcampava, vcamped, vcampfee, vcampnt, vennote,

            vm, vmst, vmet,

            vte, vtst, vtet,

            vw, vwst, vwet,

            vr, vrst, vret,

            vf, vfst, vfet,

            vst, vstst, vstet,

            vsn, vsnst, vsnet,

            venue_id

        ))



        db.commit()

        return redirect(url_for('venue_bp.venue_detail', venue_id=venue_id))



    cursor.execute("SELECT * FROM VENUE WHERE VENUEID = ?", (venue_id,))

    venue = cursor.fetchone()

    

    groups = db.execute('SELECT DISTINCT VENGRP FROM VGP WHERE ISACTIVE = 1 ORDER BY VENGRP ASC').fetchall()



    return render_template('venue_form.html', action='Edit', venue=venue, groups=groups)





@venue_bp.route('/venue/<int:venue_id>')

def venue_detail(venue_id):

    db = get_db()

    venue = db.execute('SELECT * FROM VENUE WHERE VENUEID = ?', (venue_id,)).fetchone()

    if not venue:

        flash('Venue record not found.', 'danger')

        return redirect(url_for('venue_bp.list_venues'))



    return render_template('venue_detail.html', venue=venue)
