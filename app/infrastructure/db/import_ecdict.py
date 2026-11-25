import argparse
import csv
import os
import pathlib
import sqlite3
import tempfile

BASE = pathlib.Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = BASE / "data" / "ecdict.csv"
DEFAULT_DATABASE = BASE / "data" / "ecdict.db"


def import_csv(source: pathlib.Path, database: pathlib.Path) -> int:
    database.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="ecdict-", suffix=".db", dir=database.parent)
    os.close(fd)
    temp_database = pathlib.Path(temp_name)
    count = 0
    try:
        with sqlite3.connect(temp_database) as conn:
            conn.execute("PRAGMA journal_mode=OFF")
            conn.execute("PRAGMA synchronous=OFF")
            conn.execute("""
                CREATE TABLE words (
                    normalized_word TEXT PRIMARY KEY,
                    word TEXT NOT NULL,
                    phonetic TEXT,
                    translation TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            with source.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                required = {"word", "phonetic", "translation"}
                if not reader.fieldnames or not required.issubset(reader.fieldnames):
                    raise ValueError("ECDICT CSV is missing required columns")
                batch = []
                for row in reader:
                    word = (row.get("word") or "").strip()
                    if not word:
                        continue
                    batch.append((
                        word.casefold(),
                        word,
                        row.get("phonetic") or "",
                        row.get("translation") or "",
                    ))
                    if len(batch) >= 5000:
                        conn.executemany(
                            "INSERT OR REPLACE INTO words VALUES (?, ?, ?, ?)", batch
                        )
                        count += len(batch)
                        batch.clear()
                if batch:
                    conn.executemany(
                        "INSERT OR REPLACE INTO words VALUES (?, ?, ?, ?)", batch
                    )
                    count += len(batch)
            conn.execute("CREATE INDEX words_source_word_idx ON words(word)")
            conn.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                [
                    ("source", "https://github.com/skywind3000/ECDICT"),
                    ("source_file", "ecdict.csv"),
                    ("license_file", "ECDICT-LICENSE"),
                ],
            )
            conn.commit()
        os.replace(temp_database, database)
        return count
    finally:
        if temp_database.exists():
            temp_database.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import ECDICT CSV into a local SQLite index.")
    parser.add_argument("--source", type=pathlib.Path, default=DEFAULT_SOURCE)
    parser.add_argument("--database", type=pathlib.Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    total = import_csv(args.source, args.database)
    with sqlite3.connect(args.database) as conn:
        indexed = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    print(f"Imported {total} rows; {indexed} unique normalized words into {args.database}")
