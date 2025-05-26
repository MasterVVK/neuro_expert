from flask import jsonify, current_app
from app.blueprints.stats import bp
from app.services.fastapi_client import FastAPIClient
import logging

logger = logging.getLogger(__name__)


@bp.route('/system')
def system_stats():
    """Возвращает статистику системных ресурсов"""
    try:
        client = FastAPIClient()
        stats = client.get_system_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Ошибка при получении системной статистики: {str(e)}")
        return jsonify({
            "error": str(e),
            "cpu": {"percent": 0, "cores": 0, "threads": 0},
            "memory": {"percent": 0, "used_gb": 0, "total_gb": 0, "available_gb": 0},
            "gpu": {"name": "Ошибка", "vram_percent": 0, "vram_used_gb": 0, "vram_total_gb": 0, "temperature": None, "utilization": 0},
            "system": {"process_count": 0, "disk_percent": 0, "active_indexing_tasks": 0, "indexing_queue_size": 0}
        })