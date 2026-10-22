from flask import Blueprint

# Initialize the single blueprint for all production-related routes
production_bp = Blueprint('production_bp', __name__)

# Import submodule registration functions
from .board import register_board_routes
from .bulk import register_bulk_routes

# Register all routes onto the shared blueprint
register_board_routes(production_bp)
register_bulk_routes(production_bp)