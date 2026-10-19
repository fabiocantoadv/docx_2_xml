#!/usr/bin/env python3
"""Valida XMLs contra a DTD JATS 1.1 e o schematron SciELO PS 1.8; gera JSONL."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciartigo.utils import XML_SUFFIXES, append_jsonl, iter_input_files, utc_now_iso
from sciartigo.validation import DTD_PATH, SCH_PATH, validate_xml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Arquivo ou pasta XML.")
    parser.add_argument("--report", required=True, type=Path, help="Relatorio JSONL.")
    parser.add_argument("--dtd", default=DTD_PATH, type=Path)
    parser.add_argument("--schematron", default=SCH_PATH, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.report.exists():
        args.report.unlink()
    valid = invalid = 0
    for xml_path in iter_input_files(args.input, XML_SUFFIXES):
        result = validate_xml(xml_path, args.dtd, args.schematron)
        result.update({"ts": utc_now_iso(), "stage": "validate_sps"})
        append_jsonl(args.report, result)
        if result["valid"]:
            valid += 1
            print(f"[valido] {xml_path.name}")
        else:
            invalid += 1
            print(f"[INVALIDO] {xml_path.name}")
            for err in (result["dtd_errors"] + result["style_errors"])[:15]:
                print(f"    {err}")
    print(f"valid={valid} invalid={invalid} report={args.report}")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
