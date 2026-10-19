"""Bloco 'Dados de publicação' (template Biblios e similares).

Le, apos o titulo do bloco: pessoas (nome, titulacao, afiliacao, e-mail,
ORCID) e campos rotulados (Financiamento, Conflito de interesses, Histórico,
Contribuição de autoria, ...). Rotulos desconhecidos ficam em `other`.
"""

from __future__ import annotations

import re

from .affiliations import looks_like_aff
from .utils import clean_text, fold, iso_date, parse_date, prefix_len_matching, strip_prefix_xml

LABELS = {
    "originalidade": "originality", "originalidad": "originality", "originality": "originality",
    "preprints": "preprint", "preprint": "preprint",
    "informacoes sobre a obra": "work_info", "informacion sobre la obra": "work_info", "about the work": "work_info",
    "agradecimentos": "ack", "agradecimientos": "ack", "acknowledgments": "ack", "acknowledgements": "ack",
    "contribuicao de autoria": "contributions", "contribuicao dos autores": "contributions",
    "contribucion de autoria": "contributions", "contribucion de los autores": "contributions",
    "author contributions": "contributions", "authorship contribution": "contributions",
    "uso de inteligencia artificial": "ai_use", "uso de ia": "ai_use", "use of artificial intelligence": "ai_use",
    "financiamento": "funding", "financiamiento": "funding", "financiacion": "funding", "funding": "funding",
    "consentimento de uso de imagem": "image_consent", "consentimiento de uso de imagen": "image_consent",
    "aprovacao de comite de etica em pesquisa": "ethics", "aprobacion de comite de etica": "ethics",
    "aprobacion del comite de etica": "ethics", "ethics approval": "ethics",
    "conflito de interesses": "conflict", "conflito de interesse": "conflict", "conflicto de intereses": "conflict",
    "conflict of interest": "conflict", "conflicts of interest": "conflict",
    "disponibilidade de dados e conjunto dos dados": "data_availability", "disponibilidade de dados": "data_availability",
    "disponibilidad de datos": "data_availability", "data availability": "data_availability",
    "licenca de uso": "license", "licencia de uso": "license", "license": "license",
    "publisher": "publisher", "editora": "publisher",
    "editores": "editors", "editor": "editors", "editoras": "editors", "editors": "editors",
    "historico": "history", "historial": "history", "history": "history",
}

NOT_APPLICABLE = ("nao se aplica", "no aplica", "no se aplica", "not applicable", "n/a", "nao ha", "não há")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_ORCID = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])")


def label_key(text: str) -> str | None:
    key = fold(text).rstrip(":. ")
    if key in LABELS:
        return LABELS[key]
    for label, value in LABELS.items():
        if key.startswith(label + ":"):
            return value
    return None


def is_not_applicable(text: str) -> bool:
    t = fold(text).rstrip(". ")
    return any(t == na or t.startswith(na + ".") for na in NOT_APPLICABLE)


def parse_history(text: str) -> dict[str, dict]:
    out = {}
    keys = {
        "received": r"(?:recebido|recibido|received|submetido|submitted)",
        "rev-recd": r"(?:revisado|revised)",
        "accepted": r"(?:aprovado|aceito|aceptado|aprobado|accepted)",
        "pub": r"(?:publicado|published)",
    }
    for key, pat in keys.items():
        m = re.search(pat + r"\s*(?:em|en|on)?\s*:?\s*([0-9][0-9./ -]+[0-9])", text, re.I)
        if m:
            parsed = parse_date(m.group(1))
            if parsed:
                out[key] = parsed
    return out


def parse_pubdata(blocks: list[dict], person_styles: set[str], label_styles: set[str]) -> dict:
    """`blocks`: [{'style','text','xml'}] a partir do titulo 'Dados de publicação' (exclusive)."""
    people: list[dict] = []
    fields: dict[str, list[dict]] = {}
    labels: dict[str, str] = {}
    current_person: dict | None = None
    current_field: str | None = None
    for b in blocks:
        text, style = b["text"], b["style"].lower()
        if not text:
            continue
        key = label_key(text)
        if key is not None:
            # "Financiamento: CAPES" (rotulo e valor na mesma linha)
            m = re.match(r"^[^:]+:\s*(.+)$", text)
            current_field = key
            current_person = None
            fields.setdefault(key, [])
            labels.setdefault(key, clean_text(text.split(":", 1)[0]))
            if m:
                cut = prefix_len_matching(b["xml"], r"^[^:]+:\s*")
                fields[key].append({"text": m.group(1), "xml": strip_prefix_xml(b["xml"], cut)})
            continue
        # papeis da contribuicao de autoria podem vir no estilo de rotulo
        # ("Coleta de dados: ..." em Heading 4): ficam no campo corrente
        if style in person_styles:
            current_field = None
            current_person = {"name": text, "bio": [], "affs": [], "email": "", "orcid": ""}
            people.append(current_person)
            continue
        if current_field:
            fields[current_field].append({"text": text, "xml": b["xml"]})
            continue
        if current_person is not None:
            email = _EMAIL.search(text)
            orcid = _ORCID.search(text) if "orcid" in text.lower() or _ORCID.fullmatch(text.strip()) else None
            if orcid:
                current_person["orcid"] = orcid.group(1)
            elif email and len(text) < 120:
                current_person["email"] = email.group(0)
            elif looks_like_aff(text) and len(text) < 250 and not re.match(r"(?i)^(doutor|doutora|mestre|mestranda|mestrando|doutorando|doutoranda|professor|professora|docente|graduad|bachar|licenciad|phd|dr\.|dra\.)", text):
                current_person["affs"].append(text)
            else:
                current_person["bio"].append(text)
    out: dict = {"people": people}
    for key, items in fields.items():
        texts = [i["text"] for i in items]
        if key == "contributions":
            roles = []
            for t in texts:
                if ":" in t:
                    role, names = t.split(":", 1)
                    roles.append({"role": clean_text(role), "names": [clean_text(n) for n in re.split(r";", names) if clean_text(n)]})
                else:
                    roles.append({"role": "", "names": [clean_text(t)]})
            out["contributions"] = roles
        elif key == "history":
            out["history"] = {k: iso_date(v) for k, v in parse_history(" ".join(texts)).items()}
            out["history_text"] = " ".join(texts)
        else:
            out[key] = {"label": labels.get(key, key), "text": " ".join(texts), "xml": " ".join(i["xml"] for i in items),
                        "not_applicable": all(is_not_applicable(t) for t in texts) if texts else True}
    return out
