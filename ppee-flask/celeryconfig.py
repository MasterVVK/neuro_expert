"""
Конфигурация Celery для проекта
"""
import os
from kombu import Queue

# === ГЛАВНАЯ НАСТРОЙКА - МЕНЯЙТЕ ТОЛЬКО ЭТО ===
PROJECT_NAME = 'neuro'  # Измените на имя вашего проекта
REDIS_DB = 0  # Используйте разные базы для разных проектов (0-15)

# === АВТОМАТИЧЕСКИ ГЕНЕРИРУЕМЫЕ НАСТРОЙКИ ===
QUEUE_NAME = f'{PROJECT_NAME}_queue'
WORKER_NAME = f'{PROJECT_NAME}_worker'

# === НАСТРОЙКИ ДЛЯ SYSTEMD СЕРВИСА ===
SERVICE_CONFIG = {
    'worker_name': WORKER_NAME,
    'queues': [QUEUE_NAME, 'celery'],  # celery для обратной совместимости
    'concurrency': 2,
    'gpu_device': None,  # Установите '0' или '1' для ограничения GPU
}

# === НАСТРОЙКИ CELERY ===
# Основные настройки брокера
broker_url = f'redis://localhost:6379/{REDIS_DB}'
result_backend = f'redis://localhost:6379/{REDIS_DB}'

# Очередь по умолчанию для этого проекта
task_default_queue = QUEUE_NAME

# Определение очередей
task_queues = (
    Queue(QUEUE_NAME),
    Queue('celery'),  # Для обратной совместимости
)

# Маршрутизация задач
task_routes = {
    'app.tasks.*': {'queue': QUEUE_NAME},
}

# Настройки сериализации
task_serializer = 'json'
accept_content = ['json']
result_serializer = 'json'
timezone = 'UTC'
enable_utc = True

# Настройки производительности
task_acks_late = True
worker_prefetch_multiplier = 1
task_reject_on_worker_lost = True

# Время жизни результатов
result_expires = 3600

# Настройки для избежания утечек памяти при работе с GPU
worker_max_tasks_per_child = 1