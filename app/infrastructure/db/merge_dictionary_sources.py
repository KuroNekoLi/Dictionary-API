"""Atomically add legacy dictionary stores to the unified SQLite database."""

import argparse
import hashlib
import os
import shutil
import sqlite3
import tempfile
import urllib.request
from contextlib import closing
from pathlib import Path

from opencc import OpenCC

from app.infrastructure.db.import_wordnet import (
    _index_cache_database,
    _index_complete_dictionary_data,
    _index_ecdict_database,
    _index_word_atlas_data,
    ATLAS_DATA_SHA256,
    COMPLETE_DICTIONARY_SHA256,
    COMPLETE_DICTIONARY_URL,
    WORD_ATLAS_DATA,
)


def merge_sources(
    database: Path,
    *,
    ecdict_database: Path | None = None,
    cache_database: Path | None = None,
    complete_dictionary_data: Path | None = None,
    complete_dictionary_archive: Path | None = None,
    word_atlas_data: Path | None = WORD_ATLAS_DATA,
) -> None:
    database = database.resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    fd, temporary_name = tempfile.mkstemp(prefix=database.stem + ".merge-", suffix=".db", dir=database.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(database, temporary)
        with closing(sqlite3.connect(temporary)) as conn, conn:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("CREATE TABLE IF NOT EXISTS ecdict_entries (normalized_word TEXT PRIMARY KEY, word TEXT NOT NULL, phonetic TEXT, translation TEXT) WITHOUT ROWID")
            conn.execute("CREATE TABLE IF NOT EXISTS complete_dictionary (word TEXT PRIMARY KEY, data BLOB NOT NULL) WITHOUT ROWID")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS cache_words (id INTEGER PRIMARY KEY AUTOINCREMENT, word TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS cache_pronunciations (word_id INTEGER, uk TEXT, us TEXT);
                CREATE TABLE IF NOT EXISTS cache_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, word_id INTEGER, part_of_speech TEXT);
                CREATE TABLE IF NOT EXISTS cache_definitions (id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER, en_definition TEXT, zh_definition TEXT);
                CREATE TABLE IF NOT EXISTS cache_examples (id INTEGER PRIMARY KEY AUTOINCREMENT, definition_id INTEGER, example_text TEXT);
                CREATE TABLE IF NOT EXISTS dictionary_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS word_atlas (word TEXT PRIMARY KEY, data TEXT NOT NULL) WITHOUT ROWID;
            """)
            traditional = OpenCC("s2twp.json").convert
            if word_atlas_data:
                records = __import__("json").loads(word_atlas_data.read_text(encoding="utf-8"))
                actual_hash = hashlib.sha256(word_atlas_data.read_bytes()).hexdigest().upper()
                if actual_hash != ATLAS_DATA_SHA256:
                    raise ValueError(f"Word Atlas source checksum mismatch: {actual_hash}")
                conn.execute("DELETE FROM word_atlas")
                _index_word_atlas_data(conn, word_atlas_data, traditional)
                conn.execute("INSERT OR REPLACE INTO dictionary_metadata VALUES ('word_atlas_records', ?)", (str(len(records)),))
            if complete_dictionary_archive:
                archive = complete_dictionary_archive.resolve()
                if not archive.is_file():
                    with urllib.request.urlopen(COMPLETE_DICTIONARY_URL.replace("/blob/", "/raw/"), timeout=60) as response:
                        archive.write_bytes(response.read())
                archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest().upper()
                if archive_hash != COMPLETE_DICTIONARY_SHA256:
                    raise ValueError(f"Complete Dictionary archive checksum mismatch: {archive_hash}")
                import py7zr
                with tempfile.TemporaryDirectory(prefix="complete-dictionary-", dir=database.parent) as extraction_dir:
                    with py7zr.SevenZipFile(archive, mode="r") as seven_zip:
                        seven_zip.extractall(path=extraction_dir)
                    candidates = list(Path(extraction_dir).rglob("Complete_Dictionary.csv"))
                    if len(candidates) != 1:
                        raise ValueError(f"Expected one Complete_Dictionary.csv in archive, found {len(candidates)}")
                    _index_complete_dictionary_data(conn, candidates[0], traditional)
                conn.execute("INSERT OR REPLACE INTO dictionary_metadata VALUES ('complete_dictionary_archive_sha256', ?)", (archive_hash,))
            if ecdict_database:
                _index_ecdict_database(conn, ecdict_database)
                conn.execute("INSERT OR REPLACE INTO dictionary_metadata VALUES ('ecdict_imported_from', ?)", (str(ecdict_database),))
            if cache_database:
                _index_cache_database(conn, cache_database)
                conn.execute("INSERT OR REPLACE INTO dictionary_metadata VALUES ('legacy_cache_imported_from', ?)", (str(cache_database),))
            if complete_dictionary_data:
                _index_complete_dictionary_data(conn, complete_dictionary_data, traditional)
                conn.execute("INSERT OR REPLACE INTO dictionary_metadata VALUES ('complete_dictionary_imported_from', ?)", (str(complete_dictionary_data),))
            conn.execute("INSERT OR REPLACE INTO dictionary_metadata VALUES ('unified_schema_version', '1')")
            conn.execute("CREATE INDEX IF NOT EXISTS ecdict_entries_word_idx ON ecdict_entries(word)")
            conn.commit()
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise sqlite3.DatabaseError(f"Unified database integrity check failed: {result}")
        os.replace(temporary, database)
    finally:
        if temporary.exists():
            temporary.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--ecdict-database", type=Path)
    parser.add_argument("--cache-database", type=Path)
    parser.add_argument("--complete-dictionary-data", type=Path)
    parser.add_argument("--complete-dictionary-archive", type=Path)
    parser.add_argument("--word-atlas-data", type=Path, default=WORD_ATLAS_DATA)
    args = parser.parse_args()
    merge_sources(
        args.database,
        ecdict_database=args.ecdict_database,
        cache_database=args.cache_database,
        complete_dictionary_data=args.complete_dictionary_data,
        complete_dictionary_archive=args.complete_dictionary_archive,
        word_atlas_data=args.word_atlas_data,
    )
    print(f"Unified database ready: {args.database}")
