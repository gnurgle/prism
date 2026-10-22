from flask import Blueprint

# Initialize the single blueprint for all glass-related routes
glass_bp = Blueprint('glass_bp', __name__)

# Import submodule registration functions
from .crud import register_crud_routes
from .pricing import register_pricing_routes
from .inventory import register_inventory_routes
from .visuals import register_visual_routes

# Register all routes onto the shared blueprint
register_crud_routes(glass_bp)
register_pricing_routes(glass_bp)
register_inventory_routes(glass_bp)
register_visual_routes(glass_bp)