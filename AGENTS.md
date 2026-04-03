# WISMO Backend — Codex Rules

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
File này hướng dẫn Codex khi **thực thi một active change đã được OpenSpec tạo và Owner duyệt/chỉnh**.

Codex không tự quyết định roadmap, không tự chia lại ownership giữa workers, và không tự mở rộng scope ngoài change hiện tại.

Codex phải làm theo:
1. `openspec/changes/<change-name>/proposal.md`
2. `openspec/changes/<change-name>/design.md`
3. `openspec/changes/<change-name>/tasks.md`
4. các `Spec References` được liệt kê trong proposal/design

Nếu Owner đã chỉnh proposal/design/tasks sau khi OpenSpec sinh ra, **bản đã chỉnh là source of truth**.

---

## Execution Boundary

### Codex phù hợp cho
- Database models + migrations
- Serializers / views / middleware scope hẹp
- CRUD/service modules độc lập
- State machine modules cô lập
- Rule-based modules cô lập
- ResponseValidator module
- LLM provider modules / router / circuit breaker
- Celery task modules cho P4/P5/P6 theo spec
- Telemetry jobs / archive / monitoring views
- Unit tests / integration tests / regression packs
- CI pipeline / scaffolding / config updates
- Performance/load tests

### Codex không tự nhận
- Orchestrator logic
- SSE orchestration end-to-end
- Cross-service coordination nhiều lớp
- Multi-file refactor lớn
- Auth flows phức tạp
- Outbox dispatcher / dead-letter / repair orchestration
- Guest attach transaction
- RAG integration vào orchestrator
- Cleanup/refactor ngoài active change

---

## Workflow Rules
- Nhận task → đọc `proposal.md`, `design.md`, `tasks.md`
- Chỉ load đúng domain specs được list trong `Spec References`
- Không load toàn bộ full spec nếu không cần
- Code theo từng checkbox trong `tasks.md`
- Chạy test/lint đúng scope trước khi check item done
- Chỉ sửa các file nằm trong active change đã được duyệt
- Nếu task phát sinh cần đụng file ngoài scope, dừng và báo để update change/task
- Không opportunistic refactor
- Không tự ý sửa orchestrator hoặc integration lớn nếu change không giao

---

## Spec Reference Rules

### Full spec
- Full spec: `docs/WISMO_Project_Specification_v18.md`
- Chỉ dùng khi change yêu cầu; bình thường ưu tiên domain specs

### Domain spec ownership
- `architecture/spec.md`
  - session flow
  - outbox boundary
  - trace.v1
  - dual DB
  - canonical runtime rules ở mức cần cho isolated module
- `api-contracts/spec.md`
  - SSE / trace / canonical contracts
- `prompts/spec.md`
  - RuleEngine
  - P1–P9 prompt definitions
  - PromptBuilder configs
  - METHOD_CONFIG
  - P4 / P5 / P6 prompts
- `llm/spec.md`
  - providers
  - router
  - circuit breaker
  - ResponseValidator
  - safe fallbacks
  - eval framework
- `safety/spec.md`
  - InputGuard
  - crisis rules
  - Safety State Machine
  - contraindication
  - safety constraints
- `counseling/spec.md`
  - phases / methods / special counseling rules
- `consent/spec.md`
  - consent flow + middleware + ConsentService
- `database/spec.md`
  - tables / models / db router
- `memory/spec.md`
  - memory items / retrieval / cleanup
- `user-profile/spec.md`
  - P5 / P6 related user profile semantics
- `case-management/spec.md`
  - case lifecycle / context structures
- `telemetry/spec.md`
  - stats / archive / alerting / outbox delivery states
- `infrastructure/spec.md`
  - CI / monitoring / SLOs
  - backup / ops khi task yêu cầu

### Mandatory interpretation rules
- Không tìm RuleEngine trong `safety/spec.md`.
- Không tìm ResponseValidator trong `safety/spec.md`.
- RuleEngine đọc từ `prompts/spec.md`.
- ResponseValidator đọc từ `llm/spec.md`.
- Không tìm P1/P2/P3 full prompt text trong `counseling/spec.md`.

---

## Important Scope Notes

### Safety State Machine
Codex **được implement thật**, không phải chỉ scaffold.
Nhưng phải giữ nó là isolated module theo spec:
- transition table
- guards
- constraints object
- contraindication handling
- tests

Không tự ý biến phần này thành cross-service orchestration refactor.

### RuleEngine + ResponseValidator
Codex có thể implement:
- `rule_engine.py`
- `response_validator.py`

Nhưng phải đọc spec đúng nguồn:
- RuleEngine → `prompts/spec.md`
- ResponseValidator → `llm/spec.md`

### P4 / P5 / P6 tasks
Codex có thể implement task modules và prompt wrappers theo spec change.
Không tự ý kéo sang request-path orchestration hoặc outbox dispatcher logic nếu change không yêu cầu.

### LLM providers / router / circuit breaker
Codex có thể làm module độc lập + tests.
Không tự ý sửa orchestrator integration ngoài scope change.

---

## Architecture Rules
- Views/serializers phải thin
- Business logic nằm trong services/modules phù hợp
- Không query model trực tiếp xuyên app nếu spec đã định service boundary
- Không import private internals từ app khác
- Không đặt Celery side effects trực tiếp vào request business success path
- Nếu change liên quan persist/outbox/session, phải tôn trọng outbox-first boundary
- Không làm mất `trace.v1` envelope ở những module chạm vào request/stream/persist/telemetry boundary

### Dual database
- `postgres-app` (5432): app models
- `postgres-vector` (5433): vector models
- `VectorRouter` xử lý ORM routing
- Migration phải đúng DB target
- Không nhầm app DB và vector DB

---

## Code Standards
- Python 3.11
- PEP 8
- Formatter/lint: `ruff`
- Type hints bắt buộc cho function signatures

### Import order
1. stdlib
2. third-party
3. `wismo.contracts`
4. app imports

### Naming
- Classes: `PascalCase`
- Functions: `snake_case`
- Variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Files: `snake_case`

Tên phải rõ nghĩa, tránh tên mơ hồ hoặc 1 ký tự nếu không cần.

### Docstrings
- Bắt buộc cho class và function public
- Với service/module chính, docstring nên nêu:
  - mục đích
  - input/output
  - persistence side effects nếu có
  - assumptions quan trọng

### Comments
- Giải thích tại sao, không giải thích cái hiển nhiên
- Section separators cho logic dài
- Không lạm dụng comment

### Readability
- Từng bước rõ ràng
- Early return cho error cases
- Không dồn logic phức tạp vào một dòng
- Với state machine / validator, ưu tiên cấu trúc đọc được và testable

---

## Contracts
- `wismo/contracts/` là source of truth
- Nếu contract đã có, bắt buộc dùng contract đó
- Không tự tạo kiểu dữ liệu riêng chỉ vì tiện
- Nếu change đụng contract:
  - update tests
  - kiểm tra versioning impact
  - không đổi bừa shape response/request

---

## Error Handling
- Custom exceptions kế thừa `WismoError`
- Không bare `except`
- Log trước khi raise ở error path quan trọng
- Provider/external dependency failures phải có failure path rõ
- Không swallow exception âm thầm

---

## Testing Rules
- Framework: `pytest`, `pytest-django`
- Dùng `pytest-asyncio` nếu module/task cần async test
- Mỗi service/module chính cần test file tương ứng
- Mock external systems thôi
- Unit tests cho isolated modules là bắt buộc
- Integration/regression tests phải đúng scope change

### Safety / validator / providers / state machine
Với các change loại này:
- phải có regression coverage phù hợp
- không report done nếu safety regression liên quan chưa pass
- không bỏ qua test vì “module đã đơn giản”

### Migrations / models
- Kiểm tra migration target đúng DB
- Kiểm tra model indexes / constraints / idempotency assumptions theo spec

---

## Definition of Done
Chỉ report done khi:
- tất cả checklist trong `tasks.md` đã xong
- tests liên quan đã pass
- lint/format sạch
- không sửa ngoài scope
- module bám đúng domain spec đã chỉ định
- không lấn sang orchestration/refactor không được giao