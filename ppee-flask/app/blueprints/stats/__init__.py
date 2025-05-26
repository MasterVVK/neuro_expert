from flask import Blueprint

bp = Blueprint('stats', __name__, url_prefix='/stats')

from app.blueprints.stats import routes