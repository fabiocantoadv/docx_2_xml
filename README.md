# docx_2_xml

`scielo-docx-to-sps`: 
Pipeline local para converter artigos científicos em **DOCX** em **XML SciELO
Publishing Schema 1.8** (JATS 1.1), validado contra a DTD JATS e o schematron
oficial da SciELO.

É uma adaptação do pipeline de patentes
[`pi-patent-pdf-to-st36`](https://github.com/IBICT-INPI/pi-patent-pdf-to-st36)
(PDF do INPI → ST.36): a mesma arquitetura em etapas numeradas, o mesmo JSON
intermediário auditável, os mesmos logs JSONL por etapa, validação contra um
esquema local e exportação em pacotes. O que muda é a fonte (DOCX em vez de
PDF), o esquema de saída (SPS 1.8 em vez de ST.36) e o tipo de documento
(artigo científico em vez de folheto de patente). A correspondência etapa a
etapa está em [`docs/adaptacao_patentes_artigos.md`](docs/adaptacao_patentes_artigos.md).

## Fluxo

```text
docx/                                    config/journals/<revista>.json  (+ metadata.csv opcional)
  -> 01  work/sections/<nome-sps>.json   JSON intermediário (front, body, back, dados de publicação)
         work/assets/<nome-sps>/         imagens com o nome SPS (…-gf1.png)
  -> 01b work/assets/…-gfN.png           figuras feitas com formas do Word (opcional)
  -> 02  work/xml/<nome-sps>.xml         XML SciELO PS 1.8
  -> 03  work/reports/validation.jsonl   DTD JATS 1.1 + schematron sps-1.8
  -> 04  export/<nome-sps>/ (+ .zip)     pacote: XML + imagens + DOCX + manifest.json
```

O nome segue a regra SPS: `ISSN-acrônimo-volume-número-elocation`, por exemplo
`1562-4730-biblios-88-e001.xml`.

## Leitor SPS (navegador)

`viewer/index.html` é uma página estática que mostra o XML SPS como artigo, junto
com as imagens: abra a pasta de um pacote, o `.zip` ou o `.xml` com as imagens.
Tem três abas: o artigo renderizado (citações ligadas às referências, figuras,
tabelas, notas, estrutura de cada `element-citation`), o XML com destaque e
busca, e uma verificação rápida (imagens faltando, `xref` sem destino,
referências não citadas, `counts`, `pub-date` do SPS 1.8, ORCID, país).
Tudo roda no navegador; nenhum arquivo é enviado.

Publicação no GitHub Pages: o workflow `.github/workflows/pages.yml` publica a
pasta `viewer/` a cada push em `main`. Ative uma vez em *Settings → Pages →
Source: GitHub Actions*. Os exemplos de `viewer/samples/` carregam ao abrir.

## Notebook do Colab

[Abrir no Colab](https://colab.research.google.com/github/fabiocantoadv/docx_2_xml/blob/main/notebooks/docx_para_sps_colab.ipynb)

`notebooks/docx_para_sps_colab.ipynb` pede o DOCX, roda o pipeline, mostra o
XML e baixa o XML e o pacote `.zip`. O notebook baixa o pipeline deste repositório
(branch `main`) na etapa 2, então usa sempre a versão publicada. Para alterar as
células, edite e rode `python notebooks/make_colab_notebook.py`.

## Instalação

```bash
git clone https://github.com/fabiocantoadv/docx_2_xml
cd docx_2_xml
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

A única dependência obrigatória é `lxml`. Para a etapa 01b (figuras desenhadas
com formas do Word) são necessários o **LibreOffice** e o **PyMuPDF**
(`pip install -e ".[render]"`); sem eles a etapa é pulada com aviso.

## Execução completa

```bash
python scripts/run_pipeline.py \
  --docx samples/biblios-88/docx \
  --config config/journals/biblios.json \
  --render-shapes \
  --export work/export --zip \
  --reference samples/biblios-88/reference_xml
```

`--reference` é opcional: compara os XMLs gerados com XMLs de referência e
grava `work/reports/compare_reference.csv`. `--metadata` aceita um CSV com
metadados que o DOCX não traz ou que devem prevalecer (ver
`config/metadata.example.csv`). No Mac, se o `soffice` não estiver no PATH:
`--soffice /Applications/LibreOffice.app/Contents/MacOS/soffice`.

## Execução por etapa

```bash
python scripts/01_docx_to_sections.py --input docx --output work/sections --assets work/assets \
  --config config/journals/biblios.json [--metadata metadata.csv] --log work/reports/docx_to_sections.jsonl
python scripts/01b_render_shapes.py --sections work/sections --assets work/assets --pdf-cache work/pdf
python scripts/02_build_sps_xml.py --sections work/sections --config config/journals/biblios.json --output work/xml
python scripts/03_validate_sps.py --input work/xml --report work/reports/validation.jsonl
python scripts/04_export_package.py --xml work/xml --assets work/assets --sections work/sections --export-dir export --zip
python scripts/compare_with_reference.py --generated work/xml --reference samples/biblios-88/reference_xml --details
```

## De onde vem cada informação

| SPS 1.8 | Origem no DOCX |
|---|---|
| `journal-meta` | `config/journals/<revista>.json` (como o `xml_basic` das patentes) |
| DOI, número, elocation, ano | rodapé do DOCX (`No 88 (2025) e001 • DOI 10.5195/…`), sobrescrevível pelo CSV |
| título e títulos traduzidos | estilos `Title` / `Title 2` / `Article title 2`; idioma pela ordem dos resumos |
| autores, afiliação, ORCID, e-mail | linhas `Author Bio` da capa + bloco **Dados de publicação** |
| `given-names` / `surname` | pistas do próprio artigo ("Rocha, E. S. S." na contribuição de autoria); sem pista, heurística com partículas |
| resumos estruturados | `Abstract Title` + rótulos em negrito (`Objetivo.`, `Método.`…), um por parágrafo ou vários no mesmo |
| palavras-chave | `Keywords Title` + `Keywords List`, ou `Palavras-chave:` em negrito na mesma linha |
| `history`, `pub-date` | "Histórico: Recebido … – Aprovado … – Publicado …" |
| `permissions` | campo "Licença de uso" (CC BY / BY-NC… → URL Creative Commons) |
| `author-notes` | contribuição de autoria (`con`), conflito de interesses (`conflict`), editores (`edited-by`) |
| `funding-group` | campo "Financiamento": uma `award-group` por agência com sigla, `award-id` quando houver código |
| `body` | `Heading 1/2/3` → `sec` aninhadas (`sec-type` por título); listas pela numeração do Word; citações com estilo `Quote` |
| `fig` | estilo `Caption` (`Figura N – Título`, ou rótulo e título em linhas separadas) + imagem + `Fonte:`/`Nota.` → `attrib` |
| `table-wrap` | tabelas do Word (colspan/rowspan) ou "Tabela N" inserida como imagem |
| `ref-list` | parágrafos após "Referências"; ABNT → `element-citation` usando o **negrito** como `source` |
| `xref ref-type="bibr"` | chamadas autor-data no texto ligadas às referências (ver abaixo) |
| `fn-group` | notas de rodapé do Word + campos do bloco de dados de publicação (dados, IA, ética, preprint…) |
| `app-group` | seção "Apêndice"/"Anexo" |

Adaptar a outra revista é, em geral, copiar `config/journals/biblios.json` e
ajustar `journal`, os nomes de estilo do template Word e os marcadores
("Referências", "Dados de publicação").

## Resultado nas amostras da Biblios n. 88

Os dois DOCX em `samples/biblios-88/docx` geram XMLs **válidos na DTD JATS 1.1 e
no schematron sps-1.8**. Os XMLs de referência da pasta não passam no
schematron sps-1.8 (`pub-date` sem `date-type`/`publication-format`).

Comparação com a referência (`compare_with_reference.py`), e001 / e002:

| Campo | e001 | e002 | Observação |
|---|---|---|---|
| DOI, elocation, número, títulos, histórico, palavras-chave | 1,00 | 1,00 | |
| texto do corpo | 0,996 | 0,998 | |
| figuras | 5/5 | 2/2 | a Figura 5 do e001 é desenhada com formas e sai da etapa 01b |
| referências | 22/22 | 62/62 | |
| refs citadas no gabarito também ligadas | 100% | 100% | o pipeline liga 2 e 4 refs a mais, todas conferidas como corretas |
| tipo da referência | 0,77 | 0,86 | parte das divergências é erro do gabarito (ex.: BMC Medical Ethics como `book`) |
| ORCID | 1,00 | 0,00 | o gabarito do e002 não tem ORCID; o DOCX tem |
| licença | 1,00 | 0,00 | o DOCX do e002 diz CC BY 4.0; o gabarito diz BY-NC |
| resumo estruturado | 1,00 | 0,00 | o gabarito do e002 junta as 4 seções numa só |
| listas | — | 4 × 0 | o gabarito achatou as listas a), b), c) em parágrafos |

Divergências que pedem decisão editorial estão em
[`docs/revisao_humana.md`](docs/revisao_humana.md).

## Chamadas autor-data

`src/sciartigo/citations.py` liga `Metcalfe et al. (2020)`, `(Bouter, 2018, 2020)`,
`Shaw e Satalkar (2018)`, `(Soehartono; Yu; Khor, 2022)`, `(Conselho..., 2023)`,
`(Cope, c2024b)`. Só liga quando sobrenome (ou entidade) e ano batem com uma
única referência; texto dentro de links não é tocado. Referências sem nenhuma
chamada ligada aparecem no log da etapa 02 para conferência (em geral são
citadas com outro ano no texto, um erro do original).

## Testes

```bash
pytest
```

Inclui testes ponta a ponta nas amostras: XML válido, mesmos DOI/elocation,
mesmo número de referências e figuras que o gabarito, e cobertura total das
referências citadas no gabarito.

## Limitações conhecidas

- O parser de referências cobre ABNT (NBR 6023). Vancouver e APA caem em
  heurísticas mais fracas e recebem aviso; o `mixed-citation` mantém sempre o
  texto integral.
- Fórmulas (OMML) ainda não são convertidas para MathML.
- Sobrenomes compostos sem pista no documento seguem heurística e geram aviso.
- `funding-source` é extraído de nomes com sigla entre parênteses; outros
  formatos ficam como o enunciado inteiro, com aviso.

## Esquemas incluídos

`schemas/` traz a DTD JATS Publishing 1.1 e o schematron `scielo-style-1.8.sch`
(com `common.sch`), copiados do [packtools](https://github.com/scieloorg/packtools)
(licença BSD em `schemas/LICENSE.packtools`). Assim a validação roda offline,
sem instalar o packtools.
