"""Domain constants — every value traces to a verbatim PRD.md literal.

Trace map (PRD.md is the only authority; nothing here is copied from any
other source):

- LOGICAL_CLOCK_START: PRD §2.4 "the logical clock reads exactly
  2026-09-01T00:00:00Z" before any administrative call sets it.
- CLOCK endpoint: PRD §4 "POST /_clock/set_current_utc ... lives outside
  the /msha prefix".
- Cycle geometry (PRD §2.6): UNDERGROUND spans exactly 90 days, SURFACE
  exactly 180 days, both bounds inclusive (period_end = period_start + 89
  or + 179 days).
- Point factor tables (PRD §3.4): negligence 0/10/25/40/50; likelihood
  5/15/25; severity 0/10/20/30; persons 1->0, 2..5->5, 6..20->10,
  >=21->20; S&S surcharge 15; history window 730 days with tiers
  0..5->0, 6..15->5, 16..30->10, >=31->20; size tiers <50000->0,
  50000..499999->5, 500000..4999999->10, >=5000000->15.
- Dollar pipeline (PRD §3.4): marginal tiers 11,250 / 22,500 / 37,500 /
  52,500 cents per point over bands 20 / 40 / 40 / unbounded; repeat
  multiplier 1.15; good-faith discount 10%; statutory floors 150,000
  (ORDER) / 120,000 (CITATION with S&S) / 60,000 (CITATION without S&S),
  applied LAST.
- Abatement (PRD §3.4): base days 30/15/5/1 by severity; the single
  extension adds ceil(base/2) days (15/8/3/1).
- Contest window (PRD §3.6): filing is timely on or before
  issued_at + 30 days; finalize requires the clock strictly later than
  issued_at + 30 days.
- Accident late-report (PRD §3.7): strict > 900 seconds (FATAL) or
  > 7,200 seconds (otherwise); the auto-issued citation's fixed factors
  and standard_code "50.10 LATE REPORT".
- Mine plans (PRD §3.7): next_revision_due_at = approved_at + 180 days.
- POV (PRD §3.7): rolling 365-day window (window_start = screened_at -
  365 days, exclusive), +2 per S&S citation, +1 per HIGH/
  RECKLESS_DISREGARD citation, +5 per imminent-danger order, threshold
  >= 8.
- Cycle requirement (PRD §3.2): baseline 1 completed REGULAR inspection
  per cycle; +1 on every OPEN cycle when the mine enters POV_FINAL.
"""
from decimal import Decimal

# ─── Platform / clock (PRD §2.4, §4) ──────────────────────────────────────────

API_PREFIX = "/msha"
CLOCK_ENDPOINT_PATH = "/_clock/set_current_utc"   # platform-level, NOT prefixed
CLOCK_ENDPOINT_METHOD = "POST"
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

# ─── Statutory cycle geometry (PRD §2.6) ──────────────────────────────────────

UNDERGROUND_CYCLE_DAYS = 90     # inclusive span; period_end = period_start + 89
SURFACE_CYCLE_DAYS = 180        # inclusive span; period_end = period_start + 179
BASE_REQUIRED_INSPECTIONS = 1   # statutory baseline per cycle
POV_EXTRA_REQUIRED_INSPECTIONS = 1  # added to every OPEN cycle on POV_FINAL

# ─── Penalty point factor tables (PRD §3.4) ───────────────────────────────────

NEGLIGENCE_POINTS = {
    "NONE": 0,
    "LOW": 10,
    "MODERATE": 25,
    "HIGH": 40,
    "RECKLESS_DISREGARD": 50,
}
LIKELIHOOD_POINTS = {
    "UNLIKELY": 5,
    "REASONABLY_LIKELY": 15,
    "HIGHLY_LIKELY": 25,
}
SEVERITY_POINTS = {
    "NO_INJURY": 0,
    "MINOR": 10,
    "SERIOUS": 20,
    "FATAL_POTENTIAL": 30,
}
SS_SURCHARGE_POINTS = 15

# persons_affected -> points: 1 -> 0; 2..5 -> 5; 6..20 -> 10; >= 21 -> 20
PERSONS_BAND_EDGES = (2, 6, 21)          # lower bounds of the 5/10/20 tiers
PERSONS_BAND_POINTS = (0, 5, 10, 20)

# prior non-VACATED citations in the trailing 730-day window -> points:
# 0..5 -> 0; 6..15 -> 5; 16..30 -> 10; >= 31 -> 20
HISTORY_WINDOW_DAYS = 730
HISTORY_BAND_EDGES = (6, 16, 31)         # lower bounds of the 5/10/20 tiers
HISTORY_BAND_POINTS = (0, 5, 10, 20)

# operator.annual_tonnage_tons -> points:
# < 50000 -> 0; 50000..499999 -> 5; 500000..4999999 -> 10; >= 5000000 -> 15
SIZE_TONNAGE_EDGES = (50000, 500000, 5000000)
SIZE_BAND_POINTS = (0, 5, 10, 15)

# ─── Penalty dollar pipeline (PRD §3.4) ───────────────────────────────────────

PENALTY_TIER_CENTS = (11250, 22500, 37500, 52500)   # per-point, marginal
PENALTY_TIER_BANDS = (20, 40, 40)                   # first three band widths; 4th unbounded
REPEAT_MULTIPLIER = Decimal("1.15")
GOOD_FAITH_RATE = Decimal("0.10")
FLOOR_ORDER_CENTS = 150000
FLOOR_CITATION_SS_CENTS = 120000
FLOOR_CITATION_CENTS = 60000

# ─── Abatement deadlines (PRD §3.4) ───────────────────────────────────────────

ABATEMENT_BASE_DAYS = {
    "NO_INJURY": 30,
    "MINOR": 15,
    "SERIOUS": 5,
    "FATAL_POTENTIAL": 1,
}
# Single extension adds ceil(base/2) days: 30->15, 15->8, 5->3, 1->1.

# ─── Contest / finalize windows (PRD §3.4, §3.6) ─────────────────────────────

CONTEST_WINDOW_DAYS = 30   # filing timely through issued_at + 30 days inclusive;
                           # finalize requires the clock strictly later than that

# ─── Accident late-report thresholds (PRD §3.7) ──────────────────────────────

FATAL_REPORT_LIMIT_SECONDS = 900     # strict greater-than; exactly 900 is timely
OTHER_REPORT_LIMIT_SECONDS = 7200    # strict greater-than; exactly 7200 is timely
LATE_REPORT_STANDARD_CODE = "50.10 LATE REPORT"
LATE_REPORT_CITATION_FACTORS = {
    "kind": "CITATION",
    "negligence": "MODERATE",
    "gravity_likelihood": "UNLIKELY",
    "gravity_severity": "NO_INJURY",
    "persons_affected": 1,
    "significant_and_substantial": False,
    "repeat_violation": False,
}

# ─── Mine plans (PRD §3.7) ────────────────────────────────────────────────────

PLAN_REVISION_DAYS = 180   # next_revision_due_at = approved_at + 180 days

# ─── Pattern of violations (PRD §3.7) ─────────────────────────────────────────

POV_WINDOW_DAYS = 365      # window_start = screened_at - 365 days (exclusive)
POV_SS_WEIGHT = 2
POV_NEGLIGENCE_BONUS = 1          # per HIGH / RECKLESS_DISREGARD citation
POV_IDO_WEIGHT = 5
POV_THRESHOLD = 8                  # weighted_score >= 8 crosses

# ─── Pagination defaults (PRD §2.3) ───────────────────────────────────────────

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# ─── Test payload defaults (helper-layer conveniences, not PRD rules) ─────────
# Default instants are >= LOGICAL_CLOCK_START so fixtures are reachable without
# any clock call; tests that need a specific clock reading set it explicitly.

TEST_DEFAULTS = {
    "OPERATOR_LEGAL_NAME": "Canyon Coal Co",
    "OPERATOR_TONNAGE": 1000,           # size tier 0 (< 50000 tons)
    "OPERATOR_HOME_DISTRICT": "D-11",
    "MINE_NAME": "Canyon No 1",
    "MINE_TYPE": "UNDERGROUND",
    "ACTIVATION_DATE": "2026-09-01",    # == LOGICAL_CLOCK_START's calendar date
    "INSPECTOR_FULL_NAME": "R. Alvarez",
    "INSPECTOR_DISTRICT_CODE": "D-11",
    "INSPECTOR_CERTIFICATION": "BOTH",
    "PLANNED_START_AT": "2026-09-01T08:00:00Z",
    "PLANNED_END_AT": "2026-09-01T12:00:00Z",
    "STANDARD_CODE": "30 CFR 75.370",
    "HAZARD_DESCRIPTION": "roof sag over the belt line",
    "GROUNDS": "The citation misstates the condition found at the face.",
    "DOCUMENT_REF": "msha-plan-doc-0001",
    "REJECTION_REASON": "Ventilation quantities do not meet the minimum standard.",
    "ACCIDENT_DESCRIPTION": "roof fall in the No 2 entry",
    "ROOT_CAUSE": "Inadequate roof bolting pattern over the intersection.",
    "REPORT_TEXT": "Investigation findings and corrective actions.",
    "ABATEMENT_NOTE": "corrected",
    "VERIFICATION_NOTE": "verified on site",
    "JUSTIFICATION": "parts on order",
    "MINERS_WITHDRAWN_COUNT": 12,
}
