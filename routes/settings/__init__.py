from flask import Blueprint

# Initialize the single blueprint for all settings-related routes
settings_bp = Blueprint('settings_bp', __name__, template_folder='templates')

# Import submodule registration functions
from .general import register_general_routes
from .textures import register_texture_routes
from .sources import register_source_routes
from .appearance import register_appearance_routes

# Register all routes onto the shared blueprint
register_general_routes(settings_bp)
register_texture_routes(settings_bp)
register_source_routes(settings_bp)
register_appearance_routes(settings_bp)