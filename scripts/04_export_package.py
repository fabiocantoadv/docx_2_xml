#!/usr/bin/env python3
"""Monta um pacote SPS por artigo: XML + imagens referenciadas + DOCX original
+ manifesto com checksums (mesma ideia do 05_export_results das patentes)."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciartigo.utils import read_json, utc_now_iso

XLINK = "{http://www.w3.org/1999/xlink}href"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", required=True, type=Path, help="Pasta dos XMLs SPS.")
    parser.add_argument("--assets", required=True, type=Path, help="Pasta raiz dos assets.")
    parser.add_argument("--sections", required=True, type=Path, help="Pasta dos JSONs (para achar o DOCX).")
    parser.add_argument("--export-dir", required=True, type=Path)
    parser.add_argument("--zip", action="store_true", help="Tambem gera <base>.zip (formato de envio SciELO).")
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    args = parse_args()
    args.export_dir.mkdir(parents=True, exist_ok=True)
    for xml_path in sorted(args.xml.glob("*.xml")):
        base = xml_path.stem
        doc_dir = args.export_dir / base
        doc_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(xml_path, doc_dir / xml_path.name)
        tree = etree.parse(str(xml_path), etree.XMLParser(load_dtd=False, no_network=True))
        missing = []
        files = [xml_path.name]
        for g in tree.iter("graphic", "inline-graphic", "media", "supplementary-material"):
            href = g.get(XLINK)
            if not href:
                continue
            src = args.assets / base / href
            if src.exists():
                shutil.copy2(src, doc_dir / href)
                files.append(href)
            else:
                missing.append(href)
        sections_path = args.sections / f"{base}.json"
        source_docx = ""
        if sections_path.exists():
            source_docx = read_json(sections_path).get("source_docx", "")
            if source_docx and Path(source_docx).exists():
                shutil.copy2(source_docx, doc_dir / Path(source_docx).name)
        manifest = {
            "ts": utc_now_iso(), "base_name": base, "source_docx": source_docx,
            "files": {f: sha256(doc_dir / f) for f in files}, "missing_assets": missing,
        }
        (doc_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.zip:
            with zipfile.ZipFile(args.export_dir / f"{base}.zip", "w", zipfile.ZIP_DEFLATED) as zf:
                for f in files:
                    zf.write(doc_dir / f, f)
        status = "ok" if not missing else f"faltam {len(missing)} imagem(ns): {', '.join(missing)}"
        print(f"[{base}] {status}")
    print(f"Exportacao concluida em: {args.export_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
