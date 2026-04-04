# Contracts Specification Delta for cc-contracts-models-ci

## ADDED Requirements

### Requirement: Canonical Contract Models for Immediate Runtime Paths
The system SHALL provide canonical Pydantic contract models under `wismo/contracts/` for the immediate runtime paths needed by F3, S1, and S3.

#### Scenario: P1Output round-trip preserves data
- **GIVEN** a `P1Output` instance with populated fields
- **WHEN** it is serialized with `model_dump()` and reconstructed with `P1Output(**data)`
- **THEN** the reconstructed object matches the original object

#### Scenario: P2Output round-trip preserves data
- **GIVEN** a `P2Output` instance with populated fields
- **WHEN** it is serialized with `model_dump()` and reconstructed with `P2Output(**data)`
- **THEN** the reconstructed object matches the original object

#### Scenario: RuleDecision round-trip preserves data
- **GIVEN** a `RuleDecision` instance with populated fields
- **WHEN** it is serialized with `model_dump()` and reconstructed with `RuleDecision(**data)`
- **THEN** the reconstructed object matches the original object

#### Scenario: SafetyDecision round-trip preserves data
- **GIVEN** a `SafetyDecision` instance with populated fields
- **WHEN** it is serialized with `model_dump()` and reconstructed with `SafetyDecision(**data)`
- **THEN** the reconstructed object matches the original object

#### Scenario: GuardResult round-trip preserves data
- **GIVEN** a `GuardResult` instance with populated fields
- **WHEN** it is serialized with `model_dump()` and reconstructed with `GuardResult(**data)`
- **THEN** the reconstructed object matches the original object

#### Scenario: CaseTransitionEvent round-trip preserves data
- **GIVEN** a `CaseTransitionEvent` instance with populated fields
- **WHEN** it is serialized with `model_dump()` and reconstructed with `CaseTransitionEvent(**data)`
- **THEN** the reconstructed object matches the original object

#### Scenario: PersonalizationConfig round-trip preserves data
- **GIVEN** a `PersonalizationConfig` instance with populated fields
- **WHEN** it is serialized with `model_dump()` and reconstructed with `PersonalizationConfig(**data)`
- **THEN** the reconstructed object matches the original object

### Requirement: Schema Versioned Public Contracts
Each public contract model SHALL expose a fixed `schema_version` default for stable serialization.

#### Scenario: SSEEvent has schema_version default
- **GIVEN** the `SSEEvent` model
- **WHEN** an instance is created
- **THEN** `schema_version` defaults to `sse.v1`

#### Scenario: ChatDonePayload has schema_version default
- **GIVEN** the `ChatDonePayload` model
- **WHEN** an instance is created
- **THEN** `schema_version` defaults to `chat-done.v1`

#### Scenario: ChatSendRequest has schema_version default
- **GIVEN** the `ChatSendRequest` model
- **WHEN** an instance is created
- **THEN** `schema_version` defaults to `chat-send.v1`

#### Scenario: OutboxEventEnvelope has schema_version and required routing fields
- **GIVEN** the `OutboxEventEnvelope` model
- **WHEN** an instance is created
- **THEN** it exposes `schema_version`, `idempotency_key`, and `event_type`

#### Scenario: WismoError has canonical required fields
- **GIVEN** the `WismoError` model
- **WHEN** an instance is created
- **THEN** it exposes `error_code`, `error_category`, `http_status`, `frontend_state`, `user_message`, `retryable`, and `request_id`

#### Scenario: TracePayload has canonical required fields
- **GIVEN** the `TracePayload` model
- **WHEN** an instance is created
- **THEN** it exposes `request_id`, `turn_id`, `session_id`, `timestamps`, and `latencies_ms`

### Requirement: Core Validation Constraints
The system SHALL enforce the core validation constraints required for immediate runtime safety and API correctness.

#### Scenario: Emotion severity rejects values above 10
- **GIVEN** an `EmotionSignal` or `P1Output` payload with `severity=15`
- **WHEN** the model is validated
- **THEN** validation fails

#### Scenario: P1 confidence rejects values above 1.0
- **GIVEN** a `P1Output` payload with `confidence=1.5`
- **WHEN** the model is validated
- **THEN** validation fails

#### Scenario: ChatSendRequest rejects empty content
- **GIVEN** a `ChatSendRequest` payload with empty `content`
- **WHEN** the model is validated
- **THEN** validation fails

#### Scenario: ChatSendRequest rejects content above 2000 characters
- **GIVEN** a `ChatSendRequest` payload whose `content` length exceeds 2000 characters
- **WHEN** the model is validated
- **THEN** validation fails

### Requirement: Contracts Package Remains Framework-Independent
The contracts package SHALL remain import-safe and framework-independent.

#### Scenario: Contracts package does not import app modules
- **GIVEN** all files in `wismo/contracts/`
- **WHEN** the package is statically inspected
- **THEN** it contains no imports from `apps.*`

#### Scenario: Contracts package does not import Django
- **GIVEN** all files in `wismo/contracts/`
- **WHEN** the package is statically inspected
- **THEN** it contains no imports from `django.*`

### Requirement: Contracts CI Enforces Contract Health
The system SHALL run a contracts-focused CI pipeline that fails on lint, type-check, or contract test regressions.

#### Scenario: CI runs for contracts scope on push or pull request
- **GIVEN** the contracts CI workflow
- **WHEN** code is pushed or a pull request is opened
- **THEN** lint, type-check, and tests run for contracts scope

#### Scenario: CI fails on lint error
- **GIVEN** the contracts CI workflow
- **WHEN** contracts code contains a lint violation such as an unused import
- **THEN** the lint step fails

#### Scenario: CI fails on type error
- **GIVEN** the contracts CI workflow
- **WHEN** contracts code contains a type error
- **THEN** the type-check step fails

#### Scenario: CI fails on serialization regression
- **GIVEN** the contracts CI workflow and serialization tests
- **WHEN** a breaking contract field change causes serialization tests to fail
- **THEN** the test step fails
