# Design: cc-contracts-models-ci

## Overview
F2b xây lớp contract models bên trên F2a:
- F2a đóng băng enum language + version registry
- F2b dựng các Pydantic models sử dụng bộ enums đó

Thiết kế ưu tiên implementation-first:
- chỉ tạo contracts cần ngay cho F3, S1, S3
- giữ package `wismo/contracts/` độc lập
- tránh over-design cho các future contracts chưa ổn định

## File Structure

```text
wismo-backend/
├── wismo/
│   └── contracts/
│       ├── __init__.py         # update: re-export public contracts
│       ├── enums.py            # from F2a
│       ├── version.py          # from F2a
│       ├── p1.py               # P1Output + nested models
│       ├── p2.py               # P2Output + nested models
│       ├── rule.py             # RuleDecision
│       ├── safety.py           # GuardResult, CrisisResult, SafetyDecision
│       ├── style.py            # PersonalizationConfig
│       ├── sse.py              # SSEEvent, ChatDonePayload, ChatSendRequest
│       ├── outbox.py           # OutboxEventEnvelope
│       ├── error.py            # WismoError
│       ├── trace.py            # TracePayload
│       └── case.py             # CaseTransitionEvent
├── tests/
│   └── test_contracts/
│       ├── __init__.py         # from F2a
│       ├── test_enums.py       # from F2a
│       └── test_serialization.py
├── .github/
│   └── workflows/
│       └── ci.yml
└── pyproject.toml
```

## Contract Design Principles
- Dùng **Pydantic v2 BaseModel**
- Mỗi public contract có `schema_version` với default cố định
- Nested models đặt cùng file khi liên quan chặt
- Không import `apps.*` hoặc `django.*`
- Không chứa business workflow logic
- Các field vocabulary đã ổn định thì dùng enums từ F2a
- Các field chưa ổn định hoàn toàn có thể tạm giữ là `str` hoặc `Dict[str, Any]`

## Contract Inventory

### p1.py
Public model:
- `P1Output`

Nested models:
- `EmotionSignal`
- `ContraindicationSignal`
- `ScopeSignal`
- `SafetySignal`
- `ContentSignal`
- `SessionEndingSignal`

Key notes:
- `emotion.primary: EmotionTag`
- `emotion.shift: EmotionShift`
- `intent: Intent`
- `confidence` constrained `0.0..1.0`
- `emotion.severity` constrained `0..10`

### p2.py
Public model:
- `P2Output`

Nested models:
- `ContextAssessment`
- `RecommendedAction`

Key notes:
- `phase: CasePhase`
- `status: CaseStatus`
- `readiness: ReadinessLevel`
- `recommended_action.method: CounselingMethod`

### rule.py
Public model:
- `RuleDecision`

Key notes:
- `mode: CounselingMethod`
- `submode: CounselingSubmode`
- `ui_hints` có thể dùng `Dict[str, Any]`
- `safety_state` tạm để `str` cho tới khi runtime vocabulary ổn định hơn

### safety.py
Public models:
- `GuardResult`
- `CrisisResult`
- `SafetyDecision`

Nested model:
- `SafetyConstraints`

Key notes:
- `SafetyDecision.state: ConversationSafetyState`
- `CrisisResult.tier` tạm để `Optional[str]`

### style.py
Public model:
- `PersonalizationConfig`

Key notes:
- giữ các field style như `tone`, `depth`, `verbosity`, `response_length` là string trước mắt

### sse.py
Public models:
- `SSEEvent`
- `ChatDonePayload`
- `ChatSendRequest`

Key notes:
- `ChatSendRequest.content`: required, `min_length=1`, `max_length=2000`
- `SSEEvent` dùng cho SSE stream payload
- `ChatDonePayload` dùng cho canonical done event

### outbox.py
Public model:
- `OutboxEventEnvelope`

Key notes:
- required: `idempotency_key`, `event_type`, `created_at`
- `delivery_state: OutboxDeliveryState`
- timestamp fields tạm để ISO-8601 string

### error.py
Public model:
- `WismoError`

Key notes:
- required core fields: `error_code`, `error_category`, `http_status`, `user_message`
- `details` có thể dùng `Dict[str, Any]`

### trace.py
Public model:
- `TracePayload`

Key notes:
- `request_id` required
- `timestamps`, `latencies_ms`, `pipeline_steps` dùng dict payloads

### case.py
Public model:
- `CaseTransitionEvent`

Key notes:
- `from_phase`, `to_phase`: `CasePhase`
- `from_status`, `to_status`: `CaseStatus`
- dùng cho sidebar / case sync flow

## Public Exports Policy
`wismo/contracts/__init__.py` nên re-export ít nhất các public top-level symbols sau:
- `P1Output`
- `P2Output`
- `RuleDecision`
- `GuardResult`
- `CrisisResult`
- `SafetyDecision`
- `SafetyConstraints`
- `PersonalizationConfig`
- `SSEEvent`
- `ChatDonePayload`
- `ChatSendRequest`
- `OutboxEventEnvelope`
- `WismoError`
- `TracePayload`
- `CaseTransitionEvent`

Nested helper models có thể re-export nếu downstream thực sự cần import trực tiếp, nhưng không bắt buộc export tất cả.

## Validation Strategy
F2b chỉ khóa những invariants cần ngay:
- `EmotionSignal.severity` phải trong `0..10`
- `P1Output.confidence` phải trong `0.0..1.0`
- `ChatSendRequest.content` không được rỗng
- `ChatSendRequest.content` không quá 2000 ký tự

Các validation khác có thể bổ sung ở tasks sau khi runtime semantics ổn định hơn.

## Timestamp Policy
Các timestamp fields trong F2b tạm thời dùng **ISO-8601 string** thay vì `datetime` để:
- dễ serialize qua API/SSE/outbox
- giảm friction giữa contracts và persistence layers
- tránh ép chuẩn hóa quá sớm trong foundation task

Fields kiểu này gồm:
- `created_at`
- `dispatched_at`
- `persisted_at`

## CI Strategy
CI trong F2b chỉ cần cover contracts scope:
- `ruff check wismo/contracts/`
- `mypy wismo/contracts/ --strict`
- `pytest tests/test_contracts/ -v`

**Python version trong CI phải khớp version thực tế của backend repo**, không hardcode một version khác nếu repo chưa chốt.

## Dependency Management
Task này phải follow convention dependency management hiện có của repo.

- Nếu repo dùng `requirements-dev.txt`, update file đó
- Nếu repo dùng `pyproject.toml` hoặc cách khác, follow setup hiện có

F2b không được tự ý ép repo đổi sang workflow dependency khác.
