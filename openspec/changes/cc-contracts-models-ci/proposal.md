# Proposal: cc-contracts-models-ci

## Intent
Tạo các Pydantic contract models dùng chung cho WISMO backend và thiết lập CI scope dành riêng cho contracts.

Contracts trong task này là typed data shapes cho inter-app communication. Chúng không chứa business workflow, không import `apps.*` hoặc `django.*`, và phải đủ ổn định để các tasks gần nhất có thể dùng ngay.

## Scope
- 10 contract modules trong `wismo/contracts/`
- Serialization round-trip tests và validation tests cho contracts cốt lõi
- CI pipeline cho contracts scope: ruff, mypy, pytest
- Update `wismo/contracts/__init__.py` để re-export public contracts

## Out of Scope
- Các future contracts chưa cần ngay cho implementation gần nhất, ví dụ:
  - `P3Request`
  - `P3ValidatedResponse`
  - `P4ExtractionResult`
  - `MemoryItemPayload`
  - `P6PersonalitySignalResult`
  - `GoalStrategyPayload`
  - `CrisisEventPayload`
- Business logic, orchestration logic, database models, Django integration
- Full-repo CI ngoài phạm vi contracts

## Immediate Need Rationale
Task này chỉ đóng gói các contracts cần ngay để unblock:
- F3 database models (import enums và một phần contracts liên quan case flow)
- S1 orchestrator / SSE flow
- S3 safety flow
- S3 P1/P2/rule flow

## Dependencies
- **F2a merged** với:
  - 15 enums canonical trong `wismo/contracts/enums.py`
  - `CONTRACT_VERSIONS` immediate-need registry trong `wismo/contracts/version.py`

## Output sẽ được dùng bởi
- **S1.6** `cc-orchestrator-sse-fallback` — `SSEEvent`, `ChatDonePayload`
- **S3.1** `cc-input-guard-crisis` — `GuardResult`, `CrisisResult`
- **S3.2** `cx-safety-state-machine` — `SafetyDecision`
- **S3.4** `cc-p1-situation-analyzer` — `P1Output`
- **S3.5** `cc-p2-phase-evaluator` — `P2Output`
- **Rule / validator / telemetry paths** — `RuleDecision`, `WismoError`, `TracePayload`

## Success Criteria
- Public contract models tồn tại và import được từ `wismo.contracts`
- Contract serialization round-trip pass cho các models cốt lõi
- Validation constraints cốt lõi được enforce bởi tests
- `ruff`, `mypy`, `pytest` chạy xanh trong contracts scope
