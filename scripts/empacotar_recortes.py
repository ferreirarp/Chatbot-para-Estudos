#!/usr/bin/env python3
"""Empacota os recortes de cada prova num JSON (nome -> data URL) para a
página publicada, que aceita no máximo 512 arquivos.

    python scripts/empacotar_recortes.py   # gera data/enem/<ano>/blocos/pacote_<prova>.json
"""
import base64, io, json, re
from PIL import Image
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
banco = json.loads(re.search(r"BANCO_QUESTOES = (.*?);\n", (RAIZ / "data/banco_questoes.js").read_text(encoding="utf-8")).group(1))
usados = set()
for q in banco:
    usados |= {b["imagem"] for b in q.get("blocos") or [] if b["tipo"] == "figura"}
    usados |= set((q.get("alternativas_imagem") or {}).values())
pacotes = defaultdict(dict)
for caminho in sorted(usados):
    m = re.match(r"data/enem/(\d{4})/img/blocos/((?:regular|reaplicacao|belem)_D\d_CD\d+)_Q(\d{3}).*\.png$", caminho)
    if not m:
        continue
    bruto = (RAIZ / caminho).read_bytes()
    tipo, dados = "png", bruto
    im = Image.open(io.BytesIO(bruto)).convert("RGB")
    # foto (muitas cores): JPEG, bem menor; desenho e texto: PNG, sem borrão
    if len(im.getcolors(maxcolors=4096) or []) == 0:
        b = io.BytesIO(); im.save(b, "JPEG", quality=85, optimize=True)
        if b.tell() < len(bruto):
            tipo, dados = "jpeg", b.getvalue()
    grupo = f"{m[2]}_{int(m[3]) // 10:02d}"
    pacotes[(m[1], grupo)][Path(caminho).name] = f"data:image/{tipo};base64," + base64.b64encode(dados).decode()
for (ano, prova), conteudo in pacotes.items():
    destino = RAIZ / f"data/enem/{ano}/blocos/pacote_{prova}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(conteudo, separators=(",", ":")), encoding="utf-8")
total = sum((RAIZ / f"data/enem/{a}/blocos/pacote_{p}.json").stat().st_size for a, p in pacotes)
maior = max((RAIZ / f"data/enem/{a}/blocos/pacote_{p}.json").stat().st_size for a, p in pacotes)
print(f"{len(pacotes)} pacotes, {total / 1e6:.1f} MB no total, maior {maior / 1e6:.1f} MB")
