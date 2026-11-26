from app.domain.models.word import Pronunciations, Word
from app.domain.repositories.word_repository import DictionaryRepository
from app.infrastructure.external.cambridge_crawler import CambridgeCrawler


class QueryWordUsecase:
    def __init__(self, repo: DictionaryRepository, crawler: CambridgeCrawler, ecdict_repo=None, wordnet_repo=None):
        self.repo = repo
        self.crawler = crawler
        self.ecdict_repo = ecdict_repo
        self.wordnet_repo = wordnet_repo

    def query_word(self, word: str) -> Word:
        db_word = self.repo.get_word(word)
        wordnet_word = self.wordnet_repo.get_word(word) if self.wordnet_repo else None
        if wordnet_word:
            cached = db_word.pronunciations if db_word else Pronunciations()
            cached.uk = cached.uk or wordnet_word.pronunciations.uk
            cached.us = cached.us or wordnet_word.pronunciations.us
            ecdict_word = self.ecdict_repo.get_word(word) if self.ecdict_repo else None
            if ecdict_word:
                cached.phonetic = cached.phonetic or ecdict_word.pronunciations.phonetic
                wordnet_word.entries.extend(ecdict_word.entries)
            wordnet_word.pronunciations = cached
            return wordnet_word
        if db_word:
            return db_word
        ecdict_word = self.ecdict_repo.get_word(word) if self.ecdict_repo else None
        if ecdict_word:
            return ecdict_word
        word_obj = self.crawler.fetch_word(word)
        self.repo.save_word(word_obj)
        return word_obj
