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

**Escala de notas:** o INEP calcula a proficiência θ por TRI de 3 parâmetros
(D = 1), método EAP com priori normal padrão e 40 pontos de quadratura, e a
converte em nota com uma fórmula linear própria de cada **área e ano**
(nota = k·θ + m). Como k e m não são publicados, o importador os estima por
regressão numa amostra de candidatos dos microdados e valida em outra amostra.
2023: Natureza = 113,10·θ + 501,14; Matemática = 129,65·θ + 500,02; erro
máximo de 0,05 ponto em relação às notas oficiais.

**Dificuldade:** cada questão tem uma "nota equivalente" (k·b + m), a nota em
que um candidato tem chance intermediária de acertá-la. A barra é **calibrada
por área**: vai da questão mais fácil à mais difícil daquela área no banco, em
7 faixas de largura igual (Para não zerar, Facílima, Fácil, Mediana, Difícil,
Dificílima, Impossível). A calibração é refeita a cada `gerar_banco.py`, ou
seja, sempre que uma prova é adicionada. Áreas com menos de 10 questões ficam
sem barra. Questões descartadas da nota pelo INEP não têm dificuldade.

**Calculadora de nota (interface):** usa o mesmo modelo e as mesmas constantes
para estimar a nota a partir das respostas marcadas, separada por área e ano,
com uma faixa provável (±1 desvio-padrão da estimativa). Testada com 6
candidatos reais: a nota exibida coincidiu com a oficial (arredondada) nos 12
casos. As respostas ficam salvas só no navegador de quem usa a página.

### Texto e imagem
- Questões só de texto: salvas só como texto (`texto_fiel: true`).
- Questões com imagem, gráfico, desenho, tabela ou fórmula: texto + imagem
  recortada do PDF oficial (`texto_fiel: false`). Nelas a **imagem é a
  referência**; o texto serve para busca e pode ter fórmulas quebradas.

### Verificações automáticas a cada extração
- todas as questões esperadas foram encontradas;
- cada letra do conteúdo cai em exatamente uma questão (nada cortado ou duplicado);
- nenhuma figura ou desenho é partido entre duas questões;
- respostas lidas do gabarito do mesmo caderno;
- páginas da proposta de redação e títulos de seção ("Questões de 01 a 05 (opção
  espanhol)") não entram em nenhuma questão.

### Provas incluídas

| Prova | Questões | Só texto | Com imagem | Conferência manual |
|---|---|---|---|---|
| 2023 · regular · 1º dia · caderno 1 (Azul) | 95/95 (45 + 5 da 2ª língua estrangeira + 45) | 82 | 13 | 13 imagens revisadas; gabarito 95/95 contra leitura independente; 95 questões classificadas |
| 2023 · regular · 2º dia · caderno 7 (Azul) | 90/90 | 33 | 57 | 57 imagens revisadas; gabarito 90/90 contra leitura independente; 90 questões classificadas |

Escalas de nota de 2023 (validadas contra as notas oficiais, erro máximo de 0,05 ponto):
Linguagens 108,09·θ + 499,98; Humanas 112,31·θ + 501,49; Natureza 113,10·θ + 501,14;
Matemática 129,65·θ + 500,02. A calculadora foi conferida com candidatos reais nas
quatro áreas (inglês e espanhol incluídos): 24 de 24 notas iguais às oficiais.

### Observações técnicas
- O servidor `download.inep.gov.br` não envia o certificado intermediário. Os
  scripts confiam nesse intermediário (`scripts/certs/`, emitido pela GlobalSign
  Root R46) sem desligar a verificação TLS.
- `scripts/extrair_enem.py` guarda funções de download e de leitura de gabarito
  usadas pelo extrator. Também extrai os cadernos adaptados (DOSVOX), que não são
  mais usados no banco.
