"""Chamadas autor-data no texto -> <xref ref-type="bibr" rid="Bn">.

So liga quando o sobrenome (ou entidade) da referencia e o ano aparecem
juntos com conectores tipicos entre eles:

    Metcalfe et al. (2020)      (Bouter, 2020)      Shaw e Satalkar (2018)
    (Aguilera; Carracedo; Saenz, 2022)              (Bouter, 2018, 2020)

Trechos dentro de <ext-link>/<xref>/<email> nao sao tocados e um par
autor-ano ambiguo (duas referencias) nao e ligado.
"""

from __future__ import annotations

import re
import unicodedata

from lxml import etree

from .references import citation_keys

XLINK = "http://www.w3.org/1999/xlink"
_ENTITY = re.compile(r"&(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")


def _fold_char(ch: str) -> str:
    if ch in "-‐‑–—":
        return " "
    if ch in "’´`":
        return "'"
    base = unicodedata.normalize("NFKD", ch)
    base = "".join(c for c in base if not unicodedata.combining(c)) or ch
    return base[0].lower() if base else ch


def _plain_map(fragment: str) -> tuple[str, list[tuple[int, int]], list[bool]]:
    """Texto puro do fragmento, offset xml de cada caractere e se esta protegido."""
    chars: list[str] = []
    offsets: list[int] = []
    protected: list[bool] = []
    depth_protected = 0
    i = 0
    n = len(fragment)
    while i < n:
        ch = fragment[i]
        if ch == "<":
            j = fragment.index(">", i)
            tag = fragment[i + 1:j]
            name = re.match(r"/?([\w:-]+)", tag)
            name = name.group(1) if name else ""
            if name in ("ext-link", "xref", "email", "uri"):
                if tag.startswith("/"):
                    depth_protected -= 1
                elif not tag.endswith("/"):
                    depth_protected += 1
            i = j + 1
            continue
        if ch == "&":
            m = _ENTITY.match(fragment, i)
            if m:
                ent = m.group(0)
                real = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'"}.get(ent, "?")
                chars.append(real)
                offsets.append((i, len(ent)))
                protected.append(depth_protected > 0)
                i = m.end()
                continue
        chars.append(ch)
        offsets.append((i, 1))
        protected.append(depth_protected > 0)
        i += 1
    return "".join(chars), offsets, protected


GAP_OK = [
    re.compile(r"^\.?\s*(?:,|\(|;)?\s*$"),                                   # (Bouter, 2020) / Bouter (2020) / (Merton; 1962)
    re.compile(r"^\s+et\s+al\.?\s*(?:,|\()?\s*$"),                           # Metcalfe et al. (2020)
    re.compile(r"^\s*(?:,\s*[^\d();,]{1,60})*\s+(?:e|and|y|&)\s+[^\d();]{1,60}?\s*(?:,|\()?\s*$"),  # Shaw e Satalkar
    re.compile(r"^\s*;\s*[^\d()]{1,160}?\s*,\s*$"),                            # (Soehartono; Yu; Khor, 2022)
    re.compile(r"^\s*,\s*(?:[A-ZÀ-Ý]\.\s*){1,4}\(?\s*$"),                      # Shinkai, R. (2010)
    re.compile(r"^\.\.\.\s*,\s*$"),                                              # (Conselho..., 2023)
]
GAP_YEAR_LIST = re.compile(r"^\s*,\s*(?:c?\d{4}[a-z]?\s*[,;]\s*)+$")


def build_index(refs: list[dict]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for ref in refs:
        for key in citation_keys(ref["parsed"]):
            index.setdefault(key, [])
            if ref["id"] not in index[key]:
                index[key].append(ref["id"])
    return index


def link_citations(fragment: str, index: dict[str, list[str]]) -> tuple[str, int]:
    if not fragment or not index:
        return fragment, 0
    plain, offsets, protected = _plain_map(fragment)
    folded = "".join(_fold_char(c) for c in plain)
    by_year: dict[str, list[tuple[str, str]]] = {}
    for key, ids in index.items():
        name, year = key.rsplit("|", 1)
        if len(ids) == 1 and name:
            by_year.setdefault(year, []).append((name, ids[0]))
    spans: list[tuple[int, int, str]] = []
    last_span_end = -1
    for ym in re.finditer(r"(?<!\d)c?(\d{4})([a-z])?(?![\d])", plain):
        y_start, y_end = ym.start(), ym.end()
        if protected[y_start]:
            continue
        year = ym.group(1) + (ym.group(2) or "")
        cands = by_year.get(year, [])
        if not cands and ym.group(2):
            cands = by_year.get(ym.group(1), [])
        if not cands:
            continue
        window_start = max(0, y_start - 160)
        valid = []
        for name, rid in cands:
            for nm in re.finditer(r"(?<![\w'])" + re.escape(name) + r"(?![\w'])", folded[window_start:y_start]):
                s = window_start + nm.start()
                e = window_start + nm.end()
                gap = plain[e:y_start]
                if any(p.match(gap) for p in GAP_OK) or GAP_YEAR_LIST.match(gap):
                    valid.append((s, e, rid, gap))
        if not valid:
            continue
        # a referencia e a do nome mais proximo do ano; dentro dela, a chave
        # mais longa ('Dejo-Vásquez' e nao so 'Vásquez')
        closest = max(valid, key=lambda v: v[0])
        same = [v for v in valid if v[2] == closest[2] and v[1] >= closest[0]]
        s, e, rid, gap = min(same, key=lambda v: v[0])
        if GAP_YEAR_LIST.match(gap) or s <= last_span_end:
            s = y_start  # segunda data do mesmo autor: liga so o ano
            if s <= last_span_end:
                continue
        end = y_end
        if "(" in gap and end < len(plain) and plain[end] == ")":
            end += 1
        if any(protected[k] for k in range(s, end)):
            continue
        spans.append((s, end, rid))
        last_span_end = end
    if not spans:
        return fragment, 0
    out = fragment
    count = 0
    for s, e, rid in reversed(spans):
        xs = offsets[s][0]
        xe = offsets[e - 1][0] + offsets[e - 1][1]
        inner = out[xs:xe]
        try:
            etree.fromstring(f'<x xmlns:xlink="{XLINK}">{inner}</x>')
        except etree.XMLSyntaxError:
            continue
        out = f'{out[:xs]}<xref ref-type="bibr" rid="{rid}">{inner}</xref>{out[xe:]}'
        count += 1
    return out, count
