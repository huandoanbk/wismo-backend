# Consent & GDPR — Backend Domain Spec

Tài liệu mô tả GDPR consent flow, consent state machine, data deletion cascade, user rights, và ConsentService implementation.

Finland thuộc EU. Mental health data = GDPR Article 9 "special category" → cần **explicit consent** trước khi xử lý BẤT KỲ dữ liệu nào.

Worker PHẢI đọc file này khi code ConsentService, ConsentMiddleware, DeletionService, hoặc bất kỳ service nào liên quan consent/GDPR/export/delete.

---

## 1. Consent Screen — User thấy gì

Trước khi chat lần đầu, user PHẢI thấy consent screen:

```
Chào mừng bạn đến với WISMO

WISMO là AI companion giúp bạn suy ngẫm và tự hiểu mình,
KHÔNG phải dịch vụ tư vấn tâm lý hay y tế.
WISMO không chẩn đoán bệnh, không kê đơn thuốc, không trị liệu.
Nếu cần hỗ trợ khẩn cấp: 09 2525 0111

☐ Tôi đồng ý WISMO lưu và xử lý nội dung hội thoại
  để cá nhân hóa hỗ trợ cho tôi (BẮT BUỘC)

☐ Tôi đồng ý WISMO ghi nhớ thông tin giữa các phiên
  để hỗ trợ liên tục (BẮT BUỘC)

☐ Tôi đồng ý dữ liệu ẩn danh được dùng để cải thiện
  chất lượng dịch vụ (không bắt buộc)

Bạn có thể xóa dữ liệu bất cứ lúc nào trong Cài đặt.

[Bắt đầu trò chuyện]    [Tôi không đồng ý]
```

### 1.1 GDPR 6 tiêu chí consent phải đáp ứng

| Tiêu chí | Implementation |
|----------|---------------|
| Freely given | Có nút "Tôi không đồng ý" rõ ràng |
| Specific | Tách riêng 3 loại consent (chat, memory, analytics) |
| Informed | Ngôn ngữ dễ hiểu, không legal jargon |
| Unambiguous | Checkbox tick, KHÔNG pre-ticked |
| Documented | Lưu DB: version, timestamp, IP, user_agent, consent_text_hash |
| Withdrawable | Rút consent trong Settings, dễ như lúc cho |

---

## 2. Consent State Machine — 5 states

Machine quản lý quyền xử lý dữ liệu, khả năng chat, và nghĩa vụ xóa. Tách biệt với session runtime state.

### 2.1 Source of truth

- Registered user: `gdpr_consents` + `users` + deletion job state trong PostgreSQL
- Guest: consent chỉ có hiệu lực trong session hiện tại, KHÔNG long-term
- Runtime middleware CHỈ ĐỌC state này, KHÔNG mutate — chỉ ConsentService / DeletionService mutate

### 2.2 Canonical states

```
no_consent              → Chưa consent (mới hoặc guest mới)
consented_v1            → Đã consent version hiện hành, chat OK
reconsent_required      → Consent copy thay đổi, cần re-consent
withdrawn_pending_delete → Đã rút consent, đang chờ deletion pipeline
deleted                 → Dữ liệu đã xóa/anonymize
```

### 2.3 Transition table

| Current | Trigger | Guard | Next | Side effects | Idempotency |
|---------|---------|-------|------|-------------|-------------|
| `no_consent` | User tick đủ required + bấm bắt đầu | Version hiện hành hợp lệ, checkbox KHÔNG pre-ticked | `consented_v1` | Tạo GDPRConsent, lưu version/timestamp/hash/IP, mở chat | `(user_or_guest_session_id, consent_version)` |
| `consented_v1` | Consent copy thay đổi | `current_version > user_version` | `reconsent_required` | Block chat, redirect consent screen, ghi audit | `(user_id, consent_version_current)` |
| `reconsent_required` | User re-consent OK | Version mới nhất, required đủ | `consented_v1` | Tạo consent mới, mở chat lại | `(user_id, consent_version_new)` |
| `consented_v1` | User withdraw / delete account | User authenticated, deletion valid | `withdrawn_pending_delete` | Block chat mới, enqueue deletion, ghi withdraw_requested_at | `deletion_request_id` |
| `reconsent_required` | User chọn xóa thay vì re-consent | User authenticated | `withdrawn_pending_delete` | Như trên | `deletion_request_id` |
| `withdrawn_pending_delete` | Delete workflow hoàn tất | Cleanup success, audit write success | `deleted` | Xóa/anonymize theo retention matrix, ghi deleted_at | `deletion_request_id` |

### 2.4 Forbidden transitions

- `deleted → *` (terminal state, KHÔNG BAO GIỜ quay lại)
- `no_consent → deleted` (không có dữ liệu để delete)
- `withdrawn_pending_delete → consented_v1` nếu delete job đã enqueue (phải tạo account mới sau cleanup)

### 2.5 Commit ordering

State machine KHÔNG chuyển bằng narrative hay Celery callback rời rạc. Canonical ordering:

- **consent → withdrawn**: ghi audit + append outbox delete/withdraw event → commit
- **withdrawn → deleted**: CHỈ sau deletion pipeline hoàn tất + completion audit
- Outbox event phải nằm TRONG CÙNG transaction với state change

---

## 3. Guest Consent Rules

- Guest mới luôn bắt đầu tại `no_consent`, phải consent cho mỗi session mới
- Guest KHÔNG có `reconsent_required` kéo dài qua nhiều lần mở app
- Đóng tab / mở lại = session mới = consent lại

### 3.1 Guest attach & consent coupling

Attach guest session vào registered user KHÔNG copy consent:
- User identity xác thực trước → attach transaction gắn session → consent/audit rows ghi trong CÙNG transaction hoặc outbox chain
- Nếu attach rollback → consent state của account KHÔNG bị hạ cấp
- Guest consent KHÔNG thay thế cho registered user consent

---

## 4. ConsentService — Implementation

```python
class ConsentService:
    """Quản lý GDPR consent: check, grant, withdraw.
    
    Middleware gọi check_consent() trước mọi chat request.
    ConsentService là OWNER duy nhất cho consent state mutation.
    """
    CURRENT_VERSION = 'v1.0'
    
    def check_consent(self, user) -> ConsentStatus:
        """Kiểm tra user có consent hợp lệ không.
        
        Returns:
            ConsentStatus(has_consent, reason, consent)
            reason: 'no_consent' | 'version_outdated' | 'required_missing' | 'valid'
        """
        latest = GDPRConsent.objects.filter(
            user=user, withdrawn_at__isnull=True
        ).order_by('-consented_at').first()
        
        if not latest:
            return ConsentStatus(has_consent=False, reason='no_consent')
        if latest.consent_version != self.CURRENT_VERSION:
            return ConsentStatus(has_consent=False, reason='version_outdated')
        if not latest.chat_processing or not latest.memory_storage:
            return ConsentStatus(has_consent=False, reason='required_missing')
        
        return ConsentStatus(has_consent=True, consent=latest)
    
    def grant_consent(self, user, data, request) -> GDPRConsent:
        """Grant consent — tạo record với version, timestamp, IP, hash.
        
        Idempotent: cùng user + version → không tạo duplicate.
        Required: chat_processing=True, memory_storage=True.
        """
        consent = GDPRConsent.objects.create(
            user=user,
            consent_version=self.CURRENT_VERSION,
            chat_processing=data['chat_processing'],     # REQUIRED = True
            memory_storage=data['memory_storage'],        # REQUIRED = True
            anonymous_analytics=data.get('anonymous_analytics', False),
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            consent_method='checkbox_click',
            consent_text_hash=self._hash_consent_text()
        )
        GDPRAuditService().log_consent(user.id, 'all', given=True,
                                        ip=get_client_ip(request))
        return consent
    
    def withdraw_consent(self, user, reason, request):
        """Rút consent — mark withdrawn, trigger deletion workflow.
        
        Side effects: block chat, enqueue deletion, ghi audit.
        """
        latest = GDPRConsent.objects.filter(
            user=user, withdrawn_at__isnull=True
        ).first()
        if latest:
            latest.withdrawn_at = now()
            latest.withdrawal_reason = reason
            latest.save()
        
        GDPRAuditService().log_consent(user.id, 'all', given=False,
                                        ip=get_client_ip(request))
        # Trigger deletion via outbox (NOT Celery direct)
        OutboxService().append(
            aggregate_type='account',
            aggregate_id=str(user.id),
            event_type='gdpr_delete_dispatch',
            payload={'user_id': str(user.id), 'reason': reason},
            idempotency_key=f"gdpr_delete_{user.id}_{now().isoformat()}"
        )
```

---

## 5. Data Deletion Cascade — 10 bước

Khi user withdraw consent hoặc delete account, xóa HOÀN TOÀN mọi dữ liệu:

```python
def withdraw_consent_full_delete(user):
    """GDPR withdraw consent = xóa TOÀN BỘ dữ liệu cá nhân."""
    
    # 1. Chat content
    Message.objects.filter(user=user).delete()
    
    # 2. Cases + context
    UserCase.objects.filter(user=user).delete()
    
    # 3. Sessions
    Session.objects.filter(user=user).delete()
    
    # 4. Memory items + embeddings
    MemoryItem.objects.filter(user=user).delete()
    
    # 5. Derived profile
    UserPreference.objects.filter(user=user).delete()
    UserState.objects.filter(user=user).delete()
    UserProfile.objects.filter(user=user).delete()
    
    # 6. Feedback
    FeedbackLog.objects.filter(user=user).delete()
    
    # 7. Usage tracking
    UsageTracking.objects.filter(user=user).delete()
    
    # 8. Consent records (giữ cho audit trail)
    consent = GDPRConsent.objects.filter(user=user).first()
    if consent:
        consent.withdrawn_at = now()
        consent.save()
    
    # 9. GDPR audit log — GIỮ 5 NĂM (legal requirement EU)
    GDPRAuditService().log(user.id, 'full_data_deletion',
                           detail={'reason': 'consent_withdrawn'})
    
    # 10. Anonymize account
    user.is_active = False
    user.email = f"deleted_{user.id}@deleted"
    user.save()
```

### 5.1 Dữ liệu KHÔNG xóa (anonymous/aggregate)

| Data | Lý do giữ |
|------|----------|
| `crisis_events` | Anonymous — không có user_id, chỉ session_hash |
| `attack_logs` | Anonymous — không có user_id |
| `daily_stats` | Aggregate — không link user |
| `gdpr_audit_log` | Legal requirement — giữ 5 năm |

### 5.2 Delete account = withdraw + hard delete

```python
def delete_account(user):
    """Delete account hoàn toàn — giống withdraw nhưng xóa cả user record."""
    withdraw_consent_full_delete(user)
    user.delete()  # hard delete user record
```

---

## 6. Data Export — GDPR Right to Portability

```python
def export_user_data(user):
    """Export toàn bộ user data, TRỪ clinical_sensitive."""
    
    data = {
        'profile': UserProfile.objects.filter(user=user).values().first(),
        'preferences': UserPreference.objects.filter(user=user).values().first(),
        'cases': list(UserCase.objects.filter(user=user).values()),
        'messages': list(Message.objects.filter(user=user).values(
            'role', 'content', 'emotion_tag', 'created_at'
        )),
        'memory_items': [],
    }
    
    # Memory: EXCLUDE clinical_sensitive
    for item in MemoryItem.objects.filter(user=user):
        if item.sensitivity != 'clinical_sensitive':
            data['memory_items'].append({
                'text': item.text,
                'tags': item.tags,
                'sensitivity': item.sensitivity,
                'created_at': item.created_at.isoformat(),
            })
    
    # KHÔNG export: embeddings, metadata JSONB, internal signals
    
    GDPRAuditService().log_data_export(user.id, ip=None)
    return data
```

### 6.1 Export rules

- Export EXCLUDE `clinical_sensitive` memory items (trauma, crisis history)
- Export EXCLUDE internal metadata (embeddings, LLM signals, system notes)
- Export INCLUDE: messages, cases, profile, preferences, memory (public_safe + private_safe)
- Export ghi audit log
- Export file TTL ngắn — không lưu public

---

## 7. GDPR User Rights — Tổng hợp

| Quyền GDPR | Implementation | API |
|------------|---------------|-----|
| Right to access | Xem data trong Settings | GET /api/memory/items |
| Right to erasure | Xóa toàn bộ data (cascade 10 bước) | POST /api/settings/privacy/delete-all |
| Right to portability | Export JSON download | GET /api/settings/privacy/export |
| Right to withdraw consent | 1 click withdraw → trigger delete | POST /api/accounts/consent/withdraw |
| Memory management | Xem + xóa từng memory item | DELETE /api/memory/items/{id} |

### 7.1 Audit trail

- MỌI hành động GDPR (export, delete, consent grant/withdraw) → ghi GDPRAuditLog
- GDPRAuditLog giữ 5 năm (EU legal requirement)
- GDPRAuditLog.user_id là UUID field, KHÔNG phải FK → survives user deletion
- Audit log ghi: user_id, action, detail (JSONB), ip_address, performed_by, timestamp

---

## 8. ConsentMiddleware — Block chat nếu chưa consent

```python
class ConsentMiddleware:
    """Block /api/chat/* nếu user chưa consent hợp lệ."""
    
    EXEMPT_PATHS = [
        '/api/accounts/',     # auth endpoints
        '/api/consent/',      # consent endpoints  
        '/api/health/',       # health check
    ]
    
    def __call__(self, request):
        # Skip exempt paths
        if any(request.path.startswith(p) for p in self.EXEMPT_PATHS):
            return self.get_response(request)
        
        # Check consent
        status = ConsentService().check_consent(request.user)
        if not status.has_consent:
            return JsonResponse(
                WismoError(
                    error_code='consent_required',
                    error_category='consent',
                    http_status=403,
                    frontend_state='consent_required',
                    user_message='Bạn cần đồng ý điều khoản trước khi sử dụng.',
                    retryable=False,
                    action_required='consent',
                    request_id=str(request.request_id),
                ).model_dump(),
                status=403
            )
        
        return self.get_response(request)
```

---

## 9. Implementation Rules

### 9.1 Service ownership
- ConsentService là OWNER duy nhất cho consent state mutation
- ConsentMiddleware CHỈ ĐỌC, không mutate
- DeletionService execute deletion pipeline (gọi qua outbox dispatch)

### 9.2 Transaction rules
- Grant consent: create GDPRConsent + audit log → commit → mở chat
- Withdraw: mark withdrawn + append outbox delete event → commit → worker xử lý
- Delete workflow: worker execute → mark deleted → completion audit

### 9.3 Idempotency
- Grant: idempotent theo `(user_or_guest_session_id, consent_version)`
- Withdraw: idempotent theo `deletion_request_id`
- Delete: idempotent — retry không tạo effect thứ hai

### 9.4 ConsentService KHÔNG được
- Gọi Celery trực tiếp (dùng outbox)
- Import từ apps.chat, apps.memory, apps.counseling
- Tự quyết case/session state (không sở hữu)
- Pre-tick checkboxes
- Auto-infer consent từ user behavior
