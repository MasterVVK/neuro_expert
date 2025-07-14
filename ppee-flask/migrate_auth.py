"""
Скрипт прямой миграции для добавления user_id в таблицы
Используется вместо Alembic миграций при проблемах с SQLite
"""

from app import create_app, db
from app.models import User
from sqlalchemy import text
import sys


def check_column_exists(connection, table_name, column_name):
    """Проверяет существование колонки в таблице"""
    result = connection.execute(text(f"PRAGMA table_info({table_name})"))
    columns = [row[1] for row in result]
    return column_name in columns


def add_user_id_column(connection, table_name):
    """Добавляет колонку user_id в таблицу"""
    try:
        # Для SQLite нельзя добавить внешний ключ к существующей таблице
        # Поэтому просто добавляем колонку
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN user_id INTEGER"))
        print(f"✓ Колонка user_id добавлена в таблицу {table_name}")
        return True
    except Exception as e:
        if "duplicate column name" in str(e).lower():
            print(f"! Колонка user_id уже существует в таблице {table_name}")
            return False
        else:
            print(f"✗ Ошибка при добавлении колонки в {table_name}: {e}")
            raise


def update_existing_records(connection, table_name, admin_id):
    """Обновляет существующие записи, привязывая их к администратору"""
    try:
        result = connection.execute(text(f"UPDATE {table_name} SET user_id = :admin_id WHERE user_id IS NULL"),
                                    {"admin_id": admin_id})
        updated_count = result.rowcount
        if updated_count > 0:
            print(f"✓ Обновлено {updated_count} записей в таблице {table_name}")
        return True
    except Exception as e:
        print(f"✗ Ошибка при обновлении записей в {table_name}: {e}")
        return False


def update_user_roles(connection):
    """Обновляет роли manager на prompt_engineer"""
    try:
        result = connection.execute(text("UPDATE users SET role = 'prompt_engineer' WHERE role = 'manager'"))
        updated_count = result.rowcount
        if updated_count > 0:
            print(f"✓ Обновлено {updated_count} пользователей с роли manager на prompt_engineer")
        else:
            print("! Не найдено пользователей с ролью manager")
        return True
    except Exception as e:
        print(f"✗ Ошибка при обновлении ролей: {e}")
        return False


def migrate():
    """Выполняет миграцию"""
    app = create_app()

    with app.app_context():
        # Получаем соединение с БД
        connection = db.engine.connect()
        trans = connection.begin()

        try:
            print("=== Начало миграции ===\n")

            # 1. Получаем ID администратора
            result = connection.execute(text("SELECT id FROM users WHERE role = 'admin' LIMIT 1"))
            admin = result.fetchone()

            if not admin:
                print("✗ ОШИБКА: Администратор не найден в базе данных!")
                print("  Сначала выполните: python initialize_db.py")
                trans.rollback()
                return False

            admin_id = admin[0]
            print(f"✓ Найден администратор с ID: {admin_id}\n")

            # 2. Добавляем user_id в applications
            print("Обработка таблицы applications:")
            if not check_column_exists(connection, 'applications', 'user_id'):
                add_user_id_column(connection, 'applications')
                update_existing_records(connection, 'applications', admin_id)
            else:
                print("! Колонка user_id уже существует")

            print()

            # 3. Добавляем user_id в checklists
            print("Обработка таблицы checklists:")
            if not check_column_exists(connection, 'checklists', 'user_id'):
                add_user_id_column(connection, 'checklists')
                update_existing_records(connection, 'checklists', admin_id)
            else:
                print("! Колонка user_id уже существует")

            print()

            # 4. Обновляем роли пользователей
            print("Обновление ролей пользователей:")
            update_user_roles(connection)

            # Коммитим транзакцию
            trans.commit()
            print("\n=== Миграция успешно завершена! ===")

            # Обновляем версию миграции в alembic_version чтобы пропустить проблемную миграцию
            try:
                connection.execute(text("UPDATE alembic_version SET version_num = '58f23f242b4e'"))
                print("\n✓ Версия миграции обновлена в alembic_version")
            except:
                print("\n! Не удалось обновить версию в alembic_version (возможно, таблица не существует)")

            return True

        except Exception as e:
            trans.rollback()
            print(f"\n✗ ОШИБКА во время миграции: {e}")
            return False
        finally:
            connection.close()


if __name__ == '__main__':
    print("Скрипт прямой миграции базы данных")
    print("==================================\n")

    if migrate():
        print("\nТеперь вы можете запустить приложение: python wsgi.py")
    else:
        print("\nМиграция завершилась с ошибками!")
        sys.exit(1)