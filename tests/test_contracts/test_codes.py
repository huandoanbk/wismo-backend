"""Contract tests for foundation error/control code constants and payload shape.

Locks enum values, shared code values, and keyword-only error payload shape so
future sprints cannot silently drift the foundation contract.
"""

from wismo.contracts import codes
from wismo.contracts.enums import (
    CONTROL_RESPONSE_METHODS,
    CONVERSATIONAL_RESPONSE_METHODS,
    ResponseMethod,
)
from wismo.contracts.error import WismoError, keyword_error_payload

# ---------------------------------------------------------------------------
# Identity / Session codes
# ---------------------------------------------------------------------------


def test_identity_session_codes_are_canonical() -> None:
    """Identity and session error codes match the foundation contract."""

    assert codes.IDENTITY_NOT_RESOLVED == "identity_not_resolved"
    assert codes.GUEST_IDENTITY_NOT_RESOLVED == "guest_identity_not_resolved"
    assert codes.GUEST_SESSION_EXPIRED == "guest_session_expired"
    assert codes.SESSION_EXPIRED == "session_expired"
    assert codes.SESSION_REQUIRED == "session_required"


# ---------------------------------------------------------------------------
# Consent / Chat / Quota codes
# ---------------------------------------------------------------------------


def test_consent_and_chat_codes_are_canonical() -> None:
    """Consent, chat access, and quota codes match the foundation contract."""

    assert codes.CONSENT_REQUIRED == "consent_required"
    assert codes.CHAT_NOT_FOUND == "chat_not_found"
    assert codes.CHAT_ACCESS_DENIED == "chat_access_denied"
    assert codes.GUEST_CHAT_NOT_FOUND == "guest_chat_not_found"
    assert codes.QUOTA_EXCEEDED == "quota_exceeded"
    assert codes.REGISTRATION_REQUIRED_BY_QUOTA == "registration_required_by_quota"


# ---------------------------------------------------------------------------
# Request validation codes
# ---------------------------------------------------------------------------


def test_request_validation_codes_are_canonical() -> None:
    """Request validation error codes match the foundation contract."""

    assert codes.INVALID_REQUEST == "invalid_request"
    assert codes.INVALID_CHAT_ID == "invalid_chat_id"
    assert codes.MISSING_REQUIRED_FIELD == "missing_required_field"
    assert codes.EMPTY_MESSAGE == "empty_message"
    assert codes.MESSAGE_TOO_LONG == "message_too_long"
    assert codes.PAYLOAD_TOO_LARGE == "payload_too_large"


# ---------------------------------------------------------------------------
# Idempotency / concurrency codes
# ---------------------------------------------------------------------------


def test_concurrency_codes_are_canonical() -> None:
    """Concurrency gate code matches the foundation contract."""

    assert codes.TURN_IN_PROGRESS == "turn_in_progress"


# ---------------------------------------------------------------------------
# Keyword-only error payload shape
# ---------------------------------------------------------------------------


def test_wismo_error_as_dict_is_keyword_only() -> None:
    """WismoError.as_dict() enforces keyword-only envelope shape."""

    err = WismoError(code="invalid_request")
    payload = err.as_dict()

    assert payload == {"error": "invalid_request"}
    assert "message" not in payload


def test_keyword_error_payload_helper_returns_keyword_only() -> None:
    """keyword_error_payload always returns the keyword-only envelope."""

    payload = keyword_error_payload("invalid_request")

    assert payload == {"error": "invalid_request"}
    assert len(payload) == 1


# ---------------------------------------------------------------------------
# Enum grouping sets
# ---------------------------------------------------------------------------


def test_conversational_response_methods_grouping() -> None:
    """CONVERSATIONAL_RESPONSE_METHODS covers exactly the counseling path methods."""

    assert CONVERSATIONAL_RESPONSE_METHODS == {
        ResponseMethod.LISTEN,
        ResponseMethod.ASK,
        ResponseMethod.REFLECT,
        ResponseMethod.TEACH,
        ResponseMethod.FOLLOWUP,
    }


def test_control_response_methods_grouping() -> None:
    """CONTROL_RESPONSE_METHODS covers exactly the terminal/control path methods."""

    assert CONTROL_RESPONSE_METHODS == {
        ResponseMethod.REDIRECT,
        ResponseMethod.CRISIS_SAFE_ONLY,
        ResponseMethod.BLOCKED_MINOR,
        ResponseMethod.REFUSAL,
        ResponseMethod.SPAM_REPLY,
    }


def test_conversational_and_control_methods_are_disjoint_and_complete() -> None:
    """Conversational and control groupings partition all ResponseMethod values."""

    all_methods = set(ResponseMethod)
    assert CONVERSATIONAL_RESPONSE_METHODS | CONTROL_RESPONSE_METHODS == all_methods
    assert CONVERSATIONAL_RESPONSE_METHODS & CONTROL_RESPONSE_METHODS == set()
