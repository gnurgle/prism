import os
import traceback
from square_hook.utils.client import get_square_client, get_db
from square_hook.utils.price_fetcher import get_item_price
from square_hook.utils.upload_image import upload_item_image
from square_hook.utils.catalog_search import get_catalog_item_by_name

def create_item_in_square(item_id):
    """
    Creates or adds a Prism item as a variation under its ITMGRP parent in Square,
    and maps ITMSQID to the specific variation's Square ID.
    """
    client = get_square_client()
    if not client:
        return {"success": False, "error": "Square client not initialized."}

    try:
        conn = get_db()
        cursor = conn.cursor()

        # 1. Fetch local item details
        cursor.execute("""
            SELECT ITEMID, ITMNAME, ITMNOTE, ITMIMG, ITMGRP
            FROM ITM
            WHERE ITEMID = ?
        """, (item_id,))
        item = cursor.fetchone()
        conn.close()

        if not item:
            return {"success": False, "error": f"Item ID {item_id} not found locally."}

        item_name = item['ITMNAME'] or "Unnamed Item"
        item_note = item['ITMNOTE'] or ""
        image_path = item['ITMIMG'] if 'ITMIMG' in item.keys() else None
        item_group = item['ITMGRP'] or "General"

        # 2. Get active price from IPC table & convert to cents
        raw_price = get_item_price(item_id)
        price_cents = int(round(raw_price * 100))

        # 3. Upload image if present
        image_id = None
        if image_path:
            image_id = upload_item_image(item_id, image_path)

        # 4. Search catalog for existing parent group item
        parent_group_info = get_catalog_item_by_name(item_group)

        parent_square_id = None
        parent_version = None
        existing_variations = []
        parent_image_ids = []

        if parent_group_info:
            parent_square_id = parent_group_info['id']
            parent_version = parent_group_info['version']
            existing_variations = parent_group_info['variations']
            parent_image_ids = parent_group_info['image_ids']

        # 5. Build new variation payload (SKU = Prism item ID)
        new_variation_data = {
            "type": "ITEM_VARIATION",
            "id": f"#variation_{item_id}",
            "item_variation_data": {
                "name": item_name,
                "sku": str(item_id),
                "pricing_type": "FIXED_PRICING",
                "price_money": {
                    "amount": price_cents,
                    "currency": "USD"
                }
            }
        }

        # Format and append existing variations + new variation
        cleaned_variations = []
        sku_found = False

        for var in existing_variations:
            var_dict = {}
            if hasattr(var, 'to_dict'):
                var_dict = var.to_dict()
            elif hasattr(var, 'model_dump'):
                var_dict = var.model_dump()
            elif isinstance(var, dict):
                var_dict = var
            else:
                var_id = getattr(var, 'id', None)
                var_type = getattr(var, 'type', 'ITEM_VARIATION')
                var_data_obj = getattr(var, 'item_variation_data', None)
                
                v_name = getattr(var_data_obj, 'name', None) if var_data_obj else None
                v_sku = getattr(var_data_obj, 'sku', None) if var_data_obj else None
                v_pricing = getattr(var_data_obj, 'pricing_type', 'FIXED_PRICING') if var_data_obj else 'FIXED_PRICING'
                v_price_money = getattr(var_data_obj, 'price_money', None) if var_data_obj else None
                
                amount = getattr(v_price_money, 'amount', 0) if v_price_money else 0
                currency = getattr(v_price_money, 'currency', 'USD') if v_price_money else 'USD'

                var_dict = {
                    "type": var_type,
                    "id": var_id,
                    "item_variation_data": {
                        "name": v_name,
                        "sku": v_sku,
                        "pricing_type": v_pricing,
                        "price_money": {
                            "amount": amount,
                            "currency": currency
                        }
                    }
                }

            v_data = var_dict.get('item_variation_data', {})
            if v_data.get('sku') == str(item_id):
                cleaned_variations.append(new_variation_data)
                sku_found = True
            else:
                cleaned_variations.append(var_dict)

        if not sku_found:
            cleaned_variations.append(new_variation_data)

        # 6. Construct Item Payload
        item_data_dict = {
            "name": item_group,
            "description": item_note,
            "variations": cleaned_variations
        }

        if image_id:
            if image_id not in parent_image_ids:
                parent_image_ids.append(image_id)
            item_data_dict["image_ids"] = parent_image_ids
        elif parent_image_ids:
            item_data_dict["image_ids"] = parent_image_ids

        item_payload = {
            "type": "ITEM",
            "id": parent_square_id if parent_square_id else f"#group_{item_id}",
            "item_data": item_data_dict
        }

        if parent_version is not None:
            item_payload["version"] = parent_version

        # 7. Execute batch_upsert
        response = client.catalog.batch_upsert(
            idempotency_key=f"create_item_{item_id}_{os.urandom(4).hex()}",
            batches=[
                {
                    "objects": [item_payload]
                }
            ]
        )

        # 8. Parse response to find the SPECIFIC VARIATION ID matching this item's SKU
        objects_list = response.objects if hasattr(response, 'objects') else (response.get('objects', []) if isinstance(response, dict) else [])
        catalog_obj = objects_list[0] if objects_list else None

        if not catalog_obj:
            return {"success": False, "error": f"Square response missing objects. Raw: {response}"}

        resp_item_data = getattr(catalog_obj, 'item_data', None) or (catalog_obj.get('item_data') if isinstance(catalog_obj, dict) else {})
        resp_variations = getattr(resp_item_data, 'variations', None) or (resp_item_data.get('variations', []) if isinstance(resp_item_data, dict) else [])

        target_variation_id = None
        target_variation_version = None

        for var in resp_variations:
            v_data = getattr(var, 'item_variation_data', None) or (var.get('item_variation_data') if isinstance(var, dict) else {})
            v_sku = getattr(v_data, 'sku', None) or (v_data.get('sku') if isinstance(v_data, dict) else None)
            v_id = getattr(var, 'id', None) or (var.get('id') if isinstance(var, dict) else None)
            v_ver = getattr(var, 'version', None) or (var.get('version') if isinstance(var, dict) else None)

            if v_sku and str(v_sku) == str(item_id):
                target_variation_id = v_id
                target_variation_version = v_ver
                break

        if not target_variation_id:
            return {"success": False, "error": f"Could not locate created variation ID for SKU {item_id} in Square response."}

        # 9. Save variation mapping back to ITMSQ table
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT ITMSQID FROM ITMSQ WHERE ITEMID = ?", (item_id,))
        existing_mapping = cursor.fetchone()

        if existing_mapping:
            cursor.execute("UPDATE ITMSQ SET ITMSQID = ?, ITMSQV = ? WHERE ITEMID = ?", (target_variation_id, target_variation_version, item_id))
        else:
            cursor.execute("INSERT INTO ITMSQ (ITMSQID, ITEMID, ITMSQV) VALUES (?, ?, ?)", (target_variation_id, item_id, target_variation_version))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "action": "created_or_updated_group",
            "square_id": target_variation_id
        }

    except Exception as e:
        full_tb = traceback.format_exc()
        return {"success": False, "error": f"Square API Exception: {str(e)} | Trace: {full_tb}"}