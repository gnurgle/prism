from flask import Blueprint

# Initialize the single blueprint for all template-related routes
templates_bp = Blueprint('templates_bp', __name__)

# Import submodule registration functions
from .upload import register_upload_routes
from .trace import register_trace_routes
from .edit import register_edit_routes

# Register all routes onto the shared blueprint
register_upload_routes(templates_bp)
register_trace_routes(templates_bp)
register_edit_routes(templates_bp)