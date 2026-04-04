## ADDED Requirements

### Requirement: Contracts package provides canonical shared enums
The system SHALL provide a framework-independent `wismo/contracts/` package containing canonical shared enums used across backend modules.

#### Scenario: Contracts package exists as plain Python import surface
- **GIVEN** the backend repository contains the contracts foundation
- **WHEN** a developer imports `wismo.contracts`
- **THEN** the package imports successfully in plain Python context
- **AND** it does not require Django app initialization

#### Scenario: Contracts package does not import application modules
- **GIVEN** files under `wismo/contracts/`
- **WHEN** static analysis or grep checks are run
- **THEN** there are no imports from `apps.*`
- **AND** there are no imports from `django.*`

### Requirement: Canonical enums use string-backed Enum pattern
The system SHALL define canonical enums using `class Xxx(str, Enum)` so values serialize consistently as strings.

#### Scenario: Enum classes use string-backed enum inheritance
- **GIVEN** `wismo/contracts/enums.py`
- **WHEN** canonical enums are defined
- **THEN** each enum uses `str, Enum` inheritance
- **AND** enum values serialize as strings in Python and JSON contexts

### Requirement: Contracts package freezes 15 canonical enums
The system SHALL define exactly 15 canonical enums in `wismo/contracts/enums.py` for immediate shared backend vocabulary.

#### Scenario: ConversationSafetyState has 7 exact values
- **GIVEN** `ConversationSafetyState`
- **WHEN** its values are enumerated
- **THEN** the exact set is `NORMAL`, `GUARDED`, `MODERATE_RISK_SAFE_ONLY`, `HIGH_RISK_LISTEN_ONLY`, `CRISIS_ONLY`, `BLOCKED_MINOR`, `BLOCKED_OUT_OF_SCOPE`

#### Scenario: CaseStatus has 7 exact values
- **GIVEN** `CaseStatus`
- **WHEN** its values are enumerated
- **THEN** the exact set is `active`, `progressing`, `paused`, `stalled`, `resolved`, `inactive`, `archived`
- **AND** `inactive` and `archived` are treated as distinct statuses

#### Scenario: CasePhase has 3 exact values
- **GIVEN** `CasePhase`
- **WHEN** its values are enumerated
- **THEN** the exact set is `understand`, `illuminate`, `followup`

#### Scenario: CounselingMethod has 7 exact values
- **GIVEN** `CounselingMethod`
- **WHEN** its values are enumerated
- **THEN** the exact set is `LISTEN`, `ASK`, `REFLECT`, `TEACH`, `FOLLOWUP`, `REDIRECT`, `CRISIS_SAFE_ONLY`

#### Scenario: CounselingSubmode has 7 exact values
- **GIVEN** `CounselingSubmode`
- **WHEN** its values are enumerated
- **THEN** the exact set is `reflection`, `clarifying_question`, `body_awareness`, `story`, `resource_redirect`, `followup_check`, `none`

#### Scenario: EmotionTag has 10 exact values
- **GIVEN** `EmotionTag`
- **WHEN** its values are enumerated
- **THEN** the exact set is `calm`, `anxious`, `stressed`, `sad`, `angry`, `confused`, `hopeful`, `overwhelmed`, `grateful`, `neutral_unknown`

#### Scenario: EmotionShift has 5 exact values
- **GIVEN** `EmotionShift`
- **WHEN** its values are enumerated
- **THEN** the exact set is `stable`, `escalating`, `de_escalating`, `new_topic`, `unknown`

#### Scenario: Sensitivity has 3 exact values
- **GIVEN** `Sensitivity`
- **WHEN** its values are enumerated
- **THEN** the exact set is `public_safe`, `private_safe`, `clinical_sensitive`

#### Scenario: ConsentState has 5 exact values
- **GIVEN** `ConsentState`
- **WHEN** its values are enumerated
- **THEN** the exact set is `no_consent`, `consented_v1`, `reconsent_required`, `withdrawn_pending_delete`, `deleted`

#### Scenario: SessionState has 6 exact values
- **GIVEN** `SessionState`
- **WHEN** its values are enumerated
- **THEN** the exact set is `opened`, `streaming`, `completed`, `abandoned`, `timeout_closed`, `validator_rejected`

#### Scenario: OutboxDeliveryState has 4 exact values
- **GIVEN** `OutboxDeliveryState`
- **WHEN** its values are enumerated
- **THEN** the exact set is `pending`, `dispatched`, `failed`, `dead_letter`

#### Scenario: ReadinessLevel has 4 exact values
- **GIVEN** `ReadinessLevel`
- **WHEN** its values are enumerated
- **THEN** the exact set is `not_ready`, `exploring`, `insight`, `self_resolving`

#### Scenario: RiskLevel has 4 exact values
- **GIVEN** `RiskLevel`
- **WHEN** its values are enumerated
- **THEN** the exact set is `none`, `low`, `moderate`, `high`

#### Scenario: OutOfScopeType has 6 exact values
- **GIVEN** `OutOfScopeType`
- **WHEN** its values are enumerated
- **THEN** the exact set is `none`, `medication`, `diagnosis`, `trauma`, `substance`, `other`

#### Scenario: Intent has 4 exact values
- **GIVEN** `Intent`
- **WHEN** its values are enumerated
- **THEN** the exact set is `RELATED`, `UNRELATED`, `UNSAFE`, `META_ATTACK`

### Requirement: Enum regression tests detect canonical value drift
The system SHALL include regression tests that fail when canonical enum values are renamed, removed, added, or case-changed unintentionally.

#### Scenario: CaseStatus value change causes test failure
- **GIVEN** regression tests pass with canonical values
- **WHEN** a developer changes `CaseStatus.ACTIVE` from `active` to `Active`
- **THEN** the enum regression test fails

#### Scenario: Intent value change causes test failure
- **GIVEN** regression tests pass with canonical values
- **WHEN** a developer changes `Intent.RELATED` from `RELATED` to `related`
- **THEN** the enum regression test fails

### Requirement: Contracts package exposes immediate-need version registry
The system SHALL expose a version registry for immediate-need contracts in `wismo/contracts/version.py`.

#### Scenario: CONTRACT_VERSIONS contains 13 entries
- **GIVEN** `CONTRACT_VERSIONS`
- **WHEN** its keys are counted
- **THEN** the dictionary contains exactly 13 entries

#### Scenario: get_contract_version returns expected version
- **GIVEN** `get_contract_version('P1Output')`
- **WHEN** the helper is called
- **THEN** it returns `p1.v1`

#### Scenario: get_contract_version rejects unknown contract name
- **GIVEN** `get_contract_version('UnknownContract')`
- **WHEN** the helper is called
- **THEN** it raises `KeyError`
