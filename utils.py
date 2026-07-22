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
