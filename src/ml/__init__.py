"""Módulo de Machine Learning do NodeWatch.

Arquitetura única e modular (scikit-learn) com uma entrada por fonte de dados
e uma cabeça por tarefa:

* ``estado_rede``  — prevê o estado (``OK``/``RISCO``/``FALHA``) da próxima
  medição de um fluxo de rede (``dataset_final.csv``);
* ``lavagem``      — pontua transações do IBM AML HI-Small pelo rótulo
  sintético ``Is Laundering``;
* ``fusao_rede_transacao`` — combinaria sinais de rede e transações. Fica
  bloqueada até existirem transações com telemetria realmente vinculada.

Uso pela linha de comando: ``python -m src.ml.cli --help``.
"""

VERSAO_MODULO = "0.1.0"
