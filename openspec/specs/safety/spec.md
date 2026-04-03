# Safety Domain Spec — Crisis, Contraindication & Safety State Machine

**Source:** WISMO Project Specification v18, Section 5 (trích lọc và tổng hợp)  
**Scope:** `apps/safety/` — crisis detection, safety state machine, contraindication, escalation, scope guard  
**Owner app:** `safety`  
**Không thuộc scope:** session/message persistence, prompt building, memory extraction, provider routing

---

## 1. Vai trò và Ranh giới

`safety` là **hard constraint layer** — chạy trước P3, quyết định cứng những gì P3 được/không được làm. LLM không có quyền override safety state.

**Vị trí trong canonical pipeline (Section 7.9A):**

```
P1 + P2 output
    ↓
SafetyStateMachine.evaluate() ← HARD GATE, step 5
    ↓
RuleEngine (chỉ quyết định TRONG biên safety đã cấp)
    ↓
PromptBuilder + P3
    ↓
ResponseValidator (check constraints HARD, không soft)
```

**Ownership:**
- Owns: `CrisisEvent`, `AttackLog` (qua service, không direct write từ app khác)
- Exposes: `SafetyDecision` object → Orchestrator → PromptBuilder, ResponseValidator, telemetry
- Forbidden: `safety` không direct write `Message`, `Session`, `UserCase` ngoài orchestrated path. Không import `chat.views`.

**Verification note:** Mọi rule ở spec này chỉ được coi là "implemented correctly" khi vượt qua bộ Section 11A Safety Eval (crisis recall = 0 FN trên curated set, medical advice violation = 0).

---

## 2. Crisis Detection — 4 Risk Tiers

### 2.1 Bảng tiers

| Tier | Mô tả | Ví dụ | Severity |
|------|--------|-------|:---:|
| **A — Active intent/plan/means** | Có kế hoạch cụ thể hoặc đang hành động | "Tôi đã chuẩn bị rồi", "Tôi có thuốc rồi", "Tối nay tôi sẽ..." | Critical |
| **B — Ideation, không rõ plan** | Nghĩ đến tự hại nhưng chưa có plan | "Tôi muốn chết", "Không muốn sống nữa" | High |
| **C — Hopelessness / passive death wish** | Tuyệt vọng, muốn biến mất nhưng không active | "Nếu biến mất chắc tốt hơn", "Mọi thứ vô nghĩa" | Moderate |
| **D — Third-party risk** | User nói về người khác có nguy cơ | "Bạn tôi muốn chết", "Chồng tôi nói muốn tự tử" | High (indirect) |

### 2.2 Response protocol per tier

**TIER A — Active intent (critical):**

```
Detection: keyword match OR P1 classify tier_A
Response:
  1. Hotline FULL-SCREEN overlay (không phải text nhỏ)
     📞 Kriisipuhelin: 09 2525 0111 (24/7)
     💬 Hätäkeskus: 112 (nếu nguy hiểm tức thì)
  2. WISMO text (dưới overlay):
     "Mình nghe bạn, và mình lo lắng cho bạn ngay lúc này.
      Xin hãy gọi ngay số trên — họ có thể giúp bạn ngay.
      Mình ở đây, nhưng họ được đào tạo cho tình huống này."
  3. DỪNG chat flow — chỉ hiện hotline + "Mình vẫn ở đây"
  4. Log: crisis_event (tier=A, anonymous — không lưu user_id)
  5. Alert: email admin NGAY LẬP TỨC
  6. Turns tiếp: CHỈ lắng nghe, nhắc hotline mỗi response
  7. KHÔNG tạo/update case, KHÔNG run P4/P5/P6
```

**TIER B — Ideation (high):**

```
Detection: keyword match OR P1 classify tier_B
Response:
  1. Hotline inline (KHÔNG full-screen)
  2. WISMO text:
     "Mình nghe bạn. Khi mệt đến mức đó, cảm giác thật nặng nề.
      Bạn đang rất can đảm khi chia sẻ điều này.
      
      📞 Kriisipuhelin: 09 2525 0111 (24/7)
      💬 Sekasin-chat: sekasin.fi
      
      Mình muốn chắc chắn bạn an toàn.
      Bạn có đang nghĩ đến việc tự làm hại mình không?"
  3. Tiếp tục chat: CÓ, nhưng CHỈ LISTEN mode
  4. Log: crisis_event (tier=B, anonymous)
  5. Alert: email admin trong 5 phút
  6. User confirm → upgrade Tier A
  7. User deny → giữ flag, downgrade thành guarded normal flow
```

**TIER C — Hopelessness (moderate):**

```
Detection: P1 classify (KHÔNG dùng keyword exact match)
Response:
  1. Hotline KHÔNG hiện tự động (chỉ khi user hỏi hoặc severity tăng)
  2. WISMO text:
     "Mình nghe thấy bạn đang rất mệt. Cảm giác đó thật nặng nề.
      Bạn muốn chia sẻ thêm — điều gì khiến bạn cảm thấy như vậy?"
  3. Tiếp tục chat: CÓ — LISTEN mode, không khai vấn sâu
  4. Log: crisis_event (tier=C)
  5. Monitor: nếu severity tăng → upgrade
```

**TIER D — Third-party risk (high indirect):**

```
Response:
  "Mình lo lắng khi nghe bạn nói điều này.
   Người bạn/người thân đó có thể cần giúp đỡ ngay.
   
   📞 Kriisipuhelin: 09 2525 0111 (24/7) — họ tư vấn cho cả người thân
   
   Bạn có thể kể thêm về họ không?"
```

---

## 3. Safety State Machine — 7 trạng thái

### 3.1 State enum

```python
# apps/safety/services/safety_state_machine.py

class ConversationSafetyState(str, Enum):
    NORMAL                  = 'normal'
    GUARDED                 = 'guarded'
    MODERATE_RISK_SAFE_ONLY = 'moderate_risk_safe_only'
    HIGH_RISK_LISTEN_ONLY   = 'high_risk_listen_only'
    CRISIS_ONLY             = 'crisis_only'
    BLOCKED_MINOR           = 'blocked_minor'
    BLOCKED_OUT_OF_SCOPE    = 'blocked_out_of_scope'
```

### 3.2 State selection priority (cao → thấp)

```
BLOCKED_MINOR → CRISIS_ONLY → HIGH_RISK_LISTEN_ONLY
→ MODERATE_RISK_SAFE_ONLY → BLOCKED_OUT_OF_SCOPE
→ GUARDED → NORMAL
```

`GUARDED`: dành cho turn không ở mức crisis/contraindication rõ ràng nhưng có dấu hiệu mong manh — severity cao, shame spiral, dependency cue, trust còn rất thấp. P3 phải giữ câu ngắn, reflection-first, không dùng câu hỏi sâu hoặc RAG.

### 3.3 Transition table

| Current state | Trigger | Guard condition | Next state | Side effects |
|---|---|---|---|---|
| `NORMAL` | P1 detect fragility/shame spiral/severity≥7 nhưng chưa moderate | Không crisis, không minor | `GUARDED` | Giảm độ dài response, tắt deep probing, gắn telemetry `guarded_turn=true` |
| `NORMAL`/`GUARDED` | P1 detect contraindication moderate OR memory có moderate flag | Không high risk/crisis | `MODERATE_RISK_SAFE_ONLY` | Chỉ whitelist safe reflections, chặn body-based prompt |
| `NORMAL`/`GUARDED`/`MODERATE_RISK_SAFE_ONLY` | P1 detect high-risk contraindication OR memory flag high risk | Không crisis tier A/B | `HIGH_RISK_LISTEN_ONLY` | P3 locked ở listen mode + grounding ngắn, không RAG, tạo `crisis_event` |
| Bất kỳ trừ `BLOCKED_MINOR` | Crisis tier A/B detect | Crisis signal đủ ngưỡng | `CRISIS_ONLY` | Crisis protocol, hotline/resource copy, alert admin, dừng normal counseling |
| Bất kỳ | Minor detect | User age < 18 hoặc self-declared minor | `BLOCKED_MINOR` | Không chat tiếp, show block copy + external help |
| `NORMAL`/`GUARDED` | Out-of-scope hard block | `in_scope=false` và `can_partially_help=false` | `BLOCKED_OUT_OF_SCOPE` | Trả copy honest-limit + redirect, không run P3 counseling |
| `CRISIS_ONLY` | Turn sau không còn crisis, còn high risk | Crisis hạ, risk còn | `HIGH_RISK_LISTEN_ONLY` | Ghi de-escalation note, giữ listen-only |
| `HIGH_RISK_LISTEN_ONLY` | Turn sau ổn hơn, không còn high risk, còn moderate | Safety review pass | `MODERATE_RISK_SAFE_ONLY` | Mở lại whitelist safe responses |
| `MODERATE_RISK_SAFE_ONLY`/`GUARDED` | Turn sau không còn risk/fragility signal | Không persistent block | `NORMAL` | Bỏ guard flags cho turn hiện tại |

### 3.4 Forbidden transitions

```
❌ Không được nhảy trực tiếp CRISIS_ONLY → NORMAL trong cùng turn
❌ Không được để P3 override safety state
❌ Không được auto-downgrade chỉ vì model output nghe "ổn hơn"
   → Downgrade phải dựa trên turn mới + guard conditions
❌ Không được downgrade nhiều hơn 1 bậc trong cùng turn
```

### 3.5 SafetyDecision — canonical output object

```python
@dataclass
class SafetyDecision:
    """
    Output của SafetyStateMachine. Đây là object đi vào PromptBuilder,
    ResponseValidator, telemetry và SSE status mapper.
    Không được tạo SafetyDecision bằng cách khác.
    """
    state:              ConversationSafetyState
    constraints:        dict          # banned_content, allowed_exercises, required_content, max_length
    crisis_tier:        str | None    # A/B/C/D hoặc None
    requires_hotline:   bool
    hotline_display:    str           # 'fullscreen' / 'inline' / 'none'
    alert_admin:        bool
    block_case_update:  bool          # True khi crisis tier A — không update case
    block_after_turn:   bool          # True khi crisis tier A — không run P4/P5/P6
    idempotency_key:    str           # message_id — đảm bảo side effects idempotent
```

---

## 4. Contraindication System

### 4.1 Vấn đề cần giải quyết

Contraindication không thể phụ thuộc hoàn toàn vào P1 detect + P3 follow instruction vì LLM có thể:
- Bỏ sót contraindication signal
- Diễn giải sai: "user ổn rồi" → suggest body scan (nguy hiểm)
- "Sáng tạo" vượt boundary: tự thêm exercise không an toàn

**Giải pháp:** Safety State Machine đọc memory contraindication flags và quyết định CỨNG trước P3.

### 4.2 Banned content table per state

| Content | NORMAL | GUARDED | MODERATE | HIGH RISK | CRISIS |
|---------|:------:|:-------:|:--------:|:---------:|:------:|
| Body scan / quét cơ thể | ✅ | ✅ (cẩn thận) | ❌ | ❌ | ❌ |
| Eyes closed / nhắm mắt | ✅ | ✅ | ❌ | ❌ | ❌ |
| Observe bodily sensation | ✅ | ✅ | ❌ | ❌ | ❌ |
| Deep breathing / thở sâu | ✅ | ✅ | ✅ (4-7-8 only) | ❌ | ❌ |
| Long silence / im lặng lâu | ✅ | ❌ | ❌ | ❌ | ❌ |
| Visualization / hình dung | ✅ | ❌ | ❌ | ❌ | ❌ |
| Meditation / thiền | ❌ (Phase 2) | ❌ | ❌ | ❌ | ❌ |
| Socratic questions | ✅ | ✅ | ✅ | ❌ | ❌ |
| RAG knowledge (TEACH) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Exercise suggestions | ✅ (user đề xuất) | Whitelist only | Whitelist only | ❌ | ❌ |

### 4.3 Contraindication memory persistence

```python
# Khi phát hiện contraindication:
# P5 tạo memory_item với sensitivity='clinical_sensitive'
# SafetyStateMachine đọc memory tags MỌI request

"""
memory_item khi có contraindication:
  text: "Flashback khi body scan — trauma thời thơ ấu"
  tags: ["contraindication"]
  sensitivity: "clinical_sensitive"
  recall_policy: "never_recall"
  usage_scope: "safety_only"

SafetyStateMachine logic:
  IF user có memory item với tag="contraindication":
    → State KHÔNG BAO GIỜ = NORMAL cho session đó
    → Phải có ít nhất MODERATE_RISK_SAFE_ONLY
"""
```

### 4.4 Auto-downgrade rule

```
Phase 1 (MVP): KHÔNG auto-downgrade safety state.
  - HIGH → MODERATE: CHỈ admin manual
  - MODERATE → NORMAL: CHỈ admin manual (Phase 2)
  
Lý do: LLM không đủ tin cậy để đánh giá "user đã an toàn".
  Sai lệch type I (false negative) có hậu quả nghiêm trọng hơn
  sai lệch type II (false positive = WISMO quá thận trọng).
```

---

## 5. SafetyStateMachine — Implementation

```python
# apps/safety/services/safety_state_machine.py

class SafetyStateMachine:
    """
    HARD RULES. Chạy TRƯỚC P3 (step 5 trong canonical pipeline).
    LLM KHÔNG override được output của machine này.
    Input: P1Output signals + memory tags + user history
    Output: SafetyDecision
    """

    def evaluate(self, user, p1_signals: dict) -> SafetyDecision:
        # 1. Minor check (highest priority)
        if self._is_minor(user, p1_signals):
            return self._blocked_minor()

        # 2. Crisis check
        crisis_tier = self._detect_crisis(p1_signals)
        if crisis_tier in ('A', 'B'):
            return self._crisis_decision(crisis_tier, p1_signals)

        # 3. Out-of-scope check
        if p1_signals.get('in_scope') is False and not p1_signals.get('can_partially_help'):
            return self._out_of_scope_decision()

        # 4. Contraindication check (đọc memory flags)
        memory_flags = self._load_memory_flags(user.id)
        contraindication_level = self._evaluate_contraindication(
            p1_signals, memory_flags
        )

        if contraindication_level == 'high':
            return self._high_risk_decision(p1_signals)
        if contraindication_level == 'moderate':
            return self._moderate_risk_decision(p1_signals)

        # 5. Fragility/guarded check
        if self._should_guard(p1_signals):
            return self._guarded_decision(p1_signals)

        # 6. Crisis tier C (hopelessness)
        if crisis_tier == 'C':
            return self._tier_c_decision(p1_signals)

        # 7. Default NORMAL
        return self._normal_decision()

    def _detect_crisis(self, p1_signals: dict) -> str | None:
        """Kết hợp keyword match + P1 classification."""
        ...

    def _load_memory_flags(self, user_id: str) -> dict:
        """Gọi MemoryManager facade — không import memory models trực tiếp."""
        from memory.services.memory_manager import MemoryManager
        return MemoryManager().get_safety_flags(user_id)

    def _should_guard(self, p1_signals: dict) -> bool:
        severity = p1_signals.get('emotion', {}).get('severity', 0)
        has_shame = p1_signals.get('has_shame_spiral', False)
        has_dependency = p1_signals.get('has_dependency_cue', False)
        return severity >= 7 or has_shame or has_dependency
```

---

## 6. ResponseValidator — Safety Constraint Enforcement

### 6.1 Vị trí trong pipeline

`ResponseValidator` là step bắt buộc (step 10 trong 7.9A). Nó nhận `safety_constraints` từ `SafetyDecision` và check HARD — không phải soft warning.

```python
def validate_safety_constraints(
    self, response_text: str, constraints: dict
) -> list[Violation]:
    """HARD check — luôn regenerate nếu có violation, KHÔNG log only."""

    violations = []
    text_lower = response_text.lower()

    # Check banned content
    for banned in constraints.get('banned_content', []):
        if banned.lower() in text_lower:
            violations.append(Violation(
                type='safety_banned_content',
                severity='HARD',
                detail=f'Banned in state {constraints["state"]}: "{banned}"'
            ))

    # Check exercise whitelist
    if constraints.get('allowed_exercises') != 'all':
        whitelist = constraints.get('allowed_exercises', [])
        exercise_keywords = [
            'bài tập', 'exercise', 'thở', 'breathing', 'body scan',
            'grounding', 'quan sát cơ thể', 'hít thở',
        ]
        for kw in exercise_keywords:
            if kw in text_lower:
                if not any(ex.lower() in text_lower for ex in (whitelist or [])):
                    violations.append(Violation(
                        type='exercise_not_whitelisted', severity='HARD',
                        detail=f'Exercise keyword "{kw}" not in whitelist'
                    ))

    # Check required content (vd: crisis copy phải có hotline)
    for required in constraints.get('required_content', []):
        if required.lower() not in text_lower:
            violations.append(Violation(
                type='missing_required', severity='HARD',
                detail=f'Missing required content: "{required}"'
            ))

    return violations
```

### 6.2 Regeneration policy

```
Violation → REGENERATE (tối đa 2 lần)
  Attempt 1: regenerate + thêm explicit constraint reminder vào prompt
  Attempt 2: regenerate
  Vẫn fail → SAFE FALLBACK (pre-written generic response)

→ Không bao giờ gửi violated response đến user
→ Mọi violation phải ghi telemetry để phát hiện pattern
```

---

## 7. Human Escalation — Khi WISMO không đủ

### 7.1 5 triggers escalation

| Trigger | Dấu hiệu | WISMO action |
|---------|-----------|-------------|
| Stalled progress | Cùng topic 5+ sessions, severity không giảm | "Mình nghĩ chuyên gia có thể mở góc nhìn mà mình không thể." |
| User yêu cầu | "Có ai tôi có thể nói chuyện không?" | Validate + cung cấp resources ngay |
| Scope limitation | Cần medication, trauma therapy, diagnosis | Redirect + offer mindfulness angle |
| Contraindication HIGH | Safety concern rõ ràng | "An toàn của bạn là ưu tiên số 1." |
| Crisis tier A/B | Active/ideation | Crisis protocol đầy đủ |

### 7.2 EscalationDetector

```python
# apps/safety/services/escalation_detector.py

class EscalationDetector:
    """
    Phát hiện khi nào WISMO nên chủ động gợi ý chuyên gia.
    Khác với crisis detection — đây là long-term pattern, không phải immediate.
    """

    STALL_THRESHOLD_SESSIONS = 5
    STALL_SAME_TOPIC_MIN = 3

    def check_stalled(self, user_id: str, case_id: str) -> bool:
        """Cùng topic qua nhiều sessions mà severity không giảm."""
        ...

    def check_user_request(self, p1_signals: dict) -> bool:
        """User chủ động hỏi về chuyên gia."""
        return p1_signals.get('requests_professional', False)
```

### 7.3 ResourceMatcher — Finnish hotlines

```python
# apps/safety/data/finland_resources.py

FINLAND_CRISIS_RESOURCES = {
    'crisis_immediate': {
        'name': 'Kriisipuhelin',
        'number': '09 2525 0111',
        'hours': '24/7',
        'url': None,
    },
    'emergency': {
        'name': 'Hätäkeskus',
        'number': '112',
        'hours': '24/7',
    },
    'youth_chat': {
        'name': 'Sekasin-chat',
        'url': 'sekasin.fi',
        'hours': '24/7',
    },
    'mental_health': {
        'name': 'Mielenterveystalo',
        'url': 'mielenterveystalo.fi',
        'hours': 'Business hours',
    },
}
```

---

## 8. Input Sanitization & Attack Detection

### 8.1 InputGuard — bước đầu tiên trong pipeline

```python
# apps/safety/services/input_guard.py

class InputGuard:
    """
    Step 1 trong canonical pipeline (trước mọi thứ khác).
    Chặn injection, jailbreak, empty input, quá dài.
    """

    MAX_INPUT_LENGTH = 2000  # characters

    INJECTION_PATTERNS = [
        r"ignore previous instructions",
        r"forget everything",
        r"you are now",
        r"pretend you are",
        r"act as if",
        r"system prompt",
    ]

    def check(self, input_text: str) -> InputGuardResult:
        if not input_text.strip():
            return InputGuardResult(passed=False, reason='empty_input')

        if len(input_text) > self.MAX_INPUT_LENGTH:
            return InputGuardResult(passed=False, reason='too_long')

        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, input_text, re.IGNORECASE):
                self._log_attack(input_text, 'injection')
                return InputGuardResult(passed=False, reason='injection_attempt')

        return InputGuardResult(passed=True)

    def _log_attack(self, input_text: str, attack_type: str):
        AttackLog.objects.create(
            session_hash=self._hash_session(),
            attack_type=attack_type,
            blocked=True,
            input_snippet=input_text[:50],
        )
```

---

## 9. Constraints cho Agent Implementation

### Files cần tạo

```
apps/safety/
├── __init__.py
├── models.py                      ← CrisisEvent, AttackLog (owned by safety)
├── services/
│   ├── __init__.py
│   ├── safety_state_machine.py    ← SafetyStateMachine + SafetyDecision
│   ├── crisis_detector.py         ← keyword + P1-signal based detection
│   ├── input_guard.py             ← InputGuard (step 1 pipeline)
│   ├── escalation_detector.py     ← EscalationDetector
│   └── resource_matcher.py        ← Finnish resources lookup
└── data/
    └── finland_resources.py       ← Crisis hotlines dict
```

### Hard rules cho agent

1. `SafetyStateMachine.evaluate()` phải chạy ở step 5 canonical pipeline — không có exception
2. `SafetyDecision` là object canonical — không tạo ad-hoc safety dict ở nơi khác
3. ResponseValidator nhận `safety_constraints` như parameter — không tự query safety state
4. `crisis_events` table KHÔNG lưu `user_id` — anonymous bằng `session_hash`
5. Contraindication memory flag downgrade CHỈ bằng admin manual — không auto-downgrade
6. `BLOCKED_MINOR` là state cao nhất priority — check minor trước mọi thứ khác
7. Crisis tier A → `block_case_update=True`, `block_after_turn=True` — không chạy P4/P5/P6

### Test suite tối thiểu

```
tests/unit/safety/
├── test_safety_state_machine.py
│   ├── test_minor_detected_returns_blocked_minor
│   ├── test_crisis_tier_a_returns_crisis_only
│   ├── test_crisis_tier_b_returns_crisis_only
│   ├── test_out_of_scope_returns_blocked
│   ├── test_contraindication_high_returns_high_risk
│   ├── test_contraindication_moderate_returns_moderate
│   ├── test_fragility_returns_guarded
│   ├── test_normal_returns_normal
│   ├── test_state_priority_order
│   └── test_forbidden_transition_crisis_to_normal_same_turn
├── test_response_validator.py
│   ├── test_banned_content_in_high_risk_blocked
│   ├── test_body_scan_blocked_in_moderate
│   ├── test_exercise_not_whitelisted_blocked
│   ├── test_missing_hotline_in_crisis_blocked
│   ├── test_valid_response_passes
│   └── test_regeneration_on_hard_violation
├── test_input_guard.py
│   ├── test_empty_input_blocked
│   ├── test_too_long_input_blocked
│   ├── test_injection_pattern_blocked
│   └── test_normal_input_passes
└── test_crisis_detection.py
    ├── test_tier_a_keywords_detected
    ├── test_tier_b_ideation_detected
    ├── test_tier_c_hopelessness_no_keyword
    └── test_third_party_risk_detected
```

---

## 10. Cross-references

- **Orchestrator position:** `architecture/spec.md` — Section 7.9A step 5 (SafetyStateMachine là canonical hard gate)
- **Memory flags:** `memory/spec.md` — `clinical_sensitive` items, `get_safety_flags()` facade
- **Banned content list:** đây là source of truth — `ResponseValidator` trong `llm/spec.md` implement enforcement
- **Model evaluation:** Section 11A eval suite — crisis recall 0 FN, medical advice violation 0 là release gate bắt buộc
- **Telemetry:** `telemetry/spec.md` — `crisis_events` table, alert triggers
- **Product principles:** `product/spec.md` — clinical boundary và "không gây hại" principles
