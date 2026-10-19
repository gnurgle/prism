from square_hook.utils.client import get_db

def get_item_price(item_id):
    """
    Fetches the current active price for a local item from the IPC table.
    Returns float price (default 0.0 if not found).
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
                SELECT ITMPRICE AS PRICE FROM IPC 
                WHERE ITEMID = ? AND (ENDDATE IS NULL OR ENDDATE >= DATE('now'))
                ORDER BY STDATE DESC LIMIT 1
            """,
            (item_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if row and row['PRICE'] is not None:
            return float(row['PRICE'])
            
    except Exception as ex:
        print(f"Price fetch error for item {item_id}: {str(ex)}")
    
    return 0.0