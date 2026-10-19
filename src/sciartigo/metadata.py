"""Metadados externos por artigo (CSV opcional), no papel do xml_basic.

Colunas aceitas (todas opcionais, exceto `file`):

    file, doi, volume, issue, elocation, fpage, lpage, pub_date,
    collection_year, season, article_type, subject, license_url, page_count

`file` casa com o nome do DOCX (com ou sem extensao). Valores preenchidos
prevalecem sobre o que o pipeline le do rodape e do bloco de dados de
publicacao.
"""

from __future__ import annotations

import csv
from pathlib import Path

FIELDS = ("doi", "volume", "issue", "elocation", "fpage", "lpage", "pub_date", "collection_year", "season",
          "article_type", "subject", "license_url", "page_count")


def load_metadata(path: Path | None) -> dict[str, dict]:
    if path is None or not Path(path).exists():
        return {}
    out: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(2048)
        fh.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        for row in csv.DictReader(fh, dialect=dialect):
            key = (row.get("file") or "").strip()
            if not key:
                continue
            out[Path(key).stem.lower()] = {k: (row.get(k) or "").strip() for k in FIELDS if (row.get(k) or "").strip()}
    return out


def metadata_for(docx: Path, table: dict[str, dict]) -> dict:
    return dict(table.get(docx.stem.lower(), {}))
