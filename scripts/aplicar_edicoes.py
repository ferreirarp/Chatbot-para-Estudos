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
CAMPOS = {"enunciado", "alternativas", "gabarito", "disciplinas", "conteudos", "observacao", "blocos"}
RE_RECORTE = re.compile(r"^(b\d+|alt-[A-E])$")
RE_ID = re.compile(r"^\d{4}-(regular|reaplicacao|belem)-D\d-CD\d+-Q\d{3}(-(ingles|espanhol))?$")
PREFIXO_PNG = "data:image/png;base64,"
RE_DATA_URL = re.compile(r"^data:image/(png|jpeg|webp|gif);base64,")


def gravar_data_url(valor: str, destino_sem_ext: Path) -> str | None:
    """Grava uma imagem em data URL e devolve o caminho usado no banco."""
    m = RE_DATA_URL.match(valor or "")
    if not m:
        return None
    ext = {"jpeg": "jpg"}.get(m.group(1), m.group(1))
    arq = destino_sem_ext.with_suffix("." + ext)
    arq.write_bytes(base64.b64decode(valor[m.end():]))
    return f"data/enem/edicoes/img/{arq.name}"


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
        gravados = set()
        # imagens dentro dos blocos (enviadas, recortadas ou ajustadas)
        for i, b in enumerate(campos.get("blocos") or []):
            for campo, sufixo in (("imagem_png", f"bloco{i}"), ("imagem_base", f"bloco{i}_base")):
                caminho = gravar_data_url(b.get(campo) or "", PASTA / "img" / f"{qid}__{sufixo}")
                if caminho:
                    gravados.add(Path(caminho).name)
                    b["imagem" if campo == "imagem_png" else "imagem_base"] = caminho
            b.pop("imagem_png", None)
            for campo in ("imagem_id", "imagem_dados"):
                if b.pop(campo, None):
                    print(f"  {qid}: bloco {i} com imagem que não veio no arquivo (exporte de novo)")
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
        recortes = {}
        for chave, r in (ed.get("recortes") or {}).items():
            png_r = (r or {}).get("imagem_png") or ""
            if not RE_RECORTE.match(chave) or not png_r.startswith(PREFIXO_PNG):
                print(f"  {qid}: recorte {chave!r} ignorado")
                continue
            arq = PASTA / "img" / f"{qid}__{chave}.png"
            arq.write_bytes(base64.b64decode(png_r[len(PREFIXO_PNG):]))
            gravados.add(arq.name)
            recortes[chave] = {"imagem": f"data/enem/edicoes/img/{arq.name}", "receita": r.get("receita")}
        for velho in (PASTA / "img").glob(f"{qid}__*"):
            if velho.name not in gravados:
                velho.unlink()  # imagem que saiu da questão ou voltou ao original
        if recortes:
            reg["recortes"] = recortes
        if campos or "imagem" in reg or recortes:
            atuais[qid] = reg
        else:
            atuais.pop(qid, None)
        print(f"  {qid}: {', '.join(sorted(campos)) or '-'}{' + imagem' if 'imagem' in reg else ''}"
              f"{' + recortes ' + ','.join(sorted(recortes)) if recortes else ''}")

    ARQ.write_text(json.dumps(dict(sorted(atuais.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(atuais)} questões editadas em {ARQ.relative_to(RAIZ)}. Rode scripts/gerar_banco.py.")


if __name__ == "__main__":
    main()
