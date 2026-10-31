# Privacy Policy

> **Status: DRAFT** -- Must be reviewed by legal before launch.

## 1. Data We Collect

### 1.1 Student Data
- Name, grade, board, medium (provided during onboarding)
- School ID (for authentication)
- Practice responses, mastery scores, diagnostic results
- Chat messages (safety-screened and PII-redacted before storage)
- Test results and timing data

### 1.2 Guardian Data
- Name, email (for authentication)
- Linked student IDs
- Consent records (version, timestamp)

### 1.3 Teacher / Admin Data
- Name, email (for authentication)
- Content approval actions

## 2. Data Minimisation

We collect only data necessary for the adaptive learning loop:
- Diagnostic responses (to set initial mastery)
- Practice answers (to update Bayesian Knowledge Tracing)
- Hint usage (to adjust scaffolding levels)
- Misconception logs (to trigger repair cycles)
- Test results (for progress reporting)

We do NOT collect:
- Location data
- Device identifiers
- Browsing history outside the platform
- Biometric data

## 3. Child Safety

- All students are treated as minors. Guardian consent is required for students under the configured age threshold (default: 18 years).
- Consent records include version identifier and ISO 8601 timestamp.
- Chat messages are screened for self-harm, abuse, bullying, sexual content, and violence before processing.
- Unsafe messages trigger immediate helpline information display and are NOT forwarded to any LLM.
- PII (phone numbers, email addresses, ID patterns) is redacted before storage.

## 4. Data Retention

- Practice data is retained for the duration of the student's enrollment.
- Chat logs are retained in redacted form only.
- Event logs (events.jsonl) are append-only and include timestamps.

## 5. Data Deletion

- Students (or guardians on their behalf) may request complete data deletion via the DELETE /api/user/data endpoint.
- Deletion removes: user profile, mastery records, attempt history, chat logs, misconception logs, hint states, and seen question records.
- Event log entries are anonymized (user ID replaced with "DELETED") but retained for audit purposes.

## 6. Access Controls

| Role | Can Access |
|------|-----------|
| Student | Own data only |
| Guardian | Linked children's summary data only (no raw chat unless school permits) |
| Teacher | Their classes' progress and misconception data |
| Admin | Content catalog management |
| Researcher | Pseudonymous IDs only |

## 7. LLM Usage

- The LLM adapter is used for three purposes only: personalizing hints, explaining wrong answers, and answering general questions.
- Student data sent to the LLM is limited to grade level, recent misconceptions (anonymized), and the current question context.
- The LLM API key is stored in environment variables and is never logged.
- The LLM never decides mastery, correctness, or learning paths.

## 8. Helpline Information

- Tele-MANAS (India): 14416
- Emergency: 112

These numbers must be verified before launch.
