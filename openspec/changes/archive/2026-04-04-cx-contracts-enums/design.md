# Design: cx-contracts-enums

## Overview
This change creates the smallest stable contract foundation for WISMO backend:
- shared enums in `wismo/contracts/enums.py`
- a lightweight version registry in `wismo/contracts/version.py`
- a package export surface in `wismo/contracts/__init__.py`
- regression tests in `tests/test_contracts/test_enums.py`

The design goal is portability and stability, not completeness. This package must stay framework-independent so downstream modules can import it safely in Django, Celery, CLI scripts, tests, and pure Python contexts.

## File Structure

```text
wismo-backend/
├── wismo/
│   └── contracts/
│       ├── __init__.py
│       ├── enums.py
│       └── version.py
└── tests/
    └── test_contracts/
        ├── __init__.py
        └── test_enums.py
```

## Design Principles

### 1. Framework Independence
`wismo/contracts/` must not import:
- `apps.*`
- `django.*`
- ORM models
- service modules
- workflow/state machine code

This ensures the contracts package stays import-safe in any execution context.

### 2. Canonical String Serialization
All enums must use:

```python
from enum import Enum

class ExampleEnum(str, Enum):
    VALUE = "value"
```

Using `str, Enum` ensures JSON serialization is stable and compatible across API, tracing, testing, and future Pydantic models.

### 3. Freeze Exact Values
Tests must lock exact enum values using set equality or exact ordered assertions where relevant. The purpose is to block accidental renames like:
- `active` -> `Active`
- `RELATED` -> `related`
- `dead_letter` -> `dead-letter`

### 4. Keep Version Registry Lightweight
`version.py` is only a registry for immediate-need contract versions. It is not the full future contract catalog of the project.

## enums.py

### Canonical Enum Set
`enums.py` defines exactly these 15 enums:
- `ConversationSafetyState`
- `CaseStatus`
- `CasePhase`
- `CounselingMethod`
- `CounselingSubmode`
- `EmotionTag`
- `EmotionShift`
- `Sensitivity`
- `ConsentState`
- `SessionState`
- `OutboxDeliveryState`
- `ReadinessLevel`
- `RiskLevel`
- `OutOfScopeType`
- `Intent`

### Notes on Meaning
- `CaseStatus` includes both `inactive` and `archived`; they are semantically distinct.
- `CounselingMethod` uses runtime-granular methods (`ASK`, `REFLECT`, etc.), even if higher-level docs may still describe `INQUIRY` conceptually.
- `EmotionShift` is included as a canonical shared enum and is intentionally frozen as part of F2a.
- `Intent` is uppercase string-based because it is expected to be consumed by analyzers, rules, and API-adjacent layers.

## version.py

### CONTRACT_VERSIONS
`version.py` contains a dictionary with exactly 13 entries:

```python
CONTRACT_VERSIONS = {
    'P1Output': 'p1.v1',
    'P2Output': 'p2.v1',
    'RuleDecision': 'rule.v1',
    'SafetyDecision': 'safety.v1',
    'GuardResult': 'guard.v1',
    'SSEEvent': 'sse.v1',
    'ChatDonePayload': 'chat-done.v1',
    'ChatSendRequest': 'chat-send.v1',
    'OutboxEventEnvelope': 'outbox.v1',
    'WismoError': 'error.v1',
    'TracePayload': 'trace.v1',
    'CaseTransitionEvent': 'case-transition.v1',
    'PersonalizationConfig': 'style.v1',
}
```

### Helper Function
The file also exposes:

```python
def get_contract_version(contract_name: str) -> str:
    if contract_name not in CONTRACT_VERSIONS:
        raise KeyError(f"Unknown contract: {contract_name}")
    return CONTRACT_VERSIONS[contract_name]
```

## __init__.py
The package root re-exports:
- all 15 enums
- `CONTRACT_VERSIONS`
- `get_contract_version`

This makes downstream imports ergonomic:

```python
from wismo.contracts import CaseStatus, Intent, CONTRACT_VERSIONS
```

## Testing Strategy

### Enum Regression Tests
`tests/test_contracts/test_enums.py` should include 15 exact-value tests, one per enum.

Examples:

```python
def test_case_status_values_exact():
    expected = {'active', 'progressing', 'paused', 'stalled', 'resolved', 'inactive', 'archived'}
    actual = {s.value for s in CaseStatus}
    assert actual == expected
```

### Version Registry Tests
Add 3 registry tests:
- `test_contract_versions_13_entries`
- `test_get_contract_version_p1`
- `test_get_contract_version_unknown_raises`

### Import Smoke Test
Verify the package can be imported cleanly:

```bash
python -c "from wismo.contracts import CaseStatus, Intent, CONTRACT_VERSIONS; print('OK')"
```

## Verify Commands

```bash
grep -r "from apps\." wismo/contracts/ && echo "FAIL" || echo "OK"
grep -r "from django\." wismo/contracts/ && echo "FAIL" || echo "OK"
python -c "from wismo.contracts import CaseStatus, Intent, CONTRACT_VERSIONS; print('OK')"
pytest tests/test_contracts/test_enums.py -v
```

## Definition of Done
- exactly 15 canonical enums exist in `wismo/contracts/enums.py`
- exactly 13 entries exist in `CONTRACT_VERSIONS`
- `get_contract_version()` behaves correctly for known and unknown names
- `pytest tests/test_contracts/test_enums.py -v` passes with 18 tests
- no imports from `apps.*` or `django.*`
- `wismo/contracts/` is safe to import in plain Python context
