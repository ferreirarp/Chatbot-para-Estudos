# Plano do banco de questões ENEM

O que está decidido e ainda não foi feito, em ordem de prioridade. Atualize
ao concluir ou mudar de ideia.

## 1. Exportação em documento: formatação e cabeçalho
Feito: exportar a prova montada, ou o resultado da busca (até 300 questões),
em Word (.docx gerado no navegador), PDF (pela janela de impressão), HTML e
texto (.txt). As opções de conteúdo (origem, cartão-resposta, gabarito)
valem para todos os formatos.

A fazer:
- **Formatação:** fonte e tamanho, espaçamento, margens, 1 ou 2 colunas no
  Word, numeração das questões, alternativas em linha ou em lista, tamanho
  das imagens.
- **Cabeçalho:** nome da escola e logotipo, campos (nome, turma, data,
  professor), instruções da prova, título e subtítulo, rodapé com
  numeração de páginas.
- Decidir se as escolhas ficam salvas com a prova (como as opções de
  conteúdo) e se haverá modelos prontos (ex.: "simulado", "lista de
  exercícios").
- Avaliar PDF gerado direto, sem a janela de impressão. Exige uma
  biblioteca externa; hoje o container não alcança os servidores de
  bibliotecas, então não há como testar daqui.

## 2. Comentários das questões (feedback padrão)
Feito: formato, validação (`scripts/comentarios.py`), exibição na página,
roteiro em `docs/procedimentos.md` e piloto com 4 questões de 2025.

A fazer: fichas para as outras 1476 questões. Decisões pendentes:
- **Recorte:** tudo, ou começar por 2025 e 2026, ou pelas questões mais
  difíceis (onde o comentário ajuda mais).
- **Execução:** sessões em paralelo (uma por prova; mais rápido, mesmo
  custo) ou o botão "Atualizar dados" (uma prova por vez).
- **Custo:** estimativa fraca, baseada em 4 casos. Cerca de 3 buscas por
  questão (2 créditos do Firecrawl cada) e algumas horas de sessão por
  prova.
- **Revisão humana:** cada comentário aparece como "não revisado" até alguém
  conferir. Definir quem revisa e como marcar `revisado: true`.

## 3. Classificação definitiva
A classificação atual veio dos rótulos antigos e é provisória: tópico
aproximado, sem subtópico. A definitiva chega com a ficha de comentários de
cada questão (item 2). Se os comentários forem adiados por muito tempo, dá
para fazer só a classificação, prova por prova, mais barata.

## 4. Anos anteriores (2022 para trás)
Depois dos itens acima, para o banco crescer já com taxonomia, comentários e
exportação estáveis. Verificar antes: leiaute dos cadernos de cada ano e se
os microdados trazem `ITENS_PROVA` no mesmo formato.

## 5. Manutenção e pendências técnicas
- **Botões da página:** testar de ponta a ponta. Abrir a página publicada
  como dona, com o conector Claude Code Remote ativo, e disparar.
- **Tarefas agendadas sem conectores:** a organização não permite gravar
  conectores nelas, então as sessões disparadas não têm o Firecrawl e usam
  a busca nativa (WebSearch), que ainda não foi testada nesse contexto.
- **Defeitos conhecidos:**
  - 2023 regular Q135 e Q129;
  - 2025 regular Q107 (texto dentro do recorte);
  - imagem "como está na prova" desalinhada em 2025 Q138 e 2026 Q180;
  - ordem do "e" em listas de frações (corrigida à mão em 2025
    reaplicação Q148).
- **Matriz:** confirmar se há nova Matriz de Referência (Novo Ensino
  Médio) com vigência anunciada. Se houver, `scripts/taxonomia.py` precisa
  de uma versão nova.
