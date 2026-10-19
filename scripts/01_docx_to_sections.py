#!/usr/bin/env python3
"""DOCX do artigo -> JSON intermediario de secoes + imagens (assets)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciartigo.docx_sections import extract_sections
from sciartigo.metadata import load_metadata, metadata_for
from sciartigo.utils import DOCX_SUFFIXES, append_jsonl, iter_input_files, read_json, utc_now_iso, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Arquivo ou pasta de DOCX.")
    parser.add_argument("--output", required=True, type=Path, help="Pasta dos JSONs de secoes.")
    parser.add_argument("--assets", required=True, type=Path, help="Pasta raiz das imagens extraidas.")
    parser.add_argument("--config", required=True, type=Path, help="JSON do periodico (config/journals/*.json).")
    parser.add_argument("--metadata", type=Path, help="CSV opcional com metadados por artigo.")
    parser.add_argument("--log", default=Path("reports/docx_to_sections.jsonl"), type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = read_json(args.config)
    table = load_metadata(args.metadata)
    ok = failures = 0
    for docx in iter_input_files(args.input, DOCX_SUFFIXES):
        log = {"ts": utc_now_iso(), "stage": "docx_to_sections", "source": str(docx)}
        try:
            sections = extract_sections(docx, config, args.assets, metadata_for(docx, table))
            out = args.output / f"{sections['base_name']}.json"
            write_json(out, sections)
            log.update({
                "status": "ok", "output": str(out), "base_name": sections["base_name"],
                "confidence": sections["confidence"], "warnings": sections["warnings"],
                "refs": len(sections["refs"]), "figs": sum(1 for m in sections["media"]),
            })
            ok += 1
        except Exception as exc:  # um DOCX ruim nao derruba o lote
            failures += 1
            log.update({"status": "error", "error": repr(exc)})
        append_jsonl(args.log, log)
        print(f"[{log['status']}] {docx.name} -> {log.get('base_name', '')} {len(log.get('warnings', []))} aviso(s)")
    print(f"ok={ok} failures={failures} log={args.log}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
