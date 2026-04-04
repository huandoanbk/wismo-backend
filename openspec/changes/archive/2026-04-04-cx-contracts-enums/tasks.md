# Tasks: cx-contracts-enums

## 1. Create contracts package surface
- [x] Create `wismo/contracts/__init__.py`
- [x] Create `wismo/contracts/enums.py`
- [x] Create `wismo/contracts/version.py`
- [x] Re-export all 15 enums from package root
- [x] Re-export `CONTRACT_VERSIONS` and `get_contract_version`

## 2. Implement canonical enums
- [x] Add `ConversationSafetyState`
- [x] Add `CaseStatus`
- [x] Add `CasePhase`
- [x] Add `CounselingMethod`
- [x] Add `CounselingSubmode`
- [x] Add `EmotionTag`
- [x] Add `EmotionShift`
- [x] Add `Sensitivity`
- [x] Add `ConsentState`
- [x] Add `SessionState`
- [x] Add `OutboxDeliveryState`
- [x] Add `ReadinessLevel`
- [x] Add `RiskLevel`
- [x] Add `OutOfScopeType`
- [x] Add `Intent`
- [x] Ensure every enum uses `class Xxx(str, Enum)`
- [x] Ensure each enum value matches the canonical string exactly

## 3. Implement version registry
- [x] Add `CONTRACT_VERSIONS` with exactly 13 entries
- [x] Add `get_contract_version(contract_name: str) -> str`
- [x] Ensure unknown contract names raise `KeyError`

## 4. Add tests
- [x] Create `tests/test_contracts/__init__.py`
- [x] Create `tests/test_contracts/test_enums.py`
- [x] Add 15 exact-value regression tests, one for each enum
- [x] Add `test_contract_versions_13_entries`
- [x] Add `test_get_contract_version_p1`
- [x] Add `test_get_contract_version_unknown_raises`
- [x] Use exact set equality in regression tests; do not only test counts

## 5. Verify package independence
- [x] Confirm no imports from `apps.*`
- [x] Confirm no imports from `django.*`
- [x] Confirm `wismo.contracts` imports cleanly in plain Python

## 6. Final verification
- [x] Run `pytest tests/test_contracts/test_enums.py -v` and confirm 18 tests pass
- [x] Run grep checks for forbidden imports
- [x] Run import smoke test

## Suggested Verify Commands

```bash
grep -r "from apps\." wismo/contracts/ && echo "FAIL" || echo "OK"
grep -r "from django\." wismo/contracts/ && echo "FAIL" || echo "OK"
python -c "from wismo.contracts import CaseStatus, Intent, CONTRACT_VERSIONS; print('OK')"
pytest tests/test_contracts/test_enums.py -v
```

## Definition of Done
- [x] `wismo/contracts/enums.py` contains exactly 15 canonical enums
- [x] `wismo/contracts/version.py` contains exactly 13 contract version entries
- [x] `pytest tests/test_contracts/test_enums.py -v` passes with 18 tests
- [x] no `apps.*` or `django.*` imports exist in `wismo/contracts/`
- [x] package root exports enums and version helpers cleanly
- [x] branch is ready for PR as `foundation/contracts-enums`
