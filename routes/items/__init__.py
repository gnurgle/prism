from flask import Blueprint

# Initialize the single blueprint for all item-related routes
item_bp = Blueprint('item_bp', __name__)

# Import submodule registration functions
from .crud import register_crud_routes
from .pricing import register_pricing_routes
from .inventory import register_inventory_routes
from .sales import register_sales_routes
from .visuals import register_visual_routes

# Register all routes onto the shared blueprint
register_crud_routes(item_bp)
register_pricing_routes(item_bp)
register_inventory_routes(item_bp)
register_sales_routes(item_bp)
register_visual_routes(item_bp)