from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import User
from app.decorators import admin_required
from app.blueprints.users import bp


@bp.route('/')
@login_required
@admin_required
def index():
    """Список всех пользователей (только для администраторов)"""
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('users/index.html',
                           title='Управление пользователями',
                           users=users)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create():
    """Создание нового пользователя (только для администраторов)"""
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'user')

        # Валидация
        errors = []

        if not username or not email or not password:
            errors.append('Заполните все обязательные поля')

        if User.query.filter_by(username=username).first():
            errors.append('Пользователь с таким именем уже существует')

        if User.query.filter_by(email=email).first():
            errors.append('Пользователь с таким email уже существует')

        if len(password) < 6:
            errors.append('Пароль должен содержать минимум 6 символов')

        if role not in ['user', 'prompt_engineer', 'admin']:
            errors.append('Недопустимая роль')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('users/create.html',
                                   title='Создание пользователя',
                                   username=username,
                                   email=email,
                                   role=role)

        # Создание пользователя
        user = User(username=username, email=email, role=role)
        user.set_password(password)

        try:
            db.session.add(user)
            db.session.commit()
            flash(f'Пользователь {username} успешно создан', 'success')
            return redirect(url_for('users.index'))
        except Exception as e:
            db.session.rollback()
            flash('Ошибка при создании пользователя', 'error')
            return render_template('users/create.html',
                                   title='Создание пользователя',
                                   username=username,
                                   email=email,
                                   role=role)

    return render_template('users/create.html', title='Создание пользователя')


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit(id):
    """Редактирование пользователя (только для администраторов)"""
    user = User.query.get_or_404(id)

    # Защита от редактирования самого себя
    if user.id == current_user.id:
        flash('Вы не можете редактировать свой собственный профиль через эту страницу', 'error')
        return redirect(url_for('users.index'))

    if request.method == 'POST':
        email = request.form.get('email')
        role = request.form.get('role')
        new_password = request.form.get('new_password')

        # Валидация
        errors = []

        if not email:
            errors.append('Email не может быть пустым')

        # Проверка уникальности email
        existing_user = User.query.filter_by(email=email).first()
        if existing_user and existing_user.id != user.id:
            errors.append('Пользователь с таким email уже существует')

        if role not in ['user', 'prompt_engineer', 'admin']:
            errors.append('Недопустимая роль')

        if new_password and len(new_password) < 6:
            errors.append('Пароль должен содержать минимум 6 символов')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('users/edit.html',
                                   title=f'Редактирование пользователя {user.username}',
                                   user=user)

        # Обновление данных
        user.email = email
        user.role = role

        if new_password:
            user.set_password(new_password)

        try:
            db.session.commit()
            flash(f'Пользователь {user.username} успешно обновлен', 'success')
            return redirect(url_for('users.index'))
        except Exception as e:
            db.session.rollback()
            flash('Ошибка при обновлении пользователя', 'error')

    return render_template('users/edit.html',
                           title=f'Редактирование пользователя {user.username}',
                           user=user)


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete(id):
    """Удаление пользователя (только для администраторов)"""
    user = User.query.get_or_404(id)

    # Защита от удаления самого себя
    if user.id == current_user.id:
        flash('Вы не можете удалить свой собственный аккаунт', 'error')
        return redirect(url_for('users.index'))

    # Защита от удаления последнего администратора
    if user.role == 'admin':
        admin_count = User.query.filter_by(role='admin').count()
        if admin_count <= 1:
            flash('Нельзя удалить последнего администратора', 'error')
            return redirect(url_for('users.index'))

    try:
        username = user.username
        db.session.delete(user)
        db.session.commit()
        flash(f'Пользователь {username} успешно удален', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Ошибка при удалении пользователя', 'error')

    return redirect(url_for('users.index'))


@bp.route('/profile')
@login_required
def profile():
    """Профиль текущего пользователя"""
    return render_template('users/profile.html',
                           title='Мой профиль',
                           user=current_user)


@bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """Редактирование профиля текущего пользователя"""
    if request.method == 'POST':
        email = request.form.get('email')
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        # Валидация
        errors = []

        if not email:
            errors.append('Email не может быть пустым')

        # Проверка уникальности email
        existing_user = User.query.filter_by(email=email).first()
        if existing_user and existing_user.id != current_user.id:
            errors.append('Пользователь с таким email уже существует')

        # Если пользователь хочет изменить пароль
        if new_password or current_password:
            if not current_password:
                errors.append('Введите текущий пароль')
            elif not current_user.check_password(current_password):
                errors.append('Неверный текущий пароль')
            elif not new_password:
                errors.append('Введите новый пароль')
            elif len(new_password) < 6:
                errors.append('Новый пароль должен содержать минимум 6 символов')
            elif new_password != confirm_password:
                errors.append('Пароли не совпадают')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('users/edit_profile.html',
                                   title='Редактирование профиля',
                                   user=current_user)

        # Обновление данных
        current_user.email = email

        if new_password:
            current_user.set_password(new_password)

        try:
            db.session.commit()
            flash('Профиль успешно обновлен', 'success')
            return redirect(url_for('users.profile'))
        except Exception as e:
            db.session.rollback()
            flash('Ошибка при обновлении профиля', 'error')

    return render_template('users/edit_profile.html',
                           title='Редактирование профиля',
                           user=current_user)