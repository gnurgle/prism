from flask import Blueprint

# Initialize the single blueprint for all component-related routes
component_bp = Blueprint('component_bp', __name__)

# Import submodule registration functions
from .builder import register_builder_routes
from .exporter import register_exporter_routes
from .editor import register_editor_routes

# Register all routes onto the shared blueprint
register_builder_routes(component_bp)
register_exporter_routes(component_bp)
register_editor_routes(component_bp)