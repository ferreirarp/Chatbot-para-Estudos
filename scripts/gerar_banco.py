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
SIGLA = {
    "Linguagens, Códigos e suas Tecnologias": "LC",
    "Ciências Humanas e suas Tecnologias": "CH",
    "Ciências da Natureza e suas Tecnologias": "CN",
    "Matemática e suas Tecnologias": "MT",
}

# Escala de dificuldade (parâmetro b da TRI, escala (0,1) dos microdados).
# Nota equivalente na escala do ENEM = 500 + 100*b (INEP, Procedimentos de
# Análise). A barra vai de -1,5 (350 pontos) a 3,5 (850 pontos), faixa que
# cobre todas as questões de 2023 (b de -1,15 a 3,22), dividida em 7 faixas
# de largura igual. Valores fora da faixa ficam no extremo.
ESCALA = {
    "min": -1.5,
    "max": 3.5,
    "niveis": ["Para não zerar", "Facílima", "Fácil", "Mediana", "Difícil", "Dificílima", "Impossível"],
}


def nivel_dificuldade(b: float) -> str:
    n = len(ESCALA["niveis"])
    largura = (ESCALA["max"] - ESCALA["min"]) / n
    i = int((b - ESCALA["min"]) // largura)
    return ESCALA["niveis"][max(0, min(n - 1, i))]


def main() -> None:
    banco, avisos = [], []
    matriz_arq = DADOS / "matriz_referencia.json"
    matriz = json.loads(matriz_arq.read_text(encoding="utf-8")) if matriz_arq.exists() else {}
    for arq in sorted(DADOS.glob("*/*.json")):
        if not RE_PROVA.match(arq.name):
            continue
        ano = arq.parent.name
        classif_arq = DADOS / "classificacao" / f"{ano}_{arq.name}"
        classif = json.loads(classif_arq.read_text(encoding="utf-8"))["questoes"] if classif_arq.exists() else {}
        if not classif:
            avisos.append(f"{arq.relative_to(RAIZ)}: sem classificação por disciplina")
        oficial_arq = DADOS / "oficial" / f"{ano}_{arq.name}"
        oficial = json.loads(oficial_arq.read_text(encoding="utf-8"))["questoes"] if oficial_arq.exists() else {}
        if not oficial:
            avisos.append(f"{arq.relative_to(RAIZ)}: sem dados dos microdados (rode importar_microdados.py)")
        for q in json.loads(arq.read_text(encoding="utf-8")):
            c = classif.get(str(q["numero"]), {})
            if classif and not c:
                avisos.append(f"{q['id']}: não classificada")
            chave = str(q["numero"]) + (f"-{q['lingua_estrangeira']}" if q.get("lingua_estrangeira") else "")
            of = oficial.get(chave, {})
            if oficial and not of:
                avisos.append(f"{q['id']}: sem dados dos microdados")
            sigla = SIGLA.get(q["area"])
            hab = of.get("habilidade")
            hab_info = matriz.get(sigla, {}).get(hab, {}) if hab else {}
            b = of.get("param_b")
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
                "habilidade": ({
                    "codigo": hab,
                    "chave": f"{sigla} {hab}",
                    "texto": hab_info.get("texto"),
                    "competencia": hab_info.get("competencia"),
                } if hab else None),
                "dificuldade": ({
                    "b": round(b, 3),
                    "nota_equivalente": of.get("nota_equivalente"),
                    "nivel": nivel_dificuldade(b),
                } if b is not None else None),
                "descartada_da_nota": of.get("descartada_da_nota", False),
                "motivo_descarte": of.get("motivo_descarte"),
            })
    SAIDA.write_text(
        "// Gerado por scripts/gerar_banco.py — não editar à mão.\n"
        "window.BANCO_QUESTOES = " + json.dumps(banco, ensure_ascii=False) + ";\n"
        "window.ESCALA_DIFICULDADE = " + json.dumps(ESCALA, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"{len(banco)} questões -> {SAIDA.relative_to(RAIZ)}")
    for a in avisos:
        print("  aviso:", a)


if __name__ == "__main__":
    main()
