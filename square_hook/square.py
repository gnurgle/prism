import os
from flask import Blueprint, render_template, flash, redirect, url_for, jsonify
from square_hook.utils.client import get_square_client, get_db
from square_hook.utils.fetch_item import fetch_item_details_from_square
from square_hook.utils.create_item import create_item_in_square
from square_hook.utils.update_item import update_item_in_square
from square_hook.utils.clear_catalog import clear_square_catalog
from square_hook.utils.sync_all import populate_active_square_catalog
from square_hook.utils.webhook_handler import handle_square_webhook

# (You can also import sync/upsert utilities here when built out)

square_bp = Blueprint(
    'square',
    __name__,
    template_folder='templates',
    url_prefix='/square'
)

@square_bp.route('/debug', methods=['GET'])
def square_debug():
    client = get_square_client()
    location_id = os.getenv('SQUARE_LOCATION_ID')
    environment = os.getenv('SQUARE_ENVIRONMENT', 'sandbox')

    connection_status = False
    location_info = None
    error_message = None

    if not client:
        error_message = "Square Client is missing. Check your .env file."
    else:
        try:
            location_response = client.locations.get(location_id=location_id)
            if location_response and location_response.location:
                connection_status = True
                location_info = location_response.location
        except Exception as e:
            error_message = f"Square API Exception: {str(e)}"

    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT i.ITEMID, i.ITMNAME, i.ISACTIVE, sq.ITMSQID, sq.ITMSQV
            FROM ITM i
            LEFT JOIN ITMSQ sq ON i.ITEMID = sq.ITEMID
        """)
        local_items = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        local_items = []
        if not error_message:
            error_message = f"Database Error: {str(e)}"

    return render_template(
        'square_debug.html',
        environment=environment,
        location_id=location_id,
        connection_status=connection_status,
        location_info=location_info,
        local_items=local_items,
        error_message=error_message
    )

@square_bp.route('/fetch-info/<int:item_id>', methods=['GET'])
def fetch_item_info_route(item_id):
    result = fetch_item_details_from_square(item_id)
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 400

        

from square_hook.utils.upsert_item import upsert_item_in_square

@square_bp.route('/sync/<int:item_id>', methods=['POST'])
def trigger_item_sync(item_id):
    """Route to sync (create or update) a local item to Square."""
    result = upsert_item_in_square(item_id)
    
    if result['success']:
        flash(f"Successfully synced item {item_id} to Square!", "success")
    else:
        flash(f"Failed to sync item {item_id}: {result['error']}", "danger")
        
    return redirect(url_for('square.square_debug'))

@square_bp.route('/admin/clear-catalog', methods=['POST'])
def admin_clear_catalog():
    result = clear_square_catalog()
    if result['success']:
        flash(f"Catalog cleared successfully. Deleted {result.get('deleted_count', 0)} objects.", "success")
    else:
        flash(f"Failed to clear catalog: {result['error']}", "danger")
    return redirect(url_for('square.square_debug'))

@square_bp.route('/admin/sync-all-active', methods=['POST'])
def admin_sync_all_active():
    result = populate_active_square_catalog()
    if result['success']:
        flash(f"Bulk sync complete! Synced: {result['synced_count']}, Failed: {result['failed_count']}", "success")
    else:
        flash(f"Bulk sync encountered an error: {result['error']}", "danger")
    return redirect(url_for('square.square_debug'))


@square_bp.route('/webhook', methods=['POST'])
def square_webhook():
    """
    Receives incoming webhook events from Square, verifies signatures,
    and logs completed orders/sales into PRISM.
    """
    return handle_square_webhook()
