"""Minimal consent API for MVP foundation."""

from __future__ import annotations

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.services import IdentityService
from consents.services import ConsentService
from wismo.contracts.codes import IDENTITY_NOT_RESOLVED
from wismo.contracts.error import keyword_error_payload


class ConsentAcceptView(APIView):
    """Accept consent for the current session user or guest identity."""

    permission_classes = [AllowAny]

    def post(self, request):
        """Create a consent record for a registered user or guest cookie."""

        identity_service = IdentityService()
        if request.user.is_authenticated:
            record = ConsentService().accept(user=request.user, request=request)
            return Response(
                {
                    "consent_id": str(record.id),
                    "identity_type": "user",
                    "consent_state": "accepted",
                },
                status=201,
            )

        guest = identity_service.guest_from_request(request)
        if guest is None or not identity_service.is_guest_valid(guest):
            return Response(keyword_error_payload(IDENTITY_NOT_RESOLVED), status=401)

        record = ConsentService().accept(guest_identity=guest, request=request)
        return Response(
            {
                "consent_id": str(record.id),
                "identity_type": "guest",
                "consent_state": "accepted",
            },
            status=201,
        )


class ConsentWithdrawView(APIView):
    """Withdraw consent for the current session user or guest identity."""

    permission_classes = [AllowAny]

    def post(self, request):
        """Create a revoked consent record for a registered user or guest cookie."""

        identity_service = IdentityService()
        if request.user.is_authenticated:
            record = ConsentService().withdraw(user=request.user, request=request)
            return Response(
                {
                    "consent_id": str(record.id),
                    "identity_type": "user",
                    "consent_state": "required",
                },
                status=201,
            )

        guest = identity_service.guest_from_request(request)
        if guest is None or not identity_service.is_guest_valid(guest):
            return Response(keyword_error_payload(IDENTITY_NOT_RESOLVED), status=401)

        record = ConsentService().withdraw(guest_identity=guest, request=request)
        return Response(
            {
                "consent_id": str(record.id),
                "identity_type": "guest",
                "consent_state": "required",
            },
            status=201,
        )


class ConsentStatusView(APIView):
    """Return canonical consent state for the current identity."""

    permission_classes = [AllowAny]

    def get(self, request):
        """Resolve consent status without changing records."""

        identity_service = IdentityService()
        consent_service = ConsentService()
        if request.user.is_authenticated:
            return Response(
                {
                    "identity_type": "user",
                    "consent_state": consent_service.state_for_identity(user=request.user),
                },
                status=200,
            )

        guest = identity_service.guest_from_request(request)
        if guest is not None and identity_service.is_guest_valid(guest):
            return Response(
                {
                    "identity_type": "guest",
                    "consent_state": consent_service.state_for_identity(guest_identity=guest),
                },
                status=200,
            )

        return Response({"identity_type": "none", "consent_state": "unknown"}, status=200)
