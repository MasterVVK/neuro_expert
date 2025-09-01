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

# Устанавливаем значения по умолчанию
QUEUES="celery"
WORKER_NAME="worker"
CONCURRENCY=2

# Активируем виртуальное окружение для чтения конфигурации
source "${VENV_PATH}/bin/activate"

# Читаем конфигурацию из celeryconfig.py (если возможно)
cd "$SCRIPT_DIR"
CONFIG_OUTPUT=$(${VENV_PATH}/bin/python3 -c "
try:
    import celeryconfig as c
    cfg = c.SERVICE_CONFIG
    print(f'QUEUES=\"{\",\".join(cfg[\"queues\"])}\"')
    print(f'WORKER_NAME=\"{cfg[\"worker_name\"]}\"')
    print(f'CONCURRENCY={cfg.get(\"concurrency\", 2)}')
    gpu = cfg.get('gpu_device')
    if gpu: print(f'export CUDA_VISIBLE_DEVICES={gpu}')
except Exception as e:
    import sys
    print(f'# Warning: Failed to read config: {e}', file=sys.stderr)
    print('# Using default values', file=sys.stderr)
" 2>&1)

# Применяем конфигурацию, если она была успешно прочитана
if [ $? -eq 0 ]; then
    eval "$CONFIG_OUTPUT"
else
    echo "Warning: Using default configuration"
    echo "$CONFIG_OUTPUT"
fi

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