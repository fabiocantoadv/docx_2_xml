# Adaptação: pipeline de patentes → artigos SciELO

O pipeline de patentes (`pi-patent-pdf-to-st36`) foi usado como molde. A
tabela mostra o que foi mantido, o que foi trocado e por quê.

| Patentes (PDF → ST.36) | Artigos (DOCX → SPS 1.8) | Observação |
|---|---|---|
| `xml_basic/` externo ou capa do PDF (`01`/`01a`) | `config/journals/*.json` + rodapé do DOCX + `metadata.csv` opcional | O artigo traz quase toda a bibliografia no próprio DOCX; só o `journal-meta` vem de fora. |
| `02_pdf_full_to_text_sections.py` (PyMuPDF / MinerU) | `01_docx_to_sections.py` (OOXML via lxml) | O DOCX já tem estrutura (estilos, runs, notas, numeração); não há OCR nem detecção de layout. |
| `work/pdf_text_sections/*.json` | `work/sections/*.json` | Mesmo princípio: o arquivo de origem nunca vai direto para o XML final; o JSON é o artefato de auditoria. |
| `xml_full_text_assets/` (recortes do PDF) | `work/assets/<nome-sps>/` (imagens do pacote DOCX) | Nome das imagens já na regra SPS (`…-gf1.png`). |
| recorte de desenhos com PyMuPDF | `01b_render_shapes.py`: LibreOffice → PDF → PyMuPDF | Reaproveita a técnica de recorte para figuras feitas com formas do Word, que não existem como imagem no DOCX. |
| `st36.py` (montagem ST.36) | `sps.py` (montagem JATS 1.1 / SPS 1.8) | Ordem de elementos pela DTD JATS; regras de estilo pelo schematron sps-1.8. |
| `04_validate_st36.py` + DTD BR | `03_validate_sps.py` + DTD JATS 1.1 + `scielo-style-1.8.sch` | Validação dupla: estrutura (DTD) e regras SciELO (schematron). |
| `05_export_results.py` | `04_export_package.py` | Pacote por artigo com XML, imagens, DOCX original e `manifest.json` com SHA-256 (como no pacote de lote do PatenteIA). |
| `compare_batches.py` | `compare_with_reference.py` | Métrica campo a campo contra XMLs marcados (gabarito). |
| `sections_store.py` (melhor de duas extrações) | — | Um DOCX por artigo; não há extratores concorrentes. |
| `latex_text.py`, `mineru_*` | — | Sem OCR; fórmulas OMML → MathML ficam como trabalho futuro. |
| reivindicações, descrição, desenhos | front (autores, resumos, palavras-chave), `body` com seções, `ref-list`, notas | Documento de outra natureza. |
| — | `references.py`, `citations.py` | Novo: referências ABNT → `element-citation` e chamadas autor-data → `xref`. |
| — | `pubdata.py` | Novo: bloco "Dados de publicação" (ORCID, e-mail, histórico, financiamento, CRediT, conflito, licença). |

## Convenções mantidas

- scripts numerados em `scripts/`, biblioteca em `src/`;
- `run_pipeline.py` com `--skip-validation` e etapas que não derrubam o lote
  quando um documento falha (o erro vai para o JSONL);
- um registro JSONL por documento e etapa, com `status`, `warnings` e caminhos;
- esquemas locais versionados no repositório, para validar offline;
- testes `pytest` com amostra real pequena versionada em `samples/`.
