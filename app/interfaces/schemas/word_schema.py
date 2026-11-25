import re

from pydantic import BaseModel, Field
from pydantic import field_validator, model_validator
from typing import List, Optional
from opencc import OpenCC


_traditional_chinese = OpenCC("s2twp.json")
_han_character = re.compile(r"[\u3400-\u9fff]")


class PronunciationsSchema(BaseModel):
    uk: Optional[str] = Field(None, description="英式發音音標")
    us: Optional[str] = Field(None, description="美式發音音標")
    phonetic: Optional[str] = Field(None, description="ECDICT 提供的未區分英美腔調音標")


class ExampleSchema(BaseModel):
    example_text: str = Field(..., description="例句；中文內容使用台灣繁體")
    source: Optional[str] = None
    author: Optional[str] = None
    source_url: Optional[str] = None
    license_url: Optional[str] = None
    match_type: Optional[str] = None

    @field_validator("example_text", mode="before")
    @classmethod
    def convert_example_text_to_traditional(cls, value):
        if isinstance(value, str):
            return _traditional_chinese.convert(value)
        return value

    @model_validator(mode="after")
    def use_chinese_from_legacy_example(self):
        # Older Cambridge cache rows store English followed by the Chinese translation.
        if self.source is None and (start := _han_character.search(self.example_text)):
            self.example_text = self.example_text[start.start():]
        return self


class DefinitionSchema(BaseModel):
    en_definition: str = Field(..., description="英文定義")
    zh_definition: Optional[str] = Field(None, description="台灣繁體中文翻譯")
    examples: List[ExampleSchema] = Field(default=[], description="例句")

    @field_validator("zh_definition", mode="before")
    @classmethod
    def convert_zh_definition_to_traditional(cls, value):
        if isinstance(value, str):
            return _traditional_chinese.convert(value)
        return value

    @field_validator("examples")
    @classmethod
    def keep_chinese_examples(cls, value):
        return [example for example in value if _han_character.search(example.example_text)]


class EntrySchema(BaseModel):
    part_of_speech: str = Field(..., description="詞性")
    definitions: List[DefinitionSchema] = Field(default=[], description="定義列")


class WordSchema(BaseModel):
    word: str = Field(..., description="英文單字")
    pronunciations: PronunciationsSchema
    entries: List[EntrySchema] = Field(default=[], description="詞條列")
