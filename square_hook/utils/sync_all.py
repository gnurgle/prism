import traceback
from square_hook.utils.client import get_db
from square_hook.utils.upsert_item import upsert_item_in_square

def populate_active_square_catalog():
    """
    Automatically populates the Square catalog covering every active item in PRISM (ITM.CURRENT = 1).
    Applies the One-Off rule ('Special' parent group) automatically via upsert engine.
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Query all active items
        cursor.execute("""
            SELECT ITEMID, ITMNAME, ITMGRP, ONEOFF
            FROM ITM
            WHERE CURRENT = 1
        """)
        active_items = cursor.fetchall()
        conn.close()

        if not active_items:
            return {"success": True, "message": "No active items found with CURRENT = 1.", "synced_count": 0}

        success_count = 0
        failure_count = 0
        errors = []

        for row in active_items:
            item_id = row['ITEMID']
            result = upsert_item_in_square(item_id)
            
            if result.get('success'):
                success_count += 1
            else:
                failure_count += 1
                errors.append(f"Item {item_id}: {result.get('error')}")

        return {
            "success": True,
            "synced_count": success_count,
            "failed_count": failure_count,
            "errors": errors
        }

    except Exception as e:
        full_tb = traceback.format_exc()
        return {"success": False, "error": f"Bulk Populate Exception: {str(e)} | Trace: {full_tb}"}