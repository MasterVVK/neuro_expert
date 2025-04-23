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
        'task_eager_propagates': False  # Также устанавливаем в False
    }

    # Qdrant
    QDRANT_HOST = os.environ.get('QDRANT_HOST') or 'localhost'
    QDRANT_PORT = int(os.environ.get('QDRANT_PORT') or 6333)
    QDRANT_COLLECTION = os.environ.get('QDRANT_COLLECTION') or 'ppee_applications'

    # LLM
    OLLAMA_URL = os.environ.get('OLLAMA_URL') or 'http://localhost:11434'
    DEFAULT_LLM_MODEL = os.environ.get('DEFAULT_LLM_MODEL') or 'gemma3:27b'

    # Upload
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or 'uploads'
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB

    # Semantic Chunking
    USE_SEMANTIC_CHUNKING = os.environ.get('USE_SEMANTIC_CHUNKING', '1') == '1'
    USE_GPU_FOR_CHUNKING = os.environ.get('USE_GPU_FOR_CHUNKING', '1') == '1'


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