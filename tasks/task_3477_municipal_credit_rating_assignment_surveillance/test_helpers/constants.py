"""Domain constants for the Municipal Credit Ratings API.

Every literal in this module is transcribed from the PRD itself:

* mount points and the logical-clock start (PRD sections 1 and 2.4),
* the seven role names (PRD section 2.1),
* pagination bounds (PRD section 2.3),
* the seven-step notch scale and the four outlooks (PRD section 2.5),
* fee schedule and withdrawal refund ratio (PRD section 3.1),
* the document registry and the unsolicited requirement (PRD sections 3.1/3.2),
* anchor thresholds, factor-score bounds and the weak-link cap (PRD section 3.2),
* committee size, quorum, deviation band, cooling-off (PRD section 3.3),
* the 120-hour appeal window (PRD section 3.4),
* disclosure, delinquency, default and reinstatement day counts (PRD section 3.5),
* the 90-day review window and the weight-sum rule (PRD section 3.6),
* benchmark yield, spread schedule and par/maturity bounds (PRD section 3.7),
* notification event types (PRD section 2.11).

Nothing here is guessed: a value that the PRD leaves open (for example the
per-credit-type document requirement sets for SOLICITED engagements) is
deliberately NOT frozen here; fixtures read such sets back from the server.
"""

from decimal import Decimal

# ─── Mount points (PRD sections 1 / 2.4 / 4) ────────────────────────────────

API_PREFIX = "/muni"

# "this platform endpoint is deliberately mounted outside the `/muni` prefix
# at `/_clock/set_current_utc`" (PRD section 2.4).
CLOCK_PATH = "/_clock/set_current_utc"

# "the clock stands at exactly 2026-09-01T00:00:00Z" (PRD section 2.4).
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# ─── Roles (PRD section 2.1) ────────────────────────────────────────────────

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_ISSUER = "Issuer"
ROLE_UNDERWRITER = "Underwriter"
ROLE_LEAD_ANALYST = "LeadAnalyst"
ROLE_COMMITTEE_CHAIR = "CommitteeChair"
ROLE_COMMITTEE_MEMBER = "CommitteeMember"
ROLE_SURVEILLANCE_OFFICER = "SurveillanceOfficer"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_ISSUER,
    ROLE_UNDERWRITER,
    ROLE_LEAD_ANALYST,
    ROLE_COMMITTEE_CHAIR,
    ROLE_COMMITTEE_MEMBER,
    ROLE_SURVEILLANCE_OFFICER,
)

# ─── Pagination (PRD section 2.3) ───────────────────────────────────────────

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0

# ─── Issuer vocabulary (PRD section 3.1) ────────────────────────────────────

ISSUER_TYPE_GENERAL_GOVERNMENT = "GENERAL_GOVERNMENT"
ISSUER_TYPE_SPECIAL_DISTRICT = "SPECIAL_DISTRICT"
ISSUER_TYPE_ENTERPRISE_PROVIDER = "ENTERPRISE_PROVIDER"
ISSUER_TYPES = (
    ISSUER_TYPE_GENERAL_GOVERNMENT,
    ISSUER_TYPE_SPECIAL_DISTRICT,
    ISSUER_TYPE_ENTERPRISE_PROVIDER,
)

# ─── Engagement vocabulary (PRD sections 3.1-3.4) ───────────────────────────

SOLICITATION_SOLICITED = "SOLICITED"
SOLICITATION_UNSOLICITED = "UNSOLICITED"
SOLICITATIONS = (SOLICITATION_SOLICITED, SOLICITATION_UNSOLICITED)

CREDIT_TYPE_GENERAL_OBLIGATION = "GENERAL_OBLIGATION"
CREDIT_TYPE_REVENUE = "REVENUE"
CREDIT_TYPE_ENTERPRISE = "ENTERPRISE"
CREDIT_TYPES = (
    CREDIT_TYPE_GENERAL_OBLIGATION,
    CREDIT_TYPE_REVENUE,
    CREDIT_TYPE_ENTERPRISE,
)

ENGAGEMENT_REQUESTED = "REQUESTED"
ENGAGEMENT_ENGAGED = "ENGAGED"
ENGAGEMENT_INFORMATION_GATHERING = "INFORMATION_GATHERING"
ENGAGEMENT_ANALYSIS = "ANALYSIS"
ENGAGEMENT_COMMITTEE_READY = "COMMITTEE_READY"
ENGAGEMENT_RATING_ASSIGNED = "RATING_ASSIGNED"
ENGAGEMENT_PUBLISHED = "PUBLISHED"
ENGAGEMENT_WITHDRAWN = "WITHDRAWN"
ENGAGEMENT_STATUSES = (
    ENGAGEMENT_REQUESTED,
    ENGAGEMENT_ENGAGED,
    ENGAGEMENT_INFORMATION_GATHERING,
    ENGAGEMENT_ANALYSIS,
    ENGAGEMENT_COMMITTEE_READY,
    ENGAGEMENT_RATING_ASSIGNED,
    ENGAGEMENT_PUBLISHED,
    ENGAGEMENT_WITHDRAWN,
)

# "4500000 cents for `GENERAL_OBLIGATION`, 5200000 cents for `REVENUE`, and
# 5800000 cents for `ENTERPRISE`"; "an unsolicited engagement carries a
# `fee_cents` of 0" (PRD section 3.1).
FEE_GO_CENTS = 4500000
FEE_REVENUE_CENTS = 5200000
FEE_ENTERPRISE_CENTS = 5800000
FEE_UNSOLICITED_CENTS = 0
FEE_BY_CREDIT_TYPE = {
    CREDIT_TYPE_GENERAL_OBLIGATION: FEE_GO_CENTS,
    CREDIT_TYPE_REVENUE: FEE_REVENUE_CENTS,
    CREDIT_TYPE_ENTERPRISE: FEE_ENTERPRISE_CENTS,
}

# "withdrawal refunds half the paid fee ... the withdrawal refund ratio of
# 0.5, rounded half-up to whole cents" (PRD section 3.1).
WITHDRAWAL_REFUND_RATIO = Decimal("0.5")

# ─── Documents (PRD sections 3.1 / 3.2) ─────────────────────────────────────

# "a fixed registry of twelve" document codes (PRD section 3.2).
DOC_AUDIT_FY = "AUDIT_FY"
DOC_ADOPTED_BUDGET = "ADOPTED_BUDGET"
DOC_TAX_BASE_REPORT = "TAX_BASE_REPORT"
DOC_DEBT_STATEMENT = "DEBT_STATEMENT"
DOC_RATE_COVENANT = "RATE_COVENANT"
DOC_FLOW_OF_FUNDS = "FLOW_OF_FUNDS"
DOC_ENGINEERING_REPORT = "ENGINEERING_REPORT"
DOC_MANAGEMENT_DISCUSSION = "MANAGEMENT_DISCUSSION"
DOC_CAPITAL_PLAN = "CAPITAL_PLAN"
DOC_PUBLIC_FILING_FY = "PUBLIC_FILING_FY"
DOC_PENSION_VALUATION = "PENSION_VALUATION"
DOC_EPA_LITIGATION_REPORT = "EPA_LITIGATION_REPORT"

DOCUMENT_REGISTRY = (
    DOC_AUDIT_FY,
    DOC_ADOPTED_BUDGET,
    DOC_TAX_BASE_REPORT,
    DOC_DEBT_STATEMENT,
    DOC_RATE_COVENANT,
    DOC_FLOW_OF_FUNDS,
    DOC_ENGINEERING_REPORT,
    DOC_MANAGEMENT_DISCUSSION,
    DOC_CAPITAL_PLAN,
    DOC_PUBLIC_FILING_FY,
    DOC_PENSION_VALUATION,
    DOC_EPA_LITIGATION_REPORT,
)

# "is exactly the single code `PUBLIC_FILING_FY` for an unsolicited one"
# (PRD section 3.1).
UNSOLICITED_REQUIRED_DOCUMENTS = (DOC_PUBLIC_FILING_FY,)

# ─── Scorecard (PRD section 3.2) ────────────────────────────────────────────

SCORE_MIN = 1
SCORE_MAX = 5

# "at least 4.50 anchors at `AAA`; at least 4.00 ... `AA`; at least 3.50
# ... `A`; at least 3.00 ... `BBB`; at least 2.50 ... `BB`; at least 2.00
# ... `B`; and anything below 2.00 ... `CCC`" (PRD section 3.2).
ANCHOR_THRESHOLD_AAA = Decimal("4.50")
ANCHOR_THRESHOLD_AA = Decimal("4.00")
ANCHOR_THRESHOLD_A = Decimal("3.50")
ANCHOR_THRESHOLD_BBB = Decimal("3.00")
ANCHOR_THRESHOLD_BB = Decimal("2.50")
ANCHOR_THRESHOLD_B = Decimal("2.00")

WEIGHTED_SCORE_DECIMAL_PLACES = 4

# Weak-link cap: "the lowest of the six factor scores is exactly 1, the
# indicative rating becomes the worse of `anchor_notch` and `BB`" (PRD 3.2).
WEAK_LINK_MIN_SCORE = 1
WEAK_LINK_CAP_NOTCH = "BB"

# ─── Notch scale and outlooks (PRD section 2.5) ─────────────────────────────

NOTCH_AAA = "AAA"
NOTCH_AA = "AA"
NOTCH_A = "A"
NOTCH_BBB = "BBB"
NOTCH_BB = "BB"
NOTCH_B = "B"
NOTCH_CCC = "CCC"

# "ordered from strongest to weakest" (PRD section 2.5); index 0 is best.
NOTCH_SCALE = (
    NOTCH_AAA,
    NOTCH_AA,
    NOTCH_A,
    NOTCH_BBB,
    NOTCH_BB,
    NOTCH_B,
    NOTCH_CCC,
)

OUTLOOK_POSITIVE = "POSITIVE"
OUTLOOK_STABLE = "STABLE"
OUTLOOK_NEGATIVE = "NEGATIVE"
OUTLOOK_DEVELOPING = "DEVELOPING"
OUTLOOKS = (
    OUTLOOK_POSITIVE,
    OUTLOOK_STABLE,
    OUTLOOK_NEGATIVE,
    OUTLOOK_DEVELOPING,
)

# ─── Committee (PRD section 3.3) ────────────────────────────────────────────

# "a `voter_ids` pool of exactly 5 distinct voter identifiers" (PRD 3.3).
COMMITTEE_SIZE = 5
# "Fewer than 3 cast votes is a failed quorum" (PRD 3.3).
QUORUM_MIN_VOTES = 3
# "at most one notch away from the scorecard's `indicative_notch`" (PRD 3.3).
NOTCH_DEVIATION_MAX = 1
# "a 24-hour cooling-off must separate sessions on the same engagement"
# (PRD 3.3).
SESSION_COOLING_OFF_HOURS = 24

SESSION_SCHEDULED = "SCHEDULED"
SESSION_IN_SESSION = "IN_SESSION"
SESSION_COMPLETED = "COMPLETED"
SESSION_ADJOURNED = "ADJOURNED"
SESSION_STATUSES = (
    SESSION_SCHEDULED,
    SESSION_IN_SESSION,
    SESSION_COMPLETED,
    SESSION_ADJOURNED,
)

ADJOURN_QUORUM_NOT_MET = "QUORUM_NOT_MET"
ADJOURN_NOTCH_DEVIATION_EXCEEDED = "NOTCH_DEVIATION_EXCEEDED"
ADJOURN_REASONS = (ADJOURN_QUORUM_NOT_MET, ADJOURN_NOTCH_DEVIATION_EXCEEDED)

VOTE_KIND_VOTE = "VOTE"
VOTE_KIND_RECUSAL = "RECUSAL"
VOTE_KINDS = (VOTE_KIND_VOTE, VOTE_KIND_RECUSAL)

# ─── Rating, surveillance posture, actions (PRD sections 3.4 / 3.5) ─────────

RATING_ASSIGNED = "ASSIGNED"
RATING_PUBLISHED = "PUBLISHED"
RATING_WITHDRAWN = "WITHDRAWN"
RATING_REMANDED = "REMANDED"
RATING_STATUSES = (
    RATING_ASSIGNED,
    RATING_PUBLISHED,
    RATING_WITHDRAWN,
    RATING_REMANDED,
)

POSTURE_CURRENT = "CURRENT"
POSTURE_GRACE = "GRACE"
POSTURE_DELINQUENT = "DELINQUENT"
POSTURES = (POSTURE_CURRENT, POSTURE_GRACE, POSTURE_DELINQUENT)

ACTION_AFFIRM = "AFFIRM"
ACTION_UPGRADE = "UPGRADE"
ACTION_DOWNGRADE = "DOWNGRADE"
ACTION_WITHDRAW = "WITHDRAW"
RATING_ACTIONS = (
    ACTION_AFFIRM,
    ACTION_UPGRADE,
    ACTION_DOWNGRADE,
    ACTION_WITHDRAW,
)

WITHDRAW_REASON_NON_DISCLOSURE = "NON_DISCLOSURE"
WITHDRAW_REASON_ISSUER_REQUEST = "ISSUER_REQUEST"
WITHDRAW_REASON_CRITERIA = "CRITERIA"
WITHDRAW_REASONS = (
    WITHDRAW_REASON_NON_DISCLOSURE,
    WITHDRAW_REASON_ISSUER_REQUEST,
    WITHDRAW_REASON_CRITERIA,
)
# "a `withdraw_reason` of `ISSUER_REQUEST` or `CRITERIA`" — NON_DISCLOSURE is
# "reserved to the sweep and never accepted here" (PRD section 3.5).
MANUAL_WITHDRAW_REASONS = (WITHDRAW_REASON_ISSUER_REQUEST, WITHDRAW_REASON_CRITERIA)

# "no later than 120 hours after `assigned_at`" (PRD section 3.4).
APPEAL_WINDOW_HOURS = 120
# "no later than 180 days after `withdrawn_at`" (PRD section 3.5).
REINSTATE_WINDOW_DAYS = 180

# ─── Appeals (PRD section 3.4) ──────────────────────────────────────────────

APPEAL_FILED = "FILED"
APPEAL_UPHELD = "UPHELD"
APPEAL_DENIED = "DENIED"
APPEAL_STATUSES = (APPEAL_FILED, APPEAL_UPHELD, APPEAL_DENIED)

DECISION_UPHELD = "UPHELD"
DECISION_DENIED = "DENIED"
APPEAL_DECISIONS = (DECISION_UPHELD, DECISION_DENIED)

# ─── Disclosure obligations (PRD section 3.5) ───────────────────────────────

# "Its `due_at` is 210 days after that `fiscal_year_end`" (PRD section 3.5).
DISCLOSURE_DUE_DAYS = 210
# "an `OVERDUE` obligation more than 30 days past its `due_at`" (PRD 3.5).
DELINQUENCY_GRACE_DAYS = 30
# "a `DELINQUENT` obligation more than 60 days past its `due_at`" (PRD 3.5).
NONDISCLOSURE_WITHDRAW_DAYS = 60

OBLIGATION_PENDING = "PENDING"
OBLIGATION_OVERDUE = "OVERDUE"
OBLIGATION_DELINQUENT = "DELINQUENT"
OBLIGATION_DEFAULTED = "DEFAULTED"
OBLIGATION_SUBMITTED_ON_TIME = "SUBMITTED_ON_TIME"
OBLIGATION_SUBMITTED_LATE = "SUBMITTED_LATE"
OBLIGATION_STATUSES = (
    OBLIGATION_PENDING,
    OBLIGATION_OVERDUE,
    OBLIGATION_DELINQUENT,
    OBLIGATION_DEFAULTED,
    OBLIGATION_SUBMITTED_ON_TIME,
    OBLIGATION_SUBMITTED_LATE,
)
# Open states, per the reinstatement rule: "each in `SUBMITTED_ON_TIME` or
# `SUBMITTED_LATE`" must hold, so these four block reinstatement (PRD 3.5).
OBLIGATION_OPEN_STATUSES = (
    OBLIGATION_PENDING,
    OBLIGATION_OVERDUE,
    OBLIGATION_DELINQUENT,
    OBLIGATION_DEFAULTED,
)

# ─── Criteria versions and portfolio reviews (PRD section 3.6) ──────────────

CRITERIA_DRAFT = "DRAFT"
CRITERIA_ACTIVE = "ACTIVE"
CRITERIA_SUPERSEDED = "SUPERSEDED"
CRITERIA_STATUSES = (CRITERIA_DRAFT, CRITERIA_ACTIVE, CRITERIA_SUPERSEDED)

# "the six factor weights ... must sum to exactly 1.000" (PRD section 3.6).
WEIGHT_SUM_REQUIRED = Decimal("1.000")

# "whose `due_at` is 90 days after that version's `activated_at`" (PRD 3.6).
REVIEW_COMPLETION_DAYS = 90

REVIEW_PENDING = "PENDING"
REVIEW_IN_REVIEW = "IN_REVIEW"
REVIEW_ESCALATED = "ESCALATED"
REVIEW_COMPLETED_NO_ACTION = "COMPLETED_NO_ACTION"
REVIEW_COMPLETED_RATING_ACTION = "COMPLETED_RATING_ACTION"
REVIEW_ITEM_STATUSES = (
    REVIEW_PENDING,
    REVIEW_IN_REVIEW,
    REVIEW_ESCALATED,
    REVIEW_COMPLETED_NO_ACTION,
    REVIEW_COMPLETED_RATING_ACTION,
)
# "true while any of its items remains `PENDING`, `IN_REVIEW`, or
# `ESCALATED`" (PRD section 3.6).
REVIEW_OPEN_STATUSES = (REVIEW_PENDING, REVIEW_IN_REVIEW, REVIEW_ESCALATED)

REVIEW_OUTCOME_NO_ACTION = "NO_ACTION"
REVIEW_OUTCOME_RATING_ACTION = "RATING_ACTION"
REVIEW_OUTCOMES = (REVIEW_OUTCOME_NO_ACTION, REVIEW_OUTCOME_RATING_ACTION)

# ─── Bond sales (PRD section 3.7) ───────────────────────────────────────────

PRICING_MODE_PROVISIONAL = "PROVISIONAL"
PRICING_MODE_FINAL = "FINAL"
PRICING_MODES = (PRICING_MODE_PROVISIONAL, PRICING_MODE_FINAL)

# "a benchmark of 300 basis points" (PRD section 3.7).
BENCHMARK_YIELD_BPS = 300

# "25 basis points for `AAA`, 45 for `AA`, 90 for `A`, 150 for `BBB`, 325
# for `BB`, 600 for `B`, and 900 for `CCC`" (PRD section 3.7).
SPREAD_BPS = {
    NOTCH_AAA: 25,
    NOTCH_AA: 45,
    NOTCH_A: 90,
    NOTCH_BBB: 150,
    NOTCH_BB: 325,
    NOTCH_B: 600,
    NOTCH_CCC: 900,
}

# "multiplied by the effective yield in basis points and divided by 10000"
# (PRD section 3.7).
BPS_DENOMINATOR = 10000

# "a `par_amount_cents` that must be greater than zero, a `maturity_years`
# from 1 to 30" (PRD section 3.7).
PAR_AMOUNT_MIN_CENTS = 1
MATURITY_MIN_YEARS = 1
MATURITY_MAX_YEARS = 30

# ─── Notch history causes (PRD sections 3.3 / 3.5 / 3.6) ────────────────────

CAUSE_COMMITTEE_ASSIGNMENT = "COMMITTEE_ASSIGNMENT"
CAUSE_SURVEILLANCE_ACTION = "SURVEILLANCE_ACTION"
CAUSE_CRITERIA_REVIEW = "CRITERIA_REVIEW"
CAUSE_REINSTATEMENT = "REINSTATEMENT"
NOTCH_HISTORY_CAUSES = (
    CAUSE_COMMITTEE_ASSIGNMENT,
    CAUSE_SURVEILLANCE_ACTION,
    CAUSE_CRITERIA_REVIEW,
    CAUSE_REINSTATEMENT,
)

# ─── Issuer notification event types (PRD section 2.11) ─────────────────────

EVENT_ENGAGEMENT_WITHDRAWN = "ENGAGEMENT_WITHDRAWN"
EVENT_RATING_ASSIGNED = "RATING_ASSIGNED"
EVENT_RATING_PUBLISHED = "RATING_PUBLISHED"
EVENT_RATING_ACTION = "RATING_ACTION"
EVENT_RATING_WITHDRAWN = "RATING_WITHDRAWN"
EVENT_RATING_REINSTATED = "RATING_REINSTATED"
EVENT_APPEAL_UPHELD = "APPEAL_UPHELD"
EVENT_APPEAL_DENIED = "APPEAL_DENIED"
EVENT_OBLIGATION_DELINQUENT = "OBLIGATION_DELINQUENT"
EVENT_REVIEW_OPENED = "REVIEW_OPENED"
EVENT_REVIEW_COMPLETED = "REVIEW_COMPLETED"

NOTIFICATION_EVENT_TYPES = (
    EVENT_ENGAGEMENT_WITHDRAWN,
    EVENT_RATING_ASSIGNED,
    EVENT_RATING_PUBLISHED,
    EVENT_RATING_ACTION,
    EVENT_RATING_WITHDRAWN,
    EVENT_RATING_REINSTATED,
    EVENT_APPEAL_UPHELD,
    EVENT_APPEAL_DENIED,
    EVENT_OBLIGATION_DELINQUENT,
    EVENT_REVIEW_OPENED,
    EVENT_REVIEW_COMPLETED,
)
