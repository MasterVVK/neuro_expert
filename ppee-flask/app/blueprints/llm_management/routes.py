from flask import render_template, redirect, url_for, flash, request
from app.blueprints.llm_management import bp

@bp.route('/')
def index():
    """Страница управления LLM"""
    return render_template('llm_management/index.html', title='Управление LLM')
