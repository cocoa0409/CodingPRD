"""Domain constants for the CMAR guaranteed-maximum-price administration API.

Every literal here is taken from the product requirements: the fixed milestone
ranking, the thresholds the business rules compare against, the enum vocabularies
of the ten collections, and the canonical instants of the logical clock.
"""

from decimal import Decimal

# --- Roles -----------------------------------------------------------------

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_CONSTRUCTION_MANAGER = "ConstructionManager"
ROLE_PROCUREMENT_OFFICER = "ProcurementOfficer"
ROLE_OWNER_REPRESENTATIVE = "OwnerRepresentative"
ROLE_INDEPENDENT_AUDITOR = "IndependentAuditor"

ALL_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_CONSTRUCTION_MANAGER,
    ROLE_PROCUREMENT_OFFICER,
    ROLE_OWNER_REPRESENTATIVE,
    ROLE_INDEPENDENT_AUDITOR,
)

# --- Logical clock ---------------------------------------------------------

#: The instant the logical clock reads at server startup.
CLOCK_START = "2026-08-01T00:00:00Z"
#: The close instant used by the standard solicitation window in the fixtures.
SOLICITATION_CLOSE = "2026-08-15T00:00:00Z"

# --- Thresholds and rates --------------------------------------------------

MILESTONE_RANK = {"SD": 1, "DD": 2, "CD_50": 3, "CD_100": 4, "GMP_BASIS": 5}

#: A variance strictly greater than this requires a justification note at submit.
MILESTONE_VARIANCE_THRESHOLD_PCT = Decimal("0.0500")
#: A construction draw strictly greater than this requires owner approval.
DRAW_OWNER_APPROVAL_THRESHOLD = Decimal("50000.00")
#: A remaining construction-contingency percentage at or below this is CONSTRAINED.
CONSTRAINED_POSTURE_PCT = Decimal("0.1000")
#: Termination for default books the unpaid balance times this multiplier.
REPLACEMENT_PREMIUM_MULTIPLIER = Decimal("1.15")
#: Clear hours a new performance window needs from every blocking sibling.
MOBILIZATION_BUFFER_HOURS = 72

SAVINGS_TIER_1_MAX_PCT = Decimal("0.02")
SAVINGS_TIER_2_MAX_PCT = Decimal("0.05")
SAVINGS_TIER_1_CM_RATE = Decimal("0.25")
SAVINGS_TIER_2_CM_RATE = Decimal("0.35")
SAVINGS_TIER_3_CM_RATE = Decimal("0.50")
CM_SHARE_CAP_OF_FEE_PCT = Decimal("0.25")

MONEY_PRECISION = 2
RATIO_PRECISION = 4

MAX_CM_FEE_PCT = Decimal("0.1500")
MAX_INSURANCE_RATE = Decimal("0.0500")

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

HELD_REASON_CONSTRAINED = "CONSTRUCTION_CONTINGENCY_CONSTRAINED"

# --- Enum vocabularies -----------------------------------------------------

GMP_STATUSES = ("PRECONSTRUCTION", "GMP_UNDER_REVIEW", "EXECUTED", "CLOSED")
CONTINGENCY_POSTURES = ("OPEN", "CONSTRAINED", "FROZEN")
AUDIT_STATUSES = ("NOT_REQUESTED", "IN_PROGRESS", "CLOSED")
CLOSEOUT_STATUSES = (
    "NOT_STARTED",
    "PROVISIONAL_COMPUTED",
    "FINAL_COMPUTED",
    "SETTLEMENT_EXECUTED",
)

MILESTONE_CODES = ("SD", "DD", "CD_50", "CD_100", "GMP_BASIS")
ESTIMATE_STATUSES = ("DRAFT", "SUBMITTED", "RECONCILED", "RETURNED", "SUPERSEDED")
VARIANCE_BASES = ("NO_BASIS", "DECLARED_PRIOR", "HIGHEST_RECONCILED_MILESTONE")

PROPOSAL_TYPES = ("BASE", "AMENDMENT")
PROPOSAL_STATUSES = (
    "DRAFT",
    "OWNER_REVIEW",
    "RETURNED_FOR_REVISION",
    "EXECUTED",
    "REJECTED",
    "SUPERSEDED",
)
PROPOSAL_DECISIONS = ("EXECUTE", "RETURN", "REJECT")

ITEM_TYPES = ("ASSUMPTION", "ALLOWANCE", "CLARIFICATION", "EXCLUSION")
ALLOWANCE_ACTIONS = ("RECONCILE", "REVERSE")
ALLOWANCE_LAST_ACTIONS = ("NONE", "RECONCILE", "REVERSE")
ALLOWANCE_STATUSES = ("OPEN", "PARTIALLY_RECONCILED", "FULLY_RECONCILED")

PROCUREMENT_STATUSES = ("BUDGETED", "SOLICITING", "AWARDED", "REPROCUREMENT", "CLOSED")
TRANSPARENCY_STATUSES = ("SEALED", "DISCLOSED", "AUDITED")

BIDDER_TYPES = ("CM_SELF_PERFORM", "THIRD_PARTY")
BID_STATUSES = ("SEALED", "OPENED", "AWARDED", "NOT_AWARDED")
OPEN_BOOK_COMPONENTS = ("labor", "material", "equipment", "overhead", "profit")

CONTRACT_STATUSES = ("ACTIVE", "DEFAULT_NOTICED", "TERMINATED_FOR_DEFAULT", "COMPLETED")
SUBCONTRACT_ACTIONS = ("NOTICE_DEFAULT", "CURE", "COMPLETE", "TERMINATE_FOR_DEFAULT")
BOND_CLAIM_STATUSES = (
    "NOT_APPLICABLE",
    "NONE",
    "FILED",
    "ACKNOWLEDGED",
    "SETTLED",
    "DENIED",
)
BOND_CLAIM_ACTIONS = ("FILE", "ACKNOWLEDGE", "SETTLE", "DENY")

CHANGE_EVENT_ORIGINS = (
    "OWNER_DIRECTIVE",
    "DESIGN_DEVELOPMENT",
    "FIELD_CONDITION",
    "SUBCONTRACTOR_DEFAULT",
    "ALLOWANCE_OVERRUN",
)
CHANGE_EVENT_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "REVISION_REQUESTED",
    "CLASSIFIED",
    "REJECTED",
)
CHANGE_EVENT_REVIEW_ACTIONS = ("BEGIN_REVIEW", "REQUEST_REVISION", "REJECT")
CLASSIFICATIONS = (
    "SCOPE_CHANGE",
    "CONTINGENCY_USE_OWNER",
    "CONTINGENCY_USE_CONSTRUCTION",
)

CONTINGENCY_TYPES = ("OWNER", "CONSTRUCTION")
DRAW_ORIGINS = ("CHANGE_EVENT_CLASSIFICATION", "SUBCONTRACTOR_DEFAULT_PREMIUM")
DRAW_STATUSES = ("REQUESTED", "OWNER_APPROVED", "POSTED", "VOIDED", "DENIED")

COST_REPORT_STATUSES = ("OPEN", "RECONCILED", "DISPUTED", "RECONCILIATION_HELD")
COST_REPORT_DECISIONS = ("RECONCILE", "DISPUTE")

AUDIT_ACTIONS = ("POST_ADJUSTMENT", "CLOSE")
SAVINGS_BASES = ("PRE_AUDIT_PROVISIONAL", "POST_AUDIT_FINAL")

# --- The standard priced project used across the suite ---------------------
#
# A project at cm_fee_pct 0.04 / insurance_rate 0.01 priced from a
# 1,000,000.00 cost of work and 100,000.00 of general conditions with a
# 50,000.00 owner pot and a 40,000.00 construction pot prices out, through the
# four pinned steps, to the figures below.

STD_COST_OF_WORK = Decimal("1000000.00")
STD_GENERAL_CONDITIONS = Decimal("100000.00")
STD_OWNER_CONTINGENCY = Decimal("50000.00")
STD_CONSTRUCTION_CONTINGENCY = Decimal("40000.00")
STD_CM_FEE_PCT = Decimal("0.04")
STD_INSURANCE_RATE = Decimal("0.01")

STD_PROVISIONAL_FEE_AMOUNT = Decimal("44000.00")
STD_INSURANCE_AMOUNT = Decimal("11440.00")
STD_CM_FEE_AMOUNT = Decimal("44457.60")
STD_GMP_AMOUNT = Decimal("1245897.60")
