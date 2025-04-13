from flask import render_template, redirect, url_for, flash, request
from app.blueprints.applications import bp

@bp.route('/')
def index():
    """Страница со списком заявок"""
    return render_template('applications/index.html', title='Заявки')

@bp.route('/create', methods=['GET', 'POST'])
def create():
    """Создание новой заявки"""
    # Здесь будет логика создания заявки
    return render_template('applications/create.html', title='Создание заявки')
