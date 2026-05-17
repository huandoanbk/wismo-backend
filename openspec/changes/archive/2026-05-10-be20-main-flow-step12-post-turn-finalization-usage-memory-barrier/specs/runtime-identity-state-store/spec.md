## ADDED Requirements

### Requirement: Hệ thống phải có persistence store cho user_profile theo identity
Backend MUST có model/table lưu `user_profile` theo owner (`user` hoặc `guest_identity`) với ràng buộc exactly-one-owner và dữ liệu profile chuẩn hóa dạng JSON có versioning cơ bản.

#### Scenario: Upsert profile by identity
- **WHEN** Step 12 có `explicit_profile_facts` hợp lệ
- **THEN** runtime MUST upsert profile record của identity hiện tại

### Requirement: Hệ thống phải có persistence store cho user_preference theo identity
Backend MUST có model/table lưu `user_preference` theo owner, hỗ trợ `evidence_count` và timestamp để phục vụ rule threshold update.

#### Scenario: Preference threshold reached
- **WHEN** style signal đủ evidence threshold
- **THEN** runtime MUST update preference field tương ứng và evidence metadata

### Requirement: Hệ thống phải có persistence store cho user_state theo identity
Backend MUST có model/table lưu `user_state` theo owner với `primary_state`, `secondary_state` (optional) và `updated_at`.

#### Scenario: User state signal mapped
- **WHEN** Step 12 nhận `user_state_signals` hợp lệ
- **THEN** runtime MUST map signal sang state schema và upsert state record

### Requirement: Step 6 runtime bundle phải đọc identity-state store thay vì stub rỗng
Runtime bundle loader MUST đọc `user_profile`, `user_preference`, `user_state` từ persistence store mới; nếu chưa có record thì fallback `{}` không fail turn.

#### Scenario: No stored state yet
- **WHEN** identity chưa có record profile/preference/state
- **THEN** Step 6 MUST trả object rỗng cho từng field
- **AND** MUST không làm lỗi runtime bundle loading
