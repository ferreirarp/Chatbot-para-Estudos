# Chatbot-para-Estudos

## Banco de questões do ENEM

`scripts/extrair_enem.py` baixa as provas e os gabaritos oficiais do INEP e gera
`data/enem/<ano>.json`.

```bash
pip install pypdf
python scripts/extrair_enem.py --ano 2023
```

**Fonte das questões:** os arquivos DOSVOX (`.txt`) que o INEP publica para
leitores de tela. Eles trazem texto limpo e descrevem figuras e gráficos em
palavras, em vez de depender da extração de PDF (que quebra fórmulas e
transforma gráficos em números estimados).

**Fonte das respostas:** o gabarito em PDF do mesmo caderno do arquivo DOSVOX.

**Limitações conhecidas**
- Os cadernos adaptados trocam algumas questões da prova regular: o JSON é um
  banco de questões reais do ano, não a prova completa. O campo `numero` segue
  a numeração do caderno adaptado (ex.: Caderno 11 Laranja), não do Azul.
- `somente_versao_adaptada: true` marca questões que não aparecem no caderno
  regular do mesmo dia (comparação de texto com o caderno regular inteiro;
  `semelhanca_prova_regular` traz a nota de 0 a 1). Em 2023 são 4 questões, todas
  do 2º dia: CN 102, CN 113, MT 146 e MT 163 (numeração do Caderno 11). Nenhuma
  delas aparece também na reaplicação (PPL) de 2023.
- A comparação usa o `pdftotext` (pacote poppler-utils) se estiver instalado;
  sem ele, usa o pypdf, que em 2023 gerou um falso "ausente".
- Fórmulas aparecem escritas por extenso ("fração com numerador ...").
- O servidor `download.inep.gov.br` não envia o certificado intermediário. O
  script confia nesse intermediário (`scripts/certs/`, emitido pela GlobalSign
  Root R46) sem desligar a verificação TLS.

Cada questão traz `alertas`: se não estiver vazio, revise antes de usar.

## Provas regulares (fonte principal)

`scripts/extrair_prova_regular.py` extrai **uma prova regular por vez** (caderno
impresso do INEP), na numeração oficial:

```bash
pip install pdfplumber pypdf
python scripts/extrair_prova_regular.py --ano 2023 --dia 2 --caderno 7
```

Saída: `data/enem/<ano>/D<dia>_CD<caderno>.json` e, só para questões com
elementos visuais, `data/enem/<ano>/img/D<dia>_CD<caderno>_Q<n>.png`.

- Questões só de texto: salvas só como texto (`texto_fiel: true`).
- Questões com imagem, gráfico, desenho, tabela ou fórmula: texto + imagem
  recortada do PDF (`imagem`, `elementos_visuais`, `texto_fiel: false`). Nelas a
  **imagem é a referência**; o texto serve para busca e pode ter fórmulas quebradas.

Verificações automáticas a cada execução:
- todas as questões esperadas foram encontradas;
- cada letra do conteúdo cai em exatamente uma questão (nada cortado ou duplicado);
- nenhuma figura ou desenho é partido entre duas questões;
- respostas lidas do gabarito do mesmo caderno.

| Prova | Questões | Só texto | Com imagem | Conferência manual |
|---|---|---|---|---|
| 2023, dia 2, caderno 7 (Azul) | 90/90 | 33 | 57 | 57 imagens revisadas; gabarito 90/90 contra leitura independente |
