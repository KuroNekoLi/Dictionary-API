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

### 單一資料庫與 ECDICT 詞庫

服務只使用一份作用中的 SQLite 資料庫：`data/wordnet.db`。這份資料庫包含 WordNet 詞義與例句、ECDICT 詞條、Word Atlas 完整詞條、Complete_Dictionary 定義與雙語例句，以及舊查詢快取。查詢不再依賴分散的執行期資料庫；來源 SQLite 檔保留在 VPS 作為匯入來源與回復備份。

ECDICT 主詞庫取自 skywind3000/ECDICT，1.0.28 SQLite 版有 3,402,564 筆詞條。整併後的 `ecdict_entries` 提供音標和中文釋義；WordNet 與 Word Atlas 提供英文詞義及雙語例句。OpenCC `s2twp` 會將匯入的中文轉為台灣繁體。

部署時以 `app.infrastructure.db.merge_dictionary_sources` 將現有 ECDICT、快取資料庫、固定版 Word Atlas 和 Complete_Dictionary 合併到 `wordnet.db`。Complete_Dictionary 使用 `Complete_Dictionary.7z`（下載後 CSV 約 267 MB），匯入 770,611 筆單字記錄及 546,944 組可配對的英中例句。其詞義與例句維持字詞層級，API 不會把它們誤標成 WordNet 個別詞義例句。例句來源資訊隨記錄一起回傳。

### 按詞義查詢與繁體中文例句

詞義索引將 [OMW English Wordnet 2.0](https://github.com/omwn/omw-data/releases/tag/v2.0) 與 [Chinese Open Wordnet 1.1](https://bond-lab.github.io/cow/) 的詞義透過共用的 ILI ID 對齊。詞網收錄的中文例句直接隸屬該詞義，另外用 `reviewed_examples.tsv` 為常見詞補上逐義撰寫的繁體例句。`translated_examples.tsv` 補入已篩選校訂的 WordNet 例句，使用 [Helsinki-NLP OPUS-MT](https://huggingface.co/Helsinki-NLP/opus-mt-en-zh) 離線翻譯，保留原詞義 ID，回應標為機翻校訂。API 執行期間只讀 SQLite。缺少可靠例句的詞義仍可查詢。

`batch_wordnet_examples.tsv` 補入同一 ILI 的 WordNet 英文例句離線譯文，回應標為「自動翻譯」。這批資料經詞義關鍵詞、英文句子結構和回譯檢查，仍可能有翻譯瑕疵。`word_atlas_examples.tsv` 只收錄已核對的單字與 ILI 組合，用於仍缺例句的詞義。[Word Atlas](https://github.com/designfuchen/word-atlas/blob/main/README.en.md#open-dataset) 的例句由 Word Atlas contributors（词光）提供，依 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 使用並轉成繁體。

`checked_wordnet_examples.tsv` 是同一 WordNet 詞義原有英文例句的離線譯文候選，經回譯相似度篩選後匯入，仍屬自動翻譯，並非人工逐句校對。

`common_word_examples.tsv` 累計為 6,000 個常見單字加入英中雙語例句，按 ECDICT 詞頻排序；沒有 ECDICT 頻率的少數詞條按 Word Atlas 的 CEFR 程度排序。資料取自 Word Atlas 的第一個常用詞義和第一條例句；先按詞性及英文、中文定義比對 WordNet，無法可靠對應時保留 Word Atlas 自己的詞性與雙語詞義，避免把例句放到意思不符的詞義下。API 例句會同時顯示英文原句與台灣繁體中文翻譯，並保留 Word Atlas 來源資訊。

`word_atlas_source.json`（commit `4ff9c429745c12506a9d07d3c29f0791a66191d5`，SHA-256 `E4E3410809047711CD2A25FCCAFCEBB46124CE1EEB98829DC12DE0335DE71234`）保留固定版本的完整 Word Atlas 詞條。重建索引時，所有 7,298 個字詞的 13,733 個詞義與 14,596 個雙語例句會寫入獨立的 `word_atlas` 資料表，並由 `/word/{word}` 回傳為頂層 `word_atlas` 欄位。Word Atlas 的例句只標註到字詞，沒有逐句詞義標籤，因此保留在獨立欄位，不冒充 WordNet 詞義例句。回應保留英美音標、詞性、英文／中文定義、例句、分類與來源署名；中文轉為台灣繁體。來源內容由 AI 生成、經自動檢查但未逐條人工審校；授權與修改說明見 `WORD_ATLAS_CONTENT_LICENSE.md` 及資料庫 `licenses` 表。署名為 `Word Atlas contributors — CC BY 4.0`。

`tatoeba_examples.tsv` 收錄經英文詞形及繁體中文釋義比對的句對，保留兩個 Tatoeba 句子頁面連結以供作者署名查核；文字依 [CC BY 2.0 FR](https://creativecommons.org/licenses/by/2.0/fr/) 使用，中文轉為台灣繁體。依目前匯入快照，6,000 個目標詞共有 18,981 個 WordNet 詞義，其中 9,785 個已有雙語例句，9,196 個仍缺少雙語例句。這些資料源尚未覆蓋所有詞義，不能將「每個詞義都有例句」視為已完成。

取得兩個詞網官方壓縮檔並解壓，保留每份 XML 旁的 LICENSE。把以下命令的路徑換成解壓位置：

    python -m app.infrastructure.db.import_wordnet omw-en/omw-en.xml cow/cow-1.1.xml

重跑自動翻譯時，使用 Python 3.12 以上、`ctranslate2`、`sentencepiece`、`nltk` 及 `averaged_perceptron_tagger_eng`。解開 [CTranslate2 格式的 OPUS-MT 英中與中英模型](https://huggingface.co/Unbakedcookie/live-translator-models)，準備尚未加入新批次的 SQLite 索引，然後執行：

    python -m app.infrastructure.db.translate_wordnet_examples omw-en/omw-en.xml data/wordnet.db opus-mt-en-zh candidate-examples.tsv
    python -m app.infrastructure.db.check_wordnet_translations candidate-examples.tsv opus-mt-zh-en checked-examples.tsv
    python -m app.infrastructure.db.import_wordnet omw-en/omw-en.xml cow/cow-1.1.xml --batch-examples checked-examples.tsv

索引會寫到 `data/wordnet.db`，包含詞網的授權聲明。API 保留 `examples[].example_text` 並提供可選的 `source`、`author`、`source_url`、`license_url`、`match_type`。中文文字統一為台灣繁體。

## FAQ

- 如遇 "unable to open database file"，請檢查 `data/` 資料夾權限與路徑。
- 進階查詢/分詞/批量接口或其它擴充功能，請見 usecases/ 增加相應業務邏輯。
