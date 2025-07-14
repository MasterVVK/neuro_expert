from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user
from urllib.parse import urlparse
from app import db
from app.blueprints.auth import bp
from app.models import User


@bp.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа"""
    # Если пользователь уже авторизован, перенаправляем на главную
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember', False)

        # Проверка заполнения полей
        if not username or not password:
            flash('Пожалуйста, заполните все поля', 'error')
            return render_template('auth/login.html', title='Вход')

        # Поиск пользователя
        user = User.query.filter_by(username=username).first()

        # Проверка пользователя и пароля
        if user is None or not user.check_password(password):
            flash('Неверное имя пользователя или пароль', 'error')
            return render_template('auth/login.html', title='Вход')

        # Авторизация пользователя
        login_user(user, remember=remember)

        # Получаем страницу для перенаправления
        next_page = request.args.get('next')
        if not next_page or urlparse(next_page).netloc != '':
            next_page = url_for('main.index')

        flash(f'Добро пожаловать, {user.username}!', 'success')
        return redirect(next_page)

    return render_template('auth/login.html', title='Вход')


@bp.route('/logout')
def logout():
    """Выход из системы"""
    logout_user()
    flash('Вы успешно вышли из системы', 'info')
    return redirect(url_for('main.index'))


@bp.route('/register', methods=['GET', 'POST'])
def register():
    """Регистрация нового пользователя"""
    # Если пользователь уже авторизован, перенаправляем на главную
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        password2 = request.form.get('password2')

        # Валидация данных
        errors = []

        if not username or not email or not password or not password2:
            errors.append('Пожалуйста, заполните все поля')

        if password != password2:
            errors.append('Пароли не совпадают')

        if len(password) < 6:
            errors.append('Пароль должен содержать минимум 6 символов')

        # Проверка уникальности username
        if User.query.filter_by(username=username).first():
            errors.append('Пользователь с таким именем уже существует')

        # Проверка уникальности email
        if User.query.filter_by(email=email).first():
            errors.append('Пользователь с таким email уже существует')

        # Если есть ошибки, показываем их
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('auth/register.html',
                                   title='Регистрация',
                                   username=username,
                                   email=email)

        # Создание нового пользователя
        user = User(
            username=username,
            email=email,
            role='user'  # По умолчанию обычный пользователь
        )
        user.set_password(password)

        try:
            db.session.add(user)
            db.session.commit()

            flash('Регистрация прошла успешно! Теперь вы можете войти.', 'success')
            return redirect(url_for('auth.login'))

        except Exception as e:
            db.session.rollback()
            flash('Произошла ошибка при регистрации. Попробуйте позже.', 'error')
            return render_template('auth/register.html',
                                   title='Регистрация',
                                   username=username,
                                   email=email)

    return render_template('auth/register.html', title='Регистрация')