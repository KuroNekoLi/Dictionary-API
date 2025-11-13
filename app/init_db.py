import sqlite3
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJECT_ROOT, "..", "data", "words.db")
DB_PATH = os.path.abspath(DB_PATH)  # 標準化絕對路徑

SCHEMA = """
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS pronunciations (
    word_id INTEGER,
    uk TEXT,
    us TEXT,
    FOREIGN KEY (word_id) REFERENCES words(id)
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER,
    part_of_speech TEXT,
    FOREIGN KEY (word_id) REFERENCES words(id)
);
CREATE TABLE IF NOT EXISTS definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER,
    en_definition TEXT,
    zh_definition TEXT,
    FOREIGN KEY (entry_id) REFERENCES entries(id)
);
CREATE TABLE IF NOT EXISTS examples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    definition_id INTEGER,
    example_text TEXT,
    FOREIGN KEY (definition_id) REFERENCES definitions(id)
);
"""

os.makedirs(os.path.join(PROJECT_ROOT, "..", "data"), exist_ok=True)

with sqlite3.connect(DB_PATH) as conn:
    cursor = conn.cursor()
    cursor.executescript(SCHEMA)
    conn.commit()

print(f"Initialized DB at {DB_PATH}")
