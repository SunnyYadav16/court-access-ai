"""
api/tests/test_auth.py

Unit tests for api/auth.py — JWT creation, decoding, and password utilities.
Uses no database or external services.
"""

from __future__ import annotations

import pytest
from jose import JWTError

from api.auth import (
    create_access_token,
    create_refresh_token,
    create_token_pair,
    decode_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

# ══════════════════════════════════════════════════════════════════════════════
# Password utilities
# ══════════════════════════════════════════════════════════════════════════════


class TestPasswordHashing:
    def test_hash_is_different_from_plain(self):
        plain = "MySecureP@ss1"
        assert hash_password(plain) != plain

    def test_verify_correct_password(self):
        plain = "MySecureP@ss1"
        assert verify_password(plain, hash_password(plain)) is True

    def test_verify_wrong_password(self):
        assert verify_password("wrong", hash_password("correct")) is False

    def test_hash_calls_are_not_deterministic(self):
        # bcrypt uses a random salt — two hashes of the same input must differ
        h1 = hash_password("pass")
        h2 = hash_password("pass")
        assert h1 != h2

    def test_verify_still_works_after_re_hash(self):
        plain = "password"
        h = hash_password(plain)
        assert verify_password(plain, h)
        # Second independent hash must also verify correctly
        h2 = hash_password(plain)
        assert verify_password(plain, h2)


# ══════════════════════════════════════════════════════════════════════════════
# Access token creation
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateAccessToken:
    def test_returns_non_empty_string(self):
        tok = create_access_token("user-123", "public")
        assert isinstance(tok, str) and len(tok) > 0

    def test_decode_gives_correct_subject(self):
        tok = create_access_token("user-abc", "public")
        payload = decode_token(tok)
        assert payload.sub == "user-abc"

    def test_decode_gives_correct_role(self):
        tok = create_access_token("user-abc", "admin")
        payload = decode_token(tok)
        assert payload.role == "admin"

    def test_type_is_access(self):
        tok = create_access_token("uid", "public")
        payload = decode_token(tok, expected_type="access")
        assert payload.type == "access"

    def test_jti_is_unique_per_call(self):
        t1 = decode_token(create_access_token("uid", "public"))
        t2 = decode_token(create_access_token("uid", "public"))
        assert t1.jti != t2.jti

    def test_different_users_have_different_tokens(self):
        t1 = create_access_token("user-a", "public")
        t2 = create_access_token("user-b", "public")
        assert t1 != t2


# ══════════════════════════════════════════════════════════════════════════════
# Refresh token creation
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateRefreshToken:
    def test_type_is_refresh(self):
        tok = create_refresh_token("uid", "public")
        payload = decode_token(tok, expected_type="refresh")
        assert payload.type == "refresh"

    def test_subject_is_preserved(self):
        tok = create_refresh_token("user-xyz", "court_official")
        payload = decode_refresh_token(tok)
        assert payload.sub == "user-xyz"
        assert payload.role == "court_official"


# ══════════════════════════════════════════════════════════════════════════════
# Token pair creation
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateTokenPair:
    def test_returns_two_distinct_tokens(self):
        access, refresh = create_token_pair("uid", "public")
        assert access != refresh

    def test_access_token_type(self):
        access, _ = create_token_pair("uid", "public")
        assert decode_token(access, expected_type="access").type == "access"

    def test_refresh_token_type(self):
        _, refresh = create_token_pair("uid", "public")
        assert decode_token(refresh, expected_type="refresh").type == "refresh"


# ══════════════════════════════════════════════════════════════════════════════
# Token decoding / validation
# ══════════════════════════════════════════════════════════════════════════════


class TestDecodeToken:
    def test_raises_on_garbage_token(self):
        with pytest.raises(JWTError):
            decode_token("not.a.token")

    def test_raises_when_using_refresh_as_access(self):
        refresh = create_refresh_token("uid", "public")
        with pytest.raises(JWTError, match="Expected token type"):
            decode_token(refresh, expected_type="access")

    def test_raises_when_using_access_as_refresh(self):
        access = create_access_token("uid", "public")
        with pytest.raises(JWTError, match="Expected token type"):
            decode_token(access, expected_type="refresh")

    def test_raises_on_tampered_token(self):
        tok = create_access_token("uid", "public")
        tampered = tok[:-5] + "XXXXX"
        with pytest.raises(JWTError):
            decode_token(tampered)

    def test_raises_on_wrong_secret(self, monkeypatch):
        """Ensure tokens signed with a different secret are rejected."""
        tok = create_access_token("uid", "public")
        from courtaccess.core.config import settings

        monkeypatch.setattr(settings, "secret_key", "totally-wrong-key")
        with pytest.raises(JWTError):
            decode_token(tok)

    def test_payload_has_all_expected_fields(self):
        tok = create_access_token("user-99", "interpreter")
        p = decode_token(tok)
        assert p.sub == "user-99"
        assert p.role == "interpreter"
        assert p.type == "access"
        assert p.jti is not None
        assert p.exp is not None
