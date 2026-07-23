import os
import re
from werkzeug.utils import secure_filename
from PIL import Image

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
