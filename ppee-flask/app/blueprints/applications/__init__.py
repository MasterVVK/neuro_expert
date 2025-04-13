from flask import Blueprint

bp = Blueprint('applications', __name__, url_prefix='/applications')

from app.blueprints.applications import routes
