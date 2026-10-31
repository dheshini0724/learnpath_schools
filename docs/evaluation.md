# Evaluation Plan

## 1. Experimental Design

### Conditions
- **Personalised**: Adaptive engine selects concepts, questions, and hint levels based on student mastery.
- **Generic**: Fixed question sequence, fixed hint level 2, no engine adaptation.

### Assignment
Students are randomly assigned to one condition at registration time. Assignment is stored and does not change.

## 2. Metrics

### Primary Metric: Learning Gain
- Pre-test score (diagnostic) vs. post-test score after N practice sessions.
- Measured per concept and aggregated across subjects.

### Statistical Analysis
- **Effect size**: Cohen's d (standardized mean difference between conditions).
- **Confidence interval**: 95% CI for Cohen's d.
- **Significance test**: Welch's t-test (does not assume equal variances).
- **Minimum sample**: 30 students per condition for adequate power.

### Secondary Metrics
- Time to mastery (seconds of practice per concept to reach BKT >= 0.9).
- Hint usage rate (average hints requested per question).
- Misconception recurrence rate (fraction of misconceptions seen 2+ times).
- Transfer success rate (fraction passing transfer check on first attempt).

## 3. Evaluation Dataset

A minimum 50-item evaluation set spanning:
- All 3 seed concepts (adding fractions, equivalent fractions, multiplying fractions).
- Diagnostic items (8-12 per subject).
- Practice items at medium and hard difficulty.
- Transfer items (at least 1 per concept).
- Items targeting each known misconception.

## 4. Safety Evaluation

- Verify safety screen catches all SAFETY_CATEGORIES keywords.
- Verify PII redaction for phone numbers, emails, and Aadhaar patterns.
- Verify helpline numbers displayed correctly.
- Verify unsafe messages never reach LLM.

## 5. Accessibility Evaluation

- WCAG 2.2 AA contrast verification (4.5:1 for body text).
- 44x44px minimum touch targets.
- Focus outlines: --ac color, 3px width, 2px offset.
- Screen reader compatibility (aria-labels on all interactive elements).
- Keyboard navigation for all screens.

## 6. Data Integrity Checks

- Verify answer keys never reach browser before test submission.
- Verify guardian consent required for minors.
- Verify complete data deletion removes all user data.
- Verify event log entries are append-only and contain timestamps.
- Verify LLM never decides mastery or correctness.
