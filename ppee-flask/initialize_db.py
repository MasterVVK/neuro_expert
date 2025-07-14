from app import create_app, db
from app.models import User, Checklist, ChecklistParameter


def init_db():
    """Инициализирует базу данных"""
    app = create_app()
    with app.app_context():
        # Создаем таблицы
        db.create_all()

        # Создаем администратора, если он не существует
        if User.query.filter_by(username='admin').first() is None:
            admin = User(username='admin', email='admin@example.com', role='admin')
            admin.set_password('admin')
            db.session.add(admin)
            db.session.commit()  # Сохраняем изменения перед созданием чек-листа

            # Получаем модель по умолчанию из конфигурации
            default_llm_model = app.config.get('DEFAULT_LLM_MODEL', 'gemma3:27b')

            # Получаем шаблон промпта из конфигурации
            default_prompt = app.config.get('DEFAULT_LLM_PROMPT_TEMPLATE')

            # Если в конфигурации нет, используем захардкоженный fallback
            if not default_prompt:
                default_prompt = '''Ты эксперт по поиску информации в документах.

Нужно найти значение для параметра: "{query}"

Найденные результаты:
{context}

Твоя задача - извлечь точное значение для параметра "{query}" из предоставленных документов.

Правила:
1. Если значение найдено в нескольких местах, выбери наиболее полное и точное.
2. Если значение в таблице, внимательно определи соответствие между строкой и нужным столбцом.
3. Не добавляй никаких комментариев или пояснений - только параметр и его значение.
4. Значение должно содержать данные, которые есть в документах.
5. Если параметр не найден, укажи: "Информация не найдена".

Ответь одной строкой в указанном формате:
{query}: [значение]'''

            # Создаем тестовый чек-лист
            checklist = Checklist(
                name='Базовый чек-лист',
                description='Чек-лист для проверки документов ППЭЭ',
                user_id=admin.id  # Привязываем к администратору
            )
            db.session.add(checklist)
            db.session.commit()  # Сохраняем чек-лист для получения ID

            print(f"Создан чек-лист с ID: {checklist.id}")

            # Добавляем несколько базовых параметров
            params = [
                {
                    'name': 'Полное наименование юридического лица',
                    'search_query': 'полное наименование юридического лица',
                    'llm_model': default_llm_model,
                    'llm_prompt_template': default_prompt,
                    'llm_temperature': 0.1,
                    'llm_max_tokens': 1000
                },
                {
                    'name': 'ИНН организации',
                    'search_query': 'ИНН организации',
                    'llm_model': default_llm_model,
                    'llm_prompt_template': default_prompt,
                    'llm_temperature': 0.1,
                    'llm_max_tokens': 1000
                },
                {
                    'name': 'ОГРН организации',
                    'search_query': 'ОГРН организации',
                    'llm_model': default_llm_model,
                    'llm_prompt_template': default_prompt,
                    'llm_temperature': 0.1,
                    'llm_max_tokens': 1000
                }
            ]

            for param_data in params:
                param = ChecklistParameter(
                    checklist_id=checklist.id,  # Используем ID сохраненного чек-листа
                    name=param_data['name'],
                    search_query=param_data['search_query'],
                    llm_model=param_data['llm_model'],
                    llm_prompt_template=param_data['llm_prompt_template'],
                    llm_temperature=param_data['llm_temperature'],
                    llm_max_tokens=param_data['llm_max_tokens']
                )
                db.session.add(param)
                print(f"Добавлен параметр: {param_data['name']} для чек-листа ID: {checklist.id}")

            db.session.commit()
            print("База данных инициализирована с тестовыми данными")
        else:
            print("База данных уже инициализирована")

        # Обновляем роли manager на prompt_engineer если есть
        updated_count = User.query.filter_by(role='manager').update({'role': 'prompt_engineer'})
        if updated_count > 0:
            db.session.commit()
            print(f"Обновлено {updated_count} пользователей с роли manager на prompt_engineer")


if __name__ == '__main__':
    init_db()