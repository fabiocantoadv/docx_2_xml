#!/usr/bin/env python3
"""Renderiza figuras feitas com formas do Word (opcional: LibreOffice + PyMuPDF)
e atualiza o JSON de secoes com o nome da imagem gerada."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciartigo.render_shapes import docx_to_pdf, find_soffice, render_figure
from sciartigo.utils import append_jsonl, iter_input_files, read_json, utc_now_iso, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", required=True, type=Path)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--pdf-cache", default=Path("work/pdf"), type=Path)
    parser.add_argument("--soffice", default=None, help="Caminho do soffice (LibreOffice).")
    parser.add_argument("--dpi", default=300, type=int)
    parser.add_argument("--log", default=Path("reports/render_shapes.jsonl"), type=Path)
    return parser.parse_args()


def _figs(items):
    for it in items:
        if it["type"] == "fig":
            yield it
        for key in ("children",):
            yield from _figs(it.get(key, []))


def main() -> int:
    args = parse_args()
    soffice = find_soffice(args.soffice)
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        print("PyMuPDF ausente (pip install pymupdf): etapa ignorada.")
        return 0
    if not soffice:
        print("LibreOffice (soffice) nao encontrado: etapa ignorada. Use --soffice CAMINHO.")
        return 0
    rendered = 0
    for path in iter_input_files(args.sections, {".json"}):
        sections = read_json(path)
        pending = [f for f in _figs(sections.get("body", []) + sections.get("apps", [])) if f.get("needs_render")]
        if not pending:
            continue
        pdf = docx_to_pdf(Path(sections["source_docx"]), args.pdf_cache, soffice)
        base = sections["base_name"]
        for fig in pending:
            n = fig["id"].lstrip("f")
            name = f"{base}-gf{n}.png"
            note = fig["notes"][0]["text"] if fig.get("notes") else ""
            result = render_figure(pdf, fig.get("label", ""), (fig.get("title") or {}).get("text", ""), note,
                                   args.assets / base / name, args.dpi)
            log = {"ts": utc_now_iso(), "stage": "render_shapes", "source": str(path), "fig": fig["id"], **result}
            append_jsonl(args.log, log)
            if result["status"] == "ok":
                fig["graphic"] = name
                fig["needs_render"] = False
                fig["rendered_from_pdf"] = {"page": result["page"], "bbox": result["bbox"]}
                sections["warnings"] = [w for w in sections["warnings"] if not w.startswith(f"figura {fig['id']} ")]
                sections["warnings"].append(f"figura {fig['id']} renderizada do PDF (pagina {result['page']}): conferir recorte")
                rendered += 1
            print(f"[{result['status']}] {base} {fig['id']} {fig.get('label', '')}")
        write_json(path, sections)
    print(f"rendered={rendered} log={args.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
