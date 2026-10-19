"""Separacao de nome completo em given-names / surname.

Sobrenomes compostos brasileiros ('Macedo dos Santos', 'Santos d'Amorim')
sao ambiguos. A ordem de confianca e:

1. pistas do proprio documento: 'Rocha, E. S. S.' ou 'R. N. Macedo dos Santos'
   (contribuicao de autoria, referencias de autocitacao);
2. heuristica: ultimo sobrenome + particulas (de, da, dos, d') e sufixos
   (Júnior, Filho, Neto).

O metodo usado fica no JSON (`name_split`) para a revisao humana.
"""

from __future__ import annotations

import re

from .utils import clean_text, fold

PARTICLES = {"de", "da", "do", "das", "dos", "di", "del", "della", "la", "le", "van", "von", "der", "den", "y", "e", "d'", "d’"}
SUFFIXES = {"junior", "júnior", "jr", "jr.", "filho", "neto", "netto", "sobrinho", "segundo", "terceiro"}


def _initials(tokens: list[str]) -> str:
    out = []
    for tok in tokens:
        if fold(tok) in PARTICLES:
            continue
        for piece in re.split(r"-", tok):
            piece = piece.strip(".")
            if piece:
                out.append(piece[0].upper())
    return "".join(out)


def parse_hint(hint: str) -> tuple[str, str] | None:
    """'Sousa, S. D' -> ('Sousa', 'SD'); 'R. N. Macedo dos Santos' -> ('Macedo dos Santos', 'RN')."""
    hint = clean_text(hint).strip(" ;.")
    if not hint:
        return None
    m = re.match(r"^([^,]+),\s*((?:[A-ZÀ-Ý]\.?\s*-?\s*)+)$", hint)
    if m:
        return clean_text(m.group(1)), re.sub(r"[^A-ZÀ-Ý]", "", m.group(2))
    m = re.match(r"^((?:[A-ZÀ-Ý]\.\s*-?\s*)+)\s*(.+)$", hint)
    if m:
        return clean_text(m.group(2)), re.sub(r"[^A-ZÀ-Ý]", "", m.group(1))
    return None


def _norm_surname(value: str) -> str:
    return fold(value).replace("'", " ").replace("  ", " ").strip()


def split_name(full: str, hints: list[str] | None = None) -> dict[str, str]:
    full = clean_text(full)
    tokens = full.split()
    if len(tokens) == 1:
        return {"given": "", "surname": full, "name_split": "single"}
    for hint in hints or []:
        parsed = parse_hint(hint)
        if not parsed:
            continue
        surname, initials = parsed
        nsur = _norm_surname(surname).split()
        # tenta casar o final do nome com o sobrenome da pista
        for k in range(1, len(tokens)):
            tail = tokens[k:]
            if _norm_surname(" ".join(tail)).split() == nsur:
                given = tokens[:k]
                gi = _initials(given)
                if not initials or gi == initials or gi.startswith(initials) or initials.startswith(gi):
                    # particula imediatamente antes fica com o sobrenome
                    while given and fold(given[-1]) in PARTICLES:
                        tail = [given.pop()] + tail
                    return {"given": " ".join(given), "surname": " ".join(tail), "name_split": "hint"}
    # heuristica
    k = len(tokens) - 1
    if fold(tokens[k]).rstrip(".") in SUFFIXES and k > 1:
        k -= 1
    while k > 1 and fold(tokens[k - 1]) in PARTICLES:
        k -= 1
    return {"given": " ".join(tokens[:k]), "surname": " ".join(tokens[k:]), "name_split": "heuristic"}
