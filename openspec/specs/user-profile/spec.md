# User Profile Domain Spec — Facts, Personality & Personalization

**Source:** WISMO Project Specification v18, Section 4 + Section 10 (trích lọc và tổng hợp)  
**Scope:** `apps/personalization/` + phần profile trong `apps/accounts/` — 7 personality dimensions, P5/P6, PersonalizerPolicy  
**Owner app:** `personalization` (personality detection + response style policy); `accounts` (profile persistence)  
**Không thuộc scope:** memory item lifecycle (→ `memory/spec.md`), case context (→ `case-management/spec.md`)

---

## 1. Vai trò và Ranh giới

User profile có 2 thành phần tách biệt:

| Thành phần | Owned by | Build bởi | Dùng bởi |
|-----------|---------|-----------|---------|
| **Facts** (P5) — thông tin ổn định về con người | `memory` (storage), `accounts` (profile) | P5 Celery task | P3 inject, Personalizer |
| **Personality** (P6) — 7 dimensions | `personalization` | P6 Celery task → `accounts.user_preferences` | PersonalizerPolicy → P3 style |

**Personalization ownership:**
- `personalization` owns: personality detection rules, response style policy, PersonalityDetector, PersonalizerPolicy
- `personalization` không owns: memory storage, consent, case persistence
- `personalization` reads: `accounts` profile/preferences (read facade), `memory` facts (read facade), `telemetry` facade

**Forbidden:** `personalization` không direct mutate `chat.Session`, `chat.Message`, `UserCase`. Không biết orchestration internals.

---

## 2. Nguyên tắc: Xây dựng dần, không hỏi trước

WISMO **không** yêu cầu user điền form hay survey. Profile xây dựng **tự nhiên** qua hội thoại, tích lũy dần mỗi turn.

```
Turn 1:    WISMO biết: ngôn ngữ (auto-detect)
Turn 3:    WISMO biết: + vấn đề chính, occupation nếu user đề cập
Turn 5:    WISMO biết: + thích nói ngắn gọn, expertise level
Session 3: WISMO biết: + beginner mindfulness, direct tone confirmed
Session 5: WISMO biết: + triggers confirmed, trust tăng dần
Session 10: WISMO biết: + emotional expressiveness, help-seeking style stable

→ Mỗi session WISMO hiểu user HƠN session trước
→ Response ngày càng CHÍNH XÁC hơn
```

---

## 3. User Profile — 2 thành phần

### 3.1 Facts (P5 — User Profile Facts Builder)

Thông tin CỤ THỂ, ỔN ĐỊNH về con người user. Dùng cho MỌI case.

**Facts WISMO thu thập:**

| Loại | Ví dụ | Tag | Quy tắc thu thập |
|------|-------|-----|-----------------|
| Độ tuổi | "35 tuổi", "20s" | `demographics` | CHỈ khi user TỰ NÓI — không suy luận từ context |
| Nghề nghiệp | "Làm IT", "Bác sĩ", "Sinh viên" | `occupation` | CHỈ khi user TỰ NÓI |
| Chuyên môn | "Senior developer", "Chuyên khoa tim mạch" | `expertise` | Tự xuất hiện — giúp metaphor phù hợp |
| Gia đình | "Có 2 con nhỏ", "Đã kết hôn", "Sống một mình" | `family` | Tự xuất hiện |
| Mối quan hệ | "Vợ hay phàn nàn", "Bố mẹ ở xa" | `relationship` | Tự xuất hiện |
| Trigger chung | "Stress khi deadline", "Mất ngủ khi lo lắng" | `trigger` | Tự xuất hiện, xuyên nhiều cases |
| Coping | "Đi bộ giúp thư giãn", "Viết nhật ký" | `coping` | Tự xuất hiện |
| Kinh nghiệm thiền | "Đã tham gia 1 khóa thiền" | `meditation_exp` | Tự xuất hiện |
| Nơi sống | "Ở Helsinki", "Mới chuyển đến Phần Lan" | `location` | Chỉ khi user tự nói — dùng resource matching |
| Sở thích | "Thích chạy bộ", "Đọc sách" | `interest` | Tự xuất hiện — dùng cho metaphor |

**Facts WISMO KHÔNG thu thập:**

| Loại | Lý do |
|------|-------|
| Giới tính | GDPR sensitive category — WISMO không phân biệt response theo giới |
| Tôn giáo | WISMO phi tôn giáo — biết tôn giáo user có thể bias response |
| Sức khỏe / thuốc | Ngoài scope, GDPR super sensitive — chỉ ghi contraindication nếu safety cần |
| Thu nhập / tài chính | Không liên quan counseling |

### 3.2 Personality (P6 — Personality Signal Detector)

Tính cách **SUY LUẬN từ cách user giao tiếp**. Tích lũy dần, confirm khi đủ tin cậy.

---

## 4. 7 Personality Dimensions

| Dimension | Giá trị | Detect từ đâu | Ảnh hưởng response |
|-----------|---------|---------------|-------------------|
| **Tone preference** | `direct` / `gentle` / `neutral` | Cách viết: cộc lốc → direct; emoji, dài dòng → gentle | Cách WISMO nói: thẳng hay vòng vo |
| **Verbosity** | `short` / `medium` / `long` | Độ dài tin nhắn user | Response dài hay ngắn |
| **Depth preference** | `surface` / `moderate` / `deep` | Câu ngắn → surface; hay hỏi "tại sao" → deep | Khai vấn nông hay sâu |
| **Experience level** | `beginner` / `intermediate` / `advanced` | Từ vựng: "thiền là gì" → beginner; "quán sát cảm thọ" → advanced | Giải thích nhiều hay ít |
| **Trust level** | `guarded` / `opening` / `open` | Session đầu → guarded; chia sẻ sâu dần → open | Khi nào đi sâu, khi nào dừng |
| **Emotional expressiveness** | `expressive` / `reserved` / `mixed` | Hay nói cảm xúc hay kìm nén, dùng từ mạnh hay nhẹ | LISTEN nhiều cho reserved, mirror cho expressive |
| **Help-seeking style** | `proactive` / `reactive` / `mixed` | Chủ động hỏi vs chờ WISMO hỏi | INQUIRY nhiều cho reactive, follow cho proactive |

### 4.1 Cách tích lũy dần

```
Mỗi turn → P6 chạy after-turn (1 LLM call nhẹ, ~60 tokens out):
  Output: {
    tone_signal: "direct",          (null nếu không đủ info)
    depth_signal: "moderate",
    verbosity_signal: "short",
    experience_signal: "beginner",
    expressiveness_signal: "reserved",
    help_seeking_signal: null,      (chưa đủ info)
    trust_signal: "guarded",
    confidence: 0.5
  }

Tích lũy → pending_signals trong user_preferences:

Turn 1: {tone: "direct", confidence: 0.4} → pending
Turn 3: {tone: "direct", confidence: 0.5} → pending
Turn 5: {tone: "direct", confidence: 0.7} → CONFIRM ✓
  → Update user_preferences.tone = "direct"
  → P3 turn sau dùng tone direct ngay

Threshold: confidence ≥ 0.7 → confirm
Trước khi confirm → dùng default (gentle, medium, moderate)
```

### 4.2 Tại sao detect mỗi turn, không cuối session

Turn 1 user nói cộc lốc mà WISMO reply dài dòng = trải nghiệm tệ. Detect sớm → adjust sớm. Mỗi turn detection cho phép real-time calibration.

---

## 5. P6 Personality Signal Contract (`personality.v1`)

| Field | Type | Allowed | Required | Fallback |
|-------|------|---------|:---:|--------|
| `schema_version` | string | `personality.v1` | ✓ | `personality.v1` |
| `source_turn_id` | UUID string | — | ✓ | current turn |
| `dimension` | string | 7 canonical values | ✓ | bỏ record nếu dimension lạ |
| `value` | string | enum theo dimension | ✓ | bỏ record nếu value lạ |
| `confidence` | float | 0.0–1.0 | ✓ | `0.5` |
| `evidence_excerpt` | string | short quote/paraphrase | ✗ | `""` |
| `apply_now` | boolean | — | ✓ | `false` khi confidence thấp |
| `expires_with_session` | boolean | — | ✓ | guest=`true`, registered=`false` |

**Runtime rules:**
- Personalizer chỉ dùng signal khi qua ngưỡng confidence và không conflict với distress severity hiện tại
- Một signal đơn lẻ không được override hard safety style cap
- Guest chỉ dùng personality signals trong lifecycle phiên hiện tại

---

## 6. P6 Celery Task

```python
# apps/personalization/tasks.py

@shared_task(bind=True, max_retries=3)
def detect_personality_signal(self, user_id: str, user_message: str, session_id: str):
    """
    P6: Chạy after-turn. Detect personality signal → tích lũy → confirm khi ≥ 0.7.
    """
    try:
        result = llm_facade.call(
            prompt=P6_DETECTION_PROMPT.format(user_message=user_message),
            step='P6',
            user_id=user_id,
        )
        signals = json.loads(result)

        PersonalityDetector().process_signals(user_id, signals, session_id)

    except Exception as exc:
        raise self.retry(exc=exc, countdown=5)
```

```python
# apps/personalization/services/personality_detector.py

class PersonalityDetector:
    """
    Nhận signals từ P6 → tích lũy → confirm khi confidence ≥ 0.7.
    Không tự quyết định response style — chỉ update user_preferences.
    """

    CONFIRM_THRESHOLD = 0.7

    def process_signals(self, user_id: str, signals: dict, session_id: str):
        prefs = UserPreference.objects.get_or_create(user_id=user_id)[0]
        pending = prefs.pending_signals or []

        for dimension, signal_value in signals.items():
            if dimension.endswith('_signal') and signal_value is not None:
                dim = dimension.replace('_signal', '')
                confidence = signals.get('confidence', 0.5)

                # Thêm vào pending
                pending.append({
                    'dimension': dim,
                    'value': signal_value,
                    'confidence': confidence,
                    'turn': session_id,
                })

                # Kiểm tra confirm
                if confidence >= self.CONFIRM_THRESHOLD:
                    self._confirm_dimension(prefs, dim, signal_value)

        prefs.pending_signals = pending[-50:]  # giữ 50 signals gần nhất
        prefs.save()

    def _confirm_dimension(self, prefs, dimension: str, value: str):
        """Update user_preferences field tương ứng."""
        field_map = {
            'tone': 'tone',
            'verbosity': 'verbosity',
            'depth': 'depth',
            'experience': 'experience_level',
            'trust': 'trust_level',
            'expressiveness': 'expressiveness',
            'help_seeking': 'help_seeking',
        }
        field = field_map.get(dimension)
        if field:
            setattr(prefs, field, value)
            prefs.save(update_fields=[field])
```

---

## 7. PersonalizerPolicy — Pure Python, 0ms

Personalizer quyết định response style từ profile + emotion hiện tại. **Rule-based, không gọi LLM.**

### 7.1 Priority rules

```
PRIORITY 1: Emotion severity LUÔN THẮNG (safety first)
  severity ≥ 7 → gentle, surface, short (bất kể profile nói gì)
  severity 4-6 → calm, moderate, medium
  severity ≤ 3 → theo profile preference

PRIORITY 2: Profile preference (khi severity ≤ 3)
  tone:         user_preferences.tone
  depth:        user_preferences.depth
  verbosity:    user_preferences.verbosity
  expressiveness → ảnh hưởng cách hỏi cảm xúc
  help_seeking  → ảnh hưởng WISMO chủ động hay đợi

PRIORITY 3: Context adjustment
  Turn ≤ 2 → encouraging, surface (chưa biết user)
  Reserved user → ít hỏi cảm xúc trực tiếp
  Reactive user → đợi user nói, không push

PRIORITY 4: Trust level cap
  guarded + depth=deep → cap thành moderate
  guarded → WISMO không hỏi sâu, tạo safe space trước
  opening → nhẹ nhàng đào sâu
  open    → có thể đưa insight mạnh hơn
```

### 7.2 PersonalizerPolicy implementation

```python
# apps/personalization/services/personalizer.py

@dataclass
class PersonalizationConfig:
    tone:            str   # gentle / calm / direct / encouraging
    depth:           str   # surface / moderate / deep
    response_length: str   # short / medium / long
    focus:           str   # empathy / insight / listening
    notes:           list[str]  # extra instructions cho P3


class PersonalizerPolicy:
    """
    Input: user_preferences + p1_signals (emotion.severity)
    Output: PersonalizationConfig → inject vào P3 prompt [STYLE] section
    Rule-based, 0ms, không gọi LLM.
    """

    def decide(self, user, p1_signals: dict) -> PersonalizationConfig:
        prefs = UserPreference.objects.get_or_create(user=user)[0]
        severity = p1_signals.get('emotion', {}).get('severity', 0)

        config = PersonalizationConfig(
            tone='gentle', depth='moderate', response_length='medium',
            focus='empathy', notes=[]
        )

        # ── PRIORITY 1: Severity LUÔN THẮNG ──
        if severity >= 7:
            config.tone = 'gentle'
            config.depth = 'surface'
            config.response_length = 'short'
            config.focus = 'empathy'
            config.notes.append(f'User distressed ({severity}/10) — be gentle, short, empathy first')
            return config

        if severity >= 4:
            config.tone = 'calm'
            config.depth = 'moderate'
            config.response_length = 'medium'

        # ── PRIORITY 2: Profile preferences ──
        if severity <= 3:
            config.tone = prefs.tone or 'gentle'
            config.depth = prefs.depth or 'moderate'
            config.response_length = prefs.verbosity or 'medium'

        # ── PRIORITY 3: Context adjustments ──

        # Trust cap — không ép user mở lòng khi còn guarded
        if prefs.trust_level == 'guarded' and config.depth == 'deep':
            config.depth = 'moderate'
            config.notes.append('Trust guarded — cap depth to moderate')

        # Expressiveness — reserved user: ít hỏi cảm xúc trực tiếp
        if prefs.expressiveness == 'reserved':
            config.notes.append('User reserved — avoid direct emotion questions, wait for sharing')

        # Help-seeking style
        if prefs.help_seeking == 'reactive':
            config.notes.append('User reactive — wait for them to share, do not push')
        elif prefs.help_seeking == 'proactive':
            config.notes.append('User proactive — can ask deeper questions')

        # Experience level
        if prefs.experience_level == 'beginner':
            config.notes.append('User beginner — explain concepts simply, avoid jargon')
        elif prefs.experience_level == 'advanced':
            config.notes.append('User advanced — can use deeper concepts')

        return config
```

### 7.3 Ví dụ outputs theo 3 user profiles

```
User A: tone=direct, depth=moderate, expressiveness=reserved, experience=beginner

  [STYLE]
  Tone: direct — user thích thẳng thắn
  Depth: moderate
  Length: short
  Note: User reserved — avoid direct emotion questions
  Note: User beginner — explain simply

  → WISMO: "Vai cứng = tín hiệu giận sắp bùng. Lần tới thấy vai cứng, bạn muốn làm gì?"
  Ngắn, thẳng, không hỏi "bạn cảm thấy thế nào?"

---

User B: tone=gentle, depth=deep, expressiveness=expressive, experience=intermediate

  [STYLE]
  Tone: gentle
  Depth: deep
  Length: medium
  Note: User expressive — can mirror emotions directly

  → WISMO: "Mình thấy bạn vừa nhận ra điều quan trọng — cơ thể luôn báo hiệu
            trước khi cảm xúc bùng. Khi nhận ra cảm giác vai cứng đó,
            bạn cảm thấy thế nào trong người?"
  Ấm hơn, sâu hơn, hỏi cảm xúc trực tiếp

---

User C: tone=neutral, help_seeking=reactive, depth=surface, severity=7

  [STYLE]
  Tone: gentle (severity override)
  Depth: surface (severity override)
  Length: short (severity override)
  Focus: empathy (severity override)
  Note: User stressed (7/10) — be gentle

  → WISMO: "Nghe bạn chia sẻ, mình cảm nhận bạn đang rất mệt.
            Bạn muốn nói thêm về điều đó không?"
  Ngắn, empathy first, không câu hỏi sâu
```

---

## 8. Profile Update Timeline

### 8.1 Canonical timeline

```
IMMEDIATE (turn 1):
  language = auto-detect từ message đầu tiên → user_preferences.language

AFTER EACH TURN (Celery, ~2s):
  P5: extract facts → memory_items (max 3 items, cosine dedup ≥ 0.9)
  P6: detect personality → pending_signals
    - 1 LLM call nhẹ (~60 tokens out)
    - Confirm khi confidence ≥ 0.7 → update user_preferences

AFTER SESSION (Celery):
  P7: journey summary (xuyên sessions + cases)

PER CASE:
  P9: goal & strategy (1 lần khi Phase 1→2)
  P4: case context (mỗi turn, tích lũy vào case)
```

### 8.2 Confirm timeline ước tính

| Giai đoạn | Confirmed | Pending |
|-----------|-----------|---------|
| Session 1 (turns 1-8) | language, tone hint, verbosity hint | experience, depth, expressiveness, trust, help-seeking |
| Session 3 (~24 turns) | + tone, verbosity, experience level | depth, expressiveness, trust, help-seeking |
| Session 5 (~40 turns) | + depth, expressiveness | trust, help-seeking |
| Session 10 (~80 turns) | + trust level, help-seeking style | (all stable) |

---

## 9. Profile Consumers — Ai dùng gì

| Consumer | Facts (P5) | Personality (P6) | Case context (P4) | Strategy (P9) |
|----------|:---:|:---:|:---:|:---:|
| P1 (Situation Analyzer) | — | — | — | — |
| P2 (Phase Evaluator) | — | experience, trust | context_gathered | strategy, goal |
| P3 (Response Generator) | memory items inject | tone, depth, verbosity, expressiveness | case context inject | pillar, key questions |
| PersonalizerPolicy | — | all 7 dimensions | — | — |
| Rule Engine | — | experience, trust | phase, readiness | — |
| RAG search | — | — | — | relevant_teaching |
| Contraindication check | sensitive tags | — | — | — |
| Escalation detector | — | trust | stalled detection | success_indicators |
| Resource matcher | location, occupation | — | — | — |
| P8 (Title) | — | — | topic | — |

---

## 10. Database Models — Profile Tables

```python
# apps/accounts/models.py

class UserProfile(models.Model):
    """
    Optional profile — user tự điền.
    Khác với user_preferences (system detect từ P6).
    """
    user       = models.OneToOneField('User', on_delete=models.CASCADE)
    age_range  = models.CharField(max_length=20, blank=True)  # 'under_18','18-25','26-35','36-50','50+'
    goal       = models.TextField(blank=True)                 # mục tiêu sử dụng
    language   = models.CharField(max_length=10, default='en')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class UserPreference(models.Model):
    """
    System-detected personality dimensions (P6).
    Không yêu cầu user điền — tích lũy tự nhiên.
    """
    user = models.OneToOneField('User', on_delete=models.CASCADE)

    # 7 personality dimensions
    tone             = models.CharField(max_length=20, default='gentle')      # direct/gentle/neutral
    verbosity        = models.CharField(max_length=20, default='medium')      # short/medium/long
    depth            = models.CharField(max_length=20, default='moderate')    # surface/moderate/deep
    experience_level = models.CharField(max_length=20, default='beginner')    # beginner/intermediate/advanced
    trust_level      = models.CharField(max_length=20, default='guarded')     # guarded/opening/open
    expressiveness   = models.CharField(max_length=20, default='mixed')       # expressive/reserved/mixed
    help_seeking     = models.CharField(max_length=20, default='mixed')       # proactive/reactive/mixed

    # Accumulation
    pending_signals  = models.JSONField(default=list)  # signals chưa confirm

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

## 11. Guest Profile — Ephemeral

```python
# Guest session store (không persist vào DB)

guest_temp_profile = {
    'occupation': None,
    'facts': [],              # list of P5 items (tạm thời)
    'temp_preferences': {
        'tone': 'gentle',     # default
        'verbosity': 'medium',
        'depth': 'moderate',
        'trust_level': 'guarded',
    },
    'temp_state': {
        'emotion_tag': None,
        'severity_score': 0,
    }
}
```

**Rules:**
- Được update trong phiên để response chính xác hơn
- Không xuất hiện trong Settings/Memory screen
- Kết thúc session mà không login/register → xóa toàn bộ
- Login/register khi session còn mở → promote public_safe facts sang user thật

---

## 12. Constraints cho Agent Implementation

### Files cần tạo

```
apps/personalization/
├── __init__.py
├── services/
│   ├── __init__.py
│   ├── personalizer.py        ← PersonalizationConfig, PersonalizerPolicy.decide()
│   └── personality_detector.py ← PersonalityDetector.process_signals()
└── tasks.py                   ← detect_personality_signal Celery task

apps/accounts/
├── models.py                  ← UserProfile, UserPreference (thêm vào existing)
└── services/
    └── profile_service.py     ← ProfileService facade cho cross-app reads
```

### Hard rules cho agent

1. `PersonalizerPolicy` là pure Python — không gọi LLM, không query DB trong request path
2. Emotion severity override xảy ra **trước** profile lookup — không có ngoại lệ
3. `personality_detector.py` chỉ update `user_preferences` — không mutate chat/session records
4. Guest signals expire khi session kết thúc — không persist vào `user_preferences` table
5. `pending_signals` giữ tối đa 50 entries để tránh bloat
6. `PersonalityDetector` không import từ `chat.views`, không biết session/case internals
7. Trust cap: `guarded` + `depth=deep` → luôn cap thành `moderate` — không exception

### Test suite tối thiểu

```
tests/unit/personalization/
├── test_personalizer_policy.py
│   ├── test_severity_7_overrides_profile_to_gentle_short
│   ├── test_severity_4_6_calm_moderate
│   ├── test_low_severity_uses_profile_prefs
│   ├── test_trust_guarded_caps_depth
│   ├── test_reserved_user_avoids_emotion_questions
│   ├── test_reactive_user_notes_wait
│   └── test_direct_tone_applied
├── test_personality_detector.py
│   ├── test_signal_accumulates_before_threshold
│   ├── test_signal_confirmed_at_07_confidence
│   ├── test_unknown_dimension_skipped
│   ├── test_guest_signals_expire_with_session
│   └── test_pending_signals_capped_at_50
└── test_p6_contract.py
    ├── test_invalid_dimension_rejected
    └── test_unknown_value_rejected
```

---

## 13. Cross-references

- **Facts storage:** `memory/spec.md` — P5 extraction, dedup, sensitivity rules
- **P6 prompt text:** `prompts/spec.md` — Section 8.7
- **P5 prompt text:** `prompts/spec.md` — Section 8.6
- **PersonalizationConfig → P3 prompt:** `prompts/spec.md` — [STYLE] section trong P3 template
- **Orchestrator call:** `architecture/spec.md` — Section 7.9A step 6 (RuleEngine nhận personality context)
- **Safety override:** `safety/spec.md` — SafetyDecision constraints có thể override Personalizer output
- **Database schema:** `database/spec.md` — `user_profiles`, `user_preferences` tables đầy đủ
