#!/usr/bin/env python3
"""JSON de secoes -> XML SciELO PS 1.8."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciartigo.sps import Builder, write_article
from sciartigo.utils import append_jsonl, iter_input_files, read_json, utc_now_iso


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", required=True, type=Path, help="Pasta dos JSONs do script 01.")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Pasta dos XMLs SPS.")
    parser.add_argument("--log", default=Path("reports/build_sps_xml.jsonl"), type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = read_json(args.config)
    ok = failures = 0
    for path in iter_input_files(args.sections, {".json"}):
        log = {"ts": utc_now_iso(), "stage": "build_sps_xml", "source": str(path)}
        try:
            sections = read_json(path)
            builder = Builder(sections, config, sections.get("meta", {}), sections["base_name"])
            tree = builder.build()
            out = args.output / f"{sections['base_name']}.xml"
            write_article(tree, out)
            log.update({"status": "ok", "output": str(out), "xref_bibr": builder.xref_count,
                        "refs_cited": len(builder.cited_refs), "refs": len(sections.get("refs", [])),
                        "warnings": builder.warnings})
            ok += 1
        except Exception as exc:
            failures += 1
            log.update({"status": "error", "error": repr(exc)})
        append_jsonl(args.log, log)
        print(f"[{log['status']}] {path.stem}: xref={log.get('xref_bibr', 0)} "
              f"refs citadas={log.get('refs_cited', 0)}/{log.get('refs', 0)} {log.get('error', '')}")
    print(f"generated={ok} failures={failures} log={args.log}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
