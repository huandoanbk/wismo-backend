## Context

### Spec References

- `project-spec/WISMO_MVP_Spec.md`
- `project-spec/WISMO_BE_Implementation_Plan.md`
- `openspec/specs/identity-consent-auth/spec.md`
- `openspec/specs/chat-request-gate/spec.md`
- `openspec/specs/runtime-config-quota-foundation/spec.md`
- `openspec/specs/llm-gateway-foundation/spec.md`

Sprint `BE-8` nằm ngay trước nhóm Main Flow implementation. Theo plan, sprint này phải tạo shared enum/code để Step 1/2/4/8/11/12 không hard-code string. Trạng thái repo hiện tại cho thấy foundation này đã được làm một phần: `wismo/contracts/enums.py` đã chứa `ResponseMethod`, `TriageDecision`, `UsageAccountingStatus`, `Step12FinalizationStatus`, `OperationKey`, cùng các grouping sets cho conversational/control methods. Các model `chat.ChatTurn`, runtime shell, và contract tests cũng đã dùng trực tiếp các enum này.

Phần còn lệch so với mục tiêu `BE-8` là error/control codes và payload helpers:

- `accounts`, `chat`, `consents`, `runtime` vẫn còn nhiều string literal cho `error` keyword và một số control/result flags.
- `wismo/contracts/error.py` vẫn giữ `message` optional, trong khi repo rule hiện tại yêu cầu API error trả keyword-only.
- Một số domain-specific constants đã có riêng, ví dụ `llm_ops/errors.py`, nên BE-8 phải tránh biến thành một đợt gom tất cả mọi constant về một chỗ theo kiểu quá rộng.

Vì vậy change này là cross-cutting refactor/foundation change, cần design rõ trước khi apply.

## Goals / Non-Goals

**Goals:**

- Giữ `wismo/contracts` là canonical contract layer cho core enums và foundation error/control codes.
- Chuẩn hóa các `error` keyword public tối thiểu đang được share giữa auth/session, consent, chat bootstrap, và chat request gate.
- Cung cấp helper build keyword-only error/control payload để các view/runtime path không tự dựng payload rời rạc.
- Xóa hoặc gỡ call sites khỏi enum/constants legacy trùng nghĩa nếu chúng cạnh tranh với canonical source.
- Khóa regression tests để BE-9+ chỉ mở rộng trên shared constants hiện có.

**Non-Goals:**

- Không redesign meaning của API payload đang public.
- Không đổi persisted enum values hoặc thêm migration DB nếu giá trị hiện tại đã đúng spec.
- Không gom toàn bộ state strings của mọi domain vào một enum mega-file.
- Không kéo các provider-specific gateway errors trong `llm_ops/errors.py` về cùng namespace nếu chúng không phải foundation cross-app concern.

## Decisions

### 1. Giữ enum và code constants ở hai module contract tách biệt

`wismo/contracts/enums.py` sẽ tiếp tục là nơi chứa các `StrEnum` và grouping sets. Error/control codes sẽ được đưa vào một module contract riêng, ví dụ `wismo/contracts/codes.py` hoặc module tương đương, thay vì nhét thêm vào `enums.py`.

Lý do:

- Enum runtime và keyword error phục vụ hai nhu cầu khác nhau: enum cần `choices`, grouping, và typed usage; error/control codes chủ yếu là string constants public.
- Giữ tách biệt giúp `enums.py` không thành một bãi chứa mọi string của hệ thống.

Alternative đã cân nhắc:

- Nhét error codes vào `enums.py`: không chọn vì làm module contract khó đọc và blur ranh giới typed enum với public keyword constants.

### 2. Keyword-only error payload là canonical mặc định

Foundation helper cho API errors sẽ chỉ emit `{\"error\": \"<keyword>\"}` và có thể cho phép merge thêm structured metadata khi thật sự cần, nhưng không có nhánh plain-text `message` mặc định.

Lý do:

- Repo rule hiện tại đã chốt API lỗi phải trả keyword canonical bằng English.
- FE/BFF contract hiện tại cũng đang dựa vào `error` keyword thay vì plain-text server message.

Alternative đã cân nhắc:

- Giữ `message` optional để linh hoạt hơn: không chọn vì dễ làm drift giữa endpoints và phá repo rule keyword-only.

### 3. Chỉ canonicalize các public codes foundation đã thực sự xuất hiện

BE-8 sẽ khóa nhóm codes tối thiểu đã được public hoặc đang là blocker trực tiếp cho Main Flow foundation:

- request/chat payload errors;
- identity/session/consent gate errors;
- chat ownership/idempotency/quota gate errors;
- foundation control/result flags được dùng xuyên runtime path nếu chúng là contract-level concern.

Lý do:

- Sprint này là foundation, không phải audit toàn repo để gom mọi string nội bộ.
- Chỉ canonicalize những keyword đã có contract/spec hoặc đang được nhiều app dùng sẽ giữ scope chặt và giảm refactor noise.

Alternative đã cân nhắc:

- Canonicalize toàn bộ mọi string state của `accounts`, `consents`, `chat`, `runtime`, `llm_ops`: không chọn vì quá rộng, dễ lẫn internal state với public contract.

### 4. Không đổi public behavior, chỉ đổi nguồn truth và adoption path

Spec delta của BE-8 sẽ mô tả canonical shared source cho enums/codes/helpers, nhưng không thay meaning của response methods, triage decisions, hay error keywords đang public. Implementation sẽ chủ yếu là import/adoption cleanup và test locking.

Lý do:

- Repo hiện đã có code và tests chạy trên các giá trị hiện tại.
- Main Flow sprint sau cần một foundation ổn định, không cần một đợt semantic change lúc này.

### 5. Không giữ song song legacy và canonical definitions cho cùng một contract concern

Nếu trong foundation path còn tồn tại enum/constants/helper cũ diễn đạt lại cùng một public keyword hoặc runtime state, change này sẽ chọn một canonical definition và loại bỏ hoặc cô lập definition cũ khỏi production call path.

Lý do:

- Giữ song song old/new source of truth sẽ làm các sprint sau tiếp tục drift dù bề ngoài đã có module canonical.
- Mục tiêu thật của BE-8 là dọn mặt bằng contract trước Main Flow, không chỉ thêm file mới.

Alternative đã cân nhắc:

- Giữ legacy definitions thêm vài sprint để "an toàn": không chọn vì repo hiện chưa có compatibility pressure đủ lớn để chấp nhận hai nguồn truth cho cùng một contract.

## Risks / Trade-offs

- [Risk] Đụng nhiều call sites nhỏ trong views/services/tests dễ bỏ sót một string literal.
  → Mitigation: thêm contract tests cho code sets và dùng search-based cleanup trước khi merge.

- [Risk] Gom code constants quá rộng sẽ biến sprint foundation thành refactor nặng, khó review.
  → Mitigation: chỉ include public/shared keywords đã được spec hoặc contract current use xác nhận.

- [Risk] Một số helper cũ như `WismoError` đang được dùng nhẹ ở nhiều nơi; đổi interface quá mạnh có thể làm churn không cần thiết.
  → Mitigation: ưu tiên migration nhỏ, có thể giữ class/helper cũ nhưng thu hẹp serialization về keyword-only và thêm compatibility path nội bộ nếu thực sự cần.

- [Risk] OpenSpec có thể bị viết như greenfield dù repo đã có enum sẵn.
  → Mitigation: ghi rõ trong proposal/spec/design rằng BE-8 là canonicalization + adoption trên nền implementation hiện có.

## Migration Plan

1. Thêm module canonical cho public error/control codes trong `wismo/contracts`.
2. Chuẩn hóa `WismoError` và các payload helper liên quan về keyword-only behavior.
3. Thay string literal tại các call sites foundation bằng import từ module contract tương ứng, đồng thời gỡ các duplicate definitions khỏi production path.
4. Cập nhật/đổ thêm regression tests để khóa values và payload shape.
5. Chạy `manage.py check`, `ruff check .`, `pytest`, và `makemigrations --check --dry-run` để xác nhận change là pure code-contract refactor.

Rollback đơn giản vì đây là code-only change; có thể revert commit nếu adoption tạo regressions. Không cần data migration rollback.

## Open Questions

- Không có open question ở mức product/spec. Scope BE-8 đủ rõ nếu giữ đúng ranh giới foundation nêu trên.
