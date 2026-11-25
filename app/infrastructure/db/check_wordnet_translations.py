"""Filter offline WordNet translations before adding them to the index."""

import argparse
import csv
import itertools
import json
import re
from pathlib import Path

_WORDS = re.compile(r"[a-z]+(?:'[a-z]+)?|\d+", re.IGNORECASE)
_STOP = set(
    "a an the and or on in at of for from to by with as is are be been being "
    "was were it its that this they their he his she her them these those "
    "you your we our i me my himself herself themselves himself us".split()
)
_SUBORDINATE = {"although", "because", "if", "since", "when", "whereas", "while"}
_FINITE = {"VBD", "VBP", "VBZ", "MD"}
_SUBJECT = {"NN", "NNS", "NNP", "NNPS", "PRP", "EX"}
_NEGATIVES = {"no", "not", "never"}


def _complete_clause(tags):
    if not tags or tags[0][0] in _SUBORDINATE:
        return False
    return any(
        tag in _FINITE and any(earlier in _SUBJECT for _, earlier in tags[:index])
        for index, (_, tag) in enumerate(tags)
    )


def _meaning_overlap(left, right, stem):
    left_words, right_words = (_WORDS.findall(text.lower()) for text in (left, right))
    if any(re.search(r"\d", text) for text in (left, right)):
        if re.findall(r"\d+", left) != re.findall(r"\d+", right):
            return False
    # Reject negation that gets inserted or removed by the translation.
    def negative(words):
        return any(word in _NEGATIVES or word.endswith("n't") for word in words)

    if negative(left_words) != negative(right_words):
        return False
    a, b = ({stem(word) for word in words if word not in _STOP} for words in (left_words, right_words))
    shared = len(a & b)
    return shared >= 2 and shared / len(a) >= 0.7 and shared / len(b) >= 0.7


def check_examples(translations: Path, model: Path, output: Path):
    import ctranslate2
    import nltk
    import sentencepiece
    from opencc import OpenCC

    tag = json.loads((model / "opus_mt.json").read_text(encoding="utf-8")).get("language_tag")
    source = sentencepiece.SentencePieceProcessor(model_file=str(model / "source.spm"))
    target = sentencepiece.SentencePieceProcessor(model_file=str(model / "target.spm"))
    translator = ctranslate2.Translator(str(model), device="cpu", compute_type="int8", intra_threads=4)
    simplified = OpenCC("t2s.json").convert
    stem = nltk.stem.PorterStemmer().stem
    with translations.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file, delimiter="\t"))
    tags = nltk.pos_tag_sents([_WORDS.findall(row["english"].lower()) for row in rows])
    candidates = [row for row, tagged in zip(rows, tags, strict=True) if _complete_clause(tagged)]
    print(f"Candidates after sentence check: {len(candidates)} / {len(rows)}", flush=True)

    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, delimiter="\t", lineterminator="\n")
        writer.writerow(("synset", "example", "english"))
        count = 0
        for batch in itertools.batched(candidates, 24):
            tokens = [
                [*([tag] if tag else []), *source.encode(simplified(row["example"]), out_type=str), "</s>"]
                for row in batch
            ]
            results = translator.translate_batch(tokens, beam_size=2, max_decoding_length=100)
            for row, result in zip(batch, results, strict=True):
                back_translation = target.decode(result.hypotheses[0])
                if _meaning_overlap(row["english"], back_translation, stem):
                    writer.writerow((row["synset"], row["example"], row["english"]))
                    count += 1
            file.flush()
    print(f"Candidates after back translation check: {count}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("translations", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    check_examples(args.translations, args.model, args.output)
