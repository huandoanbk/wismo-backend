## MODIFIED Requirements

### Requirement: Chat message API SHALL expose control responses via SSE after gate pass
Sau khi gate pass và stream đã mở, mọi control response ở Step 4 SHALL được trả qua SSE lifecycle thay vì JSON.

#### Scenario: Crisis control response qua SSE
- **WHEN** Step 4 quyết định `crisis_hotline_immediate`
- **THEN** stream phát control response tương ứng `CRISIS_SAFE_ONLY` và phát `done` event để chốt turn lifecycle

#### Scenario: Non-persist control response qua SSE
- **WHEN** Step 4 quyết định `blocked_minor`, `hard_redirect`, `policy_bypass_refusal`, hoặc `spam_or_non_conversational`
- **THEN** stream phát control response tương ứng và kết thúc lifecycle theo contract SSE của control path

#### Scenario: Mọi control path đều phát done event
- **WHEN** Step 4 trả bất kỳ control response nào (`CRISIS_SAFE_ONLY`, `BLOCKED_MINOR`, `REDIRECT`, `REFUSAL`, `SPAM_REPLY`)
- **THEN** stream MUST phát `done` event sau control response để FE chốt lifecycle

#### Scenario: done contract cho non-persist control path
- **WHEN** control response thuộc non-persist paths (`BLOCKED_MINOR`, `REDIRECT`, `REFUSAL`, `SPAM_REPLY`)
- **THEN** `done` event MUST có `status = "completed"`, `response_method` đúng method control
- **AND** `done.turn_id` MUST là `null`
- **AND** `done.chat_id` MUST luôn có để FE giữ canonical thread state

#### Scenario: Continue path giữ SSE normal flow
- **WHEN** Step 4 quyết định `continue_to_full_reasoning`
- **THEN** stream tiếp tục flow normal hiện tại (response + done) sau các step downstream
