import requests
import logging
from typing import Dict, Any, List, Optional
from flask import current_app

logger = logging.getLogger(__name__)


class FastAPIClient:
    """Клиент для работы с FastAPI сервисом"""

    def __init__(self, base_url: str = None):
        self.base_url = base_url or current_app.config.get('FASTAPI_URL', 'http://localhost:8001')

    def get_application_stats(self, application_id: str) -> Dict[str, Any]:
        """Получает статистику по заявке"""
        try:
            response = requests.get(f"{self.base_url}/applications/{application_id}/stats")
            response.raise_for_status()
            return response.json()["stats"]
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            raise

    def get_application_chunks(self, application_id: str, limit: int = 500) -> List[Dict[str, Any]]:
        """Получает чанки заявки"""
        try:
            response = requests.get(
                f"{self.base_url}/applications/{application_id}/chunks",
                params={"limit": limit}
            )
            response.raise_for_status()
            return response.json()["chunks"]
        except Exception as e:
            logger.error(f"Ошибка получения чанков: {e}")
            raise

    def delete_application_data(self, application_id: str) -> bool:
        """Удаляет данные заявки из векторного хранилища"""
        try:
            response = requests.delete(f"{self.base_url}/applications/{application_id}")
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Ошибка удаления данных заявки: {e}")
            return False

    def delete_document_chunks(self, application_id: str, document_id: str) -> int:
        """Удаляет чанки конкретного документа из векторного хранилища"""
        try:
            response = requests.delete(
                f"{self.base_url}/applications/{application_id}/documents/{document_id}"
            )
            response.raise_for_status()
            result = response.json()
            return result.get('deleted_count', 0)
        except Exception as e:
            logger.error(f"Ошибка удаления чанков документа: {e}")
            raise

    def search(self, application_id: str, query: str, **kwargs) -> List[Dict[str, Any]]:
        """Выполняет поиск"""
        try:
            response = requests.post(f"{self.base_url}/search", json={
                "application_id": application_id,
                "query": query,
                **kwargs
            })
            response.raise_for_status()
            return response.json()["results"]
        except Exception as e:
            logger.error(f"Ошибка поиска: {e}")
            raise

    def index_document(self, task_id: str, application_id: str, document_path: str, delete_existing: bool = False):
        """Запускает индексацию документа"""
        try:
            response = requests.post(f"{self.base_url}/index", json={
                "task_id": task_id,
                "application_id": application_id,
                "document_path": document_path,
                "delete_existing": delete_existing
            })
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка запуска индексации: {e}")
            raise

    def analyze_application(self, task_id: str, application_id: str, checklist_items: List[Dict], llm_params: Dict):
        """Запускает анализ заявки"""
        try:
            response = requests.post(f"{self.base_url}/analyze", json={
                "task_id": task_id,
                "application_id": application_id,
                "checklist_items": checklist_items,
                "llm_params": llm_params
            })
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка запуска анализа: {e}")
            raise

    def get_llm_models(self) -> List[str]:
        """Получает список доступных LLM моделей"""
        try:
            response = requests.get(f"{self.base_url}/llm/models")
            response.raise_for_status()
            return response.json()["models"]
        except Exception as e:
            logger.error(f"Ошибка получения моделей: {e}")
            return []

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Получает статус задачи"""
        try:
            response = requests.get(f"{self.base_url}/tasks/{task_id}/status")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка получения статуса задачи: {e}")
            raise

    def get_task_results(self, task_id: str) -> Dict[str, Any]:
        """Получает результаты выполненной задачи"""
        try:
            response = requests.get(f"{self.base_url}/tasks/{task_id}/results")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка получения результатов задачи: {e}")
            raise

        # Добавьте этот метод в класс FastAPIClient в файле app/services/fastapi_client.py

    def get_system_stats(self) -> Dict[str, Any]:
        """Получает статистику использования системных ресурсов"""
        try:
            response = requests.get(f"{self.base_url}/api/v1/system/stats", timeout=2)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка получения системной статистики: {e}")
            # Возвращаем значения по умолчанию при ошибке
            return {
                "cpu": {"percent": 0, "cores": 0, "threads": 0},
                "memory": {"percent": 0, "used_gb": 0, "total_gb": 0, "available_gb": 0},
                "gpu": {"name": "Недоступно", "vram_percent": 0, "vram_used_gb": 0, "vram_total_gb": 0,
                        "temperature": None, "utilization": 0},
                "system": {"process_count": 0, "disk_percent": 0, "active_indexing_tasks": 0,
                           "indexing_queue_size": 0}
            }