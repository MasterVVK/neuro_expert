import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from celery import Celery
from config import config

# Инициализация расширений
db = SQLAlchemy()
migrate = Migrate()
celery = Celery()

def create_app(config_name=None):
    """
    Фабрика для создания приложения Flask.
    
    Args:
        config_name: Имя конфигурации
        
    Returns:
        Flask: Приложение Flask
    """
    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG', 'default')
    
    app = Flask(__name__, instance_relative_config=True)
    
    # Загрузка конфигурации
    app.config.from_object(config[config_name])
    if hasattr(config[config_name], 'init_app'):
        config[config_name].init_app(app)
    app.config.from_pyfile('config.py', silent=True)
    
    # Инициализация расширений
    db.init_app(app)
    migrate.init_app(app, db)
    
    # Настройка Celery
    celery.conf.update(app.config['CELERY_CONFIG'])
    
    # Настройка логирования
    setup_logging(app)
    
    # Создание директории для загрузок
    uploads_path = os.path.join(app.root_path, app.config['UPLOAD_FOLDER'])
    os.makedirs(uploads_path, exist_ok=True)
    
    # Регистрация blueprint'ов
    register_blueprints(app)
    
    # Регистрация пользовательских фильтров
    register_template_filters(app)
    
    return app

def setup_logging(app):
    """Настройка логирования для приложения"""
    if not os.path.exists('logs'):
        os.mkdir('logs')
    
    # Настройка обработчиков
    file_handler = RotatingFileHandler('logs/app.log', maxBytes=10485760, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    
    # Применение настроек к логгеру приложения
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    
    app.logger.info('Приложение запущено')

def register_blueprints(app):
    """Регистрация blueprint'ов"""
    # Импорт здесь для избежания циклических зависимостей
    from app.blueprints.main import bp as main_bp
    from app.blueprints.applications import bp as applications_bp
    from app.blueprints.checklists import bp as checklists_bp
    from app.blueprints.llm_management import bp as llm_bp
    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.search import bp as search_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(checklists_bp)
    app.register_blueprint(llm_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(search_bp)


def register_template_filters(app):
    """Регистрация пользовательских фильтров для шаблонов"""
    
    @app.template_filter('nl2br')
    def nl2br_filter(s):
        """Заменяет переносы строк на HTML-тег <br>"""
        if not s:
            return ""
        return s.replace('\n', '<br>')
