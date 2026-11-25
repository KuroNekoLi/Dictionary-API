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
            _write_examples(conn, [
                (word, synset, traditional(example), "自編例句", None, None, None, "editorial", 0)
            ])


def build_index(english: Path, chinese: Path, output: Path, examples: Path = REVIEWED_EXAMPLES):
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
                ],
            )
            _index_senses(conn, english, _chinese_senses(chinese, traditional))
            _index_reviewed_examples(conn, examples, traditional)
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
    args = parser.parse_args()
    build_index(args.english, args.chinese, args.output, args.examples)
