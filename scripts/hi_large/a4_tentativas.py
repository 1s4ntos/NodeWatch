"""Distribuição das tentativas de lavagem entre as partições da janela de 12 dias.

Para cada partição (treino, validação, teste, reserva), conta os positivos:

* de tentativas iniciadas na própria partição;
* de tentativas iniciadas em partição anterior (continuação; saem da avaliação pela Emenda 1);
* sem padrão (não agrupáveis).

E monta a matriz "partição de início × partições em que a tentativa tem eventos".
Usa só o arquivo de padrões casado com as transações; nada vira atributo.

Uso::

    python scripts/hi_large/a4_tentativas.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

import comum

DIA0 = int((pd.Timestamp("2022-08-01") - pd.Timestamp("1970-01-01")) // pd.Timedelta(minutes=1))
NOMES = np.array(["treino", "validacao", "teste", "reserva", "depois"])


def particao(minuto: np.ndarray) -> np.ndarray:
    dia = (minuto - DIA0) // 1440
    return NOMES[np.select([dia < 6, dia < 8, dia < 10, dia < 12], [0, 1, 2, 3], 4)]


def main() -> None:
    pp = pd.read_parquet(comum.TRABALHO / "padroes_casados.parquet", columns=["tentativa", "tipo_padrao", "minuto", "linha"])
    pos = pd.read_parquet(comum.TRABALHO / "positivos.parquet", columns=["linha", "minuto"])
    inicio = pp.groupby("tentativa")["minuto"].min()
    pp["particao_evento"] = particao(pp["minuto"].to_numpy())
    pp["particao_inicio"] = particao(pp["tentativa"].map(inicio).to_numpy())
    janela = pp[pp["particao_inicio"] != "depois"]
    matriz = (janela.groupby(["particao_inicio", "particao_evento"])["tentativa"].nunique()
              .unstack(fill_value=0).reindex(index=NOMES[:4], columns=NOMES, fill_value=0))
    eventos = (janela.groupby(["particao_inicio", "particao_evento"]).size()
               .unstack(fill_value=0).reindex(index=NOMES[:4], columns=NOMES, fill_value=0))
    pos["particao"] = particao(pos["minuto"].to_numpy())
    em_padrao = pp.set_index("linha")
    pos["inicio_tentativa"] = pos["linha"].map(em_padrao["particao_inicio"])
    resumo: Dict[str, Any] = {}
    ordem = {n: i for i, n in enumerate(NOMES)}
    for nome in NOMES[:4]:
        p = pos[pos["particao"] == nome]
        ini = p["inicio_tentativa"]
        resumo[nome] = {
            "positivos": int(len(p)),
            "tentativa_iniciada_na_particao": int((ini == nome).sum()),
            "continuacao_de_particao_anterior": int(ini.dropna().map(ordem).lt(ordem[nome]).sum()),
            "sem_padrao": int(ini.isna().sum()),
        }
    saida = {
        "gerado_em_utc": comum.agora(), "script": Path(__file__).name,
        "tentativas_por_particao_de_inicio_e_de_evento": {i: matriz.loc[i].to_dict() for i in matriz.index},
        "eventos_por_particao_de_inicio_e_de_evento": {i: eventos.loc[i].to_dict() for i in eventos.index},
        "positivos_por_particao": resumo,
        "leitura": ("Linhas: partição em que a tentativa começa. Colunas: partições em que ela tem eventos. "
                    "Pela Emenda 1, eventos à direita da diagonal saem da avaliação."),
    }
    print(comum.salvar_json(saida, "a4_tentativas.json"))


if __name__ == "__main__":
    main()
