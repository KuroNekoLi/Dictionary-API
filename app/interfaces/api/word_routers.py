from fastapi import APIRouter, HTTPException, Query
from app.interfaces.schemas.word_schema import WordSchema
from app.usecases.word_query import QueryWordUsecase
from app.infrastructure.db.sqlite_word_repository import SqliteDictionaryRepository
from app.infrastructure.external.cambridge_crawler import CambridgeCrawler
from dataclasses import asdict
from typing import Dict

router = APIRouter()

repo = SqliteDictionaryRepository()
crawler = CambridgeCrawler()
usecase = QueryWordUsecase(repo, crawler)


@router.get("/{word}", response_model=WordSchema)
def get_word(word: str):
    """
    使用者查詢流程：
    1. 先查 sqlite 資料庫
    2. 沒有則啟動爬蟲
    3. 回存新資料進資料庫
    4. 統一回應
    """
    try:
        word_obj = usecase.query_word(word)
        return WordSchema.model_validate(asdict(word_obj))
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/batch", response_model=Dict[str, WordSchema])
def get_words_batch(words: str = Query(..., description="以逗號分隔的英文單字清單")):
    """
    批次查詢單字：words=word1,word2,word3
    每個單字皆走快取/爬蟲/回存流程，失敗則回傳錯誤內容。
    """
    word_list = [w.strip() for w in words.split(",") if w.strip()]
    results = {}
    for w in word_list:
        try:
            obj = usecase.query_word(w)
            results[w] = WordSchema.model_validate(asdict(obj))
        except Exception as e:
            results[w] = {"error": str(e)}
    return results
