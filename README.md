# Chatbot-para-Estudos

## Banco de questões do ENEM

Questões das provas oficiais do INEP, extraídas **uma prova por vez**, com
interface para estudar e filtrar (`questoes.html`).

### Fluxo para adicionar uma prova

```bash
pip install pdfplumber pypdf
# 1. extrair (aplicação regular é o padrão; use --aplicacao reaplicacao para a PPL)
python scripts/extrair_prova_regular.py --ano 2023 --dia 2 --caderno 7
# 2. classificar as questões em data/enem/classificacao/<ano>_<aplicacao>_D<dia>_CD<caderno>.json
# 3. importar dados oficiais dos Microdados (habilidade, dificuldade, descarte)
python scripts/importar_microdados.py --ano 2023
# 4. gerar o banco usado pela interface
python scripts/gerar_banco.py
```

Abra `questoes.html` no navegador (funciona direto do disco, sem servidor).

### Arquivos

| Arquivo | Conteúdo |
|---|---|
| `data/enem/<ano>/<aplicacao>_D<dia>_CD<caderno>.json` | Questões extraídas de uma prova |
| `data/enem/<ano>/img/*.png` | Recorte da questão, só quando há imagem, gráfico, tabela ou fórmula |
| `data/enem/classificacao/*.json` | Disciplinas e conteúdos de cada questão (feito à parte; não é apagado ao reextrair) |
| `data/enem/oficial/*.json` | Dados oficiais por questão, dos Microdados do ENEM: habilidade, parâmetros da TRI (a, b, c), descarte da nota |
| `data/enem/matriz_referencia.json` | Texto das habilidades H1–H30 e competências de cada área (Matriz de Referência) |
| `data/banco_questoes.js` | Banco unificado para a interface (gerado; não editar) |

Cada questão registra a **versão da prova** (`prova`: ano e aplicação regular ou
reaplicação), a **área** com o nome oficial do ENEM, as **disciplinas** e os
**conteúdos** (uma questão pode ter mais de um de cada, quando a resolução exige).

**Critério de disciplina:** a habilidade e o conhecimento usados para chegar à
resposta, não o contexto do enunciado. Ex.: uma questão sobre um inseticida em
fluidos do corpo, resolvida por polaridade e solubilidade, é Química, não Biologia.

### Dados oficiais (Microdados do ENEM)
`importar_microdados.py` baixa por partes, do pacote de microdados do INEP, só o
`ITENS_PROVA_<ano>.csv` e a Matriz de Referência. Cada prova extraída é
associada ao código de prova (`CO_PROVA`) cujo gabarito bate com 100% das
questões da área; sem correspondência exata, nada é importado.

**Dificuldade:** parâmetro b da TRI. A nota equivalente na escala do ENEM é
500 + 100 × b (INEP, *Procedimentos de Análise*). A barra vai de b = −1,5
(350 pontos) a b = 3,5 (850 pontos) e é dividida em 7 faixas de largura igual
(≈ 0,71 cada): Para não zerar, Facílima, Fácil, Mediana, Difícil, Dificílima,
Impossível. Em 2023, o b de todas as questões ficou entre −1,15 e 3,22.
Questões descartadas da nota pelo INEP não têm b e aparecem marcadas.

### Texto e imagem
- Questões só de texto: salvas só como texto (`texto_fiel: true`).
- Questões com imagem, gráfico, desenho, tabela ou fórmula: texto + imagem
  recortada do PDF oficial (`texto_fiel: false`). Nelas a **imagem é a
  referência**; o texto serve para busca e pode ter fórmulas quebradas.

### Verificações automáticas a cada extração
- todas as questões esperadas foram encontradas;
- cada letra do conteúdo cai em exatamente uma questão (nada cortado ou duplicado);
- nenhuma figura ou desenho é partido entre duas questões;
- respostas lidas do gabarito do mesmo caderno.

### Provas incluídas

| Prova | Questões | Só texto | Com imagem | Conferência manual |
|---|---|---|---|---|
| 2023 · regular · 2º dia · caderno 7 (Azul) | 90/90 | 33 | 57 | 57 imagens revisadas; gabarito 90/90 contra leitura independente; 90 questões classificadas |

### Observações técnicas
- O servidor `download.inep.gov.br` não envia o certificado intermediário. Os
  scripts confiam nesse intermediário (`scripts/certs/`, emitido pela GlobalSign
  Root R46) sem desligar a verificação TLS.
- `scripts/extrair_enem.py` guarda funções de download e de leitura de gabarito
  usadas pelo extrator. Também extrai os cadernos adaptados (DOSVOX), que não são
  mais usados no banco.
