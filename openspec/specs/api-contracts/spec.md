# API Contracts & Data Contracts — Backend Domain Spec

Tài liệu này là **source of truth** cho tất cả contracts trong hệ thống WISMO backend. Worker PHẢI đọc file này trước khi code bất kỳ service nào truyền data giữa các components.

Contracts được implement trong `wismo/contracts/` package (pydantic BaseModel). Mọi data truyền giữa components phải dùng contract types — KHÔNG tự tạo dict/dataclass riêng.

---

## 1. Contract Registry

| Contract | Version | Producer | Consumer chính |
|----------|---------|----------|---------------|
| `P1Output` | `p1.v1` | SituationAnalyzer | SafetyStateMachine, RuleEngine, telemetry |
| `P2Output` | `p2.v1` | CasePhaseEvaluator | RuleEngine, CaseManager, P9 trigger |
| `RuleDecision` | `rule.v1` | RuleEngine | PromptBuilder, ResponseValidator, SSE frontend_state |
| `P3Request` | `p3-request.v1` | Orchestrator / PromptBuilder | LLM model call |
| `P3ValidatedResponse` | `p3-response.v1` | ResponseValidator | SSE streamer, telemetry |
| `P4ExtractionResult` | `p4.v1` | Case Context Accumulator | CaseManager |
| `MemoryItemPayload` | `memory.v1` | P5 Profile Facts Builder | MemoryManager, Personalizer |
| `P6PersonalitySignalResult` | `personality.v1` | Personality Signal Detector | Personalizer |
| `GoalStrategyPayload` | `p9.v1` | Goal & Strategy Builder | P2, P3, RAG query builder |
| `CrisisEventPayload` | `crisis-event.v1` | Safety pipeline | Telemetry, admin review |
| `SSEEvent` | `sse.v1` | ResponseStreamer | Frontend stream parser |
| `ChatSendRequest` | `chat-send.v1` | Frontend | Orchestrator |
| `ChatDonePayload` | `chat-done.v1` | Orchestrator | Frontend |
| `CaseTransitionEvent` | `case-transition.v1` | CaseManager | Sidebar sync, telemetry |
| `OutboxEventEnvelope` | `outbox.v1` | OutboxService | Dispatcher, repair jobs |
| `WismoError` | `error.v1` | Toàn hệ thống | Frontend, logging |
| `TracePayload` | `trace.v1` | Request ingress | Toàn pipeline, debug |
| `GuardResult` | `guard.v1` | InputGuard | Orchestrator |
| `CrisisResult` | `crisis.v1` | CrisisDetector | SafetyStateMachine |
| `SafetyDecision` | `safety.v1` | SafetyStateMachine | RuleEngine, PromptBuilder, ResponseValidator |
| `PersonalizationConfig` | `style.v1` | PersonalizerPolicy | PromptBuilder |

### Quy tắc contract evolution

- Mọi contract mang `schema_version` field.
- Thay đổi breaking (xóa/đổi tên field, đổi type) → bump version (v1 → v2) + migration path.
- Thay đổi additive (thêm field optional) → giữ version, thêm default.
- Mọi thay đổi breaking phải update: contract file + tests + domain spec này.

### Shared enum contracts

#### Requirement: Contracts package provides canonical shared enums
The system SHALL provide a framework-independent `wismo/contracts/` package containing canonical shared enums used across backend modules.

##### Scenario: Contracts package exists as plain Python import surface
- **GIVEN** the backend repository contains the contracts foundation
- **WHEN** a developer imports `wismo.contracts`
- **THEN** the package imports successfully in plain Python context
- **AND** it does not require Django app initialization

##### Scenario: Contracts package does not import application modules
- **GIVEN** files under `wismo/contracts/`
- **WHEN** static analysis or grep checks are run
- **THEN** there are no imports from `apps.*`
- **AND** there are no imports from `django.*`

#### Requirement: Canonical enums use string-backed Enum pattern
The system SHALL define canonical enums using `class Xxx(str, Enum)` so values serialize consistently as strings.

##### Scenario: Enum classes use string-backed enum inheritance
- **GIVEN** `wismo/contracts/enums.py`
- **WHEN** canonical enums are defined
- **THEN** each enum uses `str, Enum` inheritance
- **AND** enum values serialize as strings in Python and JSON contexts

#### Requirement: Contracts package freezes 15 canonical enums
The system SHALL define exactly 15 canonical enums in `wismo/contracts/enums.py` for immediate shared backend vocabulary.

##### Scenario: ConversationSafetyState has 7 exact values
- **GIVEN** `ConversationSafetyState`
- **WHEN** its values are enumerated
- **THEN** the exact set is `NORMAL`, `GUARDED`, `MODERATE_RISK_SAFE_ONLY`, `HIGH_RISK_LISTEN_ONLY`, `CRISIS_ONLY`, `BLOCKED_MINOR`, `BLOCKED_OUT_OF_SCOPE`

##### Scenario: CaseStatus has 7 exact values
- **GIVEN** `CaseStatus`
- **WHEN** its values are enumerated
- **THEN** the exact set is `active`, `progressing`, `paused`, `stalled`, `resolved`, `inactive`, `archived`
- **AND** `inactive` and `archived` are treated as distinct statuses

##### Scenario: CasePhase has 3 exact values
- **GIVEN** `CasePhase`
- **WHEN** its values are enumerated
- **THEN** the exact set is `understand`, `illuminate`, `followup`

##### Scenario: CounselingMethod has 7 exact values
- **GIVEN** `CounselingMethod`
- **WHEN** its values are enumerated
- **THEN** the exact set is `LISTEN`, `ASK`, `REFLECT`, `TEACH`, `FOLLOWUP`, `REDIRECT`, `CRISIS_SAFE_ONLY`

##### Scenario: CounselingSubmode has 7 exact values
- **GIVEN** `CounselingSubmode`
- **WHEN** its values are enumerated
- **THEN** the exact set is `reflection`, `clarifying_question`, `body_awareness`, `story`, `resource_redirect`, `followup_check`, `none`

##### Scenario: EmotionTag has 10 exact values
- **GIVEN** `EmotionTag`
- **WHEN** its values are enumerated
- **THEN** the exact set is `calm`, `anxious`, `stressed`, `sad`, `angry`, `confused`, `hopeful`, `overwhelmed`, `grateful`, `neutral_unknown`

##### Scenario: EmotionShift has 5 exact values
- **GIVEN** `EmotionShift`
- **WHEN** its values are enumerated
- **THEN** the exact set is `stable`, `escalating`, `de_escalating`, `new_topic`, `unknown`

##### Scenario: Sensitivity has 3 exact values
- **GIVEN** `Sensitivity`
- **WHEN** its values are enumerated
- **THEN** the exact set is `public_safe`, `private_safe`, `clinical_sensitive`

##### Scenario: ConsentState has 5 exact values
- **GIVEN** `ConsentState`
- **WHEN** its values are enumerated
- **THEN** the exact set is `no_consent`, `consented_v1`, `reconsent_required`, `withdrawn_pending_delete`, `deleted`

##### Scenario: SessionState has 6 exact values
- **GIVEN** `SessionState`
- **WHEN** its values are enumerated
- **THEN** the exact set is `opened`, `streaming`, `completed`, `abandoned`, `timeout_closed`, `validator_rejected`

##### Scenario: OutboxDeliveryState has 4 exact values
- **GIVEN** `OutboxDeliveryState`
- **WHEN** its values are enumerated
- **THEN** the exact set is `pending`, `dispatched`, `failed`, `dead_letter`

##### Scenario: ReadinessLevel has 4 exact values
- **GIVEN** `ReadinessLevel`
- **WHEN** its values are enumerated
- **THEN** the exact set is `not_ready`, `exploring`, `insight`, `self_resolving`

##### Scenario: RiskLevel has 4 exact values
- **GIVEN** `RiskLevel`
- **WHEN** its values are enumerated
- **THEN** the exact set is `none`, `low`, `moderate`, `high`

##### Scenario: OutOfScopeType has 6 exact values
- **GIVEN** `OutOfScopeType`
- **WHEN** its values are enumerated
- **THEN** the exact set is `none`, `medication`, `diagnosis`, `trauma`, `substance`, `other`

##### Scenario: Intent has 4 exact values
- **GIVEN** `Intent`
- **WHEN** its values are enumerated
- **THEN** the exact set is `RELATED`, `UNRELATED`, `UNSAFE`, `META_ATTACK`

#### Requirement: Enum regression tests detect canonical value drift
The system SHALL include regression tests that fail when canonical enum values are renamed, removed, added, or case-changed unintentionally.

##### Scenario: CaseStatus value change causes test failure
- **GIVEN** regression tests pass with canonical values
- **WHEN** a developer changes `CaseStatus.ACTIVE` from `active` to `Active`
- **THEN** the enum regression test fails

##### Scenario: Intent value change causes test failure
- **GIVEN** regression tests pass with canonical values
- **WHEN** a developer changes `Intent.RELATED` from `RELATED` to `related`
- **THEN** the enum regression test fails

#### Requirement: Contracts package exposes immediate-need version registry
The system SHALL expose a version registry for immediate-need contracts in `wismo/contracts/version.py`.

##### Scenario: CONTRACT_VERSIONS contains 13 entries
- **GIVEN** `CONTRACT_VERSIONS`
- **WHEN** its keys are counted
- **THEN** the dictionary contains exactly 13 entries

##### Scenario: get_contract_version returns expected version
- **GIVEN** `get_contract_version('P1Output')`
- **WHEN** the helper is called
- **THEN** it returns `p1.v1`

##### Scenario: get_contract_version rejects unknown contract name
- **GIVEN** `get_contract_version('UnknownContract')`
- **WHEN** the helper is called
- **THEN** it raises `KeyError`

---

## 2. REST API Endpoints

### Chat

| Method | Path | Mô tả | Auth |
|--------|------|-------|------|
| POST | `/api/chat/message` | Gửi message, nhận SSE stream response | Required |
| GET | `/api/chat/messages` | Tất cả messages của user (paginated) | Required |
| GET | `/api/chat/cases` | List cases cho sidebar | Required |
| GET | `/api/chat/cases/{id}/messages` | Messages thuộc 1 case | Required |
| POST | `/api/chat/new-session` | Force tạo session mới | Required |
| POST | `/api/chat/messages/{id}/feedback` | Thumbs up/down | Required |
| GET | `/api/chat/turn-status/{turn_id}` | Recovery: lấy trạng thái turn | Required |

### Auth

| Method | Path | Mô tả | Auth |
|--------|------|-------|------|
| POST | `/api/accounts/register` | Đăng ký email/password | Public |
| POST | `/api/accounts/login` | Đăng nhập | Public |
| POST | `/api/accounts/logout` | Đăng xuất | Required |
| POST | `/api/accounts/google/callback` | Google OAuth callback | Public |
| GET | `/api/accounts/profile` | Xem profile | Required |
| PUT | `/api/accounts/profile` | Cập nhật profile | Required |
| POST | `/api/auth/guest/init` | Tạo guest session | Public |

### Consent

| Method | Path | Mô tả | Auth |
|--------|------|-------|------|
| GET | `/api/accounts/consent/check` | Check consent status | Required |
| POST | `/api/accounts/consent` | Grant consent | Required |
| POST | `/api/accounts/consent/withdraw` | Withdraw consent | Required |

### Privacy (GDPR)

| Method | Path | Mô tả | Auth |
|--------|------|-------|------|
| GET | `/api/settings/privacy/export` | Export user data (async) | Required |
| POST | `/api/settings/privacy/delete-all` | Delete all data (async) | Required |

### Memory

| Method | Path | Mô tả | Auth |
|--------|------|-------|------|
| GET | `/api/memory/items` | List memory items (user_visible only) | Required |
| DELETE | `/api/memory/items/{id}` | Xóa 1 memory item | Required |
| DELETE | `/api/memory/items/all` | Xóa tất cả memory | Required |

---

## 3. REST API Request/Response Contracts

### 3.1 POST `/api/chat/message` — Request (`chat-send.v1`)

```python
class ChatSendRequest(BaseModel):
    """Request gửi message từ frontend.
    
    Frontend gửi qua POST body, backend validate rồi
    chuyển cho Orchestrator.handle_message().
    """
    schema_version: str = "chat-send.v1"
    content: str                        # trim; rỗng → 400
    session_id: str                     # guest và registered đều có
    active_case_id: Optional[str] = None  # optional; backend có quyền resolve lại
    client_context: Optional[ClientContext] = None

class ClientContext(BaseModel):
    """Metadata phía client, dùng cho analytics + locale."""
    app_locale: str = "vi"              # vi, en, fi
    timezone: Optional[str] = None      # fallback user profile timezone
    platform: str = "web"               # web, ios, android, unknown
```

### 3.2 POST `/api/chat/message` — Response: SSE Stream (`sse.v1`)

Response là SSE stream, mỗi event có format:
```
data: {"schema_version":"sse.v1", "type":"thinking", ...}\n\n
data: {"schema_version":"sse.v1", "type":"token", "text":"Mình"}\n\n
data: {"schema_version":"sse.v1", "type":"done", "final_text":"...", ...}\n\n
```

```python
class SSEEvent(BaseModel):
    """Một event trong SSE stream. FE parse từng event và switch theo type."""
    schema_version: str = "sse.v1"
    type: str               # thinking | token | info | done | error | state
    request_id: str          # UUID, từ POST request
    turn_id: Optional[str] = None
    text: Optional[str] = None          # chỉ có với type=token
    message: Optional[str] = None       # user-facing info/error message
    state_name: Optional[str] = None    # session_resolved, case_resolved, safety_resolved, validated
    frontend_state: str = "normal"      # FE switch UI theo field này
    is_final: bool = False              # True cho done và error
    meta: dict = {}
```

**Frontend states hợp lệ:** `normal`, `show_hotline_inline`, `show_hotline_overlay`, `show_info_banner`, `reconnecting`, `interrupted`, `recover_final_available`, `regenerate_required`

**Rules:**
- Client chỉ append text khi `type=token`
- `token` text là preview, KHÔNG phải source of truth cuối cùng
- `done` = turn đã validated + persisted → dùng `final_text` từ done payload
- Unknown event type → client ignore an toàn

### 3.3 Done Payload (`chat-done.v1`)

```python
class ChatDonePayload(BaseModel):
    """Payload khi turn hoàn thành. Là source of truth cuối cùng."""
    schema_version: str = "chat-done.v1"
    turn_id: str
    assistant_message_id: str
    final_text: str                     # SOURCE OF TRUTH cho FE
    final_status: str                   # completed | completed_terminal_safety | completed_after_regenerate
    active_case_id: Optional[str] = None
    case_transition: Optional[CaseTransitionEvent] = None
    feedback_enabled: bool = True
    validator_action: str               # passed_first_try | regenerated_once | regenerated_multiple | safe_truncated
    was_regenerated: bool = False
    persisted_at: str                   # ISO-8601
    preview_discard_required: bool = True
```

### 3.4 Turn Status Recovery (`chat-turn-status.v1`)

```python
class TurnStatusResponse(BaseModel):
    """Recovery endpoint khi FE reconnect giữa stream."""
    schema_version: str = "chat-turn-status.v1"
    turn_id: str
    recovery_state: str         # completed | stream_interrupted_no_final | failed_terminal
    assistant_message_id: Optional[str] = None
    final_text: Optional[str] = None
    retry_action: str           # recover_final | regenerate | none
    frontend_state: str         # recover_final_available | regenerate_required | error
```

---

## 4. Error Envelope (`error.v1`)

```python
class WismoError(BaseModel):
    """Envelope lỗi chuẩn. FE switch theo error_code + frontend_state."""
    schema_version: str = "error.v1"
    error_code: str
    error_category: str         # consent | auth | safety | rate_limit | stream | data_rights | provider | system
    http_status: int
    frontend_state: str
    user_message: str
    retryable: bool
    action_required: Optional[str] = None
    request_id: str
    turn_id: Optional[str] = None
    session_id: Optional[str] = None
    queued_job_id: Optional[str] = None
    details: Optional[dict] = None
```

**Error codes:**

| error_code | Khi dùng | frontend_state |
|------------|---------|----------------|
| `consent_required` | Chưa consent / expired | `consent_required` |
| `blocked_minor` | Age gate fail | `blocked` |
| `rate_limited` | Quota / abuse | `rate_limited` |
| `stream_interrupted` | Stream đứt | `reconnecting` |
| `attach_failed_login_succeeded` | OAuth ok, attach fail | `attach_review_required` |
| `export_queued` | Export accepted | `queued` |
| `delete_queued` | Delete accepted | `queued` |
| `provider_degraded` | Degraded mode | `degraded_mode` |
| `safe_fallback_only` | Safe fallback | `safe_fallback` |
| `system_unavailable` | Lỗi hệ thống | `error` |

---

## 5. Trace Envelope (`trace.v1`)

```python
class TracePayload(BaseModel):
    """Correlation xuyên suốt pipeline. Sinh ở ingress."""
    schema_version: str = "trace.v1"
    request_id: str
    turn_id: Optional[str] = None
    session_id: Optional[str] = None
    case_id: Optional[str] = None
    assistant_message_id: Optional[str] = None
    outbox_event_ids: list[str] = []
    provider_call_ids: list[str] = []
    validator_action_id: Optional[str] = None
    trace_status: str           # started | streaming_preview | validated | persisted | completed | recovered | failed
    contract_versions: dict = {}
    timestamps: dict[str, str] = {}
    latencies_ms: dict[str, int] = {}
    pipeline_steps: dict = {}
```

---

## 6. Domain Event Contracts

### 6.1 Case Transition (`case-transition.v1`)

```python
class CaseTransitionEvent(BaseModel):
    """Event khi case chuyển phase/status."""
    schema_version: str = "case-transition.v1"
    case_id: str
    from_phase: str             # understand | illuminate | followup
    to_phase: str
    from_status: str            # 7 CaseStatus values
    to_status: str
    reason_codes: list[str] = []
    trigger_turn_id: str
    persisted: bool
```

### 6.2 Outbox Event (`outbox.v1`)

```python
class OutboxEventEnvelope(BaseModel):
    """Async side effect đi qua outbox table."""
    schema_version: str = "outbox.v1"
    aggregate_type: str         # session | case | consent | account | archive
    aggregate_id: Optional[str] = None
    event_type: str
    event_version: str = "v1"
    payload: dict
    idempotency_key: str        # UNIQUE
    delivery_state: str = "pending"
    created_at: Optional[str] = None
    dispatched_at: Optional[str] = None
    retry_count: int = 0
```

**Event types:** `after_turn_dispatch`, `after_terminal_turn_dispatch`, `goal_strategy_dispatch`, `journey_summary_dispatch`, `guest_attach_dispatch`, `gdpr_delete_dispatch`, `consent_withdrawn_dispatch`, `archive_restore_dispatch`, `telemetry_aggregate_dispatch`

**Delivery states:** `pending` → `dispatched` | `failed` → (retry) | `dead_letter`

### 6.3 Crisis Event (`crisis-event.v1`)

```python
class CrisisEventPayload(BaseModel):
    """Log crisis detection. Anonymous — KHÔNG lưu user_id."""
    schema_version: str = "crisis-event.v1"
    session_hash: str           # hashed
    trigger_type: str           # keyword | pattern | p1_contextual
    crisis_level: str           # A | B | C | D
    detected_keywords: list[str]
    action_taken: str
    confidence: float
```

---

## 7. Internal Pipeline Contracts

### 7.1 Guard Result (`guard.v1`)

```python
class GuardResult(BaseModel):
    """InputGuard output — layer 1 security."""
    schema_version: str = "guard.v1"
    passed: bool = True
    blocked: bool = False        # legacy convenience mirror; should equal (not passed)
    block_reason: Optional[str] = None
    response: str = ""
    sanitized_content: Optional[str] = None
    reason: str = ""            # legacy alias: injection | empty | too_long | normal
    flags: list[str] = []
```

### 7.2 Crisis Result (`crisis.v1`)

```python
class CrisisResult(BaseModel):
    """CrisisDetector output — rule-based."""
    tier: Optional[str] = None  # A | B | C | D | None
    keyword: str = ""
    third_party: bool = False
    confidence: float = 0.0
    is_sarcasm: bool = False
    is_hypothetical: bool = False
```

### 7.3 Safety Decision (`safety.v1`)

```python
class SafetyDecision(BaseModel):
    """SafetyStateMachine output — hard constraints."""
    schema_version: str = "safety.v1"
    state: str                  # ConversationSafetyState enum
    constraints: dict           # allowed_methods, banned_exercises, required_elements
    reason_codes: list[str] = []
    persistent_flags: list[str] = []
```

### 7.4 Personalization Config (`style.v1`)

```python
class PersonalizationConfig(BaseModel):
    """PersonalizerPolicy output — style cho P3."""
    schema_version: str = "style.v1"
    tone: str = "warm"
    depth: str = "moderate"
    verbosity: str = "medium"
    response_length: str = "medium"
    notes: list[str] = []
```

---

## 8. State Machine Registry

| Machine | States | Source of truth | Owner |
|---------|--------|-----------------|-------|
| **ConsentLifecycle** | no_consent, consented_v1, reconsent_required, withdrawn_pending_delete, deleted | PostgreSQL gdpr_consents | ConsentService |
| **ConversationSafety** | NORMAL, GUARDED, MODERATE_RISK_SAFE_ONLY, HIGH_RISK_LISTEN_ONLY, CRISIS_ONLY, BLOCKED_MINOR, BLOCKED_OUT_OF_SCOPE | Runtime + persistent flags | SafetyStateMachine |
| **CaseLifecycle** | active, progressing, paused, stalled, resolved, inactive, archived | PostgreSQL user_cases | CaseManager |
| **CasePhase** | understand, illuminate, followup | PostgreSQL user_cases.phase | P2, CaseManager |
| **SessionRuntime** | opened, streaming, completed, abandoned, timeout_closed | DB sessions + runtime | SessionManager |

**Rules:** mỗi machine có 1 owner → consumer KHÔNG copy transition logic. Celery jobs mutate state chỉ qua owner service.

---

## 9. Enum Registry

Implement trong `wismo/contracts/enums.py`. Thay đổi value = breaking change.

| Enum | Values |
|------|--------|
| `ConversationSafetyState` | NORMAL, GUARDED, MODERATE_RISK_SAFE_ONLY, HIGH_RISK_LISTEN_ONLY, CRISIS_ONLY, BLOCKED_MINOR, BLOCKED_OUT_OF_SCOPE |
| `CaseStatus` | active, progressing, paused, stalled, resolved, inactive, archived |
| `CasePhase` | understand, illuminate, followup |
| `CounselingMethod` | LISTEN, ASK, REFLECT, TEACH, FOLLOWUP, REDIRECT, CRISIS_SAFE_ONLY |
| `CounselingSubmode` | reflection, clarifying_question, body_awareness, story, resource_redirect, followup_check, none |
| `EmotionTag` | calm, anxious, stressed, sad, angry, confused, hopeful, overwhelmed, grateful, neutral_unknown |
| `EmotionShift` | stable, escalating, de_escalating, new_topic, unknown |
| `Sensitivity` | public_safe, private_safe, clinical_sensitive |
| `ConsentState` | no_consent, consented_v1, reconsent_required, withdrawn_pending_delete, deleted |
| `SessionState` | opened, streaming, completed, abandoned, timeout_closed, validator_rejected |
| `OutboxDeliveryState` | pending, dispatched, failed, dead_letter |
| `ReadinessLevel` | not_ready, exploring, insight, self_resolving |
| `RiskLevel` | none, low, moderate, high |
| `OutOfScopeType` | none, medication, diagnosis, trauma, substance, other |
| `Intent` | RELATED, UNRELATED, UNSAFE, META_ATTACK |
