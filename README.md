# LearnPath for Schools — Adaptive AI Tutor for Grades 5 to 12

**LearnPath for Schools** is a closed-loop adaptive learning platform built specifically for school students in Grades 5 to 12. Unlike a traditional chatbot, it implements a deterministic pedagogical loop:
1. **Diagnose**: Pre-assess student knowledge using diagnostic items and prerequisite DAGs.
2. **Support**: Deliver scaffolded 4-level hint ladders tailored to student performance.
3. **Observe**: Classify student responses against a verified misconception taxonomy.
4. **Adapt**: Escalate hints on errors, fade scaffolding on success, and launch contrasting-example repair cycles on recurring mistakes.
5. **Measure**: Verify genuine retention with unassisted transfer problems, schedule spaced reviews (1, 3, 7, 21 days), and measure experimental learning gain (Cohen's $d$).

---

## Non-Negotiable Child Safety & Launch Gate Rules

- **Launch Gate**: Marked as **PENDING** in `docs/launch-gate.md`. No real student data may be stored until signed off by a human administrator.
- **Guardian Consent**: Mandated for all students under 18 (configurable in `config.py`). Versioned consent (`v1.0`) and timestamps are recorded in the audit trail.
- **Answer Key Security**: Answer keys **never** reach the browser before test submission. Server-side timing enforces auto-submission at zero seconds.
- **Pure-Python Learning Engine**: Mastery, correctness, hint levels, and question selection are determined strictly by `engine.py` using Bayesian Knowledge Tracing ($p_{init}=0.2, p_{transit}=0.1, p_{slip}=0.1, p_{guess}=0.2, \text{threshold}=0.90$). The LLM never decides pedagogy.
- **Safety Screen & Helplines**: Automated screening blocks self-harm, abuse, bullying, sexual content, and violence. It immediately provides verified Indian helpline numbers (Tele-MANAS `14416`, Emergency `112`).
- **PII Redaction**: Phone numbers, emails, and Aadhaar patterns are redacted before storage or logging.

---

## Visual Design & Theme System (WCAG 2.2 AA)

Built with a left-sidebar card layout using the exact CSS variables required by specification:

| Theme | Background (`--bg`) | Card Panel (`--panel`) | Sidebar (`--side`) | Text (`--tx`) | Accent (`--ac`) | Success (`--ok`) | Danger (`--bad`) |
|-------|:-------------------:|:---------------------:|:------------------:|:-------------:|:---------------:|:----------------:|:----------------:|
| **Dark (Default)** | `#0f1115` | `#171a21` | `#12151b` | `#e8ebf2` | `#3b82f6` | `#22c55e` | `#ef4444` |
| **Light (Toggle)**  | `#f4f6fa` | `#ffffff` | `#eef1f7` | `#14171f` | `#2563eb` | `#16a34a` | `#dc2626` |

- **Contrast**: WCAG 2.2 AA compliance (4.5:1 minimum contrast for body text).
- **Touch Targets**: Minimum 44x44px for buttons, inputs, and interactive cards.
- **Focus Rings**: 3px solid `--ac` with 2px offset.

---

## Step-by-Step Instructions to Open & Run in VS Code

### Step 1: Open in VS Code
Open your VS Code editor, press `Ctrl + O` (or `File > Open Folder...`), and select:
```
C:\Users\Dheshini\.gemini\antigravity\scratch\learnpath_schools
```

### Step 2: Open Terminal
Press `Ctrl + ` ` ` (backtick) or select **Terminal > New Terminal** in VS Code.

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Run the Complete Test Suite (All 87 Tests)
```bash
python -m pytest tests/ -v
```
*All 87 tests validate engine BKT, hint ladders, misconception classifiers, API routes, scoring rules, safety filters, and data deletion.*

### Step 5: Run the Automated Simulation Script
Run the end-to-end 5-stage simulation showing the closed loop:
```bash
python demo_script.py
```

### Step 6: Start the Web Server
Launch the FastAPI development server:
```bash
python -m uvicorn app:app --reload --port 8000
```

### Step 7: Open in Your Browser
Visit `http://localhost:8000` in your web browser. You will see:
1. **Onboarding & Guardian Consent**: Minor consent verified.
2. **Left Sidebar**: Chats (Ask Anything), Mock Test, Practice & Diagnosis, Memory Tree, Library Vault, Progress.
3. **Role Switcher**: Seamlessly switch between Student, Guardian, Teacher, and Admin views in the sidebar footer.
4. **Theme Switcher**: Instant toggle between Dark mode and Light mode.

---

## Project Structure

```
learnpath_schools/
├── engine.py                  # Pure-Python adaptive engine (zero LLM imports)
├── app.py                     # FastAPI backend (REST API, static mounting, auth)
├── config.py                  # Configurable constants (helplines, boards, age threshold)
├── demo_script.py             # End-to-end simulation script
├── requirements.txt           # Dependencies
├── docker-compose.yml         # Container configuration (PostgreSQL + API)
├── Dockerfile                 # Container image specification
│
├── content/
│   ├── grade7_maths.json      # Approved seed content (3 concepts, 5 questions, 4 hints each)
│   ├── grade7_science.json    # Draft seed placeholder
│   └── library.json           # Library Vault textbooks & notes
│
├── static/
│   └── index.html             # High-fidelity single-page app (dark/light, sidebar, palette)
│
├── tests/
│   ├── test_engine.py         # 64 engine unit tests
│   ├── test_practice.py       # 12 practice session & hint ladder tests
│   └── test_api.py            # 11 integration & security tests
│
└── docs/
    ├── launch-gate.md         # Launch gate checklist (Status: PENDING)
    ├── architecture.md        # System architecture & component design
    ├── workflow.md            # User journeys & permission matrix
    ├── privacy.md             # Child privacy policy & data minimisation
    └── evaluation.md          # 50-item evaluation set & Cohen's d methodology
```
