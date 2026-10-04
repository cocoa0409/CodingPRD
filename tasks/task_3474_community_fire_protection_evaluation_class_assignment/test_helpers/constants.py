"""Domain constants — every threshold, weight, cap, and pinned default.

All numeric literals are copied from the PRD (§2.3–§2.4, §3.1–§3.9) and its
calculation definitions. Nothing here is invented; if a rule is qualitative
it has no constant. Test code should import these names instead of
re-typing the literals so the suite and the helpers never drift apart.
"""

# ── Logical clock (PRD §2.4) ─────────────────────────────────────────────
# Before any set call, the logical clock reads exactly this instant.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-09-01"

# ── Pagination (PRD §2.3) ────────────────────────────────────────────────
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# ── Role names (PRD §2.1) ────────────────────────────────────────────────
ROLE_EVALUATION_COORDINATOR = "EvaluationCoordinator"
ROLE_FIELD_ANALYST = "FieldAnalyst"
ROLE_CLASS_REGISTRAR = "ClassRegistrar"
ROLE_FIRE_CHIEF = "FireChief"
ROLE_WATER_UTILITY_MANAGER = "WaterUtilityManager"
ROLE_COMMS_SUPERVISOR = "CommsSupervisor"
ROLE_COMMUNITY_OFFICIAL = "CommunityOfficial"
ROLE_INSURER = "Insurer"
ALL_ROLES = (
    ROLE_EVALUATION_COORDINATOR,
    ROLE_FIELD_ANALYST,
    ROLE_CLASS_REGISTRAR,
    ROLE_FIRE_CHIEF,
    ROLE_WATER_UTILITY_MANAGER,
    ROLE_COMMS_SUPERVISOR,
    ROLE_COMMUNITY_OFFICIAL,
    ROLE_INSURER,
)

# ── Flow normalization (PRD §3.4) ────────────────────────────────────────
REFERENCE_RESIDUAL_PSI = 20
PRESSURE_EXPONENT = 0.54

# ── Equipment credit (PRD §3.6) ──────────────────────────────────────────
NEEDED_PUMP_GPM = 1750
LADDER_MIN_FT = 75
TANKER_MIN_GAL = 1000
EQUIPMENT_MAX_POINTS = 20

# ── Staffing credit (PRD §3.6) ───────────────────────────────────────────
NEEDED_ON_SHIFT = 6
STAFFING_MAX_POINTS = 15
VOLUNTEER_FACTOR = 0.5
CAREER_FACTOR = 1.0  # RAW_HEADCOUNT variant counts every head fully

# ── Training credit (PRD §3.6) ───────────────────────────────────────────
TRAINING_HOURS_BENCHMARK = 240
LIVE_FIRE_CAP = 6
TRAINING_MAX_POINTS = 9

# ── Response credit (PRD §3.6) ───────────────────────────────────────────
RESPONSE_MAX_POINTS = 6
FD_TOTAL_MAX_POINTS = 50

# ── Water supply scoring (PRD §3.6) ──────────────────────────────────────
SUPPLY_MAX_POINTS = 10
FLOW_MAX_POINTS = 18
DISTRIBUTION_MAX_POINTS = 7
STORAGE_MAX_POINTS = 5
WATER_MAX_POINTS = 40
FLOW_TARGET_MULT = 1.5
HYDRANT_CREDIT_MIN_GPM = 1000
STORAGE_DURATION_MIN = 120
STALE_FACTOR = 0.5
STALE_MONTHS = 60
ALT_SITE_TARGET = 2
RURAL_AREA_PCT_THRESHOLD = 50  # RURAL_SHUTTLE needs rural_area_pct above this

# ── Emergency communications (PRD §3.6) ──────────────────────────────────
COMMS_MAX_POINTS = 10
OPERATORS_FULL_CREDIT = 2
ALARM_FAST_SECONDS = 60
ALARM_SLOW_SECONDS = 90
# Unattested defaults (PRD §3.1): zero credit from the comms arm.
DEFAULT_OPERATORS_ON_DUTY_MIN = 0
DEFAULT_ALARM_TO_DISPATCH_SECONDS = 999

# ── Community risk reduction credit (PRD §3.6) ───────────────────────────
CRR_ITEM_CAP = 2.0
CRR_TOTAL_CAP = 5.5
CRR_PCT_OF_SUBTOTAL = 0.10

# ── Divergence penalty and class thresholds (PRD §3.6) ───────────────────
DIVERGENCE_RATIO = 0.5
DIVERGENCE_PENALTY_MULT = 2
# adjusted_total_points thresholds: >= 90 → class 1 ... >= 10 → class 9,
# below 10 → class 10.
CLASS_THRESHOLDS = (
    (90, 1),
    (80, 2),
    (70, 3),
    (60, 4),
    (50, 5),
    (40, 6),
    (30, 7),
    (20, 8),
    (10, 9),
)
LOWEST_CLASS = 10

# ── Property applicability radii (PRD §3.8) ──────────────────────────────
HYDRANT_RADIUS_FT = 1000        # exactly 1000 ft is WITHIN (base class)
STATION_RADIUS_MI = 5.0         # exactly 5.0 road miles is WITHIN

# ── Premium modifier table (PRD §3.7) ────────────────────────────────────
PREMIUM_MODIFIER_TABLE = {
    1: 0.65,
    2: 0.70,
    3: 0.75,
    4: 0.80,
    5: 0.85,
    6: 0.90,
    7: 0.95,
    8: 1.00,
    9: 1.10,
    10: 1.25,
}

# ── Exposure ledger (PRD §3.8) ───────────────────────────────────────────
EXPOSURE_CAP_CENTS = 500_000_000
COVERAGE_VALUE_CAP_RATIO = 1.5  # exactly 150% of insured value is allowed

# ── Schedule windows (PRD §2.4, §3.2, §3.9) ──────────────────────────────
EVAL_INTERVAL_MONTHS = 60       # next_evaluation_due_date = effective_from + 60 months
REEVAL_MIN_MONTHS = 12          # reevaluation needs clock >= effective_from + 12 months
APPEAL_WINDOW_DAYS = 90         # appeal window closes 90 days after published_at
REEVAL_SPAWNED_CYCLE_FREEZE_DAYS = 90  # approved request's cycle freezes 90 days out

# ── Input ranges (PRD §3.1, §3.4, §3.8) ──────────────────────────────────
NEEDED_FIRE_FLOW_MIN_GPM = 500
NEEDED_FIRE_FLOW_MAX_GPM = 50000
STATIC_PSI_MIN_EXCLUSIVE = 20   # static_psi must be above 20
STATIC_PSI_MAX = 300
RESIDUAL_PSI_MIN = 10           # and strictly below static_psi
TERM_MONTHS_MIN = 1
TERM_MONTHS_MAX = 120
RURAL_AREA_PCT_MAX = 100
