"""Shared error handling for every Gemini-backed endpoint.

Gemini failures (quota exhaustion, transient outages, misconfiguration)
should never surface as a bare, unhandled HTTP 500 — this module is the one
place that classifies those failures into an appropriate HTTP status and a
message that's safe to show a user directly, so every AI-powered route
degrades the same way instead of each route re-implementing (or forgetting)
this handling.

Call `call_gemini(llm, payload)` instead of `llm.invoke(payload)` directly.
"""

from fastapi import HTTPException
from google.genai.errors import APIError
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

NOT_CONFIGURED_MESSAGE = "AI features are not configured. Set GOOGLE_API_KEY on the server."
QUOTA_MESSAGE = "AI features are temporarily unavailable — the usage limit has been reached. Please try again in a few minutes."
UNAVAILABLE_MESSAGE = "AI features are temporarily unavailable right now. Please try again shortly."
GENERIC_MESSAGE = "The AI request failed. Please try again."

# Upstream Google status codes/strings that mean "rate limited" or
# "temporarily down" respectively — everything else falls back to a generic
# 502, since it's most likely a server-side misconfiguration the user can't
# retry their way out of.
_QUOTA_CODES = {429}
_QUOTA_STATUSES = {"RESOURCE_EXHAUSTED"}
_UNAVAILABLE_CODES = {500, 503, 504}
_UNAVAILABLE_STATUSES = {"UNAVAILABLE", "DEADLINE_EXCEEDED", "INTERNAL"}


def call_gemini(llm, payload):
    """Invokes a Gemini chat model and normalizes every failure into an
    HTTPException with an appropriate status code and a user-safe message.
    Returns the model's response unchanged on success.
    """

    if llm is None:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED_MESSAGE)

    try:
        return llm.invoke(payload)
    except APIError as exc:
        raise HTTPException(status_code=_status_for(exc.code, exc.status), detail=_message_for(exc.code, exc.status)) from exc
    except ChatGoogleGenerativeAIError as exc:
        # LangChain's wrapper around google-genai; the structured APIError is
        # usually its __cause__, but fall back to sniffing the message text
        # in case a future version doesn't chain it.
        cause = exc.__cause__
        if isinstance(cause, APIError):
            raise HTTPException(status_code=_status_for(cause.code, cause.status), detail=_message_for(cause.code, cause.status)) from exc
        text = str(exc).upper()
        code = 429 if "RESOURCE_EXHAUSTED" in text or "429" in text else None
        status = "RESOURCE_EXHAUSTED" if code == 429 else None
        raise HTTPException(status_code=_status_for(code, status), detail=_message_for(code, status)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=GENERIC_MESSAGE) from exc


def _status_for(code, status) -> int:
    if code in _QUOTA_CODES or status in _QUOTA_STATUSES:
        return 429
    if code in _UNAVAILABLE_CODES or status in _UNAVAILABLE_STATUSES:
        return 503
    return 502


def _message_for(code, status) -> str:
    if code in _QUOTA_CODES or status in _QUOTA_STATUSES:
        return QUOTA_MESSAGE
    if code in _UNAVAILABLE_CODES or status in _UNAVAILABLE_STATUSES:
        return UNAVAILABLE_MESSAGE
    return GENERIC_MESSAGE
