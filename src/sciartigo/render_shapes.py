"""Figuras desenhadas com formas do Word (sem imagem raster).

O DOCX so tem a descricao vetorial (wpg/wps). O caminho e o mesmo do
pipeline de patentes, ao contrario: LibreOffice converte o DOCX em PDF e o
PyMuPDF recorta a regiao entre a legenda e a fonte/nota, usando a uniao dos
desenhos vetoriais da pagina, e renderiza em PNG.

Dependencias opcionais: LibreOffice (soffice) e PyMuPDF (`pip install pymupdf`).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SOFFICE_CANDIDATES = (
    "soffice", "libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
)


def find_soffice(explicit: str | None = None) -> str | None:
    for cand in ([explicit] if explicit else []) + list(SOFFICE_CANDIDATES):
        if cand and (shutil.which(cand) or Path(cand).exists()):
            return shutil.which(cand) or cand
    return None


def docx_to_pdf(docx: Path, pdf_dir: Path, soffice: str) -> Path:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdf_dir / (docx.stem + ".pdf")
    if pdf.exists() and pdf.stat().st_mtime >= docx.stat().st_mtime:
        return pdf
    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(pdf_dir), str(docx)],
                   check=True, capture_output=True, timeout=300)
    return pdf


def _first_words(text: str, n: int) -> str:
    return " ".join((text or "").split()[:n])


def render_figure(pdf_path: Path, label: str, title: str, note: str, out_png: Path, dpi: int = 300) -> dict:
    import pymupdf  # import tardio: dependencia opcional

    doc = pymupdf.open(str(pdf_path))
    needles = [f"{label} – {_first_words(title, 2)}", f"{label} - {_first_words(title, 2)}", f"{label}: {_first_words(title, 2)}",
               _first_words(title, 5), label]
    for page_no, page in enumerate(doc):
        caps = []
        for needle in needles:
            if needle.strip():
                caps = page.search_for(needle)
                if caps:
                    break
        for cap in caps:
            for pno in (page_no, page_no + 1):
                if pno >= doc.page_count:
                    continue
                pg = doc[pno]
                top = cap.y1 if pno == page_no else 0
                bottom = pg.rect.y1
                if note:
                    notes = [r for r in pg.search_for(_first_words(note, 3)) if r.y0 > top]
                    if notes:
                        bottom = notes[0].y0
                rects = [d["rect"] for d in pg.get_drawings()
                         if d["rect"].y0 >= top - 2 and d["rect"].y1 <= bottom + 2 and d["rect"].width > 2]
                if len(rects) < 2:
                    continue
                union = pymupdf.Rect(rects[0])
                for r in rects[1:]:
                    union |= r
                if union.height < 40 or union.width < 80:
                    continue
                out_png.parent.mkdir(parents=True, exist_ok=True)
                pix = pg.get_pixmap(clip=union + (-4, -4, 4, 4), dpi=dpi)
                pix.save(str(out_png))
                return {"status": "ok", "page": pno + 1, "bbox": [round(v, 1) for v in union], "png": str(out_png)}
    return {"status": "not_found"}
