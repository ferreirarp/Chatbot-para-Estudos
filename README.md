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
# 3. gerar o banco usado pela interface
python scripts/gerar_banco.py
```

Abra `questoes.html` no navegador (funciona direto do disco, sem servidor).

### Arquivos

| Arquivo | Conteúdo |
|---|---|
| `data/enem/<ano>/<aplicacao>_D<dia>_CD<caderno>.json` | Questões extraídas de uma prova |
| `data/enem/<ano>/img/*.png` | Recorte da questão, só quando há imagem, gráfico, tabela ou fórmula |
| `data/enem/classificacao/*.json` | Disciplinas e conteúdos de cada questão (feito à parte; não é apagado ao reextrair) |
| `data/banco_questoes.js` | Banco unificado para a interface (gerado; não editar) |

Cada questão registra a **versão da prova** (`prova`: ano, aplicação regular ou
reaplicação, dia, caderno e cor), a **área** (Ciências da Natureza, Ciências
Exatas, Linguagens, Ciências Humanas), as **disciplinas** e os **conteúdos**.

**Critério de disciplina:** a habilidade e o conhecimento usados para chegar à
resposta, não o contexto do enunciado. Ex.: uma questão sobre um inseticida em
fluidos do corpo, resolvida por polaridade e solubilidade, é Química, não Biologia.

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
