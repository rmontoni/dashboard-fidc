"""Autenticação por token assinado (HMAC) e helpers FastAPI."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import Depends, Header, HTTPException

TOKEN_TTL_S = int(os.getenv("AUTH_TOKEN_TTL_S", str(7 * 24 * 3600)))


def _secret() -> bytes:
    raw = (os.getenv("AUTH_SECRET") or "").strip()
    if not raw:
        raw = "fidc-dev-secret-altere-em-producao"
    return raw.encode("utf-8")


def criar_token(usuario: dict[str, Any]) -> str:
    exp = int(time.time()) + TOKEN_TTL_S
    body = {
        "sub": int(usuario["id"]),
        "username": str(usuario["username"]),
        "nome": str(usuario.get("nome") or ""),
        "perfil": str(usuario.get("perfil") or "usuario"),
        "exp": exp,
    }
    payload = base64.urlsafe_b64encode(
        json.dumps(body, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    sig = hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def decodificar_token(token: str) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    esperado = hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(esperado, sig):
        return None
    pad = "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload + pad)
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if int(body.get("exp") or 0) < int(time.time()):
        return None
    return body


def usuario_de_token(token: str) -> dict[str, Any] | None:
    body = decodificar_token(token)
    if not body:
        return None
    username = body.get("username") or body.get("email") or ""
    return {
        "id": int(body["sub"]),
        "username": str(username),
        "nome": str(body.get("nome") or ""),
        "perfil": str(body.get("perfil") or "usuario"),
    }


def _extrair_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    partes = authorization.strip().split(None, 1)
    if len(partes) != 2 or partes[0].lower() != "bearer":
        return None
    return partes[1].strip() or None


async def usuario_opcional(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any] | None:
    token = _extrair_bearer(authorization)
    if not token:
        return None
    return usuario_de_token(token)


async def exigir_usuario(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    token = _extrair_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    user = usuario_de_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.")
    return user


async def exigir_admin(usuario: dict[str, Any] = Depends(exigir_usuario)) -> dict[str, Any]:
    if str(usuario.get("perfil") or "") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores.")
    return usuario
