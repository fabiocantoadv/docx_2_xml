"""DOCX -> JSON intermediario de secoes (equivalente ao pdf_text_sections).

O JSON e deliberado, como no pipeline de patentes: o DOCX nao e gravado
direto no XML final. Cada artigo vira um JSON auditavel com front, body,
back e os dados de publicacao, que o script 02 transforma em SPS.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .affiliations import looks_like_aff, parse_aff, same_org
from .docx_reader import Block, DocxPackage, read_docx
from .lang import abstract_title_lang, detect_lang, keyword_label
from .names import split_name
from .naming import sps_base_name
from .pubdata import parse_pubdata
from .references import parse_reference
from .utils import clean_text, fold, prefix_len_matching, strip_prefix_xml, strip_tags

LABEL_RE = (
    r"^\s*(?P<kind>Figura|Figure|Fig\.?|Gráfico|Grafico|Gráfica|Grafica|Mapa|Imagem|Imagen|Ilustração|Ilustracion|"
    r"Esquema|Fotografia|Foto|Diagrama|Fluxograma|Quadro|Cuadro|Tabela|Tabla|Table|Chart|Box|Map)"
    r"\s*(?P<num>\d+[A-Za-z]?)\s*(?:[-–—:.|]\s*)?"
)
TABLE_KINDS = {"tabela", "tabla", "table"}
NOTE_RE = r"^\s*(?:Nota|Notas|Note|Notes|Fonte|Fuente|Source|Elaboração|Elaboracion)\b\s*[.:]?"
SEC_TYPES = [
    (r"^(introdu[cç][aã]o|introducci[oó]n|introduction)\b", "intro"),
    (r"^(resultados e discuss[aã]o|resultados y discusi[oó]n|results and discussion)\b", "results|discussion"),
    (r"^(materiais e m[eé]todos|materiales y m[eé]todos|materials and methods)\b", "materials|methods"),
    (r"^(metodologia|m[eé]todos?|procedimentos metodol[oó]gicos|percurso metodol[oó]gico|methodology|methods?)\b", "methods"),
    (r"^(resultados|results)\b", "results"),
    (r"^(discuss[aã]o|discusi[oó]n|discussion)\b", "discussion"),
    (r"^(conclus[aãoõ]+e?s?|conclusi[oó]n(es)?|conclusions?|considera[cç][oõ]es finais|consideraciones finales|final considerations)\b", "conclusions"),
]
HEADING_RE = re.compile(r"^(heading|título|titulo|encabezado)\s*(\d)$", re.I)


def _norm_styles(values) -> set[str]:
    return {v.lower() for v in values or []}


class _Cfg:
    def __init__(self, config: dict):
        st = config.get("styles", {})
        self.title = _norm_styles(st.get("title"))
        self.trans_title = _norm_styles(st.get("trans_title"))
        self.author = _norm_styles(st.get("author"))
        self.abstract_title = _norm_styles(st.get("abstract_title"))
        self.abstract_text = _norm_styles(st.get("abstract_text"))
        self.keywords_title = _norm_styles(st.get("keywords_title"))
        self.keywords = _norm_styles(st.get("keywords"))
        self.caption = _norm_styles(st.get("caption"))
        self.list = _norm_styles(st.get("list"))
        self.reference = _norm_styles(st.get("reference"))
        self.quote = _norm_styles(st.get("quote"))
        self.pubdata_label = _norm_styles(st.get("pubdata_label"))
        self.pubdata_person = _norm_styles(st.get("pubdata_person"))
        mk = config.get("markers", {})
        self.m_refs = {fold(x) for x in mk.get("references", [])}
        self.m_app = {fold(x) for x in mk.get("appendix", [])}
        self.m_pubdata = {fold(x) for x in mk.get("pubdata", [])}
        self.m_ack = {fold(x) for x in mk.get("ack", [])}
        self.default_lang = config.get("defaults", {}).get("lang", "pt")
        # estilos com papel conhecido: o outlineLvl deles nao indica secao
        self.known = (self.title | self.trans_title | self.author | self.abstract_title | self.abstract_text
                      | self.keywords_title | self.keywords | self.caption | self.list | self.reference
                      | self.quote | self.pubdata_person)


def heading_level(b: Block, cfg: _Cfg) -> int | None:
    style = b.style.lower()
    if style in cfg.title or style in cfg.trans_title:
        return None
    m = HEADING_RE.match(style)
    if m:
        return int(m.group(2))
    if b.outline_level is not None and b.outline_level < 6 and style not in cfg.known:
        return b.outline_level + 1
    return None


def _sec_type(title: str) -> str:
    t = fold(title)
    t = re.sub(r"^\d+(\.\d+)*\.?\s*", "", t)
    for pat, sec_type in SEC_TYPES:
        if re.match(pat, t):
            return sec_type
    return ""


def _is_caption(b: Block, cfg: _Cfg) -> bool:
    if b.style.lower() in cfg.caption:
        return True
    return bool(re.match(LABEL_RE, b.text)) and len(b.text) < 300 and b.align in ("center", "both", "") and not b.images


def _list_type(fmt: str) -> str:
    return {
        "bullet": "bullet", "decimal": "order", "decimalZero": "order", "lowerLetter": "alpha-lower",
        "upperLetter": "alpha-upper", "lowerRoman": "roman-lower", "upperRoman": "roman-upper", "none": "simple",
    }.get(fmt, "bullet")


def _table_rows(block: Block) -> list[dict]:
    """Converte w:tbl em linhas com colspan/rowspan resolvidos."""
    grid: list[list[dict]] = []
    open_cells: dict[int, dict] = {}
    for row in block.rows:
        out_row = []
        col = 0
        for cell in row["cells"]:
            xml = " <break/> ".join(p.xml for p in cell["paragraphs"] if p.xml) if cell["paragraphs"] else ""
            entry = {"xml": xml, "colspan": cell["colspan"], "rowspan": 1, "header": row["header"]}
            if cell["vmerge"] == "continue" and col in open_cells:
                open_cells[col]["rowspan"] += 1
            else:
                out_row.append(entry)
                if cell["vmerge"] == "restart":
                    open_cells[col] = entry
                else:
                    open_cells.pop(col, None)
            col += cell["colspan"]
        grid.append({"header": row["header"], "cells": out_row})
    return grid


class _Builder:
    def __init__(self, pkg: DocxPackage, config: dict, assets_dir: Path | None, base_name: str):
        self.pkg = pkg
        self.config = config
        self.cfg = _Cfg(config)
        self.assets_dir = assets_dir
        self.base_name = base_name
        self.warnings: list[str] = []
        self.fig_n = 0
        self.table_n = 0
        self.saved_media: dict[str, str] = {}
        self.refs_title = ""

    # ---------- midia ----------
    def save_image(self, target: str, kind: str, n: int) -> str:
        data = self.pkg.media.get(target)
        if data is None:
            self.warnings.append(f"imagem ausente no pacote: {target}")
            return ""
        ext = Path(target).suffix.lower().lstrip(".") or "png"
        if ext == "jpeg":
            ext = "jpg"
        name = f"{self.base_name}-{kind}{n}.{ext}"
        if self.assets_dir is not None:
            self.assets_dir.mkdir(parents=True, exist_ok=True)
            (self.assets_dir / name).write_bytes(data)
        self.saved_media[name] = hashlib.sha256(data).hexdigest()
        return name

    # ---------- front ----------
    def front(self, blocks: list[Block]) -> tuple[dict, int]:
        cfg = self.cfg
        front: dict = {"title": None, "trans_titles": [], "authors": [], "abstracts": [], "kwd_groups": [], "category": ""}
        i = 0
        state = None
        current_abs = None
        pending_titles: list[dict] = []
        while i < len(blocks):
            b = blocks[i]
            if b.kind != "p":
                break
            style = b.style.lower()
            text = b.text
            if b.textboxes and not front["category"]:
                front["category"] = b.textboxes[0]
            if heading_level(b, cfg) is not None and front["title"] is not None:
                break
            if not text:
                i += 1
                continue
            if front["title"] is None and (style in cfg.title or i == 0):
                front["title"] = {"xml": b.xml, "text": text}
                i += 1
                continue
            if style in cfg.trans_title:
                tt = {"xml": b.xml, "text": text, "lang": ""}
                front["trans_titles"].append(tt)
                pending_titles.append(tt)
                state = None
                i += 1
                continue
            abs_lang = abstract_title_lang(text) if (style in cfg.abstract_title or len(text) < 20) else None
            if abs_lang:
                current_abs = {"lang": abs_lang, "title": text, "paragraphs": []}
                front["abstracts"].append(current_abs)
                state = "abstract"
                i += 1
                continue
            kl = keyword_label(text) if (style in cfg.keywords_title or style in cfg.keywords or len(text) < 25 or b.leading_bold) else None
            if style in cfg.keywords_title or (kl and fold(text).rstrip(":.") == fold(kl[0])):
                lang = kl[1] if kl else (current_abs or {}).get("lang", "")
                front["kwd_groups"].append({"lang": lang, "title": text.rstrip(":") + ":", "kwds": []})
                state = "kwd"
                i += 1
                continue
            if kl and style in cfg.keywords | cfg.abstract_text | {"normal"}:
                cut = prefix_len_matching(b.xml, r"^[^:]+:\s*")
                rest = strip_prefix_xml(b.xml, cut)
                front["kwd_groups"].append({"lang": kl[1], "title": text[: cut].strip().rstrip(":") + ":", "kwds": _split_kwds(rest)})
                state = None
                i += 1
                continue
            if state == "kwd" and front["kwd_groups"] and not front["kwd_groups"][-1]["kwds"]:
                front["kwd_groups"][-1]["kwds"] = _split_kwds(b.xml)
                state = None
                i += 1
                continue
            if state == "abstract" and current_abs is not None and style not in cfg.author:
                current_abs["paragraphs"].append({"xml": b.xml, "text": text, "lead": b.leading_bold})
                i += 1
                continue
            if style in cfg.author or (not front["abstracts"] and front["title"] is not None):
                if looks_like_aff(text) and front["authors"]:
                    front["authors"][-1]["aff_texts"].append(text)
                else:
                    front["authors"].append({"name": text, "aff_texts": []})
                i += 1
                continue
            # paragrafo nao reconhecido antes do corpo
            self.warnings.append(f"front: paragrafo nao classificado ({b.style}): {text[:60]}")
            i += 1
        # idioma dos titulos traduzidos: ordem dos resumos nos demais idiomas
        main_lang = front["abstracts"][0]["lang"] if front["abstracts"] else (detect_lang(front["title"]["text"] if front["title"] else "", self.cfg.default_lang))
        other_langs = [a["lang"] for a in front["abstracts"][1:] if a["lang"] != main_lang]
        for n, tt in enumerate(front["trans_titles"]):
            guess = detect_lang(tt["text"])
            if n < len(other_langs) and (not guess or guess == other_langs[n] or guess == main_lang):
                tt["lang"] = other_langs[n]
            else:
                tt["lang"] = guess
        for kg in front["kwd_groups"]:
            if not kg["lang"]:
                kg["lang"] = detect_lang(" ".join(strip_tags(k) for k in kg["kwds"]), main_lang)
        for ab in front["abstracts"]:
            ab["sections"] = _abstract_sections(ab["paragraphs"])
        front["lang"] = main_lang
        return front, i

    # ---------- corpo ----------
    def body(self, blocks: list[Block], start: int) -> tuple[list, list, list, list, int]:
        cfg = self.cfg
        root: dict = {"type": "root", "children": [], "level": 0}
        stack = [root]
        refs: list[dict] = []
        apps: list[dict] = []
        phase = "body"
        pending_caption: dict | None = None
        last_float: dict | None = None
        i = start
        pubdata_start = len(blocks)
        while i < len(blocks):
            b = blocks[i]
            text = b.text
            style = b.style.lower()
            if b.kind == "p" and text and fold(text) in cfg.m_pubdata:
                pubdata_start = i + 1
                break
            level = heading_level(b, cfg) if b.kind == "p" and text else None
            if level is not None:
                key = fold(re.sub(r"^\d+(\.\d+)*\.?\s*", "", text)).rstrip(":")
                if key in cfg.m_refs:
                    phase = "refs"
                    self.refs_title = text
                    i += 1
                    continue
                if key in cfg.m_app or (phase == "app" and level == 1):
                    phase = "app"
                    app = {"type": "app", "title": {"xml": b.xml, "text": text}, "children": [], "level": 1}
                    apps.append(app)
                    stack = [app]
                    i += 1
                    continue
                if phase == "refs":
                    phase = "body"
                sec = {"type": "sec", "title": {"xml": b.xml, "text": text}, "sec_type": _sec_type(text) if level == 1 else "",
                       "children": [], "level": level}
                if phase == "body" and key in cfg.m_ack:
                    sec["type"] = "ack"
                while len(stack) > 1 and stack[-1]["level"] >= level:
                    stack.pop()
                stack[-1]["children"].append(sec)
                stack.append(sec)
                pending_caption, last_float = None, None
                i += 1
                continue
            if phase == "refs":
                if b.kind == "p" and text:
                    refs.append({"xml": b.xml, "text": text, "tokens": [{"text": t.text, "bold": "bold" in t.fmt, "italic": "italic" in t.fmt} for t in b.tokens if t.kind == "text"]})
                i += 1
                continue
            container = stack[-1]["children"]
            if b.kind == "table":
                self.table_n += 1
                tw = {"type": "table-wrap", "id": f"t{self.table_n}", "label": "", "title": None, "notes": [], "rows": _table_rows(b)}
                if pending_caption:
                    tw["label"], tw["title"] = pending_caption["label"], pending_caption["title"]
                    pending_caption = None
                container.append(tw)
                last_float = tw
                i += 1
                continue
            if not text and not b.images:
                i += 1
                continue
            if b.images and len(text) < 40:
                imgs = [im for im in b.images if im.cx == 0 or im.cx > 914400 * 0.8]
                if not imgs:
                    i += 1
                    continue
                for im in imgs:
                    self.fig_n += 1
                    fig = {"type": "fig", "id": f"f{self.fig_n}", "label": "", "title": None, "notes": [], "alt": im.descr,
                           "graphic": self.save_image(im.target, "gf", self.fig_n) if im.target else "",
                           "needs_render": not im.target, "extent_emu": [im.cx, im.cy]}
                    if not im.target:
                        self.warnings.append(f"figura f{self.fig_n} feita com formas do Word (sem imagem): renderizar (--render-shapes)")
                    if pending_caption and pending_caption["kind"] not in TABLE_KINDS:
                        fig["label"], fig["title"] = pending_caption["label"], pending_caption["title"]
                        pending_caption = None
                    elif pending_caption and pending_caption["kind"] in TABLE_KINDS:
                        # "Tabela N" inserida como imagem: vira table-wrap com graphic
                        self.fig_n -= 1
                        self.table_n += 1
                        fig = {"type": "table-wrap", "id": f"t{self.table_n}", "label": pending_caption["label"],
                               "title": pending_caption["title"], "notes": [], "rows": [],
                               "graphic": self.save_image(im.target, "gt", self.table_n)}
                        pending_caption = None
                    container.append(fig)
                    last_float = fig
                i += 1
                continue
            if _is_caption(b, cfg):
                m = re.match(LABEL_RE, text)
                if m:
                    label = f"{m.group('kind')} {m.group('num')}"
                    rest = strip_prefix_xml(b.xml, m.end())
                    cap = {"kind": fold(m.group("kind")).rstrip("."), "label": label, "title": {"xml": rest, "text": strip_tags(rest)} if rest else None}
                    if last_float is not None and not last_float["label"] and container and container[-1] is last_float:
                        last_float["label"], last_float["title"] = cap["label"], cap["title"]
                    else:
                        pending_caption = cap
                    i += 1
                    continue
                if re.match(NOTE_RE, text):
                    target = last_float if last_float is not None and container and container[-1] is last_float else None
                    if target is not None:
                        target["notes"].append({"xml": b.xml, "text": text})
                    else:
                        self.warnings.append(f"nota/fonte sem figura/tabela: {text[:60]}")
                        container.append({"type": "p", "xml": b.xml})
                    i += 1
                    continue
                if pending_caption and pending_caption["title"] is None:
                    pending_caption["title"] = {"xml": b.xml, "text": text}
                    i += 1
                    continue
                if last_float is not None and last_float["title"] is None and container and container[-1] is last_float:
                    last_float["title"] = {"xml": b.xml, "text": text}
                    i += 1
                    continue
            if (b.num and style not in cfg.title | cfg.trans_title) or style in cfg.list:
                ilvl = b.num["ilvl"] if b.num else 0
                fmt = b.num["fmt"] if b.num else "bullet"
                _append_list_item(container, b.xml, ilvl, _list_type(fmt))
                last_float = None
                i += 1
                continue
            if style in cfg.quote:
                container.append({"type": "disp-quote", "xml": b.xml})
            else:
                container.append({"type": "p", "xml": b.xml})
            last_float = None
            i += 1
        if pending_caption:
            self.warnings.append(f"legenda sem figura/tabela: {pending_caption['label']}")
        # paragrafos antes do primeiro titulo ficam numa secao sem titulo? nao: SPS aceita p direto em body
        return root["children"], refs, apps, [], pubdata_start


def _append_list_item(container: list, xml: str, ilvl: int, list_type: str) -> None:
    lst = container[-1] if container and container[-1]["type"] == "list" else None
    if lst is None:
        lst = {"type": "list", "list_type": list_type, "items": []}
        container.append(lst)
    target = lst
    for _ in range(ilvl):
        if not target["items"]:
            target["items"].append({"xml": "", "sublist": None})
        last = target["items"][-1]
        if last.get("sublist") is None:
            last["sublist"] = {"type": "list", "list_type": list_type, "items": []}
        target = last["sublist"]
    target["items"].append({"xml": xml, "sublist": None})


def _split_kwds(xml: str) -> list[str]:
    xml = xml.strip()
    xml = re.sub(r"\.\s*$", "", xml)
    sep = ";" if ";" in xml else ","
    out = []
    for piece in xml.split(sep):
        piece = piece.strip().strip(".").strip()
        # tags que abrem num pedaco e fecham noutro: descarta formatacao
        if re.search(r"<(\w+)[^>]*>", piece) and piece.count("<") % 2:
            piece = strip_tags(piece)
        if strip_tags(piece):
            out.append(piece)
    return out


def _abstract_sections(paragraphs: list[dict]) -> list[dict]:
    """Resumo estruturado: rotulo em negrito no inicio ('Objetivo.') abre secao.
    Aceita um rotulo por paragrafo ou varios no mesmo paragrafo."""
    if not paragraphs:
        return []
    joined = " ".join(p["xml"] for p in paragraphs)
    pieces = re.split(r"(<bold>[^<]{2,60}?</bold>\s*\.?)", joined)
    if len(pieces) < 3 or pieces[0].strip():
        return [{"title": "", "xml": p["xml"]} for p in paragraphs]
    sections = []
    for k in range(1, len(pieces), 2):
        title = strip_tags(pieces[k]).strip().rstrip(".:").strip()
        body = pieces[k + 1].strip() if k + 1 < len(pieces) else ""
        body = re.sub(r"^[.:]\s*", "", body)
        if not title:
            continue
        sections.append({"title": title, "xml": body})
    return sections


def _footer_meta(pkg: DocxPackage) -> dict:
    text = " ".join(pkg.footers + pkg.headers)
    meta = {}
    m = re.search(r"\bDOI:?\s*(10\.\d{4,9}/[^\s•|]+)", text, re.I) or re.search(r"(10\.\d{4,9}/[^\s•|]+)", text)
    if m:
        meta["doi"] = m.group(1).rstrip(".,;")
    m = re.search(r"\b(e\d{3,})\b", text)
    if m:
        meta["elocation"] = m.group(1)
    m = re.search(r"(?<![A-Za-z])(?:No|Nº|N\.|n\.|Núm\.?|Num\.?|Issue)\s*\.?\s*(\d+)\b", text)
    if m:
        meta["issue"] = m.group(1)
    m = re.search(r"(?<![A-Za-z])(?:v\.|Vol\.?|Volume)\s*(\d+)\b", text, re.I)
    if m:
        meta["volume"] = m.group(1)
    m = re.search(r"\((\d{4})\)", text)
    if m:
        meta["year"] = m.group(1)
    m = re.search(r"https?://[^\s•|]+", text)
    if m:
        meta["journal_url"] = m.group(0)
    meta["footer_text"] = text[:500]
    return meta


def _author_hints(pubdata: dict) -> list[str]:
    hints = []
    for role in pubdata.get("contributions", []):
        hints.extend(role["names"])
    return hints


def extract_sections(docx_path: Path, config: dict, assets_root: Path | None = None, overrides: dict | None = None) -> dict:
    """`overrides`: metadados externos (planilha) que prevalecem sobre o rodape."""
    pkg = read_docx(docx_path)
    meta = _footer_meta(pkg)
    for key, value in (overrides or {}).items():
        if value not in (None, ""):
            meta[key] = value
    base_name = sps_base_name(config.get("journal", {}), meta)
    assets_dir = assets_root / base_name if assets_root is not None else None
    builder = _Builder(pkg, config, assets_dir, base_name)
    blocks = pkg.blocks
    front, body_start = builder.front(blocks)
    body, refs_raw, apps, _, pubdata_start = builder.body(blocks, body_start)
    cfg = builder.cfg
    pub_blocks = [{"style": b.style, "text": b.text, "xml": b.xml} for b in blocks[pubdata_start:] if b.kind == "p"]
    pubdata = parse_pubdata(pub_blocks, cfg.pubdata_person, cfg.pubdata_label) if pubdata_start < len(blocks) else {"people": []}

    hints = _author_hints(pubdata)
    # autores: nome, afiliacao, ORCID/e-mail vindos dos dados de publicacao
    affs: list[dict] = []
    contribs = []
    for a in front["authors"]:
        person = _match_person(a["name"], pubdata.get("people", []))
        split = split_name(a["name"], hints)
        aff_ids = []
        for aff_text in a["aff_texts"]:
            existing = next((x for x in affs if x["original"] == aff_text), None)
            if existing is None:
                parsed = parse_aff(aff_text)
                parsed["id"] = f"aff{len(affs) + 1}"
                parsed["label"] = str(len(affs) + 1)
                # versao detalhada do bloco de dados de publicacao (departamento, UF)
                for detailed in (person or {}).get("affs", []):
                    if same_org(detailed, aff_text):
                        d = parse_aff(detailed)
                        parsed["detailed"] = detailed
                        for k in ("orgdiv1", "orgdiv2", "state"):
                            if d.get(k) and not parsed.get(k):
                                parsed[k] = d[k]
                        if d.get("city") and fold(d["city"]) != fold(parsed.get("city", "")):
                            # o texto da capa vale para 'original'; cidade divergente fica como aviso
                            builder.warnings.append(f"cidade divergente capa x dados de publicacao: {aff_text} | {detailed}")
                        break
                affs.append(parsed)
                existing = parsed
            aff_ids.append(existing["id"])
        if not a["aff_texts"]:
            builder.warnings.append(f"autor sem afiliacao: {a['name']}")
        contribs.append({
            "name_raw": a["name"], "given": split["given"], "surname": split["surname"], "name_split": split["name_split"],
            "aff_ids": aff_ids, "orcid": (person or {}).get("orcid", ""), "email": (person or {}).get("email", ""),
            "bio": (person or {}).get("bio", []),
        })
        if split["name_split"] == "heuristic" and len(a["name"].split()) > 2:
            builder.warnings.append(f"sobrenome por heuristica, revisar: {a['name']} -> {split['surname']}")

    refs = []
    for n, r in enumerate(refs_raw, 1):
        parsed = parse_reference(r["text"], r["tokens"])
        refs.append({"id": f"B{n}", "xml": r["xml"], "text": r["text"], "parsed": parsed})
        for w in parsed.get("warnings", []):
            builder.warnings.append(f"ref B{n}: {w}")

    footnotes = [
        {"id": f"fn{fn['label']}", "label": fn["label"], "xml": fn["xml"], "text": fn["text"]}
        for fn in sorted(pkg.footnotes.values(), key=lambda f: int(f["label"]))
    ]
    if not front["title"]:
        builder.warnings.append("titulo nao encontrado")
    if not front["abstracts"]:
        builder.warnings.append("resumo nao encontrado")
    if not refs:
        builder.warnings.append("referencias nao encontradas")

    return {
        "source_docx": str(docx_path),
        "extractor": "docx-ooxml",
        "base_name": base_name,
        "pages": pkg.pages,
        "meta": meta,
        "lang": front["lang"],
        "category": front["category"],
        "title": front["title"],
        "trans_titles": front["trans_titles"],
        "contribs": contribs,
        "affs": affs,
        "abstracts": [{"lang": a["lang"], "title": a["title"], "sections": a["sections"]} for a in front["abstracts"]],
        "kwd_groups": front["kwd_groups"],
        "body": body,
        "refs_title": builder.refs_title,
        "refs": refs,
        "footnotes": footnotes,
        "apps": apps,
        "pubdata": pubdata,
        "media": builder.saved_media,
        "warnings": builder.warnings,
        "confidence": "high" if not builder.warnings else ("medium" if len(builder.warnings) < 10 else "low"),
    }


def _match_person(name: str, people: list[dict]) -> dict | None:
    target = fold(name)
    for p in people:
        if fold(p["name"]) == target:
            return p
    # 'Sofia Dias De Sousa' x 'Sofia Dias de Sousa', iniciais etc.
    tset = set(target.split())
    best, score = None, 0.0
    for p in people:
        pset = set(fold(p["name"]).split())
        s = len(tset & pset) / max(len(tset | pset), 1)
        if s > score:
            best, score = p, s
    return best if score >= 0.6 else None
