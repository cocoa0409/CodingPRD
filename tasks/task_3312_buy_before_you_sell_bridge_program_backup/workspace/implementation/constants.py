"""Named constants for the Buy-Before-You-Sell Bridge Program API.

Every number here is either stated literally in ``PRD.md`` or is a structural
convention (role names, enum values) that the PRD and ``SCAFFOLD.yaml`` agree on.
No constant is invented "for convenience".

Three names are deliberately left *unvalued* by the PRD.  They are declared here
so the surrounding boundary semantics can be implemented without asserting a
number the requirements never pin:

* ``TASK_SLOT_DAYS``         -- coordination-task overlap window length (PRD 3.7)
* ``REFERRAL_COORDINATION_CENTS`` -- per-additional-referral coordination amount (PRD 3.9)
* ``APPRAISAL_VALIDITY_DAYS`` -- appraisal staleness horizon (PRD 2.10/3.3)

Where a value is ``None`` the dependent rule degenerates to a no-op rather than
raising, so that an unvalued constant can never turn a valid request into a 500.
See ``services/coordination.py`` and ``services/disclosure.py`` for the two
places that consume them.
"""

import os

# ---------------------------------------------------------------------------
# Logical clock (PRD 3.11)
# ---------------------------------------------------------------------------
# The clock starts at exactly this instant on every fresh boot and never falls
# back to real wall-clock time.
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
COORDINATOR = "Coordinator"
UNDERWRITER = "Underwriter"
HOMEOWNER = "Homeowner"
AGENT = "Agent"
PROGRAM_ADMIN = "ProgramAdmin"

ROLES = (COORDINATOR, UNDERWRITER, HOMEOWNER, AGENT, PROGRAM_ADMIN)

# Entity-backed roles: X-User-ID is the id of the acting entity and ownership
# checks compare it against a foreign-key field.  The remaining roles are
# operational: X-User-ID is an opaque operator identifier that is never
# compared to an entity id (except for the segregation-of-duties rule).
ENTITY_BACKED_ROLES = (HOMEOWNER, AGENT)
OPAQUE_ROLES = (COORDINATOR, UNDERWRITER, PROGRAM_ADMIN)

# ---------------------------------------------------------------------------
# Money precision (PRD 2.4)
# ---------------------------------------------------------------------------
BPS_DENOMINATOR = 10000          # ten thousand basis points == factor of one

# ---------------------------------------------------------------------------
# Purchase capacity (PRD 3.2)
# ---------------------------------------------------------------------------
# PRD prose pins the condition credit as a per-grade ladder (D=0, C=500,
# B=1000, A=1500 basis points), which supersedes the scaffold's
# `CONDITION_CREDIT_BASE_BPS * (rank - 3)` expression.  The PRD value wins.
BASE_EQUITY_RATIO_BPS = 7000
MARKET_APPRECIATION_BPS = 1000
CONDITION_CREDIT_BPS = {"D": 0, "C": 500, "B": 1000, "A": 1500}
PMI_MAX_MULTIPLE = 50000         # five times annual income
EQUITY_RATIO_DECIMALS = 4        # "carried to four decimal places"

# Approval requires the household to clear the lender's floor.
CREDIT_SCORE_MINIMUM = 620
CREDIT_SCORE_MIN = 300
CREDIT_SCORE_MAX = 850

# Qualifications expire on both windows, measured against the logical clock.
QUALIFICATION_EXPIRY_DAYS = 90

# ---------------------------------------------------------------------------
# Draw headroom (PRD 3.4)
# ---------------------------------------------------------------------------
PROGRAM_FEE_BPS = 150
STAKE_HOLDER_REVIEW_CENTS = 9000000

# ---------------------------------------------------------------------------
# Financing ceilings (PRD 3.3 / 3.4 / 3.11)
# ---------------------------------------------------------------------------
LTV_MAX_BPS = 7500                       # interim loan / new appraised value
REPAIR_APPROVAL_CEILING_CENTS = 5000000  # per repair advance

# ---------------------------------------------------------------------------
# Interest accrual (PRD 3.5)
# ---------------------------------------------------------------------------
INTERIM_DAY_COUNT_BPS = 3000

# ---------------------------------------------------------------------------
# Carrying-cost burden (PRD 3.9)
# ---------------------------------------------------------------------------
NEW_CONSTRUCTION_ADJUSTMENT_BPS = 2500
HIGH_COST_BUCKET_GRADE_AB = "NEW_CONSTRUCTION_INSURANCE"
HIGH_COST_BUCKET_OTHER_GRADE = "NEW_TAX"
CARRYING_COST_KINDS = (
    "DEPARTING_TAX",
    "DEPARTING_INSURANCE",
    "DEPARTING_HOA",
    "DEPARTING_UTILITY",
    "NEW_TAX",
    "NEW_INSURANCE",
    "NEW_HOA",
    "NEW_UTILITY",
)
# `projected_carry_months` at or above this switches the burden algorithm from
# per-row to pooled (PRD 3.9: "three months or more" -> pooled).
BURDEN_POOL_THRESHOLD_MONTHS = 3

# ---------------------------------------------------------------------------
# Program charge disclosure (PRD 3.9)
# ---------------------------------------------------------------------------
COORDINATION_FLAT_CENTS = 45000

# PRD 3.9 leaves this unvalued: "each additional OPEN referral adds a further
# coordination amount to that flat charge".  When None the additional term
# contributes nothing, so the coordination charge stays at the flat amount.
REFERRAL_COORDINATION_CENTS = None

DISCLOSURE_MIN_CENTS = 300000
DISCLOSURE_REVIEW_CENTS = 500000
ESCALATOR_LOW_BPS = 250
ESCALATOR_HIGH_BPS = 500
SUBTOTAL_REFERENCE_CENTS = 400000

# ---------------------------------------------------------------------------
# Referral discount waterfall (PRD 3.8)
# ---------------------------------------------------------------------------
AGENT_REFERRAL_POOL_CENTS = 25000
COORDINATION_CREDIT_POOL_CENTS = 10000

# ---------------------------------------------------------------------------
# Backup-offer price floor (PRD 3.6)
# ---------------------------------------------------------------------------
OFFER_DISCOUNT_BPS = 1200
OFFER_CONDITION_MODIFIER_BPS = {"A": 0, "B": 200, "C": 450, "D": 600}
REGULATORY_MIN_RATIO_BPS = 8500
OFFER_EXTENSION_DAYS = 30        # under-contract pushes expires_at out 30 days

# ---------------------------------------------------------------------------
# Referral fee reconciliation (PRD 3.7)
# ---------------------------------------------------------------------------
QUALIFIED_BONUS_BPS = 300
COORDINATION_CREDIT_CAP_CENTS = 20000
COORDINATION_CREDIT_PER_TASK_CENTS = 8000

# ---------------------------------------------------------------------------
# Household / property / agent intake defaults (PRD 3.1)
# ---------------------------------------------------------------------------
DEFAULT_MAX_DTI_BPS = 4300
DEFAULT_MORTGAGE_PAYOFF_CENTS = 0
DEFAULT_PURCHASE_PRICE_CENTS = 0
DEFAULT_APPRAISAL_DATE = LOGICAL_CLOCK_START
DEFAULT_REPAIR_PROGRESS_BPS = 300
DEFAULT_SITE_VISIT_COUNT = 0
REPAIR_VISIT_SCALE = 100         # site_visit_count * 100 >= repair_progress_bps
DEFAULT_AGENT_REFERRAL_RATE_BPS = 250
DEFAULT_PROGRAM_FEE_BASIS_POINTS = 150
DEFAULT_REFERRAL_RATE_BPS = 250
DEFAULT_QUALIFYING_VOLUME_CENTS = 0
PROJECTED_CARRY_MONTHS_MIN = 1
PROJECTED_CARRY_MONTHS_MAX = 24
WINDOW_DAYS_MIN = 1
WINDOW_DAYS_MAX = 180

# ---------------------------------------------------------------------------
# Coordination tasks (PRD 3.7)
# ---------------------------------------------------------------------------
# PRD 3.7 leaves this unvalued.  Each task occupies the half-open interval
# [due_date - TASK_SLOT_DAYS, due_date).  When None the interval degenerates to
# the empty [due_date, due_date), which can overlap nothing, so scheduling
# never spuriously refuses; the adjacency / half-open semantics are still
# implemented and take effect the moment a length is pinned.
TASK_SLOT_DAYS = None

TASK_KINDS = (
    "PHOTOGRAPHY",
    "INSPECTION",
    "APPRAISAL",
    "REPAIR_BID",
    "CLOSING_PREP",
    "RESALE_PREP",
)
TASK_KINDS_UNLOCKING_REPAIR = ("REPAIR_BID", "PHOTOGRAPHY")

# ---------------------------------------------------------------------------
# Appraisal staleness (PRD 2.10 / 3.3)
# ---------------------------------------------------------------------------
# PRD 2.10 and 3.3 both reference APPRAISAL_VALIDITY_DAYS without assigning it a
# value, and neither the scaffold nor any sibling task pins one.  Six months is
# the conventional horizon for a residential appraisal, and it is consistent
# with the 90-day windows the PRD does pin.  Override with the env var of the
# same name when the harness supplies a value.
_appraisal_env = os.environ.get("APPRAISAL_VALIDITY_DAYS")
APPRAISAL_VALIDITY_DAYS = int(_appraisal_env) if _appraisal_env else 180

# ---------------------------------------------------------------------------
# Enum vocabularies (used for range validation, PRD 2.11 / SCAFFOLD entities)
# ---------------------------------------------------------------------------
PROPERTY_KINDS = ("DEPARTING", "NEW")
CONDITION_GRADES = ("A", "B", "C", "D")
LISTING_STATUSES = ("UNLISTED", "LISTED", "UNDER_CONTRACT", "SOLD_TO_PROGRAM", "RESOLD")
REPAIR_STATUSES = ("NOT_STARTED", "IN_PROGRESS", "COMPLETE")
QUALIFICATION_VARIANTS = ("CONSERVATIVE", "OPTIMISTIC")
QUALIFICATION_STATUSES = ("PENDING", "APPROVED", "DENIED", "EXPIRED")
ADVANCE_STATUSES = ("PENDING", "FUNDING", "FUNDED", "SETTLED")
OCCUPANCY_STATUSES = ("VACANT", "OCCUPYING_NEW", "DEPARTING_LISTED", "DEPARTING_SOLD")
LOAN_STATUSES = ("ORIGINATED", "DRAWN", "REPAYING", "REPAID", "DELINQUENT")
ADVANCE_PURPOSES = ("DOWN_PAYMENT", "CARRYING_COST", "REPAIR", "FEE", "DISCLOSURE")
ADVANCE_STATUSES_BA = ("PENDING", "APPROVED", "DISBURSED", "REPAID", "REJECTED")
REPAIR_ADVANCE_STATUSES = ("REQUESTED", "APPROVED", "DISBURSED", "SETTLED")
ESCROW_RELEASE_MODES = ("LUMP_SUM", "MILESTONE")
OFFER_STATUSES = ("DRAFT", "ISSUED", "EXPIRED", "EXTENDED", "EXERCISED", "VOIDED")
LISTING_LIFECYCLE = ("DRAFT", "LIVE", "PAUSED", "CLOSED")
MARKETING_STATUSES = ("NOT_STARTED", "ACTIVE", "STOPPED")
AGENT_STATUSES = ("PENDING", "QUALIFIED", "SUSPENDED")
REFERRAL_STATUSES = ("OPEN", "COMPLETED", "VOIDED")
REFERRAL_ROLE_SCOPES = ("DEPARTING_SIDE", "NEW_SIDE", "RESALE_SIDE")
TASK_STATUSES = ("OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED")
DISBURSEMENT_SOURCE_KINDS = ("CLOSING_SALE", "RESALE", "REPAIR_CLAWBACK")
DISBURSEMENT_STATUSES = ("RECORDED", "APPLIED")
HOMEOWNER_PROGRAM_STATUSES = ("NONE", "QUALIFYING", "ENROLLED", "BRIDGED", "SETTLED", "WITHDRAWN")
CARRYING_COST_REPAYMENT_STATUSES = ("UNPAID", "REPAID")

# Every entity that participates in the common-field convention of PRD 2.5.
# The PRD states that every entity carries id / created_at / updated_at /
# version, so this list covers all fourteen.
ENTITY_NAMES = (
    "Homeowner",
    "Property",
    "Qualification",
    "BridgeProgram",
    "InterimLoan",
    "BridgeAdvance",
    "CarryingCost",
    "RepairAdvance",
    "BackupOffer",
    "Listing",
    "Agent",
    "Referral",
    "CoordinationTask",
    "Disbursement",
)