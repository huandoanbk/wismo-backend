"""Shared constants for the accounts app."""

from __future__ import annotations

import uuid

# Fixed UUID for the Anonymous Sentinel user — receives ownership of all
# anonymized data when a user erases their chat history (GDPR right to erasure).
# This record is seeded once via data migration and must never be deleted.
ANONYMOUS_USER_ID: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
