import sqlite3
from contextlib import closing
from pathlib import Path

from app.domain.models.word import Definition, Entry, Example, Word

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "wordnet.db"
POS = {
    "n": "noun", "v": "verb", "a": "adjective", "s": "adjective", "r": "adverb",
    "int": "interjection",
}


class WordnetRepository:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path.resolve()

    def get_word(self, word: str) -> Word | None:
        if not self.db_path.is_file():
            return None
        word = word.strip().casefold()
        with closing(sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True)) as conn:
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
        if groups:
            return Word(word=word, entries=[Entry(pos, definitions) for pos, definitions in groups.items()])
        return None
