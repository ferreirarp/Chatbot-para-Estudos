#!/usr/bin/env python3
"""Funções compartilhadas pelos scripts: caminhos, download do INEP e leitura
do gabarito em PDF."""

from __future__ import annotations

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
CERT_INTERMEDIARIO = Path(__file__).resolve().parent / "certs" / "rnp_icpedu_gr46_ov_tls_ca_2025.pem"
BASE_DOWNLOAD = "https://download.inep.gov.br/enem/provas_e_gabaritos/"
RESPOSTA = r"(?:[A-E]|Anulad[ao])"


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
