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
FOLGA = 3.0           # pontos de margem em volta de cada recorte
JUNTAR = 8.0          # objetos mais próximos que isso viram um recorte só

SOBRESCRITO = str.maketrans("0123456789+-−=()niaxyboc", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ⁿⁱᵃˣʸᵇᵒᶜ")
SUBSCRITO = str.maketrans("0123456789+-−=()aeoxhklmnpstrijuv", "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜᵣᵢⱼᵤᵥ")


def _privado(ch: str) -> bool:
    return any(0xE000 <= ord(c) <= 0xF8FF for c in ch) or "(cid:" in ch


def _decorativo(o, r, chars_pedaco, faixas_cab, ip) -> bool:
    vertical_divisoria = ex.DIVISORIA[0] < o["x0"] < ex.DIVISORIA[1] and o["x1"] - o["x0"] < 1
    no_cabecalho = any(i == ip and a <= o["top"] <= z for i, a, z in faixas_cab)
    horizontal_longo = o["bottom"] - o["top"] < 1.5 and o["x1"] - o["x0"] >= 0.7 * (r[2] - r[0])
    fecho = horizontal_longo and not any(c["top"] > o["bottom"] for c in chars_pedaco)
    fora = (not ex.X_ESQ <= (o["x0"] + o["x1"]) / 2 <= ex.X_DIR
            or not ex.TOPO <= (o["top"] + o["bottom"]) / 2 <= ex.BASE)
    return vertical_divisoria or no_cabecalho or fecho or fora


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
    for o in pg.lines + pg.rects:
        w, h = o["x1"] - o["x0"], o["bottom"] - o["top"]
        if not (h < 1.5 and 3 < w < 80):
            continue
        if not (r[0] <= (o["x0"] + o["x1"]) / 2 <= r[2] and r[1] <= o["top"] <= r[3]):
            continue
        na_largura = [c for c in chars if c["x0"] >= o["x0"] - 1.5 and c["x1"] <= o["x1"] + 1.5]
        num = [c for c in na_largura if 0 <= o["top"] - c["bottom"] < 4.5]
        den = [c for c in na_largura if 0 <= c["top"] - o["bottom"] < 4.5]
        if num and den:
            out.append((o, sorted(num, key=lambda c: c["x0"]), sorted(den, key=lambda c: c["x0"])))
    return out


def _parte(cs):
    t = "".join(c["text"] for c in cs)
    return f"({t})" if re.search(r"[+\-−×·]", t) else t


def _linhas(pg, r):
    """Linhas de texto da região (sem o cabeçalho). Agrupa pela linha de base
    dos caracteres de tamanho normal; índices e expoentes (menores) entram na
    linha a que estão encostados. Um caractere pertence à região em que cai
    o seu centro."""
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
    # frações simples viram texto "num/den" na linha em que o traço está
    insercoes = []
    for o, num, den in _fracoes(pg, r, chars):
        usados = {id(c) for c in num + den}
        chars = [c for c in chars if id(c) not in usados]
        insercoes.append({"text": f"{_parte(num)}/{_parte(den)}", "x0": o["x0"], "x1": o["x1"],
                          "top": o["top"] - tam * 0.7, "bottom": o["top"] + tam * 0.3,
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
    for c in pequenos_cand:
        meio = (c["top"] + c["bottom"]) / 2
        dv = lambda g: abs((g["top"] + g["bottom"]) / 2 - meio)
        ancorados = [g for g in normais + [x for x in pequenos_cand if id(x) in grupo_de]
                     if g is not c and dv(g) < g["size"] * 0.7]
        esq = [g for g in ancorados if -1.0 <= c["x0"] - g["x1"] < 4.0]
        dir_ = [g for g in ancorados if -1.0 <= g["x0"] - c["x1"] < 4.0]
        # vizinho mais provável: perto na horizontal e, sobretudo, na vertical
        viz = (min(esq, key=lambda g: max(0, c["x0"] - g["x1"]) + 2 * dv(g), default=None)
               or min(dir_, key=lambda g: max(0, g["x0"] - c["x1"]) + 2 * dv(g), default=None))
        if viz is not None and id(viz) in grupo_de:
            grupo_de[viz and id(viz)]["chars"].append(c)
            grupo_de[id(c)] = grupo_de[id(viz)]
        else:
            soltos.append(c)
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
            grupos.append({"base": f["bottom"], "chars": [f]})
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
        if re.fullmatch(r"\s*QUESTÃO\s*\d+\s*", texto):
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
    tam = statistics.mode(round(c["size"], 1) for c in normais)
    base = statistics.median(c["bottom"] for c in normais if abs(c["size"] - tam) < 0.6)
    partes, complexa, anterior = [], False, None
    for c in chars:
        t = c["text"]
        if _privado(t):
            complexa = True
        if anterior is not None and c["x0"] - anterior["x1"] > 0.15 * max(anterior["size"], c["size"]):
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
        partes.append(t)
        anterior = c
    texto = re.sub(r" {2,}", " ", "".join(partes)).strip()
    texto = re.sub(r"(?<=[\d)]) (?=[.,;:](?:\s|$))", "", texto)  # "15/60 ." -> "15/60."
    return texto, complexa


FONTE_ALT = ex.FONTE_ALTERNATIVA


def _marcadores(pg, r) -> list[dict]:
    """Letras (A)...(E) das alternativas no pedaço (fonte própria do ENEM;
    em 2023 a letra vem duplicada, fica só uma)."""
    ms = []
    for c in sorted(pg.chars, key=lambda c: (round(c["top"]), c["x0"])):
        if FONTE_ALT in c["fontname"].lower() and c["text"].upper() in "ABCDE" and c["text"].strip() \
                and ex._intersecta(c, r):
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
    # traços finos e curtos (barra de fração, de raiz, sublinhado) são de
    # fórmula; formas pequenas (círculo, quadrado de legenda) são figura
    pequenos = [o for o in vetores if o["x1"] - o["x0"] < 60 and o["bottom"] - o["top"] < 15
                and min(o["x1"] - o["x0"], o["bottom"] - o["top"]) < 1.5]
    objetos += [_caixa(o, r) for o in vetores if o not in pequenos]
    caixas = [c for c in _juntar(objetos) if c[3] - c[1] >= 3]  # traço solto (separador) não é figura
    for o in pequenos:  # pequenos traços encostados num desenho fazem parte dele
        for c in caixas:
            if o["x0"] < c[2] + JUNTAR and o["x1"] > c[0] - JUNTAR and o["top"] < c[3] + JUNTAR and o["bottom"] > c[1] - JUNTAR:
                c[:] = [min(c[0], o["x0"]), min(c[1], o["top"]), max(c[2], o["x1"]), max(c[3], o["bottom"])]
                break
    tracos_fracao = {id(o) for o, _n, _d in _fracoes(pg, r, chars_reg)}
    formulas = [[o["x0"], o["top"] - 1, o["x1"], o["bottom"] + 1] for o in pequenos
                if id(o) not in tracos_fracao and o["bottom"] - o["top"] < 1.5 and o["x1"] - o["x0"] > 3
                and not any(c[1] - 1 <= o["top"] <= c[3] + 1 for c in caixas)]

    def absorver(cx):
        mudou = True
        while mudou:
            mudou = False
            for ln in linhas:
                if not ln.get("usada") and min(ln["bottom"], cx[3]) - max(ln["top"], cx[1]) > 0.4 * (ln["bottom"] - ln["top"]):
                    cx[:] = [min(cx[0], ln["x0"]), min(cx[1], ln["top"]), max(cx[2], ln["x1"]), max(cx[3], ln["bottom"])]
                    ln["usada"] = mudou = True

    tam_reg = statistics.median(c["size"] for c in chars_reg) if chars_reg else None
    # margens do bloco de texto (linhas de tamanho normal), não da região
    normais_reg = [ln for ln in linhas if tam_reg and statistics.median(c["size"] for c in ln["chars"]) >= tam_reg * 0.95]
    bloco_x0 = min([ln["x0"] for ln in normais_reg] or [r[0]])
    bloco_x1 = max([ln["x1"] for ln in normais_reg] or [r[2]])
    itens = []
    for c in caixas:
        absorver(c)
        itens.append((c[1], "figura", (c, "figura")))
    for f in _juntar(formulas):
        if any(f[1] < c[3] and f[3] > c[1] for _, t, (c, _m) in itens):
            continue
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
    for ln in linhas:
        if ln.get("usada"):
            continue
        texto, complexa = _texto_linha(ln)
        if complexa:
            itens.append((ln["top"], "figura", ([ln["x0"], ln["top"], ln["x1"], ln["bottom"]], "fórmula")))
            revisar.add("fórmula recortada como imagem")
        else:
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
    ocup = []
    for o in pg.chars + pg.images + pg.lines + pg.rects + pg.curves:
        if o.get("object_type") == "char" and not o["text"].strip():
            continue
        if o["x1"] > x0 and o["x0"] < x1 and o["bottom"] > a["top"] and o["top"] < b["top"]:
            ocup.append((max(o["top"], a["top"]), min(o["bottom"], b["top"])))
    ocup.sort()
    melhor, y = (0.0, (a["top"] + b["top"]) / 2), a["top"]
    for t, fim in ocup:
        if t - y > melhor[0]:
            melhor = (t - y, (t + y) / 2)
        y = max(y, fim)
    if b["top"] - y > melhor[0]:
        melhor = (b["top"] - y, (b["top"] + y) / 2)
    return melhor[1]


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
            topo = _fronteira(pg, col[i - 1], m, m["x0"], direita) if i else max(topo_texto, m["top"] - passo / 2)
            base = _fronteira(pg, m, col[i + 1], m["x0"], direita) if i + 1 < len(col) else r[3]
            zonas[m["letra"]] = (m, [m["x1"] + 0.5, topo, direita, base])
    return zonas


def estruturar(pdf, q: dict, pasta_img: Path, prefixo: str) -> dict:
    faixas_cab = [(ip, h["top"] - 3, h["bottom"] + 8) for ip, h in q["cabecalhos"]]
    revisar: set[str] = set()
    blocos, alternativas, alt_img = [], {}, {}
    n_fig = [0]

    def recortar(ip, c):
        n_fig[0] += 1
        nome = f"{prefixo}_f{n_fig[0]}.png"
        pg = pdf.pages[ip]
        caixa = (max(0, c[0] - FOLGA), max(0, c[1] - FOLGA), min(pg.width, c[2] + FOLGA), min(pg.height, c[3] + FOLGA))
        img = pg.crop(caixa).to_image(resolution=RESOLUCAO).original.convert("RGB")
        (pasta_img).mkdir(parents=True, exist_ok=True)
        img.save(pasta_img / nome, optimize=True)
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
        linhas_acima = [ln for ln in _linhas(pg, (r[0], r[1], r[2], topo_alt - 1))]
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
    if sorted(alternativas) != list("ABCDE"):
        revisar.add("alternativas incompletas: conferir com a imagem original")
    for b in blocos:
        if b["tipo"] == "texto":
            b["texto"] = re.sub(r"\n{3,}", "\n\n", b["texto"]).strip("\n")
            b["texto"] = re.sub(r"\n?(CIÊNCIAS DA NATUREZA|MATEMÁTICA|LINGUAGENS|CIÊNCIAS HUMANAS)[^\n]*Questões de \d+ a \d+\s*$", "", b["texto"]).strip()
    blocos = [b for b in blocos if b["tipo"] != "texto" or b["texto"]]
    return {"blocos": blocos, "alternativas": alternativas, "alternativas_imagem": alt_img, "revisar": sorted(revisar)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ano", type=int, required=True)
    ap.add_argument("--dia", type=int, choices=(1, 2), required=True)
    ap.add_argument("--caderno", type=int, required=True)
    ap.add_argument("--aplicacao", choices=tuple(ex.APLICACOES), default="regular")
    ap.add_argument("--questoes", help="números separados por vírgula (padrão: todas com imagem); 1-ingles para a língua")
    a = ap.parse_args()

    trecho, _ = ex.APLICACOES[a.aplicacao]
    chave = f"{a.aplicacao}_D{a.dia}_CD{a.caderno}"
    pdf_arq = ex.CACHE / str(a.ano) / f"{a.ano}_PV_{trecho}_D{a.dia}_CD{a.caderno}.pdf"
    bruto = pdfplumber.open(str(pdf_arq))
    ex.configurar_geometria(bruto)
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


if __name__ == "__main__":
    main()
