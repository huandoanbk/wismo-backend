# Tasks: cc-contracts-models-ci

## Checklist

### 1. Tạo contract modules
Đọc `design.md` để lấy đầy đủ fields cho mỗi contract.

- [x] 1.1 Tạo `wismo/contracts/p1.py` — `P1Output` + nested: `EmotionSignal`, `SafetySignal`, `ContentSignal`, `SessionEndingSignal`, `ContraindicationSignal`, `ScopeSignal`
- [x] 1.2 Tạo `wismo/contracts/p2.py` — `P2Output` + nested: `ContextAssessment`, `RecommendedAction`
- [x] 1.3 Tạo `wismo/contracts/rule.py` — `RuleDecision`
- [x] 1.4 Tạo `wismo/contracts/safety.py` — `GuardResult`, `CrisisResult`, `SafetyDecision`, `SafetyConstraints`
- [x] 1.5 Tạo `wismo/contracts/style.py` — `PersonalizationConfig`
- [x] 1.6 Tạo `wismo/contracts/sse.py` — `SSEEvent`, `ChatDonePayload`, `ChatSendRequest`
- [x] 1.7 Tạo `wismo/contracts/outbox.py` — `OutboxEventEnvelope`
- [x] 1.8 Tạo `wismo/contracts/error.py` — `WismoError`
- [x] 1.9 Tạo `wismo/contracts/trace.py` — `TracePayload`
- [x] 1.10 Tạo `wismo/contracts/case.py` — `CaseTransitionEvent`

### 2. Update exports
- [x] 2.1 Update `wismo/contracts/__init__.py` để re-export các public top-level contracts
- [x] 2.2 Không export quá tay các nested helper models nếu downstream chưa cần import trực tiếp

### 3. Serialization tests
- [x] 3.1 Tạo `tests/test_contracts/test_serialization.py`
- [x] 3.2 Thêm các tests sau:
  - `test_p1output_roundtrip`
  - `test_p2output_roundtrip`
  - `test_rule_decision_roundtrip`
  - `test_safety_decision_roundtrip`
  - `test_guard_result_roundtrip`
  - `test_sse_event_schema_version`
  - `test_chat_done_payload_roundtrip`
  - `test_chat_send_request_roundtrip`
  - `test_outbox_envelope_has_idempotency_key`
  - `test_wismo_error_roundtrip`
  - `test_trace_payload_roundtrip`
  - `test_contract_versions_13_entries`

### 4. Validation tests
- [x] 4.1 Thêm validation tests vào `test_serialization.py`
- [x] 4.2 Dùng `pytest.raises(ValidationError)` cho Pydantic v2 validation paths
- [x] 4.3 Thêm các tests sau:
  - `test_p1_severity_must_be_0_to_10`
  - `test_p1_confidence_must_be_0_to_1`
  - `test_chat_send_content_not_empty`
  - `test_chat_send_content_max_2000`

### 5. Additional coverage
- [x] 5.1 Thêm `test_case_transition_event_roundtrip`
- [x] 5.2 Thêm `test_personalization_config_roundtrip`

### 6. CI / tooling
- [x] 6.1 Tạo `.github/workflows/ci.yml` cho contracts scope
- [x] 6.2 Tạo hoặc update config lint/type-check theo convention repo hiện có
- [x] 6.3 Dùng cùng Python version với backend repo thực tế
- [x] 6.4 Dependency management phải follow convention repo hiện có, không ép workflow mới

### 7. Import checks
- [x] 7.1 Verify không có import từ `apps.*` hoặc `django.*`

## Verify commands cuối cùng

```bash
# 1. Không có import vi phạm
grep -r "from apps\." wismo/contracts/ && echo "FAIL" || echo "OK"
grep -r "from django\." wismo/contracts/ && echo "FAIL" || echo "OK"

# 2. Smoke test schema_version
python -c "
from wismo.contracts.sse import SSEEvent
from wismo.contracts.error import WismoError
from wismo.contracts.outbox import OutboxEventEnvelope
assert SSEEvent(type='thinking', request_id='test-id').schema_version == 'sse.v1'
assert WismoError(error_code='E', error_category='system', http_status=500, user_message='x').schema_version == 'error.v1'
assert OutboxEventEnvelope(idempotency_key='k', event_type='evt', created_at='2026-01-01T00:00:00Z').schema_version == 'outbox.v1'
print('OK')
"

# 3. Serialization + validation tests
pytest tests/test_contracts/test_serialization.py -v

# 4. Type check
mypy wismo/contracts/ --strict

# 5. Lint clean
ruff check wismo/contracts/
```

## Definition of Done
- [x] `pytest tests/test_contracts/` — **41 tests passed**
  - F2a: 18 tests
  - F2b: 23 tests
- [x] `mypy wismo/contracts/ --strict` — no errors
- [x] `ruff check wismo/contracts/` — clean
- [x] Không có import từ `apps.*` hoặc `django.*`
- [x] `CONTRACT_VERSIONS` có đúng 13 entries
- [ ] CI pipeline green sau khi push
- [ ] PR với branch `foundation/contracts-models`
- [ ] Merge → main → tag `v0.0.3-contracts`
