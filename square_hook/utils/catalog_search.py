from square_hook.utils.client import get_square_client

def get_catalog_item_by_name(group_name):
    """
    Searches Square catalog for an ITEM object whose name matches the group name.
    Returns a dict containing id, version, variations, and image_ids if found, else None.
    """
    client = get_square_client()
    if not client or not group_name:
        return None

    try:
        response = client.catalog.search(
            object_types=["ITEM"],
            query={
                "text_query": {
                    "keywords": [group_name]
                }
            }
        )
        
        objects = response.objects if hasattr(response, 'objects') else (response.get('objects', []) if isinstance(response, dict) else [])
        
        for obj in objects:
            item_data = obj.item_data if hasattr(obj, 'item_data') else obj.get('item_data', {})
            name = item_data.name if hasattr(item_data, 'name') else item_data.get('name')
            
            if name and name.strip().lower() == group_name.strip().lower():
                sq_id = obj.id if hasattr(obj, 'id') else obj.get('id')
                sq_version = obj.version if hasattr(obj, 'version') else obj.get('version')
                variations = item_data.variations if hasattr(item_data, 'variations') else item_data.get('variations', [])
                image_ids = item_data.image_ids if hasattr(item_data, 'image_ids') else item_data.get('image_ids', [])
                
                return {
                    "id": sq_id,
                    "version": sq_version,
                    "variations": variations,
                    "image_ids": image_ids
                }
                
    except Exception as e:
        print(f"Catalog search error for group '{group_name}': {str(e)}")
        
    return None