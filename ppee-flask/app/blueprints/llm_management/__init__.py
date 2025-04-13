from flask import Blueprint

bp = Blueprint('llm_management', __name__, url_prefix='/llm')

from app.blueprints.llm_management import routes
