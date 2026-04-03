# Architecture — Backend Domain Spec

Tài liệu này mô tả kiến trúc tổng thể của WISMO backend: request lifecycle, project structure, module boundaries, outbox pattern, middleware chain, và timing targets.

Worker PHẢI đọc file này khi code orchestrator, services, middleware, hoặc bất kỳ thành phần nào ảnh hưởng đến request flow.

---

## 1. Hệ thống tổng quan

WISMO gồm 2 hệ thống riêng biệt:

**Hệ thống 1 — Embedding Service (offline, chạy trước):** nạp knowledge base vào vector DB. Stack: FastAPI + SQLAlchemy + Streamlit. Repo riêng: `wismo-embedding`.

**Hệ thống 2 — Chatbot App (online, chạy 24/7):** serve user, counseling. Stack: Django + Next.js + Celery + Redis. Kết nối: đọc từ vector DB đã populated bởi Embedding Service. Repo này (`wismo-backend`) chỉ chứa hệ thống 2.

## 2. Tech Stack

| Layer | Công nghệ |
|-------|-----------|
| Frontend | Next.js 15 + React + Tailwind + next-intl (repo riêng) |
| Realtime | SSE (Server-Sent Events) |
| Backend | Django 5 + DRF |
| Async | Celery + Redis |
| App DB | PostgreSQL 16 (port 5432) |
| Vector DB | PostgreSQL 16 + pgvector (port 5433) |
| Object Storage | Contabo S3 |
| LLM Free | DeepSeek V3 |
| LLM Pro | GPT-4o |
| LLM Fallback | GPT-4o-mini |
| Auth | Django + Google OAuth |
| Monitoring | Sentry + structured logging |
| CI/CD | GitHub Actions |
| Deploy | VPS + Docker + Nginx + Gunicorn |

## 3. Canonical Request Lifecycle v2

Khi user gửi message, flow đi qua 3 layers. Request path chỉ xử lý sync logic, persist state, rồi append outbox. Async work KHÔNG fire trực tiếp từ request path.

```
USER GỬI MESSAGE
    │
    ▼
┌─ PRESENTATION (Next.js) ────────────────────────────┐
│  POST /api/chat/message → SSE stream                │
│  FE chỉ coi thành công khi nhận `done` canonical    │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─ APPLICATION (Django Orchestrator) ─────────────────┐
│  1. InputGuard (sanitize, length, injection)        │
│  2. Resolve consent / identity / session            │
│  3. Resolve case context                            │
│  4. P1 + P2 (parallel)                              │
│  5. SafetyStateMachine (HARD GATE)                  │
│  6. RuleEngine + Personalizer                       │
│  7. Load context (memory / RAG / case / journey)    │
│  8. Build P3Request (prompt assembly)               │
│  9. Stream preview + validator + regenerate          │
│ 10. Persist final canonical assistant turn           │
│ 11. Append outbox events (SAME transaction)         │
│ 12. Commit transaction                              │
│ 13. Emit SSE `done` từ persisted final state        │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─ ASYNC (Outbox-backed dispatch) ────────────────────┐
│  Dispatcher đọc outbox_events sau commit            │
│  → P4 / P5 / P6 (after-turn)                       │
│  → P7 / P8 / P9 (triggered)                        │
│  → telemetry / audit side effects                   │
│  → repair / export-delete workflows                 │
└─────────────────────────────────────────────────────┘
```

### 3.1 Hard Rules

- SafetyStateMachine là CANONICAL HARD GATE. RuleEngine và P3 KHÔNG override.
- RuleEngine chỉ quyết định TRONG safety envelope đã được machine cấp.
- ResponseValidator là bước BẮT BUỘC, không phải optional post-process.
- `done` chỉ emit SAU KHI persist + outbox commit thành công.
- Celery/outbox side effects chỉ dispatch SAU persist thành công.
- Frontend state mapping đọc từ SSEEvent/ChatDonePayload, KHÔNG tự suy luận.

### 3.2 Canonical Event Ordering (SSE)

**Success path:**
`thinking` → `state(session_resolved)` → `state(case_resolved)` → `state(safety_resolved)` → `token*` → `state(validated)` → `done`

**Validator reject (regenerate):**
`thinking` → states → `info(validation_regenerate)` → `token*` → `state(validated)` → `done`

**Blocked / crisis path:**
`thinking` → `state(safety_resolved)` → `token*` (safe response) → `done`

### 3.3 Persist / Emit / Async Ordering

Success path:
1. Save user message
2. Compute final validated assistant payload
3. Begin transaction
4. Persist assistant message + telemetry + transition events
5. Append `outbox_events` TRONG CÙNG transaction
6. Commit
7. Emit SSE `done`
8. Dispatcher xử lý outbox events

Failure:
- Lỗi trước persist → emit `error`, KHÔNG `done`, KHÔNG outbox
- Persist fail trong transaction → rollback ALL, KHÔNG emit `done`
- Commit ok nhưng dispatcher fail → request vẫn `done`, outbox repair job xử lý

### 3.4 Timing Targets

```
0ms:          User gửi message
0-2ms:        InputGuard
2-10ms:       Resolve identity / consent / session
10-20ms:      Resolve case + save user message
20-220ms:     P1 + P2 PARALLEL
220-260ms:    SafetyStateMachine + RuleEngine + Personalizer
260-420ms:    Load context (memory / RAG)
420-700ms:    Build P3Request + first provider chunks
700ms+:       Token stream + incremental validation
3200-3400ms:  Final validation → persist
3400ms:       Emit SSE done
3401ms+:      Dispatch outbox (async, user không đợi)
```

User-perceived: first token ~700-900ms, completed ~3-4s.

---

## 4. Django Project Structure

```
wismo_backend/
├── manage.py
├── wismo/
│   ├── settings/ (base.py, dev.py, prod.py)
│   ├── urls.py
│   ├── celery.py
│   ├── asgi.py
│   ├── db_router.py              ← VectorRouter
│   └── contracts/                ← shared types (pydantic)
│       ├── enums.py              ← 13 StrEnum classes
│       ├── p1.py, p2.py, ...     ← pipeline contracts
│       ├── sse.py, error.py      ← API contracts
│       └── version.py            ← CONTRACT_VERSIONS
│
├── apps/
│   ├── accounts/                 ← Auth, User, Consent
│   ├── chat/                     ← Orchestrator, Session, Case, Message
│   ├── counseling/               ← P1, P2, P9
│   ├── personalization/          ← PersonalizerPolicy, P6
│   ├── memory/                   ← MemoryManager, P5
│   ├── knowledge/                ← Retriever, Embedder (read from vector DB)
│   ├── llm/                      ← LLMRouter, providers
│   ├── safety/                   ← CrisisDetector, SafetyStateMachine, Validator
│   └── telemetry/                ← DailyStats, Audit, OutboxDispatcher
│
└── tests/
    ├── unit/
    └── integration/
```

---

## 5. Module Ownership

Mỗi app sở hữu 1 domain rõ ràng. App KHÔNG được sở hữu logic thuộc app khác.

| App | Sở hữu | KHÔNG sở hữu | Service entrypoints |
|-----|--------|-------------|-------------------|
| `accounts` | auth, identity, consent, profile, deletion | orchestration, case logic, RAG | AuthService, ConsentService, ProfileService |
| `chat` | session, message persistence, orchestrator, streaming, case resolution | safety policy, memory extract, provider routing | Orchestrator, SessionManager, CaseManager, PersistService |
| `counseling` | P1, P2, P9 analysis | DB ownership session/message | SituationAnalyzer, CasePhaseEvaluator |
| `personalization` | style policy, P6 rules | memory storage, consent, case persist | PersonalizerPolicy, PersonalityDetector |
| `memory` | memory lifecycle, dedup, P5 | session transport, SSE | MemoryManager, ProfileBuilder |
| `knowledge` | source/chunk metadata, retrieval, reranking | chat persist, prompt policy | Retriever, Embedder, RAGQueryBuilder |
| `llm` | provider abstraction, failover, structured parse | case policy, safety rules | LLMRouter, provider clients |
| `safety` | crisis detect, escalation, validator | session persist, general orchestration | CrisisDetector, ResponseValidator, SafetyStateMachine |
| `telemetry` | feedback, audit, metrics, alerts | decision-making cho safety/case | TelemetryService, GDPRAuditService |

---

## 6. Dependency Direction & Import Rules

### 6.1 Call Graph (top-down only)

```
views / serializers / middleware
    ↓
chat.services.orchestrator  ← ENTRY POINT duy nhất
    ↓
domain service facades (per app)
    ↓
ORM / provider clients / outbox / Celery
```

### 6.2 Allowed Imports

| Caller | Được import | CẤM import |
|--------|------------|------------|
| views/middleware | orchestrator, accounts services | memory, knowledge, llm, counseling trực tiếp |
| chat | TẤT CẢ service facades | import ngược views; raw provider clients |
| accounts | own models, telemetry facade | chat, memory, knowledge, counseling |
| counseling | llm facade, shared contracts | chat.models, memory.models trực tiếp |
| memory | accounts facade (consent), telemetry | chat.views, knowledge, provider clients |
| knowledge | own models, telemetry | chat, accounts, memory direct writes |
| llm | provider clients, contracts | BẤT KỲ business service nào |
| safety | own models, telemetry | chat views; direct write Message/Session |
| telemetry | own models, event envelopes | mutate domain state BẤT KỲ app nào |

### 6.3 Forbidden Reverse Imports (CI fail)

- accounts → chat
- memory → chat.views
- knowledge → chat / accounts
- llm → bất kỳ domain app
- telemetry → mutate state bất kỳ app
- counseling → direct write chat/memory/accounts models
- safety → direct write Message/Session/UserCase

### 6.4 Cross-App Access Rule

**Ưu tiên theo thứ tự:**
1. Pass typed contract in (app upstream resolve → pass payload xuống)
2. Expose read facade (service method read-only)
3. Publish domain event / outbox event (async reaction)
4. Promote shared enum/contract (khi 2 app cùng cần)
5. ADR exception (ghi rõ lý do, scope, review date)

**KHÔNG dùng circular import.**

### 6.5 Public Facade Requirement

Mỗi app phải expose facade ổn định:
- `accounts.facade`: resolve_identity(), get_consent_state()
- `memory.facade`: load_runtime_memory(), upsert_memory_items()
- `knowledge.facade`: retrieve_context(), disable_source()
- `safety.facade`: evaluate_safety_state(), validate_response()
- `telemetry.facade`: append_domain_event(), record_feedback()

App khác gọi qua facade — KHÔNG import helper/private module nội bộ.

---

## 7. Outbox Pattern

### 7.1 Strategy Decision

Full outbox pattern từ Phase 1. KHÔNG dùng simplified Celery fire. Lý do: mental health data cần guaranteed delivery — mất P4/P5 event = mất case context/memory = ảnh hưởng counseling quality.

### 7.2 Canonical Pattern

1. Request path commit business state
2. Ghi `outbox_events` TRONG CÙNG DB transaction
3. Response emit `done` SAU COMMIT thành công
4. Worker/dispatcher đọc outbox → enqueue Celery
5. Repair job retry `pending`/`failed` events

### 7.3 Hard Rules

- KHÔNG gọi Celery trực tiếp từ views/serializers/callback
- Request path chỉ gọi OutboxService.append()
- Event phải có `idempotency_key` ổn định
- Dispatcher: at-least-once delivery + consumer dedupe
- Event side effects PHẢI idempotent (replay = no-op)

### 7.4 Event Types

`after_turn_dispatch`, `after_terminal_turn_dispatch`, `goal_strategy_dispatch`, `journey_summary_dispatch`, `guest_attach_dispatch`, `gdpr_delete_dispatch`, `consent_withdrawn_dispatch`, `archive_restore_dispatch`, `telemetry_aggregate_dispatch`

### 7.5 Dedupe Rules

| Event | Dedupe key |
|-------|-----------|
| after_turn_dispatch | turn_id + event_type |
| goal_strategy_dispatch | case_id + strategy_version + event_type |
| journey_summary_dispatch | session_id + session_closed_at + event_type |
| guest_attach_dispatch | session_id + target_user_id + event_type |
| gdpr_delete_dispatch | account_id + delete_request_id + event_type |

---

## 8. Middleware Chain

```
Request → Nginx → Gunicorn → Django Middleware:

1. SecurityMiddleware       ← HTTPS, headers
2. SessionMiddleware        ← Django session
3. AuthMiddleware           ← Authenticate (token/session/cookie)
4. GuestMiddleware          ← Hydrate guest session context
5. ConsentMiddleware        ← Block chat nếu chưa consent
6. RateLimitMiddleware      ← Phase 2: quota check
   ↓
View (ChatMessageView, etc.)
```

ConsentMiddleware chỉ block `/api/chat/*` — exempt `/api/auth/*`, `/api/consent/*`, `/api/health/`.

---

## 9. Celery Tasks

### 9.1 After-Turn (mỗi message, parallel, ~2s)

| Task | Mục đích |
|------|---------|
| P4: case_context_accumulate | Tích lũy context vào case |
| P5: profile_facts_build | Extract facts vào memory |
| P6: personality_signal_detect | Detect tone/style signals |

### 9.2 After-Session

| Task | Mục đích |
|------|---------|
| P7: journey_summary_build | Tóm tắt journey |

### 9.3 Triggered

| Task | Trigger |
|------|---------|
| P8: conversation_title | ≥3 turns + topic rõ |
| P9: case_goal_strategy | P2 says Phase 1→2 |

### 9.4 Scheduled (Celery Beat)

| Task | Schedule |
|------|----------|
| daily_stats_generate | 1AM daily |
| archive_old_messages | Ngày 1 monthly |
| cleanup_guest_sessions | 4AM daily |
| outbox_repair_dispatch | 5 phút |
| dead_letter_repair | 2AM daily |
| s3_scan_new_files | Hourly |
| vastai_auto_scale | 5 phút |

---

## 10. Contracts Package

Đặt tại `wismo/contracts/` — shared types giữa các apps.

```
wismo/contracts/
├── enums.py        ← 13 StrEnum classes
├── p1.py           ← P1Output, EmotionSignal
├── p2.py           ← P2Output
├── rule.py         ← CounselingDecision
├── safety.py       ← GuardResult, CrisisResult, SafetyDecision
├── style.py        ← PersonalizationConfig
├── sse.py          ← SSEEvent, ChatDonePayload
├── outbox.py       ← OutboxEventEnvelope
├── error.py        ← WismoError
├── trace.py        ← TracePayload
└── version.py      ← CONTRACT_VERSIONS dict
```

**Rules:**
- Chỉ chứa contracts/enums/types — KHÔNG chứa ORM, provider, business workflow
- Type chỉ dùng trong 1 app → để local trong app, không promote lên contracts
- Promote lên contracts CHỈ KHI thật sự cross-app

Chi tiết từng contract: xem `api-contracts-spec.md`.

---

## 11. Special Workflow Ordering

### 11.1 Terminal Safety Turn (crisis/blocked)

1. Persist terminal assistant turn + crisis event
2. Append `after_terminal_turn_dispatch`
3. Commit → emit `done`
4. Worker: escalation candidate, hotline analytics

### 11.2 Guest Attach

1. OAuth/login callback resolve user identity
2. Lock current guest session (FOR UPDATE)
3. Verify guards: still guest, not attached, not closed
4. Re-assign session ownership → backfill messages → promote profile/case
5. Append `guest_attach_dispatch` + audit IN SAME transaction
6. Commit → return success
7. Fail → rollback ALL, session vẫn guest, no partial attach

### 11.3 GDPR Delete

1. Append audit `data_delete_requested`
2. Transition consent → `withdrawn_pending_delete`
3. Append `gdpr_delete_dispatch`
4. Commit → acknowledge user
5. Worker execute deletion pipeline
6. Khi complete → transition → `deleted` + completion audit

---

## 12. Architecture Enforcement

### 12.1 CI Checks

- Import-lint: CI fail nếu vi phạm call graph
- Unit tests cho public facades: facade ổn định, contracts parse được
- No private cross-app imports: cấm `from apps.x.services.y import _internal`

### 12.2 Review Checklist (mỗi PR)

- App nào ownership?
- Có import ngược không?
- Có type chung mới cần promote lên contracts không?
- Outbox event mới có idempotency key?
- Service method mới có typed input/output contract?
