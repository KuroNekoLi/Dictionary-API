from app.domain.models.word import Word, Pronunciations, Entry, Definition, Example
import requests
from bs4 import BeautifulSoup
import re


class CambridgeCrawler:
    HEADERS = {
        "User-Agent": "TOEICPractice/1.0 (Android 15; Pixel 9) +mailto:abc@gmail.com"
    }
    BASE_URL = "https://dictionary.cambridge.org/zht/詞典/英語-漢語-繁體/"

    @staticmethod
    def clean_text(text: str) -> str:
        if not text:
            return text
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\s+([,.!?;:])', r'\1', text)
        text = re.sub(r'\s*\(\s*', ' (', text)
        text = re.sub(r'\s*\)\s*', ') ', text)
        text = re.sub(r'\s*/\s*', '/', text)
        return text.strip()

    def fetch_word(self, word: str) -> Word:
        url = f"{self.BASE_URL}{word}"
        resp = requests.get(url, headers=self.HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        pronunciations = Pronunciations()
        uk_pron = soup.select_one(".uk.dpron-i .ipa.dipa")
        if uk_pron:
            pronunciations.uk = uk_pron.get_text(strip=True)
        us_pron = soup.select_one(".us.dpron-i .ipa.dipa")
        if us_pron:
            pronunciations.us = us_pron.get_text(strip=True)
        entries = []
        entry_blocks = soup.select(".pr.entry-body__el")

        for entry_block in entry_blocks:
            pos_element = entry_block.select_one(".pos.dpos")
            part_of_speech = pos_element.get_text(strip=True) if pos_element else ""
            definitions = []
            def_blocks = entry_block.select(".def-block.ddef_block")
            for def_block in def_blocks:
                en_def = def_block.select_one(".def.ddef_d.db")
                if not en_def:
                    continue
                en_text = self.clean_text(en_def.get_text(separator=' ', strip=True))
                zh_text = ""
                trans_elements = def_block.select(".trans.dtrans")
                for trans in trans_elements:
                    if trans.select(".dtrans"):
                        zh_text = trans.get_text(strip=True)
                        break
                examples = []
                example_blocks = def_block.select(".examp.dexamp")
                for ex_block in example_blocks:
                    en_example = ex_block.select_one(".eg.deg")
                    zh_example = ex_block.select_one(".trans.dtrans")
                    if en_example:
                        en_text_example = self.clean_text(en_example.get_text(separator=' ', strip=True))
                        zh_text_example = zh_example.get_text(strip=True) if zh_example else ""
                        val = f"{en_text_example} {zh_text_example}" if zh_text_example else en_text_example
                        examples.append(Example(val))
                definitions.append(Definition(en_definition=en_text, zh_definition=zh_text, examples=examples))
            if definitions:
                entries.append(Entry(part_of_speech=part_of_speech, definitions=definitions))
        return Word(word=word, pronunciations=pronunciations, entries=entries)
