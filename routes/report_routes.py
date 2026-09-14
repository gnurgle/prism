from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for

from datetime import datetime

import io

import os



from reportlab.lib.pagesizes import letter

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from reportlab.lib import colors



report_bp = Blueprint('report_bp', __name__)



# Configurable domain variable for generated PDF item links

BASE_URL = "http://192.168.1.18:7665"



def get_db():

    from __main__ import get_db

    return get_db()



@report_bp.route('/reports', methods=['GET'])

def expense_revenue_report():

    start_date = request.args.get('start_date', '')

    end_date = request.args.get('end_date', '')

    return render_template('report_page.html', start_date=start_date, end_date=end_date)



@report_bp.route('/reports/generate-pdf', methods=['POST'])

def generate_pdf_report():

    db = get_db()

    start_date = request.form.get('start_date')

    end_date = request.form.get('end_date')

    

    if not start_date or not end_date:

        flash('Please select both start date and end date.', 'warning')

        return redirect(url_for('report_bp.expense_revenue_report', start_date=start_date, end_date=end_date))

        

    # 2) Item Sales: ITMSALE based on date range, joined with IPC price based on date

    sales_rows = db.execute(

        """

        SELECT s.SALEID, s.ITEMID, i.ITMNAME, s.SUNITS, s.SDATE

        FROM ITMSALE s

        JOIN ITM i ON s.ITEMID = i.ITEMID

        WHERE s.SDATE BETWEEN ? AND ?

        ORDER BY s.SDATE ASC

        """,

        (start_date, end_date)

    ).fetchall()

    

    item_sales_data = []

    total_sales_revenue = 0.0

    

    for row in sales_rows:

        item_id = row['ITEMID']

        sdate = row['SDATE']

        sunits = row['SUNITS'] or 0

        

        price_row = db.execute(

            """

            SELECT ITMPRICE FROM IPC 

            WHERE ITEMID = ? AND STDATE <= ? AND (ENDDATE IS NULL OR ENDDATE >= ?)

            ORDER BY STDATE DESC LIMIT 1

            """,

            (item_id, sdate, sdate)

        ).fetchone()

        

        if not price_row:

            price_row = db.execute(

                """

                SELECT ITMPRICE FROM IPC 

                WHERE ITEMID = ? 

                ORDER BY STDATE ASC LIMIT 1

                """,

                (item_id,)

            ).fetchone()

            

        unit_price = float(price_row['ITMPRICE']) if price_row and price_row['ITMPRICE'] is not None else 0.0

        line_total = sunits * unit_price

        total_sales_revenue += line_total

        

        item_sales_data.append({

            'date': sdate,

            'item_id': item_id,

            'item': row['ITMNAME'],

            'units': sunits,

            'price': unit_price,

            'total': line_total

        })



    # Helper function to compute item unit cost exactly like item_detail / item_visuals

    def calculate_item_unit_cost(item_id):

        comps = db.execute(

            """

            SELECT c.COMPLEN, c.COMPWID, g.GLSLEN, g.GLSWID, 

                   (SELECT gp.GLSPRICE FROM GPC gp WHERE gp.GLASSID = g.GLASSID AND (gp.ENDDATE IS NULL OR gp.ENDDATE >= DATE('now')) ORDER BY gp.STDATE DESC LIMIT 1) AS LATEST_GLSPRICE

            FROM IGC c

            JOIN GSI g ON c.GLASSID = g.GLASSID

            WHERE c.ITEMID = ?

            """,

            (item_id,)

        ).fetchall()

        mat_cost = 0.0

        for comp in comps:

            sqin = (comp['COMPLEN'] or 0) * (comp['COMPWID'] or 0)

            sheet_area = (comp['GLSLEN'] or 1) * (comp['GLSWID'] or 1)

            sheet_price = comp['LATEST_GLSPRICE'] or 0.0

            if sheet_area > 0:

                mat_cost += sqin * (sheet_price / sheet_area)

                

        supplies = db.execute(

            """

            SELECT msi.MSIID, msi.MSITYPE, imi.IMIAMT, msi.MSIUNIT, u.CFACTOR

            FROM IMI imi

            JOIN MSI msi ON imi.MSIID = msi.MSIID

            LEFT JOIN UNTS u ON msi.UNTTYPE = u.UNTTYPE

            WHERE imi.ITEMID = ?

            """,

            (item_id,)

        ).fetchall()

        sup_cost = 0.0

        for s in supplies:

            p_row = db.execute("SELECT MSIPRICE FROM MSP WHERE MSIID = ? ORDER BY STDATE DESC LIMIT 1", (s['MSIID'],)).fetchone()

            if p_row and p_row['MSIPRICE']:

                u_price = float(p_row['MSIPRICE'])

                cfactor = float(s['CFACTOR']) if s['CFACTOR'] and float(s['CFACTOR']) > 0 else 1.0

                msiunit = float(s['MSIUNIT']) if s['MSIUNIT'] and float(s['MSIUNIT']) > 0 else 1.0

                divisor = cfactor * msiunit

                amt = float(s['IMIAMT'] or 0)

                if divisor > 0:

                    sup_cost += amt * (u_price / divisor)

        return mat_cost + sup_cost



    # 3) Item Expenses: cross referencing ITMINV based on date range

    inv_rows = db.execute(

        """

        SELECT ii.ITMTRNID, ii.ITEMID, ii.ITMSTOCK, ii.TS, i.ITMNAME

        FROM ITMINV ii

        JOIN ITM i ON ii.ITEMID = i.ITEMID

        WHERE DATE(ii.TS) BETWEEN ? AND ?

        ORDER BY ii.TS ASC

        """,

        (start_date, end_date)

    ).fetchall()

    

    item_expenses_data = []

    total_item_expenses = 0.0

    

    for inv in inv_rows:

        item_id = inv['ITEMID']

        stock = inv['ITMSTOCK'] or 0

        prev_inv = db.execute(

            """

            SELECT ITMSTOCK FROM ITMINV 

            WHERE ITEMID = ? AND (TS < ? OR (TS = ? AND ITMTRNID < ?))

            ORDER BY TS DESC, ITMTRNID DESC LIMIT 1

            """,

            (item_id, inv['TS'], inv['TS'], inv['ITMTRNID'])

        ).fetchone()

        prev_stock = prev_inv['ITMSTOCK'] if prev_inv and prev_inv['ITMSTOCK'] is not None else 0

        added_qty = stock - prev_stock

        if added_qty > 0:

            unit_cost = calculate_item_unit_cost(item_id)

            line_cost = added_qty * unit_cost

            total_item_expenses += line_cost

            item_expenses_data.append({

                'date': inv['TS'][:10],

                'item_id': item_id,

                'item': inv['ITMNAME'],

                'quantity': added_qty,

                'unit_cost': unit_cost,

                'total': line_cost

            })



    # 4) Glass Expenses: GLSINV based on date range, joined with GPC price based on dates

    glass_inv_rows = db.execute(

        """

        SELECT gi.GLSTRNID, gi.GLASSID, gi.GLSSTOCK, gi.TS, g.GLSNAME

        FROM GLSINV gi

        JOIN GSI g ON gi.GLASSID = g.GLASSID

        WHERE DATE(gi.TS) BETWEEN ? AND ?

        ORDER BY gi.TS ASC

        """,

        (start_date, end_date)

    ).fetchall()

    

    glass_expenses_data = []

    total_glass_expenses = 0.0

    

    for giv in glass_inv_rows:

        glass_id = giv['GLASSID']

        ts = giv['TS']

        stock = giv['GLSSTOCK'] or 0

        prev_giv = db.execute(

            """

            SELECT GLSSTOCK FROM GLSINV 

            WHERE GLASSID = ? AND (TS < ? OR (TS = ? AND GLSTRNID < ?))

            ORDER BY TS DESC, GLSTRNID DESC LIMIT 1

            """,

            (glass_id, ts, ts, giv['GLSTRNID'])

        ).fetchone()

        prev_stock = prev_giv['GLSSTOCK'] if prev_giv and prev_giv['GLSSTOCK'] is not None else 0

        added_qty = stock - prev_stock

        

        if added_qty > 0:

            gpc_row = db.execute(

                """

                SELECT GLSPRICE FROM GPC 

                WHERE GLASSID = ? AND STDATE <= ? AND (ENDDATE IS NULL OR ENDDATE >= ?)

                ORDER BY STDATE DESC LIMIT 1

                """,

                (glass_id, ts[:10], ts[:10])

            ).fetchone()

            if not gpc_row:

                gpc_row = db.execute("SELECT GLSPRICE FROM GPC WHERE GLASSID = ? ORDER BY STDATE ASC LIMIT 1", (glass_id,)).fetchone()

            

            g_price = float(gpc_row['GLSPRICE']) if gpc_row and gpc_row['GLSPRICE'] is not None else 0.0

            line_cost = added_qty * g_price

            total_glass_expenses += line_cost

            glass_expenses_data.append({

                'date': ts[:10],

                'glass_id': glass_id,

                'glass': giv['GLSNAME'],

                'quantity': added_qty,

                'price': g_price,

                'total': line_cost

            })



    # 5) Misc Expenses: MSIINV based on date range, joined with MSP price based on dates

    misc_inv_rows = db.execute(

        """

        SELECT mi.MSITRNID, mi.MSIID, mi.MSISTOCK, mi.TS, m.MSINAME

        FROM MSIINV mi

        JOIN MSI m ON mi.MSIID = m.MSIID

        WHERE DATE(mi.TS) BETWEEN ? AND ?

        ORDER BY mi.TS ASC

        """,

        (start_date, end_date)

    ).fetchall()

    

    misc_expenses_data = []

    total_misc_expenses = 0.0

    

    for miv in misc_inv_rows:

        msi_id = miv['MSIID']

        ts = miv['TS']

        stock = miv['MSISTOCK'] or 0

        prev_miv = db.execute(

            """

            SELECT MSISTOCK FROM MSIINV 

            WHERE MSIID = ? AND (TS < ? OR (TS = ? AND MSITRNID < ?))

            ORDER BY TS DESC, MSITRNID DESC LIMIT 1

            """,

            (msi_id, ts, ts, miv['MSITRNID'])

        ).fetchone()

        prev_stock = prev_miv['MSISTOCK'] if prev_miv and prev_miv['MSISTOCK'] is not None else 0

        added_qty = stock - prev_stock

        

        if added_qty > 0:

            msp_row = db.execute(

                """

                SELECT MSIPRICE FROM MSP 

                WHERE MSIID = ? AND STDATE <= ? AND (ENDDATE IS NULL OR ENDDATE >= ?)

                ORDER BY STDATE DESC LIMIT 1

                """,

                (msi_id, ts[:10], ts[:10])

            ).fetchone()

            if not msp_row:

                msp_row = db.execute("SELECT MSIPRICE FROM MSP WHERE MSIID = ? ORDER BY STDATE ASC LIMIT 1", (msi_id,)).fetchone()

                

            m_price = float(msp_row['MSIPRICE']) if msp_row and msp_row['MSIPRICE'] is not None else 0.0

            line_cost = added_qty * m_price

            total_misc_expenses += line_cost

            misc_expenses_data.append({

                'date': ts[:10],

                'msi_id': msi_id,

                'misc_item': miv['MSINAME'],

                'quantity': added_qty,

                'price': m_price,

                'total': line_cost

            })



    # 6) Revenue Summary

    total_expenses = total_item_expenses + total_glass_expenses + total_misc_expenses

    net_revenue = total_sales_revenue - total_expenses



    # Generate PDF Report

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)

    story = []

    styles = getSampleStyleSheet()

    

    # Styles

    cover_title_style = ParagraphStyle('CoverTitle', parent=styles['Heading1'], fontSize=26, leading=32, textColor=colors.HexColor('#1a365d'), alignment=1, spaceAfter=15)

    cover_subtitle_style = ParagraphStyle('CoverSubTitle', parent=styles['Normal'], fontSize=12, leading=16, textColor=colors.HexColor('#4a5568'), alignment=1, spaceAfter=20)

    

    section_title_style = ParagraphStyle('SectionHeading', parent=styles['Heading1'], fontSize=22, leading=26, textColor=colors.HexColor('#1a365d'), spaceBefore=5, spaceAfter=12)

    normal_style = styles['Normal']

    

    table_header_style = ParagraphStyle('TableHeader', parent=styles['Normal'], fontSize=9, leading=11, textColor=colors.HexColor('#1a365d'), fontName='Helvetica-Bold')

    table_cell_style = ParagraphStyle('TableCell', parent=styles['Normal'], fontSize=9, leading=11, textColor=colors.HexColor('#2d3748'))

    table_link_style = ParagraphStyle('TableLink', parent=styles['Normal'], fontSize=9, leading=11, textColor=colors.HexColor('#2b6cb0'))

    table_total_style = ParagraphStyle('TableTotal', parent=styles['Normal'], fontSize=9, leading=11, textColor=colors.HexColor('#1a365d'), fontName='Helvetica-Bold')

    toc_item_style = ParagraphStyle('TOCItem', parent=styles['Normal'], fontSize=11, leading=16, textColor=colors.HexColor('#2b6cb0'))

    

    # --- 1. COVER PAGE ---

    story.append(Spacer(1, 140))

    story.append(Paragraph("<b>Expense & Revenue Report</b>", cover_title_style))

    story.append(Paragraph(f"<b>Reporting Period:</b> {start_date} to {end_date}", cover_subtitle_style))

    story.append(Paragraph(f"<b>Generated On:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", cover_subtitle_style))

    story.append(PageBreak())

    

    # --- 2. TABLE OF CONTENTS ---

    story.append(Paragraph("<b>Table of Contents</b>", cover_title_style))

    story.append(Spacer(1, 20))

    

    toc_links = [

        ("1. Item Sales", "#sec1", "Page 3"),

        ("2. Item Expenses", "#sec2", "Page 4"),

        ("3. Glass Expenses", "#sec3", "Page 5"),

        ("4. Misc Item Expenses", "#sec4", "Page 6"),

        ("5. Revenue Summary", "#sec5", "Page 7")

    ]

    

    for title, link, page in toc_links:

        toc_line = f"<a href='{link}'>{title} . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . {page}</a>"

        story.append(Paragraph(toc_line, toc_item_style))

        story.append(Spacer(1, 6))

        

    story.append(PageBreak())

    

    def add_section(anchor_name, title, total_label, total_val, total_qty, headers, data_rows):

        story.append(Paragraph(f"<a name='{anchor_name}'></a>{title}", section_title_style))

        

        # Summary Box Table at the top of each section (pure white background for cells)

        summary_box_data = [

            [Paragraph("<b>Total Amount (Quantity)</b>", table_header_style), Paragraph(f"<b>{total_qty}</b>", table_cell_style)],

            [Paragraph(f"<b>{total_label}</b>", table_header_style), Paragraph(f"<b>${total_val:.2f}</b>", table_cell_style)]

        ]

        sum_box = Table(summary_box_data, colWidths=[200, 200])

        sum_box.setStyle(TableStyle([

            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),

            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#ffffff')),

            ('TOPPADDING', (0,0), (-1,-1), 6),

            ('BOTTOMPADDING', (0,0), (-1,-1), 6),

        ]))

        story.append(sum_box)

        story.append(Spacer(1, 15))

        

        if not data_rows:

            story.append(Paragraph("<i>No records found for this date range.</i>", normal_style))

            story.append(PageBreak())

            return

            

        formatted_headers = [Paragraph(f"<b>{h}</b>", table_header_style) for h in headers]

        table_data = [formatted_headers]

        

        for r in data_rows:

            row_cells = [Paragraph(str(cell), table_cell_style) for cell in r]

            table_data.append(row_cells)

            

        total_row_cells = [Paragraph("<b>Total</b>", table_total_style)] + [Paragraph("", table_cell_style) for _ in range(len(headers) - 2)] + [Paragraph(f"<b>${total_val:.2f}</b>", table_total_style)]

        table_data.append(total_row_cells)

        

        col_widths = [70, 55, 175, 50, 80, 110][:len(headers)]

        t_style = [

            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#edf2f7')),

            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),

            ('TOPPADDING', (0,0), (-1,0), 6),

            ('BOTTOMPADDING', (0,0), (-1,0), 6),

            ('LINEABOVE', (0, -1), (-1, -1), 1.5, colors.HexColor('#718096')),

            ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#e2e8f0')),

        ]

        

        # Alternate white and light gray backgrounds for data rows

        for i in range(1, len(data_rows) + 1):

            bg = colors.HexColor('#ffffff') if i % 2 != 0 else colors.HexColor('#f7fafc')

            t_style.append(('BACKGROUND', (0, i), (-1, i), bg))



        t = Table(table_data, colWidths=col_widths)

        t.setStyle(TableStyle(t_style))

        story.append(t)

        story.append(PageBreak())



    # 1. Item Sales

    total_sales_qty = sum(r['units'] for r in item_sales_data)

    sales_rows_formatted = [

        [

            r['date'], 

            str(r['item_id']), 

            f"<a href='{BASE_URL}/item/{r['item_id']}'>{r['item']}</a>", 

            str(r['units']), 

            f"${r['price']:.2f}", 

            f"${r['total']:.2f}"

        ] for r in item_sales_data

    ]

    add_section("sec1", "1) Item Sales", "Total Sales Revenue", total_sales_revenue, total_sales_qty,

                ["Date", "Item ID", "Item Name", "Units", "Unit Price", "Total Revenue"], sales_rows_formatted)

    

    # 2. Item Expenses

    total_item_exp_qty = sum(r['quantity'] for r in item_expenses_data)

    item_exp_rows_formatted = [

        [

            r['date'], 

            str(r['item_id']), 

            f"<a href='{BASE_URL}/item/{r['item_id']}'>{r['item']}</a>", 

            str(r['quantity']), 

            f"${r['unit_cost']:.2f}", 

            f"${r['total']:.2f}"

        ] for r in item_expenses_data

    ]

    add_section("sec2", "2) Item Expenses", "Total Item Expenses", total_item_expenses, total_item_exp_qty,

                ["Date", "Item ID", "Item Name", "Qty Added", "Est. Unit Cost", "Total Cost"], item_exp_rows_formatted)

    

    # 3. Glass Expenses

    total_glass_qty = sum(r['quantity'] for r in glass_expenses_data)

    glass_exp_rows_formatted = [

        [

            r['date'], 

            str(r['glass_id']), 

            f"<a href='{BASE_URL}/glass/{r['glass_id']}'>{r['glass']}</a>", 

            str(r['quantity']), 

            f"${r['price']:.2f}", 

            f"${r['total']:.2f}"

        ] for r in glass_expenses_data

    ]

    add_section("sec3", "3) Glass Expenses", "Total Glass Expenses", total_glass_expenses, total_glass_qty,

                ["Date", "Glass ID", "Glass Name", "Qty Added", "Unit Price", "Total Cost"], glass_exp_rows_formatted)

    

    # 4. Misc Item Expenses

    total_misc_qty = sum(r['quantity'] for r in misc_expenses_data)

    misc_exp_rows_formatted = [

        [

            r['date'], 

            str(r['msi_id']), 

            f"<a href='{BASE_URL}/misc_item/{r['msi_id']}'>{r['misc_item']}</a>", 

            str(r['quantity']), 

            f"${r['price']:.2f}", 

            f"${r['total']:.2f}"

        ] for r in misc_expenses_data

    ]

    add_section("sec4", "4) Misc Item Expenses", "Total Misc Expenses", total_misc_expenses, total_misc_qty,

                ["Date", "Misc ID", "Misc Item Name", "Qty Added", "Unit Price", "Total Cost"], misc_exp_rows_formatted)

    

    # --- 5. REVENUE SUMMARY (Final Page) ---

    story.append(Paragraph("<a name='sec5'></a>5) Revenue Summary", section_title_style))

    story.append(Spacer(1, 10))

    

    net_color_hex = '#22543d' if net_revenue >= 0 else '#742a2a'

    net_bg_hex = '#c6f6d5' if net_revenue >= 0 else '#fed7d7'

    net_label = "Net Profit (Positive)" if net_revenue >= 0 else "Net Loss (Negative)"

    

    net_style = ParagraphStyle('NetStyle', parent=styles['Normal'], fontSize=10, leading=12, textColor=colors.HexColor(net_color_hex), fontName='Helvetica-Bold')



    summary_rows = [

        [Paragraph("<b>Total Item Sales Revenue</b>", table_cell_style), Paragraph(f"<b>${total_sales_revenue:.2f}</b>", table_cell_style)],

        [Paragraph("<b>Total Item Production Expenses</b>", table_cell_style), Paragraph(f"<b>-${total_item_expenses:.2f}</b>", table_cell_style)],

        [Paragraph("<b>Total Glass Expenses</b>", table_cell_style), Paragraph(f"<b>-${total_glass_expenses:.2f}</b>", table_cell_style)],

        [Paragraph("<b>Total Misc Item Expenses</b>", table_cell_style), Paragraph(f"<b>-${total_misc_expenses:.2f}</b>", table_cell_style)],

        [Paragraph("<b>Total All Expenses</b>", table_total_style), Paragraph(f"<b>-${total_expenses:.2f}</b>", table_total_style)],

        [Paragraph(f"<b>{net_label}</b>", net_style), Paragraph(f"<b>${net_revenue:.2f}</b>", net_style)]

    ]

    

    sum_table = Table(summary_rows, colWidths=[260, 160])

    sum_table.setStyle(TableStyle([

        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),

        ('TOPPADDING', (0,0), (-1,-1), 6),

        ('BOTTOMPADDING', (0,0), (-1,-1), 6),

        ('BACKGROUND', (0,0), (-1,-4), colors.HexColor('#ffffff')),

        ('LINEABOVE', (0, -2), (-1, -2), 1.5, colors.HexColor('#718096')),

        ('BACKGROUND', (0,-2), (-1,-2), colors.HexColor('#edf2f7')),

        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor(net_bg_hex)),

    ]))

    story.append(sum_table)

    

    doc.build(story)

    buffer.seek(0)

    

    pdf_filename = f"report_{start_date}_to_{end_date}.pdf"

    pdf_path = os.path.join('static', 'reports', pdf_filename)

    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    with open(pdf_path, 'wb') as f:

        f.write(buffer.getvalue())

        

    return render_template('report_page.html', start_date=start_date, end_date=end_date, pdf_file=pdf_filename)



@report_bp.route('/reports/download/<filename>')

def download_pdf(filename):

    pdf_path = os.path.join('static', 'reports', filename)

    return send_file(pdf_path, as_attachment=True)
