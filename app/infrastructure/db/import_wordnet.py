"""Build the read-only bilingual sense index from WordNet and curated examples."""

import argparse
import csv
import html
import json
import re
import sqlite3
import tempfile
import xml.etree.ElementTree as ET
import zlib
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from opencc import OpenCC

from app.infrastructure.db.wordnet_repository import DB_PATH, POS

COW_URL = "https://bond-lab.github.io/cow/"
COW_LICENSE = COW_URL + "LICENSE"
HAN = re.compile(r"[\u3400-\u9fff]")
REVIEWED_EXAMPLES = Path(__file__).with_name("reviewed_examples.tsv")
TRANSLATED_EXAMPLES = Path(__file__).with_name("translated_examples.tsv")
BATCH_EXAMPLES = Path(__file__).with_name("batch_wordnet_examples.tsv")
ATLAS_EXAMPLES = Path(__file__).with_name("word_atlas_examples.tsv")
WORD_ATLAS_DATA = Path(__file__).with_name("word_atlas_source.json")
COMMON_WORD_EXAMPLES = Path(__file__).with_name("common_word_examples.tsv")
WORD_ATLAS_SECOND_EXAMPLES = Path(__file__).with_name("word_atlas_second_examples.tsv")
TATOEBA_EXAMPLES = Path(__file__).with_name("tatoeba_examples.tsv")
CHECKED_WORDNET_EXAMPLES = Path(__file__).with_name("checked_wordnet_examples.tsv")
TATOEBA_URL = "https://tatoeba.org/en/downloads"
TATOEBA_LICENSE = "https://creativecommons.org/licenses/by/2.0/fr/"
ATLAS_COMMIT = "4ff9c429745c12506a9d07d3c29f0791a66191d5"
ATLAS_DATA_SHA256 = "E4E3410809047711CD2A25FCCAFCEBB46124CE1EEB98829DC12DE0335DE71234"
ATLAS_URL = f"https://github.com/designfuchen/word-atlas/blob/{ATLAS_COMMIT}/data/word-atlas.json"
ATLAS_LICENSE = "https://creativecommons.org/licenses/by/4.0/"
ATLAS_AUTHOR = "Word Atlas contributors — CC BY 4.0"
COMPLETE_DICTIONARY_COMMIT = "814551f13ec768058ad38737f6beea6c580c9d6d"
COMPLETE_DICTIONARY_SHA256 = "ECB923C0DCDBC832F94B7C43B541423C3B341E4A17256717EEC452D83C4C8543"
COMPLETE_DICTIONARY_URL = (
    "https://github.com/dyeeee/English-Chinese-Dictionary/blob/"
    f"{COMPLETE_DICTIONARY_COMMIT}/Complete_Dictionary.7z"
)
COMPLETE_DICTIONARY_REPO_URL = "https://github.com/dyeeee/English-Chinese-Dictionary"
COMPLETE_DICTIONARY_CSDN_URL = "https://blog.csdn.net/u25th_engineer/article/details/105901529"
COMPLETE_DICTIONARY_SOURCE = "English-Chinese-Dictionary / Bing Dictionary examples"
COMPLETE_DICTIONARY_SEGMENT = re.compile(r"<br\s*/?>", re.IGNORECASE)
HTML_TAG = re.compile(r"<[^>]+>")


@dataclass
class ChineseSense:
    gloss: str
    examples: tuple[str, ...]


def _lexicon_records(path: Path):
    stack = []
    for event, node in ET.iterparse(path, events=("start", "end")):
        if event == "start":
            stack.append(node)
            continue
        if len(stack) == 3:
            yield node
            stack[-2].remove(node)
        stack.pop()


def _valid_sentence(value: str) -> bool:
    return 5 <= len(HAN.findall(value)) and len(value) <= 100


def _chinese_senses(path: Path, traditional):
    terms = defaultdict(dict)
    senses = {}
    for node in _lexicon_records(path):
        if node.tag == "LexicalEntry":
            word = traditional(node.find("Lemma").attrib["writtenForm"])
            for sense in node.findall("Sense"):
                if sense.get("lexicalized") != "false":
                    terms[sense.attrib["synset"]][word] = None
        elif node.tag == "Synset":
            ili = node.get("ili")
            if not ili or ili == "in":
                continue
            words = tuple(terms.pop(node.attrib["id"], {}))
            definition = traditional((node.findtext("Definition") or "").strip())
            if not definition and not words:
                continue
            gloss = "、".join(words[:3])
            if definition and definition not in words:
                gloss = f"{gloss}（{definition}）" if gloss else definition
            examples = tuple(
                traditional(example.text.strip())
                for example in node.findall("Example")
                if example.text and _valid_sentence(example.text.strip())
            )
            senses[ili] = ChineseSense(gloss, examples)
    return senses


def _index_senses(conn, path: Path, chinese):
    english_synsets = {}
    lexical_entries = []
    for node in _lexicon_records(path):
        if node.tag == "LexicalEntry":
            lemma = node.find("Lemma")
            pos = lemma.attrib["partOfSpeech"]
            if pos not in POS:
                continue
            word = lemma.attrib["writtenForm"].casefold()
            linked = [
                (sense.attrib["synset"], int(sense.get("n", "0")), int(sense.findtext("Count", "0")))
                for sense in node.findall("Sense")
            ]
            lexical_entries.append((word, pos, linked))
        elif node.tag == "Synset" and node.get("ili") in chinese:
            english_synsets[node.attrib["id"]] = (
                node.attrib["ili"], (node.findtext("Definition") or "").strip()
            )

    rows = []
    examples = []
    for word, pos, linked in lexical_entries:
        for synset, number, count in linked:
            if synset not in english_synsets:
                continue
            ili, en = english_synsets[synset]
            sense = chinese[ili]
            rows.append((word, ili, pos, number, count, en, sense.gloss))
            examples.extend(
                (word, ili, example, "Chinese Open Wordnet", None, COW_URL, COW_LICENSE, "source_sense", 1)
                for example in sense.examples
            )
    conn.executemany("INSERT OR IGNORE INTO senses VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    _write_examples(conn, examples)


def _write_examples(conn, examples):
    conn.executemany("INSERT OR IGNORE INTO examples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", examples)


def _index_reviewed_examples(conn, path: Path, traditional):
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source, delimiter="\t"):
            word, synset, example = row["word"], row["synset"], row["example"]
            if row["pos"]:
                conn.execute(
                    """INSERT INTO senses VALUES (?, ?, ?, 1, 100, ?, ?)
                       ON CONFLICT(word, synset) DO UPDATE SET en = excluded.en, zh = excluded.zh""",
                    (word, synset, row["pos"], row["en"], row["zh"]),
                )
            else:
                exists = conn.execute(
                    "SELECT 1 FROM senses WHERE word = ? AND synset = ?", (word, synset)
                ).fetchone()
                if not exists:
                    raise ValueError(f"{word}: unknown sense {synset}")
            english_example = (row.get("en_example") or "").strip()
            example_text = (
                f"{english_example}\n{traditional(example)}"
                if english_example else traditional(example)
            )
            _write_examples(conn, [
                (word, synset, example_text, "自編例句", None, None, None, "editorial",
                 -1 if english_example else 0)
            ])


def _index_translated_examples(conn, path: Path, traditional, *, reviewed: bool):
    conn.execute("""CREATE TEMP TABLE translated (
        synset TEXT PRIMARY KEY, example TEXT, english TEXT NOT NULL DEFAULT ''
    )""")
    with path.open(encoding="utf-8", newline="") as source:
        conn.executemany(
            "INSERT INTO translated VALUES (?, ?, ?)",
            (
                (row["synset"], traditional(row["example"]).replace(",", "，"),
                 (row.get("english") or "").strip())
                for row in csv.DictReader(source, delimiter="\t")
            ),
        )
    conn.execute("""
        INSERT INTO examples
        SELECT s.word, s.synset,
               CASE WHEN t.english != '' THEN t.english || char(10) || t.example ELSE t.example END, ?,
               'Princeton WordNet / Helsinki-NLP OPUS-MT',
               'https://wordnet.princeton.edu/',
               'https://wordnet.princeton.edu/license-and-commercial-use',
               ?, CASE WHEN t.english != '' THEN -1 ELSE ? END
        FROM senses s JOIN translated t ON s.synset = t.synset
        WHERE NOT EXISTS (
            SELECT 1 FROM examples e WHERE e.word = s.word AND e.synset = s.synset
              AND instr(e.text, char(10)) > 0
        )
    """, (
        "Princeton WordNet（機翻校訂）" if reviewed else "Princeton WordNet（自動翻譯）",
        "reviewed_translation" if reviewed else "machine_translation",
        2 if reviewed else 3,
    ))
    conn.execute("DROP TABLE translated")


def _index_atlas_examples(conn, path: Path, traditional):
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source, delimiter="\t"):
            word, synset = row["word"], row["synset"]
            if not conn.execute(
                "SELECT 1 FROM senses WHERE word = ? AND synset = ?", (word, synset)
            ).fetchone():
                raise ValueError(f"{word}: unknown Word Atlas mapping {synset}")
            conn.execute("""
                INSERT INTO examples
                SELECT ?, ?, ?, 'Word Atlas', ?, ?, ?, 'reviewed_atlas_mapping', 4
                WHERE NOT EXISTS (SELECT 1 FROM examples WHERE word = ? AND synset = ?)
            """, (word, synset, traditional(row["example"]), ATLAS_AUTHOR, ATLAS_URL,
                  ATLAS_LICENSE, word, synset))


def _index_common_word_examples(conn, path: Path, traditional):
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source, delimiter="\t"):
            word, synset = row["word"], row["synset"]
            if row.get("pos") and row.get("en_definition") and row.get("zh_definition"):
                conn.execute(
                    """INSERT OR IGNORE INTO senses VALUES (?, ?, ?, 1, 0, ?, ?)""",
                    (word, synset, row["pos"], row["en_definition"].strip(),
                     traditional(row["zh_definition"].strip())),
                )
            if not conn.execute(
                "SELECT 1 FROM senses WHERE word = ? AND synset = ?", (word, synset)
            ).fetchone():
                raise ValueError(f"{word}: unknown common-word sense {synset}")
            english = row["en_example"].strip()
            chinese = traditional(row["zh_example"].strip())
            bilingual = f"{english}\n{chinese}"
            _write_examples(conn, [(
                word, synset, bilingual, "Word Atlas", ATLAS_AUTHOR, ATLAS_URL,
                ATLAS_LICENSE, "common_word_atlas", -1
            )])


def _convert_atlas_text(value, traditional):
    if isinstance(value, str):
        return traditional(value)
    if isinstance(value, list):
        return [_convert_atlas_text(item, traditional) for item in value]
    if isinstance(value, dict):
        return {key: _convert_atlas_text(item, traditional) for key, item in value.items()}
    return value


def _index_word_atlas_data(conn, path: Path, traditional):
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Word Atlas source must be a JSON list")
    seen = set()
    rows = []
    for source_record in records:
        if not isinstance(source_record, dict):
            raise ValueError("Word Atlas record must be an object")
        word = (source_record.get("w") or "").strip().casefold()
        senses = source_record.get("senses")
        examples = source_record.get("ex")
        if not word or word in seen:
            raise ValueError(f"Word Atlas has an empty or duplicate word: {word!r}")
        if not isinstance(senses, list) or not senses or not isinstance(examples, list) or not examples:
            raise ValueError(f"Word Atlas record is missing senses/examples: {word}")
        for sense in senses:
            if not all(isinstance(sense.get(key), str) and sense[key].strip()
                       for key in ("pos", "en", "zh")):
                raise ValueError(f"Word Atlas sense is incomplete: {word}")
        for example in examples:
            if not all(isinstance(example.get(key), str) and example[key].strip()
                       for key in ("en", "zh")):
                raise ValueError(f"Word Atlas example is incomplete: {word}")
        seen.add(word)
        record = _convert_atlas_text(source_record, traditional)
        record["provenance"] = {
            "source": "Word Atlas",
            "author": ATLAS_AUTHOR,
            "source_url": ATLAS_URL,
            "source_commit": ATLAS_COMMIT,
            "dataset_sha256": ATLAS_DATA_SHA256,
            "license": "CC BY 4.0",
            "license_url": ATLAS_LICENSE,
            "changes": "Chinese text converted to Taiwan Traditional; examples remain word-level because the source does not assign them to individual senses.",
        }
        rows.append((word, json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)))
    conn.executemany("INSERT INTO word_atlas(word, data) VALUES (?, ?)", rows)
    print(f"Word Atlas words: {len(rows)}; senses: {sum(len(r.get('senses', [])) for r in records)}; examples: {sum(len(r.get('ex', [])) for r in records)}")


def _index_complete_dictionary_data(conn, path: Path, traditional):
    inserted_words = 0
    inserted_examples = 0
    batch = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"wordID", "wordContent", "definition", "translation", "exampleSentences"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("Complete Dictionary CSV is missing required dictionary columns")
        for row in reader:
            word = (row.get("wordContent") or "").strip().casefold()
            raw = (row.get("exampleSentences") or "").strip()
            if not word:
                continue
            examples = []
            if raw and raw.casefold() not in {"nulltag", "null", "none"}:
                segments = [
                    html.unescape(HTML_TAG.sub("", part)).strip()
                    for part in COMPLETE_DICTIONARY_SEGMENT.split(raw)
                ]
                for index in range(0, len(segments) - 1, 2):
                    english, chinese = segments[index:index + 2]
                    if (not english or not chinese or english.casefold() in {"nulltag", "null"}
                            or chinese.casefold() in {"nulltag", "null"} or not HAN.search(chinese)):
                        continue
                    examples.append({"en": english, "zh": traditional(chinese)})
            record = {
                "source": COMPLETE_DICTIONARY_SOURCE,
                "author": "dyeeee / English-Chinese-Dictionary; original examples attributed to the cited CSDN source",
                "source_url": COMPLETE_DICTIONARY_URL,
                "repository_url": COMPLETE_DICTIONARY_REPO_URL,
                "original_source_url": COMPLETE_DICTIONARY_CSDN_URL,
                "source_commit": COMPLETE_DICTIONARY_COMMIT,
                "dataset_sha256": COMPLETE_DICTIONARY_SHA256,
                "license": "User-confirmed full authorization",
                "changes": "Complete English/Chinese pairs retained at word level; Chinese converted to Taiwan Traditional; source does not map each pair to a dictionary sense.",
                "word_id": row.get("wordID"),
                "phonetic_en": row.get("phonetic_EN") or None,
                "phonetic_us": row.get("phonetic_US") or None,
                "definition": row.get("definition") or None,
                "translation": traditional(row.get("translation") or "") or None,
                "word_tags": row.get("wordTags") or None,
                "word_exchanges": row.get("wordExchanges") or None,
                "bnc_level": row.get("bncLevel") or None,
                "frequency_level": row.get("frqLevel") or None,
                "collins_level": row.get("collinsLevel") or None,
                "oxford_level": row.get("oxfordLevel") or None,
                "examples": examples,
            }
            encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            batch.append((word, zlib.compress(encoded, level=6)))
            inserted_words += 1
            inserted_examples += len(examples)
            if len(batch) >= 2000:
                conn.executemany(
                    "INSERT OR REPLACE INTO complete_dictionary(word, data) VALUES (?, ?)", batch
                )
                batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO complete_dictionary(word, data) VALUES (?, ?)", batch
        )
    print(f"Complete Dictionary records: {inserted_words}; bilingual pairs: {inserted_examples}")


def _index_ecdict_database(conn, path: Path):
    path = path.resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "stardict" in tables:
            rows = source.execute("SELECT word, phonetic, translation FROM stardict")
        elif "words" in tables:
            columns = {row[1] for row in source.execute("PRAGMA table_info(words)")}
            if {"normalized_word", "word", "phonetic", "translation"}.issubset(columns):
                rows = source.execute("SELECT word, phonetic, translation FROM words")
            else:
                raise ValueError(f"Unsupported ECDICT words schema in {path}")
        else:
            raise ValueError(f"No supported ECDICT table in {path}")
        batch = []
        count = 0
        for word, phonetic, translation in rows:
            if not word:
                continue
            batch.append((word.strip().casefold(), word, phonetic or "", translation or ""))
            if len(batch) >= 10000:
                conn.executemany("INSERT OR REPLACE INTO ecdict_entries VALUES (?, ?, ?, ?)", batch)
                count += len(batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT OR REPLACE INTO ecdict_entries VALUES (?, ?, ?, ?)", batch)
            count += len(batch)
    print(f"ECDICT records imported: {count}")


def _index_cache_database(conn, path: Path):
    path = path.resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
        table_names = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"words", "pronunciations", "entries", "definitions", "examples"}
        if not required.issubset(table_names):
            raise ValueError(f"Unsupported cache database schema in {path}")
        for table in sorted(required):
            columns = [row[1] for row in source.execute(f"PRAGMA table_info({table})")]
            conn.executemany(
                f"INSERT OR REPLACE INTO cache_{table} ({', '.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                source.execute(f"SELECT {', '.join(columns)} FROM {table}"),
            )
    print("Legacy query cache imported")


def _index_tatoeba_examples(conn, path: Path, traditional):
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source, delimiter="\t"):
            word, synset = row["word"], row["synset"]
            if not conn.execute(
                "SELECT 1 FROM senses WHERE word = ? AND synset = ?", (word, synset)
            ).fetchone():
                continue
            english = row["en_example"].strip()
            chinese = traditional(row["zh_example"].strip())
            if not english or not chinese:
                continue
            text = f"{english}\n{chinese}"
            en_id, zh_id = row["en_id"], row["zh_id"]
            links = (
                f"https://tatoeba.org/en/sentences/show/{en_id}; "
                f"https://tatoeba.org/en/sentences/show/{zh_id}"
            )
            authors = "; ".join(
                f"{language}: {row[key].strip()}" for language, key in (
                    ("English", "en_author"), ("Chinese", "zh_author")
                ) if row.get(key, "").strip()
            ) or "See linked Tatoeba sentence pages for contributor attribution"
            _write_examples(conn, [(
                word, synset, text, "Tatoeba", authors, links, TATOEBA_LICENSE,
                "tatoeba_gloss_match", 0,
            )])


def build_index(
    english: Path, chinese: Path, output: Path, examples: Path = REVIEWED_EXAMPLES,
    batch_examples: Path = BATCH_EXAMPLES, atlas_examples: Path = ATLAS_EXAMPLES,
    common_word_examples: Path = COMMON_WORD_EXAMPLES,
    tatoeba_examples: Path = TATOEBA_EXAMPLES,
    word_atlas_second_examples: Path | None = WORD_ATLAS_SECOND_EXAMPLES,
    word_atlas_data: Path | None = WORD_ATLAS_DATA,
    complete_dictionary_data: Path | None = None,
    ecdict_database: Path | None = None,
    cache_database: Path | None = None,
):
    traditional = OpenCC("s2twp.json").convert
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=output.name + ".") as temporary:
        database = Path(temporary) / output.name
        with closing(sqlite3.connect(database)) as conn, conn:
            conn.executescript("""
                CREATE TABLE senses (
                    word TEXT, synset TEXT, pos TEXT, sense_number INTEGER, frequency INTEGER,
                    en TEXT, zh TEXT, PRIMARY KEY (word, synset)
                ) WITHOUT ROWID;
                CREATE TABLE examples (
                    word TEXT, synset TEXT, text TEXT, source TEXT, author TEXT,
                    source_url TEXT, license_url TEXT, match_type TEXT, priority INTEGER,
                    PRIMARY KEY (word, synset, text)
                ) WITHOUT ROWID;
                CREATE TABLE licenses (source TEXT PRIMARY KEY, notice TEXT NOT NULL);
                CREATE TABLE word_atlas (word TEXT PRIMARY KEY, data TEXT NOT NULL) WITHOUT ROWID;
                CREATE TABLE complete_dictionary (word TEXT PRIMARY KEY, data BLOB NOT NULL) WITHOUT ROWID;
                CREATE TABLE ecdict_entries (
                    normalized_word TEXT PRIMARY KEY, word TEXT NOT NULL, phonetic TEXT, translation TEXT
                ) WITHOUT ROWID;
                CREATE TABLE cache_words (id INTEGER PRIMARY KEY AUTOINCREMENT, word TEXT UNIQUE NOT NULL);
                CREATE TABLE cache_pronunciations (word_id INTEGER, uk TEXT, us TEXT);
                CREATE TABLE cache_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, word_id INTEGER, part_of_speech TEXT);
                CREATE TABLE cache_definitions (id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER, en_definition TEXT, zh_definition TEXT);
                CREATE TABLE cache_examples (id INTEGER PRIMARY KEY AUTOINCREMENT, definition_id INTEGER, example_text TEXT);
            """)
            conn.executemany(
                "INSERT INTO licenses VALUES (?, ?)",
                [
                    ("Princeton WordNet", english.with_name("LICENSE").read_text(encoding="utf-8")),
                    ("Chinese Open Wordnet", chinese.with_name("LICENSE").read_text(encoding="utf-8")),
                    ("Word Atlas", f"{ATLAS_AUTHOR} ({ATLAS_LICENSE}). Data: {ATLAS_URL}. "
                     f"Dataset SHA-256: {ATLAS_DATA_SHA256}. "
                     "Changes: Chinese text converted to Taiwan Traditional. All source-level examples "
                     "are retained without assigning them to individual senses."),
                    ("English-Chinese-Dictionary", "Full authorization to use the Complete_Dictionary dataset was confirmed by the project owner. "
                     f"Source archive: {COMPLETE_DICTIONARY_URL}; repository README: {COMPLETE_DICTIONARY_REPO_URL}/blob/{COMPLETE_DICTIONARY_COMMIT}/README.md. "
                     f"Original example source cited by that README: {COMPLETE_DICTIONARY_CSDN_URL}. "
                     f"Archive SHA-256: {COMPLETE_DICTIONARY_SHA256}. Chinese text converted to Taiwan Traditional; "
                     "examples remain at word level and are not mapped to individual senses."),
                    ("Tatoeba", "Tatoeba contributors. Text licensed under CC BY 2.0 FR "
                     f"({TATOEBA_LICENSE}). Sentence contributor links are stored per example; "
                     f"data source: {TATOEBA_URL}. Chinese text converted to Traditional Chinese."),
                ],
            )
            _index_senses(conn, english, _chinese_senses(chinese, traditional))
            _index_reviewed_examples(conn, examples, traditional)
            _index_translated_examples(conn, TRANSLATED_EXAMPLES, traditional, reviewed=True)
            _index_translated_examples(conn, batch_examples, traditional, reviewed=False)
            _index_translated_examples(conn, CHECKED_WORDNET_EXAMPLES, traditional, reviewed=False)
            _index_atlas_examples(conn, atlas_examples, traditional)
            _index_common_word_examples(conn, common_word_examples, traditional)
            if word_atlas_second_examples and word_atlas_second_examples.exists():
                _index_common_word_examples(conn, word_atlas_second_examples, traditional)
            _index_tatoeba_examples(conn, tatoeba_examples, traditional)
            if word_atlas_data:
                _index_word_atlas_data(conn, word_atlas_data, traditional)
            if complete_dictionary_data:
                _index_complete_dictionary_data(conn, complete_dictionary_data, traditional)
            if ecdict_database:
                _index_ecdict_database(conn, ecdict_database)
            if cache_database:
                _index_cache_database(conn, cache_database)
            for label, query in (
                ("words", "SELECT count(DISTINCT word) FROM senses"),
                ("word senses", "SELECT count(*) FROM senses"),
                ("word senses with examples", "SELECT count(*) FROM (SELECT DISTINCT word, synset FROM examples)"),
            ):
                print(f"{label}: {conn.execute(query).fetchone()[0]}")
        database.chmod(0o644)
        # Publish only the finished database. SQLite readers see either complete version.
        database.replace(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("english", type=Path)
    parser.add_argument("chinese", type=Path)
    parser.add_argument("--output", type=Path, default=DB_PATH)
    parser.add_argument("--examples", type=Path, default=REVIEWED_EXAMPLES)
    parser.add_argument("--batch-examples", type=Path, default=BATCH_EXAMPLES)
    parser.add_argument("--atlas-examples", type=Path, default=ATLAS_EXAMPLES)
    parser.add_argument("--common-word-examples", type=Path, default=COMMON_WORD_EXAMPLES)
    parser.add_argument("--tatoeba-examples", type=Path, default=TATOEBA_EXAMPLES)
    parser.add_argument("--word-atlas-second-examples", type=Path, default=WORD_ATLAS_SECOND_EXAMPLES)
    parser.add_argument("--word-atlas-data", type=Path, default=WORD_ATLAS_DATA)
    parser.add_argument("--complete-dictionary-data", type=Path)
    parser.add_argument("--ecdict-database", type=Path)
    parser.add_argument("--cache-database", type=Path)
    args = parser.parse_args()
    build_index(args.english, args.chinese, args.output, args.examples,
                args.batch_examples, args.atlas_examples, args.common_word_examples,
                args.tatoeba_examples, args.word_atlas_second_examples, args.word_atlas_data,
                args.complete_dictionary_data, args.ecdict_database, args.cache_database)
