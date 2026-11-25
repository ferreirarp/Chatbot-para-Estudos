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
RE_PROVA = re.compile(r"^(regular|reaplicacao|belem)_D\d_CD\d+\.json$")
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
# Únicas disciplinas aceitas na classificação.
DISCIPLINAS_VALIDAS = {
    "Língua Portuguesa", "Língua Inglesa", "Língua Espanhola", "Artes", "Educação Física",
    "Geografia", "História", "Filosofia", "Sociologia",
    "Matemática", "Biologia", "Física", "Química",
}
NIVEIS = ["Para não zerar", "Facílima", "Fácil", "Mediana", "Difícil", "Dificílima", "Impossível"]
MIN_QUESTOES_CALIBRACAO = 10


# Itens com discriminação muito baixa (a ≈ 0,2) podem ter b extremo (nota
# equivalente > 1700) e, sozinhos, comprimiriam a barra da área inteira. Por
# isso os limites da barra ignoram valores além da cerca de Tukey (3·IQR); esses
# itens ficam presos à ponta da barra e são marcados como "fora_da_escala".
FATOR_IQR = 3.0


def quartil(v: list[float], p: float) -> float:
    v = sorted(v)
    i = (len(v) - 1) * p
    lo = int(i)
    return v[lo] + (v[min(lo + 1, len(v) - 1)] - v[lo]) * (i - lo)


def calibrar(banco: list[dict]) -> dict:
    escalas = {}
    for area in SIGLA:
        notas = [q["dificuldade"]["nota_equivalente"] for q in banco
                 if q["area"] == area and q["dificuldade"] and q["dificuldade"]["nota_equivalente"] is not None]
        if len(notas) >= MIN_QUESTOES_CALIBRACAO:
            q1, q3 = quartil(notas, .25), quartil(notas, .75)
            lo, hi = q1 - FATOR_IQR * (q3 - q1), q3 + FATOR_IQR * (q3 - q1)
            dentro = [n for n in notas if lo <= n <= hi]
            escalas[area] = {"min": min(dentro), "max": max(dentro), "n": len(notas),
                             "fora_da_escala": len(notas) - len(dentro), "niveis": NIVEIS}
    return escalas


def nivel(nota: float, esc: dict) -> str:
    largura = (esc["max"] - esc["min"]) / len(NIVEIS) or 1
    i = int((nota - esc["min"]) // largura)
    return NIVEIS[max(0, min(len(NIVEIS) - 1, i))]


def aplicar_edicoes(banco: list[dict], avisos: list[str]) -> None:
    """Edições feitas na interface e incorporadas por aplicar_edicoes.py."""
    arq = DADOS / "edicoes" / "edicoes.json"
    if not arq.exists():
        return
    edicoes = json.loads(arq.read_text(encoding="utf-8"))
    por_id = {q["id"]: q for q in banco}
    for qid, ed in edicoes.items():
        q = por_id.get(qid)
        if not q:
            avisos.append(f"edição de {qid}: questão não existe no banco")
            continue
        for k, v in ed.get("campos", {}).items():
            q[k] = v
        for chave, r in (ed.get("recortes") or {}).items():
            if chave.startswith("alt-") and q.get("alternativas_imagem"):
                q["alternativas_imagem"][chave[4:]] = r["imagem"]
            elif q.get("blocos") and chave[1:].isdigit() and int(chave[1:]) < len(q["blocos"]):
                q["blocos"][int(chave[1:])]["imagem"] = r["imagem"]
        if ed.get("imagem") and q["imagem"] and not q.get("blocos"):
            q["imagem_original"] = q["imagem"]
            q["imagem"] = ed["imagem"]
        invalidas = [d for d in q["disciplinas"] if d not in DISCIPLINAS_VALIDAS]
        if invalidas:
            avisos.append(f"edição de {qid}: disciplina fora da lista oficial: {invalidas}")
        if set(ed.get("campos", {})) - {"revisar"} or ed.get("recortes") or ed.get("imagem"):
            q["editada_no_repositorio"] = True  # só limpar avisos conferidos não conta como edição


def main() -> None:
    banco, avisos = [], []
    matriz_arq = DADOS / "matriz_referencia.json"
    matriz = json.loads(matriz_arq.read_text(encoding="utf-8")) if matriz_arq.exists() else {}
    escalas_nota = {}  # "ano|área" -> {k, m}: conversão θ → nota usada pela calculadora
    textos_base = {}   # id -> {questoes, blocos}: textos compartilhados (2025+)
    for arq in sorted(DADOS.glob("*/*_textos_base.json")):
        ano = arq.parent.name
        for tid, t in json.loads(arq.read_text(encoding="utf-8")).items():
            t["blocos"] = [dict(b, imagem=f"data/enem/{ano}/{b['imagem']}") if b["tipo"] == "figura" else b for b in t["blocos"]]
            textos_base[tid] = t
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
            chave = str(q["numero"]) + (f"-{q['lingua_estrangeira']}" if q.get("lingua_estrangeira") else "")
            c = classif.get(chave, {})
            invalidas = [d for d in c.get("disciplinas", []) if d not in DISCIPLINAS_VALIDAS]
            if invalidas:
                avisos.append(f"{q['id']}: disciplina fora da lista oficial: {invalidas}")
            if classif and not c:
                avisos.append(f"{q['id']}: não classificada")
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
                "texto_base": q.get("texto_base"),
                "enunciado": re.sub(r"^\s*QUESTÃO\s*\d+[ \d]*\n", "", q["enunciado"]),  # cabeçalho residual
                "alternativas": q["alternativas"],
                "gabarito": q["gabarito"],
                "anulada": q["anulada"],
                "visuais": q["elementos_visuais"],
                "imagem": (f"data/enem/{ano}/{q['imagem']}" if q["imagem"] else None),
                "texto_fiel": q["texto_fiel"],
                # versão estruturada: texto + recortes só dos objetos visuais
                "blocos": ([dict(b, imagem=f"data/enem/{ano}/{b['imagem']}") if b["tipo"] == "figura" else b
                            for b in q["blocos"]] if q.get("blocos") else None),
                "alternativas_imagem": ({L: f"data/enem/{ano}/{v}" for L, v in q["alternativas_imagem"].items()}
                                        if q.get("alternativas_imagem") else None),
                # "fórmula recortada como imagem" é nota de extração, não erro
                "revisar": [r for r in q.get("revisar") or [] if r != "fórmula recortada como imagem"],
                "habilidade": ({
                    "codigo": hab,
                    "chave": f"{sigla} {hab}",
                    "texto": hab_info.get("texto"),
                    "competencia": hab_info.get("competencia"),
                } if hab else None),
                "dificuldade": ({
                    "b": round(b, 3),
                    "nota_equivalente": of.get("nota_equivalente"),
                } if b is not None and not of.get("gabarito_microdado") else None),
                # parâmetros da TRI para a calculadora de nota
                "tri": ({"a": of["param_a"], "b": of["param_b"], "c": of["param_c"]}
                        if b is not None and not of.get("descartada_da_nota")
                        and not of.get("gabarito_microdado") else None),
                "gabarito_microdado": of.get("gabarito_microdado"),
                "descartada_da_nota": of.get("descartada_da_nota", False),
                "motivo_descarte": of.get("motivo_descarte"),
            })
    aplicar_edicoes(banco, avisos)
    escalas = calibrar(banco)
    for q in banco:
        d, e = q["dificuldade"], escalas.get(q["area"])
        if d and e and d["nota_equivalente"] is not None:
            d["nivel"] = nivel(d["nota_equivalente"], e)
            pos = (d["nota_equivalente"] - e["min"]) / ((e["max"] - e["min"]) or 1)
            d["posicao"] = round(max(0.0, min(1.0, pos)), 4)
            if not 0 <= pos <= 1:
                d["fora_da_escala"] = True
                avisos.append(f"{q['id']}: dificuldade fora da escala da área (nota equivalente {d['nota_equivalente']:.0f}); presa à ponta da barra")
        elif d:
            d["nivel"] = None
            avisos.append(f"{q['id']}: dificuldade sem calibração (área com poucas questões ou sem escala de notas)")
    SAIDA.write_text(
        "// Gerado por scripts/gerar_banco.py — não editar à mão.\n"
        "window.BANCO_QUESTOES = " + json.dumps(banco, ensure_ascii=False) + ";\n"
        "window.ESCALA_DIFICULDADE = " + json.dumps(escalas, ensure_ascii=False) + ";\n"
        "window.ESCALA_NOTAS = " + json.dumps(escalas_nota, ensure_ascii=False) + ";\n"
        "window.TEXTOS_BASE = " + json.dumps(textos_base, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"{len(banco)} questões -> {SAIDA.relative_to(RAIZ)}")
    for area, e in escalas.items():
        largura = (e["max"] - e["min"]) / len(NIVEIS)
        cortes = " | ".join(f"{n}: {e['min'] + i * largura:.0f}–{e['min'] + (i + 1) * largura:.0f}" for i, n in enumerate(NIVEIS))
        print(f"  {area} ({e['n']} questões, {e['fora_da_escala']} fora da escala): {cortes}")
    for q in banco:
        if q["texto_base"] and q["texto_base"] not in textos_base:
            avisos.append(f"{q['id']}: texto-base {q['texto_base']} não encontrado (rode estruturar_questoes.py)")
    for a in avisos:
        print("  aviso:", a)


if __name__ == "__main__":
    main()
