#!/usr/bin/env python3
"""Extrai as questões de UMA prova regular do ENEM (caderno impresso do INEP).

Para cada questão salva o texto (enunciado + alternativas) e o gabarito.
Quando a questão tem elementos que o texto não representa bem (imagem,
gráfico, desenho, tabela ou fórmula), salva também a imagem da questão
recortada do PDF oficial, que passa a ser a referência fiel.

Uso (uma prova por vez):
    pip install pdfplumber pypdf
    python scripts/extrair_prova_regular.py --ano 2023 --dia 2 --caderno 7

Saída:
    data/enem/<ano>/D<dia>_CD<caderno>.json
    data/enem/<ano>/img/D<dia>_CD<caderno>_Q<numero>.png   (só quando há visual)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import statistics
import sys
from pathlib import Path

try:
    import pdfplumber
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("Instale as dependências: pip install pdfplumber pypdf")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import (  # noqa: E402
    BASE_DOWNLOAD, CACHE, RAIZ, baixar, contexto_ssl, ler_gabarito, normalizar_resposta,
)

logging.getLogger("pdfminer").setLevel(logging.ERROR)

SAIDA = RAIZ / "data" / "enem"
RESOLUCAO = 150  # dpi das imagens recortadas

# Geometria do caderno do ENEM (pontos PDF; página 567 x 780). Medida em 2023.
TOPO, BASE = 60.0, 740.0            # abaixo do cabeçalho da página, acima do rodapé
X_ESQ, X_DIR = 25.0, 545.0          # margens laterais do conteúdo
DIVISORIA = (280.0, 288.0)          # faixa entre as colunas (linha divisória ou corredor vazio)
COM_LINHA_DIVISORIA = True          # 2023: linha vertical; 2024: só espaço em branco
MARGEM = 2.0
TAMANHO_MIN_CARACTERE = 3.5         # ignora microtexto de segurança (2024: corpo 1,2–1,8)

# Perfis medidos em cada formato de caderno. Novo formato = novo perfil.
PERFIS = {
    "2023": {"largura": 566.9, "TOPO": 60.0, "BASE": 740.0, "X_ESQ": 25.0, "X_DIR": 545.0,
             "DIVISORIA": (280.0, 288.0), "COM_LINHA_DIVISORIA": True},
    "2024": {"largura": 636.6, "TOPO": 95.0, "BASE": 780.0, "X_ESQ": 50.0, "X_DIR": 578.0,
             "DIVISORIA": (311.5, 324.5), "COM_LINHA_DIVISORIA": False},
}


CORREDOR_ADAPTATIVO = False  # 2025+: o corredor entre colunas muda de página para página


def configurar_geometria(pdf, ano: int | None = None) -> str:
    """Escolhe o perfil pelo tamanho da página e ajusta as constantes."""
    global TOPO, BASE, X_ESQ, X_DIR, DIVISORIA, COM_LINHA_DIVISORIA, CORREDOR_ADAPTATIVO
    CORREDOR_ADAPTATIVO = bool(ano and ano >= 2025)
    largura = pdf.pages[min(1, len(pdf.pages) - 1)].width
    nome, perfil = min(PERFIS.items(), key=lambda kv: abs(kv[1]["largura"] - largura))
    if abs(perfil["largura"] - largura) > 3:
        sys.exit(f"Formato de página desconhecido (largura {largura:.1f}); é preciso medir um perfil novo.")
    TOPO, BASE, X_ESQ, X_DIR = perfil["TOPO"], perfil["BASE"], perfil["X_ESQ"], perfil["X_DIR"]
    DIVISORIA, COM_LINHA_DIVISORIA = perfil["DIVISORIA"], perfil["COM_LINHA_DIVISORIA"]
    return nome


class Documento:
    """PDF com páginas sem o microtexto de segurança (caracteres minúsculos)."""

    def __init__(self, pdf):
        self.pdf = pdf
        self.pages = [p.filter(lambda o: o.get("object_type") != "char"
                               or o.get("size", 10) >= TAMANHO_MIN_CARACTERE) for p in pdf.pages]

AREAS = {
    (1, "LC"): range(1, 46), (1, "CH"): range(46, 91),
    (2, "CN"): range(91, 136), (2, "MT"): range(136, 181),
}
# Nomes oficiais das áreas de conhecimento do ENEM.
NOMES_AREA = {
    "LC": "Linguagens, Códigos e suas Tecnologias",
    "CH": "Ciências Humanas e suas Tecnologias",
    "CN": "Ciências da Natureza e suas Tecnologias",
    "MT": "Matemática e suas Tecnologias",
}
APLICACOES = {
    # aplicação: (trecho do nome do arquivo no INEP até 2024, rótulo)
    "regular": ("impresso", "Aplicação regular"),
    "reaplicacao": ("reaplicacao_PPL", "Reaplicação"),
    # 2025: aplicação própria para Belém, Ananindeua e Marituba (outra prova)
    "belem": (None, "Aplicação Belém, Ananindeua e Marituba"),
}
# Desde 2025 todas as aplicações usam "impresso" e os dias seguem em
# sequência: regular D1/D2, Belém D3/D4, reaplicação D5/D6.
DESLOCAMENTO_DIA_2025 = {"regular": 0, "belem": 2, "reaplicacao": 4}


def arquivos(ano: int, aplicacao: str, dia: int, caderno: int) -> tuple[str, str]:
    """Nomes (prova, gabarito) no site do INEP. `dia` é o dia lógico (1 ou 2)."""
    if ano >= 2025:
        trecho, d = "impresso", dia + DESLOCAMENTO_DIA_2025[aplicacao]
    else:
        trecho, d = APLICACOES[aplicacao][0], dia
        if trecho is None:
            sys.exit(f"Aplicação {aplicacao!r} não existe em {ano}.")
    return f"{ano}_PV_{trecho}_D{d}_CD{caderno}.pdf", f"{ano}_GB_{trecho}_D{d}_CD{caderno}.pdf"
SIMBOLOS_FORMULA = set("√∑∫∞≤≥≠≈±×÷πΔ∆θλμσΩωαβγ⋅·∙")
FONTES_FORMULA = ("symbol", "math", "cambria", "euclid", "mt extra", "mtextra")
FONTE_ALTERNATIVA = "bundesbahnpi"   # fonte dos marcadores (A)...(E)


def area_da_questao(dia: int, numero: int) -> str:
    for (d, area), faixa in AREAS.items():
        if d == dia and numero in faixa:
            return area
    return "?"


# --------------------------------------------------------------- segmentação
def corredor_da_pagina(pagina) -> tuple[float, float]:
    """Corredor medido na página (2025+): a faixa vertical perto do centro
    com menos letras. Linhas de largura total cobrem todos os x por igual e
    não mudam onde fica o mínimo."""
    meio = (DIVISORIA[0] + DIVISORIA[1]) / 2
    xs = range(int(meio) - 30, int(meio) + 31)
    cont = {x: 0 for x in xs}
    for c in pagina.chars:
        if c["text"].strip() and TOPO <= c["top"] < BASE:
            for x in xs:
                if c["x0"] <= x + 0.5 and c["x1"] >= x - 0.5:
                    cont[x] += 1
    minimo = min(cont.values())
    # maior sequência de x com a contagem mínima, a mais próxima do centro
    seqs, atual = [], []
    for x in xs:
        if cont[x] == minimo:
            atual.append(x)
        elif atual:
            seqs.append(atual); atual = []
    if atual:
        seqs.append(atual)
    melhor = max(seqs, key=lambda q: (len(q), -abs((q[0] + q[-1]) / 2 - meio)))
    if len(melhor) < 4:
        return DIVISORIA
    return (melhor[0] - 0.5, melhor[-1] + 0.5)


def zonas_por_corredor(pagina) -> list[tuple[float, float, float, float]]:
    """Sem linha divisória: tudo o que atravessa o corredor entre as colunas
    (linha de texto ou figura de largura total) marca uma faixa de largura
    total; o resto da página é lido em duas colunas."""
    g0, g1 = corredor_da_pagina(pagina) if CORREDOR_ADAPTATIVO else DIVISORIA
    bloqueios = []
    for c in pagina.chars:
        # folga de 1,5 pt: texto alinhado à direita termina encostado no corredor
        if c["text"].strip() and TOPO <= c["top"] < BASE and g0 + 1.5 < (c["x0"] + c["x1"]) / 2 < g1 - 1.5:
            bloqueios.append((c["top"] - 2, c["bottom"] + 2))
    for o in pagina.rects + pagina.curves + pagina.images + pagina.lines:
        # só é largura total se avançar bem nas duas colunas (imagens podem
        # ter a caixa maior que a parte visível)
        if o["x0"] < g0 - 20 and o["x1"] > g1 + 20 and o["bottom"] > TOPO and o["top"] < BASE \
                and o["x1"] < X_DIR + 5:
            bloqueios.append((o["top"] - 2, o["bottom"] + 2))
    bloqueios.sort()
    faixas: list[list[float]] = []
    for t, b in bloqueios:
        if faixas and t - faixas[-1][1] < 25:  # junta linhas da mesma faixa larga
            faixas[-1][1] = max(faixas[-1][1], b)
        else:
            faixas.append([t, b])
    # Questão de largura total: a faixa larga começa no cabeçalho dela, não
    # alguns pontos abaixo (senão o topo do cabeçalho fica na questão anterior).
    topos = [h["top"] for h in cabecalhos(pagina)]
    for f in faixas:
        perto = [t for t in topos if f[0] - 14 <= t < f[0] + 2]
        if perto:
            f[0] = min(perto) - 3
    meio = (g0 + g1) / 2  # cada coluna fica com metade do corredor
    g0 = g1 = meio
    zonas, y = [], TOPO
    for t, b in faixas:
        t, b = max(TOPO, t), min(BASE, b)
        if t - y > 12:
            zonas += [(X_ESQ, y, g0, t), (g1, y, X_DIR, t)]
            inicio = t
        else:
            inicio = y  # sobra estreita acima da faixa larga: pertence a ela
        zonas.append((X_ESQ, inicio, X_DIR, b))
        y = b
    if BASE - y > 12:
        zonas += [(X_ESQ, y, g0, BASE), (g1, y, X_DIR, BASE)]
    return zonas


def zonas_da_pagina(pagina) -> list[tuple[float, float, float, float]]:
    if not COM_LINHA_DIVISORIA:
        return zonas_por_corredor(pagina)
    """Retângulos (x0, topo, x1, base) em ordem de leitura. Onde há a linha
    divisória vertical, a faixa é lida como duas colunas; fora dela, largura
    total."""
    candidatas = [
        (l["top"], l["bottom"]) for l in pagina.lines
        if DIVISORIA[0] < l["x0"] < DIVISORIA[1] and abs(l["x1"] - l["x0"]) < 1
        and l["bottom"] - l["top"] > 20
    ]

    def atravessa(t: float, b: float) -> bool:
        # Uma divisória de colunas não é cruzada por nada; uma linha vertical
        # de gráfico ou tabela é (ex.: 2023 D2 CD7, página 17).
        objs = pagina.chars + pagina.rects + pagina.curves + [
            l for l in pagina.lines if l["bottom"] - l["top"] < 1.5]
        return any(o["x0"] < DIVISORIA[0] - 1 and o["x1"] > DIVISORIA[1] + 1
                   and o["bottom"] > t and o["top"] < b for o in objs)

    trechos = sorted((t, b) for t, b in candidatas if not atravessa(t, b))
    if not trechos:
        return [(X_ESQ, TOPO, X_DIR, BASE)]
    y0, y1 = min(t for t, _ in trechos), max(b for _, b in trechos)
    # A divisória termina alguns pontos antes da última linha de texto
    # (em 2023: divisória até 730, texto até 733). Se ela vai até perto
    # da margem, a coluna vai até a margem.
    if y0 - TOPO < 20:
        y0 = TOPO
    if BASE - y1 < 20:
        y1 = BASE
    zonas = []
    if y0 - TOPO > 12:
        zonas.append((X_ESQ, TOPO, X_DIR, y0))
    zonas.append((X_ESQ, max(TOPO, y0), DIVISORIA[0], min(BASE, y1)))
    zonas.append((DIVISORIA[1], max(TOPO, y0), X_DIR, min(BASE, y1)))
    if BASE - y1 > 12:
        zonas.append((X_ESQ, y1, X_DIR, BASE))
    return zonas


def _cabecalhos_por_caracteres(pagina) -> list[dict]:
    """"QUESTÃO N" com letras espaçadas (2026: "Q U ES T Ã O 09"): junta os
    caracteres em negrito de cada linha, ignorando os espaços."""
    cs = sorted((c for c in pagina.chars if c["text"].strip() and "bold" in c["fontname"].lower()),
                key=lambda c: (round(c["top"]), c["x0"]))
    linhas: list[list] = []
    for c in cs:
        if linhas and abs(linhas[-1][0]["top"] - c["top"]) < 2:
            linhas[-1].append(c)
        else:
            linhas.append([c])
    achados = []
    for ln in linhas:
        ln.sort(key=lambda c: c["x0"])
        texto = "".join(c["text"] for c in ln)
        for m in re.finditer(r"QUEST[ÃAã]O(\d{2,3})", texto, re.I):
            c0 = ln[m.start()]
            achados.append({"numero": int(m.group(1)), "x0": c0["x0"], "top": c0["top"],
                            "bottom": max(c["bottom"] for c in ln[m.start():m.end()])})
    return achados


def cabecalhos(pagina) -> list[dict]:
    palavras = pagina.extract_words(extra_attrs=["fontname"])
    achados = []
    for i, w in enumerate(palavras[:-1]):
        prox = palavras[i + 1]
        # 2025: a fonte codifica o "Ã" como "ã" ("QUESTãO")
        if w["text"].upper() == "QUESTÃO" and "bold" in w["fontname"].lower() and prox["text"].isdigit():
            achados.append({"numero": int(prox["text"]), "x0": w["x0"], "top": w["top"],
                            "bottom": w["bottom"]})
    vistos = {h["numero"] for h in achados}
    achados += [h for h in _cabecalhos_por_caracteres(pagina) if h["numero"] not in vistos]
    return sorted(achados, key=lambda h: (h["top"], h["x0"]))


RE_TITULO_AREA = re.compile(
    r"^\s*(LINGUAGENS|CIÊNCIAS|MATEMÁTICA)[^\n]*(\n[^\n]*)?Questões de \d+ a \d+[^\n]*\s*$", re.S)


def e_titulo_de_area(texto: str) -> bool:
    """Pedaço que contém só o título de área ("MATEMÁTICA ... Questões de
    136 a 180"), que não pertence a nenhuma questão."""
    t = re.sub(r"\s+", " ", texto).strip()
    return bool(re.fullmatch(r"(LINGUAGENS|CIÊNCIAS|MATEMÁTICA).{0,80}Questões de \d+ a \d+.{0,40}", t))


def e_pagina_de_redacao(pagina) -> bool:
    """Páginas da proposta de redação (no meio do caderno do 1º dia): não
    pertencem a nenhuma questão objetiva."""
    texto = (pagina.extract_text() or "").upper()
    titulo = "INSTRUÇÕES PARA A REDAÇÃO" in texto or "PROPOSTA DE REDAÇÃO" in texto
    return titulo and not cabecalhos(pagina)


def _titulos_por_linhas(pagina) -> list[dict]:
    """Títulos com letras espaçadas (2026: "Q uestõ es de 136 a 180")."""
    achados = []
    linhas = pagina.extract_text_lines(return_chars=True)
    for i, ln in enumerate(linhas):
        sem = ln["text"].replace(" ", "")
        m = re.match(r"Textoparaas?Questões?de(\d+)a(\d+)", sem)
        if m:
            achados.append({"x0": ln["x0"], "top": ln["top"], "texto_base": (int(m.group(1)), int(m.group(2)))})
            continue
        if re.match(r"Questõesde\d+a\d+", sem):
            topo = ln["top"]
            for ac in linhas[max(0, i - 2):i]:  # nome da área logo acima
                if ln["top"] - ac["top"] < 25 and re.match(r"(LINGUAGENS|CIÊNCIAS|MATEMÁTICA)", ac["text"], re.I):
                    topo = ac["top"]
            achados.append({"x0": ln["x0"], "top": topo})
    return achados


def titulos_de_secao(pagina) -> list[dict]:
    """Títulos como "Questões de 01 a 05 (opção espanhol)" ou "MATEMÁTICA E
    SUAS TECNOLOGIAS / Questões de 136 a 180". Encerram a questão anterior."""
    palavras = pagina.extract_words(extra_attrs=["fontname"])
    achados = []
    for i, w in enumerate(palavras[:-2]):
        if w["text"] == "Questões" and palavras[i + 1]["text"] == "de" and palavras[i + 2]["text"].isdigit():
            topo = w["top"]
            # 2025+: "Texto para as Questões de 06 a 10." abre um texto-base
            ant = [p["text"] for p in palavras[max(0, i - 3):i] if abs(p["top"] - w["top"]) < 3]
            if len(ant) == 3 and ant[0] == "Texto" and ant[1] == "para":
                fim = palavras[i + 4]["text"] if i + 4 < len(palavras) else palavras[i + 2]["text"]
                achados.append({"x0": palavras[i - 3]["x0"], "top": topo,
                                "texto_base": (int(palavras[i + 2]["text"]), int(re.sub(r"\D", "", fim) or 0))})
                continue
            # inclui o nome da área em maiúsculas logo acima, se houver
            acima = [p for p in palavras if w["top"] - 30 <= p["top"] < w["top"] - 2
                     and p["text"].isupper() and len(p["text"]) > 2
                     and abs(p["x0"] - w["x0"]) < 260 and "bold" in p["fontname"].lower()]
            if acima:
                topo = min(p["top"] for p in acima)
            achados.append({"x0": w["x0"], "top": topo})
    por_linha = _titulos_por_linhas(pagina)
    for t in por_linha:
        igual = [a for a in achados if abs(a["top"] - t["top"]) < 20 and abs(a["x0"] - t["x0"]) < 60]
        if not igual:
            achados.append(t)
        elif t["top"] < igual[0]["top"]:  # o nome da área acima (em qualquer caixa) começa o título
            igual[0]["top"] = t["top"]
    return achados


def pedaco_vazio(pagina, caixa) -> bool:
    x0, t, x1, b = caixa
    dentro = lambda o: o["x1"] > x0 and o["x0"] < x1 and o["bottom"] > t and o["top"] < b
    tem_texto = any(dentro(c) and c["text"].strip() for c in pagina.chars)
    tem_figura = any(dentro(o) for o in pagina.images + pagina.curves + pagina.rects
                     if (o["x1"] - o["x0"]) > 3 or (o["bottom"] - o["top"]) > 3)
    return not tem_texto and not tem_figura


TEXTOS_BASE: list[dict] = []  # preenchido por segmentar (2025+)


def segmentar(pdf) -> list[dict]:
    """Retorna as questões em ordem de leitura, cada uma com seus pedaços
    (página, retângulo) e a posição dos seus cabeçalhos. Textos-base
    ("Texto para as Questões de 06 a 10") ficam em TEXTOS_BASE."""
    TEXTOS_BASE.clear()
    questoes: list[dict] = []
    atual = None
    for ip, pagina in enumerate(pdf.pages):
        if e_pagina_de_redacao(pagina):
            atual = None  # a questão anterior termina antes da redação
            continue
        heads = cabecalhos(pagina)
        titulos = titulos_de_secao(pagina)
        if not heads and atual is None and not any(t.get("texto_base") for t in titulos):
            continue  # capa / instruções
        zonas = zonas_da_pagina(pagina)

        def zona_de(item) -> int | None:
            """Cada cabeçalho/título vai para UMA zona: a primeira em que cabe
            inteiro; se nenhuma, a primeira que contém o seu topo."""
            cands = [i for i, (x0, t, x1, b) in enumerate(zonas)
                     if x0 - 8 <= item["x0"] <= x1 and t - 2 <= item["top"] < b]
            inteiras = [i for i in cands if item["top"] < zonas[i][3] - 6]
            return (inteiras or cands or [None])[0]

        por_zona: dict[int, list] = {}
        for h in heads:
            por_zona.setdefault(zona_de(h), []).append((h["top"], "questao", h))
        for ti in titulos:
            por_zona.setdefault(zona_de(ti), []).append((ti["top"], "titulo", ti))
        for iz, (x0, t, x1, b) in enumerate(zonas):
            eventos = sorted(por_zona.get(iz, []), key=lambda e: e[0])
            cortes = [t] + [e[0] for e in eventos] + [b]
            for k in range(len(cortes) - 1):
                if k > 0:
                    _, tipo, h = eventos[k - 1]
                    if tipo == "titulo" and h.get("texto_base"):
                        # texto-base: tudo até a próxima questão é dele
                        a, z = h["texto_base"]
                        # o título funciona como cabeçalho (a faixa colorida dele é decoração)
                        cab = {"numero": f"T{a}-{z}", "x0": h["x0"], "top": h["top"] - 5, "bottom": h["top"] + 12}
                        atual = {"numero": f"T{a}-{z}", "texto_base": (a, z), "pedacos": [], "cabecalhos": [(ip, cab)]}
                        TEXTOS_BASE.append(atual)
                    elif tipo == "titulo":
                        atual = None  # título de seção: o que vem até a próxima questão não é de ninguém
                        continue
                    else:
                        atual = {"numero": h["numero"], "pedacos": [], "cabecalhos": []}
                        atual["cabecalhos"].append((ip, h))
                        questoes.append(atual)
                if atual is not None and cortes[k + 1] - cortes[k] > 4:
                    caixa = (x0, cortes[k], x1, cortes[k + 1])
                    if k == 0 and "texto_base" not in atual and e_titulo_de_area(pagina.crop(caixa).extract_text() or ""):
                        continue
                    if k == 0 and pedaco_vazio(pagina, caixa):
                        continue  # sobra sem conteúdo antes de um título ou no topo da coluna
                    # margem só antes de um cabeçalho/título (fim de zona não tem)
                    antes_de_cabecalho = k + 1 < len(cortes) - 1
                    fim = cortes[k + 1] - (MARGEM if antes_de_cabecalho or b >= BASE else 0)
                    atual["pedacos"].append((ip, (x0, cortes[k] - MARGEM if k else cortes[k], x1, fim)))
        if not heads and atual is not None and ip == len(pdf.pages) - 1:
            break
    # Descarta pedaços finais em páginas sem nenhum cabeçalho depois da última
    # questão (folha de rascunho etc.).
    ultima_pag = max(ip for q in questoes for ip, _ in q["cabecalhos"])
    if questoes:
        questoes[-1]["pedacos"] = [(ip, r) for ip, r in questoes[-1]["pedacos"] if ip <= ultima_pag]
    return questoes


# -------------------------------------------------------- detecção de visuais
def _intersecta(obj, r) -> bool:
    x0, t, x1, b = r
    return obj["x1"] > x0 and obj["x0"] < x1 and obj["bottom"] > t and obj["top"] < b


def _fracao_dentro(obj, r) -> float:
    """Fração da área do objeto que fica dentro do retângulo. Imagens podem
    ter a caixa maior que a parte visível (máscara de recorte); só contam
    para a questão que contém a maior parte delas."""
    x0, t, x1, b = r
    w = max(0.0, min(obj["x1"], x1) - max(obj["x0"], x0))
    h = max(0.0, min(obj["bottom"], b) - max(obj["top"], t))
    area = max(1e-6, (obj["x1"] - obj["x0"]) * (obj["bottom"] - obj["top"]))
    return w * h / area


def faixa_de_titulo(o, chars) -> bool:
    """Decoração de 2025+: faixa colorida baixa atrás de um título de seção
    ("Texto para as Questões de 06 a 10", "LINGUAGENS... Questões de 01 a 05"),
    ou marca pequena encostada na margem."""
    w, h = o["x1"] - o["x0"], o["bottom"] - o["top"]
    if w < 12 and h < 12 and (o["x0"] < X_ESQ or o["x1"] > X_DIR):
        return True
    if h > 36 or w < 150:
        return False
    dentro = "".join(c["text"] for c in chars if o["x0"] <= (c["x0"] + c["x1"]) / 2 <= o["x1"]
                     and o["top"] <= (c["top"] + c["bottom"]) / 2 <= o["bottom"])
    return bool(re.search(r"Questões\s*de\s*\d+|Textopara|QUESTÃO", dentro.replace(" ", ""), re.I))


def elementos_visuais(pdf, q: dict) -> list[str]:
    tipos: set[str] = set()
    faixas_cab = [(ip, h["top"] - 3, h["bottom"] + 8) for ip, h in q["cabecalhos"]]
    for ip, r in q["pedacos"]:
        pg = pdf.pages[ip]
        if any(_fracao_dentro(im, r) >= 0.3 for im in pg.images):
            tipos.add("imagem")

        texto_pedaco = [c for c in pg.chars if _intersecta(c, r) and c["text"].strip()]

        def decorativo(o):
            vertical_divisoria = DIVISORIA[0] < o["x0"] < DIVISORIA[1] and o["x1"] - o["x0"] < 1
            no_cabecalho = any(i == ip and a <= o["top"] <= z for i, a, z in faixas_cab)
            # Traço que encerra a questão: horizontal, longo, sem texto abaixo.
            horizontal_longo = (o["bottom"] - o["top"] < 1.5
                                and o["x1"] - o["x0"] >= 0.7 * (r[2] - r[0]))
            fecho = horizontal_longo and not any(c["top"] > o["bottom"] for c in texto_pedaco)
            fora_da_area = (not X_ESQ <= (o["x0"] + o["x1"]) / 2 <= X_DIR
                            or not TOPO <= (o["top"] + o["bottom"]) / 2 <= BASE)
            return vertical_divisoria or no_cabecalho or fecho or fora_da_area or faixa_de_titulo(o, pg.chars)

        vetores = [o for o in pg.lines + pg.rects + pg.curves if _intersecta(o, r) and not decorativo(o)]
        if vetores:
            curvas = [o for o in vetores if o.get("object_type") == "curve"]
            horiz = [o for o in vetores if abs(o["bottom"] - o["top"]) < 1.5]
            vert = [o for o in vetores if abs(o["x1"] - o["x0"]) < 1.5]
            if not curvas and len(horiz) >= 3 and len(vert) >= 2:
                tipos.add("tabela")
            elif all(o["x1"] - o["x0"] < 60 and o["bottom"] - o["top"] < 15 for o in vetores):
                tipos.add("formula")  # traços de fração, sinal de raiz
            else:
                tipos.add("figura/gráfico")

        chars = [c for c in pg.chars if _intersecta(c, r)
                 and FONTE_ALTERNATIVA not in c["fontname"].lower()]
        if not chars:
            continue
        if any(c["text"] in SIMBOLOS_FORMULA for c in chars) or any(
                any(f in c["fontname"].lower() for f in FONTES_FORMULA) for c in chars):
            tipos.add("formula")
        tamanho_texto = statistics.median(c["size"] for c in chars)
        grandes = [c for c in chars if c["size"] >= tamanho_texto * 0.95]
        for c in chars:
            # índice/expoente: caractere menor, colado a um caractere de
            # tamanho normal e com linha de base deslocada.
            if c["size"] < tamanho_texto * 0.85 and c["text"].strip() and c["text"] not in ",.;:":
                for g in grandes:
                    if abs(g["x1"] - c["x0"]) < 1.5 and abs(g["bottom"] - c["bottom"]) > 1.2 \
                            and abs(g["top"] - c["top"]) < g["size"]:
                        tipos.add("formula")
                        break
            if "formula" in tipos:
                break
    return sorted(tipos)


def verificar_cobertura(pdf, questoes: list[dict]) -> list[str]:
    """Cada caractere do conteúdo (entre a primeira e a última questão) deve
    cair em exatamente um recorte. Detecta cortes e sobreposições."""
    pedacos: dict[int, list] = {}  # página -> [(número da questão, retângulo)]
    for q in questoes:
        for ip, r in q["pedacos"]:
            pedacos.setdefault(ip, []).append((q["numero"], r))
    if not pedacos:
        return ["nenhuma questão encontrada"]
    problemas = []
    primeira = min(ip for q in questoes for ip, _ in q["cabecalhos"])
    for ip in range(primeira, max(pedacos) + 1):
        if e_pagina_de_redacao(pdf.pages[ip]):
            continue
        fora, duplo = [], []
        for c in pdf.pages[ip].chars:
            if not c["text"].strip() or c["top"] < TOPO or c["bottom"] > BASE + 2 \
                    or not X_ESQ <= (c["x0"] + c["x1"]) / 2 <= X_DIR:
                continue
            donos = {n for n, r in pedacos.get(ip, []) if _intersecta(c, r)
                     and r[0] <= (c["x0"] + c["x1"]) / 2 <= r[2]
                     and r[1] <= (c["top"] + c["bottom"]) / 2 <= r[3]}
            if not donos:
                fora.append(c)
            elif len(donos) > 1:
                duplo.append(c)
        if ip == primeira:  # título da área antes da 1ª questão
            fora = [c for c in fora if c["top"] > min(h["top"] for q in questoes
                                                       for i, h in q["cabecalhos"] if i == ip)]
        texto_fora = re.sub(r"\s+", " ", "".join(c["text"] for c in fora))
        if fora and re.fullmatch(r"[A-ZÀ-Ýa-zà-ý ,]*Questões ?de ?\d+ ?a ?\d+.{0,40}",
                                 texto_fora.replace("Questõesde", "Questões de"), re.I):
            fora = []  # só o título de área
        if fora:
            amostra = "".join(c["text"] for c in fora[:40])
            problemas.append(f"página {ip + 1}: {len(fora)} caracteres fora de qualquer questão: {amostra!r}")
        if duplo:
            problemas.append(f"página {ip + 1}: {len(duplo)} caracteres em duas questões")
        # Figuras e desenhos não podem ser cortados pela borda de um recorte.
        pg = pdf.pages[ip]
        for o in pg.images + pg.curves + pg.rects:
            if o["top"] < TOPO or o["bottom"] > BASE or not X_ESQ <= (o["x0"] + o["x1"]) / 2 <= X_DIR \
                    or faixa_de_titulo(o, pg.chars):
                continue  # fora da área útil (decoração das bordas da página)
            donos = {n for n, r in pedacos.get(ip, []) if _fracao_dentro(o, r) > 0.02}
            if len(donos) == 1 and sum(_fracao_dentro(o, r) for _, r in pedacos.get(ip, [])) > 0.98:
                continue  # dividido entre pedaços da MESMA questão: não há corte
            fracoes = [_fracao_dentro(o, r) for _, r in pedacos.get(ip, [])]
            maior = max(fracoes, default=0)
            if o["object_type"] == "image":
                cortado = maior < 0.7  # tolera máscara de recorte
            else:
                cortado = 0.02 < maior < 0.98
            if cortado:
                problemas.append(f"página {ip + 1}: {o['object_type']} em "
                                 f"({o['x0']:.0f},{o['top']:.0f})-({o['x1']:.0f},{o['bottom']:.0f}) "
                                 f"cortado entre recortes (maior parte: {maior:.0%})")
                break
    return problemas


# ------------------------------------------------------------------- texto
def texto_da_questao(pdf, q: dict) -> tuple[str, dict[str, str]]:
    # Cada linha vira (texto, letra do marcador ou None). O marcador da
    # alternativa é reconhecido pela fonte (BundesbahnPi), não pelo texto:
    # em 2023 a letra vem duplicada ("AA"), em 2024 vem simples ("A").
    linhas = []
    for ip, r in q["pedacos"]:
        for ln in pdf.pages[ip].crop(r).extract_text_lines(return_chars=True, strip=True):
            chars = [c for c in ln["chars"] if c["text"].strip()]
            n = 0
            while n < len(chars) and FONTE_ALTERNATIVA in chars[n]["fontname"].lower():
                n += 1
            letra = chars[0]["text"].upper() if n and chars[0]["text"].upper() in "ABCDE" else None
            texto = ln["text"]
            if letra:
                texto = texto.replace(" ", "", 0)
                texto = texto[n:] if texto[:n].replace(" ", "").upper() == letra * n else texto[1:]
            linhas.append((texto.strip(), letra))
    # remove o cabeçalho "QUESTÃO N"
    linhas = [(t, l) for t, l in linhas if not re.fullmatch(r"QUESTÃO\d+", t.replace(" ", ""), re.I)]
    corpo, alternativas, atual = [], {}, None
    for l, letra in linhas:
        if letra and (atual is None and letra == "A" or atual and ord(letra) == ord(atual) + 1):
            atual = letra
            alternativas[atual] = l
        elif atual:
            alternativas[atual] = (alternativas[atual] + " " + l.strip()).strip()
        else:
            corpo.append(l)
    enunciado = "\n".join(corpo).strip()
    enunciado = re.sub(r"\n?(CIÊNCIAS DA NATUREZA|MATEMÁTICA|LINGUAGENS|CIÊNCIAS HUMANAS)[^\n]*Questões de \d+ a \d+\s*$",
                       "", enunciado)
    return enunciado, alternativas


def salvar_imagem(pdf, q: dict, destino: Path) -> None:
    partes = [pdf.pages[ip].crop(r).to_image(resolution=RESOLUCAO).original.convert("RGB")
              for ip, r in q["pedacos"]]
    largura = max(p.width for p in partes)
    altura = sum(p.height for p in partes)
    final = Image.new("RGB", (largura, altura), "white")
    y = 0
    for p in partes:
        final.paste(p, (0, y))
        y += p.height
    destino.parent.mkdir(parents=True, exist_ok=True)
    final.save(destino, optimize=True)


# -------------------------------------------------------------------- main
def processar(ano: int, dia: int, caderno: int, aplicacao: str = "regular") -> Path:
    ctx = contexto_ssl()
    rotulo_aplicacao = APLICACOES[aplicacao][1]
    nome_prova, nome_gab = arquivos(ano, aplicacao, dia, caderno)
    chave = f"{aplicacao}_D{dia}_CD{caderno}"
    prova = baixar(BASE_DOWNLOAD + nome_prova, CACHE / str(ano) / nome_prova, ctx)
    gab = ler_gabarito(baixar(BASE_DOWNLOAD + nome_gab, CACHE / str(ano) / nome_gab, ctx))

    bruto = pdfplumber.open(str(prova))
    perfil = configurar_geometria(bruto, ano)
    pdf = Documento(bruto)
    capa = (pdf.pages[0].extract_text() or "").upper()
    cor = next((c for c in ("AZUL", "AMARELO", "BRANCO", "ROSA", "CINZA", "VERDE", "LARANJA")
                if c in capa), "?").capitalize()

    pasta = SAIDA / str(ano)
    saida, alertas_gerais, vistos = [], [], {}
    questoes = segmentar(pdf)
    for q in questoes:
        n = q["numero"]
        vistos[n] = vistos.get(n, 0) + 1
        lingua = None
        if dia == 1 and n <= 5:
            lingua = "ingles" if vistos[n] == 1 else "espanhol"
        enunciado, alternativas = texto_da_questao(pdf, q)
        visuais = elementos_visuais(pdf, q)
        bruta = gab["linguas"].get(n, {}).get(lingua) if lingua else gab["comum"].get(n)
        resposta, anulada = normalizar_resposta(bruta)

        sufixo = f"_{lingua}" if lingua else ""
        imagem = None
        if visuais:
            arq = pasta / "img" / f"{chave}_Q{n:03d}{sufixo}.png"
            salvar_imagem(pdf, q, arq)
            imagem = arq.relative_to(pasta).as_posix()

        alertas = []
        if len(alternativas) != 5:
            alertas.append(f"{len(alternativas)} alternativas no texto (esperado 5)"
                           + ("; ver a imagem" if visuais else ""))
        if bruta is None:
            alertas.append("sem resposta no gabarito")
        if not enunciado:
            alertas.append("enunciado vazio")
        alertas_gerais += [f"Q{n}{sufixo}: {a}" for a in alertas]

        saida.append({
            "id": f"{ano}-{aplicacao}-D{dia}-CD{caderno}-Q{n:03d}{sufixo.replace('_', '-')}",
            "prova": {
                "ano": ano,
                "aplicacao": aplicacao,
                "reaplicacao": aplicacao == "reaplicacao",
                "rotulo_aplicacao": rotulo_aplicacao,
                "descricao": f"ENEM {ano} · {rotulo_aplicacao}",
            },
            "area": NOMES_AREA.get(area_da_questao(dia, n)),
            # Número no caderno: só para rastrear até o PDF e o gabarito oficiais.
            "numero": n,
            "lingua_estrangeira": lingua,
            "enunciado": enunciado,
            "alternativas": alternativas,
            "gabarito": resposta,
            "anulada": anulada,
            "texto_base": next((f"{ano}-{aplicacao}-D{dia}-CD{caderno}-T{t['texto_base'][0]:02d}"
                                for t in TEXTOS_BASE if t["texto_base"][0] <= n <= t["texto_base"][1]
                                and not (lingua and n <= 5)), None),
            "elementos_visuais": visuais,
            "imagem": imagem,
            "texto_fiel": not visuais,
            "alertas": alertas,
            "fonte": {"prova": BASE_DOWNLOAD + nome_prova, "gabarito": BASE_DOWNLOAD + nome_gab},
        })

    alertas_gerais += verificar_cobertura(pdf, questoes + TEXTOS_BASE)

    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{chave}.json"
    destino.write_text(json.dumps(saida, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    esperado = 90 + (10 if dia == 1 else 0) - (5 if dia == 1 else 0)
    numeros = sorted({q["numero"] for q in saida})
    print(f"{ano} dia {dia} caderno {caderno} ({cor}): {len(saida)} questões "
          f"(esperado {esperado}) -> {destino.relative_to(RAIZ)}")
    faltando = sorted(set(range(1 if dia == 1 else 91, 91 if dia == 1 else 181)) - set(numeros))
    if faltando:
        print("  FALTANDO:", faltando)
    so_texto = sum(1 for q in saida if not q["elementos_visuais"])
    print(f"  só texto: {so_texto} | com imagem salva: {len(saida) - so_texto}")
    contagem: dict[str, int] = {}
    for q in saida:
        for v in q["elementos_visuais"]:
            contagem[v] = contagem.get(v, 0) + 1
    print("  elementos:", contagem)
    print(f"  alertas: {len(alertas_gerais)}")
    for a in alertas_gerais:
        print("   -", a)
    return destino


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ano", type=int, required=True)
    ap.add_argument("--dia", type=int, choices=(1, 2), required=True)
    ap.add_argument("--caderno", type=int, required=True)
    ap.add_argument("--aplicacao", choices=tuple(APLICACOES), default="regular",
                    help="regular (padrão) ou reaplicacao (PPL)")
    a = ap.parse_args()
    processar(a.ano, a.dia, a.caderno, a.aplicacao)


if __name__ == "__main__":
    main()
