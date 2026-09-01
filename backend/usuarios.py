"""Cadastro local de usuários do dashboard (JSON em data/)."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

USUARIOS_PATH = Path(__file__).resolve().parent / "data" / "usuarios.json"
_PBKDF2_ITERS = 260_000


def _agora_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _hash_senha(senha: str, *, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, _PBKDF2_ITERS)
    return digest.hex(), salt.hex()


def _verificar_senha(senha: str, senha_hash: str, salt_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
        esperado, _ = _hash_senha(senha, salt=salt)
    except ValueError:
        return False
    return secrets.compare_digest(esperado, senha_hash)


def _normalizar_username(username: str) -> str:
    return username.strip().lower()


def _username_de_row(row: dict[str, Any]) -> str:
    if row.get("username"):
        return str(row["username"])
    if row.get("email"):
        return str(row["email"])
    return ""


def _carregar_raw() -> dict[str, Any]:
    if not USUARIOS_PATH.exists():
        return {"usuarios": []}
    try:
        raw = json.loads(USUARIOS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {"usuarios": []}
    if not isinstance(raw.get("usuarios"), list):
        return {"usuarios": []}
    return raw


def _persistir(usuarios: list[dict[str, Any]]) -> None:
    USUARIOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    USUARIOS_PATH.write_text(
        json.dumps({"usuarios": usuarios}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _publico(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "nome": str(row.get("nome") or ""),
        "username": _username_de_row(row),
        "perfil": str(row.get("perfil") or "usuario"),
        "ativo": bool(row.get("ativo", True)),
        "criado_em": row.get("criado_em"),
        "atualizado_em": row.get("atualizado_em"),
    }


def _garantir_admin_inicial() -> None:
    raw = _carregar_raw()
    usuarios: list[dict[str, Any]] = list(raw.get("usuarios") or [])
    if usuarios:
        return
    username = _normalizar_username(os.getenv("AUTH_ADMIN_USERNAME") or "admin")
    senha = (os.getenv("AUTH_ADMIN_PASSWORD") or "admin123").strip()
    nome = (os.getenv("AUTH_ADMIN_NOME") or "Administrador").strip()
    h, s = _hash_senha(senha)
    agora = _agora_iso()
    usuarios.append(
        {
            "id": 1,
            "nome": nome,
            "username": username,
            "senha_hash": h,
            "salt": s,
            "perfil": "admin",
            "ativo": True,
            "criado_em": agora,
            "atualizado_em": agora,
        }
    )
    _persistir(usuarios)


def listar_usuarios() -> list[dict[str, Any]]:
    _garantir_admin_inicial()
    return [_publico(u) for u in _carregar_raw().get("usuarios") or []]


def obter_usuario(usuario_id: int) -> dict[str, Any] | None:
    _garantir_admin_inicial()
    for row in _carregar_raw().get("usuarios") or []:
        if int(row.get("id") or 0) == usuario_id:
            return _publico(row)
    return None


def autenticar(username: str, senha: str) -> dict[str, Any] | None:
    _garantir_admin_inicial()
    alvo = _normalizar_username(username)
    for row in _carregar_raw().get("usuarios") or []:
        if _normalizar_username(_username_de_row(row)) != alvo:
            continue
        if not row.get("ativo", True):
            return None
        if not _verificar_senha(senha, str(row.get("senha_hash") or ""), str(row.get("salt") or "")):
            return None
        return _publico(row)
    return None


def criar_usuario(
    *,
    nome: str,
    username: str,
    senha: str,
    perfil: str = "usuario",
    ativo: bool = True,
) -> dict[str, Any]:
    _garantir_admin_inicial()
    nome = nome.strip()
    username = _normalizar_username(username)
    if not nome or not username or not senha:
        raise ValueError("Nome, username e senha são obrigatórios.")
    if perfil not in ("admin", "usuario"):
        raise ValueError("Perfil inválido.")
    usuarios: list[dict[str, Any]] = list(_carregar_raw().get("usuarios") or [])
    if any(_normalizar_username(_username_de_row(u)) == username for u in usuarios):
        raise ValueError("Username já cadastrado.")
    novo_id = max((int(u.get("id") or 0) for u in usuarios), default=0) + 1
    h, s = _hash_senha(senha)
    agora = _agora_iso()
    row = {
        "id": novo_id,
        "nome": nome,
        "username": username,
        "senha_hash": h,
        "salt": s,
        "perfil": perfil,
        "ativo": ativo,
        "criado_em": agora,
        "atualizado_em": agora,
    }
    usuarios.append(row)
    _persistir(usuarios)
    return _publico(row)


def atualizar_usuario(
    usuario_id: int,
    *,
    nome: str | None = None,
    username: str | None = None,
    senha: str | None = None,
    perfil: str | None = None,
    ativo: bool | None = None,
) -> dict[str, Any]:
    _garantir_admin_inicial()
    usuarios: list[dict[str, Any]] = list(_carregar_raw().get("usuarios") or [])
    idx = next((i for i, u in enumerate(usuarios) if int(u.get("id") or 0) == usuario_id), None)
    if idx is None:
        raise LookupError("Usuário não encontrado.")
    row = dict(usuarios[idx])
    if nome is not None:
        row["nome"] = nome.strip()
    if username is not None:
        novo_username = _normalizar_username(username)
        if any(
            _normalizar_username(_username_de_row(u)) == novo_username
            and int(u.get("id") or 0) != usuario_id
            for u in usuarios
        ):
            raise ValueError("Username já cadastrado.")
        row["username"] = novo_username
        row.pop("email", None)
    if perfil is not None:
        if perfil not in ("admin", "usuario"):
            raise ValueError("Perfil inválido.")
        row["perfil"] = perfil
    if ativo is not None:
        row["ativo"] = bool(ativo)
    if senha:
        h, s = _hash_senha(senha)
        row["senha_hash"] = h
        row["salt"] = s
    row["atualizado_em"] = _agora_iso()
    usuarios[idx] = row
    _persistir(usuarios)
    return _publico(row)


def excluir_usuario(usuario_id: int) -> None:
    _garantir_admin_inicial()
    usuarios: list[dict[str, Any]] = list(_carregar_raw().get("usuarios") or [])
    admins = [u for u in usuarios if str(u.get("perfil")) == "admin" and u.get("ativo", True)]
    alvo = next((u for u in usuarios if int(u.get("id") or 0) == usuario_id), None)
    if alvo is None:
        raise LookupError("Usuário não encontrado.")
    if str(alvo.get("perfil")) == "admin" and len(admins) <= 1:
        raise ValueError("Não é possível excluir o último administrador.")
    usuarios = [u for u in usuarios if int(u.get("id") or 0) != usuario_id]
    _persistir(usuarios)
