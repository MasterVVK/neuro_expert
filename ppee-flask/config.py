import os
from datetime import timedelta


class Config:
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-not-for-production'
    FLASK_APP = os.environ.get('FLASK_APP') or 'wsgi.py'
    FLASK_ENV = os.environ.get('FLASK_ENV') or 'development'

    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Celery
    # Redis для Celery
    CELERY_BROKER_URL = 'redis://localhost:6379/0'
    CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
    CELERY_CONFIG = {
        'broker_url': CELERY_BROKER_URL,
        'result_backend': CELERY_RESULT_BACKEND,
        'task_serializer': 'json',
        'accept_content': ['json'],
        'result_serializer': 'json',
        'enable_utc': True,
        'task_always_eager': False,  # Важно! Установите в False для асинхронного режима
        'result_expires': 3600,
        'task_eager_propagates': False  # Также устанавливаем в False
    }

    # Qdrant
    QDRANT_HOST = os.environ.get('QDRANT_HOST') or 'localhost'
    QDRANT_PORT = int(os.environ.get('QDRANT_PORT') or 6333)
    QDRANT_COLLECTION = os.environ.get('QDRANT_COLLECTION') or 'ppee_applications'

    # LLM
    OLLAMA_URL = os.environ.get('OLLAMA_URL') or 'http://localhost:11434'
    DEFAULT_LLM_MODEL = os.environ.get('DEFAULT_LLM_MODEL') or 'gemma3:27b'

# Универсальный шаблон промпта по умолчанию для LLM
    DEFAULT_LLM_PROMPT_TEMPLATE = """Ты эксперт по извлечению информации из документов.

ЗАДАЧА: Найти точное значение для параметра "{query}"

ИНСТРУКЦИИ:
1. Внимательно изучи предоставленные фрагменты документов
2. Найди ТОЧНОЕ значение для запрашиваемого параметра
3. Если значение встречается несколько раз - выбери наиболее полное и актуальное
4. В таблицах правильно сопоставляй строки и столбцы
5. Используй ТОЛЬКО информацию из предоставленных документов

ФОРМАТ ОТВЕТА:
- Отвечай СТРОГО в формате: {query}: найденное значение
- НЕ добавляй пояснения или комментарии
- Если информация не найдена: {query}: Информация не найдена

ПАРАМЕТР ДЛЯ ПОИСКА: "{query}"

ДОКУМЕНТЫ:
{context}"""

    # Upload
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or 'uploads'
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB

    # Semantic Chunking
    USE_SEMANTIC_CHUNKING = os.environ.get('USE_SEMANTIC_CHUNKING', '1') == '1'
    USE_GPU_FOR_CHUNKING = os.environ.get('USE_GPU_FOR_CHUNKING', '1') == '1'

    # FastAPI сервис
    FASTAPI_URL = os.environ.get('FASTAPI_URL') or 'http://localhost:8001'

    DEFAULT_LLM_MODEL = os.environ.get('DEFAULT_LLM_MODEL') or 'gemma3:27b-it-qat'

class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    DEBUG = False

    @classmethod
    def init_app(cls, app):
        assert os.environ.get('SECRET_KEY'), 'SECRET_KEY must be set for production'


config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
