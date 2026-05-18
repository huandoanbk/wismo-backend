"""Runtime config, quota, and Step 6 runtime-bundle services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from admin_config.models import RuntimeConfig
from memory.models import MemoryItem, UserPreferenceState, UserProfileState, UserStateSnapshot
from runtime.models import UsageQuotaWindow


@dataclass(frozen=True)
class RuntimeInputLimits:
    """Canonical request input limits for runtime gate checks."""

    max_message_length_chars: int
    max_payload_bytes: int


@dataclass(frozen=True)
class QuotaPolicy:
    """Canonical quota policy for one identity class."""

    token_limit: int
    window_seconds: int


@dataclass(frozen=True)
class PendingInputLimits:
    """Canonical bounds for quota-blocked pending input storage."""

    max_appends: int
    max_chars: int


@dataclass(frozen=True)
class StepTraceConfig:
    """Runtime step trace capture mode for per-turn admin observability."""

    level: str


@dataclass(frozen=True)
class GuestSessionPolicy:
    """Admin-controlled guest session idle TTL."""

    idle_ttl_hours: int


@dataclass(frozen=True)
class AdminContactPolicy:
    """Admin-controlled destination email for contact form submissions."""

    email: str


@dataclass(frozen=True)
class PromptAssemblyPolicy:
    """Admin-controlled prompt assembly compaction threshold."""

    max_estimated_tokens: int


class RuntimeConfigService:
    """Read admin-controlled runtime configuration with deterministic defaults."""

    INPUT_LIMITS_KEY = "runtime.input_limits"
    GUEST_QUOTA_POLICY_KEY = "quota.guest_policy"
    USER_QUOTA_POLICY_KEY = "quota.user_policy"
    PENDING_INPUT_LIMITS_KEY = "quota.pending_input_limits"
    STEP_TRACE_KEY = "runtime.step_trace"
    GUEST_SESSION_KEY = "guest.session_policy"
    ADMIN_CONTACT_KEY = "admin.contact_email"
    PROMPT_ASSEMBLY_KEY = "runtime.prompt_assembly"

    DEFAULT_INPUT_LIMITS = RuntimeInputLimits(max_message_length_chars=8000, max_payload_bytes=65536)
    DEFAULT_GUEST_QUOTA_POLICY = QuotaPolicy(token_limit=100000, window_seconds=86400)
    DEFAULT_USER_QUOTA_POLICY = QuotaPolicy(token_limit=1000000, window_seconds=86400)
    DEFAULT_PENDING_INPUT_LIMITS = PendingInputLimits(max_appends=10, max_chars=12000)
    DEFAULT_PROMPT_ASSEMBLY_POLICY = PromptAssemblyPolicy(max_estimated_tokens=3500)
    DEFAULT_STEP_TRACE = StepTraceConfig(level="off")
    DEFAULT_GUEST_SESSION_POLICY = GuestSessionPolicy(idle_ttl_hours=6)
    DEFAULT_ADMIN_CONTACT_POLICY = AdminContactPolicy(email="")

    def input_limits(self) -> RuntimeInputLimits:
        """Return canonical text and payload limits for request gate checks."""

        return self._parse_input_limits(
            self._load_value(self.INPUT_LIMITS_KEY, self.DEFAULT_INPUT_LIMITS),
        )

    def guest_quota_policy(self) -> QuotaPolicy:
        """Return canonical quota policy for guest identities."""

        return self._parse_quota_policy(
            self._load_value(self.GUEST_QUOTA_POLICY_KEY, self.DEFAULT_GUEST_QUOTA_POLICY),
            self.DEFAULT_GUEST_QUOTA_POLICY,
        )

    def user_quota_policy(self) -> QuotaPolicy:
        """Return canonical quota policy for registered identities."""

        return self._parse_quota_policy(
            self._load_value(self.USER_QUOTA_POLICY_KEY, self.DEFAULT_USER_QUOTA_POLICY),
            self.DEFAULT_USER_QUOTA_POLICY,
        )

    def pending_input_limits(self) -> PendingInputLimits:
        """Return canonical bounds for quota-blocked pending input state."""

        return self._parse_pending_input_limits(
            self._load_value(self.PENDING_INPUT_LIMITS_KEY, self.DEFAULT_PENDING_INPUT_LIMITS),
        )

    def step_trace_config(self) -> StepTraceConfig:
        """Return runtime step trace capture mode."""

        return self._parse_step_trace(
            self._load_value(self.STEP_TRACE_KEY, self.DEFAULT_STEP_TRACE),
        )

    def guest_session_policy(self) -> GuestSessionPolicy:
        """Return admin-controlled guest session idle TTL policy."""

        return self._parse_guest_session_policy(
            self._load_value(self.GUEST_SESSION_KEY, self.DEFAULT_GUEST_SESSION_POLICY),
        )

    def admin_contact_policy(self) -> AdminContactPolicy:
        """Return admin-controlled destination email for contact form submissions."""

        return self._parse_admin_contact_policy(
            self._load_value(self.ADMIN_CONTACT_KEY, self.DEFAULT_ADMIN_CONTACT_POLICY),
        )

    def prompt_assembly_policy(self) -> PromptAssemblyPolicy:
        """Return admin-controlled prompt assembly compaction threshold."""

        return self._parse_prompt_assembly_policy(
            self._load_value(self.PROMPT_ASSEMBLY_KEY, self.DEFAULT_PROMPT_ASSEMBLY_POLICY),
        )

    def step_trace_level(self) -> str:
        """Return normalized step trace level token."""

        return self.step_trace_config().level

    def quota_policy_for_identity(self, *, user=None, guest_identity=None) -> QuotaPolicy:
        """Return the active quota policy for the resolved identity class."""

        if user is not None:
            return self.user_quota_policy()
        if guest_identity is not None:
            return self.guest_quota_policy()
        raise ValueError("Quota policy requires a user or guest identity.")

    def _load_value(self, key: str, default: Any) -> dict[str, Any]:
        """Load an active runtime config record or return the deterministic default."""

        record = (
            RuntimeConfig.objects.filter(key=key, is_active=True)
            .order_by("-updated_at", "-created_at")
            .first()
        )
        if record is None or not isinstance(record.value, dict):
            return self._clone_default(default)
        return record.value

    @staticmethod
    def _clone_default(default: Any) -> dict[str, Any]:
        """Return a JSON-like mapping for a dataclass default."""

        if hasattr(default, "__dict__"):
            return dict(default.__dict__)
        return dict(default)

    @staticmethod
    def _parse_int(value: Any, default: int) -> int:
        """Parse a positive integer config field with fallback to default."""

        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        if parsed <= 0:
            return default
        return parsed

    def _parse_input_limits(self, value: dict[str, Any]) -> RuntimeInputLimits:
        """Coerce the `runtime.input_limits` mapping into a typed config object."""

        default = self.DEFAULT_INPUT_LIMITS
        return RuntimeInputLimits(
            max_message_length_chars=self._parse_int(
                value.get("max_message_length_chars", default.max_message_length_chars),
                default.max_message_length_chars,
            ),
            max_payload_bytes=self._parse_int(
                value.get("max_payload_bytes", default.max_payload_bytes),
                default.max_payload_bytes,
            ),
        )

    def _parse_quota_policy(self, value: dict[str, Any], default: QuotaPolicy) -> QuotaPolicy:
        """Coerce a quota policy mapping into a typed config object."""

        return QuotaPolicy(
            token_limit=self._parse_int(value.get("token_limit", default.token_limit), default.token_limit),
            window_seconds=self._parse_int(
                value.get("window_seconds", default.window_seconds),
                default.window_seconds,
            ),
        )

    def _parse_pending_input_limits(self, value: dict[str, Any]) -> PendingInputLimits:
        """Coerce pending-input bounds into a typed config object."""

        default = self.DEFAULT_PENDING_INPUT_LIMITS
        return PendingInputLimits(
            max_appends=self._parse_int(value.get("max_appends", default.max_appends), default.max_appends),
            max_chars=self._parse_int(value.get("max_chars", default.max_chars), default.max_chars),
        )

    def _parse_step_trace(self, value: dict[str, Any]) -> StepTraceConfig:
        """Coerce runtime step trace config into a typed config object."""

        allowed = {"off", "meta", "full"}
        raw = value.get("level", self.DEFAULT_STEP_TRACE.level)
        normalized = raw.strip().lower() if isinstance(raw, str) else self.DEFAULT_STEP_TRACE.level
        if normalized not in allowed:
            normalized = self.DEFAULT_STEP_TRACE.level
        return StepTraceConfig(level=normalized)

    def _parse_guest_session_policy(self, value: dict[str, Any]) -> GuestSessionPolicy:
        """Coerce guest session policy mapping into a typed config object."""

        default = self.DEFAULT_GUEST_SESSION_POLICY
        return GuestSessionPolicy(
            idle_ttl_hours=self._parse_int(
                value.get("idle_ttl_hours", default.idle_ttl_hours),
                default.idle_ttl_hours,
            ),
        )

    def _parse_prompt_assembly_policy(self, value: dict[str, Any]) -> PromptAssemblyPolicy:
        """Coerce prompt assembly policy mapping into a typed config object."""

        default = self.DEFAULT_PROMPT_ASSEMBLY_POLICY
        return PromptAssemblyPolicy(
            max_estimated_tokens=self._parse_int(
                value.get("max_estimated_tokens", default.max_estimated_tokens),
                default.max_estimated_tokens,
            ),
        )

    def _parse_admin_contact_policy(self, value: dict[str, Any]) -> AdminContactPolicy:
        """Coerce admin contact email mapping into a typed config object."""

        raw = value.get("email", self.DEFAULT_ADMIN_CONTACT_POLICY.email)
        email = str(raw).strip() if isinstance(raw, str) else ""
        return AdminContactPolicy(email=email)


class QuotaService:
    """Resolve and mutate quota windows using canonical runtime config."""

    def __init__(self, config_service: RuntimeConfigService | None = None) -> None:
        """Create a quota service with injectable config resolution."""

        self.config_service = config_service or RuntimeConfigService()

    def current_for_identity(self, *, user=None, guest_identity=None) -> UsageQuotaWindow:
        """Return the current quota window, rolling forward when expired."""

        policy = self.config_service.quota_policy_for_identity(user=user, guest_identity=guest_identity)
        now = timezone.now()
        with transaction.atomic():
            current = self._locked_current_window(user=user, guest_identity=guest_identity)
            if current is not None:
                self._normalize_current_window(current, policy)
                if current.window_ends_at is not None and current.window_ends_at <= now:
                    return self._rollover_window(
                        user=user,
                        guest_identity=guest_identity,
                        policy=policy,
                        now=now,
                    )
                return current
            return self._create_window(user=user, guest_identity=guest_identity, policy=policy, now=now)

    def append_pending_input(self, quota_window: UsageQuotaWindow, message: str) -> UsageQuotaWindow:
        """Append blocked input using admin-controlled recovery bounds."""

        limits = self.config_service.pending_input_limits()
        input_limits = self.config_service.input_limits()
        max_chars = min(limits.max_chars, input_limits.max_message_length_chars)
        with transaction.atomic():
            window = self._locked_window(quota_window)
            window.append_pending_input(message, max_appends=limits.max_appends, max_chars=max_chars)
            return window

    def consume_tokens(self, quota_window: UsageQuotaWindow, tokens: int) -> tuple[UsageQuotaWindow, dict[str, Any], dict[str, Any]]:
        """Consume billable tokens and return before/after snapshots."""

        with transaction.atomic():
            window = self._locked_window(quota_window)
            quota_before = window.snapshot()
            window.consume_tokens(tokens)
            quota_after = window.snapshot()
            return window, quota_before, quota_after

    def _locked_current_window(self, *, user=None, guest_identity=None) -> UsageQuotaWindow | None:
        """Lock and return the latest quota window for the resolved identity."""

        filters: dict[str, Any]
        if user is not None:
            filters = {"user": user, "guest_identity__isnull": True}
        elif guest_identity is not None:
            filters = {"guest_identity": guest_identity, "user__isnull": True}
        else:
            raise ValueError("Quota window requires a user or guest identity.")

        return (
            UsageQuotaWindow.objects.select_for_update()
            .filter(**filters)
            .order_by("-window_started_at", "-created_at", "-id")
            .first()
        )

    def _locked_window(self, quota_window: UsageQuotaWindow) -> UsageQuotaWindow:
        """Lock and refresh a single quota window row."""

        return UsageQuotaWindow.objects.select_for_update().get(pk=quota_window.pk)

    def _normalize_current_window(self, quota_window: UsageQuotaWindow, policy: QuotaPolicy) -> None:
        """Backfill legacy expiry metadata for the latest window if needed."""

        if quota_window.window_ends_at is not None:
            return

        quota_window.window_ends_at = quota_window.window_started_at + timedelta(seconds=policy.window_seconds)
        quota_window.save(update_fields=["window_ends_at", "updated_at"])

    def _rollover_window(self, *, user=None, guest_identity=None, policy: QuotaPolicy, now) -> UsageQuotaWindow:
        """Create a new current window for the next quota period."""

        return UsageQuotaWindow.objects.create(
            user=user,
            guest_identity=guest_identity,
            window_started_at=now,
            window_ends_at=now + timedelta(seconds=policy.window_seconds),
            token_limit=policy.token_limit,
        )

    def _create_window(self, *, user=None, guest_identity=None, policy: QuotaPolicy, now) -> UsageQuotaWindow:
        """Create the initial current window for an identity."""

        return UsageQuotaWindow.objects.create(
            user=user,
            guest_identity=guest_identity,
            window_started_at=now,
            window_ends_at=now + timedelta(seconds=policy.window_seconds),
            token_limit=policy.token_limit,
        )


class IdentityStateStoreService:
    """Read and upsert identity-scoped profile/preference/state records."""

    PREFERENCE_THRESHOLD = 2

    def read_bundle_fields(self, *, identity) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Return profile/preference/state payloads for Step 6 bundle with safe fallbacks."""

        profile_payload = self._read_profile(identity=identity)
        preference_payload = self._read_preference(identity=identity)
        state_payload = self._read_state(identity=identity)
        return profile_payload, preference_payload, state_payload

    def upsert_user_profile(self, *, identity, explicit_profile_facts: list[str]) -> list[str]:
        """Merge extracted profile facts into identity profile state."""

        facts = self._normalize_facts(explicit_profile_facts)
        if not facts:
            return []
        record, _ = UserProfileState.objects.get_or_create(
            **identity.owner_kwargs(),
            defaults={"profile_data": {"facts": facts}, "version": 1},
        )
        profile_data = record.profile_data if isinstance(record.profile_data, dict) else {}
        existing_facts = profile_data.get("facts")
        merged = self._merge_string_lists(existing_facts if isinstance(existing_facts, list) else [], facts)
        if merged == (existing_facts if isinstance(existing_facts, list) else []):
            return []
        profile_data["facts"] = merged
        record.profile_data = profile_data
        record.version = max(1, int(record.version)) + 1
        record.save(update_fields=["profile_data", "version", "updated_at"])
        return ["facts"]

    def upsert_user_preference(self, *, identity, style_signals: list[str]) -> list[str]:
        """Update preference state when style signals reach evidence threshold."""

        normalized_signals = [item.strip() for item in style_signals if isinstance(item, str) and item.strip()]
        if not normalized_signals:
            return []
        record, _ = UserPreferenceState.objects.get_or_create(
            **identity.owner_kwargs(),
            defaults={"preference_data": {}, "evidence_counts": {}},
        )
        evidence_counts = record.evidence_counts if isinstance(record.evidence_counts, dict) else {}
        preference_data = record.preference_data if isinstance(record.preference_data, dict) else {}
        updated_fields: list[str] = []
        for signal in normalized_signals:
            count = int(evidence_counts.get(signal, 0)) + 1
            evidence_counts[signal] = count
            if count >= self.PREFERENCE_THRESHOLD and preference_data.get(signal) is not True:
                preference_data[signal] = True
                updated_fields.append(signal)
        record.evidence_counts = evidence_counts
        record.preference_data = preference_data
        record.save(update_fields=["evidence_counts", "preference_data", "updated_at"])
        return updated_fields

    def upsert_user_state(self, *, identity, user_state_signals: list[str]) -> dict[str, str]:
        """Persist primary/secondary user state from normalized state signals."""

        ordered = self._ordered_state_signals(user_state_signals)
        if not ordered:
            return {}
        primary = ordered[0]
        secondary = ordered[1] if len(ordered) > 1 else ""
        record, _ = UserStateSnapshot.objects.get_or_create(
            **identity.owner_kwargs(),
            defaults={
                "primary_state": primary,
                "secondary_state": secondary,
                "raw_signals": ordered,
            },
        )
        record.primary_state = primary
        record.secondary_state = secondary
        record.raw_signals = ordered
        record.save(update_fields=["primary_state", "secondary_state", "raw_signals", "updated_at"])
        return {"primary_state": primary, "secondary_state": secondary}

    def _read_profile(self, *, identity) -> dict[str, Any]:
        record = UserProfileState.objects.filter(**identity.owner_kwargs()).first()
        if record is None or not isinstance(record.profile_data, dict):
            return {}
        return record.profile_data

    def _read_preference(self, *, identity) -> dict[str, Any]:
        record = UserPreferenceState.objects.filter(**identity.owner_kwargs()).first()
        if record is None or not isinstance(record.preference_data, dict):
            return {}
        return record.preference_data

    def _read_state(self, *, identity) -> dict[str, Any]:
        record = UserStateSnapshot.objects.filter(**identity.owner_kwargs()).first()
        if record is None:
            return {}
        payload: dict[str, Any] = {}
        if record.primary_state:
            payload["primary_state"] = record.primary_state
        if record.secondary_state:
            payload["secondary_state"] = record.secondary_state
        if isinstance(record.raw_signals, list) and record.raw_signals:
            payload["signals"] = [str(item) for item in record.raw_signals if isinstance(item, str)]
        return payload

    @staticmethod
    def _normalize_facts(values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in values:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if not value or value.lower() == "none":
                continue
            if value not in cleaned:
                cleaned.append(value)
        return cleaned

    @staticmethod
    def _merge_string_lists(left: list[str], right: list[str]) -> list[str]:
        merged: list[str] = []
        for item in left + right:
            if isinstance(item, str) and item not in merged:
                merged.append(item)
        return merged

    @staticmethod
    def _ordered_state_signals(signals: list[str]) -> list[str]:
        priority = [
            "emotionally_fragile",
            "overwhelmed",
            "ruminating",
            "defensive",
            "stable_enough",
        ]
        cleaned = [item.strip() for item in signals if isinstance(item, str) and item.strip() and item != "none"]
        if not cleaned:
            return []
        ranked = sorted(set(cleaned), key=lambda value: priority.index(value) if value in priority else len(priority))
        return ranked[:2]


class RuntimeBundleService:
    """Assemble Main Flow Step 6 runtime bundle fields."""

    def __init__(self, state_store: IdentityStateStoreService | None = None) -> None:
        """Create a runtime bundle service with injectable state-store dependency."""

        self.state_store = state_store or IdentityStateStoreService()

    def build_bundle(
        self,
        *,
        chat,
        turn,
        case,
        identity,
        current_message: str,
    ) -> dict[str, Any]:
        """Return the canonical runtime_bundle for downstream steps."""

        recent_turns = self._recent_turns(chat=chat, current_turn=turn)
        context_summary = case.context_summary if case is not None else ""
        long_term_memory = self._long_term_memory(case=case, identity=identity)
        user_profile, user_preference, user_state = self.state_store.read_bundle_fields(identity=identity)

        return {
            "current_message": current_message,
            "recent_turns": recent_turns,
            "context_summary": context_summary,
            "user_profile": user_profile,
            "user_preference": user_preference,
            "user_state": user_state,
            "long_term_memory": long_term_memory,
        }

    @staticmethod
    def _recent_turns(*, chat, current_turn) -> list[dict[str, Any]]:
        """Load up to 5 recent turns ordered from oldest to newest."""

        rows = list(
            chat.turns.filter(status="completed")
            .exclude(id=current_turn.id)
            .order_by("-created_at", "-id")[:5]
            .values(
                "user_message_text",
                "assistant_response_text",
                "response_method",
            )
        )
        rows.reverse()
        return rows

    def _long_term_memory(self, *, case, identity) -> list[dict[str, Any]]:
        """Load case-scoped long-term timeline segments with fail-safe fallback."""

        if case is None:
            return []
        try:
            queryset = (
                MemoryItem.objects.filter(case=case, **identity.owner_kwargs())
                .order_by("updated_at", "id")
                .values(
                    "user_concern_summary",
                    "assistant_approach_summary",
                    "user_response_summary",
                    "state_shift",
                    "open_loops",
                    "updated_at",
                )
            )
            return [
                {
                    "user_concern_summary": item["user_concern_summary"] or "",
                    "assistant_approach_summary": item["assistant_approach_summary"] or "",
                    "user_response_summary": item["user_response_summary"] or "",
                    "state_shift": item["state_shift"] or "",
                    "open_loops": item["open_loops"] if isinstance(item["open_loops"], list) else [],
                    "updated_at": item["updated_at"].isoformat() if item.get("updated_at") else "",
                }
                for item in queryset
            ]
        except Exception:
            return []
