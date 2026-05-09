"""Configuração do pytest.

Adiciona a raiz do projeto ao sys.path para que os testes possam
importar usando o caminho absoluto (ex.: ``from src.core.graph import Graph``)
sem depender de instalação prévia (``pip install -e .``).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
