from sciartigo.affiliations import parse_aff
from sciartigo.citations import link_citations
from sciartigo.names import split_name

IDX = {"metcalfe|2020": ["B12"], "bouter|2018": ["B8"], "bouter|2020": ["B9"], "shaw|2018": ["B48"],
       "dejo vasquez|2021": ["B15"], "vasquez|2021": ["B15"]}


def test_narrative_citation_with_etal():
    out, n = link_citations("De acordo com Metcalfe <italic>et al.</italic> (2020), a integridade", IDX)
    assert n == 1
    assert '<xref ref-type="bibr" rid="B12">Metcalfe <italic>et al.</italic> (2020)</xref>' in out


def test_parenthetical_multiple():
    out, n = link_citations("(Bouter, 2018, 2020; Shaw e Satalkar, 2018).", IDX)
    assert n == 3
    assert 'rid="B9">2020</xref>' in out


def test_longest_surname_key():
    out, _ = link_citations("como relatam Dejo-Vásquez, Lescano e Pérez-Carreño (2021), ao citar", IDX)
    assert '<xref ref-type="bibr" rid="B15">Dejo-Vásquez' in out


def test_links_are_not_touched():
    frag = '<ext-link ext-link-type="uri" xlink:href="x">Bouter, 2020</ext-link>'
    assert link_citations(frag, IDX) == (frag, 0)


def test_split_name_with_hint():
    r = split_name("Raimundo Nonato Macedo dos Santos", ["R. N. Macedo dos Santos"])
    assert (r["given"], r["surname"], r["name_split"]) == ("Raimundo Nonato", "Macedo dos Santos", "hint")
    r = split_name("Karen Santos d’Amorim", ["K. Santos-d’Amorim"])
    assert r["surname"] == "Santos d’Amorim"


def test_split_name_heuristic():
    r = split_name("Ana Maria da Silva", [])
    assert (r["given"], r["surname"]) == ("Ana Maria", "da Silva")


def test_parse_aff():
    a = parse_aff("Universidade de São Paulo – USP, Ribeirão Preto, Brasil")
    assert (a["orgname"], a["acronym"], a["city"], a["country_code"]) == ("Universidade de São Paulo", "USP", "Ribeirão Preto", "BR")
    a = parse_aff("Universidade Federal de Pernambuco, Departamento de Ciência da Informação, Recife, PE, Brasil")
    assert (a["orgdiv1"], a["state"], a["city"]) == ("Departamento de Ciência da Informação", "PE", "Recife")
