#!/usr/bin/env python3
"""Verifica o que há de novo para o banco (o botão "Atualizar dados").

    python scripts/atualizar_dados.py

Etapas automáticas:
  1. provas novas no site do INEP (cadernos 1 e 7 ainda não extraídos);
  2. microdados novos: importa os anos que têm provas sem dados oficiais;
  3. comentários: questões sem ficha e fichas com pesquisa antiga (mais de
     ATUALIZAR_APOS dias), que precisam de nova busca na web;
  4. banco regenerado.
O que exige julgamento (extrair e revisar uma prova nova, pesquisar e
redigir comentários) fica em data/enem/relatorios/atualizacao.json, para a
sessão do Claude seguir docs/procedimentos.md.
"""
from __future__ import annotations

import datetime
import glob
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import BASE_DOWNLOAD, RAIZ, contexto_ssl  # noqa: E402

DADOS = RAIZ / "data" / "enem"
ATUALIZAR_APOS = 365


def existe(url: str, ctx) -> bool:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "banco-enem/1.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def provas_novas(ctx) -> list[str]:
    """Cadernos 1 e 7 publicados no servidor de downloads do INEP e ainda não
    extraídos. A página de provas monta os links por script, então o teste é
    feito direto nos nomes de arquivo (padrão usado desde 2023)."""
    anos_no_banco = sorted(int(Path(p).name) for p in glob.glob(str(DADOS / "20*")))
    hoje = datetime.date.today()
    extraidas = {Path(f).name for f in glob.glob(str(RAIZ / ".cache" / "enem" / "*" / "*_PV_*.pdf"))}
    novas = []
    for ano in range(anos_no_banco[-1], hoje.year + 1):
        for dia in range(1, 7):  # regular, Belém e reaplicação (D1-D6 desde 2025)
            cad = 1 if dia % 2 else 7
            nome = f"{ano}_PV_impresso_D{dia}_CD{cad}.pdf"
            if nome not in extraidas and existe(BASE_DOWNLOAD + nome, ctx):
                novas.append(nome)
    return novas


def anos_sem_microdados() -> list[int]:
    anos = set()
    for f in glob.glob(str(DADOS / "20*" / "*_D?_CD*.json")):
        if f.endswith("_textos_base.json"):
            continue
        ano, prova = Path(f).parent.name, Path(f).stem
        if not (DADOS / "oficial" / f"{ano}_{prova}.json").exists():
            anos.add(int(ano))
    return sorted(anos)


def comentarios_pendentes() -> dict:
    hoje = datetime.date.today()
    sem, antigas = [], []
    for f in sorted(glob.glob(str(DADOS / "20*" / "*_D?_CD*.json"))):
        if f.endswith("_textos_base.json"):
            continue
        ano, prova = Path(f).parent.name, Path(f).stem
        arq = DADOS / "comentarios" / f"{ano}_{prova}.json"
        fichas = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
        for q in json.loads(Path(f).read_text(encoding="utf-8")):
            chave = str(q["numero"]) + (f"-{q['lingua_estrangeira']}" if q.get("lingua_estrangeira") else "")
            ficha = fichas.get(chave)
            if not ficha:
                sem.append(q["id"])
            elif (hoje - datetime.date.fromisoformat(ficha.get("pesquisado_em", "2000-01-01"))).days > ATUALIZAR_APOS:
                antigas.append(q["id"])
    return {"sem_comentario": sem, "pesquisa_antiga": antigas}


def main() -> None:
    ctx = contexto_ssl()
    rel = {"data": datetime.date.today().isoformat()}
    rel["provas_novas"] = provas_novas(ctx)
    rel["microdados"] = {}
    for ano in anos_sem_microdados():
        r = subprocess.run([sys.executable, "scripts/importar_microdados.py", "--ano", str(ano)],
                           cwd=RAIZ, capture_output=True, text=True)
        ultima = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
        rel["microdados"][ano] = "importado" if r.returncode == 0 else f"indisponível ({ultima[0][:120]})"
    rel["comentarios"] = comentarios_pendentes()
    r = subprocess.run([sys.executable, "scripts/gerar_banco.py"], cwd=RAIZ, capture_output=True, text=True)
    rel["banco"] = "ok" if r.returncode == 0 else "ERRO"
    destino = DADOS / "relatorios" / "atualizacao.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps(rel, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    c = rel["comentarios"]
    print(f"provas novas: {len(rel['provas_novas'])} | microdados: {rel['microdados'] or 'nada a importar'} | "
          f"sem comentário: {len(c['sem_comentario'])} | pesquisa antiga: {len(c['pesquisa_antiga'])} | banco: {rel['banco']}")
    for p in rel["provas_novas"][:20]:
        print("  nova:", p)


if __name__ == "__main__":
    main()
