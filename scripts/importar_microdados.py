#!/usr/bin/env python3
"""Importa dos Microdados do ENEM (INEP) os dados oficiais de cada questão:
habilidade da Matriz de Referência, parâmetros da TRI (dificuldade b,
discriminação a, acerto ao acaso c) e se a questão foi descartada da nota.

    python scripts/importar_microdados.py --ano 2023

O pacote de microdados tem centenas de MB; o script baixa por partes (HTTP
Range) só o ITENS_PROVA_<ano>.csv e a Matriz de Referência.

Para cada prova já extraída em data/enem/<ano>/, descobre o código da prova
nos microdados (CO_PROVA) comparando o gabarito questão a questão: só aceita
um código cujo gabarito bate com 100% das questões da área.

Também estima, para cada área, a conversão da proficiência (θ) para a nota
do ENEM daquele ano: nota = k·θ + m. O INEP calcula θ por EAP (TRI de 3
parâmetros, priori normal padrão, 40 pontos de quadratura); k e m variam por
área e ano e não vêm publicados, então são obtidos por regressão sobre uma
amostra de candidatos dos microdados e validados em outra amostra. Em 2023 o
erro máximo de reprodução da nota oficial foi de 0,05 ponto.

Gera:
  data/enem/oficial/<ano>_<aplicacao>_D<dia>_CD<caderno>.json
  data/enem/oficial/<ano>_escala_notas.json   (k e m por área)
  data/enem/matriz_referencia.json   (texto das habilidades H1–H30 por área)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import statistics
import ssl
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extrair_enem import CACHE, RAIZ, contexto_ssl  # noqa: E402

DADOS = RAIZ / "data" / "enem"
URL_MICRODADOS = "https://download.inep.gov.br/microdados/microdados_enem_{ano}.zip"
SIGLA = {
    "Linguagens, Códigos e suas Tecnologias": "LC",
    "Ciências Humanas e suas Tecnologias": "CH",
    "Ciências da Natureza e suas Tecnologias": "CN",
    "Matemática e suas Tecnologias": "MT",
}
ORDEM_MATRIZ = ["LC", "MT", "CN", "CH"]  # ordem dos blocos H1–H30 no PDF da matriz
LINGUA = {"0": "ingles", "1": "espanhol"}


# ------------------------------------------------------------ zip remoto
class ArquivoRemoto(io.RawIOBase):
    """Arquivo HTTP com leitura por partes, para abrir um .zip sem baixá-lo."""

    def __init__(self, url: str, ctx: ssl.SSLContext):
        self.url, self.ctx, self.pos = url, ctx, 0
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), context=ctx) as r:
            self.tamanho = int(r.headers["Content-Length"])

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.tamanho + off
        return self.pos

    def readinto(self, b):
        n = min(len(b), self.tamanho - self.pos)
        if n <= 0:
            return 0
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{self.pos + n - 1}"})
        with urllib.request.urlopen(req, context=self.ctx, timeout=120) as r:
            dados = r.read()
        b[:len(dados)] = dados
        self.pos += len(dados)
        return len(dados)


def extrair_do_zip(ano: int, padrao: str, destino: Path, ctx) -> Path:
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    z = zipfile.ZipFile(io.BufferedReader(ArquivoRemoto(URL_MICRODADOS.format(ano=ano), ctx), 1 << 20))
    alvo = next((i for i in z.infolist() if not i.is_dir() and re.search(padrao, i.filename, re.I)), None)
    if alvo is None:
        sys.exit(f"{padrao!r} não encontrado nos microdados de {ano}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(z.read(alvo))
    return destino


# ------------------------------------------------- escala de notas (θ → nota)
PONTOS = [-4 + 8 * i / 39 for i in range(40)]  # 40 pontos de quadratura
PRIORI = [math.exp(-t * t / 2) for t in PONTOS]  # normal padrão


def theta_eap(itens: list[tuple[float, float, float]], acertos: list[bool]) -> float:
    """Proficiência por EAP (TRI 3PL, D = 1), como no cálculo oficial."""
    num = den = 0.0
    for t, w in zip(PONTOS, PRIORI):
        L = w
        for (a, b, c), x in zip(itens, acertos):
            p = c + (1 - c) / (1 + math.exp(-a * (t - b)))
            L *= p if x else 1 - p
        num += t * L
        den += L
    return num / den


def amostra_participantes(ano: int, ctx, linhas: int = 60000) -> Path:
    destino = CACHE / str(ano) / "microdados" / f"participantes_amostra_{linhas}.csv"
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    z = zipfile.ZipFile(io.BufferedReader(ArquivoRemoto(URL_MICRODADOS.format(ano=ano), ctx), 1 << 20))
    # até 2023: MICRODADOS_ENEM_<ano>.csv; desde 2024 as respostas e notas
    # ficam em RESULTADOS_<ano>.csv (o perfil foi para PARTICIPANTES_<ano>.csv)
    info = next(i for i in z.infolist() if re.search(rf"(MICRODADOS_ENEM|RESULTADOS)_{ano}\.csv$", i.filename))
    destino.parent.mkdir(parents=True, exist_ok=True)
    with z.open(info) as f, destino.open("wb") as out:
        for i, linha in enumerate(f):
            out.write(linha)
            if i >= linhas:
                break
    return destino


def pares_theta_nota(sigla: str, codigos: list[str], por_prova: dict, participantes: list[dict], limite: int):
    pares = []
    for p in participantes:
        cod, nota, resp = p.get(f"CO_PROVA_{sigla}"), p.get(f"NU_NOTA_{sigla}"), p.get(f"TX_RESPOSTAS_{sigla}")
        if cod not in codigos or not nota or not resp or float(nota) <= 0:
            continue
        lingua = LINGUA.get(p.get("TP_LINGUA", "")) if sigla == "LC" else None
        linhas = sorted(
            (r for k, r in por_prova[cod].items() if "-" not in k or k.endswith(f"-{lingua}")),
            key=lambda r: int(r["CO_POSICAO"]))
        if len(linhas) != len(resp):
            continue  # formato do vetor de respostas diferente do esperado
        usar = [(r, resp[i]) for i, r in enumerate(linhas)
                if r["IN_ITEM_ABAN"] != "1" and r["TX_GABARITO"] in "ABCDE"]
        itens = [(float(r["NU_PARAM_A"]), float(r["NU_PARAM_B"]), float(r["NU_PARAM_C"])) for r, _ in usar]
        pares.append((theta_eap(itens, [x == r["TX_GABARITO"] for r, x in usar]), float(nota)))
        if len(pares) >= limite:
            break
    return pares


def validar_prova(sigla, codigos, escala, por_prova, participantes) -> dict:
    """Confere a escala da área nos candidatos que fizeram ESTA prova."""
    pares = pares_theta_nota(sigla, codigos, por_prova, participantes, 500)
    if not pares:
        return {"candidatos": 0}
    erros = [abs(escala["k"] * t + escala["m"] - y) for t, y in pares]
    return {"candidatos": len(pares), "erro_maximo": round(max(erros), 3),
            "acima_de_1_ponto": sum(e > 1.0 for e in erros)}


def amostra_dirigida(ano: int, ctx, codigos: dict[str, set], minimo: int = 40,
                     max_linhas: int = 6_000_000) -> Path:
    """Percorre o arquivo de resultados até juntar `minimo` candidatos de cada
    código pedido (provas com poucos participantes, como a reaplicação)."""
    chave = "_".join(sorted(c for cs in codigos.values() for c in cs))
    destino = CACHE / str(ano) / "microdados" / f"amostra_codigos_{chave}.csv"
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    z = zipfile.ZipFile(io.BufferedReader(ArquivoRemoto(URL_MICRODADOS.format(ano=ano), ctx), 1 << 20))
    info = next(i for i in z.infolist() if re.search(rf"(MICRODADOS_ENEM|RESULTADOS)_{ano}\.csv$", i.filename))
    contagem = {(a, c): 0 for a, cs in codigos.items() for c in cs}
    with z.open(info) as f, destino.open("wb") as out:
        cab = f.readline()
        out.write(cab)
        nomes = cab.decode("latin-1").strip().split(";")
        idx = {a: nomes.index(f"CO_PROVA_{a}") for a in codigos}
        for n, linha in enumerate(f):
            campos = linha.decode("latin-1").split(";")
            util = False
            for a, i in idx.items():
                k = (a, campos[i])
                if k in contagem and contagem[k] < minimo:
                    contagem[k] += 1
                    util = True
            if util:
                out.write(linha)
            if all(v >= minimo for v in contagem.values()) or n > max_linhas:
                break
    print(f"  amostra dirigida: {dict((f'{a}:{c}', v) for (a, c), v in contagem.items())} ({n + 1} linhas lidas)")
    return destino


def estimar_escala(sigla: str, codigos: list[str], por_prova: dict, participantes: list[dict]) -> dict | None:
    """Ajusta nota = k·θ + m para uma área e valida em candidatos não usados."""
    pares = pares_theta_nota(sigla, codigos, por_prova, participantes, 3000)
    if len(pares) < 600:
        print(f"  escala {sigla}: candidatos insuficientes na amostra ({len(pares)})")
        return None
    ajuste, teste = pares[: len(pares) // 2], pares[len(pares) // 2:]
    mx = statistics.mean(t for t, _ in ajuste)
    my = statistics.mean(y for _, y in ajuste)
    k = sum((t - mx) * (y - my) for t, y in ajuste) / sum((t - mx) ** 2 for t, _ in ajuste)
    m = my - k * mx
    # Ajuste robusto: descarta os poucos casos extremos (nota máxima, em que a
    # integração numérica fica no limite de θ = 4) e refaz a regressão.
    residuos = [abs(k * t + m - y) for t, y in ajuste]
    limpos = [par for par, r in zip(ajuste, residuos) if r <= 1.0]
    if len(limpos) >= 0.99 * len(ajuste):
        mx = statistics.mean(t for t, _ in limpos)
        my = statistics.mean(y for _, y in limpos)
        k = sum((t - mx) * (y - my) for t, y in limpos) / sum((t - mx) ** 2 for t, _ in limpos)
        m = my - k * mx
    erros = sorted(abs(k * t + m - y) for t, y in teste)
    fora = sum(e > 1.0 for e in erros)
    escala = {"k": round(k, 4), "m": round(m, 4), "n_ajuste": len(ajuste), "n_validacao": len(teste),
              "erro_mediano": round(statistics.median(erros), 3), "erro_maximo": round(erros[-1], 3),
              "acima_de_1_ponto": fora}
    if fora > 0.005 * len(erros):
        print(f"  escala {sigla}: reprodução imprecisa ({fora} de {len(erros)} candidatos com erro > 1 ponto); não usada")
        return None
    return escala


# ------------------------------------------------------------- matriz
def ler_matriz(pdf: Path) -> dict:
    texto = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    matriz: dict[str, dict] = {}
    bloco, atual, competencia = -1, None, None
    for linha in texto.splitlines():
        l = linha.strip()
        m_comp = re.match(r"^Competência de área (\d+)\s*[-–]\s*(.*)$", l)
        m_hab = re.match(r"^H(\d+)\s*[-–]\s*(.*)$", l)
        if m_comp:
            atual = None
            competencia = {"numero": int(m_comp.group(1)), "texto": m_comp.group(2)}
            continue
        if m_hab:
            h = int(m_hab.group(1))
            if h == 1:
                bloco += 1
            area = ORDEM_MATRIZ[bloco]
            atual = {"texto": m_hab.group(2), "competencia": dict(competencia or {})}
            matriz.setdefault(area, {})[f"H{h}"] = atual
            continue
        if not l:
            atual = None
            competencia = competencia if competencia and competencia.get("_fechada") else competencia
            continue
        if atual is not None:
            atual["texto"] += " " + l
        elif competencia is not None and not m_hab and len(competencia["texto"]) < 400 and atual is None:
            competencia["texto"] += " " + l
    for area in matriz.values():
        for hab in area.values():
            hab["texto"] = re.sub(r"\s+", " ", hab["texto"]).strip()
            hab["competencia"]["texto"] = re.sub(r"\s+", " ", hab["competencia"].get("texto", "")).strip()
    faltando = {a: 30 - len(matriz.get(a, {})) for a in ORDEM_MATRIZ if len(matriz.get(a, {})) != 30}
    if faltando:
        sys.exit(f"Matriz de referência incompleta: {faltando}")
    return matriz


# ------------------------------------------------------- associação
def chave_questao(q: dict) -> str:
    return f"{q['numero']}" + (f"-{q['lingua_estrangeira']}" if q.get("lingua_estrangeira") else "")


def importar(ano: int) -> None:
    ctx = contexto_ssl()
    pasta_cache = CACHE / str(ano) / "microdados"
    itens_csv = extrair_do_zip(ano, rf"ITENS_PROVA_{ano}\.csv$", pasta_cache / f"ITENS_PROVA_{ano}.csv", ctx)
    matriz_pdf = extrair_do_zip(ano, r"matriz_referencia.*\.pdf$", pasta_cache / "matriz_referencia_enem.pdf", ctx)

    matriz = ler_matriz(matriz_pdf)
    (DADOS / "matriz_referencia.json").write_text(json.dumps(matriz, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    itens = list(csv.DictReader(itens_csv.open(encoding="latin-1"), delimiter=";"))
    por_prova: dict[str, dict[str, dict]] = {}
    for r in itens:
        k = r["CO_POSICAO"] + (f"-{LINGUA[r['TP_LINGUA']]}" if r["TP_LINGUA"] in LINGUA else "")
        por_prova.setdefault(r["CO_PROVA"], {})[k] = r

    # 1ª passagem: associar provas a códigos; 2ª: escala por área; 3ª: gravar.
    associacoes = []
    for arq in sorted((DADOS / str(ano)).glob("*_D*_CD*.json")):
        questoes = json.loads(arq.read_text(encoding="utf-8"))
        associacoes.append((arq, questoes, associar(arq, questoes, por_prova)))

    codigos_area: dict[str, set] = {}
    for _, _, cods in associacoes:
        for sigla, lista in cods.items():
            codigos_area.setdefault(sigla, set()).update(lista)
    participantes = list(csv.DictReader(amostra_participantes(ano, ctx).open(encoding="latin-1"), delimiter=";"))
    escalas = {}
    for sigla, cods in sorted(codigos_area.items()):
        e = estimar_escala(sigla, sorted(cods), por_prova, participantes)
        if e:
            escalas[sigla] = e
            print(f"escala {sigla} {ano}: nota = {e['k']:.2f}·θ + {e['m']:.2f} "
                  f"(validação em {e['n_validacao']} candidatos: erro mediano {e['erro_mediano']}, máx {e['erro_maximo']})")
    destino_escala = DADOS / "oficial" / f"{ano}_escala_notas.json"
    destino_escala.parent.mkdir(parents=True, exist_ok=True)
    destino_escala.write_text(json.dumps({"ano": ano, "modelo": "TRI 3PL, D=1, EAP, priori N(0,1), 40 pontos em [-4, 4]; nota = k*theta + m",
                                          "areas": escalas}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # Provas sem candidatos na amostra padrão: busca dirigida no arquivo completo.
    faltam: dict[str, set] = {}
    for _, _, cods in associacoes:
        for sigla, lista in cods.items():
            # menos de 20 candidatos não basta para conferir a escala da prova
            if sum(p.get(f"CO_PROVA_{sigla}") in lista for p in participantes) < 20:
                faltam.setdefault(sigla, set()).update(lista)
    if faltam:
        extra = amostra_dirigida(ano, ctx, faltam)
        participantes += list(csv.DictReader(extra.open(encoding="latin-1"), delimiter=";"))

    for arq, questoes, cods in associacoes:
        validacao = {}
        for sigla, lista in cods.items():
            if sigla in escalas:
                v = validar_prova(sigla, lista, escalas[sigla], por_prova, participantes)
                validacao[sigla] = v
                ok = v["candidatos"] == 0 or v["acima_de_1_ponto"] <= max(1, 0.005 * v["candidatos"])
                print(f"  {arq.stem} {sigla}: escala conferida em {v['candidatos']} candidatos desta prova"
                      + (f", erro máx {v['erro_maximo']}, acima de 1 ponto: {v['acima_de_1_ponto']}"
                         if v["candidatos"] else " (nenhum na amostra)")
                      + ("" if ok else "  <- ATENÇÃO: escala não reproduz as notas desta prova"))
        gravar(ano, arq, questoes, cods, por_prova, escalas, validacao)


def associar(arq: Path, questoes: list[dict], por_prova: dict) -> dict[str, list[str]]:
    codigos = {}
    for area_nome, sigla in SIGLA.items():
        qs = [q for q in questoes if q["area"] == area_nome]
        if not qs:
            continue
        esperado = {chave_questao(q): ("X" if q["anulada"] else q["gabarito"]) for q in qs}
        candidatos = []
        for cod, linhas in por_prova.items():
            if not linhas or next(iter(linhas.values()))["SG_AREA"] != sigla:
                continue
            acertos = sum(1 for k, g in esperado.items() if k in linhas and linhas[k]["TX_GABARITO"] == g)
            candidatos.append((acertos, cod))
        candidatos.sort(reverse=True)
        if not candidatos or candidatos[0][0] != len(esperado):
            melhor = candidatos[0] if candidatos else (0, None)
            print(f"  {arq.name} {sigla}: nenhum código bate 100% (melhor {melhor[1]}: {melhor[0]}/{len(esperado)})")
            continue
        codigos[sigla] = [c for a, c in candidatos if a == len(esperado)]
    return codigos


def gravar(ano, arq, questoes, codigos, por_prova, escalas, validacao=None) -> None:
    saida = {"prova": f"{ano}/{arq.stem}", "fonte": URL_MICRODADOS.format(ano=ano),
             "codigos_prova": codigos, "validacao_escala": validacao or {}, "questoes": {}}
    for area_nome, sigla in SIGLA.items():
        if sigla not in codigos:
            continue
        cod = codigos[sigla][0]
        esc = escalas.get(sigla)
        for q in [q for q in questoes if q["area"] == area_nome]:
            r = por_prova[cod][chave_questao(q)]
            b = float(r["NU_PARAM_B"]) if r["NU_PARAM_B"] else None
            saida["questoes"][chave_questao(q)] = {
                "co_item": r["CO_ITEM"],
                "habilidade": f"H{int(r['CO_HABILIDADE'])}" if r["CO_HABILIDADE"] else None,
                "param_a": float(r["NU_PARAM_A"]) if r["NU_PARAM_A"] else None,
                "param_b": b,
                "param_c": float(r["NU_PARAM_C"]) if r["NU_PARAM_C"] else None,
                # nota na escala do ENEM em que a questão está "no meio" (b)
                "nota_equivalente": round(esc["k"] * b + esc["m"]) if (b is not None and esc) else None,
                "descartada_da_nota": r["IN_ITEM_ABAN"] == "1",
                "motivo_descarte": r["TX_MOTIVO_ABAN"] or None,
                "item_adaptado": r["IN_ITEM_ADAPTADO"] == "1",
            }
    destino = DADOS / "oficial" / f"{ano}_{arq.stem}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(saida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n = len(saida["questoes"])
    desc = [k for k, v in saida["questoes"].items() if v["descartada_da_nota"]]
    print(f"{arq.name}: {n}/{len(questoes)} questões associadas; códigos {saida['codigos_prova']}; "
          f"descartadas da nota: {desc} -> {destino.relative_to(RAIZ)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ano", type=int, required=True)
    importar(ap.parse_args().ano)


if __name__ == "__main__":
    main()
