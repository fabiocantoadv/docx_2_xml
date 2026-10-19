#!/usr/bin/env python3
"""Compara XMLs gerados com XMLs de referencia (marcados manualmente / SciELO).

Mesmo papel do compare_batches.py das patentes: mede, campo a campo, quanto
o pipeline reproduz o gabarito. Casa os arquivos pelo nome SPS ou pelo DOI.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import re
import sys
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciartigo.utils import fold  # noqa: E402
from sciartigo.validation import validate_xml  # noqa: E402

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
XLINK = "{http://www.w3.org/1999/xlink}href"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--csv", type=Path, help="Grava as metricas por campo em CSV.")
    parser.add_argument("--details", action="store_true", help="Mostra divergencias item a item.")
    return parser.parse_args()


def load(path: Path) -> etree._Element:
    return etree.parse(str(path), etree.XMLParser(load_dtd=False, no_network=True, remove_blank_text=True)).getroot()


def txt(el) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def norm(s: str) -> str:
    s = fold(s)
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def ratio(a: str, b: str) -> float:
    a, b = norm(a).split(), norm(b).split()
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def doi(root) -> str:
    return txt(root.find(".//article-meta/article-id[@pub-id-type='doi']")).lower()


def set_score(gen: set, ref: set) -> tuple[float, float]:
    if not gen and not ref:
        return 1.0, 1.0
    inter = len(gen & ref)
    return (inter / len(gen) if gen else 0.0, inter / len(ref) if ref else 0.0)


def compare(gen_path: Path, ref_path: Path, details: bool) -> list[dict]:
    g, r = load(gen_path), load(ref_path)
    rows: list[dict] = []

    def add(field: str, score: float, note: str = ""):
        rows.append({"article": gen_path.stem, "field": field, "score": round(score, 3), "note": note})

    am_g, am_r = g.find(".//article-meta"), r.find(".//article-meta")
    for name, xp in (("doi", "article-id[@pub-id-type='doi']"), ("elocation-id", "elocation-id"), ("issue", "issue"),
                     ("volume", "volume"), ("subject", ".//subject")):
        a, b = txt(am_g.find(xp)), txt(am_r.find(xp))
        add(name, 1.0 if a == b else 0.0, "" if a == b else f"gerado={a!r} ref={b!r}")
    add("article-title", ratio(txt(am_g.find("title-group/article-title")), txt(am_r.find("title-group/article-title"))))
    tg = {t.get(XML_LANG): txt(t.find("trans-title")) for t in am_g.findall("title-group/trans-title-group")}
    tr = {t.get(XML_LANG): txt(t.find("trans-title")) for t in am_r.findall("title-group/trans-title-group")}
    add("trans-title", sum(ratio(tg.get(k, ""), v) for k, v in tr.items()) / max(len(tr), 1), f"langs gerado={sorted(tg)} ref={sorted(tr)}")

    def people(am):
        return [(fold(txt(c.find("name/surname"))), fold(txt(c.find("name/given-names"))), txt(c.find("contrib-id")))
                for c in am.findall(".//contrib-group/contrib")]
    pg, pr = people(am_g), people(am_r)
    same = sum(1 for a, b in zip(pg, pr) if a[:2] == b[:2])
    add("contrib names", same / max(len(pr), 1), "" if same == len(pr) else f"gerado={pg} ref={pr}")
    add("contrib orcid", sum(1 for a, b in zip(pg, pr) if a[2] == b[2]) / max(len(pr), 1))

    def affs(am):
        return [(fold(txt(a.find("institution[@content-type='orgname']"))), fold(txt(a.find(".//city"))),
                 (a.find("country").get("country") if a.find("country") is not None else ""))
                for a in am.findall(".//aff")]
    ag, ar = affs(am_g), affs(am_r)
    add("aff (orgname, cidade, pais)", sum(1 for a, b in zip(ag, ar) if a == b) / max(len(ar), 1), f"gerado={ag} ref={ar}" if ag != ar else "")

    def hist(am):
        out = {}
        for d in am.findall("history/date"):
            out[d.get("date-type")] = "-".join(txt(d.find(x)).zfill(2) for x in ("year", "month", "day"))
        return out
    hg, hr = hist(am_g), hist(am_r)
    keys = [k for k in hr if k in ("received", "accepted")]
    add("history", sum(1 for k in keys if hg.get(k) == hr[k]) / max(len(keys), 1), f"gerado={hg} ref={hr}" if any(hg.get(k) != hr[k] for k in keys) else "")
    lg = am_g.find("permissions/license")
    lr = am_r.find("permissions/license")
    a = (lg.get(XLINK) if lg is not None else "").replace("http://", "https://")
    b = (lr.get(XLINK) if lr is not None else "").replace("http://", "https://")
    add("license", 1.0 if a == b else 0.0, "" if a == b else f"gerado={a} ref={b}")

    def abstracts(am):
        out = {}
        for ab in am.findall("abstract") + am.findall("trans-abstract"):
            lang = ab.get(XML_LANG) or "main"
            out[lang] = (len(ab.findall("sec")), " ".join(txt(p) for p in ab.findall(".//p")))
        return out
    abg, abr = abstracts(am_g), abstracts(am_r)
    add("abstracts (texto)", sum(ratio(abg.get(k, (0, ""))[1], v[1]) for k, v in abr.items()) / max(len(abr), 1))
    add("abstracts (secoes)", sum(1 for k, v in abr.items() if abg.get(k, (0,))[0] == v[0]) / max(len(abr), 1))

    def kwds(am):
        return {k.get(XML_LANG): {norm(txt(x)) for x in k.findall("kwd")} for k in am.findall("kwd-group")}
    kg, kr = kwds(am_g), kwds(am_r)
    scores = [set_score(kg.get(k, set()), v)[1] for k, v in kr.items()]
    add("kwd (recall)", sum(scores) / max(len(scores), 1))

    bg, br = g.find("body"), r.find("body")
    add("body texto", ratio(txt(bg), txt(br)))
    tg_ = [norm(txt(s.find("title"))) for s in bg.findall("sec")]
    tr_ = [norm(txt(s.find("title"))) for s in br.findall("sec")]
    add("body secoes nivel 1", set_score(set(tg_), set(tr_))[1], f"gerado={len(tg_)} ref={len(tr_)}")
    fg, fr = [txt(f.find("label")) for f in g.iter("fig")], [txt(f.find("label")) for f in r.iter("fig")]
    add("figuras", 1.0 if fg == fr else len(set(fg) & set(fr)) / max(len(fr), 1), f"gerado={fg} ref={fr}" if fg != fr else "")
    add("tabelas", 1.0 if len(list(g.iter("table-wrap"))) == len(list(r.iter("table-wrap"))) else 0.0,
        f"gerado={len(list(g.iter('table-wrap')))} ref={len(list(r.iter('table-wrap')))}")
    add("listas", 1.0 if len(list(g.iter("list"))) == len(list(r.iter("list"))) else 0.0,
        f"gerado={len(list(g.iter('list')))} ref={len(list(r.iter('list')))}")

    refs_g, refs_r = g.findall(".//ref-list/ref"), r.findall(".//ref-list/ref")
    add("ref-count", 1.0 if len(refs_g) == len(refs_r) else 0.0, f"gerado={len(refs_g)} ref={len(refs_r)}")
    pairs = list(zip(refs_g, refs_r))
    add("mixed-citation (texto)", sum(ratio(txt(a.find("mixed-citation")), txt(b.find("mixed-citation"))) for a, b in pairs) / max(len(pairs), 1))
    for field, xp in (("publication-type", None), ("source", "element-citation/source"), ("year", "element-citation/year"),
                      ("volume", "element-citation/volume"), ("issue", "element-citation/issue"), ("fpage", "element-citation/fpage"),
                      ("doi", "element-citation/pub-id[@pub-id-type='doi']"), ("article-title", "element-citation/article-title"),
                      ("autores (n)", None)):
        ok = 0
        diffs = []
        for a, b in pairs:
            if field == "publication-type":
                va, vb = a.find("element-citation").get("publication-type"), b.find("element-citation").get("publication-type")
            elif field == "autores (n)":
                va = len(a.findall("element-citation/person-group[@person-group-type='author']/*"))
                vb = len(b.findall("element-citation/person-group[@person-group-type='author']/*"))
            else:
                va, vb = norm(txt(a.find(xp))), norm(txt(b.find(xp)))
            if va == vb:
                ok += 1
            else:
                diffs.append(f"{b.get('id')}: gerado={va!r} ref={vb!r}")
        add(f"element-citation {field}", ok / max(len(pairs), 1), "; ".join(diffs[:6]) if details else f"{len(diffs)} divergencia(s)")
    cg = {x.get("rid") for x in g.iter("xref") if x.get("ref-type") == "bibr"}
    cr = {x.get("rid") for x in r.iter("xref") if x.get("ref-type") == "bibr"}
    prec, rec = set_score(cg, cr)
    add("xref bibr (refs citadas) precisao", prec, f"so no gerado={sorted(cg - cr, key=lambda v: int(v[1:]))}")
    add("xref bibr (refs citadas) cobertura", rec, f"so na ref={sorted(cr - cg, key=lambda v: int(v[1:]))}")
    ng = len([x for x in g.iter("xref") if x.get("ref-type") == "bibr"])
    nr = len([x for x in r.iter("xref") if x.get("ref-type") == "bibr"])
    add("xref bibr (chamadas)", min(ng, nr) / max(ng, nr, 1), f"gerado={ng} ref={nr}")
    fng, fnr = len(g.findall(".//back/fn-group/fn")), len(r.findall(".//back/fn-group/fn"))
    add("notas de rodape", 1.0 if fng >= fnr else fng / max(fnr, 1), f"gerado={fng} ref={fnr}")
    vg, vr = validate_xml(gen_path), validate_xml(ref_path)
    add("valido DTD+SPS 1.8 (gerado)", 1.0 if vg["valid"] else 0.0, "; ".join((vg["dtd_errors"] + vg["style_errors"])[:3]))
    add("valido DTD+SPS 1.8 (referencia)", 1.0 if vr["valid"] else 0.0, "; ".join((vr["dtd_errors"] + vr["style_errors"])[:3]))
    return rows


def main() -> int:
    args = parse_args()
    refs = {p.stem: p for p in args.reference.glob("*.xml")}
    refs_by_doi = {doi(load(p)): p for p in refs.values()}
    all_rows = []
    for gen in sorted(args.generated.glob("*.xml")):
        ref = refs.get(gen.stem) or refs_by_doi.get(doi(load(gen)))
        if ref is None:
            print(f"[sem referencia] {gen.name}")
            continue
        rows = compare(gen, ref, args.details)
        all_rows.extend(rows)
        print(f"\n== {gen.name}  x  {ref.name}")
        for row in rows:
            flag = "  " if row["score"] >= 0.95 else "!!" if row["score"] < 0.7 else " ~"
            print(f"{flag} {row['field']:<40} {row['score']:>6.3f}  {row['note'][:220]}")
    if args.csv and all_rows:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["article", "field", "score", "note"])
            w.writeheader()
            w.writerows(all_rows)
        print(f"\ncsv={args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
