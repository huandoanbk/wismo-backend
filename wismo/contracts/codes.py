"""Canonical shared error and control code constants for the MVP foundation.

Covers codes used across auth/session, consent, chat bootstrap, and the
request gate pipeline. Domain-specific codes (OTP, Google auth, etc.) stay
in their own service modules.
"""

# --- Identity / Session ---

IDENTITY_NOT_RESOLVED = "identity_not_resolved"
GUEST_IDENTITY_NOT_RESOLVED = "guest_identity_not_resolved"
GUEST_SESSION_EXPIRED = "guest_session_expired"
SESSION_EXPIRED = "session_expired"
SESSION_REQUIRED = "session_required"

# --- Consent ---

CONSENT_REQUIRED = "consent_required"

# --- Chat Access ---

CHAT_NOT_FOUND = "chat_not_found"
CHAT_ACCESS_DENIED = "chat_access_denied"
GUEST_CHAT_NOT_FOUND = "guest_chat_not_found"

# --- Quota ---

QUOTA_EXCEEDED = "quota_exceeded"
REGISTRATION_REQUIRED_BY_QUOTA = "registration_required_by_quota"

# --- Request Validation ---

INVALID_REQUEST = "invalid_request"
INVALID_CHAT_ID = "invalid_chat_id"
MISSING_REQUIRED_FIELD = "missing_required_field"
EMPTY_MESSAGE = "empty_message"
MESSAGE_TOO_LONG = "message_too_long"
PAYLOAD_TOO_LARGE = "payload_too_large"

# --- Concurrency ---

TURN_IN_PROGRESS = "turn_in_progress"

# --- Account Settings ---

NO_USABLE_PASSWORD = "no_usable_password"
ALREADY_HAS_PASSWORD = "already_has_password"
INVALID_CURRENT_PASSWORD = "invalid_current_password"
DISPLAY_NAME_TOO_LONG = "display_name_too_long"
