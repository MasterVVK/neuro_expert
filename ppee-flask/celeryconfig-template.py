"""
Шаблон конфигурации Celery
Скопируйте этот файл как celeryconfig.py и измените PROJECT_NAME и REDIS_DB
"""
import os
from kombu import Queue

# === ГЛАВНАЯ НАСТРОЙКА - МЕНЯЙТЕ ТОЛЬКО ЭТО ===
PROJECT_NAME = 'myproject'  # Измените на имя вашего проекта
REDIS_DB = 2  # Используйте разные базы для разных проектов (0-15)
GPU_DEVICE = None  # Установите '0', '1' и т.д. для ограничения GPU

# === АВТОМАТИЧЕСКИ ГЕНЕРИРУЕМЫЕ НАСТРОЙКИ ===
QUEUE_NAME = f'{PROJECT_NAME}_queue'
WORKER_NAME = f'{PROJECT_NAME}_worker'

# === НАСТРОЙКИ ДЛЯ SYSTEMD СЕРВИСА ===
SERVICE_CONFIG = {
    'worker_name': WORKER_NAME,
    'queues': [QUEUE_NAME],  # Добавьте 'celery' если нужна совместимость
    'concurrency': 2,
    'gpu_device': GPU_DEVICE,
}

# === НАСТРОЙКИ CELERY ===
broker_url = f'redis://localhost:6379/{REDIS_DB}'
result_backend = f'redis://localhost:6379/{REDIS_DB}'
task_default_queue = QUEUE_NAME

task_queues = (
    Queue(QUEUE_NAME),
)

task_routes = {
    'app.tasks.*': {'queue': QUEUE_NAME},
}

# Стандартные настройки
task_serializer = 'json'
accept_content = ['json']
result_serializer = 'json'
timezone = 'UTC'
enable_utc = True
task_acks_late = True
worker_prefetch_multiplier = 1
task_reject_on_worker_lost = True
result_expires = 3600
worker_max_tasks_per_child = 1