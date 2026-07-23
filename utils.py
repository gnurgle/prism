import os
import re
import numpy as np
import xml.etree.ElementTree as ET
from lxml import etree
from PIL import Image, ImageFilter
from autotrace import Bitmap, VectorFormat
from werkzeug.utils import secure_filename

# Allowed extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_and_save_image(file_obj, upload_subfolder, custom_filename_base, target_size=(256, 256)):
    """
    Modular utility to upload, process, and resize images.
    
    :param file_obj: FileStorage object from request.files
    :param upload_subfolder: e.g. 'images/glass' relative to static folder
    :param custom_filename_base: Base string for filename e.g. '101_Clear_Float'
    :param target_size: Tuple for resizing, default (256, 256)
    :return: Relative path string to save in the DB (e.g., 'images/glass/101_Clear_Float.jpg') or None
    """
    if not file_obj or file_obj.filename == '':
        return None

    if not allowed_file(file_obj.filename):
        raise ValueError("Unsupported file format.")

    # Sanitize custom base name (remove illegal filesystem chars)
    clean_base = re.sub(r'[^\w\-]', '_', str(custom_filename_base))
    
    # Get extension
    ext = file_obj.filename.rsplit('.', 1)[1].lower()
    filename = f"{clean_base}.{ext}"

    # Build target directory path (assumes standard Flask app.static_folder)
    # Target directory: ./static/images/glass
    upload_dir = os.path.join('./static', upload_subfolder)
    os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, filename)

    # Process and resize image using Pillow
    img = Image.open(file_obj)
    
    # Convert RGBA/P to RGB if saving as JPEG
    if img.mode in ("RGBA", "P") and ext in ('jpg', 'jpeg'):
        img = img.convert("RGB")

    # Crop/resize to exact square without distortion
    # Fit inside target dimensions using a thumbnail or high-quality resized output
    img = img.resize(target_size, Image.Resampling.LANCZOS)
    img.save(file_path, quality=90)

    # Return web-friendly relative path (e.g. 'images/glass/12_Red_Opal.jpg')
    return os.path.join(upload_subfolder, filename).replace('\\', '/')

def hex_to_hsv(hex_str):

    """Takes a hex color string (e.g., 'FF0000' or '#FF0000') and returns a numeric sortable tuple/value (H, S, V)."""
    if not hex_str:
        return (360, 0, 1.0) # Default sorting value for missing colors (push to end)

    hex_str = hex_str.lstrip('#')
    if len(hex_str) != 6:
        return (360, 0, 1.0)
    
    try:
        r = int(hex_str[0:2], 16) / 255.0
        g = int(hex_str[2:4], 16) / 255.0
        b = int(hex_str[4:6], 16) / 255.0
    except ValueError:
        return (360, 0, 1.0)

    max_c = max(r, g, b)
    min_c = min(r, g, b)
    diff = max_c - min_c

    # Value
    v = max_c

    # Saturation
    s = 0 if max_c == 0 else (diff / max_c)

    # Hue
    if diff == 0:
        h = 0
    elif max_c == r:
        h = (60 * ((g - b) / diff) + 360) % 360
    elif max_c == g:
        h = (60 * ((b - r) / diff) + 120) % 360
    else:
        h = (60 * ((r - g) / diff) + 240) % 360

    # Return a single comparable numeric weight or tuple. 
    # Combining H, S, V into a single floating-point number: (H * 1000) + (S * 100) + V
    return (h * 1000) + (s * 100) + v

def convert_image_to_svg(input_image_path: str, output_svg_path: str) -> bool:
    """

    Isolates each enclosed white or transparent space, crops out extra outer 

    whitespace padding from the source image, traces them into separate paths, 

    and packages them into a clean, appropriately-bounded SVG.

    """

    try:

        os.makedirs(os.path.dirname(output_svg_path), exist_ok=True)



        with Image.open(input_image_path) as img:

            # 1. Automatically crop out extra outer white/transparent padding from the source image

            # Convert to RGBA to inspect transparency & white borders accurately

            rgba_img = img.convert("RGBA")

            

            # Create a non-transparent/non-white mask to find content bounding box

            np_img = np.array(rgba_img)

            r, g, b, a = np_img[:,:,0], np_img[:,:,1], np_img[:,:,2], np_img[:,:,3]

            

            # Content is anything that is not fully transparent and not pure white (>= 245)

            is_content = (a > 0) & ~((r >= 245) & (g >= 245) & (b >= 245))

            

            # Find coordinates of content to compute crop box

            coords = np.argwhere(is_content)

            if coords.size > 0:

                y_min, x_min = coords.min(axis=0)

                y_max, x_max = coords.max(axis=0)

                

                # Add a small 5-pixel padding buffer so lines aren't right on the edge

                pad = 5

                crop_box = (

                    max(0, x_min - pad),

                    max(0, y_min - pad),

                    min(rgba_img.width, x_max + pad),

                    min(rgba_img.height, y_max + pad)

                )

                cropped_img = rgba_img.crop(crop_box)

            else:

                cropped_img = rgba_img



            width, height = cropped_img.size

            pixels = cropped_img.load()



            # 2. Threshold to find white or transparent spaces within the cropped bounds

            white_mask = np.zeros((height, width), dtype=bool)

            for y in range(height):

                for x in range(width):

                    pr, pg, pb, pa = pixels[x, y]

                    if pa == 0 or (pr >= 180 and pg >= 180 and pb >= 180):

                        white_mask[y, x] = True



            visited = np.zeros((height, width), dtype=bool)

            components = []



            # 3. Flood-fill to find individual enclosed white/transparent regions

            for y in range(height):

                for x in range(width):

                    if white_mask[y, x] and not visited[y, x]:

                        queue = [(x, y)]

                        visited[y, x] = True

                        component = [(x, y)]

                        touches_edge = (x == 0 or x == width - 1 or y == 0 or y == height - 1)



                        head = 0

                        while head < len(queue):

                            cx, cy = queue[head]

                            head += 1



                            if cx == 0 or cx == width - 1 or cy == 0 or cy == height - 1:

                                touches_edge = True



                            for nx, ny in [(cx+1, cy), (cx-1, cy), (cx, cy+1), (cx, cy-1)]:

                                if 0 <= nx < width and 0 <= ny < height:

                                    if white_mask[ny, nx] and not visited[ny, nx]:

                                        visited[ny, nx] = True

                                        queue.append((nx, ny))

                                        component.append((nx, ny))



                        # Keep internal enclosed regions that are large enough

                        if not touches_edge and len(component) > 50:

                            components.append(component)



        # 4. Create root SVG container scaled to the cropped dimensions

        root_svg = ET.Element("svg", {

            "xmlns": "http://www.w3.org/2000/svg",

            "version": "1.1",

            "width": str(width),

            "height": str(height),

            "viewBox": f"0 0 {width} {height}"

        })



        valid_index = 1



        def is_full_canvas_path(path_data):

            numbers = [float(n) for n in re.findall(r"[-+]?\d*\.\d+|\d+", path_data)]

            if not numbers:

                return False

            min_x, max_x = min(numbers[0::2]), max(numbers[0::2])

            min_y, max_y = min(numbers[1::2]), max(numbers[1::2])

            return (max_x - min_x) >= (width * 0.9) and (max_y - min_y) >= (height * 0.9)



        # 5. Trace each isolated component independently

        for idx, component in enumerate(components):

            comp_array = np.full((height, width), 255, dtype=np.uint8)

            for px, py in component:

                comp_array[py, px] = 0  # Solid black object



            comp_img = Image.fromarray(comp_array).convert("RGB")

            bitmap = Bitmap(np.array(comp_img))



            temp_svg_path = f"{output_svg_path}_temp_{idx}.svg"

            try:

                vector = bitmap.trace(

                    centerline=False,

                    color_count=2,

                    despeckle_level=2,

                    corner_threshold=100,

                    error_threshold=1.0,

                    preserve_width=True

                )

                vector.save(temp_svg_path)



                tree = ET.parse(temp_svg_path)

                temp_root = tree.getroot()

                

                for elem in temp_root.iter():

                    if elem.tag.endswith('path'):

                        path_data = elem.get('d')

                        if path_data:

                            if is_full_canvas_path(path_data):

                                continue



                            new_path = ET.Element("path", {

                                "d": path_data,

                                "fill": "black",

                                "id": f"region-{valid_index}",

                                "data-region-id": str(valid_index)

                            })

                            root_svg.append(new_path)

                            valid_index += 1

            finally:

                if os.path.exists(temp_svg_path):

                    os.remove(temp_svg_path)



        # 6. Save final cropped SVG

        tree = ET.ElementTree(root_svg)

        tree.write(output_svg_path, encoding="utf-8", xml_declaration=True)

        return True

        

    except Exception as e:

        print(f"Error during cropped whitespace SVG conversion: {e}")

        return False
def convert_image_to_bksvg_bk(input_image_path: str, output_svg_path: str) -> bool:

    try:
        os.makedirs(os.path.dirname(output_svg_path), exist_ok=True)

        with Image.open(input_image_path) as img:
            # 1. Convert to grayscale
            gray_img = img.convert("L")
            
            # 2. Invert logic: Make white spaces black (0) and black lines white (255).
            # This turns the internal white regions into solid objects for tracing.
            table = [255 if p < 180 else 0 for p in range(256)]
            inverted_img = gray_img.point(table, 'L')
            
            # 3. Clean and merge tiny spots/holes:
            # MedianFilter/MinFilter smooths and fills minor fragmented regions, 
            # effectively absorbing tiny specs or micro-gaps into adjacent areas.
            processed_img = inverted_img.filter(ImageFilter.MedianFilter(size=5))
            
            # 4. Convert to RGB format required by Bitmap
            rgb_image = processed_img.convert("RGB")
            image_array = np.array(rgb_image)

        bitmap = Bitmap(image_array)

        # 5. Trace settings optimized for filled regions/white spaces (centerline=False captures outlines)
        vector = bitmap.trace(
            centerline=False,             # Trace full outlines of the whitespace areas, not just center skeletons
            color_count=2,                
            despeckle_level=4,            # Higher despeckle level to eliminate stray tiny shapes
            corner_threshold=100,         
            error_threshold=1.0,          
            preserve_width=True           
        )

        vector.save(output_svg_path)
        return True
        
    except Exception as e:
        print(f"Error during whitespace SVG conversion: {e}")
        return False

def remove_svg_region_and_renumber(svg_path, target_region_id_num):

    """

    Helper function using the robust wildcard logic proven in the test harness.

    Removes a specific path and re-indexes all remaining paths sequentially.

    """

    if not os.path.exists(svg_path):

        print(f"HELPER ERROR: File path does not exist -> {svg_path}")

        return False



    try:

        # Use robust XML parser settings

        parser = etree.XMLParser(remove_blank_text=True, recover=True)

        tree = etree.parse(svg_path, parser)

        

        # Use local-name() wildcard to bypass strict namespace issues

        path_elements = tree.xpath('//*[local-name()="path"]')



        removed = False

        for elem in path_elements:

            region_val = elem.get('data-region-id')

            elem_id = elem.get('id', '')



            # Match by data-region-id or ID string format (e.g., 'region-2' or '2')

            if (region_val and str(region_val).strip() == str(target_region_id_num)) or (elem_id in [f"region-{target_region_id_num}", str(target_region_id_num)]):

                

                parent = elem.getparent()

                if parent is not None:

                    parent.remove(elem)

                    removed = True

                    print(f"HELPER SUCCESS: Removed element ID '{elem_id}', data-region-id '{region_val}'")

                break



        if not removed:

            print(f"HELPER WARNING: Target region '{target_region_id_num}' was not found inside {svg_path}")

            return False



        # Re-fetch remaining paths and re-index attributes sequentially starting from 1

        remaining_paths = tree.xpath('//*[local-name()="path"]')

        for new_idx, elem in enumerate(remaining_paths, start=1):

            elem.set('id', f'region-{new_idx}')

            elem.set('data-region-id', str(new_idx))

            if elem.get('data-number') is not None:

                elem.set('data-number', str(new_idx))



        # Explicitly write changes back out to disk using binary mode

        root = tree.getroot()

        xml_bytes = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='utf-8')

        with open(svg_path, 'wb') as f:

            f.write(xml_bytes)



        print(f"HELPER COMMITTED: Successfully wrote updated XML tree back to disk -> {svg_path}")

        return True

    except Exception as e:

        print(f"HELPER EXCEPTION: Error processing SVG renumbering: {e}")

        return False
