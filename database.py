# database.py
import sqlite3
from config import DB_NAME

def init_db():
    """Инициализация базы данных и создание таблиц"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. Таблица студентов (уже включает новое поле daily_questions_count)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            telegram_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            timezone TEXT DEFAULT 'America/Argentina/Buenos_Aires',
            current_streak INTEGER DEFAULT 0,
            last_activity DATE,
            is_active BOOLEAN DEFAULT 1,
            daily_questions_count INTEGER DEFAULT 2
        )
    ''')

    # Безопасное добавление колонки, если база была создана ранее
    try:
        cursor.execute("ALTER TABLE students ADD COLUMN daily_questions_count INTEGER DEFAULT 2")
    except sqlite3.OperationalError:
        pass  # Колонка уже существует

    # 2. Таблица тем
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            tag TEXT UNIQUE NOT NULL,
            image_url TEXT
        )
    ''')

    # 3. Связь Студент <-> Темы
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS student_topics (
            student_id INTEGER,
            topic_id INTEGER,
            is_enabled BOOLEAN DEFAULT 0,
            PRIMARY KEY (student_id, topic_id),
            FOREIGN KEY (student_id) REFERENCES students(telegram_id) ON DELETE CASCADE,
            FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
        )
    ''')

    # 4. Пул заданий
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_tag TEXT,
            task_type TEXT CHECK(task_type IN ('test', 'creative')),
            question_text TEXT NOT NULL,
            options TEXT,
            correct_answer TEXT,
            explanation TEXT,
            FOREIGN KEY (topic_tag) REFERENCES topics(tag)
        )
    ''')

    # 5. Таблица ошибок
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS error_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            question_text TEXT,
            wrong_answer TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()

def add_test_topic(name: str, tag: str, image_url: str = None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO topics (name, tag, image_url) VALUES (?, ?, ?)", (name, tag, image_url))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()

def add_test_task(topic_tag: str, task_type: str, question: str, options: str = None, correct: str = None, exp: str = None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO tasks (topic_tag, task_type, question_text, options, correct_answer, explanation)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (topic_tag, task_type, question, options, correct, exp))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("База данных успешно обновлена и инициализирована!")