"""One request contract for supported generation models, without model fallback."""
from typing import Any

from openai import (
    APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError,
    BadRequestError, NotFoundError, PermissionDeniedError, RateLimitError,
)

from ai_models.models import AIModelConfig, CATALOG_VERIFIED_ON
from .token_utils import calculate_token_budget, get_optimal_response_tokens, get_token_count


class AIRequestError(RuntimeError):
    """A safe public message, never a raw provider response or request body."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.public_message = message
        self.status_code = status_code


def _model(model_id: str):
    try:
        return AIModelConfig.get_model_by_id(model_id)
    except ValueError:
        raise AIRequestError("The selected model is not supported. Choose an available model in Settings.", 400) from None


def generation_metadata(model: str, operation: str, reasoning_effort: str | None = None) -> dict[str, Any]:
    spec = _model(model)
    effort = reasoning_effort or ("low" if operation in ("query_gate", "query_rewrite") else spec.default_reasoning_effort)
    if effort not in spec.reasoning_efforts:
        raise AIRequestError("Unsupported reasoning setting for the selected model. Update Settings.", 400)
    try:
        completion_budget = get_optimal_response_tokens(operation, model)
    except ValueError:
        raise AIRequestError("Invalid AI token budget configuration. Check the local AI budget settings.", 503) from None
    return {
        "model_id": model,
        "endpoint": "chat.completions",
        "reasoning_effort": effort,
        "max_completion_tokens": completion_budget,
        "catalog_verified_on": CATALOG_VERIFIED_ON,
    }


async def create_chat_completion(
    client, *, model: str, messages: list[dict[str, str]],
    max_completion_tokens: int, reasoning_effort: str | None = None,
    validate_output: bool = True, **kwargs,
):
    """Validate settings/output and classify errors; make one explicit model call.

    Chat Completions is retained for M2. No implicit temperature, endpoint
    migration, larger-budget retry, or more expensive fallback is introduced.
    """
    spec = _model(model)
    effort = reasoning_effort or spec.default_reasoning_effort
    if effort not in spec.reasoning_efforts:
        raise AIRequestError("Unsupported reasoning setting for the selected model.", 400)
    if (type(max_completion_tokens) is not int or
            not 0 < max_completion_tokens <= spec.max_output_tokens):
        raise AIRequestError("The completion budget is outside the selected model's limits.", 400)
    if set(kwargs) - {"response_format"}:
        raise AIRequestError("Unsupported generation request option.", 400)
    if client is None:
        raise AIRequestError("Add your OpenAI API key in Settings to use AI features.", 400)
    # Local token estimates are a conservative guard, not provider usage billing.
    try:
        estimated_input = sum(get_token_count(item.get("content", ""), model) + 8 for item in messages) + 16
        input_budget = calculate_token_budget(model, max_completion_tokens)
    except ValueError:
        raise AIRequestError("Invalid AI token budget configuration. Check the local AI budget settings.", 503) from None
    if estimated_input > input_budget:
        raise AIRequestError("This request exceeds the configured AI input budget. Use a smaller document or adjust the local token budget deliberately.", 400)
    try:
        response = await client.chat.completions.create(
            model=model, messages=messages, max_completion_tokens=max_completion_tokens,
            reasoning_effort=effort, store=False, **kwargs,
        )
    except AuthenticationError:
        raise AIRequestError("OpenAI rejected the API key. Update your key in Settings.", 400) from None
    except (NotFoundError, PermissionDeniedError):
        raise AIRequestError("The selected model is unavailable to this API key. Check OpenAI model access or choose another model in Settings; no fallback was used.", 400) from None
    except RateLimitError:
        raise AIRequestError("OpenAI's rate or spending limit was reached. Check your API quota and billing before retrying.", 429) from None
    except BadRequestError:
        raise AIRequestError("OpenAI could not accept this model request. Check model access and the configured token budget; no fallback was used.", 400) from None
    except (APITimeoutError, APIConnectionError):
        raise AIRequestError("OpenAI could not be reached. Check your connection and retry when ready.", 503) from None
    except APIStatusError:
        raise AIRequestError("OpenAI could not complete this request. Retry when ready; no model fallback was used.", 502) from None
    # The review engine validates every output itself so it can retain usage for
    # refusals and unfinished responses. Existing callers keep the strict gate.
    if not validate_output:
        return response
    choices = getattr(response, "choices", None)
    if not choices:
        raise AIRequestError("The selected model returned no answer. No result was saved.")
    choice = choices[0]
    message = choice.message
    if getattr(message, "refusal", None) or choice.finish_reason == "content_filter":
        raise AIRequestError("The model declined this request. No generated result was saved.")
    if choice.finish_reason == "length":
        raise AIRequestError("The model reached the completion budget before finishing. No incomplete result was saved. Review the token budget before retrying.")
    if choice.finish_reason != "stop" or not isinstance(message.content, str) or not message.content.strip():
        raise AIRequestError("The selected model returned an incomplete or empty answer. No generated result was saved.")
    return response
