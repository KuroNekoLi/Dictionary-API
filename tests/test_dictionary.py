import json
import sqlite3
import tempfile
import unittest
import zlib
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from opencc import OpenCC

from app.domain.models.word import Word
from app.infrastructure.db.ecdict_repository import EcdictRepository
from app.infrastructure.db.import_wordnet import (
    ATLAS_AUTHOR,
    ATLAS_LICENSE,
    _index_atlas_examples,
    _index_common_word_examples,
    _index_complete_dictionary_data,
    _index_ecdict_database,
    _index_tatoeba_examples,
    _index_translated_examples,
    _index_word_atlas_data,
)
from app.infrastructure.db.wordnet_repository import WordnetRepository
from app.interfaces.schemas.word_schema import DefinitionSchema, WordSchema
from app.usecases.word_query import QueryWordUsecase


class DictionaryTest(unittest.TestCase):
    def test_tatoeba_pairs_keep_sentence_attribution_and_traditional_chinese(self):
        with tempfile.TemporaryDirectory() as folder, closing(sqlite3.connect(":memory:")) as conn:
            conn.executescript("""
                CREATE TABLE senses(word, synset);
                CREATE TABLE examples(
                    word, synset, text, source, author, source_url, license_url, match_type, priority,
                    PRIMARY KEY(word, synset, text)
                );
                INSERT INTO senses VALUES ('bank', 'shore');
            """)
            source = Path(folder) / "tatoeba.tsv"
            source.write_text(
                "word\tsynset\ten_example\tzh_example\ten_author\tzh_author\ten_id\tzh_id\n"
                "bank\tshore\tThey sat by the river bank.\t他們坐在河边。\t\tcontributor\t123\t456\n",
                encoding="utf-8",
            )
            _index_tatoeba_examples(conn, source, lambda value: value.replace("边", "邊"))
            row = conn.execute("SELECT * FROM examples").fetchone()
            self.assertEqual(row[2], "They sat by the river bank.\n他們坐在河邊。")
            self.assertEqual(row[3], "Tatoeba")
            self.assertIn("https://tatoeba.org/en/sentences/show/123", row[5])
            self.assertIn("contributor", row[4])

    def test_imported_sources_fill_only_matching_uncovered_senses(self):
        with tempfile.TemporaryDirectory() as folder, sqlite3.connect(":memory:") as conn:
            conn.executescript("""
                CREATE TABLE senses(word, synset);
                CREATE TABLE examples(
                    word, synset, text, source, author, source_url, license_url, match_type, priority
                );
                INSERT INTO senses VALUES ('bank', 'money'), ('bank', 'shore'), ('riverbank', 'shore'),
                                          ('lender', 'credit'), ('stream', 'water');
                INSERT INTO examples VALUES ('bank', 'money', '我去銀行。', '自編例句',
                                             NULL, NULL, NULL, 'editorial', 0);
            """)
            batch_file = Path(folder) / "batch.tsv"
            batch_file.write_text(
                "synset\texample\tenglish\n"
                "money\t銀行將這筆款項安全保管。\tThe bank kept the money safe.\n"
                "credit\t貸方同意向公司提供信用貸款。\tThe lender extended credit to the company.\n",
                encoding="utf-8",
            )
            atlas_file = Path(folder) / "atlas.tsv"
            atlas_file.write_text(
                "word\tsynset\texample\nbank\tshore\t她沿著河岸散步。\n"
                "bank\tmoney\t這句不能覆蓋。\n", encoding="utf-8",
            )
            _index_translated_examples(conn, batch_file, str, reviewed=False)
            _index_atlas_examples(conn, atlas_file, str)
            self.assertEqual(
                conn.execute("SELECT word, synset, match_type FROM examples ORDER BY word, synset").fetchall(),
                [("bank", "money", "editorial"), ("bank", "money", "machine_translation"),
                 ("bank", "shore", "reviewed_atlas_mapping"),
                 ("lender", "credit", "machine_translation")],
            )
            self.assertEqual(
                conn.execute("SELECT text FROM examples WHERE word = 'bank' AND synset = 'money' AND instr(text, char(10)) > 0").fetchone()[0],
                "The bank kept the money safe.\n銀行將這筆款項安全保管。",
            )
            self.assertEqual(
                conn.execute("SELECT author, license_url FROM examples WHERE synset = 'shore'").fetchone(),
                (ATLAS_AUTHOR, ATLAS_LICENSE),
            )

    def test_imports_word_atlas_second_example_as_bilingual_and_attributed(self):
        with tempfile.TemporaryDirectory() as folder, closing(sqlite3.connect(":memory:")) as conn:
            conn.executescript("""
                CREATE TABLE senses(word, synset, pos, en, zh, PRIMARY KEY(word, synset));
                CREATE TABLE examples(
                    word, synset, text, source, author, source_url, license_url, match_type, priority,
                    PRIMARY KEY(word, synset, text)
                );
                INSERT INTO senses VALUES ('say', 'i113123', 'n', 'the chance to speak', '發言權');
                INSERT INTO examples VALUES ('say', 'i113123', 'Residents have a say.\n居民有發言權。',
                    'Word Atlas', 'Word Atlas contributors（词光）', 'https://example.test/atlas',
                    'https://creativecommons.org/licenses/by/4.0/', 'common_word_atlas', -1);
            """)
            source = Path(folder) / "atlas-second.tsv"
            source.write_text(
                "word\tsynset\tpos\ten_definition\tzh_definition\ten_example\tzh_example\tfrequency_rank\n"
                "say\ti113123\tn\t\t\tResidents should have a say in local decisions.\t居民應對地方決策有發言權。\t1\n",
                encoding="utf-8",
            )
            _index_common_word_examples(conn, source, str)
            rows = conn.execute(
                "SELECT text, source, author, license_url FROM examples WHERE word='say' ORDER BY text"
            ).fetchall()
            self.assertEqual(len(rows), 2)
            added = next(row for row in rows if "local decisions" in row[0])
            self.assertEqual(added[0], "Residents should have a say in local decisions.\n居民應對地方決策有發言權。")
            self.assertEqual(added[1], "Word Atlas")
            self.assertEqual(added[2], ATLAS_AUTHOR)
            self.assertEqual(added[3], ATLAS_LICENSE)

    def test_imports_complete_word_atlas_entries_without_sense_mapping(self):
        with tempfile.TemporaryDirectory() as folder, closing(sqlite3.connect(":memory:")) as conn:
            conn.execute("CREATE TABLE word_atlas(word TEXT PRIMARY KEY, data TEXT NOT NULL)")
            source = Path(folder) / "word-atlas.json"
            source.write_text(json.dumps([{
                "w": "Novelty",
                "uk": "/nɒvəlti/",
                "us": "/nɑːvəlti/",
                "senses": [
                    {"pos": "n.", "en": "A new or unusual thing.", "zh": "新事物"},
                    {"pos": "n.", "en": "The quality of being new.", "zh": "新颖性"},
                ],
                "ex": [
                    {"en": "The novelty attracted many visitors.", "zh": "新颖性吸引了许多访客。"},
                    {"en": "The museum relies on novelty to attract visitors.", "zh": "博物馆依靠新奇感吸引参观者。"},
                ],
                "topic": "culture",
            }], ensure_ascii=False), encoding="utf-8")
            converter = OpenCC("s2twp.json").convert
            _index_word_atlas_data(conn, source, converter)
            word, data = conn.execute("SELECT word, data FROM word_atlas").fetchone()
            record = json.loads(data)
            self.assertEqual(word, "novelty")
            self.assertEqual([sense["en"] for sense in record["senses"]], [
                "A new or unusual thing.", "The quality of being new.",
            ])
            self.assertEqual(record["ex"][0]["zh"], "新穎性吸引了許多訪客。")
            self.assertEqual(len(record["ex"]), 2)
            self.assertEqual(record["provenance"]["author"], ATLAS_AUTHOR)
            self.assertEqual(record["provenance"]["license_url"], ATLAS_LICENSE)
            self.assertIn("word-level", record["provenance"]["changes"])

    def test_word_atlas_only_entry_is_returned_by_api_shape_and_keeps_wordnet_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            index = Path(folder) / "index.db"
            atlas_record = {
                "w": "novelty",
                "uk": "/nɒvəlti/",
                "us": "/nɑːvəlti/",
                "senses": [{"pos": "n.", "en": "A new or unusual thing.", "zh": "新事物"}],
                "ex": [
                    {"en": "The novelty attracted many visitors.", "zh": "新颖性吸引了許多访客。"},
                    {"en": "The museum relies on novelty.", "zh": "博物館依賴新奇感。"},
                ],
            }
            with closing(sqlite3.connect(index)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE senses(word, synset, pos, sense_number, frequency, en, zh);
                    CREATE TABLE examples(
                        word, synset, text, source, author, source_url, license_url, match_type, priority
                    );
                    CREATE TABLE word_atlas(word TEXT PRIMARY KEY, data TEXT NOT NULL);
                """)
                conn.execute("INSERT INTO word_atlas VALUES (?, ?)", ("novelty", json.dumps(atlas_record)))

            class Cache:
                def get_word(self, word):
                    return Word(word)

            result = QueryWordUsecase(Cache(), None, wordnet_repo=WordnetRepository(index)).query_word("NOVELTY")
            response = WordSchema.model_validate(asdict(result))
            self.assertEqual(response.word, "novelty")
            self.assertEqual(response.pronunciations.uk, "/nɒvəlti/")
            self.assertEqual(response.entries, [])
            self.assertEqual(len(response.word_atlas["ex"]), 2)

    def test_complete_dictionary_rows_keep_definitions_and_bilingual_examples(self):
        with tempfile.TemporaryDirectory() as folder, closing(sqlite3.connect(":memory:")) as conn:
            conn.execute("CREATE TABLE complete_dictionary(word TEXT PRIMARY KEY, data TEXT NOT NULL)")
            source = Path(folder) / "complete.csv"
            source.write_text(
                "wordID,wordContent,phonetic_EN,phonetic_US,definition,translation,wordTags,wordExchanges,"
                "bncLevel,frqLevel,collinsLevel,oxfordLevel,exampleSentences\n"
                "1,example,/ɪɡˈzɑːmpəl/,/ɪɡˈzæmpəl/,something illustrative,例子,名詞,,1,2,3,4,"
                "This is an example.<br>這是一個例子。\n",
                encoding="utf-8",
            )
            _index_complete_dictionary_data(conn, source, OpenCC("s2twp.json").convert)
            word, raw_data = conn.execute("SELECT word, data FROM complete_dictionary").fetchone()
            record = json.loads(zlib.decompress(raw_data).decode("utf-8"))
            self.assertEqual(word, "example")
            self.assertEqual(record["definition"], "something illustrative")
            self.assertEqual(record["translation"], "例子")
            self.assertEqual(record["examples"], [{"en": "This is an example.", "zh": "這是一個例子。"}])

    def test_unified_database_query_returns_ecdict_definitions_and_complete_examples(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "wordnet.db"
            with closing(sqlite3.connect(database)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE senses(word, synset, pos, sense_number, frequency, en, zh);
                    CREATE TABLE examples(word, synset, text, source, author, source_url, license_url, match_type, priority);
                    CREATE TABLE word_atlas(word TEXT PRIMARY KEY, data TEXT NOT NULL);
                    CREATE TABLE complete_dictionary(word TEXT PRIMARY KEY, data TEXT NOT NULL);
                    CREATE TABLE ecdict_entries(normalized_word TEXT PRIMARY KEY, word, phonetic, translation);
                    INSERT INTO senses VALUES ('example', 'i1', 'n', 1, 1, 'A representative form', '範例');
                    INSERT INTO complete_dictionary VALUES ('example', '{"source":"Complete Dictionary","examples":[{"en":"This is an example.","zh":"這是一個例子。"}]}');
                    INSERT INTO ecdict_entries VALUES ('example', 'example', '/ɪɡˈzæmpəl/', 'n. 例子\\n示例');
                """)

            ecdict = EcdictRepository(database, Path(folder) / "missing-release.db")
            result = QueryWordUsecase(
                repo=type("Cache", (), {"get_word": lambda self, word: None})(),
                crawler=None,
                ecdict_repo=ecdict,
                wordnet_repo=WordnetRepository(database),
            ).query_word("EXAMPLE")
            response = WordSchema.model_validate(asdict(result))
            self.assertEqual(response.entries[0].definitions[0].en_definition, "A representative form")
            self.assertIn("示例", [definition.zh_definition for definition in response.entries[-1].definitions])
            self.assertEqual(response.complete_dictionary["examples"][0]["zh"], "這是一個例子。")

    def test_uses_release_only_when_the_current_ecdict_has_no_word(self):
        with tempfile.TemporaryDirectory() as folder:
            current, release = (Path(folder) / name for name in ("current.db", "release.db"))
            with closing(sqlite3.connect(current)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE words(word, phonetic, translation, normalized_word);
                    INSERT INTO words VALUES ('apple', '', 'n. 蘋果', 'apple');
                """)
            with closing(sqlite3.connect(release)) as conn, conn:
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
            with closing(sqlite3.connect(index)) as conn, conn:
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
