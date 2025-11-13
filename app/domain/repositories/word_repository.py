from typing import Optional, List
from app.domain.models.word import Word


class DictionaryRepository:
    def get_word(self, word: str) -> Optional[Word]:
        raise NotImplementedError

    def save_word(self, word_obj: Word):
        raise NotImplementedError

    def get_words(self, words: List[str]) -> List[Word]:
        raise NotImplementedError
