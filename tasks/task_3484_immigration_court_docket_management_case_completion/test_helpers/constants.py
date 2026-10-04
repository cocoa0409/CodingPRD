"""Domain constants — every numeric threshold and anchor named by the PRD.

Values are verbatim from the PRD's calculation rules (hearing durations and
factors, daily caps, priority-score weights, day windows, continuance policy,
backlog ratio, pace denominators) plus the logical-clock default.  No value
here is a placeholder; each appears in PRD prose.
"""

# ─── Logical clock (PRD §2.4) ─────────────────────────────────────────────
# Before any clock-setting call, the logical clock reads exactly this instant
# and never falls back to wall-clock time.
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# ─── Hearing duration & daily load (PRD §3.3) ─────────────────────────────
MASTER_BASE_MINUTES = 30            # raw master-calendar block length
MERITS_BASE_MINUTES = 120           # raw individual-merits block length
DETAINED_MERITS_FACTOR = 0.75       # merits factor when the case is DETAINED
REPRESENTED_MERITS_FACTOR = 0.8     # merits factor when representation != PRO_SE
LOP_MASTER_FACTOR = 0.5             # master factor with an active LOP at/above threshold
LOP_COVERAGE_THRESHOLD_PCT = 50     # coverage_pct >= 50 activates the LOP factor (inclusive)
SLOT_MINUTES = 15                   # per-hearing ceil-to-15-minute block
JUDGE_DAILY_MINUTE_CAP = 120        # judge's summed rounded minutes per UTC day (equality allowed)

# ─── Interpreter selection (PRD §3.3) ─────────────────────────────────────
INTERPRETER_BUFFER_MINUTES = 15     # buffer reserved on both sides of existing hearings (strict)

# ─── Case priority score (PRD §3.2) ───────────────────────────────────────
DETAINED_PRIORITY_BASE = 1000       # base points for DETAINED custody, else 0
AGE_POINTS_PER_DAY = 2              # points per calendar day pending
AGE_CAP_DAYS = 720                  # cap on the age term input: min(days, 720)
CONTINUANCE_DRAG_POINTS = 25        # points subtracted per granted continuance
CONTINUANCE_DRAG_CAP = 4            # cap on the drag input: min(count, 4)

# ─── Case age / completion targets (PRD §3.2) ─────────────────────────────
TARGET_DAYS_DETAINED = 60           # filed_at + 60 days; is_past_goal is strict >
TARGET_DAYS_NON_DETAINED = 365      # filed_at + 365 days

# ─── Detained scheduling (PRD §3.3) ───────────────────────────────────────
DETAINED_MASTER_HEARING_DAYS = 14   # master must start <= filed_at + 14 days (inclusive)
DETAINED_MERITS_HEARING_DAYS = 30   # merits must start <= filed_at + 30 days (inclusive)

# ─── Continuance policy (PRD §3.4) ────────────────────────────────────────
CONTINUANCE_CAP_DETAINED = 2        # filing rejected when granted count >= 2
CONTINUANCE_CAP_NON_DETAINED = 5    # filing rejected when granted count >= 5
CONTINUANCE_LEAD_HOURS = 24         # filing no later than 24h before start (first attorney carve-out)
CONTINUANCE_BUMP_DAYS_DETAINED = 7  # replacement hearing = old start + 7 days
CONTINUANCE_BUMP_DAYS_NON_DETAINED = 28  # replacement hearing = old start + 28 days

# ─── Auto-created hearing offsets (PRD §3.4–§3.6) ─────────────────────────
AUTO_HEARING_REMAND_DAYS = 42       # remand merits hearing at clock + 42 days
AUTO_HEARING_REOPEN_DAYS = 21       # reopen master hearing at clock + 21 days

# ─── Appeal & reopen windows (PRD §3.5–§3.6) ──────────────────────────────
APPEAL_WINDOW_DAYS = 30             # appeal_deadline = issued_at + 30 days (inclusive)
REOPEN_WINDOW_DAYS = 180            # reopen_deadline = issued_at + 180 days (inclusive)

# ─── Court backlog & pace (PRD §2.9, §3.8) ────────────────────────────────
BACKLOG_CRITICAL_RATIO = 0.25       # is_backlog_critical: pending >= ceil(0.25 * goal)
DAYS_PER_YEAR = 365                 # calendar pace denominator
HEARING_DAYS_PER_YEAR = 260         # hearing-day pace denominator
PACE_RATIO_DECIMAL_PLACES = 4       # round-half-up precision on pace ratios
REPRESENTATION_RATE_DECIMAL_PLACES = 1  # round-half-up precision on representation rate

# ─── Standard fixture time anchors (shared setup plumbing) ────────────────
# Hearing starts used by the composite fixtures; all are >= the clock default.
MASTER_HEARING_START_ISO = "2026-09-03T10:00:00Z"
MASTER_HEARING_CLOCK_ISO = "2026-09-03T10:30:00Z"   # clock at which the master can complete
MERITS_HEARING_START_ISO = "2026-09-04T10:00:00Z"
MERITS_HEARING_CLOCK_ISO = "2026-09-04T12:00:00Z"   # clock at which the merits can complete
NOSHOW_HEARING_START_ISO = "2026-09-05T10:00:00Z"
NOSHOW_CLOCK_ISO = "2026-09-05T11:00:00Z"           # clock at which the no-show is recorded
NOTICE_SERVED_AT_ISO = "2026-08-20T00:00:00Z"       # served before the default clock
CONTINUANCE_HEARING_START_ISO = "2026-09-10T10:00:00Z"  # far-enough start for 24h lead time
