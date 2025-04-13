from app import create_app, db
from app.models import User, Checklist

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
            
            # Создаем тестовый чек-лист
            checklist = Checklist(name='Базовый чек-лист', description='Чек-лист для проверки документов ППЭЭ')
            db.session.add(checklist)
            
            db.session.commit()
            print("База данных инициализирована с тестовыми данными")
        else:
            print("База данных уже инициализирована")

if __name__ == '__main__':
    init_db()
