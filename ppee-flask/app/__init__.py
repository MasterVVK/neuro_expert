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
    from app.blueprints.stats import bp as stats_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(checklists_bp)
    app.register_blueprint(llm_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(stats_bp)


def register_template_filters(app):
    """Регистрация пользовательских фильтров для шаблонов"""

    @app.template_filter('nl2br')
    def nl2br_filter(s):
        """Заменяет переносы строк на HTML-тег <br>"""
        if not s:
            return ""
        return s.replace('\n', '<br>')

    @app.template_filter('to_moscow_time')
    def to_moscow_time_filter(dt):
        """Конвертирует UTC время в московское"""
        if dt:
            from pytz import timezone
            utc = timezone('UTC')
            moscow = timezone('Europe/Moscow')
            # Если datetime не имеет информации о часовом поясе, считаем что это UTC
            if dt.tzinfo is None:
                dt = utc.localize(dt)
            return dt.astimezone(moscow)
        return dt

    @app.template_filter('strftime')
    def strftime_filter(dt, format='%d.%m.%Y %H:%M'):
        """Форматирует datetime объект в строку"""
        if dt:
            return dt.strftime(format)
        return ''

    @app.template_filter('format_datetime')
    def format_datetime_filter(dt, format='%d.%m.%Y %H:%M', timezone='Europe/Moscow', show_tz=True):
        """
        Универсальный фильтр для форматирования даты/времени

        Args:
            dt: datetime объект
            format: формат вывода
            timezone: целевой часовой пояс
            show_tz: показывать ли аббревиатуру часового пояса
        """
        if not dt:
            return ''

        from pytz import timezone as tz

        # Конвертируем в нужный часовой пояс
        utc = tz('UTC')
        target_tz = tz(timezone)

        if dt.tzinfo is None:
            dt = utc.localize(dt)

        dt_converted = dt.astimezone(target_tz)

        # Форматируем
        result = dt_converted.strftime(format)

        # Добавляем часовой пояс если нужно
        if show_tz:
            tz_abbr = dt_converted.strftime('%Z')  # Получаем аббревиатуру (MSK, MSD и т.д.)
            result += f' {tz_abbr}'

        return result

    @app.template_filter('time_ago')
    def time_ago_filter(dt, timezone='Europe/Moscow'):
        """
        Показывает, сколько времени прошло с момента события
        Например: "5 минут назад", "2 часа назад", "вчера"
        """
        if not dt:
            return ''

        from datetime import datetime
        from pytz import timezone as tz

        # Конвертируем в московское время для правильного расчета
        utc = tz('UTC')
        moscow = tz(timezone)

        if dt.tzinfo is None:
            dt = utc.localize(dt)

        dt_moscow = dt.astimezone(moscow)
        now_moscow = datetime.now(moscow)

        diff = now_moscow - dt_moscow

        seconds = diff.total_seconds()

        if seconds < 60:
            return 'только что'
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f'{minutes} мин. назад'
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f'{hours} ч. назад'
        elif seconds < 172800:
            return 'вчера'
        else:
            days = int(seconds / 86400)
            if days < 7:
                return f'{days} дн. назад'
            elif days < 30:
                weeks = int(days / 7)
                return f'{weeks} нед. назад'
            else:
                return dt_moscow.strftime('%d.%m.%Y')

    @app.template_filter('format_page_ranges')
    def format_page_ranges_filter(pages):
        """
        Форматирует список страниц в диапазоны
        Например: [2, 3, 4, 6, 7, 8, 10, 11, 12] -> "2-4, 6-8, 10-12"
        """
        if not pages:
            return ''

        # Собираем все номера страниц
        nums = []

        # Если это список строк вида ['10,11,12', '6,7,8', '2,3,4']
        if isinstance(pages, list):
            for item in pages:
                if isinstance(item, str):
                    # Разбиваем строку по запятым
                    for p in item.split(','):
                        p = p.strip()
                        if p.isdigit():
                            nums.append(int(p))
                elif isinstance(item, (int, float)):
                    nums.append(int(item))
        # Если это строка
        elif isinstance(pages, str):
            for p in pages.split(','):
                p = p.strip()
                if p.isdigit():
                    nums.append(int(p))

        if not nums:
            return ', '.join(str(p) for p in pages)

        # Убираем дубликаты и сортируем
        nums = sorted(set(nums))

        # Группируем в диапазоны
        ranges = []
        start = nums[0]
        end = nums[0]

        for num in nums[1:]:
            if num == end + 1:
                end = num
            else:
                # Добавляем предыдущий диапазон
                if start == end:
                    ranges.append(str(start))
                else:
                    ranges.append(f"{start}-{end}")
                start = num
                end = num

        # Добавляем последний диапазон
        if start == end:
            ranges.append(str(start))
        else:
            ranges.append(f"{start}-{end}")

        return ', '.join(ranges)

    # Отладочный вывод для проверки регистрации фильтров
    app.logger.info("Зарегистрированные фильтры:")
    for name in app.jinja_env.filters:
        if name in ['nl2br', 'to_moscow_time', 'strftime', 'format_datetime', 'time_ago', 'format_page_ranges']:
            app.logger.info(f"  - {name}")