"""
passenger_wsgi.py — Ponto de entrada exigido pelo Phusion Passenger (hPanel da Hostinger).

A Hostinger (hospedagem compartilhada/Business) roda apps Python via Passenger,
que espera um callable WSGI chamado `application`. O FastAPI é ASGI, então
usamos a2wsgi para converter — nenhuma mudança é necessária em app.py.

Configuração no hPanel > Setup Python App:
  Arquivo de inicialização: passenger_wsgi.py
  Ponto de entrada (entry point): application
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from a2wsgi import ASGIMiddleware

from app import app as _fastapi_app

application = ASGIMiddleware(_fastapi_app)
