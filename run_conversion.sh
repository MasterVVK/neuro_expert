#!/bin/bash

# Путь к виртуальному окружению (измените при необходимости)
VENV_DIR="./.venv"

# Проверяем, существует ли виртуальное окружение
if [ ! -d "$VENV_DIR" ]; then
    echo "Виртуальное окружение не найдено по пути $VENV_DIR"
    exit 1
fi

# Активируем виртуальное окружение
source "$VENV_DIR/bin/activate"

# Устанавливаем переменные окружения для компилятора
export CC=/usr/bin/gcc-9
export CXX=/usr/bin/g++-9
export TORCH_CUDA_ARCH_LIST="8.6"  # Для RTX 3090

# Очищаем кэш сборки расширений PyTorch (опционально)
rm -rf ~/.cache/torch_extensions

# Запускаем ваш python-скрипт
python pdf_to_markdown.py "Очищенная ППЭЭ (с масками) итог.pdf"

# Деактивируем виртуальное окружение (если нужно)
deactivate
