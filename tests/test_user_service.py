import pytest
from api.user_service import (
    criar_usuario,
    autenticar_usuario,
    gerar_token_sessao,
    validar_token_sessao,
    listar_usuarios,
    atualizar_usuario,
    resetar_senha,
    alternar_status_usuario,
    excluir_usuario,
)


def test_criar_e_autenticar_usuario():
    # 1. Criar operador
    ok, msg = criar_usuario("alexandre_pcp", "Alexandre PCP", "alexandre@papinhababy.com.br", "senha123", "operador")
    assert ok is True

    # 2. Autenticar com senha correta
    user, err = autenticar_usuario("alexandre_pcp", "senha123")
    assert user is not None
    assert user["username"] == "alexandre_pcp"
    assert user["role"] == "operador"
    assert err == ""

    # 3. Autenticar com senha incorreta
    user_inv, err_inv = autenticar_usuario("alexandre_pcp", "senha_errada")
    assert user_inv is None
    assert "incorretos" in err_inv


def test_sessao_token_lifecycle():
    # Gerar token de sessão
    token = gerar_token_sessao(1, "admin", "admin")
    assert token is not None

    # Validar token
    user_data = validar_token_sessao(token)
    assert user_data is not None
    assert user_data["username"] == "admin"
    assert user_data["role"] == "admin"


def test_admin_crud_operations():
    # Criar usuário temporário
    ok, _ = criar_usuario("temp_user", "Usuario Teste", "teste@papinha.com", "senha123", "operador")
    assert ok is True

    usuarios = listar_usuarios()
    u = next((x for x in usuarios if x["username"] == "temp_user"), None)
    assert u is not None

    # Atualizar
    ok_up, _ = atualizar_usuario(u["id"], "Usuario Teste Atualizado", "novo@papinha.com", "operador")
    assert ok_up is True

    # Resetar senha
    ok_pwd, _ = resetar_senha(u["id"], "novasenha999")
    assert ok_pwd is True

    user_auth, _ = autenticar_usuario("temp_user", "novasenha999")
    assert user_auth is not None

    # Desativar
    ok_tog, _ = alternar_status_usuario(u["id"])
    assert ok_tog is True

    user_bloq, err_bloq = autenticar_usuario("temp_user", "novasenha999")
    assert user_bloq is None
    assert "desativado" in err_bloq.lower()

    # Excluir
    ok_del, _ = excluir_usuario(u["id"])
    assert ok_del is True
