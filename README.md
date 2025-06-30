# Dictionary API

取得英文單字定義、音標與例句。

## 📋 功能特色

- 🔍 單字查詢：提供完整詞性、定義、音標和例句
- 📚 批次查詢：一次查詢多個單字
- 🌍 中英對照：英文定義搭配中文翻譯
- 🎯 RESTful API：標準化 HTTP 介面
- 📖 自動文件：Swagger UI 互動式文件
- 🚀 雲端部署：支援 Render 一鍵部署

## 🚀 快速開始

### 本地開發

1. **安裝依賴**

```bash
pip install -r requirements.txt
```

2. **啟動服務**

```bash
python api.py
# 或
uvicorn api:app --reload
```

3. **測試 API**

- 服務地址：http://localhost:8000
- API 文件：http://localhost:8000/docs

### 雲端部署（Render）

1. **準備 GitHub 倉庫**
    - 將專案推送到 GitHub

2. **建立 Render 服務**
    - 前往 [Render Dashboard](https://dashboard.render.com/)
    - 點擊「New → Web Service」
    - 連接 GitHub 倉庫

3. **設定部署參數**
   ```
   Name: dictionary-api（或任意名稱）
   Language: Python 3
   Branch: main
   Build Command: pip install -r requirements.txt
   Start Command: uvicorn api:app --host 0.0.0.0 --port $PORT
   ```

4. **部署完成**
    - Render 會自動分配 URL：`https://your-service.onrender.com`

## 📡 API 使用說明

### 基礎 URL

```
https://your-service.onrender.com
```

### 端點說明

#### 1. 查詢單字

```http
GET /api/v1/word/{word}
```

**範例**

```bash
curl https://your-service.onrender.com/api/v1/word/adjust
```

**回應格式**

```json
{
  "word": "adjust",
  "pronunciations": {
    "uk": "/əˈdʒʌst/",
    "us": "/əˈdʒʌst/"
  },
  "entries": [
    {
      "part_of_speech": "verb",
      "definitions": [
        {
          "en_definition": "to change something slightly to make it fit, work better, or be more suitable",
          "zh_definition": "調整；使適合",
          "examples": [
            "You can adjust the chair height to suit you. 您可以調整椅子的高度以適合您。"
          ]
        }
      ]
    }
  ]
}
```

#### 2. 批次查詢

```http
GET /api/v1/words?words=word1,word2,word3
```

**範例**

```bash
curl "https://your-service.onrender.com/api/v1/words?words=adjust,consent,advice"
```

**回應格式**

```json
{
  "adjust": {
    "word": "adjust",
    "pronunciations": {...},
    "entries": [...]
  },
  "consent": {
    "word": "consent",
    "pronunciations": {...},
    "entries": [...]
  },
  "advice": {
    "word": "advice",
    "pronunciations": {...},
    "entries": [...]
  }
}
```

### 錯誤處理

- **404 Not Found**：查無相關詞條
- **500 Internal Server Error**：伺服器內部錯誤

## 🛠️ 技術架構

### 核心技術棧

- **FastAPI**：現代化 Python Web 框架
- **BeautifulSoup4**：HTML 解析與網頁爬蟲
- **Requests**：HTTP 請求處理
- **Uvicorn**：ASGI 伺服器

### 專案結構

```
├── api.py              # FastAPI 應用程式主檔
├── LinCrawers.py       # 劍橋字典爬蟲核心邏輯
├── requirements.txt    # Python 依賴套件
├── render.yaml        # Render 部署設定
└── README.md          # 專案文件
```

### 資料流程

1. 客戶端發送 HTTP 請求
2. FastAPI 路由處理請求
3. 呼叫爬蟲函式查詢劍橋字典
4. 解析 HTML 並提取所需資料
5. 格式化為 JSON 回應
6. 回傳結構化資料給客戶端

## ⚙️ 進階設定

### 自訂設定

#### 修改 User-Agent

在 `LinCrawers.py` 中修改：

```python
HEADERS = {
    "User-Agent": "YourApp/1.0 (Platform) +mailto:your-email@domain.com"
}
```

#### 調整請求延遲

```python
DELAY_RANGE = (1.0, 3.0)  # 1-3秒隨機延遲
```

#### 修改 API 文件標題

在 `api.py` 中：

```python
app = FastAPI(
    title="Your Custom API Title",
    description="Your API description",
    version="1.0.0"
)
```

### CORS 設定

預設允許所有來源，如需限制可修改：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # 指定允許的網域
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)
```

## 🔧 常見問題

### Q: 如何處理中文查詢？

A: 目前專為英文單字設計，中文查詢可能無法正常運作。

### Q: API 有使用頻率限制嗎？

A: 為避免對劍橋字典造成負擔，爬蟲內建 1-2 秒隨機延遲。建議合理使用。

### Q: 如何處理查詢失敗？

A: API 會回傳適當的 HTTP 狀態碼：

- 404：找不到該單字
- 500：伺服器錯誤

### Q: Render 免費方案的限制？

A:

- 服務閒置 15 分鐘後會休眠
- 每月 750 小時免費使用時數
- 首次喚醒可能需要 30 秒

### Q: 如何監控 API 狀態？

A: 可透過以下方式：

- Render Dashboard 查看部署狀態
- 訪問 `/docs` 確認服務正常
- 定期呼叫測試端點

## 📄 授權條款

本專案僅供學習和個人使用。請遵守劍橋字典的使用條款，避免過度請求造成服務負擔。

## 🤝 貢献指南

歡迎提交 Issue 和 Pull Request！

1. Fork 專案
2. 建立功能分支：`git checkout -b feature/new-feature`
3. 提交變更：`git commit -m 'Add new feature'`
4. 推送分支：`git push origin feature/new-feature`
5. 提交 Pull Request

## 📞 聯絡資訊

如有問題或建議，歡迎透過 GitHub Issues 聯繫。

---

**⚠️ 重要提醒**：本專案為教育目的，請合理使用並遵守相關網站的服務條款。
