"""Error helpers for foundation APIs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WismoError:
    """Small structured error payload used by API views.

    Always serializes as keyword-only: {"error": code}.
    No plain-text message field — keeps FE/BFF contract stable.
    """

    code: str

    def as_dict(self) -> dict[str, str]:
        """Return the canonical keyword-only error payload."""

        return {"error": self.code}


def keyword_error_payload(code: str) -> dict[str, str]:
    """Build a keyword-only API error payload dict.

    Use this in views for ad-hoc error responses so all foundation
    error payloads share the same shape.
    """

    return {"error": code}
