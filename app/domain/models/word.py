from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Pronunciations:
    uk: Optional[str] = None
    us: Optional[str] = None


@dataclass
class Example:
    example_text: str


@dataclass
class Definition:
    en_definition: str
    zh_definition: Optional[str] = None
    examples: List["Example"] = field(default_factory=list)


@dataclass
class Entry:
    part_of_speech: str
    definitions: List["Definition"] = field(default_factory=list)


@dataclass
class Word:
    word: str
    pronunciations: Pronunciations = field(default_factory=Pronunciations)
    entries: List[Entry] = field(default_factory=list)
