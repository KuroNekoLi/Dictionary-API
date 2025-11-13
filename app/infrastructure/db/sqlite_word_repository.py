import pathlib
import sqlite3
from typing import Optional, List

from app.domain.models.word import Word, Entry, Definition, Example, Pronunciations
from app.domain.repositories.word_repository import DictionaryRepository

# 專案根目錄（無論啟動目錄如何，保證指向正確路徑）
BASE = pathlib.Path(__file__).resolve().parent.parent.parent
DB_PATH = str(BASE.parent / "data" / "words.db")

class SqliteDictionaryRepository(DictionaryRepository):
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def get_word(self, word: str) -> Optional[Word]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM words WHERE word=?", (word,))
            word_row = cursor.fetchone()
            if word_row is None:
                return None
            word_id = word_row[0]

            cursor.execute("SELECT uk, us FROM pronunciations WHERE word_id=?", (word_id,))
            pron_row = cursor.fetchone()
            pron = Pronunciations(uk=pron_row[0], us=pron_row[1]) if pron_row else Pronunciations()

            cursor.execute("SELECT id, part_of_speech FROM entries WHERE word_id=?", (word_id,))
            entries = []
            for entry_id, part_of_speech in cursor.fetchall():
                cursor.execute("SELECT id, en_definition, zh_definition FROM definitions WHERE entry_id=?", (entry_id,))
                definitions = []
                for def_id, en_def, zh_def in cursor.fetchall():
                    cursor.execute("SELECT example_text FROM examples WHERE definition_id=?", (def_id,))
                    examples = [Example(example_text=row[0]) for row in cursor.fetchall()]
                    definitions.append(Definition(en_definition=en_def, zh_definition=zh_def, examples=examples))
                entries.append(Entry(part_of_speech=part_of_speech, definitions=definitions))
            return Word(word=word, pronunciations=pron, entries=entries)

    def save_word(self, word_obj: Word):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO words(word) VALUES (?)", (word_obj.word,))
            cursor.execute("SELECT id FROM words WHERE word=?", (word_obj.word,))
            word_id = cursor.fetchone()[0]
            cursor.execute("DELETE FROM pronunciations WHERE word_id=?", (word_id,))
            cursor.execute("INSERT INTO pronunciations(word_id, uk, us) VALUES (?, ?, ?)",
                           (word_id, word_obj.pronunciations.uk, word_obj.pronunciations.us))
            cursor.execute("DELETE FROM entries WHERE word_id=?", (word_id,))
            for entry in word_obj.entries:
                cursor.execute("INSERT INTO entries(word_id, part_of_speech) VALUES(?, ?)",
                               (word_id, entry.part_of_speech))
                entry_id = cursor.lastrowid
                for definition in entry.definitions:
                    cursor.execute("INSERT INTO definitions(entry_id, en_definition, zh_definition) VALUES (?, ?, ?)",
                                   (entry_id, definition.en_definition, definition.zh_definition))
                    def_id = cursor.lastrowid
                    for example in definition.examples:
                        cursor.execute("INSERT INTO examples(definition_id, example_text) VALUES (?, ?)",
                                       (def_id, example.example_text))
            conn.commit()

    def get_words(self, words: List[str]) -> List[Word]:
        return [w for w in (self.get_word(word) for word in words) if w]
