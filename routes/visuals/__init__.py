from flask import Blueprint

# Initialize the single blueprint for all visuals-related routes
visuals_bp = Blueprint('visuals_bp', __name__)

# Import submodule registration functions
from .sales import register_sales_visual_routes

# Register all routes onto the shared blueprint
register_sales_visual_routes(visuals_bp)