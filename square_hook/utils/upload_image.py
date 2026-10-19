import os
import json
import io
import requests
from PIL import Image
from square_hook.utils.client import get_square_client

def upload_item_image(item_id, image_path):
    """
    Dynamically converts server-side WebP images into JPEG/PNG streams in-memory
    and uploads them to Square as an unattached catalog image with a temporary #image ID.
    Returns the Square Image ID if successful, else None.
    """
    client = get_square_client()
    if not client or not image_path:
        return None

    # Get the project root directory
    app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

    # Build potential paths to check on disk
    candidate_paths = [
        image_path,
        os.path.join(app_root, image_path),
        os.path.join(app_root, 'static', image_path),
    ]

    if image_path.startswith('images/'):
        candidate_paths.append(os.path.join(app_root, 'static', image_path))
    elif not image_path.startswith('static/'):
        candidate_paths.append(os.path.join(app_root, 'static', 'images', image_path))

    resolved_path = None
    for path in candidate_paths:
        if os.path.exists(path):
            resolved_path = path
            break

    if not resolved_path:
        print(f"Image path not found on disk for item {item_id}. Tried paths: {candidate_paths}")
        return None

    try:
        # Open the WebP image with Pillow and convert dynamically in-memory
        with Image.open(resolved_path) as img:
            image_io = io.BytesIO()
            
            # Check for transparency (RGBA) -> save as PNG, otherwise convert to RGB and save as JPEG
            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                img.save(image_io, format='PNG')
                content_type = "image/png"
                filename = f"item_{item_id}.png"
            else:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                img.save(image_io, format='JPEG', quality=95)
                content_type = "image/jpeg"
                filename = f"item_{item_id}.jpg"
            
            image_io.seek(0)

        # Extract credentials and environment from the client or environment variables
        access_token = getattr(client, 'access_token', None) or os.environ.get('SQUARE_ACCESS_TOKEN')
        environment = str(getattr(client, 'environment', 'production')).lower()
        
        base_url = "https://connect.squareupsandbox.com" if "sandbox" in environment else "https://connect.squareup.com"
        url = f"{base_url}/v2/catalog/images"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Square-Version": "2026-09-16"
        }

        # Included temporary "id": "#image_{item_id}" inside the image object while omitting top-level object_id
        request_body = {
            "idempotency_key": f"img_upload_{item_id}_{os.urandom(4).hex()}",
            "image": {
                "type": "IMAGE",
                "id": f"#image_{item_id}",
                "image_data": {
                    "name": f"Item {item_id}"
                }
            }
        }

        files = {
            'request': (None, json.dumps(request_body), 'application/json'),
            'file': (filename, image_io, content_type)
        }
        
        response = requests.post(url, headers=headers, files=files)
        
        if response.status_code == 200:
            resp_json = response.json()
            img_obj = resp_json.get('image', {})
            return img_obj.get('id')
        else:
            print(f"Square Image Upload HTTP error {response.status_code}: {response.text}")
                
    except Exception as ex:
        print(f"Image upload exception for item {item_id}: {str(ex)}")
    
    return None