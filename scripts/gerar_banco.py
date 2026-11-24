#!/usr/bin/env python3
"""Junta as provas extraídas e as classificações num único banco de questões
para a interface (questoes.html).

    python scripts/gerar_banco.py

Lê:   data/enem/<ano>/<aplicacao>_D<dia>_CD<caderno>.json
      data/enem/classificacao/<ano>_<aplicacao>_D<dia>_CD<caderno>.json
Gera: data/banco_questoes.js  (window.BANCO_QUESTOES = [...])

Um arquivo .js (e não .json) permite abrir questoes.html direto do disco,
sem servidor: navegadores bloqueiam fetch() de arquivos locais.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data" / "enem"
SAIDA = RAIZ / "data" / "banco_questoes.js"
RE_PROVA = re.compile(r"^(regular|reaplicacao)_D\d_CD\d+\.json$")


def main() -> None:
    banco, avisos = [], []
    for arq in sorted(DADOS.glob("*/*.json")):
        if not RE_PROVA.match(arq.name):
            continue
        ano = arq.parent.name
        classif_arq = DADOS / "classificacao" / f"{ano}_{arq.name}"
        classif = json.loads(classif_arq.read_text(encoding="utf-8"))["questoes"] if classif_arq.exists() else {}
        if not classif:
            avisos.append(f"{arq.relative_to(RAIZ)}: sem classificação por disciplina")
        for q in json.loads(arq.read_text(encoding="utf-8")):
            c = classif.get(str(q["numero"]), {})
            if classif and not c:
                avisos.append(f"{q['id']}: não classificada")
            banco.append({
                "id": q["id"],
                "prova": q["prova"],
                "area": q["area"],
                "disciplinas": c.get("disciplinas", []),
                "conteudos": c.get("conteudos", []),
                "observacao": c.get("observacao"),
                "lingua": q.get("lingua_estrangeira"),
                "enunciado": q["enunciado"],
                "alternativas": q["alternativas"],
                "gabarito": q["gabarito"],
                "anulada": q["anulada"],
                "visuais": q["elementos_visuais"],
                "imagem": (f"data/enem/{ano}/{q['imagem']}" if q["imagem"] else None),
                "texto_fiel": q["texto_fiel"],
            })
    SAIDA.write_text(
        "// Gerado por scripts/gerar_banco.py — não editar à mão.\n"
        "window.BANCO_QUESTOES = " + json.dumps(banco, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"{len(banco)} questões -> {SAIDA.relative_to(RAIZ)}")
    for a in avisos:
        print("  aviso:", a)


if __name__ == "__main__":
    main()
