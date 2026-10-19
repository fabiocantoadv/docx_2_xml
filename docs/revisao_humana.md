# Pontos para revisão humana (amostras Biblios n. 88)

O pipeline registra estes casos como aviso (`warnings` no JSON e no JSONL).
Nos dois artigos de exemplo, as divergências em relação ao XML de referência
são estas:

## e001 (DOI 10.5195/biblios.2025.1310)

- **Sobrenome da segunda autora.** O DOCX lista "Sofia Dias de Sousa"; a
  contribuição de autoria do próprio artigo usa "Sousa, S. D". O pipeline gera
  `surname` = "de Sousa", `given-names` = "Sofia Dias". A referência usa
  "Dias de Sousa" / "Sofia". Precisa de confirmação com a autora.
- **Afiliação da segunda autora.** A capa do DOCX diz "São Paulo"; a
  referência repete "Ribeirão Preto" da primeira autora. O pipeline segue o DOCX.
- **Tabela do Apêndice.** O DOCX tem uma tabela ("Campos Analisados") no
  apêndice; a referência não a inclui. O pipeline gera `app-group/app/table-wrap`.
- **Figura 5.** É feita com formas do Word (sem imagem). A etapa 01b renderiza
  a figura a partir de um PDF gerado pelo LibreOffice; vale conferir o recorte.
- **Ref. B9 (INFODEMIC).** Entrada por título, sem negrito: tipo `book` com
  `chapter-title`; a referência marcou como `webpage`.

## e002 (DOI 10.5195/biblios.2025.1217)

- **Licença.** O DOCX diz "Creative Commons Attribution (CC BY) 4.0"; a
  referência usa BY-NC 4.0. O pipeline segue o DOCX; a revista deve confirmar.
- **ORCID.** O DOCX traz os dois ORCID; a referência não tem nenhum.
- **Resumo estruturado.** O DOCX tem os quatro rótulos (Objetivo, Método,
  Resultados, Conclusões) no mesmo parágrafo; o pipeline cria quatro `sec`,
  enquanto a referência criou uma só.
- **Listas.** As enumerações a), b), c) do DOCX viram `list list-type="alpha-lower"`;
  a referência as achatou em parágrafos.
- **Ref. B6 (ANTES A. L., KUYKENDALL, A.; DUBOIS J. M.).** Autoria fora do
  padrão ABNT no original; o parser avisa "autoria possivelmente incompleta".
- **Refs. B12 e B23.** Sem ano no original; o ano foi inferido da data de acesso.
- **Refs. sem chamada ligada** (log da etapa 02): B52 (Steneck et al., 2018) é
  citada no texto como "Steneck et al., 2017"; B57 (World Conference on Research
  Integrity) como "World Conferences on Research Integrity, c2024"; B43 (Resnik;
  Elliott, 2019) aparece uma vez como "Resnik; Elliott, 2023"; B42 (Resnik, 2008)
  e outras (Garfield, Karlberg, Lee, Srivastava) não aparecem no corpo do texto.
  São inconsistências do próprio original, que o pipeline não corrige.
