import json
import sqlite3
import zlib
from contextlib import closing
from pathlib import Path

from app.domain.models.word import Definition, Entry, Example, Pronunciations, Word

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "wordnet.db"
POS = {
    "n": "noun", "v": "verb", "a": "adjective", "s": "adjective", "r": "adverb",
    "int": "interjection", "prep": "preposition", "det": "determiner",
    "pron": "pronoun", "conj": "conjunction", "num": "numeral", "phr": "phrase",
}


class WordnetRepository:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path.resolve()

    def get_word(self, word: str) -> Word | None:
        if not self.db_path.is_file():
            return None
        word = word.strip().casefold()
        with closing(sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True)) as conn:
            has_atlas_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'word_atlas'"
            ).fetchone()
            atlas_row = (
                conn.execute("SELECT data FROM word_atlas WHERE word = ?", (word,)).fetchone()
                if has_atlas_table else None
            )
            word_atlas = json.loads(atlas_row[0]) if atlas_row else None
            has_complete_dictionary_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'complete_dictionary'"
            ).fetchone()
            complete_dictionary_row = (
                conn.execute(
                    "SELECT data FROM complete_dictionary WHERE word = ?", (word,)
                ).fetchone()
                if has_complete_dictionary_table else None
            )
            if complete_dictionary_row:
                payload = complete_dictionary_row[0]
                if isinstance(payload, bytes):
                    payload = zlib.decompress(payload).decode("utf-8")
                complete_dictionary = json.loads(payload)
            else:
                complete_dictionary = None
            senses = conn.execute(
                """SELECT synset, pos, en, zh FROM senses WHERE word = ?
                   ORDER BY frequency DESC, sense_number, synset""",
                (word,),
            ).fetchall()
            examples = conn.execute(
                """SELECT synset, text, source, author, source_url, license_url, match_type
                   FROM examples WHERE word = ? ORDER BY priority, length(text), text""",
                (word,),
            )
            by_synset = {}
            for synset, *fields in examples:
                by_synset.setdefault(synset, []).append(Example(*fields))

        groups = {}
        for synset, pos, en, zh in senses:
            definition = Definition(en, zh, by_synset.get(synset, [])[:3])
            groups.setdefault(POS[pos], []).append(definition)
        if groups or word_atlas or complete_dictionary:
            pronunciations = Pronunciations(
                uk=(word_atlas or {}).get("uk"),
                us=(word_atlas or {}).get("us"),
            )
            return Word(
                word=word,
                pronunciations=pronunciations,
                entries=[Entry(pos, definitions) for pos, definitions in groups.items()],
                word_atlas=word_atlas,
                complete_dictionary=complete_dictionary,
            )
        return None
