from app.domain.models.word import Word
from app.domain.repositories.word_repository import DictionaryRepository
from app.infrastructure.external.cambridge_crawler import CambridgeCrawler


class QueryWordUsecase:
    def __init__(self, repo: DictionaryRepository, crawler: CambridgeCrawler, ecdict_repo=None):
        self.repo = repo
        self.crawler = crawler
        self.ecdict_repo = ecdict_repo

    def query_word(self, word: str) -> Word:
        db_word = self.repo.get_word(word)
        if db_word:
            return db_word
        if self.ecdict_repo is not None:
            ecdict_word = self.ecdict_repo.get_word(word)
            if ecdict_word:
                return ecdict_word
        word_obj = self.crawler.fetch_word(word)
        self.repo.save_word(word_obj)
        return word_obj
