#!/usr/bin/env python3
"""Migra a classificação antiga (disciplinas + conteúdos livres) para a
taxonomia da Matriz de Referência (data/enem/taxonomia.json).

    python scripts/migrar_classificacao.py

Cada rótulo antigo vira (conteúdo, tópico) da taxonomia pelo MAPA abaixo; o
resultado fica marcado "provisorio": true, porque o rótulo antigo não diz o
tópico exato nem o subtópico. A classificação definitiva vem da ficha de
cada questão (data/enem/fichas/), que substitui esta.
"""
from __future__ import annotations

import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "data" / "enem" / "classificacao"
TAX = json.loads((RAIZ / "data" / "enem" / "taxonomia.json").read_text(encoding="utf-8"))

# rótulo antigo -> [(início do nome do conteúdo, início do nome do tópico ou None)]
MAPA = {
    # Linguagens
    "Interpretação de texto": [("Estudo do texto", "modos de organização")],
    "Gêneros textuais": [("Estudo do texto argumentativo", "função sociocomunicativa do gênero")],
    "Argumentação": [("Estudo do texto argumentativo", "formas de apresentação")],
    "Coesão e progressão textual": [("Estudo dos aspectos linguísticos da língua portuguesa", "uso dos recursos linguísticos em processo de coesão")],
    "Comunicação e informação": [("Estudo dos gêneros digitais", "a função social")],
    "Funções da linguagem": [("Funções da linguagem e comunicação", "Funções da linguagem")],
    "Intertextualidade": [("Funções da linguagem e comunicação", "Intertextualidade")],
    "Gramática": [("Gramática da língua portuguesa", None)],
    "Recursos expressivos e figuras de linguagem": [("Estudo dos aspectos linguísticos em diferentes textos", None)],
    "Variação e diversidade linguística": [("Estudo dos aspectos linguísticos da língua portuguesa", "uso dos recursos linguísticos em relação ao contexto")],
    "Literatura (prosa)": [("Estudo do texto literário", "associações entre concepções artísticas")],
    "Literatura (poesia)": [("Estudo do texto literário", "associações entre concepções artísticas")],
    "Artes visuais": [("Produção e recepção de textos artísticos", "Artes Visuais")],
    "Música": [("Produção e recepção de textos artísticos", "Música")],
    "Dança": [("Produção e recepção de textos artísticos", "Dança")],
    "Arte e cultura popular": [("Produção e recepção de textos artísticos", "Inclusão, diversidade")],
    "Esporte e sociedade": [("Estudo das práticas corporais", "o esporte")],
    "Saúde e práticas corporais": [("Estudo das práticas corporais", "exercício físico e saúde")],
    # Matemática
    "Aritmética e operações": [("Conhecimentos numéricos", "operações em conjuntos numéricos")],
    "Razão, proporção e escala": [("Conhecimentos numéricos", "razões e proporções")],
    "Porcentagem e matemática financeira": [("Conhecimentos numéricos", "porcentagem e juros")],
    "Sequências e progressões": [("Conhecimentos numéricos", "sequências e progressões")],
    "Probabilidade e combinatória": [("Conhecimentos de estatística e probabilidade", "noções de probabilidade")],
    "Raciocínio lógico": [("Conhecimentos numéricos", None)],
    "Estatística": [("Conhecimentos de estatística e probabilidade", "medidas de tendência central")],
    "Leitura de gráficos e tabelas": [("Conhecimentos de estatística e probabilidade", "representação e análise de dados")],
    "Grandezas e medidas": [("Conhecimentos geométricos", "grandezas, unidades de medida e escalas")],
    "Geometria plana": [("Conhecimentos geométricos", "características das figuras geométricas")],
    "Geometria espacial": [("Conhecimentos geométricos", "comprimentos, áreas e volumes")],
    "Trigonometria": [("Conhecimentos geométricos", "trigonometria do ângulo agudo")],
    "Geometria analítica": [("Conhecimentos algébricos/geométricos", "plano cartesiano")],
    "Funções": [("Conhecimentos algébricos", "gráficos e funções")],
    "Logaritmos e exponenciais": [("Conhecimentos algébricos", "funções algébricas")],
    "Álgebra (equações e sistemas)": [("Conhecimentos algébricos", "equações e inequações")],
    "Matrizes": [("Conhecimentos algébricos/geométricos", "paralelismo e perpendicularidade, sistemas")],
    # Física
    "Cinemática": [("O movimento, o equilíbrio", "Descrições do movimento")],
    "Dinâmica": [("O movimento, o equilíbrio", "Leis de Newton")],
    "Energia": [("Energia, trabalho e potência", None)],
    "Hidrostática": [("O movimento, o equilíbrio", "Princípios de Pascal")],
    "Hidrodinâmica": [("O movimento, o equilíbrio", "A hidrostática")],
    "Eletrodinâmica": [("Fenômenos Elétricos e Magnéticos", "Relações entre grandezas elétricas")],
    "Eletromagnetismo": [("Fenômenos Elétricos e Magnéticos", "Campo magnético")],
    "Ondulatória": [("Oscilações, ondas, óptica e radiação", "Fenômenos ondulatórios")],
    "Óptica": [("Oscilações, ondas, óptica e radiação", "Óptica geométrica")],
    "Radiação e física moderna": [("Oscilações, ondas, óptica e radiação", None)],
    "Termologia": [("O calor e os fenômenos térmicos", None)],
    "Modelos atômicos": [("Transformações Químicas", "Natureza elétrica da matéria")],
    # Química
    "Estequiometria": [("Representação das transformações químicas", "Cálculos estequiométricos")],
    "Gases": [("Transformações Químicas", "Sistemas Gasosos")],
    "Soluções": [("Água", "Concentração das soluções")],
    "Ácidos e bases": [("Água", "Conceitos de ácidos e base")],
    "Funções inorgânicas": [("Água", "Ácidos, Bases, Sais e Óxidos")],
    "Ligações químicas e polaridade": [("Materiais, suas propriedades e usos", "Polaridade de moléculas")],
    "Propriedades da matéria": [("Materiais, suas propriedades e usos", "Propriedades de materiais")],
    "Separação de misturas": [("Materiais, suas propriedades e usos", "Misturas: tipos e métodos de separação")],
    "Termoquímica": [("Transformações Químicas e Energia", "Entalpia")],
    "Eletroquímica e oxirredução": [("Transformações Químicas e Energia", "Reação de oxirredução")],
    "Radioatividade": [("Transformações Químicas e Energia", "Conceitos fundamentais da radioatividade")],
    "Cinética química": [("Dinâmica das Transformações Químicas", None)],
    "Equilíbrio químico": [("Transformação Química e Equilíbrio", None)],
    "Química orgânica": [("Compostos de Carbono", "Principais funções orgânicas")],
    "Química ambiental": [("Relações da Química com as Tecnologias", "Química e ambiente")],
    # Biologia
    "Citologia": [("Moléculas, células e tecidos", "Estrutura e fisiologia celular")],
    "Bioquímica e metabolismo": [("Moléculas, células e tecidos", "Aspectos gerais do metabolismo celular")],
    "Biotecnologia": [("Moléculas, células e tecidos", "Aplicações de biotecnologia")],
    "Genética e biologia molecular": [("Hereditariedade e diversidade da vida", "Princípios básicos")],
    "Imunologia": [("Hereditariedade e diversidade da vida", "Antígenos e anticorpos")],
    "Evolução": [("Origem e evolução da vida", "Teorias de evolução")],
    "Ecologia": [("Ecologia e ciências ambientais", None)],
    "Botânica": [("Identidade dos seres vivos", "Funções vitais dos seres vivos")],
    "Zoologia": [("Identidade dos seres vivos", "Evolução e padrões anatômicos")],
    "Diversidade dos seres vivos": [("Identidade dos seres vivos", "Sistemática")],
    "Fisiologia animal": [("Identidade dos seres vivos", "Funções vitais dos seres vivos")],
    "Fisiologia humana": [("Identidade dos seres vivos", "Embriologia, anatomia e fisiologia humana")],
    "Reprodução e embriologia": [("Identidade dos seres vivos", "Embriologia, anatomia e fisiologia humana")],
    "Saúde e parasitologia": [("Qualidade de vida das populações humanas", "Principais doenças")],
    # Humanas
    "Questões ambientais": [("Os domínios naturais", "As questões ambientais contemporâneas")],
    "Clima": [("Os domínios naturais", "Situação geral da atmosfera")],
    "Geologia e relevo": [("Os domínios naturais", "Estrutura interna da terra")],
    "Cartografia e leitura de mapas": [("Representação espacial", "Projeções cartográficas")],
    "Geografia agrária": [("Características e transformações das estruturas produtivas", "Produção e transformação dos espaços agrários")],
    "Geografia urbana": [("Formas de organização social", "Vida urbana")],
    "Economia e globalização": [("Características e transformações das estruturas produtivas", "A globalização")],
    "Geopolítica": [("Formas de organização social", "Conflitos político-culturais pós-Guerra Fria")],
    "Formação territorial": [("Formas de organização social", "Formação territorial brasileira")],
    "População e demografia": [("Geografia: conceitos e população", "População e demografia")],
    "Conceitos geográficos (lugar, território)": [("Geografia: conceitos e população", "Conceitos geográficos")],
    "Patrimônio cultural": [("Diversidade cultural", "Cultura Material e imaterial")],
    "Escravidão e diáspora africana": [("Diversidade cultural", "A Conquista da América")],
    "História da África": [("Diversidade cultural", "História cultural dos povos africanos")],
    "América pré-colombiana": [("História: períodos e historiografia", "América pré-colombiana")],
    "História antiga": [("História: períodos e historiografia", "Grécia e Roma antigas")],
    "História medieval": [("História: períodos e historiografia", "Idade Média")],
    "História moderna": [("História: períodos e historiografia", "Idade Moderna")],
    "Iluminismo": [("Formas de organização social", "Revoluções sociais e políticas na Europa Moderna")],
    "História contemporânea": [("Formas de organização social", "Geopolítica e conflitos entre os séculos XIX e XX")],
    "História da América": [("Formas de organização social", "As lutas pela conquista da independência")],
    "História do Brasil: Colônia": [("História: períodos e historiografia", "Brasil Colônia")],
    "História do Brasil: Império": [("Formas de organização social", "Grupos sociais em conflito no Brasil imperial")],
    "História do Brasil: República": [("História: períodos e historiografia", "Brasil República")],
    "História do Brasil: Era Vargas": [("História: períodos e historiografia", "Era Vargas")],
    "História do Brasil: Ditadura militar": [("História: períodos e historiografia", "Ditadura militar")],
    "Historiografia": [("História: períodos e historiografia", "Historiografia")],
    "Filosofia antiga": [("Filosofia: períodos e temas", "Filosofia antiga")],
    "Filosofia medieval": [("Filosofia: períodos e temas", "Filosofia medieval")],
    "Filosofia moderna": [("Filosofia: períodos e temas", "Filosofia moderna")],
    "Filosofia contemporânea": [("Filosofia: períodos e temas", "Filosofia contemporânea")],
    "Ética": [("Filosofia: períodos e temas", "Ética e moral")],
    "Filosofia política": [("Filosofia: períodos e temas", "Filosofia política")],
    "Teoria do conhecimento": [("Filosofia: períodos e temas", "Teoria do conhecimento")],
    "Lógica e argumentação": [("Filosofia: períodos e temas", "Lógica e argumentação")],
    "Cultura e identidade": [("Sociologia: conceitos e temas", "Cultura, identidade")],
    "Cultura e indústria cultural": [("Sociologia: conceitos e temas", "Indústria cultural")],
    "Mundo do trabalho": [("Sociologia: conceitos e temas", "Trabalho e sociedade")],
    "Desigualdade e estratificação social": [("Sociologia: conceitos e temas", "Desigualdade")],
    "Relações étnico-raciais": [("Sociologia: conceitos e temas", "Relações étnico-raciais")],
    "Gênero": [("Sociologia: conceitos e temas", "Gênero")],
    "Movimentos sociais": [("Sociologia: conceitos e temas", "Movimentos sociais")],
    "Política, poder e cidadania": [("Sociologia: conceitos e temas", "Poder, Estado e cidadania")],
    "Cidadania e direitos": [("Formas de organização social", "A luta pela conquista de direitos")],
    "Ciência, tecnologia e sociedade": [("Sociologia: conceitos e temas", "Ciência, tecnologia")],
}

# o mesmo rótulo em outra disciplina tem outro lugar na taxonomia
POR_DISCIPLINA = {
    ("Língua Inglesa", "Variação e diversidade linguística"): [("Língua estrangeira", "Aspectos culturais")],
    ("Língua Espanhola", "Variação e diversidade linguística"): [("Língua estrangeira", "Aspectos culturais")],
    ("Língua Inglesa", "Gramática"): [("Língua estrangeira", "Gramática em contexto")],
    ("Língua Espanhola", "Gramática"): [("Língua estrangeira", "Gramática em contexto")],
    ("Língua Inglesa", "Coesão e progressão textual"): [("Estudo dos aspectos linguísticos em diferentes textos", None)],
    ("Língua Espanhola", "Coesão e progressão textual"): [("Estudo dos aspectos linguísticos em diferentes textos", None)],
    ("Química", "Bioquímica e metabolismo"): [("Compostos de Carbono", "Proteínas e enzimas")],
    ("Química", "Razão, proporção e escala"): [("Representação das transformações químicas", "Aspectos quantitativos")],
    ("Química", "Ecologia"): [("Relações da Química com as Tecnologias", "Química e ambiente")],
    ("Física", "Química ambiental"): [("O calor e os fenômenos térmicos", "Aplicações e fenômenos térmicos")],
    ("Física", "Razão, proporção e escala"): [("Conhecimentos básicos e fundamentais", "Noções de ordem de grandeza")],
    ("Sociologia", "Questões ambientais"): [("Os domínios naturais", "Origem e evolução do conceito de sustentabilidade")],
    ("Artes", "Comunicação e informação"): [("Produção e recepção de textos artísticos", "Artes Visuais")],
}


def achar(area: str, conteudo: str, topico: str | None, discs: list[str]):
    cands = [c for s, a in TAX["areas"].items() for c in a["conteudos"] if c["nome"].startswith(conteudo)]
    if not cands:
        raise SystemExit(f"conteúdo não encontrado: {conteudo}")
    c = cands[0]
    t = None
    if topico:
        t = next((x for x in c["topicos"] if x["nome"].startswith(topico)), None)
        if t is None:
            raise SystemExit(f"tópico não encontrado em {c['nome']}: {topico}")
    # disciplina: a da questão que o conteúdo/tópico admite
    admitidas = (t or {}).get("disciplinas") or c["disciplinas"]
    disc = next((d for d in discs if d in admitidas), admitidas[0])
    return {"disciplina": disc, "conteudo": c["nome"], "topico": t["nome"] if t else None, "subtopico": None}


def main() -> None:
    faltam = set()
    for arq in sorted(PASTA.glob("*.json")):
        d = json.loads(arq.read_text(encoding="utf-8"))
        for num, v in d["questoes"].items():
            if "classificacao" in v and not v.get("provisorio"):
                continue  # já classificada na taxonomia (ficha)
            discs = v.get("disciplinas") or []
            itens = []
            for rot in v.get("conteudos") or []:
                regra = next((POR_DISCIPLINA[(d, rot)] for d in discs if (d, rot) in POR_DISCIPLINA), MAPA.get(rot))
                if regra is None:
                    faltam.add(rot)
                    continue
                for cont, top in regra:
                    item = achar(None, cont, top, discs)
                    if item not in itens:
                        itens.append(item)
            v["classificacao"] = itens
            v["provisorio"] = True
        d["criterio"] = TAX["criterio"]
        d.pop("disciplinas_validas", None)
        arq.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if faltam:
        raise SystemExit(f"rótulos sem mapa: {sorted(faltam)}")
    print("classificações migradas (provisórias)")


if __name__ == "__main__":
    main()
