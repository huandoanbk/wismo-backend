"""Consent service helpers for API and request gate paths."""

from __future__ import annotations

from django.utils import timezone

from consents.models import ConsentRecord


class ConsentService:
    """Manage current consent records for registered and guest identities."""

    def state_for_identity(self, *, user=None, guest_identity=None) -> str:
        """Return canonical consent state for a resolved or missing identity."""

        if user is None and guest_identity is None:
            return "unknown"

        latest = self._latest_record(user=user, guest_identity=guest_identity)
        if latest is None:
            return "required"
        if (
            latest.is_accepted
            and latest.revoked_at is None
            and latest.reconsent_required is False
            and latest.consent_version == ConsentRecord.CURRENT_VERSION
        ):
            return "accepted"
        return "required"

    def accept(self, *, user=None, guest_identity=None, request=None) -> ConsentRecord:
        """Persist current consent for exactly one identity."""

        payload = {
            "consent_version": ConsentRecord.CURRENT_VERSION,
            "is_accepted": True,
            "accepted_at": timezone.now(),
            "revoked_at": None,
            "reconsent_required": False,
        }
        if request is not None:
            payload["ip_address"] = self._client_ip(request)
            payload["user_agent"] = request.META.get("HTTP_USER_AGENT", "")

        if user is not None:
            payload["user"] = user
            payload["guest_identity"] = None
        elif guest_identity is not None:
            payload["guest_identity"] = guest_identity
            payload["user"] = None
        else:
            raise ValueError("Consent requires a user or guest identity.")

        return ConsentRecord.objects.create(**payload)

    def withdraw(self, *, user=None, guest_identity=None, request=None) -> ConsentRecord:
        """Persist a latest record that revokes current consent for an identity."""

        payload = {
            "consent_version": ConsentRecord.CURRENT_VERSION,
            "is_accepted": False,
            "accepted_at": timezone.now(),
            "revoked_at": timezone.now(),
            "reconsent_required": False,
        }
        if request is not None:
            payload["ip_address"] = self._client_ip(request)
            payload["user_agent"] = request.META.get("HTTP_USER_AGENT", "")

        if user is not None:
            payload["user"] = user
            payload["guest_identity"] = None
        elif guest_identity is not None:
            payload["guest_identity"] = guest_identity
            payload["user"] = None
        else:
            raise ValueError("Consent withdrawal requires a user or guest identity.")

        return ConsentRecord.objects.create(**payload)

    def has_active_consent(self, *, user=None, guest_identity=None) -> bool:
        """Return whether the resolved identity has accepted current consent."""

        return self.state_for_identity(user=user, guest_identity=guest_identity) == "accepted"

    def require_reconsent(self, *, user=None, guest_identity=None) -> ConsentRecord:
        """Persist a latest record that forces consent before chat resumes."""

        payload = {
            "consent_version": ConsentRecord.CURRENT_VERSION,
            "is_accepted": False,
            "accepted_at": timezone.now(),
            "revoked_at": None,
            "reconsent_required": True,
        }
        if user is not None:
            payload["user"] = user
            payload["guest_identity"] = None
        elif guest_identity is not None:
            payload["guest_identity"] = guest_identity
            payload["user"] = None
        else:
            raise ValueError("Re-consent requires a user or guest identity.")
        return ConsentRecord.objects.create(**payload)

    def _latest_record(self, *, user=None, guest_identity=None) -> ConsentRecord | None:
        """Return the latest current-version consent record for an identity."""

        filters = {"consent_version": ConsentRecord.CURRENT_VERSION}
        if user is not None:
            filters["user"] = user
            filters["guest_identity__isnull"] = True
        elif guest_identity is not None:
            filters["guest_identity"] = guest_identity
            filters["user__isnull"] = True
        else:
            return None
        return ConsentRecord.objects.filter(**filters).order_by("-accepted_at", "-id").first()

    @staticmethod
    def _client_ip(request) -> str | None:
        """Extract client IP from common proxy headers."""

        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
