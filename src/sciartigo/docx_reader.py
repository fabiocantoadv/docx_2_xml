"""Leitura de baixo nivel do DOCX (OOXML) sem python-docx.

Equivale ao papel do PyMuPDF/MinerU no pipeline de patentes: transforma o
arquivo de origem numa sequencia de blocos com o texto ja marcado em JATS
inline (<italic>, <bold>, <sup>, <sub>, <ext-link>, <xref ref-type="fn">).

Decisoes:
- mc:AlternateContent: so o ramo mc:Choice e lido (o mc:Fallback repete o
  mesmo conteudo e duplicava o texto dos hiperlinks);
- caixas de texto (w:txbxContent) nao entram no fluxo do texto; ficam em
  `textboxes` do bloco (a Biblios usa uma delas para a secao do artigo);
- revisoes: w:ins entra, w:del/w:moveFrom sao descartados;
- formatacao vem do run (w:rPr) e do estilo de caractere (w:rStyle).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from lxml import etree

from .utils import clean_text, strip_tags, xml_escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
V = "urn:schemas-microsoft-com:vml"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W, "r": R, "a": A, "wp": WP, "mc": MC, "v": V}


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


@dataclass
class Token:
    kind: str  # text | fnref | image | break
    text: str = ""
    fmt: frozenset = frozenset()
    link: str | None = None
    ref: str = ""  # id da nota ou rId da imagem


@dataclass
class Image:
    rid: str
    target: str  # caminho dentro do zip (word/media/image1.png)
    cx: int = 0  # EMU
    cy: int = 0
    descr: str = ""


@dataclass
class Block:
    kind: str  # p | table
    index: int
    style: str = ""
    style_id: str = ""
    align: str = ""
    outline_level: int | None = None
    num: dict | None = None  # {"num_id", "ilvl", "fmt"}
    xml: str = ""
    text: str = ""
    tokens: list[Token] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    textboxes: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)  # tabelas

    @property
    def leading_bold(self) -> str:
        """Texto em negrito no inicio do paragrafo (rotulos 'Objetivo.', 'Palavras-chave:')."""
        out = []
        for tok in self.tokens:
            if tok.kind != "text":
                break
            if not tok.text.strip():
                out.append(tok.text)
                continue
            if "bold" in tok.fmt:
                out.append(tok.text)
            else:
                break
        return clean_text("".join(out))


@dataclass
class DocxPackage:
    path: Path
    blocks: list[Block]
    footnotes: dict[str, dict]
    headers: list[str]
    footers: list[str]
    media: dict[str, bytes]
    pages: int | None
    styles: dict[str, str]


class _Styles:
    def __init__(self, styles_xml: bytes | None):
        self.names: dict[str, str] = {}
        self.based_on: dict[str, str] = {}
        self.rfmt: dict[str, set[str]] = {}
        self.num: dict[str, tuple[str, str]] = {}
        self.outline: dict[str, int] = {}
        if not styles_xml:
            return
        root = etree.fromstring(styles_xml)
        for st in root.iter(q(W, "style")):
            sid = st.get(q(W, "styleId")) or ""
            name = st.find("w:name", NS)
            self.names[sid] = name.get(q(W, "val")) if name is not None else sid
            based = st.find("w:basedOn", NS)
            if based is not None:
                self.based_on[sid] = based.get(q(W, "val"))
            rpr = st.find("w:rPr", NS)
            if rpr is not None:
                self.rfmt[sid] = _rpr_fmt(rpr, set())
            numpr = st.find("w:pPr/w:numPr", NS)
            if numpr is not None:
                num_id = numpr.find("w:numId", NS)
                ilvl = numpr.find("w:ilvl", NS)
                self.num[sid] = (
                    num_id.get(q(W, "val")) if num_id is not None else "",
                    ilvl.get(q(W, "val")) if ilvl is not None else "0",
                )
            outline = st.find("w:pPr/w:outlineLvl", NS)
            if outline is not None:
                self.outline[sid] = int(outline.get(q(W, "val")))

    def chain(self, sid: str):
        seen = set()
        while sid and sid not in seen:
            seen.add(sid)
            yield sid
            sid = self.based_on.get(sid, "")

    def char_fmt(self, sid: str) -> set[str]:
        out: set[str] = set()
        for s in reversed(list(self.chain(sid))):
            out = _rpr_fmt_merge(out, self.rfmt.get(s))
        return out

    def num_for(self, sid: str):
        for s in self.chain(sid):
            if s in self.num:
                return self.num[s]
        return None

    def outline_for(self, sid: str):
        for s in self.chain(sid):
            if s in self.outline:
                return self.outline[s]
        return None


def _on(el) -> bool:
    if el is None:
        return False
    val = el.get(q(W, "val"))
    return val not in ("0", "false", "off", "none")


def _rpr_fmt(rpr, base: set[str]) -> set[str]:
    out = set(base)
    for tag, name in (("b", "bold"), ("i", "italic"), ("smallCaps", "sc")):
        el = rpr.find(f"w:{tag}", NS)
        if el is not None:
            if _on(el):
                out.add(name)
            else:
                out.discard(name)
    va = rpr.find("w:vertAlign", NS)
    if va is not None:
        val = va.get(q(W, "val"))
        out.discard("sup")
        out.discard("sub")
        if val == "superscript":
            out.add("sup")
        elif val == "subscript":
            out.add("sub")
    return out


def _rpr_fmt_merge(base: set[str], fmt: set[str] | None) -> set[str]:
    return set(base) | set(fmt or ())


class _Numbering:
    def __init__(self, numbering_xml: bytes | None):
        self.fmt: dict[tuple[str, str], str] = {}
        if not numbering_xml:
            return
        root = etree.fromstring(numbering_xml)
        abstract: dict[str, dict[str, str]] = {}
        for ab in root.findall("w:abstractNum", NS):
            levels = {}
            for lvl in ab.findall("w:lvl", NS):
                fmt = lvl.find("w:numFmt", NS)
                levels[lvl.get(q(W, "ilvl"))] = fmt.get(q(W, "val")) if fmt is not None else "bullet"
            abstract[ab.get(q(W, "abstractNumId"))] = levels
        for num in root.findall("w:num", NS):
            ab_id = num.find("w:abstractNumId", NS)
            levels = abstract.get(ab_id.get(q(W, "val")) if ab_id is not None else "", {})
            for ilvl, fmt in levels.items():
                self.fmt[(num.get(q(W, "numId")), ilvl)] = fmt

    def get(self, num_id: str, ilvl: str) -> str:
        return self.fmt.get((num_id, ilvl), "bullet")


def _rels(zf: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    p = PurePosixPath(part)
    rel_path = str(p.parent / "_rels" / (p.name + ".rels"))
    if rel_path not in zf.namelist():
        return {}
    root = etree.fromstring(zf.read(rel_path))
    out = {}
    for rel in root.findall(f"{{{PR}}}Relationship"):
        target = rel.get("Target") or ""
        mode = rel.get("TargetMode") or ""
        if mode != "External" and not target.startswith(("http:", "https:", "mailto:")):
            target = str((p.parent / target)).replace("\\", "/")
            # normaliza "word/../x"
            parts: list[str] = []
            for piece in target.split("/"):
                if piece == "..":
                    if parts:
                        parts.pop()
                elif piece and piece != ".":
                    parts.append(piece)
            target = "/".join(parts)
            mode = "Internal"
        out[rel.get("Id")] = (target, mode)
    return out


class _InlineWalker:
    """Percorre o conteudo de um w:p e produz Tokens na ordem do documento."""

    def __init__(self, styles: _Styles, rels: dict[str, tuple[str, str]]):
        self.styles = styles
        self.rels = rels
        self.tokens: list[Token] = []
        self.images: list[Image] = []
        self.textboxes: list[str] = []
        # campos complexos (HYPERLINK "url")
        self._field_stack: list[dict] = []

    def _current_field_link(self) -> str | None:
        for fld in reversed(self._field_stack):
            if fld.get("separated") and fld.get("link"):
                return fld["link"]
        return None

    def _in_field_code(self) -> bool:
        return any(not f.get("separated") for f in self._field_stack)

    def walk(self, el, link: str | None = None) -> None:
        for child in el:
            tag = etree.QName(child).localname if isinstance(child.tag, str) else ""
            ns = etree.QName(child).namespace if isinstance(child.tag, str) else ""
            if ns == MC and tag == "AlternateContent":
                choice = child.find("mc:Choice", NS)
                if choice is not None:
                    self.walk(choice, link)
                continue
            if ns != W:
                # wps/wpg/v: formas; procura imagens e caixas de texto dentro
                self._scan_drawing(child)
                continue
            if tag == "r":
                self._run(child, link)
            elif tag == "hyperlink":
                rid = child.get(q(R, "id"))
                href = self.rels.get(rid, ("", ""))[0] if rid else None
                anchor = child.get(q(W, "anchor"))
                if href and anchor and "#" not in href:
                    href = f"{href}#{anchor}"
                self.walk(child, href or link)
            elif tag in ("ins", "smartTag", "customXml", "sdt", "sdtContent", "fldSimple", "moveTo", "bdo", "dir"):
                if tag == "fldSimple":
                    instr = child.get(q(W, "instr")) or ""
                    m = re.search(r'HYPERLINK\s+"([^"]+)"', instr)
                    self.walk(child, m.group(1) if m else link)
                else:
                    self.walk(child, link)
            elif tag in ("del", "moveFrom", "pPr", "proofErr", "bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd"):
                continue
            else:
                self.walk(child, link)

    def _scan_drawing(self, el) -> None:
        # desenho feito com formas do Word (wpg/wps, sem imagem raster): o
        # conteudo so existe vetorial; registra para renderizacao posterior
        for anc in el.iter(q(WP, "inline"), q(WP, "anchor")):
            if next(anc.iter(q(A, "blip")), None) is not None:
                continue
            ext = anc.find("wp:extent", NS)
            cx, cy = (int(ext.get("cx", 0)), int(ext.get("cy", 0))) if ext is not None else (0, 0)
            if cx > 914400 * 1.5 and cy > 914400:
                doc_pr = anc.find("wp:docPr", NS)
                descr = clean_text(doc_pr.get("descr") or "") if doc_pr is not None else ""
                self.images.append(Image(rid="", target="", cx=cx, cy=cy, descr=descr))
                self.tokens.append(Token("image", ref=""))
        for blip in el.iter(q(A, "blip")):
            rid = blip.get(q(R, "embed")) or blip.get(q(R, "link"))
            if rid:
                self._add_image(rid, blip)
        for imd in el.iter(q(V, "imagedata")):
            rid = imd.get(q(R, "id"))
            if rid:
                self._add_image(rid, imd)
        for tb in el.iter(q(W, "txbxContent")):
            text = clean_text("".join(t.text or "" for t in tb.iter(q(W, "t"))))
            if text:
                self.textboxes.append(text)

    def _add_image(self, rid: str, node) -> None:
        target = self.rels.get(rid, ("", ""))[0]
        if not target or target.lower().endswith(".wdp"):
            return
        cx = cy = 0
        descr = ""
        anc = node
        while anc is not None:
            if etree.QName(anc).namespace == WP and etree.QName(anc).localname in ("inline", "anchor"):
                ext = anc.find("wp:extent", NS)
                if ext is not None:
                    cx, cy = int(ext.get("cx", 0)), int(ext.get("cy", 0))
                doc_pr = anc.find("wp:docPr", NS)
                if doc_pr is not None:
                    descr = clean_text(doc_pr.get("descr") or "")
                break
            anc = anc.getparent()
        if any(img.rid == rid and img.target == target for img in self.images):
            return
        self.images.append(Image(rid=rid, target=target, cx=cx, cy=cy, descr=descr))
        self.tokens.append(Token("image", ref=rid))

    def _run(self, run, link: str | None) -> None:
        fmt: set[str] = set()
        rpr = run.find("w:rPr", NS)
        if rpr is not None:
            rstyle = rpr.find("w:rStyle", NS)
            if rstyle is not None:
                fmt = self.styles.char_fmt(rstyle.get(q(W, "val")))
            fmt = _rpr_fmt(rpr, fmt)
        ffmt = frozenset(fmt)
        for child in run:
            if not isinstance(child.tag, str):
                continue
            ns, tag = etree.QName(child).namespace, etree.QName(child).localname
            if ns == MC and tag == "AlternateContent":
                choice = child.find("mc:Choice", NS)
                if choice is not None:
                    self._scan_drawing(choice)
                continue
            if tag in ("drawing", "pict", "object"):
                self._scan_drawing(child)
                continue
            if ns != W:
                continue
            if tag == "fldChar":
                kind = child.get(q(W, "fldCharType"))
                if kind == "begin":
                    self._field_stack.append({"instr": "", "separated": False})
                elif kind == "separate" and self._field_stack:
                    fld = self._field_stack[-1]
                    fld["separated"] = True
                    m = re.search(r'HYPERLINK\s+"([^"]+)"', fld["instr"])
                    fld["link"] = m.group(1) if m else None
                elif kind == "end" and self._field_stack:
                    self._field_stack.pop()
                continue
            if tag == "instrText":
                if self._field_stack:
                    self._field_stack[-1]["instr"] += child.text or ""
                continue
            if self._in_field_code():
                continue
            effective_link = link or self._current_field_link()
            if tag == "t":
                self._text(child.text or "", ffmt, effective_link)
            elif tag in ("tab", "ptab"):
                self._text(" ", ffmt, effective_link)
            elif tag in ("br", "cr"):
                if child.get(q(W, "type")) in ("page", "column"):
                    continue
                self.tokens.append(Token("break"))
            elif tag == "noBreakHyphen":
                self._text("-", ffmt, effective_link)
            elif tag == "sym":
                code = child.get(q(W, "char")) or ""
                try:
                    self._text(symbol_char(int(code, 16), child.get(q(W, "font")) or ""), ffmt, effective_link)
                except ValueError:
                    pass
            elif tag == "footnoteReference":
                self.tokens.append(Token("fnref", ref=child.get(q(W, "id")) or ""))
            elif tag == "endnoteReference":
                self.tokens.append(Token("fnref", ref="e" + (child.get(q(W, "id")) or "")))

    def _text(self, text: str, fmt: frozenset, link: str | None) -> None:
        if text:
            self.tokens.append(Token("text", text=text, fmt=fmt, link=link))


# fonte Symbol/Wingdings: codigos na area privada (U+F0xx) -> Unicode
_SYMBOL = {0x2D: "−", 0xB7: "•", 0xAE: "→", 0xAC: "←", 0xAD: "↑", 0xAF: "↓", 0xB0: "°", 0xB1: "±", 0xB4: "×",
           0xB8: "÷", 0xA3: "≤", 0xB3: "≥", 0xB9: "≠", 0xBB: "≈", 0xA5: "∞", 0xD6: "√", 0xE5: "∑", 0xF2: "∫",
           0x61: "α", 0x62: "β", 0x63: "χ", 0x64: "δ", 0x65: "ε", 0x66: "φ", 0x67: "γ", 0x68: "η", 0x6C: "λ",
           0x6D: "μ", 0x70: "π", 0x71: "θ", 0x72: "ρ", 0x73: "σ", 0x74: "τ", 0x77: "ω", 0x44: "Δ", 0x53: "Σ",
           0x57: "Ω", 0x46: "Φ", 0x50: "Π", 0x47: "Γ", 0x4C: "Λ", 0xA7: "♣", 0xA8: "♦", 0xA9: "♥", 0xAA: "♠"}


def symbol_char(code: int, font: str = "") -> str:
    if 0xF000 <= code <= 0xF0FF:
        code -= 0xF000
        if "symbol" in font.lower() or not font:
            return _SYMBOL.get(code, chr(code))
        if "wingdings" in font.lower():
            return {0x9F: "•", 0xA7: "▪", 0xD8: "➢", 0xE0: "→", 0xFC: "✓", 0x6C: "●", 0x6E: "■"}.get(code, "•")
        return chr(code)
    return chr(code)


_FMT_ORDER = (("bold", "bold"), ("italic", "italic"), ("sc", "sc"), ("sup", "sup"), ("sub", "sub"))


def _wrap(text: str, fmt: frozenset) -> str:
    """Envolve texto escapado nas tags de formatacao, deixando espacos de borda fora."""
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    core = text.strip()
    if not core:
        return xml_escape(text)
    out = xml_escape(core)
    for name, tag in reversed(_FMT_ORDER):
        if name in fmt:
            out = f"<{tag}>{out}</{tag}>"
    return xml_escape(lead) + out + xml_escape(trail)


def _render_plain(tokens: list[Token]) -> str:
    # espacos isolados entre dois trechos de mesma formatacao herdam a formatacao
    toks = [Token(t.kind, t.text, t.fmt, t.link, t.ref) for t in tokens]
    for i, tok in enumerate(toks):
        if tok.kind == "text" and not tok.text.strip() and 0 < i < len(toks) - 1:
            prev, nxt = toks[i - 1], toks[i + 1]
            if prev.fmt == nxt.fmt:
                tok.fmt = prev.fmt
        if tok.kind == "text" and not tok.text.strip():
            pass
    merged: list[list] = []
    for tok in toks:
        fmt = tok.fmt if tok.text.strip() else (merged[-1][0] if merged else frozenset())
        if merged and merged[-1][0] == fmt:
            merged[-1][1] += tok.text
        else:
            merged.append([fmt, tok.text])
    return "".join(_wrap(text, fmt) for fmt, text in merged)


def render_tokens(tokens: list[Token], fn_labels: dict[str, str] | None = None) -> str:
    fn_labels = fn_labels or {}
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.kind == "text":
            j = i
            while j < len(tokens) and tokens[j].kind == "text" and tokens[j].link == tok.link:
                j += 1
            inner = _render_plain(tokens[i:j])
            if tok.link:
                href = tok.link.strip()
                if href.lower().startswith("mailto:"):
                    out.append(f"<email>{xml_escape(href[7:])}</email>")
                elif re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]+:", href):
                    lead = inner[: len(inner) - len(inner.lstrip())]
                    trail = inner[len(inner.rstrip()):]
                    out.append(f'{lead}<ext-link ext-link-type="uri" xlink:href="{xml_escape(href)}">{inner.strip()}</ext-link>{trail}')
                else:
                    out.append(inner)  # ancora interna: so o texto
            else:
                out.append(inner)
            i = j
            continue
        if tok.kind == "fnref":
            label = fn_labels.get(tok.ref, tok.ref)
            out.append(f'<xref ref-type="fn" rid="fn{xml_escape(label)}"><sup>{xml_escape(label)}</sup></xref>')
        elif tok.kind == "break":
            out.append(" ")
        i += 1
    xml = "".join(out)
    xml = re.sub(r"[ \t\r\n ]{2,}", " ", xml)
    return xml.strip()


def _paragraph_block(p, index: int, styles: _Styles, numbering: _Numbering, rels) -> Block:
    ppr = p.find("w:pPr", NS)
    style_id = ""
    align = ""
    num = None
    outline = None
    if ppr is not None:
        ps = ppr.find("w:pStyle", NS)
        if ps is not None:
            style_id = ps.get(q(W, "val")) or ""
        jc = ppr.find("w:jc", NS)
        if jc is not None:
            align = jc.get(q(W, "val")) or ""
        numpr = ppr.find("w:numPr", NS)
        if numpr is not None:
            nid = numpr.find("w:numId", NS)
            ilvl = numpr.find("w:ilvl", NS)
            num_id = nid.get(q(W, "val")) if nid is not None else ""
            if num_id and num_id != "0":
                lvl = ilvl.get(q(W, "val")) if ilvl is not None else "0"
                num = {"num_id": num_id, "ilvl": int(lvl), "fmt": numbering.get(num_id, lvl)}
        ol = ppr.find("w:outlineLvl", NS)
        if ol is not None:
            outline = int(ol.get(q(W, "val")))
    if num is None and style_id:
        snum = styles.num_for(style_id)
        if snum and snum[0] and snum[0] != "0":
            num = {"num_id": snum[0], "ilvl": int(snum[1] or 0), "fmt": numbering.get(snum[0], snum[1] or "0")}
    if outline is None and style_id:
        outline = styles.outline_for(style_id)
    walker = _InlineWalker(styles, rels)
    walker.walk(p)
    block = Block(
        kind="p",
        index=index,
        style=styles.names.get(style_id, style_id or "Normal"),
        style_id=style_id,
        align=align,
        outline_level=outline,
        num=num,
        tokens=walker.tokens,
        images=walker.images,
        textboxes=walker.textboxes,
    )
    return block


def _table_block(tbl, index: int, styles: _Styles, numbering: _Numbering, rels) -> Block:
    rows = []
    for tr in tbl.findall("w:tr", NS):
        header = tr.find("w:trPr/w:tblHeader", NS) is not None and _on(tr.find("w:trPr/w:tblHeader", NS))
        cells = []
        for tc in tr.findall("w:tc", NS):
            tcpr = tc.find("w:tcPr", NS)
            span = 1
            vmerge = None
            if tcpr is not None:
                gs = tcpr.find("w:gridSpan", NS)
                if gs is not None:
                    span = int(gs.get(q(W, "val")) or 1)
                vm = tcpr.find("w:vMerge", NS)
                if vm is not None:
                    vmerge = vm.get(q(W, "val")) or "continue"
            paras = [_paragraph_block(p, -1, styles, numbering, rels) for p in tc.iter(q(W, "p"))]
            cells.append({"paragraphs": paras, "colspan": span, "vmerge": vmerge})
        rows.append({"header": header, "cells": cells})
    return Block(kind="table", index=index, rows=rows)


def _iter_body(el):
    for child in el:
        if not isinstance(child.tag, str):
            continue
        tag = etree.QName(child).localname
        if tag in ("p", "tbl"):
            yield child
        elif tag in ("sdt", "sdtContent", "customXml", "ins"):
            yield from _iter_body(child)


def _part_text(zf: zipfile.ZipFile, name: str) -> str:
    root = etree.fromstring(zf.read(name))
    paras = []
    for p in root.iter(q(W, "p")):
        pieces = []
        for node in p.iter():
            if node.tag == q(W, "t"):
                pieces.append(node.text or "")
            elif node.tag in (q(W, "tab"), q(W, "ptab")):
                pieces.append(" ")
        paras.append("".join(pieces))
    return clean_text(" ".join(paras))


def read_docx(path: Path) -> DocxPackage:
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        styles = _Styles(zf.read("word/styles.xml") if "word/styles.xml" in names else None)
        numbering = _Numbering(zf.read("word/numbering.xml") if "word/numbering.xml" in names else None)
        rels = _rels(zf, "word/document.xml")
        doc = etree.fromstring(zf.read("word/document.xml"))
        body = doc.find("w:body", NS)

        # notas de rodape: rotulo sequencial na ordem do arquivo
        footnotes: dict[str, dict] = {}
        for part, prefix in (("word/footnotes.xml", ""), ("word/endnotes.xml", "e")):
            if part not in names:
                continue
            frels = _rels(zf, part)
            froot = etree.fromstring(zf.read(part))
            for fn in froot:
                if not isinstance(fn.tag, str) or etree.QName(fn).localname not in ("footnote", "endnote"):
                    continue
                if fn.get(q(W, "type")) in ("separator", "continuationSeparator", "continuationNotice"):
                    continue
                walker = _InlineWalker(styles, frels)
                for p in fn.findall("w:p", NS):
                    walker.walk(p)
                    walker.tokens.append(Token("text", text=" "))
                footnotes[prefix + (fn.get(q(W, "id")) or "")] = {"tokens": walker.tokens}

        blocks: list[Block] = []
        for i, el in enumerate(_iter_body(body)):
            if etree.QName(el).localname == "p":
                blocks.append(_paragraph_block(el, i, styles, numbering, rels))
            else:
                blocks.append(_table_block(el, i, styles, numbering, rels))

        # rotulos das notas na ordem de chamada no texto
        order: list[str] = []
        for b in blocks:
            for tok in _all_tokens(b):
                if tok.kind == "fnref" and tok.ref not in order:
                    order.append(tok.ref)
        labels = {ref: str(n) for n, ref in enumerate(order, 1)}
        for b in blocks:
            _finish_block(b, labels)
        for ref, fn in footnotes.items():
            fn["label"] = labels.get(ref, "")
            fn["xml"] = render_tokens(fn["tokens"], labels)
            fn["text"] = strip_tags(fn["xml"])
            del fn["tokens"]
        footnotes = {k: v for k, v in footnotes.items() if v["label"] and v["text"]}

        headers = [_part_text(zf, n) for n in sorted(names) if re.match(r"word/header\d*\.xml$", n)]
        footers = [_part_text(zf, n) for n in sorted(names) if re.match(r"word/footer\d*\.xml$", n)]
        media = {n: zf.read(n) for n in names if n.startswith("word/media/")}
        pages = None
        if "docProps/app.xml" in names:
            m = re.search(rb"<Pages>(\d+)</Pages>", zf.read("docProps/app.xml"))
            if m:
                pages = int(m.group(1))
    return DocxPackage(
        path=path,
        blocks=blocks,
        footnotes=footnotes,
        headers=[h for h in headers if h],
        footers=[f for f in footers if f],
        media=media,
        pages=pages,
        styles=styles.names,
    )


def _all_tokens(block: Block):
    if block.kind == "p":
        yield from block.tokens
    else:
        for row in block.rows:
            for cell in row["cells"]:
                for p in cell["paragraphs"]:
                    yield from p.tokens


def _finish_block(block: Block, labels: dict[str, str]) -> None:
    if block.kind == "p":
        block.xml = render_tokens(block.tokens, labels)
        block.text = strip_tags(block.xml)
    else:
        for row in block.rows:
            for cell in row["cells"]:
                for p in cell["paragraphs"]:
                    _finish_block(p, labels)
        block.text = " | ".join(
            " ".join(p.text for p in cell["paragraphs"]) for row in block.rows for cell in row["cells"]
        )
