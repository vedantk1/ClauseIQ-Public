"""Focused tests for fresh-account email verification and BYOK onboarding."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import services.auth_service as auth_service_module
from config.environments import Environment, EnvironmentConfig
from services.auth_service import AuthService


class FakeDocumentService:
    def __init__(self, user=None):
        self.user = user
        self.created_users = []

    async def get_user_by_email(self, _email):
        return self.user

    async def get_user_by_id(self, _user_id):
        return self.user

    async def create_user(self, user_data):
        self.created_users.append(dict(user_data))
        return user_data["id"]


def make_auth_service(document_service):
    service = AuthService.__new__(AuthService)
    service.document_service = document_service
    return service


def verification_settings(required):
    return SimpleNamespace(
        email=SimpleNamespace(verification_required=required),
    )


@pytest.fixture(autouse=True)
def deterministic_auth_primitives(monkeypatch):
    monkeypatch.setattr(
        auth_service_module,
        "get_password_hash",
        lambda _password: "hashed-password",
    )
    monkeypatch.setattr(
        auth_service_module,
        "create_access_token",
        lambda data: f"access-{data['sub']}",
    )
    monkeypatch.setattr(
        auth_service_module,
        "create_refresh_token",
        lambda data: f"refresh-{data['sub']}",
    )
    monkeypatch.setattr(
        auth_service_module,
        "create_email_verification_token",
        lambda email: f"verify-{email}",
    )


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        (Environment.DEVELOPMENT, False),
        (Environment.TESTING, False),
        (Environment.STAGING, True),
        (Environment.PRODUCTION, True),
    ],
)
def test_email_verification_defaults_by_environment(environment, expected):
    config = EnvironmentConfig(
        _env_file=None,
        environment=environment,
        email_verification_required=None,
    )

    assert config.email.verification_required is expected


def test_hosted_email_verification_cannot_be_disabled():
    for environment in (Environment.STAGING, Environment.PRODUCTION):
        config = EnvironmentConfig(
            _env_file=None,
            environment=environment,
            email_verification_required=False,
        )

        assert config.email.verification_required is True


def test_development_email_verification_can_be_enabled():
    config = EnvironmentConfig(
        _env_file=None,
        environment=Environment.DEVELOPMENT,
        email_verification_required=True,
    )

    assert config.email.verification_required is True


@pytest.mark.asyncio
async def test_local_registration_skips_email_and_returns_verified_public_user(
    monkeypatch,
):
    document_service = FakeDocumentService()
    service = make_auth_service(document_service)
    send_verification_email = AsyncMock(return_value=True)
    monkeypatch.setattr(
        auth_service_module,
        "get_environment_config",
        lambda: verification_settings(False),
    )
    monkeypatch.setattr(
        auth_service_module,
        "send_verification_email",
        send_verification_email,
    )

    success, token, error = await service.register_user(
        full_name="Local User",
        email="local@example.com",
        password="password",
    )

    assert success is True
    assert error is None
    send_verification_email.assert_not_awaited()
    assert len(document_service.created_users) == 1
    created_user = document_service.created_users[0]
    assert created_user["email_verified"] is True
    assert token.user == {
        "id": created_user["id"],
        "email": "local@example.com",
        "full_name": "Local User",
        "created_at": created_user["created_at"],
        "email_verified": True,
    }


@pytest.mark.asyncio
async def test_required_registration_sends_email_and_returns_unverified_user(
    monkeypatch,
):
    document_service = FakeDocumentService()
    service = make_auth_service(document_service)
    send_verification_email = AsyncMock(return_value=True)
    monkeypatch.setattr(
        auth_service_module,
        "get_environment_config",
        lambda: verification_settings(True),
    )
    monkeypatch.setattr(
        auth_service_module,
        "send_verification_email",
        send_verification_email,
    )

    success, token, error = await service.register_user(
        full_name="Hosted User",
        email="hosted@example.com",
        password="password",
    )

    assert success is True
    assert error is None
    send_verification_email.assert_awaited_once_with(
        "hosted@example.com",
        "Hosted User",
        "verify-hosted@example.com",
    )
    assert document_service.created_users[0]["email_verified"] is False
    assert token.user["email_verified"] is False


@pytest.mark.asyncio
async def test_required_registration_stops_when_email_cannot_be_sent(monkeypatch):
    document_service = FakeDocumentService()
    service = make_auth_service(document_service)
    monkeypatch.setattr(
        auth_service_module,
        "get_environment_config",
        lambda: verification_settings(True),
    )
    monkeypatch.setattr(
        auth_service_module,
        "send_verification_email",
        AsyncMock(return_value=False),
    )

    success, token, error = await service.register_user(
        full_name="Hosted User",
        email="hosted@example.com",
        password="password",
    )

    assert success is False
    assert token is None
    assert "could not be sent" in error
    assert document_service.created_users == []


@pytest.mark.asyncio
async def test_resend_reports_email_delivery_failure(monkeypatch):
    document_service = FakeDocumentService(
        user={
            "id": "user-1",
            "email": "hosted@example.com",
            "full_name": "Hosted User",
            "email_verified": False,
        }
    )
    service = make_auth_service(document_service)
    monkeypatch.setattr(
        auth_service_module,
        "get_environment_config",
        lambda: verification_settings(True),
    )
    monkeypatch.setattr(
        auth_service_module,
        "send_verification_email",
        AsyncMock(return_value=False),
    )

    success, error = await service.resend_verification_email("user-1")

    assert success is False
    assert error == "Verification email could not be sent"


@pytest.mark.asyncio
async def test_login_returns_only_public_user_fields(monkeypatch):
    user = {
        "id": "user-1",
        "email": "person@example.com",
        "full_name": "Person",
        "created_at": "2026-01-01T00:00:00+00:00",
        "email_verified": True,
        "hashed_password": "hashed-password",
        "openai_api_key_encrypted": "must-not-leak",
        "openai_api_key_set": True,
    }
    service = make_auth_service(FakeDocumentService(user=user))
    monkeypatch.setattr(auth_service_module, "verify_password", lambda *_args: True)

    success, token, error = await service.authenticate_user(
        email="person@example.com",
        password="password",
    )

    assert success is True
    assert error is None
    assert token.user == {
        "id": "user-1",
        "email": "person@example.com",
        "full_name": "Person",
        "created_at": "2026-01-01T00:00:00+00:00",
        "email_verified": True,
    }
