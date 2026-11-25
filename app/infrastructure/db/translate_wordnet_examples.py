"""Translate examples already attached to a WordNet sense, offline."""

import argparse
import csv
import itertools
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from opencc import OpenCC

from app.infrastructure.db.import_wordnet import _lexicon_records, _valid_sentence

_LATIN = re.compile(r"[A-Za-z]")
_HAN = re.compile(r"[\u3400-\u9fff]")


def _candidates(english: Path, database: Path):
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        missing = {}
        for ili, frequency, gloss in conn.execute("""
            SELECT s.synset, s.frequency, s.zh FROM senses AS s
            WHERE NOT EXISTS (SELECT 1 FROM examples e WHERE e.word = s.word AND e.synset = s.synset)
        """):
            if ili not in missing or frequency > missing[ili][0]:
                terms = [
                    part for part in re.split("、|；", gloss.split("（")[0])
                    if re.fullmatch(r"[\u3400-\u9fff]{2,}", part)
                ]
                if terms:
                    missing[ili] = (frequency, terms)

    candidates = []
    for node in _lexicon_records(english):
        ili = node.get("ili")
        if node.tag == "Synset" and ili in missing:
            frequency, terms = missing[ili]
            examples = [
                item.text for item in node.findall("Example")
                if item.text and 6 <= len(item.text.split()) <= 24
                and not any(mark in item.text for mark in ('"', "…", ";"))
            ]
            if examples:
                candidates.append((frequency, ili, terms, min(examples, key=len)))
    return sorted(candidates, key=lambda candidate: (-candidate[0], candidate[1]))


def translate(english: Path, database: Path, model: Path, output: Path, limit: int | None):
    import ctranslate2
    import sentencepiece

    tag = json.loads((model / "opus_mt.json").read_text(encoding="utf-8"))["language_tag"]
    source = sentencepiece.SentencePieceProcessor(model_file=str(model / "source.spm"))
    target = sentencepiece.SentencePieceProcessor(model_file=str(model / "target.spm"))
    translator = ctranslate2.Translator(str(model), device="cpu", compute_type="int8", intra_threads=4)
    traditional = OpenCC("s2twp.json").convert
    candidates = _candidates(english, database)[:limit]
    print(f"Eligible source senses: {len(candidates)}", flush=True)

    with output.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination, delimiter="\t")
        writer.writerow(("synset", "example", "english"))
        accepted = 0
        for batch in itertools.batched(candidates, 24):
            tokens = [[tag, *source.encode(example, out_type=str), "</s>"] for *_, example in batch]
            results = translator.translate_batch(
                tokens, beam_size=2, max_decoding_length=100, return_scores=True,
            )
            for (_, ili, terms, original), result in zip(batch, results, strict=True):
                sentence = traditional(target.decode(result.hypotheses[0]).strip())
                if (
                    result.scores[0] < -1.45
                    or not _valid_sentence(sentence)
                    or len(_HAN.findall(sentence)) < 6
                    or _LATIN.search(sentence)
                    or not any(term in sentence for term in terms)
                ):
                    continue
                sentence = sentence.translate(str.maketrans(",?!", "，？！"))
                if not sentence.endswith(("。", "？", "！", "…")):
                    sentence = sentence.rstrip(".") + "。"
                writer.writerow((ili, sentence, original))
                accepted += 1
            destination.flush()
    print(f"Accepted by automatic filters: {accepted}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("english", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    translate(args.english, args.database, args.model, args.output, args.limit)
