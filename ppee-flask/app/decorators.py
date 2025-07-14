from functools import wraps
from flask import flash, redirect, url_for, abort
from flask_login import current_user


def admin_required(f):
    """
    Декоратор, требующий роль администратора.
    Использовать после @login_required
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))

        if not current_user.is_admin():
            flash('Доступ запрещен. Требуются права администратора.', 'error')
            abort(403)

        return f(*args, **kwargs)

    return decorated_function


def prompt_engineer_required(f):
    """
    Декоратор, требующий роль промпт-инженера или администратора.
    Использовать после @login_required
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))

        if current_user.role not in ['prompt_engineer', 'admin']:
            flash('Доступ запрещен. Требуются права промпт-инженера.', 'error')
            abort(403)

        return f(*args, **kwargs)

    return decorated_function


def role_required(*roles):
    """
    Универсальный декоратор для проверки ролей.
    Пример использования: @role_required('admin', 'prompt_engineer')
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))

            if current_user.role not in roles:
                flash(f'Доступ запрещен. Требуется одна из ролей: {", ".join(roles)}.', 'error')
                abort(403)

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def owner_or_admin_required(model_class, id_param='id'):
    """
    Декоратор для проверки, что пользователь является владельцем объекта или администратором.

    Args:
        model_class: Класс модели SQLAlchemy
        id_param: Имя параметра с ID объекта в маршруте
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))

            # Получаем ID объекта из параметров
            obj_id = kwargs.get(id_param)
            if not obj_id:
                abort(404)

            # Получаем объект из БД
            obj = model_class.query.get_or_404(obj_id)

            # Проверяем права доступа
            if hasattr(obj, 'user_id'):
                if obj.user_id != current_user.id and not current_user.is_admin():
                    flash('Доступ запрещен. Вы не являетесь владельцем этого объекта.', 'error')
                    abort(403)
            elif not current_user.is_admin():
                flash('Доступ запрещен. Требуются права администратора.', 'error')
                abort(403)

            # Добавляем объект в kwargs для использования в функции
            kwargs['obj'] = obj

            return f(*args, **kwargs)

        return decorated_function

    return decorator