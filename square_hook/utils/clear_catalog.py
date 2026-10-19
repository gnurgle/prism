import os
from square_hook.utils.client import get_square_client, get_db

def clear_square_catalog():
    """
    Clears out the entire Square catalog by using client.catalog.search(...)
    to find all objects, batch deleting them with direct keyword arguments, 
    and resetting local ITMSQ mappings.
    """
    client = get_square_client()
    if not client:
        return {"success": False, "error": "Square client not initialized."}

    try:
        # 1. Retrieve all catalog object IDs using client.catalog.search
        object_ids = []
        cursor = None
        
        while True:
            if cursor:
                response = client.catalog.search(cursor=cursor)
            else:
                response = client.catalog.search()
            
            # Parse response safely
            objects = []
            if hasattr(response, 'objects'):
                objects = response.objects
            elif isinstance(response, dict):
                objects = response.get('objects', [])

            for obj in objects:
                obj_id = getattr(obj, 'id', None) or (obj.get('id') if isinstance(obj, dict) else None)
                if obj_id:
                    object_ids.append(obj_id)

            # Check for pagination cursor
            cursor = getattr(response, 'cursor', None)
            if isinstance(response, dict):
                cursor = response.get('cursor', cursor)
                
            if not cursor:
                break

        total_deleted = 0
        if object_ids:
            # Square batch delete in chunks (max 200 per request) using direct keyword arguments
            chunk_size = 200
            for i in range(0, len(object_ids), chunk_size):
                chunk = object_ids[i:i + chunk_size]
                
                client.catalog.batch_delete(object_ids=chunk)
                total_deleted += len(chunk)

        # 2. Clear out local ITMSQ mapping table so no stale variation IDs remain
        conn = get_db()
        cursor_db = conn.cursor()
        cursor_db.execute("DELETE FROM ITMSQ")
        conn.commit()
        conn.close()

        return {
            "success": True, 
            "message": f"Successfully cleared Square catalog ({total_deleted} remote objects deleted) and reset local ITMSQ mappings.", 
            "deleted_count": total_deleted
        }

    except Exception as ex:
        return {"success": False, "error": f"Clear Catalog Exception: {str(ex)}"}