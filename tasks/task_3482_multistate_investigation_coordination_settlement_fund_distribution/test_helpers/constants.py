"""Domain thresholds and canonical world values (PRD §2.4, §2.6, §2.7, §3).

Every numeric threshold below is named in PRD prose; the logical-clock
constants are derived from the PRD's default clock (2026-09-01T00:00:00Z)
plus the PRD's window arithmetic (45-day sign-on window, 90-day claim
window, 180-day appropriation window, 180-day monitoring periods).
"""

# ── Thresholds (PRD §3) ───────────────────────────────────────────────────
LEAD_MIN_COUNT = 2                 # >= 2 LEAD participations to open a matter
ACTIVE_PARTICIPATION_MIN = 3       # >= 3 ACTIVE participations to open
MAX_SETTLEMENT_ROUNDS = 4          # counters 1..4 allowed; a 5th is rejected
LEAD_COST_BPS = 500                # lead pool = 5% of the base
LEAD_COST_CAP_CENTS = 25000000     # lead pool capped at $250,000
SIGN_ON_WINDOW_DAYS = 45           # sign-on deadline = opened + 45 days
SIGN_ON_QUORUM_BPS = 8000          # inclusive: exactly 8000 passes
SIGN_ON_MIN_STATES = 3             # at least 3 signed states
TOTAL_WEIGHT_BPS = 10000           # line weights of a settlement sum to 10000
APPROPRIATION_WINDOW_DAYS = 180    # certify by executed_at + 180 days
CLAIM_WINDOW_DAYS = 90             # claim registration by executed_at + 90 days
MONITORING_PERIOD_DAYS = 180       # each monitoring window is 180 days
MONITORING_MAX_PERIODS = 6         # at most 6 periods
BREACH_ESCALATION_THRESHOLD = 2    # breach_count >= 2 escalates

# ── Logical clock (PRD §2.4) ──────────────────────────────────────────────
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# Derived deadlines assuming execution at the default clock.
SIGN_ON_DEADLINE_AT_DEFAULT = "2026-10-16T00:00:00Z"      # default + 45d
PAST_SIGN_ON_DEADLINE = "2026-10-17T00:00:00Z"            # one day past it
CLAIM_WINDOW_END_AT_DEFAULT = "2026-11-30T00:00:00Z"      # default + 90d
PAST_CLAIM_WINDOW = "2026-12-01T00:00:00Z"                # strictly past it
APPROPRIATION_WINDOW_END_AT_DEFAULT = "2027-02-28T00:00:00Z"  # default + 180d
PAST_APPROPRIATION_WINDOW = "2027-03-01T00:00:00Z"        # one day past it

# Monitoring period window starts for a settlement executed at the default
# clock: period i starts at executed_at + (i - 1) * 180 days.
MONITORING_PERIOD_STARTS = [
    "2026-09-01T00:00:00Z",   # period 1
    "2027-02-28T00:00:00Z",   # period 2
    "2027-08-27T00:00:00Z",   # period 3
    "2028-02-23T00:00:00Z",   # period 4
    "2028-08-21T00:00:00Z",   # period 5
    "2029-02-17T00:00:00Z",   # period 6
]
MONITORING_PERIOD_ENDS = [
    "2027-02-28T00:00:00Z",
    "2027-08-27T00:00:00Z",
    "2028-02-23T00:00:00Z",
    "2028-08-21T00:00:00Z",
    "2029-02-17T00:00:00Z",
    "2029-08-16T00:00:00Z",
]

# ── Canonical world (used across the design recipes) ─────────────────────
# Offices: CA(pop 100, PREAPPROPRIATED), TX(300, PREAPPROPRIATED),
# NY(400, CERTIFICATION_REQUIRED), FL(200, GENERAL_FUND_ONLY);
# harms 50/150/200/100. Leads: CA, TX.
CANONICAL_OFFICES = {
    "CA": {"state_code": "CA", "population": 100, "harm_measure_cents": 50,
           "appropriation_rule": "PREAPPROPRIATED",
           "cia_tier": "LEAD_ONLY", "is_lead": True},
    "TX": {"state_code": "TX", "population": 300, "harm_measure_cents": 150,
           "appropriation_rule": "PREAPPROPRIATED",
           "cia_tier": "RESTRICTED", "is_lead": True},
    "NY": {"state_code": "NY", "population": 400, "harm_measure_cents": 200,
           "appropriation_rule": "CERTIFICATION_REQUIRED",
           "cia_tier": "STANDARD", "is_lead": False},
    "FL": {"state_code": "FL", "population": 200, "harm_measure_cents": 100,
           "appropriation_rule": "GENERAL_FUND_ONLY",
           "cia_tier": "STANDARD", "is_lead": False},
}
CANONICAL_OFFICE_CODES = ("CA", "TX", "NY", "FL")
CANONICAL_LEAD_CODES = ("CA", "TX")

CANONICAL_TOTAL_CENTS = 100000000
CANONICAL_RESERVE_CENTS = 10000000
CANONICAL_INJUNCTIVE_TERMS = [
    "No misleading marketing",
    "Annual compliance audit",
    "Data preservation",
]
CANONICAL_SIGN_ONS = {"CA": "SIGNED", "TX": "SIGNED", "NY": "SIGNED",
                      "FL": "DECLINED"}

# Expected canonical execution economics (POPULATION basis; CA+TX+NY locked):
# base 90,000,000; lead pool min(25,000,000, round_half_up(90,000,000*5%))
# = 4,500,000; distributable 85,500,000; weights over locked pops 100/300/400
# (sum 800) = 1250/3750/5000 bps.
CANONICAL_PROVISIONAL_WEIGHTS_BPS = {"CA": 1000, "TX": 3000, "NY": 4000,
                                     "FL": 2000}
CANONICAL_LEAD_COST_CENTS = 4500000
CANONICAL_DISTRIBUTABLE_CENTS = 85500000
CANONICAL_WEIGHT_BPS = {"CA": 1250, "TX": 3750, "NY": 5000}
CANONICAL_SHARE_CENTS = {"CA": 10687500, "TX": 32062500, "NY": 42750000}
CANONICAL_LEAD_BONUS_CENTS = {"CA": 2250000, "TX": 2250000, "NY": 0}
CANONICAL_GROSS_SHARE_CENTS = {"CA": 12937500, "TX": 34312500, "NY": 42750000}
