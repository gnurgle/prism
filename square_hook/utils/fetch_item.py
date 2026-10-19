from square_hook.utils.client import get_square_client, get_db

def fetch_item_details_from_square(item_id):
    """
    Fetches a local item's Square ID, queries Square's catalog list or search,
    and returns parsed details (name, description, variations, images) for the modal.
    """
    client = get_square_client()
    if not client:
        return {"success": False, "error": "Square client not initialized."}

    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT ITMSQID FROM ITMSQ WHERE ITEMID = ?", (item_id,))
        mapping = cursor.fetchone()
        conn.close()

        if not mapping or not mapping['ITMSQID']:
            return {"success": False, "error": "Item is not mapped to Square yet."}

        sq_id = mapping['ITMSQID'].strip()

        # Fetch using search_catalog_objects for universal SDK compatibility
        response = client.catalog.search_catalog_objects(
            object_types=["ITEM"],
            include_related_objects=True,
            query={
                "exact_query": {
                    "attribute_name": "id",
                    "attribute_value": sq_id
                }
            }
        )

        objects_list = response.objects if hasattr(response, 'objects') else (response.get('objects', []) if isinstance(response, dict) else [])
        related_objects = response.related_objects if hasattr(response, 'related_objects') else (response.get('related_objects', []) if isinstance(response, dict) else [])

        object_data = objects_list[0] if objects_list else None
        if not object_data:
            return {"success": False, "error": "Catalog object not found in Square."}

        def get_field(obj, key):
            return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)

        item_data = get_field(object_data, 'item_data') or {}
        image_ids = get_field(item_data, 'image_ids') or []
        variations = get_field(item_data, 'variations') or []

        # Extract image URLs from related objects
        image_urls = []
        for rel in related_objects:
            rel_id = get_field(rel, 'id')
            rel_type = get_field(rel, 'type')
            if rel_type == 'IMAGE' and rel_id in image_ids:
                img_data = get_field(rel, 'image_data') or {}
                url = get_field(img_data, 'url')
                if url:
                    image_urls.append(url)

        # Parse variations
        parsed_variations = []
        for var in variations:
            var_data = get_field(var, 'item_variation_data') or {}
            price_money = get_field(var_data, 'price_money') or {}
            amount = get_field(price_money, 'amount') or 0
            parsed_variations.append({
                "name": get_field(var_data, 'name'),
                "price": amount / 100.0,
                "currency": get_field(price_money, 'currency') or 'USD'
            })

        return {
            "success": True,
            "square_id": sq_id,
            "name": get_field(item_data, 'name'),
            "description": get_field(item_data, 'description'),
            "item_group_id": get_field(item_data, 'item_group_id'),
            "variations": parsed_variations,
            "images": image_urls
        }

    except Exception as e:
        return {"success": False, "error": str(e)}