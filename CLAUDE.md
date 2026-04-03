# WISMO Backend — Claude Code Rules

## Project
- Django 5.2 LTS + DRF + Celery + Redis + PostgreSQL 16 + pgvector
- Python 3.11
- Monorepo: 9 Django apps
  - accounts
  - chat
  - counseling
  - personalization
  - memory
  - knowledge
  - llm
  - safety
  - telemetry

## Purpose
File này hướng dẫn Claude Code khi **thực thi một active change đã được OpenSpec tạo và Owner duyệt/chỉnh**.

Claude không tự quyết định roadmap, không tự chia lại ownership giữa workers, và không tự mở rộng scope ngoài change hiện tại.

Claude phải làm theo:
1. `openspec/changes/<change-name>/proposal.md`
2. `openspec/changes/<change-name>/design.md`
3. `openspec/changes/<change-name>/tasks.md`
4. các `Spec References` được liệt kê trong proposal/design

Nếu Owner đã chỉnh proposal/design/tasks sau khi OpenSpec sinh ra, **bản đã chỉnh là source of truth**.

---

## Execution Boundary

### Claude phù hợp cho
- Orchestrator / canonical request lifecycle
- SSE streaming / reconnect / recovery
- Cross-service coordination
- Multi-file integration
- Auth flow phức tạp
- Outbox dispatcher / repair / dead-letter handling
- P1 / P2 analyzers
- PromptBuilder integration vào orchestrator
- Memory retrieval + Personalizer integration
- Guest attach transaction
- RAG retriever / reranker integration phía backend
- Eval runner / infra ops scripts / kill switches

### Claude không tự nhận
- Boilerplate CRUD đơn giản nếu tasks không yêu cầu
- Refactor ngoài scope change
- Cleanup tiện tay
- Tự ý làm thay phần isolated module đã thuộc Codex
- Tự ý đổi contract, build order, ownership hoặc spec structure

---

## Workflow Rules
- Trước khi code, đọc `proposal.md`, `design.md`, `tasks.md`.
- Chỉ load các domain spec được liệt kê trong `Spec References`.
- Không load toàn bộ full spec nếu change đã chỉ rõ domain specs cần đọc.
- Code theo checklist trong `tasks.md`.
- Chạy test đúng scope trước khi check xong từng task quan trọng.
- Chỉ sửa các file nằm trong active change đã được duyệt.
- Nếu đang làm mà phát sinh nhu cầu sửa file ngoài scope, dừng và báo để update change/task trước khi tiếp tục.
- Không tự ý gộp nhiều changes vào một lần implement.
- Nếu proposal/tasks lệch với codebase hiện tại, ưu tiên:
  1. spec/architecture
  2. proposal/design/tasks đã duyệt
  3. code cũ

---

## Spec Reference Rules

### Full spec
- Full spec: `docs/WISMO_Project_Specification_v18.md`
- KHÔNG load toàn bộ full spec nếu change đã chỉ rõ domain specs cần đọc.

### Domain spec ownership
- `architecture/spec.md`
  - orchestrator
  - canonical request lifecycle
  - session flow
  - outbox
  - middleware chain
  - trace.v1
  - dual DB
  - guest attach
- `api-contracts/spec.md`
  - contract index
  - SSE events
  - trace envelope
  - build order
- `prompts/spec.md`
  - P1–P9 prompt text
  - PromptBuilder
  - METHOD_CONFIG
  - RuleEngine
- `llm/spec.md`
  - providers
  - router
  - circuit breaker
  - ResponseValidator
  - safe fallbacks
  - eval framework
- `safety/spec.md`
  - crisis detection
  - InputGuard
  - Safety State Machine
  - contraindication
  - safety constraints
- `counseling/spec.md`
  - phases
  - methods
  - special counseling rules
- `memory/spec.md`
  - memory item lifecycle
  - retrieval
  - cleanup
- `user-profile/spec.md`
  - profile dimensions
  - P5/P6-facing semantics
- `case-management/spec.md`
  - case lifecycle
  - case status rules
- `consent/spec.md`
  - GDPR consent flow
  - attach coupling
  - deletion/export rules
- `database/spec.md`
  - models / tables / routing
- `telemetry/spec.md`
  - audit / metrics / delivery state
- `infrastructure/spec.md`
  - backup
  - kill switches
  - incident ops

### Mandatory interpretation rules
- Không tìm RuleEngine trong `safety/spec.md`.
- Không tìm ResponseValidator trong `safety/spec.md`.
- Không tìm P1/P2/P3 full prompt text trong `counseling/spec.md`.
- RuleEngine đọc từ `prompts/spec.md`.
- ResponseValidator đọc từ `llm/spec.md`.

---

## Architecture Rules

### Canonical request lifecycle
- Orchestrator là entry point duy nhất cho chat turn.
- Views/serializers/SSE endpoints phải thin: auth, validation, transport, response envelope.
- Business logic phải nằm trong services layer.
- Cross-app access qua service boundary/facade, không query model trực tiếp xuyên app.
- Celery tasks chỉ điều phối async work, không chứa domain business logic lõi.

### Persistence / emit ordering
- Không emit `done` trước khi final assistant turn được persist thành công.
- `done.final_text` là source of truth.
- Token preview không phải canonical business result.
- Nếu final persist fail thì không emit `done`.
- Async side effects phụ thuộc turn phải đi sau persist/outbox boundary.

### P1 / P2 concurrency
- P1 và P2 chạy song song khi canonical flow yêu cầu.
- Không tự biến thành sequential flow nếu spec không cho phép.

### Outbox pattern
- Không gọi Celery trực tiếp từ request path cho side effects business.
- Dùng outbox-first pattern.
- Dispatcher / repair / dead-letter phải tôn trọng ordering và idempotency.

### Dual database
- `postgres-app` (5432): OLTP cho app models
- `postgres-vector` (5433): vector models
- `VectorRouter` xử lý routing
- Không bypass pattern kiến trúc bằng query/vector access tùy tiện

### Kill switches
- `disable_rag`
- `disable_llm`
- `disable_new_sessions`
- `read_only_mode`
- `maintenance`

Không hardcode bypass. Luôn đi qua service chuẩn.

### Trace / correlation
- Mọi flow orchestration / streaming / outbox / validator phải preserve `trace.v1`.
- Không làm mất correlation fields giữa request, SSE, persistence, telemetry, provider calls, recovery path.

---

## Code Standards
- Python 3.11, PEP 8
- Formatter/lint: `ruff`
- Type hints bắt buộc cho function signatures
- Import order:
  1. stdlib
  2. third-party
  3. `wismo.contracts`
  4. app imports

### Naming
- Classes: `PascalCase`
- Functions: `snake_case`
- Variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Files/modules: `snake_case`

Tên phải tự giải thích, tránh tên mơ hồ như `x`, `data`, `obj`, `tmp` khi có thể đặt rõ nghĩa.

### Docstrings
- Bắt buộc cho class và function public.
- Với service quan trọng, docstring phải nêu:
  - purpose
  - inputs
  - returns
  - side effects nếu có
  - idempotency / safety assumptions nếu có

### Comments
- Chỉ comment để giải thích **tại sao**
- Không comment điều hiển nhiên
- Với logic dài, dùng section separators hợp lý

### Readability
- Ưu tiên code rõ ràng, chia phase/bước mạch lạc
- Early return cho invalid/error cases
- Không dồn nhiều nhánh logic vào một dòng

---

## Contracts
- `wismo/contracts/` là source of truth cho shared data types
- Nếu contract đã tồn tại thì phải dùng contract đó
- Không tự tạo dataclass / TypedDict / schema khác chỉ vì tiện
- Nếu change đụng contract:
  - update tests liên quan
  - kiểm tra blast radius
  - xử lý versioning nếu spec yêu cầu

---

## Error Handling
- Custom exceptions kế thừa `WismoError`
- Không bare `except`
- Log trước khi raise lại ở error path quan trọng
- Provider failures phải có fallback hoặc failure path rõ ràng
- Không để external failure làm crash toàn pipeline nếu spec yêu cầu graceful degradation

---

## Testing Rules
- Framework: `pytest`, `pytest-django`, `pytest-asyncio`
- Mỗi service/module chính cần test file tương ứng
- Integration change phải có integration tests đúng scope
- Mock external systems thôi:
  - LLM API
  - S3
  - external HTTP
- Không mock bừa internal services trong integration tests
- Dùng factory-boy khi phù hợp

### Safety / validator / streaming / outbox
Với các change loại này:
- chạy regression pack liên quan
- không report done nếu regression quan trọng còn fail

---

## Safety Critical Rules
- Đọc `safety/spec.md` trước khi code crisis / contraindication / safety state machine
- Đọc `prompts/spec.md` khi code P1 / P2 / PromptBuilder / RuleEngine-related integration
- Đọc `llm/spec.md` khi code validator / regeneration / failover / safe fallback / eval
- Safety State Machine là hard-rule runtime gate
- ResponseValidator phải nằm đúng chỗ trong canonical flow
- Không bao giờ đưa user-facing text dùng clinical language bị cấm
- Crisis logic phải tôn trọng multilingual rules nếu spec yêu cầu

---

## Definition of Done
Chỉ report done khi:
- tất cả checklist item trong `tasks.md` đã xong
- tests liên quan đã pass
- lint/format sạch
- không sửa ngoài scope
- code bám đúng spec refs
- không vi phạm canonical architecture