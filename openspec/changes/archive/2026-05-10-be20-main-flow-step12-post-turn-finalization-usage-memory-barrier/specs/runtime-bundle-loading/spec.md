## MODIFIED Requirements

### Requirement: Step 6 phải load identity-level runtime context với fallback rỗng
Step 6 MUST load `user_profile`, `user_preference`, `user_state` theo identity hiện tại từ persistence store canonical; nếu chưa có dữ liệu thì MUST trả object rỗng chuẩn hóa.

#### Scenario: Identity context thiếu dữ liệu
- **WHEN** identity chưa có dữ liệu profile/preference/state
- **THEN** Step 6 MUST set `user_profile = {}`
- **AND** Step 6 MUST set `user_preference = {}`
- **AND** Step 6 MUST set `user_state = {}`

#### Scenario: Identity context có dữ liệu persisted
- **WHEN** identity đã có record profile/preference/state hợp lệ
- **THEN** Step 6 MUST đưa dữ liệu persisted vào `runtime_bundle`
- **AND** MUST không fallback về stub rỗng
