# Dictionary API (Clean Architecture)

本專案採用現代 Python Clean Architecture 分層，具備：

- 本地 SQLite 快取／永續
- 劍橋字典爬蟲
- 完整單字定義查詢，支援擴充
- 測試資料請查詢 /word/{word} route

---

## 專案目錄結構

```
app/
├── domain/
│   ├── models/word.py          # Entity/Value Object
│   └── repositories/word_repository.py   # Repository interface
├── usecases/word_query.py      # 業務邏輯（無第三方依賴）
├── infrastructure/
│   ├── db/sqlite_word_repository.py      # SQLite 實作
│   └── external/cambridge_crawler.py    # 劍橋爬蟲
├── interfaces/
│   ├── api/word_routers.py              # FastAPI routers
│   └── schemas/word_schema.py           # Pydantic schema
├── main.py                 # 啟動/路由註冊點
├── init_db.py              # DB 初始化腳本
```

---

## 安裝與啟動

```bash
# 安裝依賴
pip install -r requirements.txt

# 初始化資料庫 (只需首次執行)
python app/init_db.py

# 啟動 API
uvicorn app.main:app --reload
# 或
python app/main.py
```

## API 測試

打開 [http://localhost:8000/docs](http://localhost:8000/docs)

或：

```bash
curl -X GET 'http://localhost:8000/word/adjust' -H 'accept: application/json'
```

- 第一次查會自動爬蟲快取，之後每次查皆走資料庫。

### 範例回應格式

```json
{
  "word": "adjust",
  "pronunciations": {"uk": "əˈdʒʌst", "us": "əˈdʒʌst"},
  "entries": [
    {
      "part_of_speech": "verb",
      "definitions": [
        {"en_definition": "...", "zh_definition": "...", "examples": [{"example_text": "..."}]}
      ]
    }
  ]
}
```

---

## 架構說明

- **domain/** 完全獨立，僅描述物件/約定/行為
- **infrastructure/** 實作細節，與 domain interface 解耦
- **usecases/** 只依賴 domain、repositories，不碰 API/database 實作
- **interfaces/** 提供所有對外 API/Schema，獨立於業務邏輯
- **main.py** 僅用於組裝（注入 DI/路由），後續測試/擴充都集中於這裡

---

## FAQ

- 如遇 "unable to open database file"，請檢查 `data/` 資料夾權限與路徑。
- 進階查詢/分詞/批量接口或其它擴充功能，請見 usecases/ 增加相應業務邏輯。
