"""Deteccao simples de idioma (pt/es/en/fr) por palavras funcionais e rotulos."""

from __future__ import annotations

import re

from .utils import fold

_STOP = {
    "pt": "o a os as de do da dos das em no na nos nas um uma que para com por não se ao à é são pelo pela entre sobre também mais como foi ser seus suas este esta".split(),
    "es": "el la los las de del en un una que para con por no se al es son entre sobre también más como fue ser sus este esta y lo".split(),
    "en": "the of and in to a is are for with on by this that from as be an which their its was were these research".split(),
    "fr": "le la les de des du en un une que pour avec par ne se au est sont entre sur aussi plus comme été être leurs cette et".split(),
}

ABSTRACT_TITLES = {
    "resumo": "pt", "resumen": "es", "abstract": "en", "resume": "fr", "résumé": "fr", "summary": "en",
}
KEYWORD_TITLES = {
    "palavras-chave": "pt", "palavras chave": "pt", "palavra-chave": "pt", "descritores": "pt",
    "palabras clave": "es", "palabras-clave": "es", "palabra clave": "es",
    "keywords": "en", "key words": "en", "keyword": "en",
    "mots-cles": "fr", "mots cles": "fr",
}


def detect_lang(text: str, default: str = "") -> str:
    words = re.findall(r"[a-zà-ÿ]+", (text or "").lower())
    if not words:
        return default
    scores = {lang: sum(1 for w in words if w in stop) for lang, stop in _STOP.items()}
    # desempate pt x es: grafias exclusivas
    low = " " + " ".join(words) + " "
    for marker in (" não ", " são ", " também ", " ção", "ções ", " uma ", " pela ", " pelo "):
        if marker in low:
            scores["pt"] += 2
    for marker in (" y ", " una ", " ción", "ciones ", " del ", " los ", " las "):
        if marker in low:
            scores["es"] += 2
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else default


def abstract_title_lang(text: str) -> str | None:
    key = fold(text).rstrip(":.")
    return ABSTRACT_TITLES.get(key)


def keyword_label(text: str) -> tuple[str, str] | None:
    """Retorna (rotulo, idioma) se o texto comeca com um rotulo de palavras-chave."""
    key = fold(text)
    for label, lang in sorted(KEYWORD_TITLES.items(), key=lambda kv: -len(kv[0])):
        flabel = fold(label)
        if key == flabel or key.startswith(flabel + ":") or key.startswith(flabel + " :") or key.rstrip(":.") == flabel:
            return label, lang
    return None
