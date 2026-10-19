#!/usr/bin/env python3
"""Executa o pipeline DOCX de artigo -> XML SciELO PS 1.8 validado."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docx", default=ROOT / "docx", type=Path, help="Pasta (ou arquivo) com os DOCX.")
    parser.add_argument("--config", default=ROOT / "config/journals/biblios.json", type=Path)
    parser.add_argument("--metadata", type=Path, help="CSV opcional com metadados por artigo.")
    parser.add_argument("--work", default=ROOT / "work", type=Path, help="Raiz das saidas (sections, assets, xml, reports).")
    parser.add_argument("--render-shapes", action="store_true",
                        help="Renderiza figuras feitas com formas do Word (LibreOffice + PyMuPDF).")
    parser.add_argument("--soffice", default=None)
    parser.add_argument("--skip-validation", action="store_true")
    parser.add_argument("--reference", type=Path, help="Pasta de XMLs de referencia para comparacao.")
    parser.add_argument("--export", type=Path, help="Pasta para exportar os pacotes SPS.")
    parser.add_argument("--zip", action="store_true", help="Com --export, gera tambem um .zip por artigo.")
    return parser.parse_args()


def run_step(label: str, command: list[str], check: bool = True) -> int:
    print(f"\n== {label} ==")
    print(" ".join(str(part) for part in command))
    return subprocess.run(command, cwd=ROOT, check=check).returncode


def main() -> int:
    args = parse_args()
    py = sys.executable
    w = args.work
    sections, assets, xml, reports = w / "sections", w / "assets", w / "xml", w / "reports"
    for path in (sections, assets, xml, reports):
        path.mkdir(parents=True, exist_ok=True)

    cmd = [py, "scripts/01_docx_to_sections.py", "--input", str(args.docx), "--output", str(sections),
           "--assets", str(assets), "--config", str(args.config), "--log", str(reports / "docx_to_sections.jsonl")]
    if args.metadata:
        cmd += ["--metadata", str(args.metadata)]
    run_step("1/4 DOCX -> JSON de secoes + imagens", cmd, check=False)
    if args.render_shapes:
        cmd = [py, "scripts/01b_render_shapes.py", "--sections", str(sections), "--assets", str(assets),
               "--pdf-cache", str(w / "pdf"), "--log", str(reports / "render_shapes.jsonl")]
        if args.soffice:
            cmd += ["--soffice", args.soffice]
        run_step("1b Figuras de formas do Word -> PNG (LibreOffice + PyMuPDF)", cmd, check=False)
    run_step("2/4 JSON -> XML SciELO PS 1.8",
             [py, "scripts/02_build_sps_xml.py", "--sections", str(sections), "--config", str(args.config),
              "--output", str(xml), "--log", str(reports / "build_sps_xml.jsonl")], check=False)
    if not args.skip_validation:
        run_step("3/4 Validacao DTD JATS 1.1 + schematron SPS 1.8",
                 [py, "scripts/03_validate_sps.py", "--input", str(xml), "--report", str(reports / "validation.jsonl")],
                 check=False)
    if args.export:
        cmd = [py, "scripts/04_export_package.py", "--xml", str(xml), "--assets", str(assets),
               "--sections", str(sections), "--export-dir", str(args.export)]
        if args.zip:
            cmd.append("--zip")
        run_step("4/4 Pacotes SPS", cmd, check=False)
    if args.reference:
        run_step("Comparacao com XMLs de referencia",
                 [py, "scripts/compare_with_reference.py", "--generated", str(xml), "--reference", str(args.reference),
                  "--csv", str(reports / "compare_reference.csv")], check=False)
    print("\nPipeline concluido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
