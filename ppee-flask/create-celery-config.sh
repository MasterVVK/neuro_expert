#!/bin/bash
# Скрипт для создания celeryconfig.py для нового проекта

if [ $# -lt 2 ]; then
    echo "Usage: $0 <project_name> <redis_db> [gpu_device]"
    echo "Example: $0 myproject 3"
    echo "Example: $0 myproject 3 0  # с GPU device 0"
    exit 1
fi

PROJECT_NAME=$1
REDIS_DB=$2
GPU_DEVICE=${3:-None}

# Если указан GPU, добавляем кавычки
if [ "$GPU_DEVICE" != "None" ]; then
    GPU_DEVICE="'$GPU_DEVICE'"
fi

cat > celeryconfig.py <<EOF
"""
Конфигурация Celery для проекта ${PROJECT_NAME}
Автоматически сгенерировано $(date)
"""
import os
from kombu import Queue

# === ГЛАВНАЯ НАСТРОЙКА ===
PROJECT_NAME = '${PROJECT_NAME}'
REDIS_DB = ${REDIS_DB}

# === АВТОМАТИЧЕСКИ ГЕНЕРИРУЕМЫЕ НАСТРОЙКИ ===
QUEUE_NAME = f'{PROJECT_NAME}_queue'
WORKER_NAME = f'{PROJECT_NAME}_worker'

# === НАСТРОЙКИ ДЛЯ SYSTEMD СЕРВИСА ===
SERVICE_CONFIG = {
    'worker_name': WORKER_NAME,
    'queues': [QUEUE_NAME],
    'concurrency': 2,
    'gpu_device': ${GPU_DEVICE},
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
EOF

echo "Created celeryconfig.py for project '${PROJECT_NAME}'"
echo "Settings:"
echo "  - Queue name: ${PROJECT_NAME}_queue"
echo "  - Worker name: ${PROJECT_NAME}_worker"
echo "  - Redis DB: ${REDIS_DB}"
echo "  - GPU device: ${GPU_DEVICE}"