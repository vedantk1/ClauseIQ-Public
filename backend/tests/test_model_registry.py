"""Catalog, settings and actual SDK request contracts without network/paid calls."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncOpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_models.models import AIModelConfig, AIModelResponse, DEFAULT_MODEL, DEFAULT_QUERY_GATE_MODEL
from config.environments import AIConfig, EnvironmentConfig
from database.service import DocumentService
from services.ai import generation
from services.ai.generation import AIRequestError, create_chat_completion, generation_metadata
from routers.workspace import SettingsUpdate


@pytest.fixture(autouse=True)
def local_token_estimate(monkeypatch):
    # Tokenizer correctness is exercised separately; SDK contract tests stay offline.
    monkeypatch.setattr(generation, "get_token_count", lambda text, model: len(text))


RETIRED = ["gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]


def test_single_catalog_has_gpt6_defaults_capabilities_and_prices():
    assert DEFAULT_MODEL == DEFAULT_QUERY_GATE_MODEL == AIModelConfig.get_default_model() == "gpt-6-sol"
    assert AIModelConfig.get_model_ids() == [
        "gpt-6-luna", "gpt-6-sol", "gpt-6-astra",
    ]
    assert sum(model.is_default for model in AIModelConfig.get_available_models()) == 1
    for model in AIModelConfig.get_models_for_api():
        assert AIModelResponse(**model).model_dump() == model
        assert "tokenizer_encoding" not in model
        assert model["pricing_verified_on"] == "2026-09-24"
        assert model["max_output_tokens"] == 128_000
        assert model["context_window"] == 1_050_000
        assert not model["legacy"]
    assert [(m.input_price_per_million, m.output_price_per_million)
            for m in AIModelConfig.get_available_models()] == [(0.10, 0.50), (2, 10), (10, 50)]
    assert "none" not in AIModelConfig.get_model_by_id("gpt-6-astra").reasoning_efforts
    assert "none" in AIModelConfig.get_model_by_id("gpt-6-luna").reasoning_efforts


@pytest.mark.parametrize("model", AIModelConfig.get_model_ids())
def test_settings_accept_every_catalog_model(model):
    settings = SettingsUpdate(model_id=model, query_gate_model_id=model)
    assert settings.model_id == model


def test_settings_reject_unregistered_choice():
    with pytest.raises(ValueError):
        SettingsUpdate(model_id="unknown")


@pytest.mark.parametrize("retired", RETIRED)
@pytest.mark.parametrize("field", ["model_id", "query_gate_model_id"])
def test_retired_models_are_not_selectable(retired, field):
    assert retired not in AIModelConfig.get_model_ids()
    with pytest.raises(ValueError):
        AIModelConfig.get_model_by_id(retired)
    with pytest.raises(ValueError):
        SettingsUpdate(**{field: retired})


@pytest.mark.asyncio
@pytest.mark.parametrize("model,effort", [(m.id, e) for m in AIModelConfig.get_available_models() for e in m.reasoning_efforts])
async def test_installed_sdk_serializes_supported_request_without_network(model, effort):
    seen = []

    def respond(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={
            "id": "fixture-completion", "object": "chat.completion", "created": 1,
            "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"result":"fixture"}', "refusal": None,
            }}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        })

    async with AsyncOpenAI(api_key="fixture-not-a-real-key", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))) as client:
        result = await create_chat_completion(client, model=model,
            messages=[{"role": "user", "content": "Return JSON"}],
            max_completion_tokens=4000, reasoning_effort=effort, response_format={"type": "json_object"})
    assert result.choices[0].message.content == '{"result":"fixture"}'
    assert seen == [{"model": model, "messages": [{"role": "user", "content": "Return JSON"}],
                     "max_completion_tokens": 4000, "reasoning_effort": effort,
                     "store": False, "response_format": {"type": "json_object"}}]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected,phrase", [
    (401, 400, "API key"), (403, 400, "unavailable"), (404, 400, "unavailable"),
    (429, 429, "quota"), (400, 400, "request"), (500, 502, "complete"),
])
async def test_provider_errors_are_safe_and_never_switch_models(status, expected, phrase):
    seen = []

    def respond(request):
        seen.append(json.loads(request.content)["model"])
        return httpx.Response(status, json={"error": {"message": "PRIVATE-DOCUMENT-AND-KEY", "type": "fixture_error"}})

    async with AsyncOpenAI(api_key="fixture-not-a-real-key", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))) as client:
        with pytest.raises(AIRequestError) as error:
            await create_chat_completion(client, model=DEFAULT_MODEL,
                messages=[{"role": "user", "content": "Synthetic clause"}], max_completion_tokens=1000)
    assert error.value.status_code == expected
    assert phrase in str(error.value)
    assert "PRIVATE" not in str(error.value)
    assert seen == [DEFAULT_MODEL]


@pytest.mark.asyncio
@pytest.mark.parametrize("finish,content,refusal", [
    ("length", "partial", None), ("content_filter", None, None),
    ("stop", "", None), ("stop", " ", None), ("stop", None, None),
    ("stop", "ignored", "refused"), ("tool_calls", "unexpected", None),
])
async def test_incomplete_output_is_not_accepted(finish, content, refusal):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(
        return_value=SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish,
            message=SimpleNamespace(content=content, refusal=refusal))])))))
    with pytest.raises(AIRequestError):
        await create_chat_completion(client, model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": "fixture"}], max_completion_tokens=1024)
    client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"model": "unknown"}, {"reasoning_effort": "minimal"},
    {"max_completion_tokens": 0}, {"max_completion_tokens": 128001},
    {"temperature": 0.7}, {"model": "gpt-5", "reasoning_effort": "none"},
    {"model": "gpt-5-mini"}, {"model": "gpt-5-nano"},
    {"model": "gpt-6-astra", "reasoning_effort": "none"},
    {"model": "gpt-5.6-terra"},
])
async def test_invalid_request_options_fail_before_spend(overrides):
    client = AsyncMock()
    arguments = dict(model=DEFAULT_MODEL, messages=[{"role": "user", "content": "fixture"}], max_completion_tokens=1024)
    with pytest.raises(AIRequestError):
        await create_chat_completion(client, **(arguments | overrides))
    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_input_cost_cap_checked_before_spend(monkeypatch):
    monkeypatch.setenv("AI_MAX_INPUT_TOKENS", "50")
    client = AsyncMock()
    with pytest.raises(AIRequestError, match="input budget"):
        await create_chat_completion(client, model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": "x" * 60}], max_completion_tokens=1024)
    client.chat.completions.create.assert_not_called()


def test_generation_metadata_matches_explicit_defaults():
    assert generation_metadata(DEFAULT_MODEL, "summary") == {
        "model_id": DEFAULT_MODEL, "endpoint": "chat.completions",
        "reasoning_effort": "medium", "max_completion_tokens": 4000,
        "catalog_verified_on": "2026-09-24",
    }
    assert generation_metadata(DEFAULT_QUERY_GATE_MODEL, "query_gate")["reasoning_effort"] == "low"


def test_generation_metadata_reports_invalid_budget_safely(monkeypatch):
    monkeypatch.setenv("AI_SUMMARY_MAX_COMPLETION_TOKENS", "private-invalid-value")
    with pytest.raises(AIRequestError, match="budget configuration") as error:
        generation_metadata(DEFAULT_MODEL, "summary")
    assert error.value.status_code == 503
    assert "private-invalid-value" not in error.value.public_message


@pytest.mark.asyncio
async def test_model_settings_default_only_when_unset(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_DEFAULT_MODEL", raising=False)
    service = DocumentService()
    monkeypatch.setattr(service, "get_system_config", AsyncMock(return_value=None))
    assert await service.get_system_ai_model() == DEFAULT_MODEL
    assert await service.get_query_gate_model() == DEFAULT_QUERY_GATE_MODEL
    for existing in ("gpt-6-luna", "gpt-6-sol", "gpt-6-astra", "unsupported-historical-model"):
        service.get_system_config.return_value = {"model_id": existing}
        assert await service.get_system_ai_model() == existing
        assert await service.get_query_gate_model() == existing
    service.get_system_config.assert_awaited_with("query_gate_model", raise_on_error=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("retired", RETIRED)
async def test_retired_saved_selections_resolve_without_rewriting_storage(monkeypatch, retired):
    service = DocumentService()
    original = {"model_id": retired, "configured_at": "historical"}
    monkeypatch.setattr(service, "get_system_config", AsyncMock(return_value=original))
    monkeypatch.setattr(service, "set_system_config", AsyncMock())
    assert await service.get_system_ai_model() == "gpt-6-sol"
    assert await service.get_query_gate_model() == "gpt-6-sol"
    assert await service.get_workspace_generation_settings("local") == {"model_id": "gpt-6-sol", "reasoning_effort": "medium"}
    assert await service.get_system_ai_model_config() == original
    assert await service.get_query_gate_model_config() == original
    assert original == {"model_id": retired, "configured_at": "historical"}
    service.set_system_config.assert_not_awaited()


@pytest.mark.parametrize("configured,expected", [
    *((retired, "gpt-6-sol") for retired in RETIRED),
    ("gpt-6-luna", "gpt-6-luna"), ("gpt-6-astra", "gpt-6-astra"),
    ("unknown-historical-model", "unknown-historical-model"),
])
@pytest.mark.asyncio
async def test_environment_choices_resolve_only_explicitly_retired_models(monkeypatch, tmp_path, configured, expected):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_DEFAULT_MODEL", configured)
    environment = EnvironmentConfig(_env_file=None)
    assert environment.openai_default_model == expected
    assert environment.ai.default_model == expected
    direct = AIConfig(default_model=configured, gate_model=configured, rewrite_model=configured)
    assert (direct.default_model, direct.gate_model, direct.rewrite_model) == (expected, expected, expected)
    service = DocumentService()
    monkeypatch.setattr(service, "get_system_config", AsyncMock(return_value=None))
    assert await service.get_system_ai_model() == expected
    if configured == "unknown-historical-model":
        client = AsyncMock()
        with pytest.raises(AIRequestError, match="not supported"):
            await create_chat_completion(client, model=expected,
                messages=[{"role": "user", "content": "Synthetic text"}], max_completion_tokens=1000)
        client.chat.completions.create.assert_not_called()


@pytest.mark.parametrize("retired", RETIRED)
def test_historical_review_attribution_does_not_resolve_retired_ids(retired):
    from clauseiq_types.review import ReviewGeneration

    historical = ReviewGeneration(model_id=retired, reasoning_effort="medium", max_completion_tokens=4000,
        catalog_verified_on="historical", prompt_version="historical-v1", schema_version="historical-v1",
        extraction_version="historical-v1", estimated_input_tokens=100)
    assert ReviewGeneration.model_validate(historical.model_dump()).model_id == retired


@pytest.mark.asyncio
async def test_database_failure_never_selects_a_default(monkeypatch):
    service = DocumentService()
    monkeypatch.setattr(service, "_get_db", AsyncMock(side_effect=RuntimeError("private database details")))
    for read_model in (service.get_system_ai_model, service.get_query_gate_model):
        with pytest.raises(AIRequestError, match="model settings") as error:
            await read_model()
        assert error.value.status_code == 503
        assert "private database" not in str(error.value)
