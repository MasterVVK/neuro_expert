from flask import Blueprint

bp = Blueprint('search', __name__, url_prefix='/search')

from app.blueprints.search import routes