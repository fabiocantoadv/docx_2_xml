"""Referencias ABNT (NBR 6023) -> campos de element-citation.

Usa duas pistas do DOCX alem do texto: o negrito (a ABNT destaca o titulo
do periodico/livro, que vira <source>) e os hiperlinks. Cada referencia
recebe `confidence` e `warnings` para a revisao humana; o texto original
continua integral em <mixed-citation>.
"""

from __future__ import annotations

import re

from .utils import clean_text, fold, iso_date, parse_date

PARTICLES = r"(?:van|von|de|da|do|dos|das|den|der|del|della|la|le|y|e|DA|DE|DO|DOS|DAS|DEL|VAN|VON|Y|E)"
UC = "A-ZÀ-ÖØ-Ý\u0100-\u024F"  # latim estendido (Ł, Ń, Č...) entra inteiro
UPPER_WORD = rf"[{UC}][{UC}ß'´’`\-]+\.?"
SURNAME = rf"(?:{PARTICLES}\s+)*{UPPER_WORD}(?:\s+(?:{PARTICLES}\s+)*{UPPER_WORD})*"
INITIAL = re.compile(rf"^[{UC}]\.?(?:-[{UC}]\.?)?[;,.]*$")
GIVEN_WORD = re.compile(r"^[A-ZÀ-Ý][a-zà-ÿ'’\-]+[;,.]?$")
YEAR = re.compile(r"(?<![\d/.-])\[?c?((?:1[5-9]|20)\d{2})([a-z])?\]?(?![\d/])")
URL = re.compile(r"https?://[^\s<>]+")
DOI = re.compile(r"(?:doi\.org/|doi:\s*|DOI:?\s*)(10\.\d{4,9}/[^\s<>]+)", re.I)
DOI_BARE = re.compile(r"\b(10\.\d{4,9}/[^\s<>]+)")
ACCESS = re.compile(r"(?:Acesso em|Acessado em|Accedido(?: el)?|Consultado (?:el|em)|Accessed|Access(?:ed)? (?:in|on)|Acceso)\s*:?\s*(\d{1,2}\.?\s*(?:de\s+)?[A-Za-zçÇ]{3,10}\.?\s*(?:de\s+)?\d{4}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4}|[A-Za-zçÇ]{3,10}\.?\s*(?:de\s+)?\d{4}|\d{4}-\d{2}-\d{2})", re.I)
AVAILABLE = re.compile(r"(?:Dispon[ií]vel em|Disponible en|Available (?:from|at|in)|Recuperado de)\s*:?\s*", re.I)


def _strip_url_punct(url: str) -> str:
    return url.rstrip(".,;)]")


def _bold_segments(tokens: list[dict]) -> list[str]:
    segs: list[str] = []
    current: list[str] = []
    pending_space = ""
    for tok in tokens:
        if tok.get("bold") and tok["text"].strip():
            current.append(pending_space + tok["text"])
            pending_space = ""
        elif not tok["text"].strip() and current:
            pending_space += tok["text"]
        else:
            if current:
                segs.append(clean_text("".join(current)))
            current, pending_space = [], ""
    if current:
        segs.append(clean_text("".join(current)))
    return [s.strip(" .,:;") for s in segs if len(s.strip(" .,:;")) > 1]


def split_authors(text: str) -> tuple[list[dict], bool, int]:
    """Le autores pessoais no inicio: 'ABDI, S.; FIEUWS, S.; DIERICKX, K. Titulo...'.
    Retorna (autores, etal, posicao_fim)."""
    authors: list[dict] = []
    pos = 0
    etal = False
    while True:
        m = re.match(rf"\s*({SURNAME}),\s+", text[pos:])
        if not m:
            break
        surname = m.group(1).strip()
        p = pos + m.end()
        tokens = list(re.finditer(r"\S+", text[p:]))
        given: list[str] = []
        end = None
        more = False
        for k, tm in enumerate(tokens):
            tok = tm.group(0)
            nxt = tokens[k + 1].group(0) if k + 1 < len(tokens) else ""
            nxt2 = tokens[k + 2].group(0) if k + 2 < len(tokens) else ""
            # inicial sem ponto ('A', 'D') so vale fechada por ';'/',' ou no fim:
            # em 'QADHI, S. A model' e 'ZIMAN, J. M. A Força' o 'A' abre o titulo
            bare_initial = INITIAL.match(tok) and not tok.rstrip(";,").endswith(".")
            if bare_initial and given and not tok.endswith((";", ",")) and nxt2 is not None and not nxt.startswith(";"):
                if nxt and not INITIAL.match(nxt):
                    end = p + tm.start()
                    break
            if INITIAL.match(tok) or (not given and GIVEN_WORD.match(tok)) or (given and GIVEN_WORD.match(tok) and not given[-1].endswith(".")):
                given.append(tok.rstrip(";,"))
                if tok.endswith(";") or tok.endswith(","):
                    more = True
                    end = p + tm.end()
                    break
                continues = (INITIAL.match(nxt) and (nxt.rstrip(";,").endswith(".") or nxt.endswith((";", ",")) or not nxt2 or INITIAL.match(nxt2) or nxt2.startswith(";"))) \
                    or re.fullmatch(rf"{PARTICLES}\.[;,]?", nxt or "-") or nxt.startswith(";") or nxt.lower().startswith("et")
                if tok.endswith(".") and not continues:
                    end = p + tm.end()
                    break
                continue
            if re.fullmatch(rf"{PARTICLES}\.?[;,]?", tok) and given:
                given.append(tok.rstrip(";,."))
                end = p + tm.end()
                more = tok.endswith(";")
                break
            if tok.startswith(";"):
                more = True
                end = p + tm.start() + 1
                break
            end = p + tm.start()
            break
        if not given or end is None:
            break
        authors.append({"surname": surname.rstrip("."), "given": " ".join(given).rstrip(";,").strip()})
        pos = end
        rest = text[pos:]
        m_etal = re.match(r"\s*;?\s*et\s+al\.*\s*\.?", rest, re.I)
        if m_etal:
            etal = True
            pos += m_etal.end()
            break
        if not more:
            break
    if not authors:
        authors, etal, pos = _split_authors_vancouver(text)
    return authors, etal, pos


def _split_authors_vancouver(text: str) -> tuple[list[dict], bool, int]:
    """'DESMOND H, DIERICKX K. Titulo' ou 'RESNIK D. B. Titulo' (sem virgula apos o sobrenome)."""
    head = re.match(r"^\s*([^.]{2,200}?)\.\s", text)
    if head:
        words = head.group(1).split()
        # entidade em caixa alta ('ACADEMIA BRASILEIRA DE CIÊNCIAS', 'COMMITTEE ON ...'):
        # palavras funcionais ou mais de 4 palavras longas nao sao iniciais de pessoa
        if any(w.upper() in {"DE", "DA", "DO", "DOS", "DAS", "ON", "OF", "FOR", "THE", "AND", "E", "Y", "LA", "DEL", "EL"} for w in words):
            return [], False, 0
        if sum(1 for w in words if len(w.strip(",.")) > 3) > 4:
            return [], False, 0
    m = re.match(rf"^\s*((?:{SURNAME})\s+(?:(?:[{UC}]\.\s*){{1,4}}|[{UC}]{{1,3}})(?:\s*,\s*(?:{SURNAME})\s+(?:(?:[{UC}]\.\s*){{1,4}}|[{UC}]{{1,3}}))*)\.?\s+(?:et al\.?\s*)?(?=[{UC}0-9“\"])", text)
    if not m:
        return [], False, 0
    authors = []
    for piece in re.split(r"\s*,\s*", m.group(1)):
        mm = re.match(rf"^({SURNAME})\s+(.+)$", piece.strip())
        if mm:
            authors.append({"surname": mm.group(1).rstrip("."), "given": mm.group(2).strip()})
    etal = "et al" in m.group(0)
    return authors, etal, m.end()


def _collab(text: str) -> tuple[str, int]:
    m = re.match(r"^\s*([A-ZÀ-Ý][\w\s]{1,60}?\.\.\.)\s+", text)  # 'Conselho... Titulo'
    if m:
        return m.group(1), m.end()
    m = re.match(r"^\s*([A-ZÀ-Ý][^.]{1,150}?)\.\s+", text)
    if not m:
        return "", 0
    seg = m.group(1)
    letters = [c for c in seg if c.isalpha()]
    upper = sum(1 for c in letters if c.isupper())
    words = seg.split()
    if letters and upper / len(letters) > 0.75:
        return seg.strip(), m.end()
    # 'COPE Council.' : primeira palavra em caixa alta, ate 5 palavras capitalizadas
    if words and words[0].isupper() and len(words[0]) > 1 and len(words) <= 5 and all(w[0].isupper() for w in words):
        return seg.strip(), m.end()
    return "", 0


def _detect_type(text: str, has_bold_after_title: bool, has_url: bool) -> str:
    t = text
    if re.search(r"\b(Tese|Disserta[cç][aã]o|Tesis|Thesis|Monografia|Trabalho de [Cc]onclus[aã]o)\b", t) and re.search(
        r"\((?:Doutorado|Mestrado|Doctorado|Maestr[ií]a|PhD|Ph\.D|Gradua[cç][aã]o|Especializa[cç][aã]o|Licenciatura)", t
    ):
        return "thesis"
    if re.search(r"\b(Lei|Decreto|Portaria|Resolu[cç][aã]o|Medida Provis[oó]ria|Constitui[cç][aã]o|Instru[cç][aã]o Normativa)\b\s*(n[ºo°.]|\d|da|de)", t) or "Diário Oficial" in t:
        return "legal-doc"
    if re.search(r"\bIn:", t) and re.search(r"(Anais|Proceedings|Congresso|Congress|Conference|Confer[eê]ncia|Encontro|Simp[oó]sio|Semin[aá]rio|Jornada|Workshop|Actas|Coloquio|Col[oó]quio|Meeting)", t):
        return "confproc"
    if re.search(r"\bpatente\b|\bpatent\b", t, re.I) and re.search(r"\b(BR|US|EP|WO)\s*\d", t):
        return "patent"
    if re.search(r"\b(v\.|vol\.|n\.|núm\.|no\.)\s*\d", t, re.I) and has_bold_after_title and not re.search(r"\bIn:", t):
        return "journal"
    publisher = re.search(r"(?:^|[.\]]\s)[A-ZÀ-Ý\[][^.:;]{1,60}:\s*[^,;]{2,120},\s*(?:\[?c?\d{4})", t)
    if has_bold_after_title and re.search(r"\b10\.\d{4,9}/", t) and not re.search(r"\bIn:", t) and not publisher:
        return "journal"
    if re.search(r"\bIn:", t):
        return "book"
    if re.search(r"\b(Relat[oó]rio|Report|Informe|Working Paper|Texto para discuss[aã]o|Nota t[eé]cnica)\b", t):
        return "report"
    if re.search(r"\b(Jornal|Folha de S|O Globo|Estad[aã]o|newspaper)\b", t):
        return "newspaper"
    if re.search(r"(?:^|[.\]]\s)[A-ZÀ-Ý\[][^.:;]{1,60}:\s*[^,;]{2,120},\s*(?:\[?c?\d{4})", t):
        return "book"
    if has_url:
        return "webpage"
    return "book" if has_bold_after_title else "other"


def parse_reference(text: str, tokens: list[dict] | None = None) -> dict:
    t = clean_text(text)
    out: dict = {
        "publication_type": "other", "authors": [], "collab": "", "etal": False,
        "article_title": "", "chapter_title": "", "source": "", "series": "", "edition": "",
        "publisher_loc": "", "publisher_name": "", "volume": "", "issue": "", "fpage": "", "lpage": "",
        "elocation": "", "size_pages": "", "year": "", "year_letter": "", "doi": "", "uri": "",
        "access_date": "", "access_date_iso": "", "comment_prefix": "", "warnings": [],
    }
    bold = _bold_segments(tokens or [])
    doi = DOI.search(t) or DOI_BARE.search(t)
    if doi:
        out["doi"] = _strip_url_punct(doi.group(1))
    urls = [_strip_url_punct(u) for u in URL.findall(t)]
    non_doi = [u for u in urls if "doi.org/" not in u.lower()]
    if non_doi:
        out["uri"] = non_doi[0]
    acc = ACCESS.search(t)
    if acc:
        out["access_date"] = clean_text(acc.group(1)).strip(" .")
        out["access_date_iso"] = iso_date(parse_date(out["access_date"]))
    avail = AVAILABLE.search(t)
    if avail:
        out["comment_prefix"] = clean_text(avail.group(0)).rstrip(":") + ":"

    # nucleo: sem URL, DOI e acesso
    cut = len(t)
    for m in (avail, acc):
        if m:
            cut = min(cut, m.start())
    for u in URL.finditer(t):
        cut = min(cut, u.start())
    m_doi_label = re.search(r"\b(?:doi|DOI)\s*:", t)
    if m_doi_label:
        cut = min(cut, m_doi_label.start())
    core = t[:cut].strip()

    authors, etal, pos = split_authors(core)
    if authors:
        out["authors"], out["etal"] = authors, etal
    else:
        collab, cpos = _collab(core)
        rest_after = core[cpos:]
        # 'INFODEMIC. In: OXFORD English Dictionary' e entrada por titulo, nao autoria
        if collab and not re.match(r"\s*In:", rest_after):
            out["collab"] = collab
            pos = cpos
        else:
            pos = 0
    rest = core[pos:].strip(" .")

    # source em negrito
    source = ""
    before = rest
    after = ""
    for seg in bold:
        idx = rest.find(seg)
        if idx >= 0 and fold(seg) not in {fold(a["surname"]) for a in out["authors"]} and fold(seg) != fold(out["collab"]):
            source = seg
            before = rest[:idx].strip(" .:")
            after = rest[idx + len(seg):]
            # subtitulo fora do negrito (ABNT): 'Higher Education: Handbook of ...'
            m_sub = re.match(r"^\s*:\s*([^.(\[]{2,150}?)\s*(?=[.(\[]|$)", after)
            if m_sub and not re.search(r"\b(v\.|n\.|p\.|se[cç][aã]o)\s*\d", m_sub.group(1)):
                source = f"{seg}: {m_sub.group(1).strip()}"
                after = after[m_sub.end():]
            break
    if not source:
        # sem negrito: titulo = ate o primeiro ponto; o resto e imprenta
        m = re.match(r"^(.+?[^A-Z\s.])\.\s+(.*)$", rest)
        m_in = re.match(r"^(.+?)\.\s+In:\s*(.+?[^A-Z\s.])\.\s+(.*)$", rest)
        if m_in:
            out["chapter_title"] = m_in.group(1)
            source, after = m_in.group(2), m_in.group(3)
        elif m:
            source, after = m.group(1), m.group(2)
        else:
            source, after = rest, ""
        before = ""
        out["warnings"].append("source sem negrito (inferido)")

    in_match = re.search(r"\bIn:\s*", before)
    ptype = _detect_type(t, bool(before) or bool(bold), bool(urls))
    out["publication_type"] = ptype
    if in_match:
        out["chapter_title"] = before[: in_match.start()].strip(" .")
        eds_seg = before[in_match.end():]
        eds, eds_etal, _ = split_authors(eds_seg)
        if eds:
            role = re.search(r"\((ed|eds|org|orgs|coord|coords|comp|trad)\.?\)", eds_seg, re.I)
            out["editors"] = eds
            out["editors_role"] = {"trad": "translator", "comp": "compiler"}.get((role.group(1).lower() if role else "ed")[:4].rstrip("s"), "editor")
        before = ""
    if ptype == "legal-doc" and before:
        out["source"], out["series"] = before.strip(" ."), source
    elif ptype in ("journal", "newspaper") and before:
        out["article_title"], out["source"] = before.strip(" ."), source
    elif before and not out["chapter_title"]:
        # livro/relatorio com titulo antes do negrito (subtitulo em negrito e raro): usa tudo como source
        if ptype in ("webpage", "other", "report", "thesis", "book") and len(before) > 3:
            out["article_title"] = before.strip(" .")
            out["source"] = source
        else:
            out["source"] = (before + ". " + source).strip(" .")
    else:
        out["source"] = source

    tail = after
    m = re.search(r"\b(?:v\.|vol\.)\s*(\d+[\w-]*)", tail, re.I) or re.search(r"\bano\s+(\d+)", tail)
    if m:
        out["volume"] = m.group(1)
    m = re.search(r"\b(?:n\.|nº|núm\.|no\.)\s*(\d+[\w/-]*)", tail, re.I)
    if m:
        out["issue"] = m.group(1)
    m = re.search(r"\bp\.\s*(\d+)\s*[-–—]\s*(\d+)", tail) or re.search(r",\s*(\d+)\s*[-–—]\s*(\d+),\s*(?:\[?c?\d{4})", tail)
    if m:
        out["fpage"], out["lpage"] = m.group(1), m.group(2)
    else:
        m = re.search(r"\bp\.\s*(\d+)\b", tail)
        if m:
            out["fpage"] = out["lpage"] = m.group(1)
    m = re.search(r"\b(\d+)\s*p\b\.?(?!\s*\d)", tail)
    if m and not out["fpage"]:
        out["size_pages"] = m.group(1)
    m = re.search(r"\b(e\d{4,})\b", tail)
    if m:
        out["elocation"] = m.group(1)
    m = re.search(r"\b(\d+)\.?\s*(?:ed\.|edição|edición|edition)", tail, re.I)
    if m:
        out["edition"] = m.group(1)
    years = list(YEAR.finditer(tail)) or list(YEAR.finditer(core))
    if years:
        out["year"], out["year_letter"] = years[-1].group(1), years[-1].group(2) or ""
    elif out["access_date_iso"]:
        out["year"] = out["access_date_iso"][:4]
        out["warnings"].append("ano inferido da data de acesso")
    else:
        out["warnings"].append("ano nao encontrado")
    if ptype in ("journal", "newspaper"):
        m = re.match(r"^\s*,\s*(.+?),\s*(?:v\.|vol\.|n\.|nº|ano|p\.|\[?c?\d{4})", tail, re.I)
        if m and not re.search(r"\d", m.group(1)):
            out["publisher_loc"] = m.group(1).strip()
    else:
        m = None
        for cand in re.finditer(r"(?:^|(?<=[.\]])\s+|^\s*)([A-ZÀ-Ý\[][^.:;]{1,60}?):\s*([^;]{2,120}?),\s*(?:\[?c?\d{4})", tail):
            loc, name = cand.group(1).strip(), cand.group(2)
            if re.match(r"(?i)(tradu[cç][aã]o|traducci[oó]n|translated|organiza[cç][aã]o|coordena[cç][aã]o|edi[cç][aã]o|in)$", loc):
                continue
            if ". " in name:
                continue
            m = cand
            break
        if m:
            out["publisher_loc"] = m.group(1).strip(" []") if not re.match(r"\[?S\.\s*l\.?", m.group(1)) else ""
            out["publisher_name"] = m.group(2).strip(" .")
        elif ptype == "thesis":
            m = re.search(r"\)\s*[–-]\s*([^,]+),\s*([^,]+),\s*\d{4}", tail)
            if m:
                out["publisher_name"], out["publisher_loc"] = m.group(1).strip(), m.group(2).strip()
        if ptype == "thesis":
            m = re.search(r"\(([^)]*(?:Doutorado|Mestrado|Doctorado|Maestr[ií]a|PhD)[^)]*)\)", t)
            if m:
                out["thesis_degree"] = clean_text(m.group(0))

    if re.search(rf"{SURNAME},\s+[{UC}]\.", out["article_title"] or out["source"]):
        out["warnings"].append("autoria possivelmente incompleta (sobrenome no titulo)")
    if not out["authors"] and not out["collab"] and not out["chapter_title"]:
        out["warnings"].append("sem autoria identificada")
    if not out["source"]:
        out["warnings"].append("source vazio")
    score = 3 - len(out["warnings"])
    out["confidence"] = "high" if score >= 3 else ("medium" if score == 2 else "low")
    return out


def citation_keys(parsed: dict) -> list[str]:
    """Chaves de casamento autor-data para as chamadas no texto."""
    year = parsed.get("year", "") + parsed.get("year_letter", "")
    keys = []
    if parsed.get("authors"):
        sur = parsed["authors"][0]["surname"]
        keys.append(fold(sur).rstrip("."))
        # 'TEIXEIRA DA SILVA' -> 'teixeira da silva' e 'silva'; 'SANTOS-D´AMORIM' -> 'santos d amorim'
        parts = fold(sur).split()
        if len(parts) > 1:
            keys.append(parts[-1])
            keys.append(parts[0])
    elif parsed.get("collab"):
        c = fold(parsed["collab"])
        keys.append(c)
        keys.append(c.split()[0])  # 'COPE Council' citado como (Cope, 2024)
        m = re.search(r"\(([^)]+)\)", parsed["collab"])
        if m:
            keys.append(fold(m.group(1)))
        keys.append(re.sub(r"\s*\([^)]*\)", "", c))
    elif parsed.get("chapter_title") or parsed.get("article_title") or parsed.get("source"):
        # entrada pelo titulo: 'INFODEMIC. In: ...' citado como (Infodemic, 2024)
        first = (parsed.get("chapter_title") or parsed.get("article_title") or parsed.get("source")).split()[0]
        keys.append(fold(first).strip(".,:"))
    return [f"{k}|{year}" for k in dict.fromkeys(k for k in keys if k)]
