# Change Proposal: cx-contracts-enums

## Why
WISMO backend cần một lớp shared enums canonical để mọi app và service dùng cùng một ngôn ngữ trạng thái, thay vì tự định nghĩa string literals rải rác. Nếu không đóng băng lớp này sớm, các task tiếp theo như database models, P1/P2 analyzers, safety state machine, SSE mapping, và tracing sẽ dễ drift semantics, khó type-check, và khó viết regression tests.

Task này tập trung vào phần foundation nhỏ nhất nhưng có giá trị cao nhất:
- canonical enums cho shared vocabulary
- contract version registry cho immediate-need contracts
- regression tests để ngăn breaking changes

## What Changes
This change creates a lightweight `wismo/contracts/` foundation package containing:
- `enums.py` với 15 canonical enums
- `version.py` với `CONTRACT_VERSIONS` (13 immediate-need contract versions) và `get_contract_version()`
- `__init__.py` re-export public enums và version utilities
- enum regression tests và version registry tests

This change does **not** create Pydantic contract models yet. Actual data models sẽ được tạo ở task kế tiếp `cc-contracts-models-ci`.

## Scope
Included:
- `wismo/contracts/__init__.py`
- `wismo/contracts/enums.py`
- `wismo/contracts/version.py`
- `tests/test_contracts/__init__.py`
- `tests/test_contracts/test_enums.py`

Excluded:
- Pydantic models như `P1Output`, `P2Output`, `RuleDecision`, `SafetyDecision`, `SSEEvent`, v.v.
- CI pipeline setup
- Django model integration
- business logic, state machines, or serializer workflows

## Canonical Enums for F2a
This change freezes the following 15 enums as canonical shared vocabulary:
1. `ConversationSafetyState`
2. `CaseStatus`
3. `CasePhase`
4. `CounselingMethod`
5. `CounselingSubmode`
6. `EmotionTag`
7. `EmotionShift`
8. `Sensitivity`
9. `ConsentState`
10. `SessionState`
11. `OutboxDeliveryState`
12. `ReadinessLevel`
13. `RiskLevel`
14. `OutOfScopeType`
15. `Intent`

## Contract Version Registry
F2a also creates an immediate-need contract version registry with 13 entries for the contracts expected to be implemented in near-term tasks:
- `P1Output`
- `P2Output`
- `RuleDecision`
- `SafetyDecision`
- `GuardResult`
- `SSEEvent`
- `ChatDonePayload`
- `ChatSendRequest`
- `OutboxEventEnvelope`
- `WismoError`
- `TracePayload`
- `CaseTransitionEvent`
- `PersonalizationConfig`

This registry is intentionally limited to near-term implementation needs and does not attempt to cover every future contract in the project.

## Dependencies
- F1 project/repo setup must already exist

## Success Criteria
- `wismo/contracts/` can be imported without touching `apps.*` or `django.*`
- all 15 enums serialize cleanly as strings
- enum regression tests lock exact values, not just counts
- version registry contains exactly 13 entries
- `pytest tests/test_contracts/test_enums.py -v` passes with 18 tests

## Downstream Users
Outputs from this change are expected to be used by:
- `cc-contracts-models-ci` (F2b)
- `cx-database-models` (F3)
- Slice 1 orchestration/SSE tasks
- Slice 3 safety, P1, P2, and rule tasks
