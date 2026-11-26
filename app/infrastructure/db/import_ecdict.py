"""Import ECDICT CSV records into the single active wordnet.db database."""

import argparse
import csv
import pathlib
import sqlite3

BASE = pathlib.Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = BASE / "data" / "ecdict.csv"
DEFAULT_DATABASE = BASE / "data" / "wordnet.db"


def import_csv(source: pathlib.Path, database: pathlib.Path) -> int:
    database = database.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with sqlite3.connect(database) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ecdict_entries (
                normalized_word TEXT PRIMARY KEY, word TEXT NOT NULL, phonetic TEXT, translation TEXT
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS dictionary_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
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
                batch.append((word.casefold(), word, row.get("phonetic") or "", row.get("translation") or ""))
                if len(batch) >= 5000:
                    conn.executemany("INSERT OR REPLACE INTO ecdict_entries VALUES (?, ?, ?, ?)", batch)
                    count += len(batch)
                    batch.clear()
            if batch:
                conn.executemany("INSERT OR REPLACE INTO ecdict_entries VALUES (?, ?, ?, ?)", batch)
                count += len(batch)
        conn.executemany(
            "INSERT OR REPLACE INTO dictionary_metadata(key, value) VALUES (?, ?)",
            [("ecdict_source", "https://github.com/skywind3000/ECDICT"),
             ("ecdict_source_file", source.name),
             ("ecdict_license_file", "ECDICT-LICENSE")],
        )
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=pathlib.Path, default=DEFAULT_SOURCE)
    parser.add_argument("--database", type=pathlib.Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    total = import_csv(args.source, args.database)
    with sqlite3.connect(args.database) as conn:
        indexed = conn.execute("SELECT COUNT(*) FROM ecdict_entries").fetchone()[0]
    print(f"Imported {total} rows; {indexed} unique words into unified database {args.database}")
