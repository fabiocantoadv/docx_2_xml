"""Ponta a ponta nas amostras da Biblios: XML valido (DTD + SPS 1.8) e campos-chave."""

from pathlib import Path

import pytest
from lxml import etree

from sciartigo.docx_sections import extract_sections
from sciartigo.sps import Builder, write_article
from sciartigo.utils import read_json
from sciartigo.validation import validate_xml

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = sorted((ROOT / "samples/biblios-88/docx").glob("*.docx"))
CONFIG = read_json(ROOT / "config/journals/biblios.json")


@pytest.mark.parametrize("docx", SAMPLES, ids=lambda p: p.stem)
def test_sample_generates_valid_sps(docx, tmp_path):
    sections = extract_sections(docx, CONFIG, tmp_path / "assets")
    builder = Builder(sections, CONFIG, sections["meta"], sections["base_name"])
    out = tmp_path / f"{sections['base_name']}.xml"
    write_article(builder.build(), out)
    result = validate_xml(out)
    assert result["valid"], result["dtd_errors"] + result["style_errors"]
    root = etree.parse(str(out)).getroot()
    ref = etree.parse(str(ROOT / "samples/biblios-88/reference_xml" / out.name)).getroot()
    # mesmos DOI, elocation, numero de referencias e de figuras do gabarito
    for xp in (".//article-id[@pub-id-type='doi']", ".//article-meta/elocation-id"):
        assert root.findtext(xp) == ref.findtext(xp)
    assert len(root.findall(".//ref-list/ref")) == len(ref.findall(".//ref-list/ref"))
    assert len(root.findall(".//fig")) == len(ref.findall(".//fig"))
    # toda referencia citada no gabarito tambem e ligada pelo pipeline
    cited_ref = {x.get("rid") for x in ref.iter("xref") if x.get("ref-type") == "bibr"}
    cited_gen = {x.get("rid") for x in root.iter("xref") if x.get("ref-type") == "bibr"}
    assert cited_ref <= cited_gen
