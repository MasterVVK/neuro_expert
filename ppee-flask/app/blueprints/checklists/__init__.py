from flask import Blueprint

bp = Blueprint('checklists', __name__, url_prefix='/checklists')

from app.blueprints.checklists import routes
