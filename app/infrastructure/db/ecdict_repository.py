import pathlib
import re
import sqlite3
from contextlib import closing
from typing import Optional

from app.domain.models.word import Definition, Entry, Pronunciations, Word

BASE = pathlib.Path(__file__).resolve().parents[3]
DB_PATH = BASE / "data" / "wordnet.db"

_POS_NAMES = {
    "n": "noun", "v": "verb", "vi": "intransitive verb", "vt": "transitive verb",
    "adj": "adjective", "a": "adjective", "adv": "adverb", "ad": "adjective",
    "prep": "preposition", "pron": "pronoun", "conj": "conjunction",
    "interj": "interjection", "int": "interjection", "num": "numeral",
    "art": "article", "aux": "auxiliary verb", "abbr": "abbreviation",
    "phr": "phrase", "pref": "prefix", "suf": "suffix",
}
_POS_PREFIX = re.compile(r"^([A-Za-z]+)\.\s+(.+)$")


class EcdictRepository:
    """Read ECDICT records from the unified dictionary database."""

    def __init__(self, db_path: pathlib.Path = DB_PATH, release_path: Optional[pathlib.Path] = None):
        self.db_path = pathlib.Path(db_path).resolve()
        self.release_path = pathlib.Path(release_path).resolve() if release_path else None

    @staticmethod
    def _entries(translation: str) -> list[Entry]:
        grouped: dict[str, list[Definition]] = {}
        current_pos = "other"
        for raw_line in translation.replace("\\n", "\n").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = _POS_PREFIX.match(line)
            if match:
                source_pos, text = match.groups()
                current_pos = _POS_NAMES.get(source_pos.lower(), source_pos.lower())
            else:
                text = line
            grouped.setdefault(current_pos, []).append(
                Definition(en_definition="", zh_definition=text)
            )
        return [
            Entry(part_of_speech=part_of_speech, definitions=definitions)
            for part_of_speech, definitions in grouped.items()
        ]

    def get_word(self, word: str) -> Optional[Word]:
        normalized = word.strip().casefold()
        if not normalized:
            return None
        row = None
        if self.db_path.is_file() and self.db_path.stat().st_size:
            with closing(sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True)) as conn:
                has_unified = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ecdict_entries'"
                ).fetchone()
                if has_unified:
                    row = conn.execute(
                        "SELECT word, phonetic, translation FROM ecdict_entries WHERE normalized_word = ?",
                        (normalized,),
                    ).fetchone()
                else:
                    has_legacy = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='words'"
                    ).fetchone()
                    if has_legacy:
                        row = conn.execute(
                            "SELECT word, phonetic, translation FROM words WHERE normalized_word = ?",
                            (normalized,),
                        ).fetchone()
        if row is None and self.release_path and self.release_path.is_file():
            with closing(sqlite3.connect(self.release_path.as_uri() + "?mode=ro", uri=True)) as conn:
                row = conn.execute(
                    "SELECT word, phonetic, translation FROM stardict WHERE word = ?",
                    (normalized,),
                ).fetchone()
        if row is None:
            return None
        source_word, phonetic, translation = row
        return Word(
            word=source_word,
            pronunciations=Pronunciations(phonetic=phonetic or None),
            entries=self._entries(translation or ""),
        )
