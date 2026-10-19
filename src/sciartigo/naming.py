"""Regra de nomeacao SciELO PS: ISSN-acron-volume-numero-paginacao.

    1562-4730-biblios-88-e001.xml      (sem volume: o trecho e omitido)
    0034-8910-rsp-48-02-0213.xml       (fpage com 4 digitos)
    ...-gf1.jpg / -gt1.jpg             (figuras / tabelas como imagem)
"""

from __future__ import annotations

import re


def sps_base_name(journal: dict, meta: dict) -> str:
    issn = journal.get("issn_epub") or journal.get("issn_ppub") or "0000-0000"
    acron = journal.get("acron") or journal.get("journal_id") or "journal"
    parts = [issn, acron]
    vol = (meta.get("volume") or "").strip()
    issue = (meta.get("issue") or "").strip()
    if vol:
        parts.append(vol)
    if issue:
        parts.append(issue.zfill(2) if issue.isdigit() and vol else issue)
    eloc = (meta.get("elocation") or "").strip()
    fpage = (meta.get("fpage") or "").strip()
    if eloc:
        parts.append(eloc)
    elif fpage:
        parts.append(fpage.zfill(4) if fpage.isdigit() else fpage)
    else:
        parts.append(re.sub(r"\W+", "", (meta.get("doi") or "").split("/")[-1])[-12:] or "x")
    return "-".join(p for p in parts if p)
