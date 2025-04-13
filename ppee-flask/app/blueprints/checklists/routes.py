from flask import render_template, redirect, url_for, flash, request
from app.blueprints.checklists import bp

@bp.route('/')
def index():
    """Страница со списком чек-листов"""
    return render_template('checklists/index.html', title='Чек-листы')
