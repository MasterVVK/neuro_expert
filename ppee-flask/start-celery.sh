#!/bin/bash
# Скрипт для запуска Celery с конфигурацией из celeryconfig.py

# Определяем пути на основе текущей директории
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PATH="${PROJECT_DIR}/.venv"

# Проверяем наличие venv
if [ ! -d "$VENV_PATH" ]; then
    echo "Error: Virtual environment not found at $VENV_PATH"
    exit 1
fi

# Читаем конфигурацию из celeryconfig.py
cd "$SCRIPT_DIR"
eval $(python3 -c "
import celeryconfig as c
cfg = c.SERVICE_CONFIG
print(f'QUEUES=\"{\",\".join(cfg[\"queues\"])}\"')
print(f'WORKER_NAME=\"{cfg[\"worker_name\"]}\"')
print(f'CONCURRENCY={cfg.get(\"concurrency\", 2)}')
gpu = cfg.get('gpu_device')
if gpu: print(f'export CUDA_VISIBLE_DEVICES={gpu}')
")

# Устанавливаем пути
export PATH="${VENV_PATH}/bin:/usr/local/bin:/usr/bin:/bin"
export PYTHONPATH="${SCRIPT_DIR}:${PROJECT_DIR}"

# Запускаем Celery
exec ${VENV_PATH}/bin/celery -A celery_worker.celery worker \
    --loglevel=info \
    --max-tasks-per-child=1 \
    --queues=${QUEUES} \
    --hostname=${WORKER_NAME}@%h \
    --concurrency=${CONCURRENCY}