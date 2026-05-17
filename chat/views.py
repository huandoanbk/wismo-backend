"""Chat bootstrap and runtime API views for the MVP foundation."""

from __future__ import annotations

import uuid
from typing import Any

from django.http import StreamingHttpResponse
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.services import GUEST_COOKIE_NAME
from chat.services import ChatBootstrapError, ChatContextService
from runtime.orchestrator import RuntimeOrchestrator
from runtime.request_gate import RequestGatePipeline
from wismo.contracts.codes import INVALID_REQUEST
from wismo.contracts.error import keyword_error_payload


def error_payload(error: ChatBootstrapError) -> dict[str, str]:
    """Serialize chat service errors using the canonical error envelope."""

    return keyword_error_payload(error.code)


def optional_string(data: Any, field_name: str) -> str:
    """Read an optional string field from request data."""

    if not hasattr(data, "get"):
        raise ChatBootstrapError(INVALID_REQUEST, 400)
    if field_name not in data:
        return ""
    value = data.get(field_name)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ChatBootstrapError(INVALID_REQUEST, 400)
    return value


def parse_chat_id(raw_chat_id: str) -> uuid.UUID:
    """Parse a chat_id path parameter into UUID form."""

    try:
        return uuid.UUID(str(raw_chat_id))
    except ValueError as exc:
        raise ChatBootstrapError(INVALID_REQUEST, 400) from exc


class ChatSendView(APIView):
    """Accept one MVP chat turn and return an SSE stream."""

    permission_classes = [AllowAny]

    def post(self, request: Any):
        """Run gate sync then open SSE stream for a chat turn."""

        gate = RequestGatePipeline()
        gate_result = gate.run(request=request, data=request.data)

        if not gate_result.passed:
            # Gate fail — return JSON error before stream opens
            response = Response(
                {"error": gate_result.error_code or INVALID_REQUEST},
                status=gate_result.status_code,
            )
            if gate_result.clear_guest_cookie:
                response.delete_cookie(GUEST_COOKIE_NAME, samesite="Lax")
            return response

        streaming_response = StreamingHttpResponse(
            RuntimeOrchestrator().stream(gate_result),
            content_type="text/event-stream",
        )
        streaming_response["Cache-Control"] = "no-cache"
        streaming_response["X-Accel-Buffering"] = "no"
        if gate_result.clear_guest_cookie:
            streaming_response.delete_cookie(GUEST_COOKIE_NAME, samesite="Lax")
        return streaming_response


class ChatBootstrapView(APIView):
    """Create or list chat shells for the current identity."""

    permission_classes = [AllowAny]

    def get(self, request: Any):
        """Return the owned chat list for the resolved identity."""

        service = ChatContextService()
        try:
            identity = service.resolve_bootstrap_identity(request=request)
        except ChatBootstrapError as exc:
            return Response(error_payload(exc), status=exc.status_code)
        return Response(service.chat_list_payload(identity=identity), status=200)

    def post(self, request: Any):
        """Create a new chat shell for the resolved identity."""

        service = ChatContextService()
        try:
            identity = service.resolve_bootstrap_identity(request=request)
            opening_input_text = optional_string(request.data, "opening_input_text")
            chat = service.create_chat(identity=identity, opening_input_text=opening_input_text)
        except ChatBootstrapError as exc:
            return Response(error_payload(exc), status=exc.status_code)

        return Response({"chat": service.chat_summary_payload(chat)}, status=201)


class ChatDetailView(APIView):
    """Return chat summary and inline turn history for the owned chat."""

    permission_classes = [AllowAny]

    def get(self, request: Any, chat_id: str):
        """Return the canonical chat detail payload."""

        service = ChatContextService()
        try:
            identity = service.resolve_bootstrap_identity(request=request)
            chat = service.get_owned_chat(identity=identity, chat_id=parse_chat_id(chat_id))
        except ChatBootstrapError as exc:
            return Response(error_payload(exc), status=exc.status_code)

        return Response(service.chat_detail_payload(chat), status=200)

    def delete(self, request: Any, chat_id: str):
        """Archive the owned chat — soft delete visible to the current identity."""

        service = ChatContextService()
        try:
            identity = service.resolve_bootstrap_identity(request=request)
            service.archive_chat(identity=identity, chat_id=parse_chat_id(chat_id))
        except ChatBootstrapError as exc:
            return Response(error_payload(exc), status=exc.status_code)

        return Response({"archived": True}, status=200)
