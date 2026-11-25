import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.domain.models.word import Word
from app.infrastructure.db.ecdict_repository import EcdictRepository
from app.infrastructure.db.wordnet_repository import WordnetRepository
from app.interfaces.schemas.word_schema import DefinitionSchema
from app.usecases.word_query import QueryWordUsecase


class DictionaryTest(unittest.TestCase):
    def test_uses_release_only_when_the_current_ecdict_has_no_word(self):
        with tempfile.TemporaryDirectory() as folder:
            current, release = (Path(folder) / name for name in ("current.db", "release.db"))
            with sqlite3.connect(current) as conn:
                conn.executescript("""
                    CREATE TABLE words(word, phonetic, translation, normalized_word);
                    INSERT INTO words VALUES ('apple', '', 'n. 蘋果', 'apple');
                """)
            with sqlite3.connect(release) as conn:
                conn.executescript("""
                    CREATE TABLE stardict(word, phonetic, translation);
                    INSERT INTO stardict VALUES ('apple', '', 'n. 果子');
                    INSERT INTO stardict VALUES ('hedgehog', '', 'n. 刺蝟');
                """)
            repo = EcdictRepository(current, release)
            for word, translation in (("apple", "蘋果"), ("HEDGEHOG", "刺蝟")):
                self.assertEqual(repo.get_word(word).entries[0].definitions[0].zh_definition, translation)
            self.assertIsNone(repo.get_word("unknown"))

    def test_examples_belong_to_their_synset_and_survive_cached_word(self):
        with tempfile.TemporaryDirectory() as folder:
            index = Path(folder) / "index.db"
            with sqlite3.connect(index) as conn:
                conn.executescript("""
                    CREATE TABLE senses(word, synset, pos, sense_number, frequency, en, zh);
                    CREATE TABLE examples(
                        word, synset, text, source, author, source_url, license_url, match_type, priority
                    );
                    INSERT INTO senses VALUES ('bank', 'shore', 'n', 1, 20, 'River bank', '河岸');
                    INSERT INTO senses VALUES ('bank', 'money', 'n', 2, 10, 'Financial company', '銀行');
                    INSERT INTO examples VALUES ('bank', 'money', '我去銀行存錢。', '自編例句',
                                                NULL, NULL, NULL, 'editorial', 0);
                """)
            class Cache:
                def get_word(self, word):
                    return Word(word)

            result = QueryWordUsecase(Cache(), None, wordnet_repo=WordnetRepository(index)).query_word("bank")
            shore, money = result.entries[0].definitions
            self.assertEqual(shore.examples, [])
            self.assertEqual(money.examples[0].example_text, "我去銀行存錢。")

    def test_legacy_examples_keep_only_chinese_text(self):
        result = DefinitionSchema.model_validate({
            "en_definition": "",
            "examples": [
                {"example_text": "The bank is closed."},
                {"example_text": "I went to the bank. 我去银行存钱。"},
            ],
        })
        self.assertEqual([example.example_text for example in result.examples], ["我去銀行存錢。"])
