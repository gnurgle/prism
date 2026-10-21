import os
import hmac
import hashlib
import base64
import traceback
from datetime import datetime
from flask import request, jsonify
from square_hook.utils.client import get_square_client, get_db

def handle_square_webhook():
    signature_header = request.headers.get('X-Square-Signature', '')
    notification_url = request.url
    raw_body = request.get_data()

    # 1. Verify Webhook Signature for security
    signature_key = os.environ.get('SQUARE_WEBHOOK_SIGNATURE_KEY', '')
    if signature_key:
        payload_to_sign = notification_url.encode('utf-8') + raw_body
        expected_signature = base64.b64encode(
            hmac.new(signature_key.encode('utf-8'), payload_to_sign, hashlib.sha1).digest()
        ).decode('utf-8')
        
        if not hmac.compare_digest(expected_signature, signature_header):
            return jsonify({"status": "unauthorized signature"}), 403

    event_data = request.json or {}
    event_type = event_data.get('type')

    print(f"--- WEBHOOK RECEIVED --- Type: {event_type}")

    # Listen to order updates/creations (ignoring fulfillment noise)
    if event_type in ['order.created', 'order.updated']:
        data_obj = event_data.get('data', {}).get('object', {})
        order_obj = data_obj.get('order_updated') or data_obj.get('order_created') or data_obj.get('order', {})
        
        state = order_obj.get('state')
        order_id = order_obj.get('order_id') or order_obj.get('id')

        print(f"Order ID: {order_id} | State: {state}")

        if state == 'COMPLETED' and order_id:
            process_completed_square_order(order_id)

    return jsonify({"status": "success"}), 200

def process_completed_square_order(order_id):
    client = get_square_client()
    if not client:
        print("Error: Square client could not be initialized.")
        return

    db = None
    try:
        db = get_db()

        # 1. Idempotency Check using your SQSALES table
        existing = db.execute("SELECT 1 FROM SQSALES WHERE SQORDERID = ? LIMIT 1", (order_id,)).fetchone()
        if existing:
            print(f"-> Duplicate order ID '{order_id}' already processed. Skipping.")
            return

        print(f"Fetching order details from Square for Order ID: {order_id}")
        response = client.orders.get(order_id=order_id)
        order = response.order if hasattr(response, 'order') else response.get('order', {})
        
        line_items = order.get('line_items', []) if isinstance(order, dict) else getattr(order, 'line_items', [])
        created_at_str = order.get('created_at') if isinstance(order, dict) else getattr(order, 'created_at', None)
        
        sale_date = datetime.today().strftime('%Y-%m-%d')
        if created_at_str:
            try:
                sale_date = created_at_str.split('T')[0]
            except Exception:
                pass

        cursor = db.cursor()

        for idx, item in enumerate(line_items):
            catalog_object_id = item.get('catalog_object_id') if isinstance(item, dict) else getattr(item, 'catalog_object_id', None)
            quantity_str = item.get('quantity', '1') if isinstance(item, dict) else getattr(item, 'quantity', '1')
            amt_sold = int(float(quantity_str))

            if not catalog_object_id or amt_sold <= 0:
                continue

            # Map Square Variation ID back to Prism ITEMID via ITMSQ
            mapping = db.execute("SELECT ITEMID FROM ITMSQ WHERE ITMSQID = ?", (catalog_object_id,)).fetchone()

            if not mapping:
                print(f"-> WARNING: Square Variation ID '{catalog_object_id}' has no match in ITMSQ.")
                continue

            item_id = mapping['ITEMID']

            active_venue_row = db.execute("SELECT VENUEID FROM VENUE WHERE ISCURRENT = 1 LIMIT 1").fetchone()
            active_venue_id = active_venue_row['VENUEID'] if active_venue_row else None

            # 2. Record the sale in ITMSALE
            cursor.execute(
                """
                INSERT INTO ITMSALE (ITEMID, SUNITS, SDATE, VENUEID)
                VALUES (?, ?, ?, ?)
                """,
                (item_id, amt_sold, sale_date, active_venue_id)
            )
            
            # Capture the auto-generated PRISM sale ID
            prism_sale_id = cursor.lastrowid

            # 3. Link Square Order ID to this specific Prism Sale ID using SALEID in SQSALES
            timestamp_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                """
                INSERT INTO SQSALES (SQORDERID, SALEID, TS)
                VALUES (?, ?, ?)
                """,
                (order_id, prism_sale_id, timestamp_str)
            )

            # 4. Timeline Inventory Propagation (Mirrors bulk-sales-adjustment)
            inv_rows = db.execute(
                "SELECT ITMTRNID, ITMSTOCK, TS FROM ITMINV WHERE ITEMID = ? ORDER BY TS ASC, ITMTRNID ASC",
                (item_id,)
            ).fetchall()

            exact_match = None
            latest_before = None
            future_rows = []

            for row in inv_rows:
                if row['TS'] == sale_date:
                    exact_match = row
                elif row['TS'] < sale_date:
                    latest_before = row
                elif row['TS'] > sale_date:
                    future_rows.append(row)

            if exact_match:
                new_stock = max(0, exact_match['ITMSTOCK'] - amt_sold)
                db.execute(
                    "UPDATE ITMINV SET ITMSTOCK = ? WHERE ITMTRNID = ?",
                    (new_stock, exact_match['ITMTRNID'])
                )
            else:
                baseline_stock = latest_before['ITMSTOCK'] if latest_before else 0
                new_stock = max(0, baseline_stock - amt_sold)
                db.execute(
                    "INSERT INTO ITMINV (ITEMID, ITMSTOCK, TS) VALUES (?, ?, ?)",
                    (item_id, new_stock, sale_date)
                )

            for f_row in future_rows:
                f_new_stock = max(0, f_row['ITMSTOCK'] - amt_sold)
                db.execute(
                    "UPDATE ITMINV SET ITMSTOCK = ? WHERE ITMTRNID = ?",
                    (f_new_stock, f_row['ITMTRNID'])
                )
            print(f"-> Successfully processed sale & inventory update for ITEMID {item_id} (Sale ID: {prism_sale_id})")

        db.commit()
        print("--- ORDER PROCESSING COMPLETE ---")

    except Exception as ex:
        if db:
            db.rollback()
        print(f"CRITICAL ERROR processing Square order {order_id}: {str(ex)}")
        print(traceback.format_exc())
