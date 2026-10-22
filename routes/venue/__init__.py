from flask import Blueprint

# Initialize the single blueprint for all venue-related routes
venue_bp = Blueprint('venue_bp', __name__)

# Import submodule registration functions
from .crud import register_venue_routes

# Register all routes onto the shared blueprint
register_venue_routes(venue_bp)