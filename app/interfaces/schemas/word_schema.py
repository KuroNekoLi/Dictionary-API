from pydantic import BaseModel, Field
from pydantic import field_validator
from typing import List, Optional
from opencc import OpenCC


_traditional_chinese = OpenCC("s2twp.json")


class PronunciationsSchema(BaseModel):
    uk: Optional[str] = Field(None, description="英式發音音標")
    us: Optional[str] = Field(None, description="美式發音音標")
    phonetic: Optional[str] = Field(None, description="ECDICT 提供的未區分英美腔調音標")


class ExampleSchema(BaseModel):
    example_text: str = Field(..., description="例句")


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


class EntrySchema(BaseModel):
    part_of_speech: str = Field(..., description="詞性")
    definitions: List[DefinitionSchema] = Field(default=[], description="定義列")


class WordSchema(BaseModel):
    word: str = Field(..., description="英文單字")
    pronunciations: PronunciationsSchema
    entries: List[EntrySchema] = Field(default=[], description="詞條列")
