from sciartigo.references import citation_keys, parse_reference


def tok(*parts):
    """parts: (texto, negrito)"""
    return [{"text": t, "bold": b, "italic": False} for t, b in parts]


def test_journal_article_with_doi():
    text = ("BOUTER, L. What Research Institutions can do to foster Research Integrity. Sci Eng Ethics, England, "
            "v. 26, p. 2363-2369, 2020. https://doi.org/10.1007/s11948-020-00178-5")
    p = parse_reference(text, tok(("BOUTER, L. What Research Institutions can do to foster Research Integrity. ", False),
                                  ("Sci Eng Ethics", True), (", England, v. 26, p. 2363-2369, 2020. https://doi.org/10.1007/s11948-020-00178-5", False)))
    assert p["publication_type"] == "journal"
    assert p["authors"] == [{"surname": "BOUTER", "given": "L."}]
    assert p["article_title"].startswith("What Research Institutions")
    assert p["source"] == "Sci Eng Ethics"
    assert (p["volume"], p["fpage"], p["lpage"], p["year"]) == ("26", "2363", "2369", "2020")
    assert p["doi"] == "10.1007/s11948-020-00178-5"
    assert p["publisher_loc"] == "England"


def test_initial_not_confused_with_title_word():
    text = "QADHI, S. A model of the interrelationship. Int J Qual Stud, v. 19, 2024."
    p = parse_reference(text, tok(("QADHI, S. A model of the interrelationship. ", False), ("Int J Qual Stud", True), (", v. 19, 2024.", False)))
    assert p["authors"] == [{"surname": "QADHI", "given": "S."}]
    assert p["article_title"] == "A model of the interrelationship"


def test_collab_and_access_date():
    text = ("ACADEMIA BRASILEIRA DE CIÊNCIAS. Rigor e integridade. Boletim UFMG, Belo Horizonte, MG, ano 40, n. 1848, 2013. "
            "Disponível em: https://www.ufmg.br/boletim/x.shtml. Acesso em: 22. jul. 2024.")
    p = parse_reference(text, tok(("ACADEMIA BRASILEIRA DE CIÊNCIAS. Rigor e integridade. ", False), ("Boletim UFMG", True),
                                  (", Belo Horizonte, MG, ano 40, n. 1848, 2013. Disponível em: https://www.ufmg.br/boletim/x.shtml. Acesso em: 22. jul. 2024.", False)))
    assert p["collab"] == "ACADEMIA BRASILEIRA DE CIÊNCIAS"
    assert p["authors"] == []
    assert p["access_date_iso"] == "2024-07-22"
    assert p["uri"] == "https://www.ufmg.br/boletim/x.shtml"
    assert p["publisher_loc"] == "Belo Horizonte, MG"


def test_book_chapter_with_editor():
    text = ("ANDERSON, M. S.; SHAW, M. A. Research Integrity. In: PAULSEN, M. (ed.). Higher Education: Handbook of Theory. "
            "Dordrecht: Springer, 2013.")
    p = parse_reference(text, tok(("ANDERSON, M. S.; SHAW, M. A. Research Integrity. In: PAULSEN, M. (ed.). ", False),
                                  ("Higher Education", True), (": Handbook of Theory. Dordrecht: Springer, 2013.", False)))
    assert p["publication_type"] == "book"
    assert p["chapter_title"] == "Research Integrity"
    assert p["editors"] == [{"surname": "PAULSEN", "given": "M."}]
    assert p["source"] == "Higher Education: Handbook of Theory"
    assert (p["publisher_loc"], p["publisher_name"]) == ("Dordrecht", "Springer")


def test_legal_doc():
    text = "BRASIL. Lei nº 9.610, de 19 de fevereiro de 1998. Altera a legislação. Diário Oficial da União: seção 1, Brasília, DF, ano 136, n. 36, p. 3-9, 20 fev. 1998."
    p = parse_reference(text, tok(("BRASIL. Lei nº 9.610, de 19 de fevereiro de 1998. Altera a legislação. ", False),
                                  ("Diário Oficial da União", True), (": seção 1, Brasília, DF, ano 136, n. 36, p. 3-9, 20 fev. 1998.", False)))
    assert p["publication_type"] == "legal-doc"
    assert p["series"] == "Diário Oficial da União"
    assert p["year"] == "1998"


def test_citation_keys():
    p = parse_reference("SANTOS-D´AMORIM, K. Titulo. Fonte, v. 1, 2024a.", tok(("SANTOS-D´AMORIM, K. Titulo. ", False), ("Fonte", True), (", v. 1, 2024a.", False)))
    keys = citation_keys(p)
    assert "santos d'amorim|2024a" in keys
