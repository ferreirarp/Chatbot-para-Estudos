#!/usr/bin/env python3
"""Transforma questões salvas como imagem inteira em TEXTO + recortes só dos
objetos visuais (foto, gráfico, desenho, tabela, fórmula complexa).

    python scripts/estruturar_questoes.py --ano 2024 --dia 2 --caderno 7 [--aplicacao reaplicacao] [--questoes 97,112]

Para cada questão com imagem, grava no JSON da prova:
  "blocos":  [{"tipo": "texto", "texto": ...}, {"tipo": "figura", "imagem": ..., "motivo": ...}, ...]
             na ordem de leitura do caderno;
  "alternativas_imagem": {"A": caminho, ...} quando a alternativa é um desenho;
  "revisar": [motivos]   pontos em que a conversão é menos confiável.
A imagem inteira da questão ("imagem") continua salva como referência.

Regras:
- Objeto visual = imagem raster ou desenho vetorial que não seja decoração da
  página. Linhas de texto que se sobrepõem verticalmente ao objeto (rótulos,
  legendas de eixo, texto dentro de tabela) fazem parte do recorte: no caderno
  do ENEM as figuras ocupam a largura da coluna, sem texto ao lado.
- Índices e expoentes viram caracteres Unicode (H₂O, x², 10⁻³). Linhas com
  fração (traço horizontal curto com números acima e abaixo), raiz com barra,
  ou caracteres sem equivalente Unicode viram recorte pequeno ("fórmula").
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

import pdfplumber
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extrair_prova_regular as ex  # noqa: E402

RESOLUCAO = 200
ESPACO = 0.15        # intervalo máximo (fração do corpo da letra) que ainda junta letras
MODO_ESPACO = "relativo"
FOLGA = 3.0           # pontos de margem em volta de cada recorte
JUNTAR = 8.0          # objetos mais próximos que isso viram um recorte só

SOBRESCRITO = str.maketrans("0123456789+-−=()niaxyboc", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ⁿⁱᵃˣʸᵇᵒᶜ")
SUBSCRITO = str.maketrans("0123456789+-−=()aeoxhklmnpstrijuv", "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜᵣᵢⱼᵤᵥ")


def _privado(ch: str) -> bool:
    return any(0xE000 <= ord(c) <= 0xF8FF for c in ch) or "(cid:" in ch


def _decorativo(o, r, chars_pedaco, faixas_cab, ip) -> bool:
    vertical_divisoria = ex.DIVISORIA[0] < o["x0"] < ex.DIVISORIA[1] and o["x1"] - o["x0"] < 1
    # decoração do cabeçalho: objeto inteiro dentro da faixa do "QUESTÃO N"
    # (um quadro que só começa logo abaixo dela não é decoração)
    no_cabecalho = any(i == ip and a <= o["top"] and o["bottom"] <= z + 2 for i, a, z in faixas_cab)
    horizontal_longo = o["bottom"] - o["top"] < 1.5 and o["x1"] - o["x0"] >= 0.7 * (r[2] - r[0])
    fecho = horizontal_longo and not any(c["top"] > o["bottom"] for c in chars_pedaco)
    fora = (not ex.X_ESQ <= (o["x0"] + o["x1"]) / 2 <= ex.X_DIR
            or not ex.TOPO <= (o["top"] + o["bottom"]) / 2 <= ex.BASE)
    return vertical_divisoria or no_cabecalho or fecho or fora or ex.faixa_de_titulo(o, chars_pedaco)


def _caixa(o, r):
    """Caixa do objeto limitada ao pedaço."""
    return [max(o["x0"], r[0]), max(o["top"], r[1]), min(o["x1"], r[2]), min(o["bottom"], r[3])]


def _juntar(caixas: list[list[float]]) -> list[list[float]]:
    caixas = [c[:] for c in caixas]
    mudou = True
    while mudou:
        mudou = False
        for i in range(len(caixas)):
            for j in range(i + 1, len(caixas)):
                a, b = caixas[i], caixas[j]
                if a[0] - JUNTAR < b[2] and b[0] - JUNTAR < a[2] and a[1] - JUNTAR < b[3] and b[1] - JUNTAR < a[3]:
                    caixas[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del caixas[j]
                    mudou = True
                    break
            if mudou:
                break
    return caixas


def _fracoes(pg, r, chars):
    """Frações simples: traço horizontal curto com caracteres logo acima e
    logo abaixo, dentro da largura do traço. Retorna [(traço, num, den)]."""
    out = []
    tam = statistics.median(c["size"] for c in chars) if chars else None
    if chars and len(chars) < 10:
        tam = max(c["size"] for c in chars)
    tracos = [o for o in pg.lines + pg.rects
              if o["bottom"] - o["top"] < 1.5 and 1.5 < o["x1"] - o["x0"] < 80
              and r[0] <= (o["x0"] + o["x1"]) / 2 <= r[2] and r[1] <= o["top"] <= r[3]]
    for o in tracos:
        # fração dentro de fração: nenhuma delas vira texto (fica o recorte)
        if any(t is not o and t["x0"] < o["x1"] and o["x0"] < t["x1"] and abs(t["top"] - o["top"]) < 15 for t in tracos):
            continue
        na_largura = [c for c in chars if c["x0"] >= o["x0"] - 1.5 and c["x1"] <= o["x1"] + 1.5]
        num = [c for c in na_largura if 0 <= o["top"] - c["bottom"] < 4.5]
        den = [c for c in na_largura if 0 <= c["top"] - o["bottom"] < 4.5]
        # fração dentro de expoente (letras pequenas, como em 3^(t/2)) não vira
        # texto: fica para o recorte de fórmula
        # conservador: tudo o que está em volta do traço (na largura dele, até
        # 8 pt acima ou abaixo) tem de ser numerador ou denominador; se sobrar
        # algo (um expoente mais alto, como em cm²·s), a fração fica no recorte
        usados = {id(c) for c in num + den}
        sobra = [c for c in chars if id(c) not in usados and o["x0"] - 1 <= (c["x0"] + c["x1"]) / 2 <= o["x1"] + 1
                 and (0 <= o["top"] - c["bottom"] <= 8 or 0 <= c["top"] - o["bottom"] <= 8)]
        if num and den and not sobra and tam and max(c["size"] for c in num + den) >= tam * 0.85:
            out.append((o, sorted(num, key=lambda c: c["x0"]), sorted(den, key=lambda c: c["x0"])))
    return out


def _parte(cs):
    # expoente/índice dentro do numerador ou denominador (m² em W/m²)
    grande = max(c["size"] for c in cs)
    base = max(c["bottom"] for c in cs if c["size"] >= grande * 0.85)
    t = "".join((c["text"].translate(SOBRESCRITO) if c["bottom"] < base - 1 else c["text"].translate(SUBSCRITO))
                if c["size"] < grande * 0.85 else c["text"] for c in cs)
    return f"({t})" if re.search(r"[+\-−×·⋅]", t) else t


def _juntar_sobrepostas_v(caixas, tol=3.0):
    """Une caixas que se tocam (com folga `tol` nos dois sentidos)."""
    out = []
    for c in caixas:
        c = c[:]
        mudou = True
        while mudou:
            mudou = False
            for o in out:
                if c[0] < o[2] + tol and o[0] < c[2] + tol and c[1] < o[3] + tol and o[1] < c[3] + tol:
                    c = [min(o[0], c[0]), min(o[1], c[1]), max(o[2], c[2]), max(o[3], c[3])]
                    out.remove(o)
                    mudou = True
                    break
        out.append(c)
    return out


def _juntar_sobrepostas(caixas, tol=4.0):
    """Une caixas que se sobrepõem, ou que estão lado a lado na mesma altura
    a até `tol` pontos (metades de uma fórmula, figuras coladas)."""
    out = []
    for c in caixas:
        for o in out:
            if c[0] < o[2] + tol and o[0] < c[2] + tol and c[1] < o[3] and o[1] < c[3]:
                o[:] = [min(o[0], c[0]), min(o[1], c[1]), max(o[2], c[2]), max(o[3], c[3])]
                break
        else:
            out.append(c[:])
    return out if len(out) == len(caixas) else _juntar_sobrepostas(out, tol)


def _linhas(pg, r):
    """Linhas de texto da região (sem o cabeçalho). Agrupa pela linha de base
    dos caracteres de tamanho normal; índices e expoentes (menores) entram na
    linha a que estão encostados. Um caractere pertence à região em que cai
    o seu centro."""
    # o PDF traz os espaços entre palavras como caracteres; marca quem vem
    # logo depois de um (fontes com larguras erradas deixam folgas falsas
    # entre letras, e o espaço explícito é a referência mais confiável)
    depois_de_espaco = False
    for c in pg.chars:
        if not c["text"].strip():
            depois_de_espaco = True
            continue
        c["_esp"] = depois_de_espaco
        depois_de_espaco = False
    chars = [c for c in pg.chars if c["text"].strip()
             and r[0] <= (c["x0"] + c["x1"]) / 2 <= r[2] and r[1] <= (c["top"] + c["bottom"]) / 2 <= r[3]]
    if not chars:
        return []
    # glifos repetidos no mesmo lugar (ligaduras "fl", negrito simulado)
    unicos = []
    for c in sorted(chars, key=lambda c: (round(c["top"]), c["x0"])):
        if any(u["text"] == c["text"] and abs(u["x0"] - c["x0"]) < 1 and abs(u["top"] - c["top"]) < 1 for u in unicos[-6:]):
            continue
        unicos.append(c)
    chars = unicos
    tam = statistics.median(c["size"] for c in chars)
    if len(chars) < 10:  # poucos caracteres (²₁D): a mediana pode ser o tamanho pequeno
        tam = max(c["size"] for c in chars)
    # frações simples viram texto "num/den" na linha em que o traço está
    insercoes = []
    for o, num, den in _fracoes(pg, r, chars):
        usados = {id(c) for c in num + den}
        chars = [c for c in chars if id(c) not in usados]
        # a caixa vai do numerador ao denominador (um recorte que inclua a
        # linha não pode cortar a fração)
        insercoes.append({"text": f"{_parte(num)}/{_parte(den)}", "x0": o["x0"], "x1": o["x1"],
                          "top": min(c["top"] for c in num), "bottom": max(c["bottom"] for c in den),
                          "size": tam, "fontname": "fracao", "eixo": o["top"]})
    if not chars and not insercoes:
        return []

    pequenos_cand = sorted([c for c in chars if c["size"] < tam * 0.85], key=lambda c: c["x0"])
    ids_cand = {id(c) for c in pequenos_cand}
    normais = sorted([c for c in chars if id(c) not in ids_cand], key=lambda c: c["bottom"])
    grupos, grupo_de = [], {}
    for c in normais:
        if grupos and abs(c["bottom"] - grupos[-1]["base"]) < min(2.0, c["size"] * 0.25):
            grupos[-1]["chars"].append(c)
        else:
            grupos.append({"base": c["bottom"], "chars": [c]})
        grupo_de[id(c)] = grupos[-1]
    # Índice/expoente: caractere menor encostado (até 4 pt, em cadeia) a um
    # vizinho à esquerda — ou à direita, como em ¹⁴C — na mesma altura.
    soltos = []
    # repete até estabilizar: numa cadeia como ¹²₆C o "1" só se liga depois do "2"
    pendentes = list(pequenos_cand)
    while True:
        antes = len(pendentes)
        restantes = []
        for c in pendentes:
            meio = (c["top"] + c["bottom"]) / 2
            dv = lambda g: abs((g["top"] + g["bottom"]) / 2 - meio)
            ancorados = [g for g in normais + [x for x in pequenos_cand if id(x) in grupo_de]
                         if g is not c and dv(g) < g["size"] * 0.7]
            esq = [g for g in ancorados if -1.0 <= c["x0"] - g["x1"] < 4.0]
            dir_ = [g for g in ancorados if -1.0 <= g["x0"] - c["x1"] < 4.0]
            viz = (min(esq, key=lambda g: max(0, c["x0"] - g["x1"]) + 2 * dv(g), default=None)
                   or min(dir_, key=lambda g: max(0, g["x0"] - c["x1"]) + 2 * dv(g), default=None))
            if viz is not None and id(viz) in grupo_de:
                grupo_de[id(viz)]["chars"].append(c)
                grupo_de[id(c)] = grupo_de[id(viz)]
            else:
                restantes.append(c)
        pendentes = restantes
        if len(pendentes) == antes:
            break
    soltos += pendentes
    # texto pequeno de verdade (fonte, legenda): linhas próprias
    for c in sorted(soltos, key=lambda c: c["bottom"]):
        alvo = next((g for g in grupos if g.get("pequeno") and abs(g["base"] - c["bottom"]) < 1.5), None)
        if alvo:
            alvo["chars"].append(c)
        else:
            grupos.append({"base": c["bottom"], "chars": [c], "pequeno": True})
    for f in insercoes:  # o traço da fração fica na altura do meio da linha
        alvo = min(grupos, key=lambda g: abs(g["base"] - tam * 0.3 - f["eixo"]), default=None)
        if alvo and abs(alvo["base"] - tam * 0.3 - f["eixo"]) < tam:
            alvo["chars"].append(f)
        else:
            grupos.append({"base": f["eixo"] + tam * 0.3, "chars": [f]})
    # setas e símbolos soltos (→, ⇌) com linha de base própria voltam à linha
    # em cuja altura estão
    caixa_g = lambda g: (min(c["top"] for c in g["chars"]), max(c["bottom"] for c in g["chars"]))
    for g in list(grupos):
        if len(g["chars"]) <= 3 and not any(c["text"].isalnum() for c in g["chars"]):
            t, b = caixa_g(g)
            meio = (t + b) / 2
            dono = next((h for h in grupos if h is not g and len(h["chars"]) > 3
                         and caixa_g(h)[0] <= meio <= caixa_g(h)[1]), None)
            if dono:
                dono["chars"] += g["chars"]
                grupos.remove(g)
    out = []
    for g in grupos:
        cs = sorted(g["chars"], key=lambda c: c["x0"])
        texto = "".join(c["text"] for c in cs)
        if re.fullmatch(r"\s*QUESTÃO\s*\d+\s*", texto, re.I) or re.fullmatch(r"\s*Textoparaas?Questões?de\d+a\d+\.?\s*", texto):
            continue
        out.append({"top": min(c["top"] for c in cs), "bottom": max(c["bottom"] for c in cs),
                    "x0": min(c["x0"] for c in cs), "x1": max(c["x1"] for c in cs), "chars": cs, "texto": texto})
    return sorted(out, key=lambda l: l["top"])


def _texto_linha(ln) -> tuple[str, bool]:
    """Texto da linha com índices/expoentes em Unicode. Retorna (texto, complexa)."""
    chars = ln["chars"]
    normais = [c for c in chars if FONTE_ALT not in c["fontname"].lower()]
    if not normais:
        return ln["texto"], False
    # tamanho "normal" da linha: o maior presente (numa linha como ²₁D os
    # caracteres pequenos são maioria)
    tam = max([round(c["size"], 1) for c in normais if c["fontname"] != "fracao"] or [round(normais[0]["size"], 1)])
    base = statistics.median([c["bottom"] for c in normais if abs(c["size"] - tam) < 0.6 and c["fontname"] != "fracao"]
                             or [c["bottom"] for c in normais])
    # Espaço entre palavras: relativo ao espaçamento entre letras da própria
    # linha (a mediana dos intervalos), porque linhas justificadas podem estar
    # comprimidas (letras a -0,3 pt, palavras a +1,4 pt).
    intervalos = [b["x0"] - a["x1"] for a, b in zip(chars, chars[1:])]
    base_letras = statistics.median(intervalos) if len(intervalos) >= 4 else 0.0
    def limiar_espaco(a, b):
        corpo = max(a["size"], b["size"])
        if MODO_ESPACO == "fixo":
            return ESPACO * corpo
        if b.get("_esp") and b["x0"] - a["x1"] > -0.5 and abs(a["size"] - b["size"]) < 0.5:
            return -1e9  # espaço explícito no PDF
        if a["x1"] - a["x0"] < 0.05 and a["text"].strip():
            return 1e9   # glifo sem largura na fonte (2026): a folga é falsa
        return min(ESPACO * corpo, max(0.06 * corpo, base_letras + 0.11 * corpo))
    # pilha de índice e expoente na mesma posição (²₁D): o expoente vem primeiro
    def tipo(c):
        if c["size"] >= tam * 0.85 or FONTE_ALT in c["fontname"].lower():
            return "n"
        return "sup" if c["bottom"] < base - 1.0 else "sub" if c["bottom"] > base + 0.6 else "n"
    ordem, i = [], 0
    while i < len(chars):
        if tipo(chars[i]) == "n":
            ordem.append(chars[i]); i += 1; continue
        j = i
        while j < len(chars) and tipo(chars[j]) != "n":
            j += 1
        bloco = chars[i:j]
        sups = [c for c in bloco if tipo(c) == "sup"]
        subs = [c for c in bloco if tipo(c) == "sub"]
        empilhado = sups and subs and min(c["x1"] for c in sups + subs) > max(c["x0"] for c in sups + subs) - 6
        ordem += (sups + subs) if empilhado else bloco
        i = j
    chars = ordem
    partes, complexa, anterior = [], False, None
    for c in chars:
        t = _texto_char(c)
        if _privado(t):
            complexa = True
        if anterior is not None and c["x0"] - anterior["x1"] > limiar_espaco(anterior, c):
            partes.append(" ")
        if c["size"] < tam * 0.85 and t.strip() and t not in ",.;:" and FONTE_ALT not in c["fontname"].lower():
            if c["bottom"] < base - 1.0:
                conv = t.translate(SOBRESCRITO)
            elif c["bottom"] > base + 0.6:
                conv = t.translate(SUBSCRITO)
            else:
                conv = t
            if conv == t and (c["bottom"] < base - 1.0 or c["bottom"] > base + 0.6):
                complexa = True  # índice/expoente sem equivalente Unicode
            t = conv
        partes.append(t + ("\u20d7" if c.get("seta") else ""))
        anterior = c
    texto = re.sub(r" {2,}", " ", "".join(partes)).strip()
    texto = re.sub(r"(?<=[\d)]) (?=[.,;:](?:\s|$))", "", texto)  # "15/60 ." -> "15/60."
    texto = re.sub(r" (?=[,.;:!?)\]](?:\s|$|[,.;:!?)\]]))", "", texto)   # "F ," -> "F,"
    texto = re.sub(r"(?<=[(\[]) ", "", texto)                            # "( t" -> "(t"
    texto = re.sub(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]+[₀₁₂₃₄₅₆₇₈₉]+) (?=[A-Z])", r"\1", texto)   # "¹²₆ C" -> "¹²₆C"
    return texto, complexa


FONTE_ALT = ex.FONTE_ALTERNATIVA
# Codificação padrão da fonte Symbol (Adobe): a letra latina guardada no PDF
# é desenhada como a grega correspondente (a -> α, D -> Δ ...).
SYMBOL = str.maketrans("ABCDEFGHIKLMNOPQRSTUWXYZabcdefghijklmnopqrstuvwxyz",
                       "ΑΒΧΔΕΦΓΗΙΚΛΜΝΟΠΘΡΣΤΥΩΞΨΖαβχδεφγηιϕκλμνοπθρστυϖωξψζ")


def _texto_char(c) -> str:
    t = c["text"]
    return t.translate(SYMBOL) if "symbol" in c["fontname"].lower() and len(t) == 1 and t.isascii() and t.isalpha() else t


def _marcadores(pg, r) -> list[dict]:
    """Letras (A)...(E) das alternativas no pedaço (fonte própria do ENEM;
    em 2023 a letra vem duplicada, fica só uma)."""
    ms = []
    for c in sorted(pg.chars, key=lambda c: (round(c["top"]), c["x0"])):
        if FONTE_ALT in c["fontname"].lower() and c["text"].upper() in "ABCDE" and c["text"].strip() \
                and r[0] <= (c["x0"] + c["x1"]) / 2 <= r[2] and r[1] <= (c["top"] + c["bottom"]) / 2 <= r[3]:
            if ms and ms[-1]["letra"] == c["text"].upper() and abs(ms[-1]["top"] - c["top"]) < 3 \
                    and c["x0"] - ms[-1]["x1"] < 3:
                ms[-1]["x1"] = c["x1"]
                continue
            ms.append({"letra": c["text"].upper(), "x0": c["x0"], "x1": c["x1"], "top": c["top"], "bottom": c["bottom"]})
    return ms


def _conteudo(pg, ip, caixa, faixas_cab, revisar):
    """Itens (topo, tipo, dados) de uma região: linhas de texto convertidas e
    recortes de figuras/fórmulas."""
    r = caixa
    chars_reg = [c for c in pg.chars if ex._intersecta(c, r) and c["text"].strip()]
    linhas = [ln for ln in _linhas(pg, r)
              if not all(FONTE_ALT in c["fontname"].lower() for c in ln["chars"])]
    objetos = [_caixa(im, r) for im in pg.images if ex._fracao_dentro(im, r) >= 0.3]
    centro_dentro = lambda o: r[0] <= (o["x0"] + o["x1"]) / 2 <= r[2] and r[1] <= (o["top"] + o["bottom"]) / 2 <= r[3]
    vetores = [o for o in pg.lines + pg.rects + pg.curves
               if centro_dentro(o) and not _decorativo(o, r, chars_reg, faixas_cab, ip)]
    # seta de vetor: traço curto (e a ponta) logo acima de uma letra -> f⃗
    setas = set()
    for o in vetores:
        if o["x1"] - o["x0"] > 12 or o["bottom"] - o["top"] > 5:
            continue
        for c in chars_reg:
            if c["text"].isalpha() and o["x0"] < c["x1"] + 3 and o["x1"] > c["x0"] - 3 \
                    and c["top"] - 5 <= o["bottom"] <= c["top"] + 0.5:
                c["seta"] = True
                setas.add(id(o))
                break
    vetores = [o for o in vetores if id(o) not in setas]
    # traços finos e curtos (barra de fração, de raiz, sublinhado) são de
    # fórmula; formas pequenas (círculo, quadrado de legenda) são figura
    pequenos = [o for o in vetores if o["x1"] - o["x0"] < 60 and o["bottom"] - o["top"] < 15
                and min(o["x1"] - o["x0"], o["bottom"] - o["top"]) < 1.5]
    objetos += [_caixa(o, r) for o in vetores if o not in pequenos]
    # traços finos agrupados (2 ou mais, com altura) formam um desenho feito
    # de linhas (planta de terreno, gráfico de eixos): é figura, não fórmula
    # mesmo conjunto de caracteres que _linhas usa (centro dentro da região):
    # um traço que não vira "a/b" lá tem de virar recorte aqui
    centro_em_r = [c for c in chars_reg if r[0] <= (c["x0"] + c["x1"]) / 2 <= r[2] and r[1] <= (c["top"] + c["bottom"]) / 2 <= r[3]]
    tracos_fracao = {id(o) for o, _n, _d in _fracoes(pg, r, centro_em_r)}
    soltos_ = [o for o in pequenos if id(o) not in tracos_fracao]
    grupos_t = []
    for o in soltos_:
        cx = [o["x0"], o["top"], o["x1"], o["bottom"]]
        for g in grupos_t:
            b = g["caixa"]
            if cx[0] - 2 < b[2] and b[0] - 2 < cx[2] and cx[1] - 2 < b[3] and b[1] - 2 < cx[3]:
                g["caixa"] = [min(b[0], cx[0]), min(b[1], cx[1]), max(b[2], cx[2]), max(b[3], cx[3])]
                g["n"] += 1
                g["ids"].add(id(o))
                break
        else:
            grupos_t.append({"caixa": cx, "n": 1, "ids": {id(o)}})
    desenhados = set()
    for g in grupos_t:
        if g["n"] >= 2 and g["caixa"][3] - g["caixa"][1] >= 6:
            objetos.append(g["caixa"])
            desenhados |= g["ids"]
    pequenos = [o for o in pequenos if id(o) not in desenhados]
    caixas = [c for c in _juntar(objetos) if c[3] - c[1] >= 3]  # traço solto (separador) não é figura
    for o in pequenos:  # pequenos traços encostados num desenho fazem parte dele
        for c in caixas:
            if o["x0"] < c[2] + JUNTAR and o["x1"] > c[0] - JUNTAR and o["top"] < c[3] + JUNTAR and o["bottom"] > c[1] - JUNTAR:
                c[:] = [min(c[0], o["x0"]), min(c[1], o["top"]), max(c[2], o["x1"]), max(c[3], o["bottom"])]
                break
    formulas = [[o["x0"], o["top"] - 1, o["x1"], o["bottom"] + 1] for o in pequenos
                if id(o) not in tracos_fracao and o["bottom"] - o["top"] < 1.5 and o["x1"] - o["x0"] > 1.5
                and not any(c[1] - 1 <= o["top"] <= c[3] + 1 for c in caixas)]

    def so_pequenos(ln):  # linha só de índices/expoentes soltos
        return tam_reg and max(c["size"] for c in ln["chars"]) < tam_reg * 0.85

    def absorver(cx):
        mudou = True
        while mudou:
            mudou = False
            for ln in linhas:
                encosta = so_pequenos(ln) and ln["top"] <= cx[3] + 3 and ln["bottom"] >= cx[1] - 3
                if not ln.get("usada") and (encosta or min(ln["bottom"], cx[3]) - max(ln["top"], cx[1]) > 0.4 * (ln["bottom"] - ln["top"])):
                    cx[:] = [min(cx[0], ln["x0"]), min(cx[1], ln["top"]), max(cx[2], ln["x1"]), max(cx[3], ln["bottom"])]
                    ln["usada"] = mudou = True

    tam_reg = statistics.median(c["size"] for c in chars_reg) if chars_reg else None
    # margens do bloco de texto (linhas de tamanho normal), não da região
    normais_reg = [ln for ln in linhas if tam_reg and statistics.median(c["size"] for c in ln["chars"]) >= tam_reg * 0.95]
    bloco_x0 = min([ln["x0"] for ln in normais_reg] or [r[0]])
    bloco_x1 = max([ln["x1"] for ln in normais_reg] or [r[2]])
    itens = []
    def rotulos(cx):
        """Linha curta, fora da margem do parágrafo, sem pontuação final e
        encostada na figura é rótulo dela (“Círculo C₁”)."""
        mudou = True
        while mudou:
            mudou = False
            for ln in linhas:
                if ln.get("usada"):
                    continue
                txt = "".join(ch["text"] for ch in ln["chars"]).strip()
                curta = ln["x1"] - ln["x0"] < 0.6 * (bloco_x1 - bloco_x0)
                fora_da_margem = ln["x0"] > bloco_x0 + 8
                sem_ponto = not re.search(r"[.:;?!]$", txt)
                # rótulos de figuras lado a lado ficam numa linha só, com
                # buracos grandes entre as palavras ("Terreno 1    Terreno 2")
                cs = ln["chars"]
                esparsa = len(cs) > 1 and max(b["x0"] - a["x1"] for a, b in zip(cs, cs[1:])) > 15
                dist = 18 if esparsa else 14
                perto = (0 <= ln["top"] - cx[3] <= dist) or (0 <= cx[1] - ln["bottom"] <= dist)
                sobrepoe = ln["x0"] < cx[2] + 20 and ln["x1"] > cx[0] - 20
                if ((curta and fora_da_margem) or esparsa) and sem_ponto and perto and sobrepoe:
                    cx[:] = [min(cx[0], ln["x0"]), min(cx[1], ln["top"]), max(cx[2], ln["x1"]), max(cx[3], ln["bottom"])]
                    ln["usada"] = mudou = True

    # absorve linhas e rótulos; figuras que passam a se sobrepor viram uma só
    while True:
        for c in caixas:
            absorver(c)
            rotulos(c)
            absorver(c)
        juntas = _juntar_sobrepostas(caixas)
        if len(juntas) == len(caixas):
            break
        caixas = juntas
    for c in caixas:
        itens.append((c[1], "figura", (c, "figura")))
    for f in _juntar(formulas):
        if any(f[1] < c[3] and f[3] > c[1] for _, t, (c, _m) in itens):
            continue
        # o traço leva junto o que está colado acima e abaixo (numerador e
        # denominador); depois as linhas inteiras entram pela absorção
        t0 = list(f)  # distâncias medidas a partir do traço, sem encadear
        for c in chars_reg:
            if c["x1"] > t0[0] - 1 and c["x0"] < t0[2] + 1 and (0 <= t0[1] - c["bottom"] <= 4.5 or 0 <= c["top"] - t0[3] <= 4.5):
                f[:] = [min(f[0], c["x0"]), min(f[1], c["top"]), max(f[2], c["x1"]), max(f[3], c["bottom"])]
        absorver(f)
        itens.append((f[1], "figura", (f, "fórmula")))
        revisar.add("fórmula recortada como imagem")
    # um recorte não invade linha que ficou como texto (caixas de imagem
    # costumam ser maiores que a parte visível)
    for _, t, (c, _m) in itens:
        for ln in linhas:
            if ln.get("usada") or min(ln["bottom"], c[3] + FOLGA) - max(ln["top"], c[1] - FOLGA) <= 0:
                continue
            if (ln["top"] + ln["bottom"]) / 2 > (c[1] + c[3]) / 2:
                c[3] = min(c[3], ln["top"] - 1 - FOLGA)
            else:
                c[1] = max(c[1], ln["bottom"] + 1 + FOLGA)
    # recorte que ficou sem altura depois de aparado não tinha conteúdo próprio
    itens = [it for it in itens if it[1] != "figura" or it[2][0][3] - it[2][0][1] >= 3]
    # 1ª passada: linhas complexas viram recorte e incorporam índices colados
    for ln in linhas:
        if ln.get("usada"):
            continue
        texto, complexa = _texto_linha(ln)
        if complexa:
            ln["usada"] = True
            cx = [ln["x0"], ln["top"], ln["x1"], ln["bottom"]]
            absorver(cx)
            itens.append((cx[1], "figura", (cx, "fórmula")))
            revisar.add("fórmula recortada como imagem")
    # recortes de fórmula na mesma faixa de altura viram um só
    formulas_it = [it for it in itens if it[1] == "figura" and it[2][1] == "fórmula"]
    outros = [it for it in itens if not (it[1] == "figura" and it[2][1] == "fórmula")]
    juntas = []
    for _, _, (cx, _m) in sorted(formulas_it, key=lambda it: it[2][0][1]):
        for j in juntas:
            if cx[1] < j[3] and j[1] < cx[3]:
                j[:] = [min(j[0], cx[0]), min(j[1], cx[1]), max(j[2], cx[2]), max(j[3], cx[3])]
                break
        else:
            juntas.append(cx[:])
    itens = outros + [(j[1], "figura", (j, "fórmula")) for j in juntas]
    # 2ª passada: o resto é texto
    for ln in linhas:
        if ln.get("usada"):
            continue
        texto, _ = _texto_linha(ln)
        # layout: linha centralizada (equação) é parágrafo próprio; recuo
        # de primeira linha abre parágrafo
        esq, dir_ = ln["x0"] - bloco_x0, bloco_x1 - ln["x1"]
        if esq > 12 and dir_ > 12 and abs(esq - dir_) < 10:
            texto = "\n" + texto + "\n"
        elif 8 < esq < 40 and dir_ < 25 and tam_reg and statistics.median(c["size"] for c in ln["chars"]) >= tam_reg * 0.95:
            texto = "\n" + texto
        itens.append((ln["top"], "linha", texto))
    return sorted(itens, key=lambda t: t[0])


def _fronteira(pg, a, b, x0, x1):
    """Altura que separa a alternativa a da b (b abaixo, mesma coluna): o
    meio da maior faixa vazia entre as duas, considerando letras e objetos."""
    ocup, desenho, letras = [], [], []
    for o in pg.chars + pg.images + pg.lines + pg.rects + pg.curves:
        if o.get("object_type") == "char" and not o["text"].strip():
            continue
        # só objetos com o centro nesta coluna (a caixa de uma imagem da
        # coluna vizinha pode passar do corredor)
        if x0 <= (o["x0"] + o["x1"]) / 2 <= x1 and o["bottom"] > a["top"] and o["top"] < b["top"]:
            if o.get("object_type") == "char":
                ocup.append((max(o["top"], a["top"]), min(o["bottom"], b["top"])))
                letras.append(o)
            else:
                desenho.append([o["x0"], o["top"], o["x1"], o["bottom"]])
    # traço de fração + o que está colado acima e abaixo dele = bloco único
    for d in desenho:
        if d[3] - d[1] < 1.5 and d[2] - d[0] < 80:
            t0 = list(d)  # distâncias medidas a partir do traço, sem encadear
            # todos os caracteres da coluna (o denominador pode passar da letra b)
            for c in [c for c in pg.chars if c["text"].strip() and x0 <= (c["x0"] + c["x1"]) / 2 <= x1]:
                if c["x1"] > t0[0] - 1 and c["x0"] < t0[2] + 1 and (0 <= t0[1] - c["bottom"] <= 4.5 or 0 <= c["top"] - t0[3] <= 4.5):
                    d[:] = [min(d[0], c["x0"]), min(d[1], c["top"]), max(d[2], c["x1"]), max(d[3], c["bottom"])]
    # traços que se tocam formam um bloco sólido (um gráfico inteiro, e não
    # as linhas de grade com espaços entre elas)
    solidos = _juntar_sobrepostas_v(desenho)
    # desenho que atravessa a linha da letra de b começa acima dela: o topo
    # dele é a fronteira (o desenho inteiro é da alternativa b)
    cruzam = [c for c in solidos if c[1] < b["top"] < c[3] and c[1] >= a["top"] - 2]
    if cruzam:
        return max(a["top"], min(c[1] for c in cruzam) - 0.5)
    for c in solidos:
        ocup.append((max(c[1], a["top"]), min(c[3], b["top"])))
    ocup.sort()
    # faixas vazias entre a e b; a fronteira é a faixa vazia mais próxima de
    # b (a mais larga pode estar dentro de a, como entre o traço e o
    # denominador de uma fração)
    vazias, y = [], a["top"]
    for t, fim in ocup:
        if t - y >= 0.8:
            vazias.append((y, t))
        y = max(y, fim)
    if b["top"] - y >= 0.8:
        vazias.append((y, b["top"]))
    if not vazias:
        return b["top"] - 0.3  # linhas coladas: logo acima da letra seguinte
    y0, y1 = vazias[-1]
    return (y0 + y1) / 2


def _zonas_alternativas(ms, r, topo_texto, pg=None):
    """Área de cada alternativa: da metade do espaço até a alternativa de
    cima até a metade do espaço até a de baixo, na mesma coluna; à direita,
    até a coluna de alternativas seguinte (alternativas em grade)."""
    colunas = []
    for m in sorted(ms, key=lambda m: m["x0"]):
        for col in colunas:
            if abs(col[0]["x0"] - m["x0"]) < 10:
                col.append(m)
                break
        else:
            colunas.append([m])
    zonas = {}
    for col in colunas:
        col.sort(key=lambda m: m["top"])
        passo = statistics.median([b["top"] - a["top"] for a, b in zip(col, col[1:])]) if len(col) > 1 else 60.0
        for i, m in enumerate(col):
            direita = min([o["x0"] - 2 for o in ms if o["x0"] > m["x0"] + 20 and abs(o["top"] - m["top"]) < passo] or [r[2]])
            # 1ª da coluna: último espaço vazio entre o fim do enunciado e ela
            # (o desenho da alternativa pode subir acima da letra)
            topo = _fronteira(pg, col[i - 1], m, m["x0"], direita) if i else max(topo_texto, _fronteira(pg, {"top": topo_texto}, m, m["x0"], direita))
            base = _fronteira(pg, m, col[i + 1], m["x0"], direita) if i + 1 < len(col) else r[3]
            zonas[m["letra"]] = (m, [m["x1"] + 0.5, topo, direita, base])
    return zonas


NORMALIZA = str.maketrans(dict(zip("⁰¹²³⁴⁵⁶⁷⁸⁹ⁿⁱᵃˣʸᵇᵒᶜ₀₁₂₃₄₅₆₇₈₉ₐₑₒₓₕₖₗₘₙₚₛₜᵣᵢⱼᵤᵥ",
                                     "0123456789niaxyboc0123456789aeoxhklmnpstrijuv")))


def _conferir(pdf, q, faixas_cab, cortes, blocos, alternativas):
    """Compara as letras e números do PDF com os do texto produzido, por um
    caminho independente da conversão (todos os caracteres dos pedaços).
    Falta: caractere que não está no texto nem na imagem salva (que inclui a
    margem FOLGA). Sobra: texto que repete o que está dentro de um recorte,
    ou que não existe no PDF."""
    from collections import Counter

    def contar(margem):
        cont = Counter()
        for ip, r in q["pedacos"]:
            vistos = []
            for c in pdf.pages[ip].chars:
                t = _texto_char(c)
                if not t.strip() or FONTE_ALT in c["fontname"].lower() or "(cid:" in t:
                    continue
                cx, cy = (c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2
                if not (r[0] <= cx <= r[2] and r[1] <= cy <= r[3]):
                    continue
                if any(i == ip and h["top"] - 1 <= cy <= h["bottom"] + 1 for i, h in q["cabecalhos"]):
                    continue  # linha do cabeçalho "QUESTÃO N"
                if any(i == ip and b[0] - margem <= cx <= b[2] + margem and b[1] - margem <= cy <= b[3] + margem
                       for i, b in cortes):
                    continue  # aparece na imagem de um recorte
                if any(v[0] == t and abs(v[1] - c["x0"]) < 1 and abs(v[2] - c["top"]) < 1 for v in vistos[-6:]):
                    continue  # glifo repetido no mesmo lugar
                vistos.append((t, c["x0"], c["top"]))
                cont.update(ch for ch in t.translate(NORMALIZA) if ch.isalnum())
        return cont
    saida = " ".join([b["texto"] for b in blocos if b["tipo"] == "texto"] + list(alternativas.values()))
    out_chars = Counter(ch for ch in saida.translate(NORMALIZA) if ch.isalnum())
    fmt = lambda c: "".join(sorted(c.elements()))[:40]
    return fmt(contar(FOLGA) - out_chars), fmt(out_chars - contar(0))


def _alternativas_raster(pdf, pedacos) -> dict:
    """{letra: (página, caixa)} quando cada letra A-E da questão tem, logo à
    direita, uma imagem (bitmap) que a contém na vertical. Procura a página
    inteira na faixa vertical da questão, porque essas alternativas podem
    atravessar o corredor entre as colunas."""
    achadas = {}
    for ip in sorted({ip for ip, _ in pedacos}):
        pg = pdf.pages[ip]
        topo = min(r[1] for j, r in pedacos if j == ip)
        base = max(r[3] for j, r in pedacos if j == ip)
        for c in pg.chars:
            if FONTE_ALT not in c["fontname"].lower() or c["text"] not in "ABCDE" or c["text"] in achadas:
                continue
            if not topo <= c["top"] <= base:
                continue
            meio = (c["top"] + c["bottom"]) / 2
            cand = [i for i in pg.images if 0 <= i["x0"] - c["x1"] <= 30 and i["top"] <= meio <= i["bottom"]]
            if cand:
                i = min(cand, key=lambda i: i["x0"] - c["x1"])
                achadas[c["text"]] = (ip, (i["x0"], i["top"], i["x1"], i["bottom"]))
    return achadas if sorted(achadas) == list("ABCDE") else {}


def estruturar(pdf, q: dict, pasta_img: Path, prefixo: str) -> dict:
    faixas_cab = [(ip, h["top"] - 3, h["bottom"] + 8) for ip, h in q["cabecalhos"]]
    revisar: set[str] = set()
    blocos, alternativas, alt_img = [], {}, {}
    n_fig = [0]

    cortes = []  # (página, caixa) de cada recorte, para a conferência
    caixas_de = {}  # caminho do recorte -> (página, caixa)

    def recortar(ip, c):
        c = list(c)
        for j, h in q["cabecalhos"]:  # o cabeçalho "QUESTÃO N" nunca entra no recorte
            if j == ip and c[1] < h["bottom"] + 1 < c[3]:
                c[1] = h["bottom"] + 1
        cortes.append((ip, tuple(c)))  # caixa do conteúdo; a imagem salva tem FOLGA a mais
        n_fig[0] += 1
        nome = f"{prefixo}_f{n_fig[0]}.png"
        pg = pdf.pages[ip]
        caixa = (max(0, c[0] - FOLGA), max(0, c[1] - FOLGA), min(pg.width, c[2] + FOLGA), min(pg.height, c[3] + FOLGA))
        img = pg.crop(caixa).to_image(resolution=RESOLUCAO).original.convert("RGB")
        (pasta_img).mkdir(parents=True, exist_ok=True)
        img.save(pasta_img / nome, optimize=True)
        caixas_de[f"img/blocos/{nome}"] = (ip, tuple(c))
        return f"img/blocos/{nome}"

    def ao_enunciado(itens, ip):
        for _, tipo, d in itens:
            if tipo == "linha":
                if blocos and blocos[-1]["tipo"] == "texto":
                    blocos[-1]["texto"] += "\n" + d
                else:
                    blocos.append({"tipo": "texto", "texto": d})
            else:
                blocos.append({"tipo": "figura", "imagem": recortar(ip, d[0]), "motivo": d[1]})

    ultima = None
    for ip, r in q["pedacos"]:
        pg = pdf.pages[ip]
        ms = [m for m in _marcadores(pg, r) if m["letra"] not in alternativas and m["letra"] not in alt_img]
        if not ms:
            itens = _conteudo(pg, ip, list(r), faixas_cab, revisar)
            if ultima is None:
                ao_enunciado(itens, ip)
            else:  # continuação da última alternativa em outra coluna/página
                for _, tipo, d in itens:
                    if tipo == "linha" and ultima in alternativas:
                        alternativas[ultima] += " " + d.strip()
                    else:
                        revisar.add("alternativa continua em outra coluna: conferir")
            continue
        topo_alt = min(m["top"] for m in ms)
        # texto do enunciado que acaba antes das alternativas
        # fim do enunciado: última linha de comprimento normal acima das
        # alternativas (rótulos curtos acima da letra A são do desenho dela)
        def corrida(ln):  # linha de texto contínua (não rótulos espalhados)
            cs = ln["chars"]
            return len(cs) >= 8 and max(b["x0"] - a["x1"] for a, b in zip(cs, cs[1:])) <= 15
        linhas_acima = [ln for ln in _linhas(pg, (r[0], r[1], r[2], topo_alt - 1))
                        if ln["x1"] - ln["x0"] >= 0.35 * (r[2] - r[0]) and corrida(ln)]
        topo_texto = max([ln["bottom"] + 1 for ln in linhas_acima] or [r[1]])
        zonas = _zonas_alternativas(ms, r, topo_texto, pg)
        inicio = min(z[1] for _, z in zonas.values())
        if inicio - r[1] > 2:
            ao_enunciado(_conteudo(pg, ip, [r[0], r[1], r[2], inicio], faixas_cab, revisar), ip)
        for letra in sorted(zonas):
            m, z = zonas[letra]
            itens = _conteudo(pg, ip, z, faixas_cab, revisar)
            if any(t == "figura" for _, t, _d in itens):
                # a alternativa é um desenho: recorta tudo o que está na área
                xs = [d[0] for _, t, d in itens if t == "figura"]
                ys = [ln for ln in _linhas(pg, z)]
                caixa = [min([c[0] for c in xs] + [l["x0"] for l in ys]), min([c[1] for c in xs] + [l["top"] for l in ys]),
                         max([c[2] for c in xs] + [l["x1"] for l in ys]), max([c[3] for c in xs] + [l["bottom"] for l in ys])]
                alt_img[letra] = recortar(ip, caixa)
                alternativas[letra] = ""
            else:
                alternativas[letra] = " ".join(d.strip() for _, t, d in itens).strip()
            ultima = letra
    for L, t in alternativas.items():  # título de seção colado na última alternativa
        alternativas[L] = re.sub(r"\s*Questões de \d+ a \d+\s*(\(opção [a-zçê]+\))?\s*$", "", t)
    if alt_img or sorted(alternativas) != list("ABCDE") or any(not alternativas.get(L) and L not in alt_img for L in "ABCDE"):
        # Alternativas que são imagens inteiras ao lado da letra (gráficos em
        # duas colunas que atravessam o corredor central): usa a caixa da imagem.
        achadas = _alternativas_raster(pdf, q["pedacos"])
        if achadas:
            usados = set(achadas.values())
            def cai_em_alternativa(ip, c):
                caixa = dict(zip(("x0", "top", "x1", "bottom"), c))
                return any(ip == j and ex._intersecta(caixa, cx) for j, cx in usados)
            blocos = [b for b in blocos if b["tipo"] != "figura" or b["imagem"] not in caixas_de
                      or not cai_em_alternativa(*caixas_de[b["imagem"]])]
            cortes = [(ip, c) for ip, c in cortes if not cai_em_alternativa(ip, c)]
            alt_img, alternativas = {}, {}
            for letra, (ip, cx) in sorted(achadas.items()):
                alt_img[letra] = recortar(ip, list(cx))
                alternativas[letra] = ""
            revisar.discard("alternativa continua em outra coluna: conferir")
    if sorted(alternativas) != list("ABCDE"):
        revisar.add("alternativas incompletas: conferir com a imagem original")
    for b in blocos:
        if b["tipo"] == "texto":
            b["texto"] = re.sub(r"\n{3,}", "\n\n", b["texto"]).strip("\n")
            b["texto"] = re.sub(r"\n?(CIÊNCIAS DA NATUREZA|MATEMÁTICA|LINGUAGENS|CIÊNCIAS HUMANAS)[^\n]*Questões de \d+ a \d+\s*$", "", b["texto"]).strip()
    blocos = [b for b in blocos if b["tipo"] != "texto" or b["texto"]]
    falta, sobra = _conferir(pdf, q, faixas_cab, cortes, blocos, alternativas)
    if falta or sobra:
        revisar.add("texto difere do PDF" + (f"; faltam: {falta}" if falta else "") + (f"; sobram: {sobra}" if sobra else ""))
    return {"blocos": blocos, "alternativas": alternativas, "alternativas_imagem": alt_img, "revisar": sorted(revisar)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ano", type=int, required=True)
    ap.add_argument("--dia", type=int, choices=(1, 2), required=True)
    ap.add_argument("--caderno", type=int, required=True)
    ap.add_argument("--aplicacao", choices=tuple(ex.APLICACOES), default="regular")
    ap.add_argument("--questoes", help="números separados por vírgula (padrão: todas com imagem); 1-ingles para a língua")
    a = ap.parse_args()

    chave = f"{a.aplicacao}_D{a.dia}_CD{a.caderno}"
    pdf_arq = ex.CACHE / str(a.ano) / ex.arquivos(a.ano, a.aplicacao, a.dia, a.caderno)[0]
    bruto = pdfplumber.open(str(pdf_arq))
    ex.configurar_geometria(bruto, a.ano)
    pdf = ex.Documento(bruto)
    pasta = ex.SAIDA / str(a.ano)
    arq_json = pasta / f"{chave}.json"
    questoes_json = json.loads(arq_json.read_text(encoding="utf-8"))
    por_chave = {str(q["numero"]) + (f"-{q['lingua_estrangeira']}" if q["lingua_estrangeira"] else ""): q for q in questoes_json}
    pedidas = set(a.questoes.split(",")) if a.questoes else None

    vistos: dict[int, int] = {}
    feitas = 0
    for q in ex.segmentar(pdf):
        n = q["numero"]
        vistos[n] = vistos.get(n, 0) + 1
        lingua = ("ingles" if vistos[n] == 1 else "espanhol") if a.dia == 1 and n <= 5 else None
        k = str(n) + (f"-{lingua}" if lingua else "")
        alvo = por_chave.get(k)
        if not alvo or not alvo["imagem"] or (pedidas and k not in pedidas and str(n) not in pedidas):
            continue
        prefixo = f"{chave}_Q{n:03d}" + (f"_{lingua}" if lingua else "")
        res = estruturar(pdf, q, pasta / "img" / "blocos", prefixo)
        alvo["blocos"] = res["blocos"]
        alvo["alternativas_imagem"] = res["alternativas_imagem"]
        alvo["revisar"] = res["revisar"]
        # o texto das alternativas passa a ser o convertido (índices em Unicode)
        for L, t in res["alternativas"].items():
            alvo["alternativas"][L] = t
        figs = sum(b["tipo"] == "figura" for b in res["blocos"])
        print(f"  Q{k}: {len(res['blocos'])} blocos ({figs} recortes), alternativas em texto {len(res['alternativas'])}, "
              f"em imagem {len(res['alternativas_imagem'])}{' | revisar: ' + '; '.join(res['revisar']) if res['revisar'] else ''}")
        feitas += 1
    arq_json.write_text(json.dumps(questoes_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{feitas} questões estruturadas em {arq_json.relative_to(ex.RAIZ)}")

    # textos-base (2025+): "Texto para as Questões de 06 a 10", guardados uma vez
    bases = {}
    for t in ex.TEXTOS_BASE:
        a0, a1 = t["texto_base"]
        tid = f"{a.ano}-{a.aplicacao}-D{a.dia}-CD{a.caderno}-T{a0:02d}"
        res = estruturar(pdf, t, pasta / "img" / "blocos", f"{chave}_T{a0:02d}")
        blocos = res["blocos"]
        if blocos and blocos[0]["tipo"] == "texto":  # tira o título, a interface mostra o seu
            blocos[0]["texto"] = re.sub(r"^\s*Texto para as? Questões? de \d+ a \d+\.?\s*", "", blocos[0]["texto"]).strip()
        for b in blocos:
            if b["tipo"] != "texto":
                continue
            # linhas numeradas (1, 2, 3...) são citadas pelas questões: mantêm a quebra
            ls = [l for l in b["texto"].split("\n") if l.strip()]
            numeradas = sum(bool(re.match(r"^\d{1,3}\s", l)) for l in ls)
            if len(ls) >= 5 and numeradas >= 0.6 * len(ls):
                b["estilo"] = "linhas"
        # linhas sem número antes da linha 1 (título, subtítulo) viram blocos próprios
        novos = []
        for b in blocos:
            if b.get("estilo") == "linhas":
                ls = b["texto"].split("\n")
                i = next((k for k, l in enumerate(ls) if re.match(r"^\d{1,3}\s", l)), 0)
                if i:
                    novos.append({"tipo": "texto", "estilo": "titulo", "texto": ls[0]})
                    if i > 1:
                        novos.append({"tipo": "texto", "estilo": "centro", "texto": " ".join(ls[1:i])})
                    b = dict(b, texto="\n".join(ls[i:]))
            novos.append(b)
        blocos = [b for b in novos if b["tipo"] != "texto" or b["texto"]]
        bases[tid] = {"id": tid, "questoes": [a0, a1], "blocos": blocos,
                      "revisar": [r for r in res["revisar"] if "alternativas" not in r]}
        print(f"  texto-base {tid}: {len(blocos)} blocos{' | revisar: ' + '; '.join(bases[tid]['revisar']) if bases[tid]['revisar'] else ''}")
    arq_bases = pasta / f"{chave}_textos_base.json"
    if bases:
        arq_bases.write_text(json.dumps(bases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif arq_bases.exists():
        arq_bases.unlink()


if __name__ == "__main__":
    main()
