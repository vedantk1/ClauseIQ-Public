"""Regression tests for ClauseIQ's PyJWT token helpers."""

from auth import (
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    create_refresh_token,
    verify_email_verification_token,
    verify_password_reset_token,
    verify_refresh_token,
    verify_token,
)


def test_access_and_refresh_tokens_keep_their_types_separate():
    access_token = create_access_token({"sub": "user-123"})
    refresh_token = create_refresh_token({"sub": "user-123"})

    assert verify_token(access_token)["sub"] == "user-123"
    assert verify_refresh_token(refresh_token)["sub"] == "user-123"
    assert verify_token(refresh_token) is None
    assert verify_refresh_token(access_token) is None


def test_single_purpose_tokens_round_trip_with_pyjwt():
    email = "developer@example.com"

    reset_payload = verify_password_reset_token(create_password_reset_token(email))
    assert reset_payload is not None
    assert reset_payload["email"] == email
    assert reset_payload["jti"]

    verification_token = create_email_verification_token(email)
    assert verify_email_verification_token(verification_token) == email


def test_invalid_jwt_is_rejected():
    assert verify_token("not-a-valid-token") is None
    assert verify_password_reset_token("not-a-valid-token") is None
    assert verify_email_verification_token("not-a-valid-token") is None
