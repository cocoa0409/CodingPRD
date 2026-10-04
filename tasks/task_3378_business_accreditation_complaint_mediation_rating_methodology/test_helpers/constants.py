"""Domain constants — every literal pinned by PRD.md prose.

Every value below is copied from PRD.md (the group comment cites the PRD
section). Tests must import these instead of re-deriving numbers inline.
"""

from decimal import ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------------------
# PRD §2.4 — the logical clock
# "At startup, before any clock operation has been issued, the logical clock
# reads exactly 2026-09-01T00:00:00Z, and it never falls back to the host's
# wall clock."
# ---------------------------------------------------------------------------
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# PRD §3.1 — size tiers from headcount
# "MICRO for 1 to 4 employees, SMALL for 5 to 19 employees, MEDIUM for 20 to
# 99 employees, and LARGE for 100 or more employees."
# ---------------------------------------------------------------------------
TIER_MICRO_MAX_EMPLOYEES = 4
TIER_SMALL_MAX_EMPLOYEES = 19
TIER_MEDIUM_MAX_EMPLOYEES = 99
SIZE_TIERS = ("MICRO", "SMALL", "MEDIUM", "LARGE")

# ---------------------------------------------------------------------------
# PRD §3.2 — accreditation eligibility, reapplication, outstanding-dues gate
# "the business must be at least 183 days old at the submit instant"
# "at least 30 days have elapsed since the application's decided_at"
# "nor any VOID invoice whose voided_at falls within the trailing 365 days"
# ---------------------------------------------------------------------------
ACCREDITATION_MIN_AGE_DAYS = 183
REAPPLICATION_COOLING_DAYS = 30
VOID_INVOICE_GATE_DAYS = 365

# ---------------------------------------------------------------------------
# PRD §3.3 — dues schedule and invoicing
# "42500 cents for MICRO, 68000 cents for SMALL, 115000 cents for MEDIUM, and
# 240000 cents for LARGE"
# "a 5 percent prepay discount ... rounded half-up to whole cents in a single
# rounding at the total"
# "a 4 percent plan surcharge ... first the plan total ... then the base
# installment is the plan total divided by 4 and rounded half-up"
# "due_date is exactly 30 days after issued_at"
# "An invoice still unpaid more than 15 days after its due_date is voided"
# ---------------------------------------------------------------------------
DUES_BASE_CENTS = {
    "MICRO": 42500,
    "SMALL": 68000,
    "MEDIUM": 115000,
    "LARGE": 240000,
}
ANNUAL_PREPAID_DISCOUNT_RATE = Decimal("0.95")  # subtotal * (1 - 0.05)
QUARTERLY_SURCHARGE_RATE = Decimal("1.04")
QUARTERLY_INSTALLMENT_COUNT = 4
INVOICE_DUE_DAYS = 30
INVOICE_VOID_GRACE_DAYS = 15  # VOID once now > due_date + 15 days

# Worked-example literals pinned verbatim by the PRD §3.3 example
# (MEDIUM base 115000 + bureau local fee 333):
WORKED_LOCAL_FEE_CENTS = 333
WORKED_SUBTOTAL_CENTS = 115333
WORKED_ANNUAL_TOTAL_CENTS = 109566  # round_half_up(115333 * 0.95)
WORKED_QUARTERLY_TOTAL_CENTS = 119946  # round_half_up(115333 * 1.04)
WORKED_QUARTERLY_INSTALLMENTS_CENTS = [29987, 29987, 29987, 29985]

# Zero-fee prepaid totals used by composite fixtures
# (round_half_up(base * 0.95); all exact):
PREPAID_TOTAL_FEE0_CENTS = {
    "MICRO": 40375,    # 42500 * 0.95
    "SMALL": 64600,    # 68000 * 0.95
    "MEDIUM": 109250,  # 115000 * 0.95
    "LARGE": 228000,   # 240000 * 0.95
}

# ---------------------------------------------------------------------------
# PRD §3.4 — complaint response cycle
# "response_deadline_at is set exactly 14 days later — precisely 1209600
# seconds after forwarded_at"
# "a complaint admits at most 3 consumer rebuttals"
# "no later than 30 days after its closed_at"
# ---------------------------------------------------------------------------
RESPONSE_WINDOW_DAYS = 14
RESPONSE_WINDOW_SECONDS = 1209600
REBUTTAL_MAX = 3
REOPEN_WINDOW_DAYS = 30

# ---------------------------------------------------------------------------
# PRD §3.5 — mediation and arbitration
# "the offer must arrive no later than 14 days after the complaint's
# last_unresolved_at"
# "sets offer_deadline_at exactly 7 days later"
# "the new hearing must start no earlier than 30 minutes after the existing
# hearing's end, or else end no later than 30 minutes before the existing
# hearing's start"
# ---------------------------------------------------------------------------
MEDIATION_OFFER_WINDOW_DAYS = 14
MEDIATION_OFFER_ACCEPT_DAYS = 7
HEARING_ROOM_BUFFER_MINUTES = 30

# ---------------------------------------------------------------------------
# PRD §3.6 — rating methodology
# "the rating window is the trailing 1095 days, inclusive at both ends"
# "The volume threshold is 3 complaints for a MICRO business, 6 for SMALL,
# 12 for MEDIUM, and 24 for LARGE." ... 6 points per excess, cap 30.
# unanswered 12 each cap 36; unresolved 8 each cap 24; adverse arbitration
# 10 each cap 20; age 2 per full year under 3, cap 6; advertising 15 / 5 / 0;
# scam 10 at 3+ published reports in trailing 365 days; pending 4 each cap 12.
# ---------------------------------------------------------------------------
RATING_WINDOW_DAYS = 1095
VOLUME_THRESHOLDS = {"MICRO": 3, "SMALL": 6, "MEDIUM": 12, "LARGE": 24}
VOLUME_POINTS_PER_EXCESS = 6
VOLUME_CAP = 30
UNANSWERED_POINTS_EACH = 12
UNANSWERED_CAP = 36
UNRESOLVED_POINTS_EACH = 8
UNRESOLVED_CAP = 24
ARBITRATION_ADVERSE_POINTS_EACH = 10
ARBITRATION_CAP = 20
AGE_POINTS_PER_YEAR_UNDER_3 = 2
AGE_YEARS_FULLY_SAFE = 3
AGE_CAP = 6
ADVERTISING_REFERRED_POINTS = 15
ADVERTISING_UNDER_REVIEW_POINTS = 5
SCAM_PATTERN_MIN_REPORTS = 3
SCAM_PATTERN_WINDOW_DAYS = 365
SCAM_PATTERN_POINTS = 10
PENDING_POINTS_EACH = 4
PENDING_CAP = 12

# Grade floors, inclusive on the lower bound (PRD §3.6):
# "a score of exactly 90 earns A_MINUS while 89 earns B_PLUS"
GRADE_FLOORS = (
    ("A_PLUS", 97),
    ("A", 94),
    ("A_MINUS", 90),
    ("B_PLUS", 85),
    ("B", 80),
    ("B_MINUS", 75),
    ("C_PLUS", 70),
    ("C", 65),
    ("C_MINUS", 60),
    ("D_PLUS", 55),
    ("D", 50),
)  # below 50 -> "F"
GRADE_NAMES = [g for g, _ in GRADE_FLOORS] + ["F"]

# ---------------------------------------------------------------------------
# PRD §3.7 — suspension scan and rating disputes
# "An ACCREDITED business whose latest published score is below 75 is
# suspended"
# "A SUSPENDED business whose latest published score is 80 or higher is
# reinstated"
# "If that suspension would be the business's second within the trailing
# 730 days, the business is instead revoked"
# "filed no later than 10 days after the snapshot's published_at"
# ---------------------------------------------------------------------------
SUSPEND_SCORE_THRESHOLD = 75
REINSTATE_SCORE_THRESHOLD = 80
REVOKE_SUSPENSION_COUNT = 2
SUSPENSION_WINDOW_DAYS = 730
RATING_DISPUTE_WINDOW_DAYS = 10


# ---------------------------------------------------------------------------
# Derived helpers mirroring PRD formulas (integer cents, round-half-up at the
# two pinned points only — PRD §2.9 / §3.3).
# ---------------------------------------------------------------------------
def round_half_up_cents(value: Decimal) -> int:
    """Round a Decimal to whole cents using the PRD's round-half-up rule."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_dues_amount_cents(size_tier: str, local_fee_cents: int,
                               billing_plan: str) -> int:
    """PRD §3.3: amount_due_cents for the given frozen pricing inputs."""
    subtotal = DUES_BASE_CENTS[size_tier] + local_fee_cents
    if billing_plan == "ANNUAL_PREPAID":
        return round_half_up_cents(Decimal(subtotal) * ANNUAL_PREPAID_DISCOUNT_RATE)
    if billing_plan == "QUARTERLY":
        return round_half_up_cents(Decimal(subtotal) * QUARTERLY_SURCHARGE_RATE)
    raise ValueError(f"unknown billing_plan {billing_plan!r}")


def expected_installments(size_tier: str, local_fee_cents: int,
                          billing_plan: str) -> list:
    """PRD §3.3: the installments array for the given frozen pricing inputs.

    QUARTERLY rounds the surcharge total first, then the per-installment
    amount, and the 4th installment absorbs the rounding remainder.
    """
    total = expected_dues_amount_cents(size_tier, local_fee_cents, billing_plan)
    if billing_plan == "ANNUAL_PREPAID":
        return [{"installment": 1, "amount_cents": total}]
    per = round_half_up_cents(Decimal(total) / QUARTERLY_INSTALLMENT_COUNT)
    return [
        {"installment": 1, "amount_cents": per},
        {"installment": 2, "amount_cents": per},
        {"installment": 3, "amount_cents": per},
        {"installment": 4, "amount_cents": total - 3 * per},
    ]


def expected_size_tier(employee_count: int) -> str:
    """PRD §3.1 size-tier bands."""
    if employee_count <= TIER_MICRO_MAX_EMPLOYEES:
        return "MICRO"
    if employee_count <= TIER_SMALL_MAX_EMPLOYEES:
        return "SMALL"
    if employee_count <= TIER_MEDIUM_MAX_EMPLOYEES:
        return "MEDIUM"
    return "LARGE"


def expected_grade(score: int) -> str:
    """PRD §3.6 grade mapping; boundaries inclusive on the lower bound."""
    for grade, floor in GRADE_FLOORS:
        if score >= floor:
            return grade
    return "F"
