#!/usr/bin/env python3
"""
Скрипт для добавления поля is_public в таблицу checklists
Использовать при проблемах с миграциями Alembic
"""
import sqlite3
import sys
import os

def find_database():
    """Поиск базы данных SQLite"""
    possible_paths = [
        "instance/app.db",
        "app.db",
        "/srv/neuro_expert/ppee-flask/instance/app.db",
        "/srv/neuro_expert/ppee-flask/app.db",
        "/srv/neuro_expert/app.db"
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    print("❌ База данных не найдена. Проверьте пути:")
    for path in possible_paths:
        print(f"  {path}")
    return None

def check_and_add_column():
    """Проверка и добавление колонки is_public"""
    db_path = find_database()
    if not db_path:
        sys.exit(1)
    
    print(f"✅ Найдена база данных: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Проверяем структуру таблицы
        cursor.execute("PRAGMA table_info(checklists);")
        columns = cursor.fetchall()
        column_names = [column[1] for column in columns]
        
        print("\nСуществующие колонки в таблице checklists:")
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
        
        # Проверяем наличие is_public
        if 'is_public' not in column_names:
            print("\n🔧 Колонка is_public не найдена. Добавляем...")
            cursor.execute("ALTER TABLE checklists ADD COLUMN is_public BOOLEAN DEFAULT 0 NOT NULL;")
            conn.commit()
            print("✅ Колонка is_public успешно добавлена!")
            
            # Проверяем результат
            cursor.execute("PRAGMA table_info(checklists);")
            new_columns = cursor.fetchall()
            print("\nОбновленная структура таблицы:")
            for col in new_columns:
                if col[1] == 'is_public':
                    print(f"  ✅ {col[1]} ({col[2]}) - ДОБАВЛЕНА")
                else:
                    print(f"  - {col[1]} ({col[2]})")
        else:
            print("\n✅ Колонка is_public уже существует!")
        
        conn.close()
        print("\n🎉 Скрипт выполнен успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка при работе с базой данных: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("=== Исправление базы данных ===")
    print("Добавление поля is_public в таблицу checklists")
    print()
    
    check_and_add_column()