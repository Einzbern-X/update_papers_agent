from dataclasses import dataclass


@dataclass
class Paper:
    venue: str
    year: int
    title: str
    authors: str = ""
    pdf_url: str = ""
    source_url: str = ""
