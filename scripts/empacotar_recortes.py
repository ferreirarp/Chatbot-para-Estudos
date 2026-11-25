#!/usr/bin/env python3
"""Empacota as imagens do banco em JSON (nome -> data URL) para a página
publicada, que aceita no máximo 512 arquivos.

    python scripts/empacotar_recortes.py

Gera, em data/enem/<ano>/blocos/ (fora do git: é derivado das PNGs):
  pacote_<prova>_<NN>.json    recortes das questões NN0-NN9 (e dos textos-base)
  original_<prova>_<NN>.json  imagem da questão como está na prova, 30 por pacote

A página (questoes.html) só baixa um pacote quando uma imagem dele falta
como arquivo. A regra de nomes está nos dois lados: mudou aqui, mude lá.
"""
import base64
import io
import json
import re
from collections import defaultdict
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
RE_IMG = re.compile(r"data/enem/(\d{4})/img/(blocos/)?((?:regular|reaplicacao|belem)_D\d_CD\d+)_([QT])(\d{2,3})[^/]*\.png$")
POR_PACOTE = {"pacote": 10, "original": 30}


def figuras(blocos):
    return {b["imagem"] for b in blocos or [] if b.get("tipo") == "figura" and b.get("imagem")}


def main() -> None:
    js = (RAIZ / "data/banco_questoes.js").read_text(encoding="utf-8")
    banco = json.loads(re.search(r"BANCO_QUESTOES = (.*?);\n", js).group(1))
    textos = json.loads(re.search(r"TEXTOS_BASE = (.*?);\n", js).group(1))
    usados = set()
    for q in banco:
        usados |= figuras(q.get("blocos")) | set((q.get("alternativas_imagem") or {}).values())
        if q.get("imagem"):
            usados.add(q["imagem"])
    for t in textos.values():
        usados |= figuras(t.get("blocos"))

    pacotes = defaultdict(dict)
    for caminho in sorted(usados):
        m = RE_IMG.match(caminho)
        if not m or not (RAIZ / caminho).exists():
            continue
        ano, recorte, prova, _, num = m.groups()
        tipo = "pacote" if recorte else "original"
        bruto = (RAIZ / caminho).read_bytes()
        mime, dados = "png", bruto
        im = Image.open(io.BytesIO(bruto)).convert("RGB")
        # foto (muitas cores): JPEG, bem menor; desenho e texto: PNG, sem borrão
        if im.getcolors(maxcolors=4096) is None:
            b = io.BytesIO()
            im.save(b, "JPEG", quality=85, optimize=True)
            if b.tell() < len(bruto):
                mime, dados = "jpeg", b.getvalue()
        grupo = f"{tipo}_{prova}_{int(num) // POR_PACOTE[tipo]:02d}"
        pacotes[(ano, grupo)][Path(caminho).name] = f"data:image/{mime};base64," + base64.b64encode(dados).decode()

    for pasta in RAIZ.glob("data/enem/*/blocos"):
        for velho in list(pasta.glob("pacote_*.json")) + list(pasta.glob("original_*.json")):
            velho.unlink()
    tamanhos = []
    for (ano, grupo), conteudo in sorted(pacotes.items()):
        destino = RAIZ / f"data/enem/{ano}/blocos/{grupo}.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(conteudo, separators=(",", ":")), encoding="utf-8")
        tamanhos.append(destino.stat().st_size)
    print(f"{len(pacotes)} pacotes, {sum(tamanhos) / 1e6:.1f} MB no total, maior {max(tamanhos) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
