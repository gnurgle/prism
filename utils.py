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

def process_and_save_image(file_obj, upload_subfolder, custom_filename_base, target_size=(1024, 1024)):
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

def format_fractional_inches(value):
    if value is None:
        return '—'
    try:
        val = float(value)
    except (ValueError, TypeError):
        return '—'
    
    whole = int(val)
    remainder = val - whole
    
    # Round to the nearest 1/8 (0.125)
    eighths = round(remainder * 8)
    
    if eighths == 8:
        whole += 1
        eighths = 0
    
    # Reduce fractions
    fractions = {
        0: '',
        1: '1/8',
        2: '1/4',
        3: '3/8',
        4: '1/2',
        5: '5/8',
        6: '3/4',
        7: '7/8'
    }
    
    frac_str = fractions.get(eighths, '')
    
    if whole == 0 and frac_str == '':
        return '0"'
    elif whole == 0:
        return f'{frac_str}"'
    elif frac_str == '':
        return f'{whole}"'
    else:
        return f'{whole} {frac_str}"'


def compute_total_path_length(svg_string, width_inches, height_inches):

    """

    Parses the SVG path string natively, determines the exact bounding box of the path 

    to use as true pixel dimensions, computes total length, and scales to physical inches.

    """

    try:

        root = etree.fromstring(svg_string.encode('utf-8'))

        namespaces = {'svg': 'http://www.w3.org/2000/svg'}

        paths = root.findall('.//svg:path', namespaces)

        if not paths:

            paths = root.findall('.//path')



        if not paths:

            return 0.0



        total_px_length = 0.0

        all_x = []

        all_y = []



        for p in paths:

            d_val = p.get('d', '')

            if not d_val:

                continue

            

            tokens = re.findall(r'[MmLlHhVvCcZz]|[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', d_val)

            

            current_x, current_y = 0.0, 0.0

            start_x, start_y = 0.0, 0.0

            

            i = 0

            while i < len(tokens):

                tok = tokens[i]

                if tok in ('M', 'm'):

                    x = float(tokens[i+1])

                    y = float(tokens[i+2])

                    if tok == 'm':

                        current_x += x

                        current_y += y

                    else:

                        current_x, current_y = x, y

                    start_x, start_y = current_x, current_y

                    all_x.append(current_x)

                    all_y.append(current_y)

                    i += 3

                elif tok in ('L', 'l'):

                    x = float(tokens[i+1])

                    y = float(tokens[i+2])

                    if tok == 'l':

                        dx, dy = x, y

                    else:

                        dx, dy = x - current_x, y - current_y

                    seg_len = np.hypot(dx, dy)

                    total_px_length += seg_len

                    current_x += dx if tok == 'l' else (x - current_x)

                    current_y += dy if tok == 'l' else (y - current_y)

                    all_x.append(current_x)

                    all_y.append(current_y)

                    i += 3

                elif tok in ('H', 'h'):

                    x = float(tokens[i+1])

                    dx = x if tok == 'h' else (x - current_x)

                    seg_len = abs(dx)

                    total_px_length += seg_len

                    current_x += dx

                    all_x.append(current_x)

                    all_y.append(current_y)

                    i += 2

                elif tok in ('V', 'v'):

                    y = float(tokens[i+1])

                    dy = y if tok == 'v' else (y - current_y)

                    seg_len = abs(dy)

                    total_px_length += seg_len

                    current_y += dy

                    all_x.append(current_x)

                    all_y.append(current_y)

                    i += 2

                elif tok in ('C', 'c'):

                    p0 = (current_x, current_y)

                    is_rel = (tok == 'c')

                    p1 = (float(tokens[i+1]) + (current_x if is_rel else 0), float(tokens[i+2]) + (current_y if is_rel else 0))

                    p2 = (float(tokens[i+3]) + (current_x if is_rel else 0), float(tokens[i+4]) + (current_y if is_rel else 0))

                    p3 = (float(tokens[i+5]) + (current_x if is_rel else 0), float(tokens[i+6]) + (current_y if is_rel else 0))

                    

                    curve_len = 0.0

                    prev_pt = p0

                    for t in np.linspace(0.1, 1.0, 10):

                        bx = (1-t)**3 * p0[0] + 3*(1-t)**2 * t * p1[0] + 3*(1-t)*t**2 * p2[0] + t**3 * p3[0]

                        by = (1-t)**3 * p0[1] + 3*(1-t)**2 * t * p1[1] + 3*(1-t)*t**2 * p2[1] + t**3 * p3[1]

                        curve_len += np.hypot(bx - prev_pt[0], by - prev_pt[1])

                        prev_pt = (bx, by)

                        

                    total_px_length += curve_len

                    current_x, current_y = p3

                    all_x.append(current_x)

                    all_y.append(current_y)

                    i += 7

                elif tok in ('Z', 'z'):

                    seg_len = np.hypot(start_x - current_x, start_y - current_y)

                    total_px_length += seg_len

                    current_x, current_y = start_x, start_y

                    all_x.append(current_x)

                    all_y.append(current_y)

                    i += 1

                else:

                    i += 1



        if not all_x or not all_y:

            return 0.0



        svg_px_width = max(all_x) - min(all_x)

        svg_px_height = max(all_y) - min(all_y)



        if svg_px_width <= 0:

            svg_px_width = 1.0

        if svg_px_height <= 0:

            svg_px_height = 1.0



        px_to_inch_x = width_inches / svg_px_width

        px_to_inch_y = height_inches / svg_px_height

        avg_scale = (px_to_inch_x + px_to_inch_y) / 2.0



        total_inches = total_px_length * avg_scale

        return round(total_inches, 2)

    except Exception as e:

        print("Path computation error:", e)

        return 0.0






def trace_stencil_to_single_path_svg(image_file):

    img = Image.open(image_file)

    rgba_img = img.convert("RGBA")

    

    np_img = np.array(rgba_img)

    r, g, b, a = np_img[:,:,0], np_img[:,:,1], np_img[:,:,2], np_img[:,:,3]

    is_content = (a > 0) & ~((r >= 245) & (g >= 245) & (b >= 245))

    

    coords = np.argwhere(is_content)

    if coords.size > 0:

        y_min, x_min = coords.min(axis=0)

        y_max, x_max = coords.max(axis=0)

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



    background = Image.new("RGB", cropped_img.size, (255, 255, 255))

    background.paste(cropped_img, mask=cropped_img.split()[3])

    

    gray_img = background.convert('L')

    binary_img = gray_img.point(lambda p: 0 if p < 200 else 255, '1')

    bin_arr = np.array(binary_img) == 0  



    current_arr = bin_arr.copy()

    skeleton_arr = np.zeros_like(current_arr, dtype=bool)

    

    for _ in range(max(width, height)):

        if not np.any(current_arr):

            break

        from scipy.ndimage import binary_erosion, binary_opening

        eroded = binary_erosion(current_arr)

        opened = binary_opening(eroded)

        subset = current_arr & ~opened

        skeleton_arr |= subset

        current_arr = eroded



    skel_img_data = np.ones((height, width, 3), dtype=np.uint8) * 255

    skel_img_data[skeleton_arr] = [0, 0, 0]

    

    final_prep_img = Image.fromarray(skel_img_data)

    img_array = np.array(final_prep_img)

    bitmap = Bitmap(img_array)

    vector = bitmap.trace(centerline=True)

    svg_bytes = vector.encode(VectorFormat.SVG)

    

    root = etree.fromstring(svg_bytes)

    namespaces = {'svg': 'http://www.w3.org/2000/svg'}

    paths = root.findall('.//svg:path', namespaces)

    if not paths:

        paths = root.findall('.//path')

        

    combined_d = []

    for p in paths:

        d_val = p.get('d')

        if d_val:

            if f"H {width}" in d_val or f"V {height}" in d_val or f"h {width}" in d_val or f"v {height}" in d_val:

                continue

            if d_val.startswith("M 0 0") or d_val.startswith("M0 0"):

                continue

            combined_d.append(d_val)

            

    new_root = ET.Element('svg', {

        'xmlns': 'http://www.w3.org/2000/svg',

        'viewBox': f'0 0 {width} {height}',

        'width': '100%',

        'height': '100%'

    })

    

    if combined_d:

        single_path_element = ET.Element('path', {

            'd': ' '.join(combined_d),

            'fill': 'none',

            'stroke': 'black',

            'stroke-width': '2',

            'stroke-linecap': 'round',

            'stroke-linejoin': 'round'

        })

        new_root.append(single_path_element)

        

    return ET.tostring(new_root, encoding='unicode')


def trace_stencil_to_outline_svg(image_file):

    """

    Traces the standard solid outline of the uploaded image. Compares original and 

    cropped dimensions; if no difference is found, processes the full image boundary.

    Otherwise, filters out frame artifacts and retains only the path with the largest bounding box area.

    """

    img = Image.open(image_file)

    rgba_img = img.convert("RGBA")

    orig_width, orig_height = rgba_img.size

    

    np_img = np.array(rgba_img)

    r, g, b, a = np_img[:,:,0], np_img[:,:,1], np_img[:,:,2], np_img[:,:,3]

    is_content = (a > 0) & ~((r >= 245) & (g >= 245) & (b >= 245))

    

    coords = np.argwhere(is_content)

    if coords.size > 0:

        y_min, x_min = coords.min(axis=0)

        y_max, x_max = coords.max(axis=0)

        pad = 5

        crop_box = (

            max(0, x_min - pad),

            max(0, y_min - pad),

            min(orig_width, x_max + pad),

            min(orig_height, y_max + pad)

        )

        cropped_img = rgba_img.crop(crop_box)

    else:

        cropped_img = rgba_img



    width, height = cropped_img.size

    no_difference = (width == orig_width and height == orig_height)



    background = Image.new("RGB", cropped_img.size, (255, 255, 255))

    background.paste(cropped_img, mask=cropped_img.split()[3])

    

    gray_img = background.convert('L')

    binary_img = gray_img.point(lambda p: 0 if p < 200 else 255, '1')

    img_array = np.array(binary_img.convert('RGB'))

    

    bitmap = Bitmap(img_array)

    vector = bitmap.trace(centerline=False)

    svg_bytes = vector.encode(VectorFormat.SVG)

    

    root = etree.fromstring(svg_bytes)

    namespaces = {'svg': 'http://www.w3.org/2000/svg'}

    paths = root.findall('.//svg:path', namespaces)

    if not paths:

        paths = root.findall('.//path')

        

    valid_paths = []

    for p in paths:

        d_val = p.get('d')

        if not d_val:

            continue

            

        if not no_difference:

            if f"H {width}" in d_val or f"V {height}" in d_val or f"h {width}" in d_val or f"v {height}" in d_val:

                continue

            if d_val.startswith("M 0 0") or d_val.startswith("M0 0"):

                continue

            

        tokens = re.findall(r'[MmLlHhVvCcZz]|[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', d_val)

        curr_x, curr_y = 0.0, 0.0

        path_x = []

        path_y = []

        

        idx = 0

        while idx < len(tokens):

            tok = tokens[idx]

            if tok in ('M', 'm', 'L', 'l'):

                if idx + 2 < len(tokens):

                    try:

                        x = float(tokens[idx+1])

                        y = float(tokens[idx+2])

                        if tok in ('m', 'l'):

                            curr_x += x

                            curr_y += y

                        else:

                            curr_x, curr_y = x, y

                        path_x.append(curr_x)

                        path_y.append(curr_y)

                    except ValueError:

                        pass

                idx += 3

            elif tok in ('H', 'h'):

                if idx + 1 < len(tokens):

                    try:

                        x = float(tokens[idx+1])

                        curr_x = curr_x + x if tok == 'h' else x

                        path_x.append(curr_x)

                        path_y.append(curr_y)

                    except ValueError:

                        pass

                idx += 2

            elif tok in ('V', 'v'):

                if idx + 1 < len(tokens):

                    try:

                        y = float(tokens[idx+1])

                        curr_y = curr_y + y if tok == 'v' else y

                        path_x.append(curr_x)

                        path_y.append(curr_y)

                    except ValueError:

                        pass

                idx += 2

            elif tok in ('C', 'c'):

                if idx + 6 < len(tokens):

                    try:

                        is_rel = (tok == 'c')

                        curr_x = float(tokens[idx+5]) + (curr_x if is_rel else 0)

                        curr_y = float(tokens[idx+6]) + (curr_y if is_rel else 0)

                        path_x.append(curr_x)

                        path_y.append(curr_y)

                    except ValueError:

                        pass

                idx += 7

            else:

                idx += 1

                

        if path_x and path_y:

            box_width = max(path_x) - min(path_x)

            box_height = max(path_y) - min(path_y)

            box_area = box_width * box_height

            valid_paths.append((box_area, d_val))



    new_root = ET.Element('svg', {

        'xmlns': 'http://www.w3.org/2000/svg',

        'viewBox': f'0 0 {width} {height}',

        'width': '100%',

        'height': '100%'

    })

    

    if valid_paths:

        if no_difference:

            # If no difference between original and cropped size, combine all valid path segments or take the largest

            valid_paths.sort(key=lambda x: x[0], reverse=True)

            largest_d = valid_paths[0][1]

        else:

            valid_paths.sort(key=lambda x: x[0], reverse=True)

            largest_d = valid_paths[0][1]

        

        single_path_element = ET.Element('path', {

            'd': largest_d,

            'fill': 'none',

            'stroke': 'black',

            'stroke-width': '2',

            'stroke-linecap': 'round',

            'stroke-linejoin': 'round'

        })

        new_root.append(single_path_element)

        

    return ET.tostring(new_root, encoding='unicode')

def trace_stencil_to_filled_outline_svg(image_file):

    """

    Traces the standard multi-path outline of the uploaded image without centerline thinning,

    following the preprocessing workflow of trace_stencil_to_single_path_svg.

    """

    img = Image.open(image_file)

    rgba_img = img.convert("RGBA")

    

    np_img = np.array(rgba_img)

    r, g, b, a = np_img[:,:,0], np_img[:,:,1], np_img[:,:,2], np_img[:,:,3]

    is_content = (a > 0) & ~((r >= 245) & (g >= 245) & (b >= 245))

    

    coords = np.argwhere(is_content)

    if coords.size > 0:

        y_min, x_min = coords.min(axis=0)

        y_max, x_max = coords.max(axis=0)

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



    background = Image.new("RGB", cropped_img.size, (255, 255, 255))

    background.paste(cropped_img, mask=cropped_img.split()[3])

    

    gray_img = background.convert('L')

    binary_img = gray_img.point(lambda p: 0 if p < 200 else 255, '1')

    img_array = np.array(binary_img.convert('RGB'))

    

    bitmap = Bitmap(img_array)

    vector = bitmap.trace(centerline=False)

    svg_bytes = vector.encode(VectorFormat.SVG)

    

    root = etree.fromstring(svg_bytes)

    namespaces = {'svg': 'http://www.w3.org/2000/svg'}

    paths = root.findall('.//svg:path', namespaces)

    if not paths:

        paths = root.findall('.//path')

        

    combined_d = []

    for p in paths:

        d_val = p.get('d')

        if d_val:

            if f"H {width}" in d_val or f"V {height}" in d_val or f"h {width}" in d_val or f"v {height}" in d_val:

                continue

            if d_val.startswith("M 0 0") or d_val.startswith("M0 0"):

                continue

            combined_d.append(d_val)

            

    new_root = ET.Element('svg', {

        'xmlns': 'http://www.w3.org/2000/svg',

        'viewBox': f'0 0 {width} {height}',

        'width': '100%',

        'height': '100%'

    })

    

    if combined_d:

        single_path_element = ET.Element('path', {

            'd': ' '.join(combined_d),

            'fill': 'none',

            'stroke': 'black',

            'stroke-width': '2',

            'stroke-linecap': 'round',

            'stroke-linejoin': 'round'

        })

        new_root.append(single_path_element)

        

    return ET.tostring(new_root, encoding='unicode')
