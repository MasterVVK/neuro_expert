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