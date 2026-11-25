# Chatbot-para-Estudos

## Banco de questões do ENEM

Questões das provas oficiais do INEP, extraídas **uma prova por vez**, com
interface para estudar e filtrar (`questoes.html`).

### Fluxo para adicionar uma prova

```bash
pip install pdfplumber pypdf
# 1. extrair (aplicação regular é o padrão; --aplicacao reaplicacao ou belem)
python scripts/extrair_prova_regular.py --ano 2023 --dia 2 --caderno 7
# 1b. converter em texto + recortes (blocos)
python scripts/estruturar_questoes.py --ano 2023 --dia 2 --caderno 7
# 2. classificar as questões em data/enem/classificacao/<ano>_<aplicacao>_D<dia>_CD<caderno>.json
# 3. importar dados oficiais dos Microdados (habilidade, dificuldade, descarte)
python scripts/importar_microdados.py --ano 2023
# 4. gerar o banco usado pela interface
python scripts/gerar_banco.py
# 5. só para publicar: pacotes de imagens (fora do git)
python scripts/empacotar_recortes.py
```

Abra `questoes.html` no navegador (funciona direto do disco, sem servidor).

### Arquivos

| Arquivo | Conteúdo |
|---|---|
| `data/enem/<ano>/<aplicacao>_D<dia>_CD<caderno>.json` | Questões extraídas de uma prova |
| `data/enem/<ano>/<prova>_textos_base.json` | Textos compartilhados por várias questões (2025 em diante: "Texto para as questões X a Y") |
| `data/enem/<ano>/img/*.png` | Imagem da questão como está na prova, só quando há imagem, gráfico, tabela ou fórmula |
| `data/enem/<ano>/img/blocos/*.png` | Recortes dos objetos visuais usados nos blocos e nas alternativas em desenho |
| `data/enem/edicoes/edicoes.json` | Correções manuais por cima do extraído (aplicadas por `gerar_banco.py`) |
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
`ITENS_PROVA_<ano>.csv` e a Matriz de Referência (o pacote de 2025 usa
compressão Deflate64, que o Python não lê: o importador baixa o zip inteiro e
usa o `unzip` do sistema). Cada prova extraída é associada ao código de prova
(`CO_PROVA`) cujo gabarito bate com 100% das questões da área. Com uma única
divergência e nenhum outro código próximo, o desempate é o vetor de gabarito
gravado por candidato (`TX_GABARITO_<área>`), que é o usado na correção.

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
Dificílima, Impossível). Os limites ignoram valores extremos (fora de 3·IQR dos
quartis): uma questão com discriminação muito baixa pode ter b absurdo (2024,
Humanas, Q62: nota equivalente 1753) e, sozinha, esmagaria a barra da área; ela
fica presa à ponta da barra e é sinalizada na interface. A calibração é refeita a cada `gerar_banco.py`, ou
seja, sempre que uma prova é adicionada. Áreas com menos de 10 questões ficam
sem barra. Questões descartadas da nota pelo INEP não têm dificuldade.

**Língua estrangeira:** a interface tem a escolha entre inglês e espanhol. A
língua não escolhida some da lista e não entra na nota, como no ENEM; com
"Ver as duas" e respostas nas duas línguas, a calculadora pede a escolha.

**Calculadora de nota (interface):** usa o mesmo modelo e as mesmas constantes
para estimar a nota a partir das respostas marcadas, separada por área e ano,
com uma faixa provável (±1 desvio-padrão da estimativa). Testada com 6
candidatos reais: a nota exibida coincidiu com a oficial (arredondada) nos 12
casos. As respostas ficam salvas só no navegador de quem usa a página.

### Texto + recortes
`scripts/estruturar_questoes.py` reescreve questões salvas como imagem inteira
em texto, recortando só os objetos visuais (foto, gráfico, desenho, tabela,
fórmula complexa). Regras: linhas que se sobrepõem a uma figura (rótulos,
legenda de eixo, texto de tabela) ficam no recorte; índices e expoentes viram
Unicode (H₂O, 10⁻³, f₀); frações simples viram "15/60"; alternativas em
desenho viram imagem por alternativa; linha centralizada (equação) é parágrafo
próprio. O que a conversão não garante fica marcado em `revisar`. A imagem
inteira continua salva e aparece em "Ver a questão como está na prova".

    python scripts/estruturar_questoes.py --ano 2024 --dia 2 --caderno 7 --questoes 92,97
    python scripts/gerar_banco.py

**Situação:** todas as questões com imagem de 2023 a 2026 estão convertidas.
Cada aviso "Conferir" foi revisado contra o PDF; as correções e os avisos
conferidos ficam em `data/enem/edicoes/edicoes.json`, e nenhum aviso fica
pendente na interface. "Fórmula recortada como imagem" é nota de extração e
não aparece para quem estuda. Defeitos conhecidos: 2023 regular Q135 (o recorte
do esquema leva junto duas linhas de texto), 2023 regular Q129 (rótulos "Cl Cl"
fora da figura) e 2025 regular Q107 (duas linhas de texto dentro do recorte da
figura); nas questões de 2025 Q138 e 2026 Q180 a imagem "como está na prova"
sai desalinhada (as alternativas, corretas, vêm dos recortes).

Para a página publicada (limite de 512 arquivos), `scripts/empacotar_recortes.py`
junta as imagens em pacotes JSON, em WebP (cerca de 4 vezes menor que PNG):
recortes de 10 em 10 questões e imagens "como está na prova" de 30 em 30. A página só baixa um pacote quando a imagem
falta como arquivo. Os pacotes são derivados das PNGs e não vão para o git.

### Classificação pela Matriz de Referência
`data/enem/taxonomia.json` (gerado por `scripts/taxonomia.py` a partir dos
"Objetos de conhecimento associados às Matrizes de Referência" do INEP)
organiza área › disciplina › conteúdo › tópico. A matriz só nomeia as
disciplinas de Ciências da Natureza; nas outras áreas a disciplina de cada
conteúdo ou tópico foi atribuída no script, e o que a matriz não cobre (ex.:
Ética, Teoria do conhecimento, gramática de língua estrangeira) está marcado
como **complemento**. O subtópico é livre e definido por questão.

A classificação antiga foi migrada por `scripts/migrar_classificacao.py` e
fica **provisória** (tópico aproximado, sem subtópico) até a questão ganhar
a ficha de comentários, que traz a classificação revista. Na interface, o
filtro "Disciplina, conteúdo e tópico" é uma árvore com seleção por grupo, e
as habilidades aparecem por área › competência.

### Comentários das questões
Cada questão pode ter uma ficha em `data/enem/comentarios/<ano>_<prova>.json`:
- comentário do enunciado;
- comentário da alternativa correta;
- um comentário por distrator;
- análise da questão (objetivo, o que facilita e o que dificulta, dados do
  INEP);
- recursos (resoluções comentadas, Wikipédia, vídeos, imagens livres), cada
  um no trecho a que se refere.

Os textos são redigidos a partir de pesquisa na web, não copiados. O padrão
está em `docs/procedimentos.md`, e `scripts/comentarios.py` valida as fichas
e gera os `.js` que a página carrega quando a questão é respondida.
Situação: piloto com 4 questões de 2025 (Física, Matemática, Filosofia e
Língua Portuguesa).

### Manutenção (botões da página)
Na página publicada, a dona vê o grupo "Manutenção do banco":
- **Atualizar dados** roda `scripts/atualizar_dados.py`: provas novas no
  servidor do INEP, microdados que saíram e comentários pendentes ou com
  pesquisa antiga.
- **Revisar e limpar** roda `scripts/manutencao.py`: anomalias, imagens
  órfãs, validação, banco e pacotes.

Cada botão dispara uma tarefa agendada (conector Claude Code Remote) que abre
uma sessão do Claude na nuvem. A sessão segue `docs/procedimentos.md`, salva
no git e republica a página. Os dois scripts também rodam à mão.

### Questões próprias e provas impressas
- **+ Nova questão** (barra lateral): questão autoral ou de outra fonte, com
  origem, fonte, ano, área e habilidade da Matriz do ENEM. O enunciado é feito
  em blocos (texto, imagem de arquivo), como nas demais. Sem parâmetros de TRI:
  a dificuldade fica para quando houver respostas de alunos.
- **+ Prova** em cada cartão monta uma prova; o botão **Prova (N)** abre o
  painel para ordenar, dar título e escolher 1 ou 2 colunas, origem das
  questões, cartão-resposta e gabarito. **Imprimir** usa a impressão do
  navegador; **Baixar para imprimir** gera um HTML com as imagens embutidas
  (abre em qualquer navegador e imprime ou salva em PDF). Provas podem ser
  salvas e reabertas.
- Na página publicada, questões próprias e provas ficam no banco de dados do
  artefato (coleções `questoes` e `provas`); "Baixar edições" inclui as duas
  como cópia de segurança.

### Edição de questões e imagens
Cada cartão tem **Editar questão** (enunciado, alternativas, gabarito,
disciplinas, conteúdos, observação) e, nas questões com imagem, **Editar
imagem** (corte arrastando sobre a figura, brilho, contraste e nitidez). Só os
campos alterados são guardados, por cima do original, e "Restaurar original"
desfaz. Da imagem guarda-se a receita (corte e ajustes), então ela reabre
ajustável a partir do original, que nunca é alterado.

Questões em blocos (texto + imagens) aceitam, no editor: adicionar campo de
texto, imagem de arquivo ou recorte da imagem original da prova; mover e
remover blocos; estilo por bloco (texto, título, legenda, fonte/citação,
centralizado); e formatação em linha (**negrito**, __itálico__, expoente e
índice). Questões no formato antigo podem ser montadas em blocos pelo botão
"Montar em blocos". Correções feitas no repositório ficam em
`data/enem/edicoes/edicoes.json` (ex.: questão 36 de 2024, cujo "TEXTO II"
estava fora do lugar na prova).

- **Página publicada:** edições no banco de dados do artefato e imagens no
  armazenamento de arquivos dele; só o dono e editores alteram, quem abre o
  link vê as mesmas edições.
- **Aberta do disco:** edições só no navegador (localStorage). Brilho,
  contraste e nitidez exigem abrir por um servidor
  (`python -m http.server`), porque o navegador bloqueia a leitura de
  imagens de arquivos locais.
- **Levar ao repositório:** "Baixar edições (JSON)" e depois
  `python scripts/aplicar_edicoes.py edicoes-banco-enem.json` e
  `python scripts/gerar_banco.py`. As edições ficam em
  `data/enem/edicoes/`, separadas dos arquivos extraídos.

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
| 2023 · reaplicação · 1º dia · caderno 1 (Azul) | 95/95 | 73 | 22 | 22 imagens revisadas; gabarito 95/95 igual aos microdados; 95 questões classificadas |
| 2023 · reaplicação · 2º dia · caderno 7 (Azul) | 90/90 | 35 | 55 | 55 imagens revisadas; gabarito 90/90 igual aos microdados; 90 questões classificadas |
| 2024 · regular · 1º dia · caderno 1 (Azul) | 95/95 | 83 | 12 | 12 imagens revisadas; gabarito 95/95 igual aos microdados; 95 questões classificadas |
| 2024 · regular · 2º dia · caderno 7 (Azul) | 90/90 | 21 | 69 | 69 imagens revisadas; gabarito 89/90 igual aos microdados (Q129 anulada); 90 questões classificadas |
| 2024 · reaplicação · 1º dia · caderno 1 (Azul) | 95/95 | 79 | 16 | 16 imagens revisadas; gabarito 95/95 igual aos microdados; 95 questões classificadas |
| 2024 · reaplicação · 2º dia · caderno 7 (Azul) | 90/90 | 32 | 58 | 58 imagens revisadas; gabarito 90/90 igual aos microdados; 90 questões classificadas |
| 2025 · regular · 1º dia · caderno 1 | 95/95 | 76 | 19 | gabarito 95/95 igual aos microdados; 1 texto-base; 95 classificadas |
| 2025 · regular · 2º dia · caderno 7 | 90/90 | 37 | 53 | gabarito 90/90 igual aos microdados (3 anuladas); 90 classificadas |
| 2025 · Belém, Ananindeua e Marituba · 1º dia · caderno 1 | 95/95 | 77 | 18 | gabarito 95/95 igual aos microdados; 1 texto-base; 95 classificadas |
| 2025 · Belém, Ananindeua e Marituba · 2º dia · caderno 7 | 90/90 | 54 | 36 | gabarito 90/90 igual aos microdados; 90 classificadas |
| 2025 · reaplicação · 1º dia · caderno 1 | 95/95 | 82 | 13 | gabarito 95/95 (Q15: ver abaixo); 95 classificadas |
| 2025 · reaplicação · 2º dia · caderno 7 | 90/90 | 47 | 43 | gabarito 90/90 igual aos microdados; 90 classificadas |
| 2026 · regular · 1º dia · caderno 1 | 95/95 | 78 | 17 | gabarito do PDF (microdados ainda não publicados); 2 textos-base; 95 classificadas |
| 2026 · regular · 2º dia · caderno 7 | 90/90 | 38 | 52 | gabarito do PDF (1 anulada); 90 classificadas |

**2025:** escalas de nota (validadas em 1500 candidatos, erro máximo 0,05
ponto): Linguagens 108,09·θ + 499,98; Humanas 112,31·θ + 501,49; Natureza
113,10·θ + 501,14; Matemática 129,65·θ + 500,02, iguais às de 2023 e 2024.
Descartadas da nota: regular 2º dia Q123, Q125, Q132, Q172 e Q174; reaplicação
Q62. Na reaplicação, Linguagens Q15: o `ITENS_PROVA` traz B, mas o caderno, o
vetor de gabarito dos 43 candidatos da amostra (TX_GABARITO_LC) e as notas
oficiais indicam D. Com D a escala reproduz as notas (erro máximo 0,048 ponto);
com B erra até 30 pontos. Fica D, e a questão conta na nota. A aplicação de
Belém, Ananindeua e Marituba não tem nenhum candidato no arquivo de resultados
(lido inteiro, 4,8 milhões de linhas), então a escala dela não foi conferida
com notas reais; o gabarito bate 100% com os microdados.

**2026:** os microdados ainda não existem (o pacote retorna 404); as questões
não têm habilidade nem dificuldade até a publicação. Os cadernos de 2026 usam
letras espaçadas em títulos e algumas fontes trazem glifos sem largura; o
extrator detecta cabeçalhos por caractere e usa os espaços explícitos do PDF.

A reaplicação de 2023 (PPL e reaplicação, mesma prova) não repete nenhuma questão
da aplicação regular do mesmo ano, mas reaproveita questões de edições anteriores.
A escala de notas de cada área é a mesma da aplicação regular: conferida em 25 a 28
candidatos da reaplicação por área (erro máximo de 0,05 ponto) e com 8 de 8 notas
reproduzidas pela calculadora.

Escalas de nota de 2023 (validadas contra as notas oficiais, erro máximo de 0,05 ponto):
Linguagens 108,09·θ + 499,98; Humanas 112,31·θ + 501,49; Natureza 113,10·θ + 501,14;
Matemática 129,65·θ + 500,02. A calculadora foi conferida com candidatos reais nas
quatro áreas (inglês e espanhol incluídos): 24 de 24 notas iguais às oficiais.

Em 2024 o INEP mudou o leiaute dos cadernos (página mais larga, sem linha
divisória entre as colunas); o extrator escolhe o perfil de página pela largura.
Os microdados de 2024 trazem respostas e notas em `RESULTADOS_2024.csv`. As
constantes da escala de nota de 2024 são idênticas às de 2023 nas quatro áreas.
Descartadas da nota em 2024: regular Q129 (anulada) e reaplicação Q40 ("algoritmo
não convergiu", motivo oficial). Calculadora conferida com 12 candidatos reais da
aplicação regular (inglês e espanhol): 24 de 24 notas iguais às oficiais; e com
28 candidatos da reaplicação: 52 de 52 notas de Natureza e Matemática iguais às
oficiais (Linguagens e Humanas da reaplicação: o arquivo de resultados inteiro, 4,33
milhões de linhas, não tem nenhum candidato com esses códigos de prova, então
essa parte não pôde ser conferida com notas reais).

### Observações técnicas
- O servidor `download.inep.gov.br` não envia o certificado intermediário. Os
  scripts confiam nesse intermediário (`scripts/certs/`, emitido pela GlobalSign
  Root R46) sem desligar a verificação TLS.
- `scripts/comum.py` guarda caminhos, download e leitura do gabarito, usados
  pelo extrator e pelo importador. (O antigo extrator dos cadernos DOSVOX foi
  removido: não era mais usado no banco.)
