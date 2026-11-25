#!/usr/bin/env python3
"""Revisão, limpeza e compactação do banco (o botão "Revisar e limpar").

    python scripts/manutencao.py            # verifica, limpa e regenera
    python scripts/manutencao.py --so-verificar

Etapas:
  1. anomalias nas questões extraídas (alternativa vazia, sem gabarito,
     cabeçalho no texto, palavras coladas, avisos "revisar" pendentes);
  2. imagens órfãs (PNG que nenhuma questão, texto-base ou edição usa);
  3. taxonomia, classificações e fichas de comentário (validação);
  4. banco (gerar_banco.py) e pacotes de imagens (empacotar_recortes.py).
O relatório vai para data/enem/relatorios/manutencao.json; o que exige
olhar humano (ou de uma sessão do Claude) fica listado em "pendencias".
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data" / "enem"
NOTA_EXTRACAO = "fórmula recortada como imagem"  # informativo, não é problema


def anomalias() -> list[str]:
    edicoes = json.loads((DADOS / "edicoes" / "edicoes.json").read_text(encoding="utf-8"))
    achados = []
    for f in sorted(glob.glob(str(DADOS / "20*" / "*_D?_CD*.json"))):
        if f.endswith("_textos_base.json"):
            continue
        ano = Path(f).parent.name
        for q in json.loads(Path(f).read_text(encoding="utf-8")):
            ed = (edicoes.get(q["id"]) or {}).get("campos", {})
            alts = ed.get("alternativas") or q.get("alternativas") or {}
            imgs = ed.get("alternativas_imagem", q.get("alternativas_imagem")) or {}
            prob = [f"alternativa {L} vazia" for L in "ABCDE" if not (alts.get(L) or "").strip() and L not in imgs]
            if q.get("gabarito") not in list("ABCDE") and not q.get("anulada"):
                prob.append(f"gabarito {q.get('gabarito')}")
            texto = " ".join(b.get("texto") or "" for b in q.get("blocos") or []) or q.get("enunciado", "")
            if re.search(r"QUEST[ÃA]O\s*\d{2,3}", texto):
                prob.append("cabeçalho no texto")
            coladas = [w for w in re.findall(r"\S{28,}", texto) if not re.search(r"https?:|www\.|\.(br|com|org)|/", w)]
            if coladas:
                prob.append("palavras coladas: " + ", ".join(w[:30] for w in coladas[:2]))
            revisar = [r for r in ed.get("revisar", q.get("revisar")) or [] if r != NOTA_EXTRACAO]
            if revisar:
                prob.append("revisar: " + "; ".join(revisar))
            if prob:
                achados.append(f"{q['id']}: {' / '.join(prob)}")
    return achados


def imagens_orfas(apagar: bool) -> list[str]:
    usados = set()

    def andar(x, ano):
        if isinstance(x, dict):
            for v in x.values():
                andar(v, ano)
        elif isinstance(x, list):
            for v in x:
                andar(v, ano)
        elif isinstance(x, str) and x.endswith((".png", ".jpg", ".webp")):
            usados.add(os.path.normpath(x if x.startswith("data/") else f"data/enem/{ano}/{x}"))

    for f in glob.glob(str(DADOS / "20*" / "*.json")):
        andar(json.loads(Path(f).read_text(encoding="utf-8")), Path(f).parent.name)
    andar(json.loads((DADOS / "edicoes" / "edicoes.json").read_text(encoding="utf-8")), "-")
    orfas = [p for p in glob.glob("data/enem/20*/img/**/*.png", recursive=True, root_dir=RAIZ)
             if os.path.normpath(p) not in usados]
    if apagar:
        for p in orfas:
            (RAIZ / p).unlink()
    return orfas


def rodar(*cmd) -> tuple[int, str]:
    r = subprocess.run([sys.executable, *cmd], cwd=RAIZ, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--so-verificar", action="store_true", help="não apaga nem regenera nada")
    args = ap.parse_args()
    rel = {"data": datetime.date.today().isoformat(), "etapas": {}, "pendencias": []}

    a = anomalias()
    rel["etapas"]["anomalias"] = len(a)
    rel["pendencias"] += a
    o = imagens_orfas(apagar=not args.so_verificar)
    rel["etapas"]["imagens_orfas" + ("" if args.so_verificar else "_apagadas")] = len(o)

    if not args.so_verificar:
        for nome, cmd in (("taxonomia", ["scripts/taxonomia.py"]),
                          ("comentarios", ["scripts/comentarios.py"]),
                          ("banco", ["scripts/gerar_banco.py"]),
                          ("pacotes", ["scripts/empacotar_recortes.py"])):
            cod, saida = rodar(*cmd)
            rel["etapas"][nome] = "ok" if cod == 0 else "ERRO"
            avisos = [l.strip() for l in saida.splitlines() if l.strip().startswith(("aviso", "erro"))]
            rel["pendencias"] += [f"{nome}: {l}" for l in avisos]
    else:
        cod, saida = rodar("scripts/comentarios.py")
        rel["etapas"]["comentarios"] = "ok" if cod == 0 else "ERRO"

    destino = DADOS / "relatorios" / "manutencao.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps(rel, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(rel["etapas"], ensure_ascii=False))
    print(f"{len(rel['pendencias'])} pendência(s) em {destino.relative_to(RAIZ)}")
    for p in rel["pendencias"][:40]:
        print("  -", p)


if __name__ == "__main__":
    main()
