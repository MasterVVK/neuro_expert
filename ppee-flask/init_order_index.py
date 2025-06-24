#!/usr/bin/env python
"""
Скрипт для инициализации order_index для существующих параметров чек-листов
"""

from app import create_app, db
from app.models import Checklist, ChecklistParameter

def init_order_index():
    """Инициализирует order_index для всех существующих параметров"""
    app = create_app()

    with app.app_context():
        # Получаем все чек-листы
        checklists = Checklist.query.all()

        for checklist in checklists:
            print(f"Обработка чек-листа: {checklist.name} (ID: {checklist.id})")

            # Получаем все параметры чек-листа, отсортированные по id
            parameters = ChecklistParameter.query.filter_by(
                checklist_id=checklist.id
            ).order_by(ChecklistParameter.id).all()

            # Присваиваем order_index каждому параметру
            for index, param in enumerate(parameters):
                if param.order_index is None or param.order_index != index:
                    param.order_index = index
                    print(f"  - Параметр '{param.name}' (ID: {param.id}): order_index = {index}")

        # Сохраняем изменения
        db.session.commit()
        print("Инициализация order_index завершена!")


if __name__ == '__main__':
    init_order_index()