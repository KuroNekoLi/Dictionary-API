"""Build the read-only bilingual sense index from WordNet and curated examples."""

import argparse
import csv
import re
import sqlite3
import tempfile
import xml.etree.ElementTree as ET
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
COMMON_WORD_EXAMPLES = Path(__file__).with_name("common_word_examples.tsv")
TATOEBA_EXAMPLES = Path(__file__).with_name("tatoeba_examples.tsv")
CHECKED_WORDNET_EXAMPLES = Path(__file__).with_name("checked_wordnet_examples.tsv")
TATOEBA_URL = "https://tatoeba.org/en/downloads"
TATOEBA_LICENSE = "https://creativecommons.org/licenses/by/2.0/fr/"
ATLAS_URL = (
    "https://github.com/designfuchen/word-atlas/blob/"
    "4ff9c429745c12506a9d07d3c29f0791a66191d5/data/word-atlas.json"
)
ATLAS_LICENSE = "https://creativecommons.org/licenses/by/4.0/"
ATLAS_AUTHOR = "Word Atlas contributors（词光）"


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
            """)
            conn.executemany(
                "INSERT INTO licenses VALUES (?, ?)",
                [
                    ("Princeton WordNet", english.with_name("LICENSE").read_text(encoding="utf-8")),
                    ("Chinese Open Wordnet", chinese.with_name("LICENSE").read_text(encoding="utf-8")),
                    ("Word Atlas", f"{ATLAS_AUTHOR}. CC BY 4.0 ({ATLAS_LICENSE}). "
                     f"Data: {ATLAS_URL}. Changes: selected examples, mapped to common WordNet senses, "
                     "combined English and Chinese text, and converted to Traditional Chinese."),
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
            _index_tatoeba_examples(conn, tatoeba_examples, traditional)
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
    args = parser.parse_args()
    build_index(args.english, args.chinese, args.output, args.examples,
                args.batch_examples, args.atlas_examples, args.common_word_examples,
                args.tatoeba_examples)
