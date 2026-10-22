from flask import Blueprint
from utils import format_fractional_inches

# Initialize the single blueprint for all miscellaneous/supply routes
misc_bp = Blueprint('misc_bp', __name__)

@misc_bp.context_processor
def inject_utils():
    return dict(format_fractional_inches=format_fractional_inches)

# Import submodule registration functions
from .crud import register_crud_routes
from .pricing import register_pricing_routes
from .inventory import register_inventory_routes
from .visuals import register_visual_routes

# Register all routes onto the shared blueprint
register_crud_routes(misc_bp)
register_pricing_routes(misc_bp)
register_inventory_routes(misc_bp)
register_visual_routes(misc_bp)