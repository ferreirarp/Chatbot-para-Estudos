#!/usr/bin/env python3
"""Comentários (feedback padrão) das questões: validação e publicação.

    python scripts/comentarios.py            # valida e gera os .js da interface
    python scripts/comentarios.py --pendentes 2025_regular_D2_CD7   # lista o que falta

Fonte: data/enem/comentarios/<ano>_<prova>.json  ->  {"<numero>[-lingua]": ficha}
Saída: data/enem/comentarios/<ano>_<prova>.js     (carregado sob demanda pela página)

Ficha (7 comentários + recursos):
{
  "enunciado":   "o que o enunciado diz, destrinchado",
  "correta":     "por que a alternativa do gabarito está certa",
  "distratores": {"A": "...", ...}      # as 4 alternativas erradas, uma a uma
  "analise":     "objetivo da questão, o que facilita e o que dificulta",
  "recursos": [{"titulo", "url", "tipo", "trecho", "credito"?}],
  "classificacao": [{"disciplina", "conteudo", "topico", "subtopico"}],
  "fontes_consultadas": ["url", ...],   # comentários e materiais lidos na pesquisa
  "pesquisado_em": "AAAA-MM-DD",
  "revisado": false                     # true depois de conferência humana
}
Texto: parágrafos separados por linha em branco; **negrito**, _itálico_ e
links [texto](https://...). Os comentários são redigidos a partir da
pesquisa, nunca copiados de terceiros; as fontes vão em "recursos".

tipo de recurso: comentario | video | artigo | wikipedia | imagem | dados | apostila | simulador
trecho: enunciado | correta | A-E | analise   (onde o recurso aparece)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "data" / "enem" / "comentarios"
TIPOS = {"comentario", "video", "artigo", "wikipedia", "imagem", "dados", "apostila", "simulador"}
TRECHOS = {"enunciado", "correta", "analise", *"ABCDE"}
RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")

sys.path.insert(0, str(Path(__file__).resolve().parent))


def questoes_da_prova(nome: str) -> dict:
    ano, prova = nome.split("_", 1)
    lista = json.loads((RAIZ / "data" / "enem" / ano / f"{prova}.json").read_text(encoding="utf-8"))
    return {str(q["numero"]) + (f"-{q['lingua_estrangeira']}" if q.get("lingua_estrangeira") else ""): q for q in lista}


def validar(nome: str, fichas: dict) -> list[str]:
    from gerar_banco import validar_item
    erros = []
    qs = questoes_da_prova(nome)
    for chave, f in fichas.items():
        q = qs.get(chave)
        onde = f"{nome} {chave}"
        if q is None:
            erros.append(f"{onde}: questão não existe")
            continue
        for campo in ("enunciado", "correta", "analise"):
            if not (f.get(campo) or "").strip():
                erros.append(f"{onde}: falta '{campo}'")
        if q.get("anulada"):
            esperadas = set("ABCDE")
        else:
            esperadas = set("ABCDE") - {q["gabarito"]}
        dist = f.get("distratores") or {}
        if set(dist) != esperadas or not all((v or "").strip() for v in dist.values()):
            erros.append(f"{onde}: distratores devem ser {sorted(esperadas)}, vieram {sorted(dist)}")
        textos = [f.get("enunciado", ""), f.get("correta", ""), f.get("analise", ""), *dist.values()]
        for t in textos:
            for _, url in RE_LINK.findall(t or ""):
                if not url.startswith("https://"):
                    erros.append(f"{onde}: link sem https: {url}")
        for r in f.get("recursos") or []:
            if not str(r.get("url", "")).startswith("https://"):
                erros.append(f"{onde}: recurso sem https: {r.get('url')}")
            if r.get("tipo") not in TIPOS:
                erros.append(f"{onde}: tipo de recurso inválido: {r.get('tipo')}")
            if r.get("trecho") not in TRECHOS:
                erros.append(f"{onde}: trecho inválido: {r.get('trecho')}")
            if r.get("tipo") == "imagem" and not r.get("credito"):
                erros.append(f"{onde}: imagem sem crédito/licença")
        for item in f.get("classificacao") or []:
            p = validar_item(item)
            if p:
                erros.append(f"{onde}: classificação: {p}")
        if not f.get("classificacao"):
            erros.append(f"{onde}: falta a classificação")
    return erros


def gerar_js(nome: str, fichas: dict) -> Path:
    ano, prova = nome.split("_", 1)
    por_id = {}
    for chave, f in fichas.items():
        num, _, lingua = chave.partition("-")
        qid = f"{ano}-{prova.replace('_', '-')}-Q{int(num):03d}" + (f"-{lingua}" if lingua else "")
        por_id[qid] = {k: f[k] for k in ("enunciado", "correta", "distratores", "analise", "recursos", "pesquisado_em", "revisado") if k in f}
    destino = PASTA / f"{nome}.js"
    corpo = json.dumps(por_id, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    destino.write_text("// Gerado por scripts/comentarios.py: não editar.\n"
                       f"Object.assign(window.COMENTARIOS = window.COMENTARIOS || {{}}, {corpo});\n", encoding="utf-8")
    return destino


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pendentes", help="prova (ex.: 2025_regular_D2_CD7): lista as questões sem ficha")
    args = ap.parse_args()
    if args.pendentes:
        arq = PASTA / f"{args.pendentes}.json"
        feitas = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
        print(" ".join(k for k in questoes_da_prova(args.pendentes) if k not in feitas))
        return
    total, erros = 0, []
    for arq in sorted(PASTA.glob("*.json")):
        fichas = json.loads(arq.read_text(encoding="utf-8"))
        erros += validar(arq.stem, fichas)
        gerar_js(arq.stem, fichas)
        total += len(fichas)
    for e in erros:
        print("  erro:", e)
    print(f"{total} fichas de comentário; {len(erros)} erro(s)")
    if erros:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
