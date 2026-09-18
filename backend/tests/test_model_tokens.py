"""Model capacities, cost budgets, and deterministic offline tokenizer tests."""

from dataclasses import replace

import pytest
import tiktoken

from ai_models.models import AIModelConfig
from services.ai import token_utils


MODEL_IDS = (
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
    "gpt-5",
)


class ByteEncoding:
    """Exercise truncation and UTF-8 cuts without downloading a vocabulary."""

    def encode(self, text, *, disallowed_special=()):
        assert disallowed_special == ()
        return list(text.encode("utf-8"))

    def decode(self, tokens, *, errors="replace"):
        return bytes(tokens).decode("utf-8", errors=errors)


@pytest.fixture(autouse=True)
def isolated_budgets(monkeypatch, tmp_path):
    # Match backend startup's cwd-relative .env without reading developer state.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AI_MAX_INPUT_TOKENS", raising=False)
    for operation in token_utils.TASK_COMPLETION_BUDGETS:
        monkeypatch.delenv(f"AI_{operation.upper()}_MAX_COMPLETION_TOKENS", raising=False)


@pytest.fixture
def offline_encoding(monkeypatch):
    names = []

    def load(name):
        names.append(name)
        return ByteEncoding()

    monkeypatch.setattr(tiktoken, "get_encoding", load)
    return names


@pytest.mark.parametrize("model", MODEL_IDS)
def test_native_tokenizer_mapping_uses_o200k(model, offline_encoding):
    assert tiktoken.model.encoding_name_for_model(model) == "o200k_base"
    assert token_utils.get_token_count("Contract", model) == 8
    assert offline_encoding == ["o200k_base"]


def test_registered_tokenizer_fallback_is_explicit(monkeypatch, offline_encoding):
    def missing_mapping(_model):
        raise KeyError("new model")

    monkeypatch.setattr(tiktoken.model, "encoding_name_for_model", missing_mapping)
    assert token_utils.get_token_count("test", "gpt-5.6-luna") == 4
    assert offline_encoding == ["o200k_base"]


def test_native_mapping_takes_precedence(monkeypatch, offline_encoding):
    monkeypatch.setattr(tiktoken.model, "encoding_name_for_model", lambda _model: "native")
    token_utils.get_token_count("test", "gpt-5.6-luna")
    assert offline_encoding == ["native"]


@pytest.mark.parametrize("function,args", [
    (token_utils.get_token_count, ("text",)),
    (token_utils.truncate_text_by_tokens, ("text", 0)),
    (token_utils.calculate_token_budget, ()),
    (token_utils.get_optimal_response_tokens, ("summary",)),
    (token_utils.get_model_capabilities, ()),
])
@pytest.mark.parametrize("model", ["unknown-model", "gpt-5-mini", "gpt-5-nano"])
def test_unavailable_models_never_inherit_fallback_limits(function, args, model):
    with pytest.raises(ValueError):
        function(*args, model=model)


@pytest.mark.parametrize("model", MODEL_IDS)
@pytest.mark.parametrize("operation,expected", list(token_utils.TASK_COMPLETION_BUDGETS.items()))
def test_completion_budgets_do_not_scale_with_context(model, operation, expected):
    assert token_utils.get_optimal_response_tokens(operation, model) == expected


def test_unknown_operation_does_not_silently_choose_a_budget():
    with pytest.raises(ValueError, match="Unknown AI task budget"):
        token_utils.get_optimal_response_tokens("typo", "gpt-5.6-luna")


def test_completion_override_and_model_cap(monkeypatch):
    monkeypatch.setenv("AI_SUMMARY_MAX_COMPLETION_TOKENS", "777")
    assert token_utils.get_optimal_response_tokens("summary", "gpt-5.6-luna") == 777
    monkeypatch.setenv("AI_SUMMARY_MAX_COMPLETION_TOKENS", "999999")
    assert token_utils.get_optimal_response_tokens("summary", "gpt-5.6-luna") == 128_000


def test_dotenv_budget_overrides_are_used(tmp_path):
    (tmp_path / ".env").write_text(
        "AI_MAX_INPUT_TOKENS=12000\nAI_SUMMARY_MAX_COMPLETION_TOKENS=777\n",
        encoding="utf-8",
    )
    assert token_utils.calculate_token_budget("gpt-5.6-luna") == 12_000
    assert token_utils.get_optimal_response_tokens("summary", "gpt-5.6-luna") == 777


def test_process_environment_takes_precedence_over_dotenv(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "AI_MAX_INPUT_TOKENS=12000\nAI_SUMMARY_MAX_COMPLETION_TOKENS=777\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_MAX_INPUT_TOKENS", "24000")
    monkeypatch.setenv("AI_SUMMARY_MAX_COMPLETION_TOKENS", "888")
    assert token_utils.calculate_token_budget("gpt-5.6-luna") == 24_000
    assert token_utils.get_optimal_response_tokens("summary", "gpt-5.6-luna") == 888


def test_invalid_dotenv_budget_is_not_silently_ignored(tmp_path):
    (tmp_path / ".env").write_text("AI_MAX_INPUT_TOKENS=invalid\n", encoding="utf-8")
    with pytest.raises(ValueError, match="AI_MAX_INPUT_TOKENS"):
        token_utils.calculate_token_budget("gpt-5.6-luna")


@pytest.mark.parametrize("raw", ["", "0", "-1", "not-a-number", "1.5"])
@pytest.mark.parametrize("variable", ["AI_MAX_INPUT_TOKENS", "AI_SUMMARY_MAX_COMPLETION_TOKENS"])
def test_invalid_budget_overrides_fail_visibly(monkeypatch, raw, variable):
    monkeypatch.setenv(variable, raw)
    with pytest.raises(ValueError, match=variable):
        if variable == "AI_MAX_INPUT_TOKENS":
            token_utils.calculate_token_budget("gpt-5.6-luna")
        else:
            token_utils.get_optimal_response_tokens("summary", "gpt-5.6-luna")


@pytest.mark.parametrize("model", MODEL_IDS)
def test_default_input_budget_is_cost_capped(model):
    assert token_utils.calculate_token_budget(model, response_tokens=16_000) == 100_000


def test_input_override_is_clamped_to_context_after_output_and_safety(monkeypatch):
    monkeypatch.setenv("AI_MAX_INPUT_TOKENS", "9999999")
    assert token_utils.calculate_token_budget("gpt-5.6-sol", 16_000, 2048) == 1_031_952
    assert token_utils.calculate_token_budget("gpt-5", 16_000, 2048) == 381_952
    monkeypatch.setenv("AI_MAX_INPUT_TOKENS", "12000")
    assert token_utils.calculate_token_budget("gpt-5.6-sol", 16_000, 2048) == 12_000


def test_exhausted_context_does_not_fabricate_input_allowance(monkeypatch):
    model = replace(AIModelConfig.get_model_by_id("gpt-5.6-luna"), context_window=100)
    monkeypatch.setattr(AIModelConfig, "get_model_by_id", lambda _model: model)
    assert token_utils.calculate_token_budget("gpt-5.6-luna", 100, 1) == 0


@pytest.mark.parametrize("arguments", [{"response_tokens": -1}, {"safety_margin": -1}])
def test_negative_reservations_are_invalid(arguments):
    with pytest.raises(ValueError):
        token_utils.calculate_token_budget("gpt-5.6-luna", **arguments)


@pytest.mark.parametrize("limit", [-10, -1, 0])
@pytest.mark.parametrize("preserve_sentences", [True, False])
def test_nonpositive_truncation_budgets_are_empty(limit, preserve_sentences):
    assert token_utils.truncate_text_by_tokens(
        "Contract text", limit, "gpt-5.6-luna", preserve_sentences,
    ) == ""


@pytest.mark.parametrize("text", [
    "First clause. Second clause is longer! Third clause?",
    "हस्ताक्षर 😀 café 合同",
    "<|endoftext|> is literal document content",
])
@pytest.mark.parametrize("limit", [1, 2, 5, 15, 30, 1000])
@pytest.mark.parametrize("preserve_sentences", [True, False])
def test_truncation_is_a_valid_prefix_within_budget(text, limit, preserve_sentences, offline_encoding):
    truncated = token_utils.truncate_text_by_tokens(
        text, limit, "gpt-5.6-luna", preserve_sentences,
    )
    assert text.startswith(truncated)
    assert "\ufffd" not in truncated
    assert token_utils.get_token_count(truncated, "gpt-5.6-luna") <= limit
    if token_utils.get_token_count(text, "gpt-5.6-luna") <= limit:
        assert truncated == text


def test_sentence_preservation_never_adds_punctuation(offline_encoding):
    text = "First clause. Second clause is longer."
    assert token_utils.truncate_text_by_tokens(text, 20, "gpt-5.6-luna") == "First clause."
    assert token_utils.truncate_text_by_tokens("No full sentence yet", 10, "gpt-5.6-luna") == "No full se"


def test_capabilities_report_real_capacity_not_page_promises():
    capabilities = token_utils.get_model_capabilities("gpt-5.6-luna")
    assert capabilities["total_context"] == 1_050_000
    assert capabilities["max_output_tokens"] == 128_000
    assert capabilities["tokenizer_encoding"] == "o200k_base"
    assert capabilities["token_counts_are_estimates"] is True
    assert "competitive_advantage" not in capabilities
    for task in capabilities["capabilities"].values():
        assert "estimated_pages" not in task
        assert task["input_tokens"] <= 100_000
