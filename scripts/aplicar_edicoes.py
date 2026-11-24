#!/usr/bin/env python3
"""Incorpora ao repositório as edições feitas na interface (questoes.html).

    python scripts/aplicar_edicoes.py edicoes-banco-enem.json
    python scripts/gerar_banco.py

O arquivo é o que o botão "Baixar edições (JSON)" gera. As edições ficam em
data/enem/edicoes/edicoes.json (só os campos alterados) e as imagens editadas
em data/enem/edicoes/img/<id>.png. Os arquivos extraídos das provas não são
tocados: gerar_banco.py aplica as edições por cima deles, então dá para
desfazer uma edição apagando a entrada correspondente.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "data" / "enem" / "edicoes"
ARQ = PASTA / "edicoes.json"
CAMPOS = {"enunciado", "alternativas", "gabarito", "disciplinas", "conteudos", "observacao"}
RE_ID = re.compile(r"^\d{4}-(regular|reaplicacao)-D\d-CD\d+-Q\d{3}(-(ingles|espanhol))?$")
PREFIXO_PNG = "data:image/png;base64,"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("arquivo", type=Path, help="JSON baixado da interface")
    args = ap.parse_args()

    entrada = json.loads(args.arquivo.read_text(encoding="utf-8"))
    if entrada.get("formato") != "banco-enem-edicoes":
        raise SystemExit("Arquivo não reconhecido: esperado o JSON do botão 'Baixar edições'.")
    atuais = json.loads(ARQ.read_text(encoding="utf-8")) if ARQ.exists() else {}
    (PASTA / "img").mkdir(parents=True, exist_ok=True)

    for qid, ed in entrada["edicoes"].items():
        if not RE_ID.match(qid):
            print(f"  ignorada (id inválido): {qid!r}")
            continue
        campos = {k: v for k, v in (ed.get("campos") or {}).items() if k in CAMPOS}
        reg = {"campos": campos, "atualizado": ed.get("atualizado")}
        png = ed.get("imagem_png")
        destino = PASTA / "img" / f"{qid}.png"
        if png:
            if not png.startswith(PREFIXO_PNG):
                print(f"  {qid}: imagem ignorada (não é PNG)")
            else:
                destino.write_bytes(base64.b64decode(png[len(PREFIXO_PNG):]))
                reg["imagem"] = f"data/enem/edicoes/img/{qid}.png"
                reg["receita"] = ed.get("receita")
        elif destino.exists():
            destino.unlink()  # a imagem voltou ao original
        if campos or "imagem" in reg:
            atuais[qid] = reg
        else:
            atuais.pop(qid, None)
        print(f"  {qid}: {', '.join(sorted(campos)) or '-'}{' + imagem' if 'imagem' in reg else ''}")

    ARQ.write_text(json.dumps(dict(sorted(atuais.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(atuais)} questões editadas em {ARQ.relative_to(RAIZ)}. Rode scripts/gerar_banco.py.")


if __name__ == "__main__":
    main()
