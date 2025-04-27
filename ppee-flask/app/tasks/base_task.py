"""
Базовый класс для задач Celery с общими функциями для обработки прогресса и ошибок.
"""

import logging
from functools import wraps
from app import db
from app.models import Application

# Настройка логирования
logger = logging.getLogger(__name__)


class BaseTask:
    """Базовый класс для задач Celery с общими функциями"""

    @staticmethod
    def update_progress(task, progress, stage, message):
        """
        Обновляет прогресс выполнения задачи.

        Args:
            task: Экземпляр задачи Celery (self в методе задачи)
            progress: Процент выполнения (0-100)
            stage: Текущий этап выполнения (prepare, convert, split, index, analyze и т.д.)
            message: Сообщение о текущем статусе
        """
        task.update_state(
            state='PROGRESS',
            meta={
                'progress': progress,
                'stage': stage,
                'message': message
            }
        )
        logger.info(f"Прогресс {progress}%: [{stage}] {message}")

    @staticmethod
    def update_success(task, result=None):
        """
        Обновляет статус задачи на успешное завершение.

        Args:
            task: Экземпляр задачи Celery (self в методе задачи)
            result: Результат выполнения задачи (опционально)
        """
        meta = {
            'progress': 100,
            'stage': 'complete',
            'message': 'Задача успешно завершена'
        }

        # Если результат - словарь, добавляем в него мета-информацию
        if isinstance(result, dict):
            # Объединяем словари, result имеет приоритет
            combined_result = meta.copy()
            combined_result.update(result)
            result = combined_result
        else:
            # Если результат не словарь, используем только мета-информацию
            result = meta

        # ВАЖНО! Используем метод update_state вместо return для явного завершения
        # Это гарантирует, что статус SUCCESS будет отправлен в бэкенд результатов
        task.update_state(state='SUCCESS', meta=result)
        logger.info(f"Прогресс 100%: [complete] Задача успешно завершена")

        # Возвращаем результат, чтобы Celery сохранил его как результат задачи
        return result

    @staticmethod
    def handle_error(task, error, application_id=None):
        """
        Обрабатывает ошибку задачи, обновляя статус и логируя информацию.

        Args:
            task: Экземпляр задачи Celery (self в методе задачи)
            error: Объект исключения
            application_id: ID заявки (опционально)

        Returns:
            dict: Словарь с информацией об ошибке для возврата из задачи
        """
        error_msg = str(error)
        logger.exception(f"Ошибка в задаче: {error_msg}")

        # Обновляем статус задачи
        error_meta = {
            'status': 'error',
            'progress': 0,
            'stage': 'error',
            'message': f'Ошибка: {error_msg}'
        }

        # ВАЖНО! Используем метод update_state для явного завершения с ошибкой
        task.update_state(state='FAILURE', meta=error_meta)

        # Обновляем статус заявки в БД, если указан ID
        if application_id:
            try:
                application = Application.query.get(application_id)
                if application:
                    application.status = "error"
                    application.status_message = error_msg
                    db.session.commit()
                    logger.info(f"Статус заявки {application_id} обновлен на 'error'")
            except Exception as db_error:
                logger.error(f"Не удалось обновить статус заявки {application_id}: {str(db_error)}")

        # Возвращаем информацию об ошибке
        return error_meta

    @staticmethod
    def task_wrapper(func):
        """
        Декоратор для оборачивания задач Celery, добавляя обработку ошибок.

        Args:
            func: Функция задачи Celery

        Returns:
            function: Обернутая функция с обработкой ошибок
        """
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                # Получаем ID заявки из аргументов (если есть)
                application_id = kwargs.get('application_id')
                if not application_id and args:
                    application_id = args[0]  # Предполагаем, что первый аргумент - ID заявки

                # Начальный статус (если нужен)
                # Начальный статус указываем в самой задаче, чтобы избежать дублирования

                # Вызываем оригинальную функцию
                result = func(self, *args, **kwargs)

                # Явно устанавливаем финальный статус успеха и возвращаем результат
                return BaseTask.update_success(self, result)

            except Exception as e:
                # Обрабатываем ошибку и возвращаем информацию о ней
                return BaseTask.handle_error(self, e, application_id)

        return wrapper