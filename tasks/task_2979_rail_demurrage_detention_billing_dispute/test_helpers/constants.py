"""Literal constants taken verbatim from the PRD.

Nothing in this module is invented: every enum member, every default and
every instant format is declared in PRD sections 2.x and 3.x.  Money is
always an integer count of cents (PRD 2.6) and never a string or a float.
"""

# ---------------------------------------------------------------------------
# PRD 2.1 - the five recognised role names carried in X-User-Role
# ---------------------------------------------------------------------------
ROLE_CUSTOMER = "Customer"
ROLE_RAILROAD_AGENT = "RailroadAgent"
ROLE_ADJUDICATOR = "DemurrageAdjudicator"
ROLE_REGULATORY_OFFICER = "RegulatoryOfficer"
ROLE_BILLING_ADMIN = "BillingAdmin"

ALL_ROLES = (
    ROLE_CUSTOMER,
    ROLE_RAILROAD_AGENT,
    ROLE_ADJUDICATOR,
    ROLE_REGULATORY_OFFICER,
    ROLE_BILLING_ADMIN,
)

# A syntactically valid but undeclared role name (PRD 2.8 band 1).
UNDECLARED_ROLE = "Stationmaster"

# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------
API_PREFIX = "/demurrage"

# PRD 2.3 pagination
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0
MAX_LIMIT = 100

# PRD 2.4 - the logical clock reads this on a cold start.
COLD_START_CLOCK = "2026-08-01T00:00:00.000Z"

# PRD 2.4 - every computed deadline or expiry lands on the last millisecond.
END_OF_DAY = "23:59:59.999Z"

# ---------------------------------------------------------------------------
# PRD 3.1 - Customer
# ---------------------------------------------------------------------------
CUSTOMER_STATUS_ACTIVE = "ACTIVE"
CUSTOMER_STATUS_SUSPENDED = "SUSPENDED"  # reserved; never written

BILLING_POSTURE_CURRENT = "CURRENT"
BILLING_POSTURE_CREDIT_HOLD = "CREDIT_HOLD"

DISPUTE_POSTURE_CLEAR = "CLEAR"
DISPUTE_POSTURE_UNDER_REVIEW = "UNDER_REVIEW"
DISPUTE_POSTURE_ESCALATED = "ESCALATED"

NOTIFICATION_METHOD_EDI = "EDI"
NOTIFICATION_METHOD_EMAIL = "EMAIL"
NOTIFICATION_METHOD_FAX = "FAX"

DEFAULT_NOTIFICATION_METHOD = NOTIFICATION_METHOD_EDI
DEFAULT_NORMAL_DAILY_PLACEMENT_CAPACITY = 2

# ---------------------------------------------------------------------------
# PRD 3.1 - Facility
# ---------------------------------------------------------------------------
FACILITY_KIND_INDUSTRY_TRACK = "INDUSTRY_TRACK"
FACILITY_KIND_RAIL_YARD = "RAIL_YARD"
FACILITY_KIND_INTERMODAL_TERMINAL = "INTERMODAL_TERMINAL"

STORAGE_CLOCK_CALENDAR = "CALENDAR_DAY_MIDNIGHT"
STORAGE_CLOCK_HOURLY = "HOURLY_FROM_ARRIVAL"

ACCESS_MODE_OPEN = "OPEN"
ACCESS_MODE_GATE_CONTROLLED = "GATE_CONTROLLED"
ACCESS_MODE_EMBARGOED = "EMBARGOED"

DEFAULT_FACILITY_KIND = FACILITY_KIND_INDUSTRY_TRACK
DEFAULT_STORAGE_CLOCK_MODE = STORAGE_CLOCK_CALENDAR
DEFAULT_GATE_OPEN_HOUR = 7
DEFAULT_GATE_CLOSE_HOUR = 16
DEFAULT_CAR_SPOT_CAPACITY = 3
DEFAULT_SWITCH_BUFFER_MINUTES = 120
DEFAULT_STORAGE_FREE_HOURS = 48
DEFAULT_STORAGE_DAILY_RATE_CENTS = 9000
DEFAULT_OPERATES_WEEKENDS = False

# ---------------------------------------------------------------------------
# PRD 3.1 - RailCar
# ---------------------------------------------------------------------------
OWNERSHIP_RAILROAD_OWNED = "RAILROAD_OWNED"
OWNERSHIP_PRIVATE = "PRIVATE"
OWNERSHIP_PRIVATE_ASSIGNED = "PRIVATE_ASSIGNED"

DEFAULT_CAR_TYPE = "BOXCAR"
DEFAULT_CAPACITY_TONS = 100

# ---------------------------------------------------------------------------
# PRD 3.1 - TariffRuleSet
# ---------------------------------------------------------------------------
TARIFF_STATUS_DRAFT = "DRAFT"
TARIFF_STATUS_PUBLISHED = "PUBLISHED"
TARIFF_STATUS_SUPERSEDED = "SUPERSEDED"
TARIFF_STATUS_CHALLENGED = "CHALLENGED"
TARIFF_STATUS_WITHDRAWN = "WITHDRAWN"

CAR_OWNERSHIP_SCOPE_ANY = "ANY"
CAR_OWNERSHIP_SCOPE_RAILROAD_OWNED = "RAILROAD_OWNED"
CAR_OWNERSHIP_SCOPE_PRIVATE = "PRIVATE"

DEFAULT_CAR_OWNERSHIP_SCOPE = CAR_OWNERSHIP_SCOPE_ANY
DEFAULT_FREE_TIME_HOURS_RAILROAD = 48
DEFAULT_FREE_TIME_HOURS_PRIVATE = 24
DEFAULT_TIER1_DAY_COUNT = 2
DEFAULT_TIER2_DAY_COUNT = 3
DEFAULT_TIER1_RATE_RAILROAD = 12550
DEFAULT_TIER2_RATE_RAILROAD = 22450
DEFAULT_TIER3_RATE_RAILROAD = 35050
DEFAULT_TIER1_RATE_PRIVATE = 8150
DEFAULT_TIER2_RATE_PRIVATE = 14950
DEFAULT_TIER3_RATE_PRIVATE = 24050
DEFAULT_WEEKEND_EXCLUDED = False
DEFAULT_NOTIFICATION_GRACE_HOURS = 4
DEFAULT_ADJUDICATION_DAYS_BASE = 20

# ---------------------------------------------------------------------------
# PRD 3.2 - PlacementCycle
# ---------------------------------------------------------------------------
MOVEMENT_ORDERED = "ORDERED"
MOVEMENT_CONSTRUCTIVELY_PLACED = "CONSTRUCTIVELY_PLACED"
MOVEMENT_ACTUALLY_PLACED = "ACTUALLY_PLACED"
MOVEMENT_RELEASED = "RELEASED"
MOVEMENT_VOIDED = "VOIDED"

BILLING_UNBILLED = "UNBILLED"
BILLING_INVOICED = "INVOICED"
BILLING_DISPUTED = "DISPUTED"
BILLING_ADJUSTED = "ADJUSTED"
BILLING_SETTLED = "SETTLED"

CLOCK_BASIS_NONE = "NONE"
CLOCK_BASIS_CONSTRUCTIVE = "CONSTRUCTIVE"
CLOCK_BASIS_ACTUAL = "ACTUAL"

REASON_TRACK_FULL = "TRACK_FULL"
REASON_GATE_CLOSED = "GATE_CLOSED"
REASON_CUSTOMER_HOLD = "CUSTOMER_HOLD"
REASON_EMBARGO = "EMBARGO"
REASON_YARD_ARRIVAL = "YARD_ARRIVAL"

# ---------------------------------------------------------------------------
# PRD 3.3 - CarNotification
# ---------------------------------------------------------------------------
CHANNEL_EDI = "EDI"
CHANNEL_EMAIL = "EMAIL"
CHANNEL_FAX = "FAX"

DELIVERY_SENT = "SENT"
DELIVERY_DELIVERED = "DELIVERED"
DELIVERY_ACKNOWLEDGED = "ACKNOWLEDGED"
DELIVERY_FAILED = "FAILED"

# ---------------------------------------------------------------------------
# PRD 3.2 / 3.5 - DemurrageCharge
# ---------------------------------------------------------------------------
CHARGE_KIND_DEMURRAGE = "DEMURRAGE"
CHARGE_KIND_DETENTION = "DETENTION"
CHARGE_KIND_STORAGE = "STORAGE"

CHARGE_PROVISIONAL = "PROVISIONAL"
CHARGE_FINAL = "FINAL"
CHARGE_DISPUTED = "DISPUTED"
CHARGE_ADJUSTED = "ADJUSTED"
CHARGE_VOIDED = "VOIDED"

BASIS_CONSTRUCTIVE = "CONSTRUCTIVE"
BASIS_ACTUAL = "ACTUAL"
BASIS_STORAGE_CALENDAR = "STORAGE_CALENDAR"
BASIS_STORAGE_HOURLY = "STORAGE_HOURLY"

# ---------------------------------------------------------------------------
# PRD 3.7 - Invoice and AverageAgreement
# ---------------------------------------------------------------------------
INVOICE_DRAFT = "DRAFT"
INVOICE_ISSUED = "ISSUED"
INVOICE_PARTIALLY_DISPUTED = "PARTIALLY_DISPUTED"
INVOICE_ADJUSTED = "ADJUSTED"
INVOICE_CLOSED = "CLOSED"

AGREEMENT_OPEN = "OPEN"
AGREEMENT_RECONCILED = "RECONCILED"
AGREEMENT_FORFEITED = "FORFEITED"

DEFAULT_CREDIT_CAP_RATIO = 0.30

# ---------------------------------------------------------------------------
# PRD 3.6 - BunchingClaim
# ---------------------------------------------------------------------------
CLAIM_SUBMITTED = "SUBMITTED"
CLAIM_ANALYZED = "ANALYZED"
CLAIM_GRANTED = "GRANTED"
CLAIM_PARTIALLY_GRANTED = "PARTIALLY_GRANTED"
CLAIM_DENIED = "DENIED"

METHOD_ORDERED_VS_CAPACITY = "ORDERED_VS_CAPACITY"
METHOD_ROLLING_AVERAGE_BASELINE = "ROLLING_AVERAGE_BASELINE"

MAX_CLUSTER_WINDOW_DATES = 14

# ---------------------------------------------------------------------------
# PRD 3.8 - DemurrageDispute and DisputeEvidence
# ---------------------------------------------------------------------------
DISPUTE_DRAFT = "DRAFT"
DISPUTE_SUBMITTED = "SUBMITTED"
DISPUTE_UNDER_REVIEW = "UNDER_REVIEW"
DISPUTE_INFO_REQUESTED = "INFO_REQUESTED"
DISPUTE_DECIDED = "DECIDED"
DISPUTE_APPEALED = "APPEALED"
DISPUTE_ESCALATED = "ESCALATED"
DISPUTE_CLOSED = "CLOSED"

SCOPE_SINGLE_CHARGE = "SINGLE_CHARGE"
SCOPE_WHOLE_INVOICE = "WHOLE_INVOICE"

GROUNDS_RAILROAD_CAUSED_DELAY = "RAILROAD_CAUSED_DELAY"
GROUNDS_BUNCHING = "BUNCHING"
GROUNDS_NOTIFICATION_FAILURE = "NOTIFICATION_FAILURE"
GROUNDS_RATE_UNREASONABLE = "RATE_UNREASONABLE"
GROUNDS_CLOCK_BASIS_ERROR = "CLOCK_BASIS_ERROR"

# PRD 3.8 - the grounds multiplier applied to adjudication_days_base.
GROUNDS_MULTIPLIER = {
    GROUNDS_RAILROAD_CAUSED_DELAY: 1.00,
    GROUNDS_BUNCHING: 1.25,
    GROUNDS_NOTIFICATION_FAILURE: 0.75,
    GROUNDS_RATE_UNREASONABLE: 1.50,
    GROUNDS_CLOCK_BASIS_ERROR: 1.00,
}

DECISION_PENDING = "PENDING"
DECISION_ALLOWED = "ALLOWED"
DECISION_PARTIALLY_ALLOWED = "PARTIALLY_ALLOWED"
DECISION_DENIED = "DENIED"

EVIDENCE_SWITCH_LIST = "SWITCH_LIST"
EVIDENCE_GATE_LOG = "GATE_LOG"
EVIDENCE_EMAIL_NOTICE = "EMAIL_NOTICE"
EVIDENCE_TRACK_EMBARGO_NOTICE = "TRACK_EMBARGO_NOTICE"
EVIDENCE_WEIGHT_CERTIFICATE = "WEIGHT_CERTIFICATE"

# PRD 3.8 - weight_points is fixed by the exhibit's class, server-side.
EVIDENCE_WEIGHT_POINTS = {
    EVIDENCE_SWITCH_LIST: 3,
    EVIDENCE_GATE_LOG: 3,
    EVIDENCE_EMAIL_NOTICE: 1,
    EVIDENCE_TRACK_EMBARGO_NOTICE: 4,
    EVIDENCE_WEIGHT_CERTIFICATE: 2,
}

# ---------------------------------------------------------------------------
# PRD 3.9 - RegulatoryComplaint
# ---------------------------------------------------------------------------
COMPLAINT_FILED = "FILED"
COMPLAINT_RAILROAD_ANSWERED = "RAILROAD_ANSWERED"
COMPLAINT_DECIDED_FOR_CUSTOMER = "DECIDED_FOR_CUSTOMER"
COMPLAINT_DECIDED_FOR_RAILROAD = "DECIDED_FOR_RAILROAD"
COMPLAINT_DISMISSED = "DISMISSED"

COMPLAINT_TYPE_RULE_REASONABLENESS = "RULE_REASONABLENESS"
COMPLAINT_TYPE_BILLING_PRACTICE = "BILLING_PRACTICE"

DOCKET_NUMBER_PATTERN = r"^D-[0-9]{5}$"

# ---------------------------------------------------------------------------
# The shared reference timeline.  "Cycle A" is the industry-track chain that
# every §1.8 and §1.9 design instance is written against; the instants and the
# money below are all derivable from PRD 3.3 / 3.5 / 3.6 at the tariff and
# facility defaults for a RAILROAD_OWNED car.
# ---------------------------------------------------------------------------
CYCLE_A_CONSTRUCTIVE_AT = "2026-08-03T08:00:00.000Z"
CYCLE_A_NOTICE_SENT_AT = "2026-08-03T09:00:00.000Z"
# notification_sent_at + notification_grace_hours (4) = the effective notice.
CYCLE_A_CONSTRUCTIVE_START = "2026-08-03T13:00:00.000Z"
CYCLE_A_CONSTRUCTIVE_EXPIRY = "2026-08-05T23:59:59.999Z"
CYCLE_A_ACTUAL_AT = "2026-08-05T10:00:00.000Z"
CYCLE_A_ACTUAL_EXPIRY = "2026-08-07T23:59:59.999Z"
CYCLE_A_RELEASE_AT = "2026-08-10T16:00:00.000Z"
CYCLE_A_CHARGEABLE_DAYS = 3
CYCLE_A_GROSS_CENTS = 47550  # 2 x 12550 + 1 x 22450

CYCLE_B_CONSTRUCTIVE_AT = "2026-08-05T08:00:00.000Z"
CYCLE_B_NOTICE_SENT_AT = "2026-08-05T09:00:00.000Z"
CYCLE_B_ACTUAL_AT = "2026-08-07T12:00:00.000Z"
CYCLE_B_RELEASE_AT = "2026-08-11T09:00:00.000Z"
CYCLE_B_CHARGEABLE_DAYS = 1
CYCLE_B_GROSS_CENTS = 12550

# PRD 3.7 - the closed billing period the reference releases fall inside.
BILLING_PERIOD_START = "2026-08-01T00:00:00.000Z"
BILLING_PERIOD_END = "2026-08-31T23:59:59.999Z"
AGREEMENT_MONTH = "2026-08"

# The two-line dispute worked example of PRD 2.6 / 3.8.
TWO_LINE_GROSSES = (47550, 12550)
TWO_LINE_ALLOWANCE_PCT = 0.65
TWO_LINE_PER_LINE_CREDIT = (30908, 8158)
TWO_LINE_CREDIT_TOTAL = 39066  # per-line half-up then summed
TWO_LINE_CREDIT_ROUND_THE_SUM = 39065  # the wrong answer PRD 2.6 names
TWO_LINE_GROSS_TOTAL = 60100
TWO_LINE_NET_TOTAL = 21034

# ---------------------------------------------------------------------------
# Logical-clock stations used by the composite fixtures, and the deadlines
# PRD 3.7 / 3.8 / 3.9 derive from them.  Each station is chosen so that the
# assertion the design index asks for lands on a real, computable date:
#
#   issue    at 2026-08-12 -> dispute_deadline_at 30 calendar days later
#   submit   at 2026-08-14 -> 19 business dates later = 2026-09-10
#                             25 business dates later = 2026-09-18
#   info req at 2026-08-20 -> 10 business dates strictly after = 2026-09-03
#   appeal   at 2026-09-01 -> 10 business dates later          = 2026-09-15
#   complaint at 2026-09-05 -> 15 business dates strictly after = 2026-09-25
# ---------------------------------------------------------------------------
CLOCK_AFTER_RELEASE = "2026-08-11T00:00:00.000Z"
CLOCK_AT_ISSUE = "2026-08-12T00:00:00.000Z"
CLOCK_AT_SUBMIT = "2026-08-14T00:00:00.000Z"
CLOCK_AT_INFO_REQUEST = "2026-08-20T00:00:00.000Z"
CLOCK_AT_APPEAL = "2026-09-01T00:00:00.000Z"
CLOCK_AT_COMPLAINT = "2026-09-05T00:00:00.000Z"

DISPUTE_DEADLINE_FROM_ISSUE = "2026-09-11T23:59:59.999Z"
DUE_AT_BASE_20_MULT_1_00_WEIGHT_3 = "2026-09-10T23:59:59.999Z"
DUE_AT_BASE_20_MULT_1_50_WEIGHT_CAPPED = "2026-09-18T23:59:59.999Z"
DUE_AT_AFTER_INFO_REQUEST = "2026-09-03T23:59:59.999Z"
DUE_AT_APPEAL_ROUND = "2026-09-15T23:59:59.999Z"
COMPLAINT_RESPONSE_DUE_AT = "2026-09-25T23:59:59.999Z"
COMPLAINT_FILED_AT = "2026-09-05T00:00:00.000Z"
