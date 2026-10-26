"""Supabase Auth token verification for the FastAPI boundary."""

from __future__ import annotations

import os
from typing import Any

import requests
from fastapi import Header, HTTPException


def require_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Verify a Supabase access token and return the authenticated user."""
    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    anon_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not supabase_url or not anon_key:
        raise HTTPException(status_code=503, detail="Supabase Auth is not configured on the API.")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to use this workspace.")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    try:
        response = requests.get(
            f"{supabase_url}/auth/v1/user",
            headers={"apikey": anon_key, "Authorization": f"Bearer {token}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Could not reach Supabase Auth.") from exc

    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Your session is invalid or expired.")
    try:
        user = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Supabase returned an invalid session.") from exc
    user_id = user.get("id") if isinstance(user, dict) else None
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Supabase session has no user id.")
    return user
