"""
api/security.py — Módulo de proteção contra ataques, bots e sobrecarga da API.
Implementa validação com Google reCAPTCHA v2 e Rate Limiting por IP.
"""

import time
import os
import requests
from typing import Dict, List, Tuple, Optional

# Chaves do Google reCAPTCHA v2
RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY", "6LdbRpotAAAAALpenNMdGvaSL2lQXMfp3w-AvJJS")
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY", "6LdbRpotAAAAAI5_Sb1XFjWILSRmfejxY04CacjY")
RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"

# Armazenamento em memória para Rate Limiting {ip: [timestamps]}
_RATE_LIMIT_BUCKET: Dict[str, List[float]] = {}


def validar_google_recaptcha(token_resposta: str, ip_cliente: Optional[str] = None) -> Tuple[bool, str]:
    """
    Valida o token do Google reCAPTCHA v2 contra os servidores do Google.
    """
    if not token_resposta:
        return False, "Por favor, marque a caixa de seleção 'Não sou um robô' para verificar a segurança."

    try:
        dados = {
            "secret": RECAPTCHA_SECRET_KEY,
            "response": token_resposta,
        }
        if ip_cliente:
            dados["remoteip"] = ip_cliente

        resp = requests.post(RECAPTCHA_VERIFY_URL, data=dados, timeout=8)
        resultado = resp.json()

        if resultado.get("success") is True:
            return True, ""

        error_codes = resultado.get("error-codes", [])
        return False, f"Falha na validação do reCAPTCHA ({', '.join(error_codes) if error_codes else 'desafio expirado'}). Tente novamente."

    except Exception as e:
        # Se houver timeout ou erro de rede no Google, não travar o cliente legítimo
        return False, f"Erro de comunicação com o serviço de segurança: {e}"


def verificar_rate_limit(ip_cliente: str, limite_por_minuto: int = 15) -> Tuple[bool, str]:
    """
    Controla a taxa de requisições por IP para proteger o ERP Excia contra sobrecarga.
    """
    if not ip_cliente:
        return True, ""

    agora = time.time()
    janela = agora - 60.0  # Último 1 minuto

    # Obter histórico do IP e descartar requisições antigas
    historico = _RATE_LIMIT_BUCKET.get(ip_cliente, [])
    historico = [t for t in historico if t > janela]

    if len(historico) >= limite_por_minuto:
        _RATE_LIMIT_BUCKET[ip_cliente] = historico
        return False, f"Limite de consultas excedido ({limite_por_minuto}/minuto). Por favor, aguarde alguns instantes para proteger a integração do ERP."

    historico.append(agora)
    _RATE_LIMIT_BUCKET[ip_cliente] = historico
    return True, ""
