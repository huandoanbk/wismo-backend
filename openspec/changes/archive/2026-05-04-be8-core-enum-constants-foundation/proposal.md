## Why

Sprint `BE-8` cần được chốt trước khi tiếp tục Main Flow vì các bước `BE-9+` sẽ bắt đầu phát sinh nhiều nhánh `response_method`, `triage_decision`, control response, và error path mới. Repo hiện tại đã có một phần enum foundation trong `wismo/contracts/enums.py`, nhưng error/control codes và error helper vẫn còn phân tán bằng string literal, nên nếu không canonicalize ngay thì các sprint tiếp theo sẽ drift rất nhanh khỏi MVP spec và contract.

## What Changes

- Chuẩn hóa `wismo/contracts/enums.py` thành nguồn truth duy nhất cho core runtime enums đã xuất hiện trong MVP foundation, bao gồm `ResponseMethod`, `TriageDecision`, và usage/finalization statuses.
- Thêm canonical constants tối thiểu cho error/control codes đang được dùng xuyên `accounts`, `consents`, `chat`, và `runtime`, thay vì để từng module tự hard-code keyword.
- Chuẩn hóa helper build payload cho API/runtime control response theo hướng keyword-only, không còn nhánh plain-text `message` trong foundation helper mặc định.
- Loại bỏ enum/constants legacy hoặc duplicate trùng nghĩa trong foundation path nếu chúng làm tồn tại song song hai nguồn truth cho cùng một contract keyword/state.
- Khóa spec và regression tests để các sprint Main Flow sau chỉ mở rộng trên nền constants chung, không thêm string literal rải rác.

## Capabilities

### New Capabilities
- `core-enum-constants-foundation`: Canonical shared enums, error/control code constants, và payload helpers cho MVP backend runtime và API foundation.

### Modified Capabilities

## Impact

- Affected code: `wismo/contracts/enums.py`, `wismo/contracts/error.py`, `wismo/contracts/chat.py`, `accounts/views.py`, `chat/views.py`, `consents/views.py`, `runtime/request_gate.py`, `runtime/orchestrator.py`, và các test contract/runtime liên quan.
- Affected APIs: không đổi meaning của payload đã public, nhưng chuẩn hóa nguồn constants cho `error` keyword và control response payload.
- Affected systems: contract foundation cho auth/session, chat request gate, và Main Flow runtime shell các sprint sau.
