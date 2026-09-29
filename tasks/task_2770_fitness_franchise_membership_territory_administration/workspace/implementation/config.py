"""Domain constants for the fitness franchise administration API.

Every value here is transcribed literally from PRD.md / SCAFFOLD.yaml.
"""
from decimal import Decimal

API_PREFIX = "/franchise"

ROLES = (
    "BrandAdministrator",
    "FranchiseOwner",
    "ClubManager",
    "ComplianceAuditor",
    "BillingPartner",
    "Member",
)
ALL_ROLES = list(ROLES)

STATE_CODES = ("CA", "TX", "NY")

# 2.9 State Health-Club Statutes
STATE_STATUTES = {
    "CA": {"cooling_off_days": 5, "max_notice_days": 30, "prorate_on_cancel": True,
           "cross_state_transfer_allowed": False},
    "TX": {"cooling_off_days": 3, "max_notice_days": 30, "prorate_on_cancel": True,
           "cross_state_transfer_allowed": True},
    "NY": {"cooling_off_days": 3, "max_notice_days": 15, "prorate_on_cancel": False,
           "cross_state_transfer_allowed": True},
}

# effective_monthly_dues
MULTI_CLUB_CREDIT_PCT = Decimal("0.015")
MAX_FRANCHISE_DISCOUNT_PCT = Decimal("0.30")
PROMO_COOLING_GAP_DAYS = 7

# royalty_due
BRAND_STANDARD_DUES_CENTS = 4500
ROYALTY_VARIANCE_TOLERANCE_PCT = Decimal("5.00")

# inspection_score
BRAND_REFRESH_CYCLE_MONTHS = 60
ACCELERATED_REFRESH_CYCLE_MONTHS = 42
ACCELERATED_MANDATE_DATE = "2020-01-01"
REMEDIATION_SCORE_THRESHOLD = 70

# usage_settlement_net
ADMIN_HOLD_PCT = Decimal("0.08")
REBATE_TIER_1_FLOOR = 50000
REBATE_TIER_2_FLOOR = 100000

# dues_ledger_projection
DELINQUENCY_DAYS_THRESHOLD = 30
COLLECTIONS_DAYS_THRESHOLD = 60

# cancellation_settlement
EARLY_TERM_MONTHLY_PCT = Decimal("0.5")
EARLY_TERM_FEE_CAP_CENTS = 15000

# transfer_fee
TRANSFER_FEE_BASE_CENTS = 2500
CROSS_FRANCHISE_TRANSFER_PCT = Decimal("0.5")
TRANSFER_FEE_DUE_DAYS = 15

# territory_encroachment_slack
KM_PER_DEG_LAT = Decimal("111.0")
KM_PER_DEG_LNG = Decimal("85.0")
PROTECTION_BUFFER_KM = Decimal("0.5")
RELOCATION_REVISION_LIMIT = 2

# club_delinquency_share
COLLECTIONS_WATCH_SHARE = Decimal("0.15")

# franchisee_compliance_score
INSPECTION_FAIL_PENALTY = 20
COLLECTIONS_WATCH_PENALTY = 20
DISPUTED_ROYALTY_PENALTY = 10
PROBATION_SCORE_THRESHOLD = 70

DELINQUENT_DUES_STATES = ("DELINQUENT", "IN_COLLECTIONS", "WRITTEN_OFF")
LIVE_AGREEMENT_STATES = ("ACTIVE", "FROZEN", "CANCELLATION_PENDING")
HELD_AGREEMENT_STATES = ("PENDING", "ACTIVE", "FROZEN", "CANCELLATION_PENDING")
ENROLLED_AGREEMENT_STATES = ("ACTIVE", "CANCELLATION_PENDING")
OPEN_RELOCATION_STATES = ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED")
