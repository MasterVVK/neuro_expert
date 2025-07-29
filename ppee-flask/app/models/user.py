from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db
from datetime import datetime


class User(UserMixin, db.Model):
    """Модель пользователя системы"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, index=True)
    email = db.Column(db.String(120), unique=True, index=True)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20), default='user')  # admin, prompt_engineer, user
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<User {self.username}>'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == 'admin'

    def is_prompt_engineer(self):
        return self.role in ['prompt_engineer', 'admin']

    def can_edit_checklist(self, checklist):
        """Проверяет, может ли пользователь редактировать чек-лист"""
        if self.is_admin() or self.role == 'prompt_engineer':
            return True
        # Обычный пользователь может редактировать только свои чек-листы
        return checklist.user_id == self.id

    def can_view_application(self, application):
        """Проверяет, может ли пользователь просматривать заявку"""
        if self.is_admin() or self.is_prompt_engineer():
            return True
        return application.user_id == self.id

    def can_edit_application(self, application):
        """Проверяет, может ли пользователь редактировать заявку"""
        if self.is_admin() or self.is_prompt_engineer():
            return True
        return application.user_id == self.id

    def can_delete_application(self, application):
        """Проверяет, может ли пользователь удалять заявку"""
        # Админы и промпт-инженеры могут удалять любые заявки
        if self.is_admin() or self.is_prompt_engineer():
            return True
        # Обычные пользователи могут удалять только свои заявки
        return application.user_id == self.id

    def can_analyze_application(self, application):
        """Проверяет, может ли пользователь запускать анализ заявки"""
        if self.is_admin() or self.is_prompt_engineer():
            return True
        return application.user_id == self.id

    def get_accessible_applications(self):
        """Возвращает список заявок, доступных пользователю"""
        from app.models import Application

        if self.is_admin() or self.is_prompt_engineer():
            # Админы и промпт-инженеры видят все заявки
            return Application.query.order_by(Application.created_at.desc()).all()
        else:
            # Обычные пользователи видят только свои заявки
            return Application.query.filter_by(user_id=self.id).order_by(Application.created_at.desc()).all()

    def get_applications_count(self):
        """Возвращает количество заявок пользователя"""
        from app.models import Application

        if self.is_admin() or self.is_prompt_engineer():
            return Application.query.count()
        else:
            return Application.query.filter_by(user_id=self.id).count()

    def get_checklists_count(self):
        """Возвращает количество чек-листов пользователя"""
        from app.models import Checklist

        if self.is_admin() or self.is_prompt_engineer():
            return Checklist.query.count()
        else:
            return Checklist.query.filter_by(user_id=self.id).count()

    def can_view_all_applications(self):
        """Проверяет, может ли пользователь видеть все заявки"""
        return self.is_admin() or self.is_prompt_engineer()

    def can_view_all_checklists(self):
        """Проверяет, может ли пользователь видеть все чек-листы"""
        return self.is_admin() or self.is_prompt_engineer()

    def get_role_display(self):
        """Возвращает отображаемое название роли"""
        role_names = {
            'admin': 'Администратор',
            'prompt_engineer': 'Промпт-инженер',
            'user': 'Пользователь'
        }
        return role_names.get(self.role, self.role)

    def get_permissions_list(self):
        """Возвращает список разрешений пользователя"""
        permissions = []

        if self.role == 'admin':
            permissions = [
                'Полный доступ ко всем функциям системы',
                'Управление пользователями',
                'Управление LLM моделями',
                'Создание и редактирование всех чек-листов',
                'Просмотр и управление всеми заявками',
                'Доступ к системной статистике'
            ]
        elif self.role == 'prompt_engineer':
            permissions = [
                'Полный доступ ко всем функциям системы (кроме управления пользователями)',
                'Создание и редактирование всех чек-листов',
                'Управление LLM моделями',
                'Создание и управление всеми заявками',
                'Просмотр всех заявок и статистики'
            ]
        else:  # user
            permissions = [
                'Создание и редактирование своих чек-листов',
                'Просмотр только своих чек-листов',
                'Создание и управление своими заявками',
                'Семантический поиск'
            ]

        return permissions

    def get_restrictions_list(self):
        """Возвращает список ограничений пользователя"""
        restrictions = []

        if self.role == 'prompt_engineer':
            restrictions = ['Управление пользователями']
        elif self.role == 'user':
            restrictions = [
                'Редактирование чужих чек-листов',
                'Просмотр чужих заявок',
                'Управление пользователями',
                'Управление LLM моделями'
            ]

        return restrictions