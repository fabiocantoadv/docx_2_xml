"""Montagem do XML SciELO PS 1.8 (JATS 1.1) a partir do JSON de secoes.

Equivale ao st36.py do pipeline de patentes. Ordem dos elementos segue o
modelo de conteudo da DTD JATS Publishing 1.1; regras de estilo seguem o
schematron sps-1.8 (pub-date com date-type/publication-format, aff com
institution[@content-type='original'], element-citation com
@publication-type, counts coerentes, etc.).
"""

from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

from .citations import build_index, link_citations
from .utils import clean_text, fold, strip_tags, xml_escape

XLINK = "http://www.w3.org/1999/xlink"
MML = "http://www.w3.org/1998/Math/MathML"
XML_NS = "http://www.w3.org/XML/1998/namespace"
DOCTYPE = (
    '<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Publishing DTD v1.1 20151215//EN" '
    '"https://jats.nlm.nih.gov/publishing/1.1/JATS-journalpublishing1.dtd">'
)

LICENSES = [
    (r"\bCC[\s-]*BY[\s-]*NC[\s-]*ND\b|Attribution[\s-]*NonCommercial[\s-]*NoDerivatives?", "by-nc-nd"),
    (r"\bCC[\s-]*BY[\s-]*NC[\s-]*SA\b|Attribution[\s-]*NonCommercial[\s-]*ShareAlike", "by-nc-sa"),
    (r"\bCC[\s-]*BY[\s-]*NC\b|Attribution[\s-]*NonCommercial", "by-nc"),
    (r"\bCC[\s-]*BY[\s-]*ND\b|Attribution[\s-]*NoDerivatives?", "by-nd"),
    (r"\bCC[\s-]*BY[\s-]*SA\b|Attribution[\s-]*ShareAlike", "by-sa"),
    (r"\bCC[\s-]*BY\b|Creative Commons Attribution|Atribui[cç][aã]o", "by"),
]

PUBDATA_FN = ("preprint", "work_info", "ai_use", "image_consent", "ethics", "data_availability")


def _x(tag: str) -> str:
    return f"{{{XLINK}}}{tag}"


def _sub(parent, tag: str, text: str | None = None, **attrs) -> etree._Element:
    el = etree.SubElement(parent, tag)
    for k, v in attrs.items():
        if v is None or v == "":
            continue
        k = k.rstrip("_").replace("__", ":")
        if k == "xml:lang":
            el.set(f"{{{XML_NS}}}lang", v)
        elif k.startswith("xlink:"):
            el.set(_x(k[6:]), v)
        else:
            el.set(k.replace("_", "-"), v)
    if text:
        el.text = text
    return el


_URL_RE = re.compile(r"(https?://[^\s<>\"]+[^\s<>\".,;:)\]])")


def autolink(fragment: str) -> str:
    """URLs soltas viram <ext-link> (fora de ext-link/xref/email existentes)."""
    if "http" not in (fragment or ""):
        return fragment
    out = []
    depth = 0
    for piece in re.split(r"(<[^>]+>)", fragment):
        if piece.startswith("<"):
            m = re.match(r"</?([\w:-]+)", piece)
            name = m.group(1) if m else ""
            if name in ("ext-link", "xref", "email", "uri"):
                depth += -1 if piece.startswith("</") else (0 if piece.endswith("/>") else 1)
            out.append(piece)
        elif depth == 0:
            out.append(_URL_RE.sub(lambda m: f'<ext-link ext-link-type="uri" xlink:href="{m.group(1)}">{m.group(1)}</ext-link>', piece))
        else:
            out.append(piece)
    return "".join(out)


def append_fragment(parent: etree._Element, fragment: str) -> None:
    """Anexa um fragmento JATS inline (texto + tags) ao final de `parent`."""
    if not fragment:
        return
    wrapper = etree.fromstring(f'<w xmlns:xlink="{XLINK}" xmlns:mml="{MML}">{fragment}</w>')
    if wrapper.text:
        if len(parent):
            last = parent[-1]
            last.tail = (last.tail or "") + wrapper.text
        else:
            parent.text = (parent.text or "") + wrapper.text
    for child in list(wrapper):
        parent.append(child)


class Builder:
    def __init__(self, sections: dict, config: dict, meta: dict, base_name: str):
        self.s = sections
        self.cfg = config
        self.meta = meta  # rodape + overrides (doi, volume, issue, elocation, datas...)
        self.base = base_name
        self.warnings: list[str] = []
        self.cite_index = build_index(sections.get("refs", []))
        self.xref_count = 0
        self.cited_refs: set[str] = set()

    # ---------- texto ----------
    def frag(self, xml: str, link: bool = True) -> str:
        xml = autolink(xml or "")
        if link:
            xml, n = link_citations(xml, self.cite_index)
            self.xref_count += n
            self.cited_refs.update(re.findall(r'ref-type="bibr" rid="([^"]+)"', xml))
        return xml

    def p(self, parent, xml: str, link: bool = True, tag: str = "p") -> etree._Element:
        el = _sub(parent, tag)
        append_fragment(el, self.frag(xml, link))
        return el

    # ---------- documento ----------
    def build(self) -> etree._ElementTree:
        s, d = self.s, self.cfg.get("defaults", {})
        cat = self._category()
        lang = s.get("lang") or d.get("lang", "pt")
        article = etree.Element(
            "article",
            nsmap={"xlink": XLINK, "mml": MML},
        )
        article.set("article-type", self.meta.get("article_type") or cat.get("article_type") or d.get("article_type", "research-article"))
        article.set("dtd-version", "1.1")
        article.set("specific-use", "sps-1.8")
        article.set(f"{{{XML_NS}}}lang", lang)
        front = _sub(article, "front")
        self.journal_meta(front)
        self.article_meta(front, lang, cat)
        self.body(article)
        self.back(article, lang)
        self.counts(article)
        unused = [r["id"] for r in s.get("refs", []) if r["id"] not in self.cited_refs]
        if unused:
            self.warnings.append(f"referencias sem chamada ligada no texto: {', '.join(unused)}")
        return etree.ElementTree(article)

    def _category(self) -> dict:
        raw = self.meta.get("subject") or self.s.get("category") or ""
        cats = self.cfg.get("categories", {})
        hit = cats.get(fold(raw)) if raw else None
        if hit:
            return hit
        if raw:
            return {"subject": raw[:1].upper() + raw[1:]}
        return {}

    def journal_meta(self, front) -> None:
        j = self.cfg["journal"]
        jm = _sub(front, "journal-meta")
        _sub(jm, "journal-id", j.get("journal_id") or j.get("acron"), journal_id_type="publisher-id")
        jtg = _sub(jm, "journal-title-group")
        _sub(jtg, "journal-title", j.get("title"))
        _sub(jtg, "abbrev-journal-title", j.get("abbrev_title") or j.get("title"), abbrev_type="publisher")
        if j.get("issn_epub"):
            _sub(jm, "issn", j["issn_epub"], pub_type="epub")
        if j.get("issn_ppub"):
            _sub(jm, "issn", j["issn_ppub"], pub_type="ppub")
        pub = _sub(jm, "publisher")
        _sub(pub, "publisher-name", j.get("publisher"))

    def article_meta(self, front, lang: str, cat: dict) -> None:
        s, m, d = self.s, self.meta, self.cfg.get("defaults", {})
        am = _sub(front, "article-meta")
        if m.get("doi"):
            _sub(am, "article-id", m["doi"], pub_id_type="doi")
        else:
            self.warnings.append("DOI ausente")
        ac = _sub(am, "article-categories")
        sg = _sub(ac, "subj-group", subj_group_type="heading")
        _sub(sg, "subject", cat.get("subject") or d.get("subject") or "Artigo")

        tg = _sub(am, "title-group")
        title = _sub(tg, "article-title")
        append_fragment(title, self.frag((s.get("title") or {}).get("xml", ""), link=False))
        for tt in s.get("trans_titles", []):
            ttg = _sub(tg, "trans-title-group", xml__lang=tt["lang"] or None)
            if not tt["lang"]:
                self.warnings.append(f"idioma do titulo traduzido nao identificado: {tt['text'][:50]}")
            el = _sub(ttg, "trans-title")
            append_fragment(el, self.frag(tt["xml"], link=False))

        cg = _sub(am, "contrib-group")
        aff_labels = {a["id"]: a["label"] for a in s.get("affs", [])}
        for c in s.get("contribs", []):
            contrib = _sub(cg, "contrib", contrib_type="author")
            if c.get("orcid"):
                _sub(contrib, "contrib-id", c["orcid"], contrib_id_type="orcid")
            name = _sub(contrib, "name")
            _sub(name, "surname", c["surname"])
            if c.get("given"):
                _sub(name, "given-names", c["given"])
            if c.get("email"):
                _sub(contrib, "email", c["email"])
            for aid in c.get("aff_ids", []):
                xref = _sub(contrib, "xref", ref_type="aff", rid=aid)
                _sub(xref, "sup", aff_labels.get(aid, ""))
        country_mode = self.cfg.get("output", {}).get("country_text", "original")
        for a in s.get("affs", []):
            aff = _sub(am, "aff", id=a["id"])
            _sub(aff, "label", a["label"])
            _sub(aff, "institution", a["original"], content_type="original")
            if a.get("orgname"):
                _sub(aff, "institution", a["orgname"], content_type="orgname")
            for k in ("orgdiv1", "orgdiv2"):
                if a.get(k):
                    _sub(aff, "institution", a[k], content_type=k)
            if a.get("city") or a.get("state"):
                al = _sub(aff, "addr-line")
                if a.get("city"):
                    _sub(al, "city", a["city"])
                if a.get("state"):
                    _sub(al, "state", a["state"])
            if a.get("country"):
                _sub(aff, "country", a["country"], country=a.get("country_code") or None)
                if not a.get("country_code"):
                    self.warnings.append(f"pais sem codigo ISO: {a['country']}")
            else:
                self.warnings.append(f"afiliacao sem pais: {a['original']}")

        self.author_notes(am)

        hist = (s.get("pubdata") or {}).get("history", {})
        pub = m.get("pub_date") or hist.get("pub")
        if pub:
            pd = _sub(am, "pub-date", publication_format="electronic", date_type="pub")
            self._date_parts(pd, pub)
        else:
            self.warnings.append("data de publicacao ausente (pub-date date-type=pub)")
        coll_year = m.get("collection_year") or m.get("year") or (pub or "")[:4]
        if coll_year:
            pc = _sub(am, "pub-date", publication_format="electronic", date_type="collection")
            if m.get("season"):
                _sub(pc, "season", m["season"])
            _sub(pc, "year", coll_year)
        if m.get("volume"):
            _sub(am, "volume", m["volume"])
        if m.get("issue"):
            _sub(am, "issue", m["issue"])
        if m.get("elocation"):
            _sub(am, "elocation-id", m["elocation"])
        elif m.get("fpage"):
            _sub(am, "fpage", m["fpage"])
            if m.get("lpage"):
                _sub(am, "lpage", m["lpage"])
        else:
            self.warnings.append("sem elocation-id nem fpage")

        if any(k in hist for k in ("received", "accepted", "rev-recd")):
            h = _sub(am, "history")
            for key in ("received", "rev-recd", "accepted"):
                if hist.get(key):
                    dt = _sub(h, "date", date_type=key)
                    self._date_parts(dt, hist[key])

        self.permissions(am, lang)

        for n, ab in enumerate(s.get("abstracts", [])):
            if n == 0 and ab["lang"] == lang:
                el = _sub(am, "abstract")
            else:
                el = _sub(am, "trans-abstract", xml__lang=ab["lang"])
            _sub(el, "title", ab["title"])
            for sec in ab["sections"]:
                if sec["title"]:
                    se = _sub(el, "sec")
                    _sub(se, "title", sec["title"])
                    self.p(se, sec["xml"], link=False)
                else:
                    self.p(el, sec["xml"], link=False)
        for kg in s.get("kwd_groups", []):
            g = _sub(am, "kwd-group", xml__lang=kg["lang"] or lang)
            _sub(g, "title", kg["title"])
            for k in kg["kwds"]:
                kw = _sub(g, "kwd")
                append_fragment(kw, k)
        self.funding(am)
        self._counts_placeholder = _sub(am, "counts")

    def _date_parts(self, el, iso: str) -> None:
        parts = iso.split("-")
        if len(parts) > 2:
            _sub(el, "day", parts[2])
        if len(parts) > 1:
            _sub(el, "month", parts[1])
        _sub(el, "year", parts[0])

    def author_notes(self, am) -> None:
        pd = self.s.get("pubdata") or {}
        notes = []
        if pd.get("contributions"):
            lines = []
            for r in pd["contributions"]:
                lines.append(f"<bold>{xml_escape(r['role'])}:</bold> {xml_escape('; '.join(r['names']))}" if r["role"] else xml_escape("; ".join(r["names"])))
            notes.append(("con", lines))
        conflict = pd.get("conflict")
        if conflict and conflict.get("text"):
            notes.append(("conflict", [conflict["xml"]]))
        editors = pd.get("editors")
        if editors and editors.get("text") and not editors.get("not_applicable"):
            notes.append(("edited-by", [f"<bold>{xml_escape(editors['label'])}:</bold> {editors['xml']}"]))
        if not notes:
            return
        an = _sub(am, "author-notes")
        for fn_type, paras in notes:
            fn = _sub(an, "fn", fn_type=fn_type)
            for para in paras:
                self.p(fn, para, link=False)

    def permissions(self, am, lang: str) -> None:
        pd = self.s.get("pubdata") or {}
        d = self.cfg.get("defaults", {})
        lic = pd.get("license") or {}
        text = lic.get("text", "")
        url = self.meta.get("license_url") or ""
        if not url and text:
            m = re.search(r"https?://creativecommons\.org/licenses/[\w./-]+", lic.get("xml", ""))
            if m:
                url = m.group(0)
            else:
                version = re.search(r"\b([1-4]\.0)\b", text)
                for pat, code in LICENSES:
                    if re.search(pat, text, re.I):
                        url = f"https://creativecommons.org/licenses/{code}/{version.group(1) if version else '4.0'}/"
                        break
        if not url:
            url = d.get("license_url", "")
            self.warnings.append("licenca nao identificada no texto: usando a padrao da revista")
        url = url.replace("http://", "https://")
        perm = _sub(am, "permissions")
        license_el = _sub(perm, "license", license_type="open-access", xlink__href=url, xml__lang=lang)
        lp = _sub(license_el, "license-p")
        append_fragment(lp, self.frag(lic.get("xml") or xml_escape(d.get("license_text", "")), link=False))

    def funding(self, am) -> None:
        f = (self.s.get("pubdata") or {}).get("funding")
        if not f or f.get("not_applicable") or not f.get("text"):
            return
        fg = _sub(am, "funding-group")
        found = 0
        # uma award-group por agencia nomeada com sigla: 'Conselho Nacional ... (CNPq)'
        org_re = re.compile(r"((?:[A-ZÀ-Ý][\wÀ-ÿ'’-]*)(?:\s+(?:[A-ZÀ-Ý][\wÀ-ÿ'’-]*|de|da|do|dos|das|e|y|para|of|for|the|and|–|-))*\s*\(([A-Z][A-Za-z/&-]{1,15})\))")
        award_re = re.compile(r"(?:processo|process|c[oó]digo de financiamento|grant|projeto|n[º°.])\s*:?\s*(?:n[º°.]?\s*)?([\w./-]*\d[\w./-]*)", re.I)
        for chunk in re.split(r";", f["text"]):
            for om in org_re.finditer(chunk):
                name = re.sub(r"^(?:(?:E|O|A|Os|As|Do|Da|De|Dos|Das|Financiamento|Financiado|Apoio|Bolsa|Aux[ií]lio|Funded|Supported)\s+(?:(?:pelo|pela|por|do|da|de|dos|das|by)\s+)?)+(?=[A-ZÀ-Ý])", "", om.group(1)).strip()
                if len(name.split()) < 2:
                    continue
                ag = _sub(fg, "award-group")
                _sub(ag, "funding-source", name)
                for award in award_re.findall(chunk[om.end():]):
                    _sub(ag, "award-id", award.rstrip("."))
                found += 1
        if not found:
            ag = _sub(fg, "award-group")
            _sub(ag, "funding-source", clean_text(f["text"]).rstrip("."))
            self.warnings.append("funding-source igual ao enunciado: revisar agencia/processo")
        st = _sub(fg, "funding-statement")
        append_fragment(st, self.frag(f["xml"], link=False))

    # ---------- corpo ----------
    def body(self, article) -> None:
        body = _sub(article, "body")
        for item in self.s.get("body", []):
            if item["type"] == "ack":
                continue
            self.block(body, item)

    def block(self, parent, item: dict) -> None:
        t = item["type"]
        if t == "sec":
            sec = _sub(parent, "sec", sec_type=item.get("sec_type") or None)
            title = _sub(sec, "title")
            append_fragment(title, self.frag(re.sub(r"^\s*\d+(\.\d+)*\.?\s+", "", item["title"]["xml"]), link=False))
            for child in item["children"]:
                self.block(sec, child)
        elif t == "p":
            self.p(parent, item["xml"])
        elif t == "disp-quote":
            dq = _sub(parent, "disp-quote")
            self.p(dq, item["xml"])
        elif t == "list":
            self.list(parent, item)
        elif t == "fig":
            self.fig(parent, item)
        elif t == "table-wrap":
            self.table(parent, item)

    def list(self, parent, item: dict) -> None:
        lst = _sub(parent, "list", list_type=item["list_type"])
        for it in item["items"]:
            li = _sub(lst, "list-item")
            self.p(li, it["xml"])
            if it.get("sublist"):
                self.list(li, it["sublist"])

    def _caption(self, parent, item: dict) -> None:
        if item.get("label"):
            _sub(parent, "label", item["label"])
        if item.get("title"):
            cap = _sub(parent, "caption")
            ti = _sub(cap, "title")
            append_fragment(ti, self.frag(item["title"]["xml"].strip().rstrip(".") if item["title"]["xml"].strip().endswith(".") and not item["title"]["xml"].strip().endswith("..") else item["title"]["xml"], link=False))
        elif item.get("label"):
            self.warnings.append(f"{item['label']}: sem titulo de legenda")

    def fig(self, parent, item: dict) -> None:
        fig = _sub(parent, "fig", id=item["id"])
        self._caption(fig, item)
        if item.get("alt"):
            _sub(fig, "alt-text", item["alt"][:250])
        href = item.get("graphic") or f"{self.base}-g{item['id']}.png"
        if not item.get("graphic"):
            self.warnings.append(f"{item['id']}: imagem pendente ({href})")
        _sub(fig, "graphic", xlink__href=href)
        for note in item.get("notes", []):
            at = _sub(fig, "attrib")
            append_fragment(at, self.frag(note["xml"]))

    def table(self, parent, item: dict) -> None:
        tw = _sub(parent, "table-wrap", id=item["id"])
        self._caption(tw, item)
        if item.get("graphic"):
            _sub(tw, "graphic", xlink__href=item["graphic"])
        elif item.get("rows"):
            table = _sub(tw, "table")
            head_rows = [r for r in item["rows"] if r["header"]]
            body_rows = [r for r in item["rows"] if not r["header"]]
            if not head_rows and len(item["rows"]) > 1 and self.cfg.get("output", {}).get("first_row_header", True):
                head_rows, body_rows = item["rows"][:1], item["rows"][1:]
            for rows, section, cell_tag in ((head_rows, "thead", "th"), (body_rows, "tbody", "td")):
                if not rows:
                    continue
                sec = _sub(table, section)
                for row in rows:
                    tr = _sub(sec, "tr")
                    for cell in row["cells"]:
                        c = _sub(tr, cell_tag, colspan=str(cell["colspan"]) if cell["colspan"] > 1 else None,
                                 rowspan=str(cell["rowspan"]) if cell["rowspan"] > 1 else None)
                        append_fragment(c, self.frag(cell["xml"].replace("<break/>", "<break/>")))
        if item.get("notes"):
            foot = _sub(tw, "table-wrap-foot")
            for n, note in enumerate(item["notes"], 1):
                fn = _sub(foot, "fn", id=f"{item['id']}fn{n}")
                self.p(fn, note["xml"])

    # ---------- back ----------
    def back(self, article, lang: str) -> None:
        s = self.s
        back = _sub(article, "back")
        pd = s.get("pubdata") or {}
        ack_items = [i for i in s.get("body", []) if i["type"] == "ack"]
        if ack_items or (pd.get("ack") and pd["ack"].get("text") and not pd["ack"].get("not_applicable")):
            ack = _sub(back, "ack")
            if ack_items:
                _sub(ack, "title", ack_items[0]["title"]["text"])
                for child in ack_items[0]["children"]:
                    if child["type"] == "p":
                        self.p(ack, child["xml"])
            else:
                _sub(ack, "title", pd["ack"].get("label") or "Agradecimentos")
                self.p(ack, pd["ack"]["xml"])
        if s.get("refs"):
            rl = _sub(back, "ref-list")
            _sub(rl, "title", self.cfg.get("output", {}).get("ref_list_title") or s.get("refs_title") or "Referências")
            for ref in s["refs"]:
                self.ref(rl, ref)
        fns = list(s.get("footnotes", []))
        extra = []
        for key in PUBDATA_FN:
            item = pd.get(key)
            if item and item.get("text") and not item.get("not_applicable"):
                extra.append((key, item))
        if fns or extra:
            fg = _sub(back, "fn-group")
            for fn in fns:
                el = _sub(fg, "fn", fn_type="other", id=fn["id"])
                _sub(el, "label", fn["label"])
                self.p(el, fn["xml"])
            for key, item in extra:
                el = _sub(fg, "fn", fn_type="other", id=f"fn-{key.replace('_', '-')}")
                self.p(el, f"<bold>{xml_escape(item['label'])}:</bold> {item['xml']}")
        if s.get("apps"):
            ag = _sub(back, "app-group")
            for n, app in enumerate(s["apps"], 1):
                el = _sub(ag, "app", id=f"app{n}")
                ti = _sub(el, "title")
                append_fragment(ti, self.frag(app["title"]["xml"], link=False))
                for child in app["children"]:
                    self.block(el, child)

    def ref(self, rl, ref: dict) -> None:
        p = ref["parsed"]
        el = _sub(rl, "ref", id=ref["id"])
        mc = _sub(el, "mixed-citation")
        append_fragment(mc, autolink(ref["xml"]))
        ec = _sub(el, "element-citation", publication_type=p["publication_type"])
        if p["authors"] or p["collab"]:
            pg = _sub(ec, "person-group", person_group_type="author")
            if p["collab"]:
                _sub(pg, "collab", p["collab"])
            for a in p["authors"]:
                nm = _sub(pg, "name")
                _sub(nm, "surname", a["surname"])
                if a["given"]:
                    _sub(nm, "given-names", a["given"])
            if p["etal"]:
                _sub(pg, "etal")
        if p.get("editors"):
            pg = _sub(ec, "person-group", person_group_type=p.get("editors_role", "editor"))
            for a in p["editors"]:
                nm = _sub(pg, "name")
                _sub(nm, "surname", a["surname"])
                if a["given"]:
                    _sub(nm, "given-names", a["given"])
        if p["article_title"]:
            _sub(ec, "article-title", p["article_title"])
        if p["chapter_title"]:
            _sub(ec, "chapter-title", p["chapter_title"])
        if p["source"]:
            _sub(ec, "source", p["source"])
        for key, tag in (("series", "series"), ("edition", "edition"), ("publisher_loc", "publisher-loc"),
                         ("publisher_name", "publisher-name"), ("volume", "volume"), ("issue", "issue")):
            if p.get(key):
                _sub(ec, tag, p[key])
        if p.get("elocation"):
            _sub(ec, "elocation-id", p["elocation"])
        elif p.get("fpage"):
            _sub(ec, "fpage", p["fpage"])
            if p.get("lpage"):
                _sub(ec, "lpage", p["lpage"])
        if p.get("size_pages"):
            _sub(ec, "size", p["size_pages"], units="pages")
        if p.get("year"):
            _sub(ec, "year", p["year"] + p.get("year_letter", ""))
        if p.get("thesis_degree"):
            _sub(ec, "comment", p["thesis_degree"].strip("()"))
        if p.get("doi"):
            _sub(ec, "pub-id", p["doi"], pub_id_type="doi")
        if p.get("uri"):
            cm = _sub(ec, "comment", (p.get("comment_prefix") or "Disponível em:") + " ")
            _sub(cm, "ext-link", p["uri"], ext_link_type="uri", xlink__href=p["uri"])
        if p.get("access_date"):
            _sub(ec, "date-in-citation", p["access_date"], content_type="access-date",
                 iso_8601_date=p.get("access_date_iso") if len(p.get("access_date_iso", "")) == 10 else None)

    def counts(self, article) -> None:
        c = self._counts_placeholder
        _sub(c, "fig-count", count=str(len(article.findall(".//fig"))))
        _sub(c, "table-count", count=str(len(article.findall(".//table-wrap"))))
        _sub(c, "equation-count", count=str(len(article.findall(".//disp-formula"))))
        _sub(c, "ref-count", count=str(len(article.findall(".//ref"))))
        pages = self.meta.get("page_count") or self.s.get("pages")
        if pages:
            _sub(c, "page-count", count=str(pages))


def write_article(tree: etree._ElementTree, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _indent(tree.getroot())
    tree.write(str(output_path), encoding="utf-8", xml_declaration=True, doctype=DOCTYPE)


# elementos com conteudo misto: a indentacao nunca entra neles
NO_INDENT = {
    "p", "title", "article-title", "trans-title", "mixed-citation", "kwd", "td", "th", "attrib", "license-p",
    "funding-statement", "label", "source", "comment", "institution", "subject", "xref", "sup", "sub", "bold",
    "italic", "sc", "ext-link", "email", "chapter-title", "publisher-name", "publisher-loc", "collab",
    "surname", "given-names", "funding-source", "date-in-citation", "alt-text", "year", "season",
}


def _indent(el: etree._Element, level: int = 0) -> None:
    children = list(el)
    if el.tag in NO_INDENT or not children:
        return
    if (el.text and el.text.strip()) or any(c.tail and c.tail.strip() for c in children):
        return
    pad = "\n" + "  " * (level + 1)
    el.text = pad
    for i, child in enumerate(children):
        _indent(child, level + 1)
        child.tail = pad if i < len(children) - 1 else "\n" + "  " * level
