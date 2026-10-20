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

    print(f"--- WEBHOOK RECEIVED --- URL: {notification_url}")

    # 1. Verify Webhook Signature
    signature_key = os.environ.get('SQUARE_WEBHOOK_SIGNATURE_KEY', '')
    if signature_key:
        payload_to_sign = notification_url.encode('utf-8') + raw_body
        expected_signature = base64.b64encode(
            hmac.new(signature_key.encode('utf-8'), payload_to_sign, hashlib.sha1).digest()
        ).decode('utf-8')
        
        if not hmac.compare_digest(expected_signature, signature_header):
            print("Webhook Signature Mismatch! Rejecting request.")
            return jsonify({"status": "unauthorized signature"}), 403

    event_data = request.json or {}
    event_type = event_data.get('type')
    print(f"Webhook Event Type: {event_type}")

    if event_type in ['order.created', 'order.updated']:
        data_obj = event_data.get('data', {}).get('object', {})
        order_obj = data_obj.get('order_updated') or data_obj.get('order_created') or data_obj.get('order', {})
        
        state = order_obj.get('state')
        order_id = order_obj.get('order_id') or order_obj.get('id')
        
        print(f"Order ID: {order_id} | State: {state}")

        if state == 'COMPLETED' and order_id:
            process_completed_square_order(order_id)
        else:
            print(f"Skipping order processing. State was '{state}' (expected 'COMPLETED').")

    return jsonify({"status": "success"}), 200

def process_completed_square_order(order_id):
    client = get_square_client()
    if not client:
        print("Error: Square client could not be initialized in webhook processor.")
        return

    try:
        print(f"Fetching order details from Square for Order ID: {order_id}")
        response = client.orders.retrieve_order(order_id=order_id)
        order = response.order if hasattr(response, 'order') else response.get('order', {})
        
        # Handle order object as dict or object
        line_items = order.get('line_items', []) if isinstance(order, dict) else getattr(order, 'line_items', [])
        created_at_str = order.get('created_at') if isinstance(order, dict) else getattr(order, 'created_at', None)
        
        print(f"Found {len(line_items)} line items in order.")

        sale_date = datetime.today().strftime('%Y-%m-%d')
        if created_at_str:
            try:
                sale_date = created_at_str.split('T')[0]
            except Exception:
                pass

        db = get_db()

        for idx, item in enumerate(line_items):
            catalog_object_id = item.get('catalog_object_id') if isinstance(item, dict) else getattr(item, 'catalog_object_id', None)
            quantity_str = item.get('quantity', '1') if isinstance(item, dict) else getattr(item, 'quantity', '1')
            amt_sold = int(float(quantity_str))

            print(f"Line Item {idx}: Catalog Object ID (Variation ID) = {catalog_object_id}, Qty = {amt_sold}")

            if not catalog_object_id or amt_sold <= 0:
                print("-> Skipping item: missing catalog_object_id or qty <= 0")
                continue

            # Look up mapping in ITMSQ
            mapping = db.execute("SELECT ITEMID FROM ITMSQ WHERE ITMSQID = ?", (catalog_object_id,)).fetchone()

            if not mapping:
                print(f"-> WARNING: Square Variation ID '{catalog_object_id}' has NO match in local ITMSQ table! Item was skipped.")
                continue

            item_id = mapping['ITEMID']
            print(f"-> Matched Square ID to Prism ITEMID: {item_id}")

            # Record sale in ITMSALE
            db.execute(
                """
                INSERT INTO ITMSALE (ITEMID, SUNITS, SDATE, VENUEID)
                VALUES (?, ?, ?, NULL)
                """,
                (item_id, amt_sold, sale_date)
            )

            # Timeline propagation logic
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
            print(f"-> Successfully processed sale & inventory update for ITEMID {item_id}")

        db.commit()
        print("--- ORDER PROCESSING COMPLETE ---")

    except Exception as ex:
        db.rollback()
        print(f"CRITICAL ERROR processing Square order {order_id}: {str(ex)}")
        print(traceback.format_exc())