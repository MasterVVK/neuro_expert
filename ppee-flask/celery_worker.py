import os
from app import create_app, celery

# Загружаем конфигурацию Celery из отдельного файла
celery.config_from_object('celeryconfig')

app = create_app(os.getenv('FLASK_CONFIG') or 'default')
app.app_context().push()