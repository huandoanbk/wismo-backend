## ADDED Requirements

### Requirement: Step 9 -> Step 10 TEACH handoff phải luôn có prompt-ready payload
Khi Step 9 retrieval thành công, runtime MUST đảm bảo `retrieval_result` chứa đủ dữ liệu để Step 10 TEACH builder assemble prompt (`retrieval_unit_text` hoặc `retrieval_prompt_payload.content_text_for_prompt`).

#### Scenario: Retrieval success handoff
- **WHEN** Step 9 trả `retrieval_result` khác null
- **THEN** payload handoff MUST có text usable cho Step 10 TEACH builder
- **AND** Step 10 MUST có thể assemble prompt không cần query lại DB

### Requirement: Retrieval failure phải tương thích fallback TEACH của Step 10
Khi Step 9 không tìm được retrieval unit usable hoặc degrade về null, runtime MUST giữ output ở trạng thái để Step 10 áp dụng TEACH fallback sang LISTEN một cách deterministic.

#### Scenario: Retrieval null handoff for TEACH fallback
- **WHEN** Step 9 trả `retrieval_result = null` hoặc retrieval text unusable
- **THEN** runtime MUST vẫn tiếp tục flow sang Step 10
- **AND** Step 10 MUST có đủ tín hiệu để fallback TEACH -> LISTEN theo rule 10.7.4
