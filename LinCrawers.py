import requests
from bs4 import BeautifulSoup
import time
import random
import logging
import re

# 日誌設定
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)

# 自訂 User-Agent，請換成您專案資訊
HEADERS = {
    "User-Agent": "TOEICPractice/1.0 (Android 15; Pixel 9) +mailto:abc@gmail.com"
}

# 每次請求之間的隨機延遲區間（秒）
DELAY_RANGE = (1.0, 2.0)

def clean_text(text: str) -> str:
    """清理文本，移除多餘空格並規範化標點符號"""
    if not text:
        return text

    # 移除多餘空格
    text = re.sub(r'\s+', ' ', text)

    # 修正標點符號前的空格
    text = re.sub(r'\s+([,.!?;:])', r'\1', text)

    # 修正括號內外的空格
    text = re.sub(r'\s*\(\s*', ' (', text)
    text = re.sub(r'\s*\)\s*', ') ', text)

    # 修正斜線前後的空格
    text = re.sub(r'\s*/\s*', '/', text)

    return text.strip()

def fetch_cambridge_entry(word: str) -> dict:
    """
    抓取指定單字的定義與例句。
    回傳格式：
    {
      "word": word,
      "pronunciations": {"uk": "音標", "us": "音標"},
      "entries": [
        {
          "part_of_speech": "詞性",
          "definitions": [
            {
              "definition": "英文定義 中文翻譯",
              "examples": ["例句1", "例句2", ...]
            },
            ...
          ]
        },
        ...
      ]
    }
    """
    url = f"https://dictionary.cambridge.org/zht/詞典/英語-漢語-繁體/{word}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 提取音標資訊
    pronunciations = {}

    # 英式音標
    uk_pron = soup.select_one(".uk.dpron-i .ipa.dipa")
    if uk_pron:
        pronunciations["uk"] = uk_pron.get_text(strip=True)

    # 美式音標
    us_pron = soup.select_one(".us.dpron-i .ipa.dipa")
    if us_pron:
        pronunciations["us"] = us_pron.get_text(strip=True)

    entries = []

    # 找出所有詞條 (每個詞性為一個詞條)
    entry_blocks = soup.select(".pr.entry-body__el")

    for entry_block in entry_blocks:
        # 提取詞性
        part_of_speech = ""
        pos_element = entry_block.select_one(".pos.dpos")
        if pos_element:
            part_of_speech = pos_element.get_text(strip=True)

        definitions = []

        # 找出該詞條下的所有定義區塊
        def_blocks = entry_block.select(".def-block.ddef_block")

        for def_block in def_blocks:
            # 英文定義
            en_def = def_block.select_one(".def.ddef_d.db")
            if not en_def:
                continue

            # 處理英文定義文本
            en_text = clean_text(en_def.get_text(separator=' ', strip=True))

            # 提取中文翻譯 - 只取真正的定義翻譯，不是例句翻譯
            zh_text = ""
            trans_elements = def_block.select(".trans.dtrans")

            for trans in trans_elements:
                # 檢查是否包含 dtrans 子標籤 (真正的定義翻譯)
                if trans.select(".dtrans"):
                    zh_text = trans.get_text(strip=True)
                    break

            # 組合定義文本
            definition_text = f"{en_text} {zh_text}" if zh_text else en_text

            # 提取該定義對應的例句
            examples = []
            example_blocks = def_block.select(".examp.dexamp")

            for ex_block in example_blocks:
                # 英文例句
                en_example = ex_block.select_one(".eg.deg")
                # 中文例句翻譯
                zh_example = ex_block.select_one(".trans.dtrans")

                if en_example:
                    en_text = clean_text(en_example.get_text(separator=' ', strip=True))
                    zh_text = zh_example.get_text(strip=True) if zh_example else ""

                    example_text = f"{en_text} {zh_text}" if zh_text else en_text
                    examples.append(example_text)

            # 將定義和其對應的例句組合
            definitions.append({
                "definition": definition_text,
                "examples": examples
            })

        # 只有當有定義時才添加詞條
        if definitions:
            entries.append({
                "part_of_speech": part_of_speech,
                "definitions": definitions
            })

    return {
        "word": word,
        "pronunciations": pronunciations,
        "entries": entries,
    }

def main():
    # 測試單字列表，可替換為你的字庫
    words = ["adjust", "consent", "advice"]
    results = []

    for w in words:
        try:
            logging.info(f"Fetching entry for '{w}'")
            entry = fetch_cambridge_entry(w)
            results.append(entry)

            # 計算總定義數和例句數
            total_definitions = sum(len(e['definitions']) for e in entry['entries'])
            total_examples = sum(len(d['examples']) for e in entry['entries'] for d in e['definitions'])
            logging.info(f"Got {len(entry['entries'])} entries, {total_definitions} definitions, {total_examples} examples")
        except Exception as e:
            logging.error(f"Error fetching '{w}': {e}")
        finally:
            # 隨機延遲，減少封鎖風險
            time.sleep(random.uniform(*DELAY_RANGE))

    # 格式化輸出
    for item in results:
        print(f"\n=== {item['word']} ===")

        # 輸出音標 - 加上斜線格式
        pron = item.get('pronunciations', {})
        if pron:
            uk_pron = pron.get('uk', '')
            us_pron = pron.get('us', '')
            # 為音標加上標準的斜線格式
            uk_formatted = f"/{uk_pron}/" if uk_pron else ""
            us_formatted = f"/{us_pron}/" if us_pron else ""
            print(f"音標：uk {uk_formatted}  us {us_formatted}")

        for entry_idx, entry in enumerate(item['entries'], 1):
            print(f"\n【{entry['part_of_speech']}】")

            for def_idx, definition in enumerate(entry['definitions'], 1):
                print(f" 定義 {def_idx}：{definition['definition']}")

                for ex_idx, example in enumerate(definition['examples'], 1):
                    print(f"   例句 {def_idx}.{ex_idx}：{example}")

                if definition['examples']:  # 如果有例句才印空行
                    print()

if __name__ == "__main__":
    main()
