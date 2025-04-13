from flask import render_template, redirect, url_for, flash, request
from app.blueprints.auth import bp

@bp.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа"""
    return render_template('auth/login.html', title='Вход')
