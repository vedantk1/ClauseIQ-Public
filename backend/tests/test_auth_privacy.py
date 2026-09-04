"""Regression tests for privacy-safe authentication and lifecycle failures."""
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import middleware.security as security_module
import routers.auth as auth_router
import services.auth_service as auth_service_module
from services.auth_service import AuthService


PRIVATE_EMAIL = "private+candidate@example.com"
PRIVATE_ERROR = f"database rejected {PRIVATE_EMAIL}; token=must-not-leak"


class SensitiveFailure(RuntimeError):
    """Exception whose message represents private provider or database detail."""


class RegistrationFailureService:
    async def get_user_by_email(self, _email):
        raise SensitiveFailure(PRIVATE_ERROR)


class MissingUserService:
    async def get_user_by_email(self, _email):
        return None


class PreferenceFailureService:
    async def get_user_preferred_model(self, _user_id):
        raise SensitiveFailure(PRIVATE_ERROR)


def make_auth_service(document_service):
    service = AuthService.__new__(AuthService)
    service.document_service = document_service
    return service


@pytest.mark.asyncio
async def test_registration_failure_is_generic_and_content_safe(caplog):
    service = make_auth_service(RegistrationFailureService())

    with caplog.at_level(logging.ERROR, logger=auth_service_module.logger.name):
        success, token, error = await service.register_user(
            full_name="Private Person",
            email=PRIVATE_EMAIL,
            password="password",
        )

    assert success is False
    assert token is None
    assert error == "Registration failed"
    assert PRIVATE_EMAIL not in caplog.text
    assert PRIVATE_ERROR not in caplog.text
    assert "operation=register" in caplog.text
    assert "stage=service" in caplog.text
    assert "status=error" in caplog.text
    assert "error_type=SensitiveFailure" in caplog.text


@pytest.mark.asyncio
async def test_failed_login_uses_keyed_account_reference_without_logging_email(
    monkeypatch,
    caplog,
):
    service = make_auth_service(MissingUserService())
    recorded_failures = []
    monkeypatch.setattr(
        auth_service_module,
        "get_environment_config",
        lambda: SimpleNamespace(
            security=SimpleNamespace(jwt_secret_key="test-only-key"),
        ),
    )
    monkeypatch.setattr(
        security_module.security_monitor,
        "record_auth_failure",
        lambda ip, account_ref: recorded_failures.append((ip, account_ref)),
    )

    with caplog.at_level(logging.INFO, logger=auth_service_module.logger.name):
        success, token, error = await service.authenticate_user(
            email=PRIVATE_EMAIL,
            password="wrong-password",
            client_ip="127.0.0.1",
        )

    assert success is False
    assert token is None
    assert error == "Invalid email or password"
    assert len(recorded_failures) == 1
    _, account_ref = recorded_failures[0]
    assert account_ref.startswith("account-")
    assert PRIVATE_EMAIL not in account_ref
    assert account_ref == auth_service_module._account_reference(PRIVATE_EMAIL.upper())
    assert PRIVATE_EMAIL not in caplog.text
    assert "status=rejected" in caplog.text


@pytest.mark.asyncio
async def test_auth_route_does_not_return_or_log_exception_details(monkeypatch, caplog):
    monkeypatch.setattr(
        auth_router,
        "get_document_service",
        lambda: PreferenceFailureService(),
    )

    with caplog.at_level(logging.ERROR, logger=auth_router.logger.name):
        response = await auth_router.get_user_preferences(
            current_user={"id": "private-user-id", "email": PRIVATE_EMAIL},
        )

    assert response.success is False
    assert response.error == {
        "code": "PREFERENCES_FETCH_FAILED",
        "message": "Failed to get user preferences",
        "details": None,
    }
    assert PRIVATE_EMAIL not in str(response.model_dump())
    assert PRIVATE_ERROR not in str(response.model_dump())
    assert PRIVATE_EMAIL not in caplog.text
    assert "private-user-id" not in caplog.text
    assert PRIVATE_ERROR not in caplog.text
    assert "operation=get_preferences" in caplog.text
    assert "error_type=SensitiveFailure" in caplog.text


@pytest.mark.parametrize(
    "relative_path",
    [
        "services/auth_service.py",
        "routers/auth.py",
        "main.py",
    ],
)
def test_sensitive_handlers_do_not_serialize_exception_details(relative_path):
    backend_root = Path(__file__).resolve().parents[1]
    source = (backend_root / relative_path).read_text(encoding="utf-8")

    assert "logger.exception(" not in source
    assert "exc_info=True" not in source
    assert "str(e)" not in source
    assert "str(error)" not in source


def test_main_retains_clauseiq_name_and_generic_health_errors():
    backend_root = Path(__file__).resolve().parents[1]
    source = (backend_root / "main.py").read_text(encoding="utf-8")

    assert 'logger.info("Starting ClauseIQ Legal AI Backend...")' in source
    assert '"database": {"status": "error", "error": "Health check failed"}' in source
    assert '"error": "Health check failed"' in source
