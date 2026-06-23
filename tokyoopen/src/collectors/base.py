from dataclasses import dataclass
from datetime import datetime


@dataclass
class Article:
    title: str
    body: str
    source: str
    url: str = ""
    section: str = ""
    published_at: datetime | None = None
    language: str = "en"
