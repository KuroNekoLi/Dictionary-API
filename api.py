from fastapi import FastAPI, HTTPException, Query
import logging
from fastapi.middleware.cors import CORSMiddleware

# 我們重用既有的爬蟲函式
from LinCrawers import fetch_cambridge_entry

# 初始化 FastAPI
app = FastAPI(
    title="DictionaryApi",
    description="本 API 用於取得英文單字的定義、音標、詞性與例句。支援查詢單一或多個單字，資料來源為劍橋字典。",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== 共用函式 =====

def _scrape_word(word: str) -> dict:
    """呼叫既有爬蟲並處理可能的錯誤。"""
    try:
        data = fetch_cambridge_entry(word)
        if not data.get("entries"):
            raise ValueError("查無相關詞條")
        return data
    except Exception as e:
        logging.exception(f"Scrape failed for word={word}: {e}")
        raise


# ===== API Endpoints =====

@app.get(
    "/api/v1/word/{word}",
    summary="查詢單字",
    description="查詢單一英文單字的定義、音標、詞性與例句。"
)
async def get_single_word(word: str):
    """查詢單一英文單字的定義、音標、詞性與例句。"""
    try:
        return _scrape_word(word)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal Server Error")


@app.get(
    "/api/v1/words",
    summary="批量查詢多個單字",
    description="一次查詢多個英文單字的定義、音標、詞性與例句。請以逗號分隔單字，例如 words=apple,banana,cat"
)
async def get_multiple_words(words: str = Query(..., description="以逗號分隔的英文單字清單，例如 adjust,consent")):
    """批次查詢多個英文單字的定義、音標、詞性與例句。"""
    word_list = [w.strip() for w in words.split(',') if w.strip()]

    results = {}
    for w in word_list:
        try:
            results[w] = _scrape_word(w)
        except Exception as e:
            # 若單字失敗，僅回傳錯誤訊息，不影響其他單字
            results[w] = {"error": str(e)}
    return results


# ===== 以 uvicorn 執行（本地測試用） =====
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
