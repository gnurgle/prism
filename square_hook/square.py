import os

import sqlite3

import traceback

from dotenv import load_dotenv

from flask import Blueprint, render_template, flash, redirect, url_for, jsonify

from square import Square

from square.environment import SquareEnvironment



# Load environment variables from .env in the same directory

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))



# Initialize Flask Blueprint

square_bp = Blueprint(

    'square',

    __name__,

    template_folder='templates',

    url_prefix='/square'

)



def get_db():

    """Connect directly to the SQLite database with foreign keys enabled."""

    db_path = os.path.join(os.path.dirname(__file__), '..', 'inventory.db')

    conn = sqlite3.connect(db_path)

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON;")

    return conn



def get_square_client():

    env_input = os.getenv('SQUARE_ENVIRONMENT', 'sandbox').lower()

    access_token = os.getenv('SQUARE_ACCESS_TOKEN')

    

    if not access_token:

        return None



    environment = SquareEnvironment.PRODUCTION if env_input == 'production' else SquareEnvironment.SANDBOX



    return Square(

        token=access_token,

        environment=environment

    )



@square_bp.route('/debug', methods=['GET'])

def square_debug():

    client = get_square_client()

    location_id = os.getenv('SQUARE_LOCATION_ID')

    environment = os.getenv('SQUARE_ENVIRONMENT', 'sandbox')



    connection_status = False

    location_info = None

    catalog_items = []

    local_items = []

    error_message = None



    if not client:

        error_message = "Square Client is missing. Check your .env file."

    else:

        try:

            # 1. Test connection via location details

            location_response = client.locations.get(location_id=location_id)

            if location_response and location_response.location:

                connection_status = True

                location_info = location_response.location



            # 2. Fetch Square catalog items using the modern list method

            catalog_response = None

            if hasattr(client.catalog, 'list'):

                catalog_response = client.catalog.list(types='ITEM')

            

            if catalog_response:

                catalog_items = list(catalog_response)



        except Exception as e:

            error_message = f"Square API Exception: {str(e)}"



    # 3. Fetch local items and their Square mapping status from SQLite using get_db()

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

        if not error_message:

            error_message = f"Database Error: {str(e)}"



    return render_template(

        'square_debug.html',

        environment=environment,

        location_id=location_id,

        connection_status=connection_status,

        location_info=location_info,

        catalog_items=catalog_items,

        local_items=local_items,

        error_message=error_message

    )



@square_bp.route('/sync/<int:item_id>', methods=['POST'])

def trigger_item_sync(item_id):

    """Route to sync a local item to Square using the ITMSQ mapping check."""

    result = sync_item_to_square(item_id)

    

    if result['success']:

        flash(f"Successfully synced item {item_id} ({result['action']}) to Square!", "success")

    else:

        flash(f"Failed to sync item {item_id}: {result['error']}", "danger")

        

    return redirect(url_for('square.square_debug'))



def upload_item_image_to_square(client, item_id, item_name, image_path_or_url):

    """

    Dedicated helper method to upload/attach an image using Square's create_catalog_image endpoint.

    """

    try:

        if image_path_or_url and os.path.exists(image_path_or_url):

            with open(image_path_or_url, 'rb') as image_file:

                request_request = {

                    "idempotency_key": f"image_upload_{item_id}_{os.urandom(4).hex()}",

                    "object_id": f"#item_{item_id}"

                }

                

                image_response = client.catalog.create_catalog_image(

                    request=request_request,

                    image_file=image_file

                )

                

                img_obj = None

                if hasattr(image_response, 'image'):

                    img_obj = image_response.image

                elif isinstance(image_response, dict):

                    img_obj = image_response.get('image')

                elif hasattr(image_response, 'body') and isinstance(image_response.body, dict):

                    img_obj = image_response.body.get('image')

                

                if img_obj:

                    return getattr(img_obj, 'id', None) or (img_obj.get('id') if isinstance(img_obj, dict) else None)

    except Exception as ex:

        print(f"Image upload warning for item {item_id}: {str(ex)}")

    

    return None



def sync_item_to_square(item_id):

    """

    Checks ITMSQ mapping for blank/null values using get_db(). 

    Creates or updates the item in Square via batch_upsert using schema-defined columns:

    ITMNAME, ITMIMG, ITMGRP, ITMNOTE, with proper price calculation and image method integration.

    """

    client = get_square_client()

    if not client:

        return {"success": False, "error": "Square client not initialized."}



    try:

        conn = get_db()

        cursor = conn.cursor()



        # Fetch item details, latest price, and Square mapping using correct schema column names

        cursor.execute("""

            SELECT i.ITEMID, i.ITMNAME, i.ITMNOTE, i.ITMIMG, i.ITMGRP, sq.ITMSQID, sq.ITMSQV

            FROM ITM i

            LEFT JOIN ITMSQ sq ON i.ITEMID = sq.ITEMID

            WHERE i.ITEMID = ?

        """, (item_id,))

        item = cursor.fetchone()



        if not item:

            conn.close()

            return {"success": False, "error": f"Item ID {item_id} not found locally."}



        sq_id = item['ITMSQID']

        sq_version = item['ITMSQV']

        has_valid_mapping = bool(sq_id and sq_id.strip())



        # Get latest price from IPC

        cursor.execute("""

            SELECT ITMPRICE FROM IPC 

            WHERE ITEMID = ? AND (ENDDATE IS NULL OR ENDDATE >= DATE('now'))

            ORDER BY STDATE DESC LIMIT 1

        """, (item_id,))

        price_row = cursor.fetchone()

        conn.close()



        item_name = item['ITMNAME'] or "Unnamed Item"

        item_note = item['ITMNOTE'] or ""

        image_path = item['ITMIMG'] if 'ITMIMG' in item.keys() else None

        item_group = item['ITMGRP'] if 'ITMGRP' in item.keys() else None



        # Correct price conversion: handle raw decimal/float correctly

        raw_price = float(price_row['ITMPRICE']) if price_row and price_row['ITMPRICE'] is not None else 0.0

        price_cents = int(round(raw_price * 100))



    except Exception as e:

        return {"success": False, "error": f"Database read error: {str(e)}"}



    try:

        # Construct Square item variation payload

        variation_data = {

            "type": "ITEM_VARIATION",

            "id": f"#variation_{item_id}",

            "item_variation_data": {

                "name": "Standard",

                "pricing_type": "FIXED_PRICING",

                "price_money": {

                    "amount": price_cents,

                    "currency": "USD"

                }

            }

        }



        item_data_dict = {

            "name": item_name,

            "description": item_note,

            "variations": [variation_data]

        }



        # Map Item Group (ITMGRP) to Square's item_group_id

        if item_group:

            item_data_dict["item_group_id"] = item_group



        # If a valid local image path exists, call the image upload method

        if image_path:

            uploaded_image_id = upload_item_image_to_square(client, item_id, item_name, image_path)

            if uploaded_image_id:

                item_data_dict["image_ids"] = [uploaded_image_id]



        item_payload = {

            "type": "ITEM",

            "item_data": item_data_dict

        }



        # Handle Update vs Create based on mapping check

        action_type = "updated"

        if has_valid_mapping:

            item_payload["id"] = sq_id.strip()

            if sq_version is not None:

                item_payload["version"] = sq_version

        else:

            action_type = "created"

            item_payload["id"] = f"#item_{item_id}"



        # Modern SDK batch_upsert call

        response = client.catalog.batch_upsert(

            idempotency_key=f"sync_item_{item_id}_{os.urandom(4).hex()}",

            batches=[

                {

                    "objects": [item_payload]

                }

            ]

        )



        # Parse batch response objects to find the primary ITEM object

        objects_list = None

        if hasattr(response, 'objects'):

            objects_list = response.objects

        elif isinstance(response, dict):

            objects_list = response.get('objects')

        elif hasattr(response, 'body') and isinstance(response.body, dict):

            objects_list = response.body.get('objects')



        catalog_obj = objects_list[0] if objects_list and len(objects_list) > 0 else None



        if not catalog_obj:

            return {"success": False, "error": f"Square response missing objects list. Raw response: {response}"}



        new_sq_id = getattr(catalog_obj, 'id', None) or (catalog_obj.get('id') if isinstance(catalog_obj, dict) else None)

        new_sq_version = getattr(catalog_obj, 'version', None) or (catalog_obj.get('version') if isinstance(catalog_obj, dict) else None)



        # Save/Update the mapping back to ITMSQ table using get_db()

        conn = get_db()

        cursor = conn.cursor()

        

        cursor.execute("SELECT ITMSQID FROM ITMSQ WHERE ITEMID = ?", (item_id,))

        existing_mapping = cursor.fetchone()



        if existing_mapping:

            cursor.execute("""

                UPDATE ITMSQ 

                SET ITMSQID = ?, ITMSQV = ? 

                WHERE ITEMID = ?

            """, (new_sq_id, new_sq_version, item_id))

        else:

            cursor.execute("""

                INSERT INTO ITMSQ (ITMSQID, ITEMID, ITMSQV) 

                VALUES (?, ?, ?)

            """, (new_sq_id, item_id, new_sq_version))



        conn.commit()

        conn.close()



        return {

            "success": True,

            "action": action_type,

            "square_id": new_sq_id

        }



    except Exception as e:

        full_tb = traceback.format_exc()

        return {"success": False, "error": f"Square API Exception: {str(e)} | Trace: {full_tb}"}

@square_bp.route('/fetch-info/<int:item_id>', methods=['GET'])

def fetch_item_info_from_square(item_id):

    """

    Fetches item details, variations, and images from Square catalog 

    using search_catalog_objects for universal SDK compatibility.

    """

    client = get_square_client()

    if not client:

        return jsonify({"success": False, "error": "Square client not initialized."}), 400



    try:

        conn = get_db()

        cursor = conn.cursor()

        cursor.execute("SELECT ITMSQID FROM ITMSQ WHERE ITEMID = ?", (item_id,))

        mapping = cursor.fetchone()

        conn.close()



        if not mapping or not mapping['ITMSQID']:

            return jsonify({"success": False, "error": "Item is not mapped to Square yet."}), 404



        sq_id = mapping['ITMSQID'].strip()



        # Use search_catalog_objects to retrieve the object and related objects safely

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



        objects_list = []

        related_objects = []



        if hasattr(response, 'objects'):

            objects_list = response.objects or []

        elif isinstance(response, dict):

            objects_list = response.get('objects', [])

            related_objects = response.get('related_objects', [])



        if hasattr(response, 'related_objects'):

            related_objects = response.related_objects or []



        object_data = objects_list[0] if objects_list else None



        if not object_data:

            return jsonify({"success": False, "error": "Catalog object not found in Square."}), 404



        def get_field(obj, key):

            if isinstance(obj, dict):

                return obj.get(key)

            return getattr(obj, key, None)



        item_data = get_field(object_data, 'item_data') or {}

        item_name = get_field(item_data, 'name')

        item_desc = get_field(item_data, 'description')

        item_group_id = get_field(item_data, 'item_group_id')

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



        # Parse variations and pricing

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



        return jsonify({

            "success": True,

            "square_id": sq_id,

            "name": item_name,

            "description": item_desc,

            "item_group_id": item_group_id,

            "variations": parsed_variations,

            "images": image_urls

        })



    except Exception as e:

        return jsonify({"success": False, "error": str(e)}), 500
