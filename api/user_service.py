"""
api/user_service.py — Gerenciamento de usuários, persistência SQLite e autenticação RBAC.
"""

import os
import sqlite3
import hashlib
import hmac
import time
import secrets
from pathlib import Path
from typing import Optional, Dict, List, Tuple

# Diretório e caminho do banco de dados SQLite
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "users.db"

# Chave secreta para assinatura dos tokens de sessão
_SESSION_SECRET = os.getenv("SESSION_SECRET", "papinha_pcp_secure_session_secret_key_2026").encode("utf-8")


def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Inicializa as tabelas do banco de dados e cria o admin padrão se não existir."""
    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                email TEXT DEFAULT '',
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'operador',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        """)
        conn.commit()

        # Verificar se existe ao menos um usuário admin
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        if cursor.fetchone()[0] == 0:
            # Criar usuário admin inicial padrão
            senha_admin_padrao = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123456")
            hash_senha = _hashear_senha(senha_admin_padrao)
            cursor.execute("""
                INSERT INTO users (username, name, email, password_hash, role, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
            """, ("admin", "Administrador do Sistema", "admin@papinhababy.com.br", hash_senha, "admin"))
            conn.commit()
            print("[User Service] Usuário 'admin' padrão criado com sucesso!")


def _hashear_senha(senha: str) -> str:
    """Gera hash PBKDF2-HMAC-SHA256 com salt aleatório de 32 bytes."""
    salt = secrets.token_hex(16)
    kdf = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt.encode("utf-8"), 200000)
    return f"{salt}${kdf.hex()}"


def _verificar_senha(senha: str, hash_armazenado: str) -> bool:
    """Verifica se a senha em texto plano corresponde ao hash armazenado."""
    try:
        salt, kdf_esperado = hash_armazenado.split("$")
        kdf = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt.encode("utf-8"), 200000)
        return hmac.compare_digest(kdf.hex(), kdf_esperado)
    except Exception:
        return False


# ── Gerenciamento de Sessão ──────────────────────────────────────────────────

def gerar_token_sessao(user_id: int, username: str, role: str) -> str:
    """
    Gera um token de sessão assinado com validade de 7 dias.
    Payload: user_id:username:role:expiracao:assinatura
    """
    expiracao = int(time.time()) + (7 * 24 * 3600)  # 7 dias
    payload = f"{user_id}:{username}:{role}:{expiracao}"
    assinatura = hmac.new(_SESSION_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{assinatura}"


def validar_token_sessao(token: str) -> Optional[Dict]:
    """
    Valida a assinatura e expiração do token de sessão.
    Retorna os dados do usuário ou None se for inválido.
    """
    if not token:
        return None

    partes = token.split(":")
    if len(partes) != 5:
        return None

    user_id_str, username, role, expiracao_str, assinatura_recebida = partes

    try:
        expiracao = int(expiracao_str)
        if time.time() > expiracao:
            return None

        payload = f"{user_id_str}:{username}:{role}:{expiracao_str}"
        assinatura_calculada = hmac.new(_SESSION_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(assinatura_recebida, assinatura_calculada):
            return None

        # Checar se o usuário ainda existe e está ativo no banco
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, name, email, role, is_active FROM users WHERE id = ?", (int(user_id_str),))
            row = cursor.fetchone()
            if not row or row["is_active"] != 1:
                return None

            return {
                "id": row["id"],
                "username": row["username"],
                "name": row["name"],
                "email": row["email"],
                "role": row["role"],
            }
    except Exception:
        return None


# ── Operações CRUD de Usuários ───────────────────────────────────────────────

def autenticar_usuario(username: str, senha: str) -> Tuple[Optional[Dict], str]:
    """
    Autentica usuário e senha.
    Retorna (dados_usuario, "") em caso de sucesso ou (None, "mensagem_erro").
    """
    u_clean = username.strip().lower()
    if not u_clean or not senha:
        return None, "Preencha usuário e senha."

    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE LOWER(username) = ?", (u_clean,))
        user = cursor.fetchone()

        if not user:
            return None, "Usuário ou senha incorretos."

        if user["is_active"] != 1:
            return None, "Este usuário foi desativado. Contate o administrador."

        if not _verificar_senha(senha, user["password_hash"]):
            return None, "Usuário ou senha incorretos."

        # Atualizar last_login
        cursor.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user["id"],))
        conn.commit()

        return {
            "id": user["id"],
            "username": user["username"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
        }, ""


def criar_usuario(username: str, name: str, email: str, senha: str, role: str = "operador") -> Tuple[bool, str]:
    """Cria um novo usuário no banco de dados."""
    u_clean = username.strip().lower()
    n_clean = name.strip()
    e_clean = email.strip()

    if not u_clean or len(u_clean) < 3:
        return False, "O nome de usuário deve ter no mínimo 3 caracteres."
    if not n_clean:
        return False, "Informe o nome completo do usuário."
    if not senha or len(senha) < 6:
        return False, "A senha deve ter no mínimo 6 caracteres."
    if role not in ("admin", "operador"):
        role = "operador"

    hash_senha = _hashear_senha(senha)

    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (username, name, email, password_hash, role, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (u_clean, n_clean, e_clean, hash_senha, role))
            conn.commit()
            return True, "Usuário criado com sucesso!"
    except sqlite3.IntegrityError:
        return False, "Este nome de usuário já está cadastrado."
    except Exception as e:
        return False, f"Erro ao criar usuário: {e}"


def listar_usuarios() -> List[Dict]:
    """Retorna lista de todos os usuários (sem expor hash de senha)."""
    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, name, email, role, is_active, created_at, last_login 
            FROM users 
            ORDER BY created_at DESC
        """)
        return [dict(row) for row in cursor.fetchall()]


def atualizar_usuario(user_id: int, name: str, email: str, role: str) -> Tuple[bool, str]:
    """Atualiza dados cadastrais de um usuário."""
    if role not in ("admin", "operador"):
        role = "operador"

    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users 
            SET name = ?, email = ?, role = ? 
            WHERE id = ?
        """, (name.strip(), email.strip(), role, user_id))
        conn.commit()
        if cursor.rowcount == 0:
            return False, "Usuário não encontrado."
        return True, "Usuário atualizado com sucesso!"


def resetar_senha(user_id: int, nova_senha: str) -> Tuple[bool, str]:
    """Redefine a senha de um usuário."""
    if not nova_senha or len(nova_senha) < 6:
        return False, "A nova senha deve ter no mínimo 6 caracteres."

    hash_senha = _hashear_senha(nova_senha)
    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_senha, user_id))
        conn.commit()
        if cursor.rowcount == 0:
            return False, "Usuário não encontrado."
        return True, "Senha redefinida com sucesso!"


def alternar_status_usuario(user_id: int) -> Tuple[bool, str]:
    """Ativa ou desativa um usuário (exceto se for o único admin ativo)."""
    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            return False, "Usuário não encontrado."

        novo_status = 0 if user["is_active"] == 1 else 1

        # Não permitir desativar o último admin
        if user["role"] == "admin" and novo_status == 0:
            cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1")
            if cursor.fetchone()[0] <= 1:
                return False, "Não é permitido desativar o único administrador ativo do sistema."

        cursor.execute("UPDATE users SET is_active = ? WHERE id = ?", (novo_status, user_id))
        conn.commit()
        msg = "Usuário ativado com sucesso!" if novo_status == 1 else "Usuário desativado com sucesso!"
        return True, msg


def excluir_usuario(user_id: int) -> Tuple[bool, str]:
    """Exclui um usuário do sistema."""
    with _get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            return False, "Usuário não encontrado."

        if user["role"] == "admin":
            cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
            if cursor.fetchone()[0] <= 1:
                return False, "Não é permitido excluir o único administrador do sistema."

        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return True, "Usuário excluído com sucesso!"


# Inicializar DB ao carregar o módulo
init_db()
