"""Afiliacoes: 'Universidade de São Paulo – USP, Ribeirão Preto, Brasil' -> campos SPS."""

from __future__ import annotations

import re

from .utils import clean_text, fold

COUNTRIES = {
    "brasil": "BR", "brazil": "BR", "portugal": "PT", "espanha": "ES", "espana": "ES", "spain": "ES",
    "argentina": "AR", "chile": "CL", "colombia": "CO", "colômbia": "CO", "mexico": "MX", "méxico": "MX",
    "peru": "PE", "perú": "PE", "uruguai": "UY", "uruguay": "UY", "paraguai": "PY", "paraguay": "PY",
    "bolivia": "BO", "bolívia": "BO", "venezuela": "VE", "equador": "EC", "ecuador": "EC", "cuba": "CU",
    "costa rica": "CR", "panama": "PA", "panamá": "PA", "guatemala": "GT", "honduras": "HN",
    "el salvador": "SV", "nicaragua": "NI", "nicarágua": "NI", "republica dominicana": "DO",
    "porto rico": "PR", "puerto rico": "PR",
    "estados unidos": "US", "estados unidos da america": "US", "eua": "US", "usa": "US", "united states": "US",
    "canada": "CA", "canadá": "CA", "reino unido": "GB", "united kingdom": "GB", "uk": "GB", "inglaterra": "GB",
    "franca": "FR", "frança": "FR", "francia": "FR", "france": "FR", "alemanha": "DE", "alemania": "DE",
    "germany": "DE", "italia": "IT", "itália": "IT", "italy": "IT", "holanda": "NL", "paises baixos": "NL",
    "netherlands": "NL", "belgica": "BE", "bélgica": "BE", "belgium": "BE", "suica": "CH", "suíça": "CH",
    "suiza": "CH", "switzerland": "CH", "suecia": "SE", "suécia": "SE", "sweden": "SE", "noruega": "NO",
    "norway": "NO", "dinamarca": "DK", "denmark": "DK", "finlandia": "FI", "finland": "FI",
    "irlanda": "IE", "ireland": "IE", "austria": "AT", "áustria": "AT", "polonia": "PL", "polônia": "PL",
    "poland": "PL", "grecia": "GR", "grécia": "GR", "greece": "GR", "russia": "RU", "rússia": "RU",
    "china": "CN", "japao": "JP", "japão": "JP", "japon": "JP", "japan": "JP", "india": "IN", "índia": "IN",
    "australia": "AU", "austrália": "AU", "nova zelandia": "NZ", "africa do sul": "ZA", "sudafrica": "ZA",
    "south africa": "ZA", "angola": "AO", "mocambique": "MZ", "moçambique": "MZ", "cabo verde": "CV",
    "israel": "IL", "turquia": "TR", "turkey": "TR", "coreia do sul": "KR", "south korea": "KR",
}

_ORG_HINT = re.compile(
    r"\b(univers|institut|faculdad|faculdade|faculty|escola|escuela|school|college|centro|center|centre|"
    r"funda[cç][aã]o|fundaci[oó]n|foundation|hospital|laborat|programa|departament|minist[eé]rio|ministerio|"
    r"secretaria|embrapa|fiocruz|ibict|conicet|csic|academia|biblioteca|library|museu|museo|empresa|"
    r"conselho|consejo|council|agency|ag[eê]ncia|instituto)",
    re.I,
)
_STATE = re.compile(r"^[A-Z]{2}$")


def country_code(name: str) -> str:
    return COUNTRIES.get(fold(name).rstrip("."), "")


def looks_like_aff(text: str) -> bool:
    text = clean_text(text)
    if not text:
        return False
    parts = [p.strip() for p in text.split(",")]
    if _ORG_HINT.search(text):
        return True
    return len(parts) >= 2 and bool(country_code(parts[-1]))


def _split_org(org: str) -> tuple[str, str]:
    """'Universidade de São Paulo – USP' -> ('Universidade de São Paulo', 'USP')."""
    m = re.match(r"^(.*?)\s*[–—-]\s*([A-ZÀ-Ý][A-Za-zÀ-ÿ/&]{1,15})\s*$", org)
    if m and m.group(2).upper() == m.group(2):
        return m.group(1).strip(), m.group(2)
    m = re.match(r"^(.*?)\s*\(([A-Z][A-Za-z/&]{1,15})\)\s*$", org)
    if m:
        return m.group(1).strip(), m.group(2)
    return org, ""


def parse_aff(original: str) -> dict[str, str]:
    original = clean_text(original)
    parts = [p.strip() for p in original.split(",") if p.strip()]
    out = {"original": original, "orgname": "", "acronym": "", "orgdiv1": "", "orgdiv2": "",
           "city": "", "state": "", "country": "", "country_code": ""}
    if not parts:
        return out
    if country_code(parts[-1]):
        out["country"] = parts.pop().rstrip(".")
        out["country_code"] = country_code(out["country"])
    if parts and _STATE.match(parts[-1]):
        out["state"] = parts.pop()
    if len(parts) >= 2 and not _ORG_HINT.search(parts[-1]):
        out["city"] = parts.pop()
    if parts:
        org, acronym = _split_org(parts[0])
        out["orgname"], out["acronym"] = org, acronym
        divs = parts[1:]
        if divs:
            out["orgdiv1"] = divs[0]
        if len(divs) > 1:
            out["orgdiv2"] = divs[1]
    return out


def same_org(a: str, b: str) -> bool:
    fa, fb = fold(_split_org(a)[0]), fold(_split_org(b)[0])
    return bool(fa) and (fa == fb or fa in fb or fb in fa)
