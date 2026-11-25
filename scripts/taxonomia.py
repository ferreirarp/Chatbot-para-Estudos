#!/usr/bin/env python3
"""Gera data/enem/taxonomia.json: área > disciplina > conteúdo > tópico.

    python scripts/taxonomia.py

Fonte: "Objetos de conhecimento associados às Matrizes de Referência" do
documento oficial da Matriz de Referência do ENEM (INEP), que o
importar_microdados.py baixa para .cache/enem/<ano>/microdados/.

Regras de leitura do documento:
- Conteúdo = item "•" (o nome é o trecho antes de ":" ou " - ").
- Tópico = em Ciências da Natureza, cada frase do item; em Matemática e
  Linguagens, cada termo da lista depois de ":" ou " - "; em Humanas, cada
  item "o".
- Subtópicos não existem no documento: são definidos por questão, na
  classificação, a partir do que a resolução exige.

A matriz só nomeia disciplinas em Ciências da Natureza (Física, Química,
Biologia). Nas outras áreas, a disciplina de cada conteúdo ou tópico é
atribuída aqui (DISCIPLINAS_*) e o que a matriz não cobre (ex.: Ética,
Teoria do conhecimento, Gramática de língua estrangeira) entra como
complemento, marcado com "origem": "complemento".
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pdfplumber

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "enem" / "taxonomia.json"

AREAS = {
    "1": ("LC", "Linguagens, Códigos e suas Tecnologias"),
    "2": ("MT", "Matemática e suas Tecnologias"),
    "3": ("CN", "Ciências da Natureza e suas Tecnologias"),
    "4": ("CH", "Ciências Humanas e suas Tecnologias"),
}

# Linguagens: disciplina(s) de cada conteúdo (pelo nome curto).
DISCIPLINAS_LC = {
    "Estudo do texto": ["Língua Portuguesa", "Língua Inglesa", "Língua Espanhola"],
    "Estudo das práticas corporais": ["Educação Física"],
    "Produção e recepção de textos artísticos": ["Artes"],
    "Estudo do texto literário": ["Língua Portuguesa", "Língua Inglesa", "Língua Espanhola"],
    "Estudo dos aspectos linguísticos em diferentes textos": ["Língua Portuguesa", "Língua Inglesa", "Língua Espanhola"],
    "Estudo do texto argumentativo, seus gêneros e recursos linguísticos": ["Língua Portuguesa", "Língua Inglesa", "Língua Espanhola"],
    "Estudo dos aspectos linguísticos da língua portuguesa": ["Língua Portuguesa"],
    "Estudo dos gêneros digitais": ["Língua Portuguesa", "Língua Inglesa", "Língua Espanhola"],
}
# Humanas: disciplina(s) de cada tópico "o", pelo começo do texto.
DISCIPLINAS_CH = [
    ("Cultura Material e imaterial", ["História", "Sociologia"]),
    ("A Conquista da América", ["História"]),
    ("História cultural dos povos africanos", ["História", "Sociologia"]),
    ("História dos povos indígenas", ["História", "Sociologia"]),
    ("Movimentos culturais no mundo ocidental", ["História", "Filosofia", "Sociologia"]),
    ("Cidadania e democracia na Antiguidade", ["História", "Filosofia", "Sociologia"]),
    ("Revoluções sociais e políticas na Europa Moderna", ["História", "Filosofia"]),
    ("Formação territorial brasileira", ["Geografia", "História"]),
    ("As lutas pela conquista da independência", ["História"]),
    ("Grupos sociais em conflito no Brasil imperial", ["História"]),
    ("O desenvolvimento do pensamento liberal", ["Filosofia", "Sociologia", "História"]),
    ("Políticas de colonização, migração", ["Geografia", "História"]),
    ("A atuação dos grupos sociais e os grandes processos revolucionários", ["História"]),
    ("Geopolítica e conflitos entre os séculos XIX e XX", ["História", "Geografia"]),
    ("Os sistemas totalitários", ["História"]),
    ("Conflitos político-culturais pós-Guerra Fria", ["Geografia", "História"]),
    ("A luta pela conquista de direitos", ["Sociologia", "História", "Filosofia"]),
    ("Vida urbana", ["Geografia", "Sociologia"]),
    ("Diferentes formas de organização da produção", ["História", "Sociologia"]),
    ("Economia agro-exportadora brasileira", ["História", "Geografia"]),
    ("Revolução Industrial", ["História", "Geografia", "Sociologia"]),
    ("A industrialização brasileira", ["Geografia", "História", "Sociologia"]),
    ("A globalização e as novas tecnologias", ["Geografia", "Sociologia"]),
    ("Produção e transformação dos espaços agrários", ["Geografia"]),
    ("Relação homem-natureza", ["Geografia"]),
    ("As questões ambientais contemporâneas", ["Geografia"]),
    ("Origem e evolução do conceito de sustentabilidade", ["Geografia", "Sociologia"]),
    ("Estrutura interna da terra", ["Geografia"]),
    ("Situação geral da atmosfera", ["Geografia"]),
    ("Os grandes domínios da vegetação", ["Geografia"]),
    ("Projeções cartográficas", ["Geografia"]),
]

# O que a matriz não cobre e aparece nas provas. Tópicos curtos, de livro
# didático; cada um fica marcado como complemento.
COMPLEMENTOS = {
    "CH": {
        "Filosofia: períodos e temas (complemento)": (["Filosofia"], [
            "Filosofia antiga", "Filosofia medieval", "Filosofia moderna", "Filosofia contemporânea",
            "Ética e moral", "Filosofia política", "Teoria do conhecimento", "Estética",
            "Lógica e argumentação", "Filosofia da ciência", "Filosofia da linguagem"]),
        "Sociologia: conceitos e temas (complemento)": (["Sociologia"], [
            "Cultura, identidade e alteridade", "Indústria cultural e meios de comunicação",
            "Trabalho e sociedade", "Desigualdade e estratificação social", "Relações étnico-raciais",
            "Gênero e sexualidade", "Movimentos sociais", "Poder, Estado e cidadania",
            "Ciência, tecnologia e sociedade", "Teoria sociológica clássica"]),
        "Geografia: conceitos e população (complemento)": (["Geografia"], [
            "Conceitos geográficos (espaço, lugar, território, paisagem, região)",
            "População e demografia", "Fontes de energia e matriz energética"]),
        "História: períodos e historiografia (complemento)": (["História"], [
            "Pré-história e Antiguidade oriental", "Grécia e Roma antigas", "Idade Média", "Idade Moderna",
            "América pré-colombiana", "Brasil Colônia", "Brasil Império", "Brasil República (1889-1930)",
            "Era Vargas", "República populista (1945-1964)", "Ditadura militar (1964-1985)",
            "Redemocratização e Nova República", "Historiografia e fontes históricas"]),
    },
    "LC": {
        "Língua estrangeira: leitura e gramática (complemento)": (["Língua Inglesa", "Língua Espanhola"], [
            "Compreensão global do texto", "Vocabulário e expressões em contexto",
            "Gramática em contexto", "Aspectos culturais e interculturalidade"]),
        "Gramática da língua portuguesa (complemento)": (["Língua Portuguesa"], [
            "Morfologia (classes de palavras)", "Sintaxe e pontuação", "Semântica e sentido das palavras",
            "Concordância, regência e colocação", "Ortografia e acentuação"]),
        "Funções da linguagem e comunicação (complemento)": (["Língua Portuguesa"], [
            "Funções da linguagem", "Elementos da comunicação", "Intertextualidade",
            "Linguagem verbal e não verbal"]),
    },
}


def texto_matriz() -> str:
    pdfs = sorted(RAIZ.glob(".cache/enem/*/microdados/matriz_referencia_enem.pdf"))
    if not pdfs:
        raise SystemExit("Matriz não encontrada: rode scripts/importar_microdados.py antes.")
    with pdfplumber.open(pdfs[-1]) as pdf:
        t = "\n".join(p.extract_text() or "" for p in pdf.pages)
    i = t.index("Objetos de conhecimento associados às Matrizes de Referência")
    return t[i:]


def limpar(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" .;:")
    s = s.replace("idéia", "ideia").replace("protéica", "proteica").replace("auto-imunes", "autoimunes")
    return s


def dividir_lista(s: str, seps: str = ";,") -> list[str]:
    """Divide pelos separadores fora de parênteses."""
    partes, nivel, atual = [], 0, ""
    for ch in s:
        nivel += ch == "("
        nivel -= ch == ")"
        if ch in seps and nivel == 0:
            partes.append(atual)
            atual = ""
        else:
            atual += ch
    partes.append(atual)
    return [limpar(p) for p in partes if limpar(p)]


def ler() -> dict:
    t = texto_matriz()
    # junta as linhas quebradas e separa por marcador
    # índices das fórmulas saem numa linha à parte no PDF
    t = re.sub(r"H , O ,\s*2 2\s*N , Cl , NH , H O, HCl, CH \.", "H₂, O₂, N₂, Cl₂, NH₃, H₂O, HCl, CH₄.", t)
    t = re.sub(r"Forças\s*2 2 3 2 4\s*intermoleculares", "Forças intermoleculares", t)
    areas: dict = {}
    area = disc = None
    for bloco in re.split(r"\n(?=\d\. |\d\.\d |• |o )", t):
        bloco = bloco.strip()
        m = re.match(r"(\d)\. (.+)", bloco)
        if m and "\n" not in bloco.strip():
            area = AREAS[m.group(1)][0]
            areas[area] = []
            disc = None
            continue
        m = re.match(r"\d\.\d (\w+)", bloco)
        if m:
            disc = m.group(1)
            continue
        if bloco.startswith("• "):
            corpo = bloco[2:].replace("\n", " ")
            # nome: até " - ", " – " ou ":" (o primeiro que vier)
            corte = re.search(r" [-–] |: ", corpo)
            nome = limpar(corpo[:corte.start()]) if corte else limpar(corpo)
            resto = corpo[corte.end():] if corte else ""
            if area == "LC" and ":" in nome:  # "Estudo do texto: as sequências..."
                nome = nome.split(":")[0]
            if area == "LC":
                nome = max((k for k in DISCIPLINAS_LC if corpo.startswith(k)), key=len, default=nome)
                desc = re.split(r" [-–] ", corpo, maxsplit=1)
                if nome == "Produção e recepção de textos artísticos":
                    topicos = ["Artes Visuais", "Teatro", "Música", "Dança",
                               "Conteúdos estruturantes das linguagens artísticas",
                               "Inclusão, diversidade e multiculturalidade nas produções artísticas"]
                else:
                    # no texto argumentativo a lista é separada por vírgulas
                    seps = ";," if nome.startswith("Estudo do texto argumentativo") else ";"
                    topicos = dividir_lista(desc[1], seps) if len(desc) > 1 else []
                discs = DISCIPLINAS_LC.get(nome, ["Língua Portuguesa"])
            elif area == "MT":
                topicos = dividir_lista(resto, ";" if ";" in resto else ",")
                discs = ["Matemática"]
            elif area == "CN":
                topicos = [limpar(f) for f in re.split(r"(?<=[a-zà-ú)\d₀-₉])\. (?=[A-ZÁÉÍÓÚÂÊ])", resto) if limpar(f)]
                discs = [disc]
            else:  # CH: tópicos vêm nos itens "o"
                topicos, discs = [], []
            areas[area].append({"nome": nome, "disciplinas": discs, "origem": "matriz",
                                "texto_matriz": limpar(corpo), "topicos": [{"nome": x, "origem": "matriz"} for x in topicos]})
        elif bloco.startswith("o ") and area == "CH":
            texto = limpar(bloco[2:].replace("\n", " "))
            discs = next((d for k, d in DISCIPLINAS_CH if texto.startswith(k)), None)
            if discs is None:
                raise SystemExit(f"Tópico de Humanas sem disciplina definida: {texto[:60]}")
            atual = areas[area][-1]
            curto = re.split(r"[.:;](?: |$)", texto, maxsplit=1)[0]
            atual["topicos"].append({"nome": limpar(curto), "texto_matriz": texto, "origem": "matriz", "disciplinas": discs})
            atual["disciplinas"] = sorted(set(atual["disciplinas"]) | set(discs))
    for sigla, comps in COMPLEMENTOS.items():
        for nome, (discs, topicos) in comps.items():
            areas[sigla].append({"nome": nome, "disciplinas": discs, "origem": "complemento",
                                 "topicos": [{"nome": x, "origem": "complemento"} for x in topicos]})
    return areas


def main() -> None:
    areas = ler()
    saida = {
        "fonte": "INEP, Matriz de Referência do ENEM: Objetos de conhecimento associados às Matrizes de Referência",
        "criterio": "Classificar pelo que a resolução exige (conceitos, procedimentos, atitudes, habilidades), não pelo contexto do enunciado.",
        "areas": {sigla: {"nome": AREAS[n][1], "conteudos": areas[sigla]}
                  for n, (sigla, _) in AREAS.items()},
    }
    DESTINO.write_text(json.dumps(saida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for sigla, a in saida["areas"].items():
        print(sigla, len(a["conteudos"]), "conteúdos,", sum(len(c["topicos"]) for c in a["conteudos"]), "tópicos")


if __name__ == "__main__":
    main()
