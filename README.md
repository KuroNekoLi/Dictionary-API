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

### 免費本機 ECDICT 詞庫

服務會查本機 WordNet 詞義索引和既有 words.db 快取，接著按順序查 ECDICT CSV 匯入索引、ECDICT 1.0.28 SQLite 版，最後才使用 Cambridge。若查得到有中文例句的 WordNet 詞條，回傳該詞條的分義資料並沿用現有音標。

ECDICT CSV 來源是 skywind3000/ECDICT（https://github.com/skywind3000/ECDICT），授權檔保存在 data/ECDICT-LICENSE。原始 CSV 和產生的 data/ecdict.db 留在 VPS，不納入 Git。回應沿用既有 /word/{word} 格式；ECDICT 資料提供一般音標與中文釋義，沒有英美腔調區分或例句。API 輸出前會以 OpenCC `s2twp` 將中文釋義及例句中的中文轉為台灣繁體（含常用詞彙），原始字典資料不會被改寫。

更新詞庫時，在 data/ 放入最新版 ecdict.csv 和授權檔，再執行：

    python -m app.infrastructure.db.import_ecdict

把 [ECDICT 1.0.28 的 SQLite 版](https://github.com/skywind3000/ECDICT/releases/tag/1.0.28) 解出的 `stardict.db` 放到 `data/ecdict-release-28.db` 即可啟用補充索引。此版有 3,402,564 筆詞條，沒有可用的例句。

### 按詞義查詢與繁體中文例句

詞義索引將 [OMW English Wordnet 2.0](https://github.com/omwn/omw-data/releases/tag/v2.0) 與 [Chinese Open Wordnet 1.1](https://bond-lab.github.io/cow/) 的詞義透過共用的 ILI ID 對齊。詞網收錄的中文例句直接隸屬該詞義，另外用 `reviewed_examples.tsv` 為常見詞補上逐義撰寫的繁體例句。`translated_examples.tsv` 補入已篩選校訂的 WordNet 例句，使用 [Helsinki-NLP OPUS-MT](https://huggingface.co/Helsinki-NLP/opus-mt-en-zh) 離線翻譯，保留原詞義 ID，回應標為機翻校訂。API 執行期間只讀 SQLite。缺少可靠例句的詞義仍可查詢。

取得兩個詞網官方壓縮檔並解壓，保留每份 XML 旁的 LICENSE。把以下命令的路徑換成解壓位置：

    python -m app.infrastructure.db.import_wordnet omw-en/omw-en.xml cow/cow-1.1.xml

索引會寫到 `data/wordnet.db`，包含詞網的授權聲明。API 保留 `examples[].example_text` 並提供可選的 `source`、`author`、`source_url`、`license_url`、`match_type`。中文文字統一為台灣繁體。

## FAQ

- 如遇 "unable to open database file"，請檢查 `data/` 資料夾權限與路徑。
- 進階查詢/分詞/批量接口或其它擴充功能，請見 usecases/ 增加相應業務邏輯。
