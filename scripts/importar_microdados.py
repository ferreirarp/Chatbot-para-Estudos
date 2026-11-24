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

Gera:
  data/enem/oficial/<ano>_<aplicacao>_D<dia>_CD<caderno>.json
  data/enem/matriz_referencia.json   (texto das habilidades H1–H30 por área)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
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

    for arq in sorted((DADOS / str(ano)).glob("*_D*_CD*.json")):
        questoes = json.loads(arq.read_text(encoding="utf-8"))
        saida = {"prova": f"{ano}/{arq.stem}", "fonte": URL_MICRODADOS.format(ano=ano),
                 "codigos_prova": {}, "questoes": {}}
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
            iguais = [c for a, c in candidatos if a == len(esperado)]
            cod = iguais[0]
            saida["codigos_prova"][sigla] = iguais
            for q in qs:
                r = por_prova[cod][chave_questao(q)]
                b = float(r["NU_PARAM_B"]) if r["NU_PARAM_B"] else None
                saida["questoes"][chave_questao(q)] = {
                    "co_item": r["CO_ITEM"],
                    "habilidade": f"H{int(r['CO_HABILIDADE'])}" if r["CO_HABILIDADE"] else None,
                    "param_a": float(r["NU_PARAM_A"]) if r["NU_PARAM_A"] else None,
                    "param_b": b,
                    "param_c": float(r["NU_PARAM_C"]) if r["NU_PARAM_C"] else None,
                    "nota_equivalente": round(500 + 100 * b) if b is not None else None,
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
