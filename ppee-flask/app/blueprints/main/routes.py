from flask import render_template, redirect, url_for
from app.blueprints.main import bp

@bp.route('/')
def index():
    """Главная страница"""
    return render_template('main/index.html', title='Главная')
