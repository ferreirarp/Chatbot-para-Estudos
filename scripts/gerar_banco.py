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

# Dificuldade: medida pela "nota equivalente" da questão (k·b + m, na escala
# de notas do ENEM daquela área e ano; ver importar_microdados.py), que é
# comparável entre anos. Cada ÁREA tem a sua barra: vai da questão mais fácil
# à mais difícil daquela área no banco, dividida em 7 faixas de largura igual.
# A calibração é refeita a cada execução, ou seja, sempre que entra uma prova.
NIVEIS = ["Para não zerar", "Facílima", "Fácil", "Mediana", "Difícil", "Dificílima", "Impossível"]
MIN_QUESTOES_CALIBRACAO = 10


def calibrar(banco: list[dict]) -> dict:
    escalas = {}
    for area in SIGLA:
        notas = [q["dificuldade"]["nota_equivalente"] for q in banco
                 if q["area"] == area and q["dificuldade"] and q["dificuldade"]["nota_equivalente"] is not None]
        if len(notas) >= MIN_QUESTOES_CALIBRACAO:
            escalas[area] = {"min": min(notas), "max": max(notas), "n": len(notas), "niveis": NIVEIS}
    return escalas


def nivel(nota: float, esc: dict) -> str:
    largura = (esc["max"] - esc["min"]) / len(NIVEIS) or 1
    i = int((nota - esc["min"]) // largura)
    return NIVEIS[max(0, min(len(NIVEIS) - 1, i))]


def main() -> None:
    banco, avisos = [], []
    matriz_arq = DADOS / "matriz_referencia.json"
    matriz = json.loads(matriz_arq.read_text(encoding="utf-8")) if matriz_arq.exists() else {}
    escalas_nota = {}  # "ano|área" -> {k, m}: conversão θ → nota usada pela calculadora
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
        esc_arq = DADOS / "oficial" / f"{ano}_escala_notas.json"
        if esc_arq.exists():
            for sig, e in json.loads(esc_arq.read_text(encoding="utf-8"))["areas"].items():
                nome = next(n for n, s in SIGLA.items() if s == sig)
                escalas_nota[f"{ano}|{nome}"] = {"k": e["k"], "m": e["m"]}
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
                } if b is not None else None),
                # parâmetros da TRI para a calculadora de nota
                "tri": ({"a": of["param_a"], "b": of["param_b"], "c": of["param_c"]}
                        if b is not None and not of.get("descartada_da_nota") else None),
                "descartada_da_nota": of.get("descartada_da_nota", False),
                "motivo_descarte": of.get("motivo_descarte"),
            })
    escalas = calibrar(banco)
    for q in banco:
        d, e = q["dificuldade"], escalas.get(q["area"])
        if d and e and d["nota_equivalente"] is not None:
            d["nivel"] = nivel(d["nota_equivalente"], e)
            d["posicao"] = round((d["nota_equivalente"] - e["min"]) / ((e["max"] - e["min"]) or 1), 4)
        elif d:
            d["nivel"] = None
            avisos.append(f"{q['id']}: dificuldade sem calibração (área com poucas questões ou sem escala de notas)")
    SAIDA.write_text(
        "// Gerado por scripts/gerar_banco.py — não editar à mão.\n"
        "window.BANCO_QUESTOES = " + json.dumps(banco, ensure_ascii=False) + ";\n"
        "window.ESCALA_DIFICULDADE = " + json.dumps(escalas, ensure_ascii=False) + ";\n"
        "window.ESCALA_NOTAS = " + json.dumps(escalas_nota, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"{len(banco)} questões -> {SAIDA.relative_to(RAIZ)}")
    for area, e in escalas.items():
        largura = (e["max"] - e["min"]) / len(NIVEIS)
        cortes = " | ".join(f"{n}: {e['min'] + i * largura:.0f}–{e['min'] + (i + 1) * largura:.0f}" for i, n in enumerate(NIVEIS))
        print(f"  {area} ({e['n']} questões): {cortes}")
    for a in avisos:
        print("  aviso:", a)


if __name__ == "__main__":
    main()
