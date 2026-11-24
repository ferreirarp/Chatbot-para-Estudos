#!/usr/bin/env python3
"""Extrai questões do ENEM a partir dos arquivos oficiais do INEP.

Fonte das questões: arquivos DOSVOX (.txt) publicados pelo INEP para leitores
de tela. Eles trazem o texto limpo e descrevem figuras e gráficos em palavras,
o que evita os erros de extração dos PDFs comuns (fórmulas quebradas, figuras
misturadas ao texto, gráficos convertidos em números estimados).

Fonte das respostas: o gabarito em PDF do MESMO caderno do arquivo DOSVOX
(a ordem das questões muda entre cadernos).

Limitação: os cadernos adaptados (DOSVOX) trocam algumas questões da prova
regular. O resultado é um banco de questões reais, não a prova completa.

Uso:
    pip install pypdf
    python scripts/extrair_enem.py --ano 2023
Saída: data/enem/<ano>.json
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import urllib.request
from pathlib import Path

try:
    import pypdf
except ImportError:  # pragma: no cover
    sys.exit("Instale a dependência: pip install pypdf")

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / ".cache" / "enem"
SAIDA = RAIZ / "data" / "enem"
CERT_INTERMEDIARIO = Path(__file__).resolve().parent / "certs" / "rnp_icpedu_gr46_ov_tls_ca_2025.pem"

PAGINA_ANO = "https://www.gov.br/inep/pt-br/areas-de-atuacao/avaliacao-e-exames-educacionais/enem/provas-e-gabaritos/{ano}"
BASE_DOWNLOAD = "https://download.inep.gov.br/enem/provas_e_gabaritos/"

AREAS = {
    "LC": "Linguagens, Códigos e suas Tecnologias",
    "CH": "Ciências Humanas e suas Tecnologias",
    "CN": "Ciências da Natureza e suas Tecnologias",
    "MT": "Matemática e suas Tecnologias",
}

RESPOSTA = r"(?:[A-E]|Anulad[ao])"


# --------------------------------------------------------------------------- rede
def contexto_ssl() -> ssl.SSLContext:
    """Verificação TLS normal + o certificado intermediário que o servidor do
    INEP deixa de enviar (cadeia incompleta). Nunca desliga a verificação."""
    ctx = ssl.create_default_context()
    if CERT_INTERMEDIARIO.exists():
        ctx.load_verify_locations(cafile=str(CERT_INTERMEDIARIO))
    return ctx


def baixar(url: str, destino: Path, ctx: ssl.SSLContext) -> Path:
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "extrair-enem/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        dados = resp.read()
    destino.write_bytes(dados)
    return destino


# ------------------------------------------------------------------ descoberta
RE_DOSVOX = re.compile(
    r"(?P<ano>\d{4})_Dia_(?P<dia>\d)_P1_(?P<area>LC|CH|CN|MT)_Caderno_(?P<cad>\d+)_(?P<cor>[A-Za-zÀ-ú]+)_DOSVOX\.txt"
)


def descobrir_arquivos(ano: int, ctx: ssl.SSLContext) -> list[dict]:
    html_path = baixar(PAGINA_ANO.format(ano=ano), CACHE / str(ano) / "pagina.html", ctx)
    html = html_path.read_text(encoding="utf-8", errors="replace")
    links = set(re.findall(r'href="([^"]+)"', html))
    achados = []
    for link in sorted(links):
        m = RE_DOSVOX.search(link)
        if not m or int(m["ano"]) != ano:
            continue
        dia, cad = int(m["dia"]), int(m["cad"])
        gabarito = f"{ano}_GB_impresso_D{dia}_CD{cad}.pdf"
        gab_link = next((l for l in links if l.endswith("/" + gabarito)), None)
        achados.append({
            "dia": dia, "caderno": cad, "cor": m["cor"], "area": m["area"],
            "url_prova": link, "url_gabarito": gab_link,
        })
    return achados


# ------------------------------------------------------------------- gabarito
def ler_gabarito(pdf: Path) -> dict:
    """Retorna {numero: resposta} e {numero: {"ingles": x, "espanhol": y}}."""
    texto = "\n".join(
        p.extract_text(extraction_mode="layout") for p in pypdf.PdfReader(str(pdf)).pages
    )
    comum: dict[int, str] = {}
    linguas: dict[int, dict[str, str]] = {}
    for linha in texto.splitlines():
        # O pypdf às vezes separa dígitos de um mesmo número ("11  0" = 110).
        # As colunas da tabela ficam separadas por muitos espaços; dígitos
        # separados por até 2 espaços pertencem ao mesmo número.
        linha = re.sub(r"(?<=\d) {1,2}(?=\d)", "", linha)
        tokens = re.findall(rf"\d+|{RESPOSTA}\b", linha)
        # Linha com língua estrangeira: num, inglês, espanhol, [num, resp]
        if (len(tokens) >= 3 and tokens[0].isdigit() and not tokens[1].isdigit()
                and not tokens[2].isdigit() and int(tokens[0]) <= 5):
            linguas[int(tokens[0])] = {"ingles": tokens[1], "espanhol": tokens[2]}
            tokens = tokens[3:]
        i = 0
        while i + 1 < len(tokens):
            if tokens[i].isdigit() and not tokens[i + 1].isdigit():
                comum[int(tokens[i])] = tokens[i + 1]
                i += 2
            else:
                i += 1
    return {"comum": comum, "linguas": linguas}


def normalizar_resposta(r: str | None) -> tuple[str | None, bool]:
    if r is None:
        return None, False
    if r.lower().startswith("anulad"):
        return None, True
    return r, False


# ---------------------------------------------------------------------- prova
RE_QUESTAO = re.compile(r"^QUESTÃO (\d+)\s*$")
RE_ALT = re.compile(r"^([a-e])\. (.*)$")
RE_LINGUA = re.compile(r"opção (inglês|espanhol)", re.I)
RE_FIM = re.compile(r"^(\(Fim d[aoe]s? (prova|questões)|PROPOSTA DE REDAÇÃO|INSTRUÇÕES PARA A REDAÇÃO|PROVA DE |Questões de \d+ a \d+)")


def ler_dosvox(txt: Path) -> list[dict]:
    bruto = txt.read_bytes()
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError:
        texto = bruto.decode("cp1252")
    linhas = [l.rstrip() for l in texto.replace("\r", "").split("\n")]

    questoes: list[dict] = []
    atual: dict | None = None
    lingua: str | None = None

    def fechar():
        if atual is not None:
            questoes.append(atual)

    for linha in linhas:
        if RE_LINGUA.search(linha) and linha.startswith("Questões"):
            lingua = "ingles" if "ingl" in linha.lower() else "espanhol"
        elif linha.startswith("Questões de 6") or linha.startswith("Questões de 46"):
            lingua = None

        m = RE_QUESTAO.match(linha)
        if m:
            fechar()
            atual = {"numero": int(m.group(1)), "lingua": lingua, "corpo": [], "alts": []}
            continue
        if atual is None:
            continue
        if RE_FIM.match(linha):
            fechar()
            atual = None
            continue
        a = RE_ALT.match(linha)
        if a and (len(atual["alts"]) < 5) and a.group(1) == "abcde"[len(atual["alts"])]:
            atual["alts"].append(a.group(2).strip())
        elif atual["alts"]:
            # Texto depois das alternativas: continuação da última alternativa
            # (quebra de linha) ou lixo entre questões; guardamos para revisão.
            if linha.strip():
                atual.setdefault("sobra", []).append(linha.strip())
        else:
            atual["corpo"].append(linha)
    fechar()
    return questoes


def limpar_enunciado(linhas: list[str]) -> str:
    texto = "\n".join(linhas).strip()
    return re.sub(r"\n{3,}", "\n\n", texto)


# ----------------------------------------------------------------------- main
def processar_ano(ano: int) -> Path:
    ctx = contexto_ssl()
    arquivos = descobrir_arquivos(ano, ctx)
    if not arquivos:
        sys.exit(f"Nenhum arquivo DOSVOX encontrado para {ano}.")

    saida: list[dict] = []
    problemas: list[str] = []
    for arq in arquivos:
        nome = arq["url_prova"].rsplit("/", 1)[-1]
        txt = baixar(arq["url_prova"], CACHE / str(ano) / nome, ctx)
        if not arq["url_gabarito"]:
            problemas.append(f"{nome}: gabarito do caderno {arq['caderno']} não encontrado")
            gab = {"comum": {}, "linguas": {}}
        else:
            gnome = arq["url_gabarito"].rsplit("/", 1)[-1]
            gab = ler_gabarito(baixar(arq["url_gabarito"], CACHE / str(ano) / gnome, ctx))

        for q in ler_dosvox(txt):
            n, lingua = q["numero"], q["lingua"]
            bruta = gab["linguas"].get(n, {}).get(lingua) if lingua else gab["comum"].get(n)
            resposta, anulada = normalizar_resposta(bruta)
            enunciado = limpar_enunciado(q["corpo"])
            alertas = []
            if len(q["alts"]) != 5:
                alertas.append(f"{len(q['alts'])} alternativas encontradas (esperado 5)")
            if q.get("sobra"):
                alertas.append("texto após as alternativas: " + " | ".join(q["sobra"])[:300])
            if bruta is None:
                alertas.append("sem resposta no gabarito")
            if not enunciado:
                alertas.append("enunciado vazio")
            for a in alertas:
                problemas.append(f"{ano} D{arq['dia']} CD{arq['caderno']} Q{n}{'/' + lingua if lingua else ''}: {a}")

            sufixo = f"-{lingua}" if lingua else ""
            saida.append({
                "id": f"{ano}-D{arq['dia']}-CD{arq['caderno']}-Q{n:03d}{sufixo}",
                "ano": ano,
                "dia": arq["dia"],
                "caderno": arq["caderno"],
                "cor": arq["cor"],
                "versao": "DOSVOX (caderno adaptado)",
                "area": arq["area"],
                "area_nome": AREAS[arq["area"]],
                "numero": n,
                "lingua_estrangeira": lingua,
                "enunciado": enunciado,
                "alternativas": dict(zip("ABCDE", q["alts"])),
                "gabarito": resposta,
                "anulada": anulada,
                "tem_descricao_visual": "Descrição d" in enunciado
                    or any("Descrição d" in a for a in q["alts"]),
                "alertas": alertas,
                "fonte": {"prova": arq["url_prova"], "gabarito": arq["url_gabarito"]},
            })

    saida.sort(key=lambda q: (q["dia"], q["numero"], q["lingua_estrangeira"] or ""))
    SAIDA.mkdir(parents=True, exist_ok=True)
    destino = SAIDA / f"{ano}.json"
    destino.write_text(json.dumps(saida, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{ano}: {len(saida)} questões -> {destino.relative_to(RAIZ)}")
    for area in AREAS:
        n = sum(1 for q in saida if q["area"] == area)
        print(f"  {area}: {n}")
    print(f"  anuladas: {sum(q['anulada'] for q in saida)}")
    print(f"  com descrição de figura/gráfico: {sum(q['tem_descricao_visual'] for q in saida)}")
    print(f"  alertas: {len(problemas)}")
    for p in problemas:
        print("   -", p)
    return destino


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ano", type=int, required=True)
    args = ap.parse_args()
    processar_ano(args.ano)


if __name__ == "__main__":
    main()
