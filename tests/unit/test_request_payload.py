"""Request gate payload validation tests."""

from runtime.request_gate import RequestGatePipeline


def test_payload_validation_accepts_mvp_shape() -> None:
    """Request gate accepts message and optional chat_id."""

    result = RequestGatePipeline()._validate_payload(
        {
            "message": "hello",
            "chat_id": "82a5dc36-0c35-4f40-8534-d768f7202f41",
        }
    )

    assert result.passed is True
    assert result.payload.message == "hello"
    assert str(result.payload.chat_id) == "82a5dc36-0c35-4f40-8534-d768f7202f41"


def test_payload_validation_accepts_message_without_chat_id() -> None:
    """Request gate accepts message-only payload for new chat creation."""

    result = RequestGatePipeline()._validate_payload({"message": "hello"})

    assert result.passed is True
    assert result.payload.message == "hello"
    assert result.payload.chat_id is None


def test_payload_validation_rejects_old_or_invalid_shapes() -> None:
    """Request gate rejects missing message and invalid chat IDs."""

    missing = RequestGatePipeline()._validate_payload({"content": "hello", "session_id": "old"})
    invalid_chat = RequestGatePipeline()._validate_payload(
        {"message": "hello", "chat_id": "not-a-uuid"}
    )

    assert missing.passed is False
    assert missing.error_code == "missing_required_field"
    assert invalid_chat.passed is False
    assert invalid_chat.error_code == "invalid_chat_id"
