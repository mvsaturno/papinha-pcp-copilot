import pytest
from unittest.mock import patch, MagicMock
from api.security import validar_google_recaptcha, verificar_rate_limit


def test_validar_google_recaptcha_vazio():
    valido, msg = validar_google_recaptcha("")
    assert valido is False
    assert "Não sou um robô" in msg


@patch("requests.post")
def test_validar_google_recaptcha_sucesso(mock_post):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"success": True}
    mock_post.return_value = mock_resp

    valido, msg = validar_google_recaptcha("token_valido_123")
    assert valido is True
    assert msg == ""


@patch("requests.post")
def test_validar_google_recaptcha_falha(mock_post):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"success": False, "error-codes": ["invalid-input-response"]}
    mock_post.return_value = mock_resp

    valido, msg = validar_google_recaptcha("token_invalido_999")
    assert valido is False
    assert "invalid-input-response" in msg


def test_rate_limiting():
    ip_teste = "192.168.100.201"

    # 15 requisições devem passar
    for _ in range(15):
        permitido, msg = verificar_rate_limit(ip_teste, limite_por_minuto=15)
        assert permitido is True

    # 16ª requisição deve ser bloqueada
    permitido, msg = verificar_rate_limit(ip_teste, limite_por_minuto=15)
    assert permitido is False
    assert "Limite de consultas excedido" in msg
