## ADDED Requirements

### Requirement: Core runtime enums are canonicalized in one shared contract module
Hệ thống SHALL giữ một nguồn truth duy nhất cho các core runtime enums và enum groupings dùng xuyên MVP foundation, để các sprint Main Flow không tự hard-code hoặc tự đặt lại values.

#### Scenario: Runtime response methods stay aligned with MVP spec
- **WHEN** backend cần đọc hoặc ghi `response_method` cho `ChatTurn`, runtime state, hoặc control branch
- **THEN** backend SHALL dùng cùng canonical `ResponseMethod` values `LISTEN`, `ASK`, `REFLECT`, `TEACH`, `FOLLOWUP`, `REDIRECT`, `CRISIS_SAFE_ONLY`, `BLOCKED_MINOR`, `REFUSAL`, và `SPAM_REPLY`

#### Scenario: Fast triage decisions stay aligned with MVP spec
- **WHEN** backend cần persist hoặc xử lý `triage_decision` ở Step 4 và các bước downstream
- **THEN** backend SHALL dùng cùng canonical `TriageDecision` values `crisis_hotline_immediate`, `blocked_minor`, `hard_redirect`, `policy_bypass_refusal`, `spam_or_non_conversational`, và `continue_to_full_reasoning`

#### Scenario: Conversational and control groupings remain explicit
- **WHEN** downstream logic cần phân biệt counseling path với terminal/control path
- **THEN** backend SHALL dùng grouping canonical từ contract layer thay vì tự copy danh sách method ở từng module

### Requirement: Foundation public error and control codes are defined as shared constants
Hệ thống SHALL định nghĩa một bộ constants dùng chung cho các public keyword foundation đã xuất hiện trong auth/session, consent, chat bootstrap, và chat request gate, để các app không tự hard-code cùng một keyword ở nhiều nơi.

#### Scenario: Request gate errors come from canonical constants
- **WHEN** backend trả lỗi cho các gate cases như payload invalid, identity/session invalid, consent required, quota exhausted, idempotency conflict, hoặc chat ownership deny
- **THEN** backend SHALL build payload từ shared constants module thay vì hard-code raw strings tại từng view hoặc service

#### Scenario: Foundation auth and chat endpoints reuse the same public keywords
- **WHEN** nhiều endpoint foundation cùng trả một public keyword như `identity_not_resolved`, `guest_session_expired`, `session_expired`, `chat_not_found`, hoặc `chat_access_denied`
- **THEN** các endpoint đó SHALL import cùng một canonical constant cho keyword tương ứng

#### Scenario: Duplicate legacy definitions are removed from production paths
- **WHEN** tồn tại enum/constants/helper legacy diễn đạt lại cùng một foundation keyword hoặc runtime state đã có canonical source
- **THEN** backend SHALL loại bỏ definition cũ khỏi production call path và SHALL NOT giữ song song hai nguồn truth cho cùng một contract concern

### Requirement: Foundation error payload helpers are keyword-only by default
Hệ thống SHALL cung cấp helper canonical để build API/runtime error payload theo dạng keyword-only, nhằm giữ FE/BFF contract ổn định và tránh plain-text drift giữa endpoints.

#### Scenario: API error payload remains keyword-only
- **WHEN** một foundation endpoint trả lỗi canonical
- **THEN** payload lỗi SHALL có field `error` với keyword English canonical và SHALL NOT thêm plain-text server `message` mặc định

#### Scenario: Runtime control reply reuses shared payload builder
- **WHEN** runtime request gate hoặc orchestrator cần trả control/error reply không đi tiếp Main Flow
- **THEN** reply helper SHALL reuse shared keyword-only payload shape thay vì tự dựng ad-hoc dictionary khác contract

### Requirement: Regression coverage locks shared contract values
Hệ thống SHALL có regression coverage cho bộ enum/code foundation để future sprint không vô tình đổi values hoặc quay lại hard-code string literals phân tán.

#### Scenario: Contract test catches drift
- **WHEN** một developer đổi enum value, bỏ một public keyword, hoặc thêm helper trả payload lỗi sai shape
- **THEN** contract hoặc unit tests SHALL fail để chặn drift trước khi các sprint Main Flow phụ thuộc vào foundation đó
