# Procedimentos do banco de questões ENEM

Roteiro para quem mantém o banco: uma pessoa, ou uma sessão do Claude aberta
pelos botões "Atualizar dados" e "Revisar e limpar" da página. Vale para
sessões novas: tudo o que é preciso saber está aqui e no README.

Repositório: `ferreirarp/Chatbot-para-Estudos`, branch
`claude/enem-question-extraction-e6x0c5`. Página publicada:
https://claude.ai/artifact/MYpQXjDMU9jRVsX3QY4oN7

## 1. Atualizar dados (botão "Atualizar dados")

1. `python scripts/atualizar_dados.py`: verifica provas novas no INEP,
   importa microdados que saíram e lista questões sem comentário ou com
   pesquisa antiga. O relatório fica em `data/enem/relatorios/atualizacao.json`.
2. **Prova nova:** siga o "Fluxo para adicionar uma prova" do README
   (extrair, estruturar, classificar pela taxonomia, importar microdados,
   revisar os avisos com a imagem do PDF ao lado).
3. **Comentários:** faça as fichas que faltam (seção 3), em lotes por
   prova. Fichas com pesquisa antiga: refaça só a pesquisa e atualize os
   recursos e o que mudou.
4. Rode `python scripts/manutencao.py` (seção 2) e publique (seção 4).

## 2. Revisar e limpar (botão "Revisar e limpar")

1. `python scripts/manutencao.py`: anomalias, imagens órfãs, validação de
   taxonomia, classificação e comentários, banco e pacotes. Relatório em
   `data/enem/relatorios/manutencao.json`.
2. Cada pendência listada: confira contra o PDF (`.cache/enem/<ano>/`).
   Correção pontual vai em `data/enem/edicoes/edicoes.json` (campos
   alterados, com `nota` explicando). Defeito que se repete: corrija o
   extrator e rode de novo as provas afetadas, comparando o texto de antes e
   depois (nenhuma questão pode piorar).
3. Publique (seção 4).

## 3. Comentários (fichas) e classificação

Uma ficha por questão em `data/enem/comentarios/<ano>_<prova>.json`, no
formato descrito em `scripts/comentarios.py`. Sete comentários:

1. **enunciado**: o que o texto e a pergunta dizem, destrinchado; o que o
   comando pede.
2. **correta**: por que a alternativa do gabarito está certa, com o
   raciocínio ou o cálculo completo.
3. **distratores** (4): para cada alternativa errada, por que é falsa e,
   quando der, qual erro de raciocínio leva a ela.
4. **analise**: objetivo da questão (conceito, procedimento, habilidade), o
   que facilita e o que dificulta. Termine com os **dados do INEP**
   (habilidade oficial e dificuldade) quando existirem, e aponte quando a
   habilidade do INEP diverge da classificação pelo que a resolução exige.

**Pesquisa:**
- Busque resoluções comentadas da questão (Firecrawl, se a sessão tiver;
  senão WebSearch e WebFetch): número da
  questão, cor do caderno e um trecho do texto. A mesma questão tem outro
  número em outras cores.
- Busque também leituras de apoio (Wikipédia em português, Wikimedia
  Commons, materiais educacionais abertos, reportagens de acesso livre,
  vídeos).
- **Toda URL citada precisa ter aparecido num resultado de busca ou ter sido
  aberta.** Nunca escreva um endereço de memória.

**Redação:**
- Texto próprio, a partir da pesquisa: nunca copie comentários de
  terceiros. As fontes vão em `recursos`, no trecho a que se referem.
- Confira o gabarito oficial e refaça a resolução. Se a fonte discordar do
  gabarito, registre na análise.
- Use português claro, frases curtas e **negrito** só no essencial.
- Imagens: só com licença livre (Wikimedia Commons) e com `credito`.

**Classificação** (vai na ficha e substitui a provisória):
- Disciplina › conteúdo › tópico devem existir em
  `data/enem/taxonomia.json`. O subtópico é livre e específico da questão.
- Inclua um item por conceito, procedimento ou habilidade que a
  **resolução exige**, não pelo tema do texto.

**Antes de terminar:** `python scripts/comentarios.py` (0 erros) e
`python scripts/gerar_banco.py`.

## 4. Publicar

1. `python scripts/empacotar_recortes.py` (pacotes WebP de imagens, fora
   do git).
2. Commit e push no branch acima, com mensagem que diga o que mudou.
3. Republique a página com a ferramenta Artifact, na URL acima:
   - Leia o artefato antes (`action: "read"`); a ferramenta recusa publicar
     num artefato que a sessão não leu.
   - `file_path` é `questoes.html`; os arquivos vão em `files`:
     - `data/banco_questoes.js`;
     - os pacotes `data/enem/*/blocos/*.json` que mudaram;
     - os `data/enem/comentarios/*.js` que mudaram.
   - Mande no máximo 255 arquivos e 64 MB por envio; divida por ano se
     precisar.
   - Não passe `capabilities`, para manter as que a página já tem.
4. Escreva no relatório final o que foi feito, o que ficou pendente e por
   quê.
