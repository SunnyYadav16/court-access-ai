"""
api/auth.py

Firebase token verification and user lookup for CourtAccess AI.

Replaces the previous JWT-based auth with Firebase Identity Platform.
The backend never handles passwords — Firebase manages all credential flows.
"""

from __future__ import annotations

from datetime import datetime, timezone

import firebase_admin
from firebase_admin import auth as firebase_auth
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User


def verify_token(token: str) -> dict:
    """
    Verify a Firebase ID token and return decoded claims.
    Raises HTTP 401 for expired, invalid, or missing tokens.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    try:
        return firebase_auth.verify_id_token(token)
    except firebase_auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


async def get_or_create_user(claims: dict, db: AsyncSession) -> User:
    """
    Look up user by firebase_uid.
    - Existing user: update last_login_at + email_verified and return
    - New user: create with role='public' (or 'court_official' for saml.massgov)
    """
    uid = claims["uid"]

    result = await db.execute(select(User).where(User.firebase_uid == uid))
    user = result.scalar_one_or_none()

    if user:
        user.last_login_at = datetime.now(timezone.utc)
        user.email_verified = claims.get("email_verified", False)
        await db.commit()
        await db.refresh(user)
        return user

    # Determine role — Mass.gov SAML users are pre-verified government employees
    provider = claims.get("firebase", {}).get("sign_in_provider", "password")
    role = "court_official" if provider == "saml.massgov" else "public"

    # username derived from email (required field in their schema)
    email = claims.get("email", "")
    username = email.split("@")[0] if email else uid[:16]

    user = User(
        firebase_uid=uid,
        email=email,
        username=username,
        hashed_password="firebase_managed",  # never used — Firebase owns credentials
        auth_provider=provider,
        email_verified=claims.get("email_verified", False),
        role=role,
        last_login_at=datetime.now(timezone.utc),
    )

    try:
        db.add(user)
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        # Email already exists under a different firebase_uid — return existing user
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

    return user