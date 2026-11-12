"""Instalação e verificação do modelo de ML distribuído com o repositório.

Por que existe
    ``artefatos_ml/`` é a pasta de trabalho de cada instalação (análises,
    datasets enviados, caches) e fica fora do Git. O modelo treinado ficava só
    ali; quem clonava o repositório abria a interface, mas não conseguia
    analisar nada. Agora o modelo treinado é **distribuído** em ``modelos/``
    (versionado) com um manifesto (``MANIFESTO_MODELO.json``: SHA-256, tamanho,
    versões das bibliotecas, origem dos dados) e é **instalado** em
    ``artefatos_ml/`` na primeira execução.

O que ``garantir_modelo`` faz (sempre na mesma ordem)
    1. Confere se as bibliotecas de ML existem e se as versões são compatíveis
       com as do treino (scikit-learn igual; NumPy, pandas e joblib na mesma
       versão principal). Um modelo ``joblib`` de outra versão do scikit-learn
       pode falhar ao carregar ou prever diferente.
    2. Se ``artefatos_ml/modelo_unificado.joblib`` já existe:
       * com o SHA-256 do manifesto → é o modelo distribuído, já instalado;
       * com outro SHA-256 → é um modelo treinado nesta máquina pela CLI: é
         mantido (nunca sobrescrito) e só validado.
    3. Se não existe: confere o SHA-256 de ``modelos/modelo_unificado.joblib``.
       Se o arquivo faltar ou não bater (corrompido, cópia incompleta, ponteiro
       do Git LFS), baixa do endereço do manifesto (ou de
       ``NODEWATCH_MODELO_URL``), confere o SHA-256 e só então o usa.
    4. Instala em ``artefatos_ml/`` por arquivo temporário + troca atômica, junto
       com ``metadados_modelo.json``: nunca fica um arquivo pela metade.
    5. Valida: carrega o modelo, confere a cabeça ``lavagem``, o preparador
       ``financeiro`` e as colunas, e faz uma previsão de teste (valores em
       [0, 1]). Se a validação falhar depois de uma instalação feita aqui, os
       arquivos instalados são removidos.

Segurança
    Arquivos ``joblib`` executam código ao serem carregados. Por isso nada é
    carregado antes de o SHA-256 bater com o manifesto versionado, e o download
    só usa o endereço do manifesto (ou o da variável, definida por quem roda).

Uso
    python -m src.ml.provisionamento                 # instala/verifica (baixa se preciso)
    python -m src.ml.provisionamento --sem-download  # só usa o que está no disco
    python -m src.ml.provisionamento --preparar-distribuicao
        # (mantenedores) copia o modelo de artefatos_ml/ para modelos/, sem
        # caminhos da máquina nos metadados, e regrava o manifesto
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import ntpath
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

RAIZ = Path(__file__).resolve().parents[2]
PASTA_DISTRIBUIDA = "modelos"
PASTA_ATIVA = "artefatos_ml"
NOME_MODELO = "modelo_unificado.joblib"
NOME_METADADOS = "metadados_modelo.json"
NOME_MANIFESTO = "MANIFESTO_MODELO.json"
VAR_URL = "NODEWATCH_MODELO_URL"
URL_PADRAO = "https://raw.githubusercontent.com/1s4ntos/NodeWatch/main/modelos/modelo_unificado.joblib"
TEMPO_LIMITE_S = 60
# compatibilidade: scikit-learn tem de ser igual; as demais, mesma versão principal
EXATAS = ("scikit-learn",)
MESMA_PRINCIPAL = ("numpy", "pandas", "joblib")
_MODULO = {"scikit-learn": "sklearn", "numpy": "numpy", "pandas": "pandas", "joblib": "joblib"}

_ultimo_erro: Optional["ErroModelo"] = None


class ErroModelo(RuntimeError):
    """Falha ao preparar o modelo, com a causa e o que fazer (mostradas ao usuário)."""

    def __init__(self, causa: str, acao: str):
        super().__init__(causa)
        self.causa, self.acao = causa, acao

    def __str__(self) -> str:
        return self.causa


def ultimo_erro() -> Optional[ErroModelo]:
    """Erro da última tentativa de preparo neste processo (None se deu certo ou não houve)."""
    return _ultimo_erro


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def ler_manifesto(raiz: Path) -> Dict[str, Any]:
    caminho = Path(raiz) / PASTA_DISTRIBUIDA / NOME_MANIFESTO
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErroModelo(f"{PASTA_DISTRIBUIDA}/{NOME_MANIFESTO} não encontrado: a cópia do repositório está incompleta.",
                         "Baixe o repositório de novo (git clone) ou restaure a pasta modelos/.") from None
    except ValueError as exc:
        raise ErroModelo(f"{PASTA_DISTRIBUIDA}/{NOME_MANIFESTO} ilegível ({exc}).",
                         "Restaure o arquivo do repositório: git checkout -- modelos/") from None


def verificar_dependencias(manifesto: Dict[str, Any]) -> Dict[str, str]:
    """Versões instaladas; ErroModelo se faltar biblioteca ou a versão não for compatível."""
    esperado = manifesto.get("dependencias") or {}
    instaladas: Dict[str, str] = {}
    faltando: List[str] = []
    for nome, modulo in _MODULO.items():
        try:
            instaladas[nome] = importlib.import_module(modulo).__version__
        except ImportError:
            faltando.append(nome)
    if faltando:
        raise ErroModelo("Bibliotecas de ML ausentes: " + ", ".join(faltando) + ".",
                         "Instale as dependências no ambiente do projeto: "
                         "python -m pip install -r requirements.txt -r requirements-ml.txt")
    problemas = []
    for nome in EXATAS:
        if nome in esperado and instaladas[nome] != esperado[nome]:
            problemas.append(f"{nome} {instaladas[nome]} (o modelo foi salvo com {esperado[nome]})")
    for nome in MESMA_PRINCIPAL:
        if nome in esperado and instaladas[nome].split(".")[0] != str(esperado[nome]).split(".")[0]:
            problemas.append(f"{nome} {instaladas[nome]} (o modelo foi salvo com {esperado[nome]})")
    if problemas:
        raise ErroModelo("Versões incompatíveis com o modelo distribuído: " + "; ".join(problemas) + ".",
                         "Instale as versões fixadas: python -m pip install -r requirements-ml.txt "
                         "(de preferência num .venv novo, com Python 3.14).")
    return instaladas


def _parece_lfs(caminho: Path) -> bool:
    try:
        with open(caminho, "rb") as f:
            return f.read(48).startswith(b"version https://git-lfs")
    except OSError:
        return False


def baixar(url: str, destino: Path, sha_esperado: str, tamanho: Optional[int],
           avisar: Callable[[str], None] = print) -> None:
    """Baixa para um temporário, confere tamanho e SHA-256 e só então troca o destino."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temp = destino.with_name(destino.name + ".baixando")
    avisar(f"Baixando o modelo de {url} ...")
    try:
        with urllib.request.urlopen(url, timeout=TEMPO_LIMITE_S) as resp, open(temp, "wb") as f:
            total = tamanho or int(resp.headers.get("Content-Length") or 0)
            lidos, proximo = 0, 0.1
            while True:
                bloco = resp.read(1 << 20)
                if not bloco:
                    break
                lidos += len(bloco)
                if tamanho and lidos > tamanho * 1.01:
                    raise ErroModelo(f"O arquivo baixado passou do tamanho esperado ({tamanho} bytes).",
                                     "Confira o endereço em NODEWATCH_MODELO_URL ou no manifesto.")
                f.write(bloco)
                if total and lidos / total >= proximo:
                    avisar(f"  {min(100, int(100 * lidos / total))}% ({lidos / 1e6:.1f} de {total / 1e6:.1f} MB)")
                    proximo += 0.1
        obtido = sha256(temp)
        if obtido != sha_esperado:
            raise ErroModelo(f"O arquivo baixado não confere (SHA-256 {obtido[:12]}…, esperado {sha_esperado[:12]}…).",
                             "Tente de novo; se repetir, o endereço não serve a versão deste repositório.")
        os.replace(temp, destino)
    except ErroModelo:
        raise
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        motivo = getattr(exc, "reason", None) or exc
        raise ErroModelo(f"Falha ao baixar o modelo de {url}: {motivo}.",
                         "Confira a conexão com a internet e rode de novo: python -m src.ml.provisionamento. "
                         f"Sem internet: copie {NOME_MODELO} do repositório para a pasta {PASTA_DISTRIBUIDA}/.") from None
    finally:
        if temp.exists():
            temp.unlink()


def _copiar_atomico(origem: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    temp = destino.with_name(destino.name + ".instalando")
    try:
        shutil.copyfile(origem, temp)
        os.replace(temp, destino)
    finally:
        if temp.exists():
            temp.unlink()


def validar(pasta: Path, manifesto: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Carrega o modelo e faz uma previsão de teste; ErroModelo se algo não servir ao painel."""
    import numpy as np
    import pandas as pd

    from src.ml.modelos import CabecaClassificacao, ModeloUnificado
    try:
        modelo = ModeloUnificado.carregar(pasta)
    except Exception as exc:  # joblib/pickle podem levantar vários tipos
        raise ErroModelo(f"O modelo em {pasta.name}/{NOME_MODELO} não pôde ser carregado ({type(exc).__name__}: {exc}).",
                         f"Se ele foi treinado nesta máquina, treine de novo (python -m src.ml.cli treinar --tarefa lavagem); "
                         f"para voltar ao modelo distribuído, renomeie ou apague {PASTA_ATIVA}/{NOME_MODELO} "
                         "e rode python -m src.ml.provisionamento.") from None
    cab = modelo.cabecas.get("lavagem")
    if not isinstance(cab, CabecaClassificacao) or "financeiro" not in modelo.codificadores:
        raise ErroModelo("O modelo não tem a cabeça 'lavagem' e o preparador 'financeiro' que o painel usa.",
                         f"Use o modelo distribuído: renomeie {PASTA_ATIVA}/{NOME_MODELO} e rode python -m src.ml.provisionamento.")
    prep = modelo.codificadores["financeiro"]
    if list(prep.colunas) != list(cab.colunas_entrada):
        raise ErroModelo("As colunas do preparador e do modelo de lavagem não coincidem.",
                         "Treine de novo pela CLI ou volte ao modelo distribuído.")
    esperado = (manifesto or {}).get("lavagem", {})
    if esperado.get("colunas") and esperado.get("versao") == cab.metadados.get("versao") \
            and len(cab.colunas_entrada) != esperado["colunas"]:
        raise ErroModelo("O modelo tem colunas diferentes das registradas no manifesto.", "Restaure a pasta modelos/.")
    X = pd.DataFrame(np.zeros((4, len(cab.colunas_entrada)), dtype=np.float32), columns=cab.colunas_entrada)
    try:
        p = cab.probabilidades(X)
    except Exception as exc:
        raise ErroModelo(f"A previsão de teste falhou ({type(exc).__name__}: {exc}).",
                         "Confira as versões com python -m pip install -r requirements-ml.txt.") from None
    if p.shape != (4, len(cab.classes)) or not np.all(np.isfinite(p)) or p.min() < 0 or p.max() > 1:
        raise ErroModelo("A previsão de teste devolveu valores fora de [0, 1].", "Restaure o modelo distribuído.")
    return {"versao": cab.metadados.get("versao"), "colunas": len(cab.colunas_entrada),
            "limiar_alerta": float(cab.limiar_alerta)}


def garantir_modelo(raiz: Path = RAIZ, baixar_se_preciso: bool = True,
                    avisar: Callable[[str], None] = print) -> Dict[str, Any]:
    """Deixa ``artefatos_ml/`` com um modelo íntegro, compatível e validado. Ver o docstring do módulo."""
    global _ultimo_erro
    raiz = Path(raiz)
    try:
        resultado = _garantir(raiz, baixar_se_preciso, avisar)
        _ultimo_erro = None
        return resultado
    except ErroModelo as exc:
        _ultimo_erro = exc
        raise


def _garantir(raiz: Path, baixar_se_preciso: bool, avisar: Callable[[str], None]) -> Dict[str, Any]:
    manifesto = ler_manifesto(raiz)
    versoes = verificar_dependencias(manifesto)
    ativa, dist = raiz / PASTA_ATIVA, raiz / PASTA_DISTRIBUIDA
    alvo = ativa / NOME_MODELO
    sha_dist = manifesto["sha256"]

    if alvo.is_file():
        sha_ativo = sha256(alvo)
        origem = "ja_instalado" if sha_ativo == sha_dist else "local_proprio"
        if origem == "local_proprio":
            avisar("Modelo próprio desta máquina em artefatos_ml/ (diferente do distribuído): mantido, só validado.")
        info = validar(ativa, manifesto)
        return {"origem": origem, "sha256": sha_ativo, "dependencias": versoes, **info}

    fonte = dist / NOME_MODELO
    origem = "copiado"
    if not fonte.is_file() or _parece_lfs(fonte) or sha256(fonte) != sha_dist:
        motivo = ("não existe" if not fonte.is_file() else "é um ponteiro do Git LFS" if _parece_lfs(fonte)
                  else "não confere com o SHA-256 do manifesto")
        if not baixar_se_preciso:
            raise ErroModelo(f"{PASTA_DISTRIBUIDA}/{NOME_MODELO} {motivo}.",
                             "Rode python -m src.ml.provisionamento (com internet) para baixar o modelo, "
                             "ou restaure o arquivo: git checkout -- modelos/")
        avisar(f"{PASTA_DISTRIBUIDA}/{NOME_MODELO} {motivo}; baixando a versão do manifesto.")
        url = os.environ.get(VAR_URL) or (manifesto.get("download") or {}).get("url") or URL_PADRAO
        baixar(url, fonte, sha_dist, manifesto.get("bytes"), avisar)
        origem = "baixado"

    instalados = []
    try:
        _copiar_atomico(fonte, alvo)
        instalados.append(alvo)
        meta_fonte = dist / NOME_METADADOS
        if meta_fonte.is_file():
            _copiar_atomico(meta_fonte, ativa / NOME_METADADOS)
            instalados.append(ativa / NOME_METADADOS)
        info = validar(ativa, manifesto)
    except BaseException:
        for arq in instalados:  # nada pela metade: sem modelo validado, nada fica instalado
            try:
                arq.unlink()
            except OSError:
                pass
        raise
    avisar(f"Modelo instalado em {PASTA_ATIVA}/ ({'baixado' if origem == 'baixado' else 'cópia de modelos/'}).")
    return {"origem": origem, "sha256": sha_dist, "dependencias": versoes, **info}


# ---------------------------------------------------------------------------
# Mantenedores: preparar a distribuição a partir de um modelo treinado
# ---------------------------------------------------------------------------
_ABSOLUTO = re.compile(r"^([A-Za-z]:[\\/]|/)")


def _sem_caminhos(o: Any) -> None:
    """Troca caminhos absolutos da máquina por só o nome do arquivo (metadados; não muda previsões)."""
    if isinstance(o, dict):
        for k, v in list(o.items()):
            if isinstance(v, str) and _ABSOLUTO.match(v):
                o[k] = ntpath.basename(v.replace("/", "\\"))
            else:
                _sem_caminhos(v)
    elif isinstance(o, list):
        for v in o:
            _sem_caminhos(v)


def preparar_distribuicao(raiz: Path = RAIZ, url: str = URL_PADRAO) -> Dict[str, Any]:
    """Copia o modelo de ``artefatos_ml/`` para ``modelos/`` (sem caminhos locais) e grava o manifesto."""
    import joblib

    from src.ml.modelos import ModeloUnificado, versoes
    raiz = Path(raiz)
    modelo = ModeloUnificado.carregar(raiz / PASTA_ATIVA)
    _sem_caminhos(modelo.metadados)
    for cab in modelo.cabecas.values():
        for attr in ("metadados", "requisitos"):
            if isinstance(getattr(cab, attr, None), (dict, list)):
                _sem_caminhos(getattr(cab, attr))
    dist = raiz / PASTA_DISTRIBUIDA
    dist.mkdir(exist_ok=True)
    joblib.dump(modelo, dist / NOME_MODELO, compress=3)
    meta = json.loads((raiz / PASTA_ATIVA / NOME_METADADOS).read_text(encoding="utf-8"))
    _sem_caminhos(meta)
    (dist / NOME_METADADOS).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    lav = modelo.cabeca("lavagem")
    md = lav.metadados or {}
    salvas = modelo.metadados.get("versoes") or versoes()
    manifesto = {
        "formato_manifesto": 1,
        "artefato": NOME_MODELO,
        "sha256": sha256(dist / NOME_MODELO),
        "bytes": (dist / NOME_MODELO).stat().st_size,
        "metadados": NOME_METADADOS,
        "sha256_metadados": sha256(dist / NOME_METADADOS),
        "salvo_em": modelo.metadados.get("salvo_em"),
        "preparado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lavagem": {"versao": md.get("versao"), "familia": lav.familia, "params": lav.params,
                    "colunas": len(lav.colunas_entrada), "limiar_alerta": lav.limiar_alerta,
                    "treinado_ate": md.get("treinado_ate"), "sha256_dados_treino": md.get("sha256")},
        "outras_cabecas": {n: getattr(c, "status", "") for n, c in modelo.cabecas.items() if n != "lavagem"},
        "dependencias": {k: salvas[k] for k in ("python", "scikit-learn", "numpy", "pandas", "joblib") if k in salvas},
        "politica_compatibilidade": "scikit-learn igual; numpy, pandas e joblib na mesma versão principal",
        "dados_de_treino": {
            "nome": "IBM Transactions for Anti Money Laundering (AML) — HI-Small (sintético)",
            "arquivo": "HI-Small_Trans.zip",
            "fonte": "https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml",
            "licenca": "CDLA-Sharing-1.0 (https://cdla.dev/sharing-1-0/)",
        },
        "licenca_do_modelo": ("O modelo é um resultado (Results) do uso computacional dos dados; a CDLA-Sharing-1.0, "
                              "seção 3.5, não impõe obrigações ou restrições aos Results."),
        "download": {"url": url},
    }
    (dist / NOME_MANIFESTO).write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8", newline="\n")
    return manifesto


def _linhas(resultado: Dict[str, Any]) -> List[str]:
    origem = {"ja_instalado": "já instalado", "copiado": "instalado agora a partir de modelos/",
              "baixado": "baixado e instalado agora", "local_proprio": "modelo próprio desta máquina"}[resultado["origem"]]
    return [f"[OK] Modelo de ML pronto: {resultado['versao']} ({origem}); {resultado['colunas']} atributos; "
            f"limiar de alerta {resultado['limiar_alerta']:.4f}.",
            "     Bibliotecas: " + ", ".join(f"{k} {v}" for k, v in resultado["dependencias"].items())]


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.ml.provisionamento", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sem-download", action="store_true", help="não baixar; só usar o que está no disco")
    p.add_argument("--preparar-distribuicao", action="store_true",
                   help="(mantenedores) copiar o modelo de artefatos_ml/ para modelos/ e regravar o manifesto")
    a = p.parse_args(argv)
    if a.preparar_distribuicao:
        m = ler_manifesto(RAIZ) if (RAIZ / PASTA_DISTRIBUIDA / NOME_MANIFESTO).is_file() else {}
        novo = preparar_distribuicao(RAIZ, (m.get("download") or {}).get("url") or URL_PADRAO)
        print(f"Distribuição preparada: {novo['lavagem']['versao']}, SHA-256 {novo['sha256']}, {novo['bytes']} bytes.")
        return 0
    try:
        for linha in _linhas(garantir_modelo(RAIZ, not a.sem_download)):
            print(linha)
        return 0
    except ErroModelo as exc:
        print(f"[ERRO] {exc.causa}", file=sys.stderr)
        print(f"       O que fazer: {exc.acao}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    sys.exit(main())
