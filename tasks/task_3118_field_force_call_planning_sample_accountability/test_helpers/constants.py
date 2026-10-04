"""Domain thresholds — numeric constants named in PRD section 3.

The logical-clock default and the disciplinary thresholds appear verbatim in
the PRD; the tier weights appear in the plan-allocation paragraph of PRD
section 3.3.
"""

# Logical clock (PRD section 2.5): the server boots with exactly this
# instant and never falls back to wall-clock.
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"
CLOCK_DEFAULT_RENDERED = "2026-09-01T00:00:00.000Z"

# Tier weights for the per-entry allocation rule (PRD section 3.3).
TIER_WEIGHT_A = 6
TIER_WEIGHT_B = 3
TIER_WEIGHT_C = 1

# Planned calls per cycle by tier (PRD section 3.3).
PLANNED_CALLS_BY_TIER = {"A": 12, "B": 6, "C": 2}

# Disciplinary tier boundaries on variance_pct (PRD section 3.6).
TIER_COUNSELING_MIN = 2.0
TIER_WRITTEN_MIN = 5.0
TIER_SUSPENSION_MIN = 10.0

# Temperature severity boundaries (PRD section 3.7).
SEVERITY_MAJOR_MAX_OUTSIDE_C = 2.0
SEVERITY_CRITICAL_MIN_OUTSIDE_C = 5.0
SEVERITY_MINOR_MAX_MINUTES = 30
SEVERITY_CRITICAL_MIN_MINUTES = 240

# Signature payload minimum length (PRD section 3.5).
SIGNATURE_MIN_CHARS = 32

# Transfer documentation note minimum length (PRD section 3.6).
DOC_NOTE_MIN_CHARS = 20

# Count-session inter-window gap in hours (PRD section 3.6).
COUNT_WINDOW_GAP_HOURS = 24

# Maximum count-session reopens (PRD section 3.6).
MAX_REOPENS = 3

# A signature payload that satisfies the >= 32 character rule.
VALID_SIGNATURE_PAYLOAD = "A" * 32

THRESHOLDS = {
    "TIER_COUNSELING_MIN": TIER_COUNSELING_MIN,
    "TIER_WRITTEN_MIN": TIER_WRITTEN_MIN,
    "TIER_SUSPENSION_MIN": TIER_SUSPENSION_MIN,
    "SEVERITY_MAJOR_MAX_OUTSIDE_C": SEVERITY_MAJOR_MAX_OUTSIDE_C,
    "SEVERITY_CRITICAL_MIN_OUTSIDE_C": SEVERITY_CRITICAL_MIN_OUTSIDE_C,
    "SEVERITY_MINOR_MAX_MINUTES": SEVERITY_MINOR_MAX_MINUTES,
    "SEVERITY_CRITICAL_MIN_MINUTES": SEVERITY_CRITICAL_MIN_MINUTES,
    "SIGNATURE_MIN_CHARS": SIGNATURE_MIN_CHARS,
    "DOC_NOTE_MIN_CHARS": DOC_NOTE_MIN_CHARS,
    "COUNT_WINDOW_GAP_HOURS": COUNT_WINDOW_GAP_HOURS,
    "MAX_REOPENS": MAX_REOPENS,
}
