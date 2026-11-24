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
from extrair_enem import (  # noqa: E402  (reaproveita download e gabarito)
    BASE_DOWNLOAD, CACHE, RAIZ, baixar, contexto_ssl, ler_gabarito, normalizar_resposta,
)

logging.getLogger("pdfminer").setLevel(logging.ERROR)

SAIDA = RAIZ / "data" / "enem"
RESOLUCAO = 150  # dpi das imagens recortadas

# Geometria do caderno do ENEM (pontos PDF; página 567 x 780). Medida em 2023.
TOPO, BASE = 60.0, 740.0            # abaixo do cabeçalho da página, acima do rodapé
X_ESQ, X_DIR = 25.0, 545.0          # margens laterais do conteúdo
DIVISORIA = (280.0, 288.0)          # faixa da linha vertical entre as colunas
MARGEM = 2.0

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
    # aplicação: (trecho do nome do arquivo no INEP, rótulo)
    "regular": ("impresso", "Aplicação regular"),
    "reaplicacao": ("reaplicacao_PPL", "Reaplicação"),
}
SIMBOLOS_FORMULA = set("√∑∫∞≤≥≠≈±×÷πΔ∆θλμσΩωαβγ⋅·∙")
FONTES_FORMULA = ("symbol", "math", "cambria", "euclid", "mt extra", "mtextra")
FONTE_ALTERNATIVA = "bundesbahnpi"   # fonte dos marcadores (A)...(E)


def area_da_questao(dia: int, numero: int) -> str:
    for (d, area), faixa in AREAS.items():
        if d == dia and numero in faixa:
            return area
    return "?"


# --------------------------------------------------------------- segmentação
def zonas_da_pagina(pagina) -> list[tuple[float, float, float, float]]:
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


def cabecalhos(pagina) -> list[dict]:
    palavras = pagina.extract_words(extra_attrs=["fontname"])
    achados = []
    for i, w in enumerate(palavras[:-1]):
        prox = palavras[i + 1]
        if w["text"] == "QUESTÃO" and "bold" in w["fontname"].lower() and prox["text"].isdigit():
            achados.append({"numero": int(prox["text"]), "x0": w["x0"], "top": w["top"],
                            "bottom": w["bottom"]})
    return achados


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


def titulos_de_secao(pagina) -> list[dict]:
    """Títulos como "Questões de 01 a 05 (opção espanhol)" ou "MATEMÁTICA E
    SUAS TECNOLOGIAS / Questões de 136 a 180". Encerram a questão anterior."""
    palavras = pagina.extract_words(extra_attrs=["fontname"])
    achados = []
    for i, w in enumerate(palavras[:-2]):
        if w["text"] == "Questões" and palavras[i + 1]["text"] == "de" and palavras[i + 2]["text"].isdigit():
            topo = w["top"]
            # inclui o nome da área em maiúsculas logo acima, se houver
            acima = [p for p in palavras if w["top"] - 30 <= p["top"] < w["top"] - 2
                     and p["text"].isupper() and len(p["text"]) > 2
                     and abs(p["x0"] - w["x0"]) < 260 and "bold" in p["fontname"].lower()]
            if acima:
                topo = min(p["top"] for p in acima)
            achados.append({"x0": w["x0"], "top": topo})
    return achados


def pedaco_vazio(pagina, caixa) -> bool:
    x0, t, x1, b = caixa
    dentro = lambda o: o["x1"] > x0 and o["x0"] < x1 and o["bottom"] > t and o["top"] < b
    tem_texto = any(dentro(c) and c["text"].strip() for c in pagina.chars)
    tem_figura = any(dentro(o) for o in pagina.images + pagina.curves + pagina.rects
                     if (o["x1"] - o["x0"]) > 3 or (o["bottom"] - o["top"]) > 3)
    return not tem_texto and not tem_figura


def segmentar(pdf) -> list[dict]:
    """Retorna as questões em ordem de leitura, cada uma com seus pedaços
    (página, retângulo) e a posição dos seus cabeçalhos."""
    questoes: list[dict] = []
    atual = None
    for ip, pagina in enumerate(pdf.pages):
        if e_pagina_de_redacao(pagina):
            atual = None  # a questão anterior termina antes da redação
            continue
        heads = cabecalhos(pagina)
        if not heads and atual is None:
            continue  # capa / instruções
        titulos = titulos_de_secao(pagina)
        for (x0, t, x1, b) in zonas_da_pagina(pagina):
            eventos = sorted(
                [(h["top"], "questao", h) for h in heads if x0 - 8 <= h["x0"] <= x1 and t - 2 <= h["top"] < b]
                + [(ti["top"], "titulo", None) for ti in titulos if x0 - 8 <= ti["x0"] <= x1 and t - 2 <= ti["top"] < b],
                key=lambda e: e[0])
            cortes = [t] + [e[0] for e in eventos] + [b]
            for k in range(len(cortes) - 1):
                if k > 0:
                    _, tipo, h = eventos[k - 1]
                    if tipo == "titulo":
                        atual = None  # título de seção: o que vem até a próxima questão não é de ninguém
                        continue
                    atual = {"numero": h["numero"], "pedacos": [], "cabecalhos": []}
                    atual["cabecalhos"].append((ip, h))
                    questoes.append(atual)
                if atual is not None and cortes[k + 1] - cortes[k] > 4:
                    caixa = (x0, cortes[k], x1, cortes[k + 1])
                    if k == 0 and e_titulo_de_area(pagina.crop(caixa).extract_text() or ""):
                        continue
                    if k == 0 and pedaco_vazio(pagina, caixa):
                        continue  # sobra sem conteúdo antes de um título ou no topo da coluna
                    atual["pedacos"].append((ip, (x0, cortes[k] - MARGEM if k else cortes[k],
                                                  x1, cortes[k + 1] - MARGEM)))
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
            return vertical_divisoria or no_cabecalho or fecho

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
    pedacos: dict[int, list] = {}
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
            if not c["text"].strip() or c["top"] < TOPO or c["bottom"] > BASE + 2:
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
        if fora and re.fullmatch(r"[A-ZÀ-Ý ,]*Questões ?de ?\d+ ?a ?\d+.{0,40}",
                                 texto_fora.replace("Questõesde", "Questões de")):
            fora = []  # só o título de área
        if fora:
            amostra = "".join(c["text"] for c in fora[:40])
            problemas.append(f"página {ip + 1}: {len(fora)} caracteres fora de qualquer questão: {amostra!r}")
        if duplo:
            problemas.append(f"página {ip + 1}: {len(duplo)} caracteres em duas questões")
        # Figuras e desenhos não podem ser cortados pela borda de um recorte.
        pg = pdf.pages[ip]
        for o in pg.images + pg.curves + pg.rects:
            if o["top"] < TOPO or o["bottom"] > BASE:
                continue
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
    blocos = []
    for ip, r in q["pedacos"]:
        t = pdf.pages[ip].crop(r).extract_text(layout=False) or ""
        blocos.append(t)
    linhas = "\n".join(blocos).split("\n")
    # remove o cabeçalho "QUESTÃO N" e títulos de seção
    linhas = [l for l in linhas if not re.fullmatch(r"\s*QUESTÃO\s+\d+\s*", l)]
    corpo, alternativas, atual = [], {}, None
    for l in linhas:
        m = re.match(r"^\s*([A-E])\1\s?(.*)$", l)  # marcador duplicado "AA texto"
        if m and (atual is None and m.group(1) == "A" or atual and ord(m.group(1)) == ord(atual) + 1):
            atual = m.group(1)
            alternativas[atual] = m.group(2).strip()
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
    trecho, rotulo_aplicacao = APLICACOES[aplicacao]
    nome_prova = f"{ano}_PV_{trecho}_D{dia}_CD{caderno}.pdf"
    nome_gab = f"{ano}_GB_{trecho}_D{dia}_CD{caderno}.pdf"
    chave = f"{aplicacao}_D{dia}_CD{caderno}"
    prova = baixar(BASE_DOWNLOAD + nome_prova, CACHE / str(ano) / nome_prova, ctx)
    gab = ler_gabarito(baixar(BASE_DOWNLOAD + nome_gab, CACHE / str(ano) / nome_gab, ctx))

    pdf = pdfplumber.open(str(prova))
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
            "elementos_visuais": visuais,
            "imagem": imagem,
            "texto_fiel": not visuais,
            "alertas": alertas,
            "fonte": {"prova": BASE_DOWNLOAD + nome_prova, "gabarito": BASE_DOWNLOAD + nome_gab},
        })

    alertas_gerais += verificar_cobertura(pdf, questoes)

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
