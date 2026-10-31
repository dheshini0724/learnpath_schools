# User Workflows & System Journeys

This document defines user journeys, guardian consent verification, and mock test lifecycles in LearnPath for Schools.

---

## 1. Student Onboarding & Guardian Consent

```
[New Student Visits] 
         │
         ▼
[Onboarding Modal Displayed]
  - Full Name, Grade (5-12), Board (CBSE/ICSE/State), Medium
         │
         ├─────────────────────────────────────────────┐
         ▼                                             ▼
[Age < 18 (Configurable Threshold)]          [Age >= 18]
  - Guardian Consent Required                   - Direct Access
  - Version: v1.0, ISO 8601 Timestamp           - Account Created
  - Stored in store.json & events.jsonl
         │
         ▼
[Student Session Initialized]
  - School ID + 4-digit PIN Authentication
  - Condition Assigned (Personalised vs Generic A/B)
```

---

## 2. Closed-Loop Practice Journey

```
[1. DIAGNOSE]
  - Subject diagnostic (8-12 items)
  - Scores: 0.8 (all unaided correct), 0.5 (partial), 0.2 (none)
  - Prerequisite DAG unlocks eligible concepts (lowest mastery first)
         │
         ▼
[2. TARGETED SUPPORT]
  - Present unseen practice problem
  - 4-Level Hint Ladder:
      Level 1: Idea prompt
      Level 2: Short conceptual explanation
      Level 3: Worked example with different numbers
      Level 4: Step-by-step next step only
         │
         ▼
[3. OBSERVE & CLASSIFY]
  - Student selects option A-D
  - Engine determines correctness (pure Python, zero LLM)
  - Distractor option mapped to Misconception ID or "gap"
         │
         ▼
[4. ADAPT & REPAIR]
  - Error: Raise hint level by 1; BKT updates mastery
  - If same misconception seen 2+ times: Flag as RECURRING
      -> Initiate Repair Cycle (Contrasting example -> practice -> check)
      -> Scaffold starts at Level 3
  - 2 consecutive unaided correct answers: Lower hint level by 1
         │
         ▼
[5. MEASURE & TRANSFER]
  - Student clicks "I think I've got it!"
  - Administer novel transfer challenge with ZERO hints
  - Pass with mastery >= 0.90 -> Mark concept MASTERED
  - Spaced review scheduled at 1, 3, 7, and 21 days
```

---

## 3. Mock Test Lifecycle & Security

```
[Step 1: Source Selection]
  - Option A: Predefined subject curriculum
  - Option B: Approved Library Vault resource
  - Option C: Custom topic (free-text)
         │
         ▼
[Step 2: Configuration & Generation]
  - Quick Start (default: 5 Qs, 5 Mins) vs Customize
  - 4-Stage Animated Progress:
      1. Analyzing test configuration...
      2. Generating questions...
      3. Preparing test environment...
      4. Redirecting to test...
         │
         ▼
[Step 3: Test Execution (SECURE)]
  - Server timer begins countdown
  - Questions served WITHOUT answer keys (hardware-enforced)
  - Palette: Green (Answered), Amber (Review Later), Grey (Unanswered)
  - Auto-submits at 0 seconds on server & browser
         │
         ▼
[Step 4: Scoring & Results]
  - Scoring Rule: Correct +1.0, Wrong -0.25, Skipped 0.0
  - Results tabs: Summary, Question Breakdown, Time Analysis
  - Answer keys revealed ONLY after submission
  - Generated tests labeled: "Not teacher-reviewed"
```

---

## 4. Multi-Role Permissions Matrix

| Feature | Student | Guardian | Teacher | Admin |
|---------|:-------:|:--------:|:-------:|:-----:|
| Practice & Diagnostic | Yes | View child | Class view | Full |
| Raw Chat Logs | Yes | **Blocked** | **Blocked** | **Blocked** |
| Active Misconceptions | Yes | Yes (child) | Heatmap | Full |
| Content Approval | No | No | Yes | Yes |
| Catalog Editor | No | No | No | Yes |
| Delete User Data | Yes (own) | Yes (child) | No | Full |
