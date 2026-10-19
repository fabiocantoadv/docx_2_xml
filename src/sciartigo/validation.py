"""Validacao: DTD JATS 1.1 (local) + Schematron SciELO PS 1.8 (do packtools).

Os dois arquivos ficam em schemas/ (copiados do packtools, licenca BSD em
schemas/LICENSE.packtools), entao a validacao roda offline e sem instalar o
packtools, cujo build falha em alguns Pythons recentes.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from lxml import etree, isoschematron

ROOT = Path(__file__).resolve().parents[2]
DTD_PATH = ROOT / "schemas/jats-publishing-dtd-1.1/JATS-journalpublishing1.dtd"
SCH_PATH = ROOT / "schemas/scielo-style-1.8.sch"
SVRL = "{http://purl.oclc.org/dsdl/svrl}"


@lru_cache(maxsize=4)
def _dtd(path: str) -> etree.DTD:
    return etree.DTD(path)


@lru_cache(maxsize=4)
def _schematron(path: str) -> isoschematron.Schematron:
    return isoschematron.Schematron(etree.parse(path), store_report=True)


def validate_tree(tree: etree._ElementTree, dtd_path: Path = DTD_PATH, sch_path: Path | None = SCH_PATH) -> dict:
    dtd = _dtd(str(dtd_path))
    dtd_ok = dtd.validate(tree)
    dtd_errors = [f"linha {e.line}: {e.message}" for e in dtd.error_log] if not dtd_ok else []
    sch_errors: list[str] = []
    if sch_path is not None and Path(sch_path).exists():
        sch = _schematron(str(sch_path))
        if not sch.validate(tree):
            for fa in sch.validation_report.iter(f"{SVRL}failed-assert"):
                text = " ".join("".join(fa.itertext()).split())
                sch_errors.append(f"{fa.get('location')}: {text}")
    return {"valid": dtd_ok and not sch_errors, "dtd_valid": dtd_ok, "dtd_errors": dtd_errors, "style_errors": sch_errors}


def validate_xml(xml_path: Path, dtd_path: Path = DTD_PATH, sch_path: Path | None = SCH_PATH) -> dict:
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)
    try:
        tree = etree.parse(str(xml_path), parser)
    except etree.XMLSyntaxError as exc:
        return {"xml_path": str(xml_path), "valid": False, "dtd_valid": False, "dtd_errors": [str(exc)], "style_errors": []}
    result = validate_tree(tree, dtd_path, sch_path)
    result["xml_path"] = str(xml_path)
    return result
