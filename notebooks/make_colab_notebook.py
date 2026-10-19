"""Gera notebooks/docx_para_sps_colab.ipynb com o pipeline embutido (base64).

Rodar a partir da raiz do projeto:  python notebooks/make_colab_notebook.py
"""

import base64
import io
import tarfile
from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]


def bundle() -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in ("src", "scripts", "schemas", "config", "pyproject.toml", "README.md"):
            tar.add(ROOT / name, arcname=f"scielo-docx-to-sps/{name}",
                    filter=lambda ti: None if "__pycache__" in ti.name else ti)
    return base64.b64encode(buf.getvalue()).decode()


md = nbf.v4.new_markdown_cell
code = nbf.v4.new_code_cell

cells = [
    md("""# DOCX de artigo → XML SciELO PS 1.8

Envie o DOCX de um artigo e receba o XML no padrão **SciELO Publishing Schema 1.8** (JATS 1.1),
validado contra a DTD JATS e o schematron oficial da SciELO, mais o pacote SPS (XML + imagens).

É o pipeline `scielo-docx-to-sps` (adaptação do `pi-patent-pdf-to-st36`), embutido neste notebook.

**Como usar:** *Ambiente de execução → Executar tudo* (ou execute as células em ordem). Na etapa 3
aparece o botão para escolher o DOCX."""),
    md("## 1. Configuração"),
    code("""#@title Opções { display-mode: "form" }
#@markdown Revista (arquivo em `config/journals/`). Para outra revista, ajuste o JSON depois da etapa 2.
REVISTA = "biblios"  #@param {type:"string"}
#@markdown Renderiza figuras feitas com formas do Word (instala LibreOffice, ~2 min na 1ª vez).
RENDERIZAR_FORMAS = True  #@param {type:"boolean"}
#@markdown Metadados que prevalecem sobre o DOCX (deixe em branco para ler do rodapé / dados de publicação).
DOI = ""  #@param {type:"string"}
VOLUME = ""  #@param {type:"string"}
NUMERO = ""  #@param {type:"string"}
ELOCATION = ""  #@param {type:"string"}
DATA_PUBLICACAO = ""  #@param {type:"string"}
#@markdown Também copiar o resultado para o Google Drive (`MyDrive/scielo_sps/`).
SALVAR_NO_DRIVE = False  #@param {type:"boolean"}
#@markdown Mostrar o XML inteiro (desmarcado: só as primeiras linhas).
XML_COMPLETO = True  #@param {type:"boolean"}
#@markdown (Fora do Colab) caminho de um DOCX local, em vez do upload.
DOCX_LOCAL = ""  #@param {type:"string"}"""),
    md("## 2. Instalação do pipeline"),
    code(f"""import base64, io, os, subprocess, sys, tarfile
from pathlib import Path

try:
    import google.colab  # noqa: F401
    EM_COLAB = True
except ImportError:
    EM_COLAB = False

BASE = Path("/content" if EM_COLAB else os.getcwd())
PIPE = BASE / "scielo-docx-to-sps"
PIPELINE_TGZ = "{bundle()}"
if not PIPE.exists():
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(PIPELINE_TGZ)), mode="r:gz") as tar:
        try:
            tar.extractall(BASE, filter="data")
        except TypeError:  # Python < 3.12
            tar.extractall(BASE)
sys.path.insert(0, str(PIPE / "src"))

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "lxml>=5.0"] +
               (["pymupdf"] if RENDERIZAR_FORMAS else []), check=True)
if RENDERIZAR_FORMAS and EM_COLAB and subprocess.run(["which", "soffice"], capture_output=True).returncode != 0:
    print("Instalando LibreOffice (só na primeira execução)...")
    subprocess.run("apt-get -qq update && apt-get -qq install -y libreoffice-writer > /dev/null", shell=True, check=False)
print("Pipeline pronto em", PIPE)"""),
    md("## 3. Envie o DOCX do artigo"),
    code("""if DOCX_LOCAL:
    docx_path = Path(DOCX_LOCAL)
elif EM_COLAB:
    from google.colab import files
    entrada = BASE / "entrada"
    entrada.mkdir(exist_ok=True)
    enviados = files.upload()
    nome = next(n for n in enviados if n.lower().endswith(".docx"))
    docx_path = entrada / nome
    docx_path.write_bytes(enviados[nome])
else:
    raise SystemExit("Fora do Colab: preencha DOCX_LOCAL na etapa 1.")
print("Arquivo:", docx_path.name, f"({docx_path.stat().st_size/1024:.0f} KB)")"""),
    md("## 4. Conversão (DOCX → JSON → XML) e validação"),
    code("""import importlib, json
from sciartigo import docx_sections, sps, validation
from sciartigo.utils import read_json, write_json

config = read_json(PIPE / "config/journals" / f"{REVISTA}.json")
overrides = {k: v for k, v in {"doi": DOI, "volume": VOLUME, "issue": NUMERO,
                               "elocation": ELOCATION, "pub_date": DATA_PUBLICACAO}.items() if v.strip()}
work = BASE / "saida"
assets = work / "assets"

# etapa 01: DOCX -> JSON de secoes + imagens
sections = docx_sections.extract_sections(docx_path, config, assets, overrides)
base = sections["base_name"]

# etapa 01b: figuras feitas com formas do Word
def _figs(items):
    for it in items:
        if it["type"] == "fig":
            yield it
        yield from _figs(it.get("children", []))

pendentes = [f for f in _figs(sections["body"] + sections["apps"]) if f.get("needs_render")]
if pendentes and RENDERIZAR_FORMAS:
    from sciartigo.render_shapes import docx_to_pdf, find_soffice, render_figure
    soffice = find_soffice()
    if soffice:
        pdf = docx_to_pdf(docx_path, work / "pdf", soffice)
        for fig in pendentes:
            nome = f"{base}-gf{fig['id'].lstrip('f')}.png"
            nota = fig["notes"][0]["text"] if fig.get("notes") else ""
            r = render_figure(pdf, fig.get("label", ""), (fig.get("title") or {}).get("text", ""), nota, assets / base / nome)
            if r["status"] == "ok":
                fig["graphic"], fig["needs_render"] = nome, False
                sections["warnings"] = [w for w in sections["warnings"] if not w.startswith(f"figura {fig['id']} ")]
                sections["warnings"].append(f"figura {fig['id']} renderizada do PDF (pagina {r['page']}): conferir recorte")
    else:
        print("LibreOffice não encontrado: figuras de formas ficarão pendentes.")
write_json(work / "sections" / f"{base}.json", sections)

# etapa 02: JSON -> XML SPS 1.8
builder = sps.Builder(sections, config, sections["meta"], base)
xml_path = work / "xml" / f"{base}.xml"
sps.write_article(builder.build(), xml_path)

# etapa 03: validacao
resultado = validation.validate_xml(xml_path)

print(f"Nome SPS: {base}")
print(f"Referências: {len(sections['refs'])} | citações ligadas no texto: {builder.xref_count} "
      f"| figuras: {len(list(_figs(sections['body'] + sections['apps'])))}")
print("VALIDO (DTD JATS 1.1 + SPS 1.8)" if resultado["valid"] else "INVALIDO")
for erro in (resultado["dtd_errors"] + resultado["style_errors"])[:20]:
    print("  ✗", erro)
avisos = sections["warnings"] + builder.warnings
if avisos:
    print(f"\\nPontos para revisão ({len(avisos)}):")
    for a in avisos:
        print("  •", a)"""),
    md("## 5. XML gerado"),
    code("""from IPython.display import HTML, display
import html as _html

texto = xml_path.read_text(encoding="utf-8")
linhas = texto.splitlines()
mostrar = texto if XML_COMPLETO else "\\n".join(linhas[:200]) + f"\\n... ({len(linhas) - 200} linhas omitidas)"
try:
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import XmlLexer
    estilo = HtmlFormatter(style="friendly").get_style_defs(".highlight")
    display(HTML(f"<style>{estilo} .highlight pre{{white-space:pre-wrap;font-size:12px}}</style>"
                 + highlight(mostrar, XmlLexer(), HtmlFormatter())))
except ImportError:
    print(mostrar)"""),
    md("## 6. Salvar o resultado\n\nBaixa o XML e o pacote SPS (`.zip` com XML + imagens). Opcionalmente copia para o Drive."),
    code("""import shutil, zipfile
from lxml import etree

pacote = work / "pacote" / base
pacote.mkdir(parents=True, exist_ok=True)
shutil.copy2(xml_path, pacote / xml_path.name)
faltando = []
arvore = etree.parse(str(xml_path), etree.XMLParser(load_dtd=False, no_network=True))
for g in arvore.iter("graphic"):
    href = g.get("{http://www.w3.org/1999/xlink}href")
    origem = assets / base / href
    if origem.exists():
        shutil.copy2(origem, pacote / href)
    else:
        faltando.append(href)
zip_path = work / f"{base}.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for f in sorted(pacote.iterdir()):
        zf.write(f, f.name)
print("XML:   ", xml_path)
print("Pacote:", zip_path, f"({len(list(pacote.iterdir()))} arquivos)")
if faltando:
    print("Imagens pendentes:", ", ".join(faltando))

if SALVAR_NO_DRIVE and EM_COLAB:
    from google.colab import drive
    drive.mount("/content/drive")
    destino = Path("/content/drive/MyDrive/scielo_sps")
    destino.mkdir(parents=True, exist_ok=True)
    shutil.copy2(xml_path, destino / xml_path.name)
    shutil.copy2(zip_path, destino / zip_path.name)
    print("Copiado para", destino)

if EM_COLAB:
    from google.colab import files
    files.download(str(xml_path))
    files.download(str(zip_path))"""),
    md("""## Observações

- O JSON intermediário (`saida/sections/*.json`) mostra o que foi lido de cada parte do DOCX; os
  avisos da etapa 4 indicam o que conferir (sobrenomes compostos, referências fora do padrão ABNT,
  figuras renderizadas).
- Os dados do periódico (`journal-meta`) e os nomes de estilo do template Word vêm de
  `config/journals/<revista>.json`. Para outra revista, edite esse arquivo pelo painel de arquivos do Colab
  e rode a etapa 4 de novo."""),
]

nb = nbf.v4.new_notebook(cells=cells, metadata={
    "colab": {"provenance": [], "name": "docx_para_sps_colab.ipynb"},
    "kernelspec": {"name": "python3", "display_name": "Python 3"},
    "language_info": {"name": "python"},
})
out = ROOT / "notebooks/docx_para_sps_colab.ipynb"
nbf.write(nb, out)
print(out, f"{out.stat().st_size/1024:.0f} KB")
