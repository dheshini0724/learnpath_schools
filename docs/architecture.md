# Architecture

## System Overview

LearnPath for Schools is a closed-loop adaptive learning platform for school students in grades 5 to 12. The system follows a continuous cycle: **Diagnose -> Support -> Observe -> Adapt -> Measure**.

```
+------------------+     +------------------+     +------------------+
|   Frontend SPA   |<--->|  FastAPI Backend  |<--->|  JSON Storage    |
| (static/index.html)    |     (app.py)      |     | (store.json)     |
+------------------+     +------------------+     +------------------+
                               |       |
                    +----------+       +----------+
                    |                              |
             +------+------+            +---------+--------+
             | Engine       |            | LLM Adapter      |
             | (engine.py)  |            | (mock / real)    |
             | Pure Python  |            | Guardrails       |
             | No LLM deps  |            | Safety Screen    |
             +--------------+            +------------------+
```

## Component Details

### 1. Frontend (static/index.html)
- Single Page Application (SPA) served as a static file.
- Dark/light theme with exact CSS variables from specification.
- Left sidebar navigation: Chats, Mock Test, Memory Tree, Library Vault, Progress.
- Mobile responsive: sidebar collapses to hamburger menu.
- WCAG 2.2 AA compliant (4.5:1 contrast, 44x44px touch targets, focus outlines).
- All API calls via `fetch()` to `/api/...` endpoints.

### 2. Backend (app.py)
- FastAPI application serving REST API and static files.
- Storage: `store.json` (JSON file) with planned PostgreSQL migration path.
- Authentication: JWT tokens, bcrypt password hashing, role-based access.
- Roles: student, guardian, teacher, admin.
- Event logging: append-only `events.jsonl`.

### 3. Engine (engine.py)
- **Pure Python** -- zero LLM imports.
- Bayesian Knowledge Tracing (BKT): p_init=0.2, slip=0.1, guess=0.2, transit=0.1, threshold=0.9.
- Diagnostic scoring: 0.8 (all correct), 0.5 (partial), 0.2 (none correct).
- Concept selection: prerequisite-aware, lowest-mastery-first.
- Question selection: prefer unseen, difficulty scaling for strong students.
- Hint ladder: 4 levels, escalate on error, de-escalate after 2 unaided correct.
- Misconception diagnosis: option-linked misconception IDs or "gap".
- Recurring mistake detection: same misconception 2+ times per concept.
- Repair cycle: contrasting example -> practice -> check (no hints).
- Spaced review: 1, 3, 7, 21 days after mastery.
- Transfer check: correct + unaided + mastery >= 0.9 = mastered.
- Generic condition: fixed sequence, fixed hint level 2, no engine calls.
- Mock-test scoring: +1 correct, -0.25 wrong, 0 skipped.

### 4. LLM Adapter
- Single class with `complete(system, user, max_tokens)` method.
- Mock provider by default (returns educational responses without external API).
- Real provider swappable via environment variable.
- Three jobs only: personalize hints, explain wrong answers, answer Ask Anything.
- LLM NEVER decides mastery, correctness, next concept/question, or hint level.

### 5. Safety & Privacy
- Safety screen: keyword detection for self-harm, abuse, bullying, sexual, violence.
- Unsafe messages blocked with helpline info (Tele-MANAS 14416, Emergency 112).
- PII redaction: phone numbers, email addresses, Aadhaar patterns.
- Guardian consent for minors (configurable age threshold).
- Complete data deletion endpoint.

## Data Flow

### Practice Flow
1. Engine selects concept (lowest mastery, prerequisites met).
2. Engine selects question (unseen preferred, difficulty adjusted).
3. Student answers.
4. Engine diagnoses misconception from option mapping.
5. BKT updates mastery.
6. Hint ladder adjusts level.
7. If recurring misconception: trigger repair cycle.
8. Repeat.

### Mock Test Flow
1. Student selects source (subject, upload, free text).
2. Server creates test with timer (stores start_time + time_limit).
3. Questions served WITHOUT answer keys.
4. Student submits OR server auto-expires at time limit.
5. Server scores and returns results WITH answer keys.
6. Mastery updated ONLY for teacher-reviewed curriculum tests (no hints).

## Storage Schema (store.json)

```json
{
  "users": {},
  "students": {},
  "guardian_links": {},
  "consent_records": {},
  "masteries": {},
  "attempts": [],
  "mock_tests": {},
  "chat_history": {},
  "hint_states": {},
  "misconception_log": [],
  "seen_questions": {},
  "review_counts": {},
  "mastery_dates": {},
  "conditions": {}
}
```

## Migration Path

Current storage is JSON file (store.json). Target is PostgreSQL with Alembic migrations. The engine and tests are designed to survive this change unchanged -- the engine operates on plain Python data structures, not database objects.
