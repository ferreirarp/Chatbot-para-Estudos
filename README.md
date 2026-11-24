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
- Fórmulas aparecem escritas por extenso ("fração com numerador ...").
- O servidor `download.inep.gov.br` não envia o certificado intermediário. O
  script confia nesse intermediário (`scripts/certs/`, emitido pela GlobalSign
  Root R46) sem desligar a verificação TLS.

Cada questão traz `alertas`: se não estiver vazio, revise antes de usar.
