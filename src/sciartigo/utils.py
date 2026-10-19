"""Utilitarios compartilhados (mesma base do patenteia/utils.py)."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape


DOCX_SUFFIXES = {".docx"}
XML_SUFFIXES = {".xml"}


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    # XML 1.0 nao aceita a maioria dos caracteres de controle.
    value = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def xml_escape(value: str) -> str:
    return escape(value or "")


def fold(value: str) -> str:
    """Minusculas, sem acentos, apostrofos e hifens normalizados (para casamento)."""
    # aspas antes da normalizacao: NFKD transforma '´' em espaco + acento
    value = (value or "").replace("’", "'").replace("´", "'").replace("`", "'").replace("‘", "'")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[-‐‑–—]", " ", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def strip_tags(fragment: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", "", fragment or "").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def iter_input_files(path: Path, suffixes: set[str]) -> Iterable[Path]:
    if path.is_file():
        if path.suffix.lower() in suffixes:
            yield path
        return
    for item in sorted(path.rglob("*")):
        # ~$arquivo.docx sao travas do Word, nao documentos
        if item.is_file() and item.suffix.lower() in suffixes and not item.name.startswith("~$"):
            yield item


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


MONTHS = {
    # pt / es / en, abreviados e por extenso (ABNT usa "jul.", "set.")
    "jan": 1, "janeiro": 1, "enero": 1, "january": 1,
    "fev": 2, "feb": 2, "fevereiro": 2, "febrero": 2, "february": 2,
    "mar": 3, "marco": 3, "março": 3, "marzo": 3, "march": 3,
    "abr": 4, "apr": 4, "abril": 4, "april": 4,
    "mai": 5, "may": 5, "maio": 5, "mayo": 5,
    "jun": 6, "junho": 6, "junio": 6, "june": 6,
    "jul": 7, "julho": 7, "julio": 7, "july": 7,
    "ago": 8, "aug": 8, "agosto": 8, "august": 8,
    "set": 9, "sep": 9, "sept": 9, "setembro": 9, "septiembre": 9, "september": 9,
    "out": 10, "oct": 10, "outubro": 10, "octubre": 10, "october": 10,
    "nov": 11, "novembro": 11, "noviembre": 11, "november": 11,
    "dez": 12, "dic": 12, "dec": 12, "dezembro": 12, "diciembre": 12, "december": 12,
}


def parse_date(value: str) -> dict[str, str] | None:
    """Converte '07-10-2024', '2024-10-07', '22 jul. 2024' ou '22. jul. 2024' em {year, month, day}."""
    raw = clean_text(value)
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", raw)
    if m:
        y, mo, d = m.groups()
        return {"year": y, "month": f"{int(mo):02d}", "day": f"{int(d):02d}"}
    m = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", raw)
    if m:
        d, mo, y = m.groups()
        return {"year": y, "month": f"{int(mo):02d}", "day": f"{int(d):02d}"}
    m = re.search(r"\b(\d{1,2})\.?\s*(?:de\s+)?([A-Za-zçÇ]{3,10})\.?\s*(?:de\s+)?(\d{4})\b", raw)
    if m:
        d, mon, y = m.groups()
        month = MONTHS.get(fold(mon).rstrip("."))
        if month:
            return {"year": y, "month": f"{month:02d}", "day": f"{int(d):02d}"}
    m = re.search(r"\b([A-Za-zçÇ]{3,10})\.?\s*(?:de\s+)?(\d{4})\b", raw)
    if m:
        mon, y = m.groups()
        month = MONTHS.get(fold(mon))
        if month:
            return {"year": y, "month": f"{month:02d}"}
    return None


def iso_date(parts: dict[str, str] | None) -> str:
    if not parts:
        return ""
    return "-".join(p for p in (parts.get("year"), parts.get("month"), parts.get("day")) if p)


def _unescape(text: str) -> str:
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")


def strip_prefix_xml(fragment: str, n_chars: int) -> str:
    """Remove os primeiros `n_chars` do texto de um fragmento XML inline,
    preservando o balanceamento das tags (rotulos como 'Figura 1 – ')."""
    out: list[str] = []
    remaining = n_chars
    for piece in re.split(r"(<[^>]+>)", fragment or ""):
        if not piece:
            continue
        if piece.startswith("<"):
            out.append(piece)
            continue
        if remaining <= 0:
            out.append(piece)
            continue
        text = _unescape(piece)
        if len(text) <= remaining:
            remaining -= len(text)
            continue
        out.append(xml_escape(text[remaining:]))
        remaining = 0
    result = "".join(out)
    # elementos que ficaram vazios: <bold></bold>, <italic> </italic>
    prev = None
    while prev != result:
        prev = result
        result = re.sub(r"<(\w[\w-]*)(?:\s[^>]*)?>\s*</\1>", "", result)
    return result.strip()


def prefix_len_matching(fragment: str, pattern: str) -> int:
    """Comprimento (em texto) do prefixo que casa `pattern` no texto puro do fragmento."""
    plain = _unescape(re.sub(r"<[^>]+>", "", fragment or ""))
    m = re.match(pattern, plain)
    return m.end() if m else 0
