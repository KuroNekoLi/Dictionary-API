from pydantic import BaseModel, Field
from typing import List, Optional


class PronunciationsSchema(BaseModel):
    uk: Optional[str] = Field(None, description="英式發音音標")
    us: Optional[str] = Field(None, description="美式發音音標")


class ExampleSchema(BaseModel):
    example_text: str = Field(..., description="例句")


class DefinitionSchema(BaseModel):
    en_definition: str = Field(..., description="英文定義")
    zh_definition: Optional[str] = Field(None, description="中文翻譯")
    examples: List[ExampleSchema] = Field(default=[], description="例句")


class EntrySchema(BaseModel):
    part_of_speech: str = Field(..., description="詞性")
    definitions: List[DefinitionSchema] = Field(default=[], description="定義列")


class WordSchema(BaseModel):
    word: str = Field(..., description="英文單字")
    pronunciations: PronunciationsSchema
    entries: List[EntrySchema] = Field(default=[], description="詞條列")
