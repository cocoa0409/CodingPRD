"""Literal vocabulary of the CTE Program of Study & Federal Reporting API.

Every role name, enum member, error identifier, tuned constant and URL path used
by the test suite is defined here exactly once and imported everywhere else, so
that no test ever spells a protocol symbol inline.
"""

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_CTE_DIRECTOR = "CteDirector"
ROLE_STATE_COMPLIANCE_REVIEWER = "StateComplianceReviewer"
ROLE_GRANT_FISCAL_OFFICER = "GrantFiscalOfficer"
ROLE_COMMITTEE_CHAIR = "CommitteeChair"
ROLE_SCHOOL_REGISTRAR = "SchoolRegistrar"

ALL_ROLES = (
    ROLE_CTE_DIRECTOR,
    ROLE_STATE_COMPLIANCE_REVIEWER,
    ROLE_GRANT_FISCAL_OFFICER,
    ROLE_COMMITTEE_CHAIR,
    ROLE_SCHOOL_REGISTRAR,
)

# A role string deliberately outside the five the system recognises.
ROLE_NOT_IN_CATALOGUE = "DistrictSuperintendent"

# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# ---------------------------------------------------------------------------
# ProgramOfStudy (PRD 3.1, 2.8)
# ---------------------------------------------------------------------------
CLUSTER_HEALTH_SCIENCE = "HEALTH_SCIENCE"
CLUSTER_ADVANCED_MANUFACTURING = "ADVANCED_MANUFACTURING"
CLUSTER_INFORMATION_TECHNOLOGY = "INFORMATION_TECHNOLOGY"
CLUSTER_CONSTRUCTION = "CONSTRUCTION"
CLUSTER_AGRICULTURE = "AGRICULTURE"

APPROVAL_DRAFT = "DRAFT"
APPROVAL_SUBMITTED = "SUBMITTED"
APPROVAL_COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
APPROVAL_CHANGES_REQUESTED = "CHANGES_REQUESTED"
APPROVAL_STATE_APPROVED = "STATE_APPROVED"
APPROVAL_SUSPENDED = "SUSPENDED"

CLNA_NOT_STARTED = "NOT_STARTED"
CLNA_DATA_COLLECTION = "DATA_COLLECTION"
CLNA_STAKEHOLDER_CONSULTATION = "STAKEHOLDER_CONSULTATION"
CLNA_GAP_ANALYSIS = "GAP_ANALYSIS"
CLNA_CERTIFIED = "CERTIFIED"
CLNA_EXPIRED = "EXPIRED"

# Program-level finding codes the sanction cascades append (PRD 3.8, 3.9)
FINDING_PERF_SUSPENSION = "PERF_SUSPENSION"
FINDING_PERF_SANCTION = "PERF_SANCTION"
FINDING_PERF_IMPROVEMENT_ACCEPTED = "PERF_IMPROVEMENT_ACCEPTED"

# ---------------------------------------------------------------------------
# SequenceCourse (PRD 3.1)
# ---------------------------------------------------------------------------
SEGMENT_SECONDARY = "SECONDARY"
SEGMENT_POSTSECONDARY = "POSTSECONDARY"

COURSE_DRAFT = "DRAFT"
COURSE_ACTIVE = "ACTIVE"
COURSE_RETIRED = "RETIRED"

ALIGNMENT_VARIANT_PROVISIONAL_LOCAL = "PROVISIONAL_LOCAL"
ALIGNMENT_VARIANT_FEDERAL_CERTIFIED = "FEDERAL_CERTIFIED"

# ---------------------------------------------------------------------------
# Credential and CredentialAttainment (PRD 3.1, 3.6)
# ---------------------------------------------------------------------------
TIER_STATE_RECOGNIZED = "STATE_RECOGNIZED"
TIER_NATIONAL = "NATIONAL"
TIER_LOCAL = "LOCAL"

VERIFICATION_SELF_REPORTED = "SELF_REPORTED"
VERIFICATION_VERIFIED = "VERIFIED"

# ---------------------------------------------------------------------------
# Student (PRD 3.6)
# ---------------------------------------------------------------------------
CONCENTRATOR_PARTICIPANT = "PARTICIPANT"
CONCENTRATOR_CONCENTRATOR = "CONCENTRATOR"
CONCENTRATOR_COMPLETER = "COMPLETER"

EXIT_GRADUATED = "GRADUATED"
EXIT_TRANSFERRED = "TRANSFERRED"
EXIT_WITHDREW = "WITHDREW"

POP_ECON_DISADV = "ECON_DISADV"
POP_IEP = "IEP"
POP_EL = "EL"
POP_SINGLE_PARENT = "SINGLE_PARENT"
POP_NONTRADITIONAL = "NONTRADITIONAL"

# ---------------------------------------------------------------------------
# AdvisoryCommittee, CommitteeMember, CommitteeMeeting (PRD 3.3)
# ---------------------------------------------------------------------------
SECTOR_EMPLOYER = "EMPLOYER"
SECTOR_POSTSECONDARY = "POSTSECONDARY"
SECTOR_LABOR = "LABOR"
SECTOR_PARENT = "PARENT"
SECTOR_STUDENT = "STUDENT"

COMMITTEE_FORMING = "FORMING"
COMMITTEE_ACTIVE = "ACTIVE"
COMMITTEE_DISSOLVED = "DISSOLVED"

MEMBER_ACTIVE = "ACTIVE"
MEMBER_EXPIRED = "EXPIRED"

AGENDA_CLNA_STAKEHOLDER = "CLNA_STAKEHOLDER"
AGENDA_POS_ENDORSEMENT = "POS_ENDORSEMENT"
AGENDA_EQUIPMENT_REVIEW = "EQUIPMENT_REVIEW"

MINUTES_SCHEDULED = "SCHEDULED"
MINUTES_FINALIZED = "FINALIZED"
MINUTES_AMENDED = "AMENDED"

# ---------------------------------------------------------------------------
# GrantAward and Expenditure (PRD 3.7)
# ---------------------------------------------------------------------------
GRANT_OPEN = "OPEN"
GRANT_CLOSED = "CLOSED"

CATEGORY_EQUIPMENT = "EQUIPMENT"
CATEGORY_CONSUMABLE = "CONSUMABLE"
CATEGORY_PROFESSIONAL_DEVELOPMENT = "PROFESSIONAL_DEVELOPMENT"
CATEGORY_ADMINISTRATION = "ADMINISTRATION"
CATEGORY_ENTERTAINMENT = "ENTERTAINMENT"

EXP_REQUESTED = "REQUESTED"
EXP_CERTIFIED = "CERTIFIED"
EXP_OBLIGATED = "OBLIGATED"
EXP_DISALLOWED = "DISALLOWED"
EXP_VOIDED = "VOIDED"
EXP_BLOCKED = "BLOCKED"

DECISION_CERTIFY = "CERTIFY"
DECISION_DISALLOW = "DISALLOW"

FINDING_ENTERTAINMENT_PROHIBITED = "ENTERTAINMENT_PROHIBITED"
FINDING_ADMIN_CAP = "ADMIN_CAP"
FINDING_NO_CAPITAL_REVIEW = "NO_CAPITAL_REVIEW"
FINDING_OUTSIDE_WINDOW = "OUTSIDE_WINDOW"
FINDING_OTHER = "OTHER"

# Federal share per category, four decimal places (PRD 3.7)
FEDERAL_SHARE_BY_CATEGORY = {
    CATEGORY_PROFESSIONAL_DEVELOPMENT: 1.0,
    CATEGORY_EQUIPMENT: 0.85,
    CATEGORY_CONSUMABLE: 0.85,
    CATEGORY_ADMINISTRATION: 0.85,
    CATEGORY_ENTERTAINMENT: 0.0,
}

# Indirect-rate tiers keyed only on the direct obligated total (PRD 3.7)
INDIRECT_TIER_LOW_BOUND_CENTS = 5000000
INDIRECT_TIER_MID_BOUND_CENTS = 20000000
INDIRECT_RATE_LOW = 0.0812
INDIRECT_RATE_MID = 0.065
INDIRECT_RATE_HIGH = 0.05

ADMIN_CAP_FRACTION = 0.05
CAPITAL_THRESHOLD_CENTS = 500000
CAPITAL_REVIEW_LOOKBACK_DAYS = 365
ASSET_BUFFER_DAYS = 14

# ---------------------------------------------------------------------------
# PerformanceIndicator and ImprovementPlan (PRD 3.8, 3.9)
# ---------------------------------------------------------------------------
INDICATOR_1S1_GRAD_RATE = "1S1_GRAD_RATE"
INDICATOR_2S1_ACADEMIC = "2S1_ACADEMIC"
INDICATOR_3S1_POST_PROGRAM = "3S1_POST_PROGRAM"
INDICATOR_4S1_CREDENTIAL = "4S1_CREDENTIAL"
INDICATOR_5S3_WORK_BASED = "5S3_WORK_BASED"

PI_PROPOSED = "PROPOSED"
PI_NEGOTIATING = "NEGOTIATING"
PI_AGREED = "AGREED"
PI_ARBITRATED = "ARBITRATED"
PI_MET = "MET"
PI_NOT_MET = "NOT_MET"
PI_NOT_SCORED = "NOT_SCORED"
PI_IMPROVEMENT_REQUIRED = "IMPROVEMENT_REQUIRED"
PI_MONITORING = "MONITORING"
PI_SANCTIONED = "SANCTIONED"

PROJECTION_MET = "MET"
PROJECTION_NOT_MET = "NOT_MET"
PROJECTION_UNDEFINED = "UNDEFINED"

PLAN_DRAFT = "DRAFT"
PLAN_SUBMITTED = "SUBMITTED"
PLAN_RETURNED = "RETURNED"
PLAN_ACCEPTED = "ACCEPTED"
PLAN_REJECTED_FINAL = "REJECTED_FINAL"

MAX_NEGOTIATION_ROUNDS = 4
PERFORMANCE_TOLERANCE = 0.90
SMALL_COHORT_MIN = 5
MISS_TOLERANCE = 2
MIN_PLAN_MILESTONES = 3
MAX_PLAN_REVISION_ROUNDS = 3

# ---------------------------------------------------------------------------
# Educator (PRD 3.5)
# ---------------------------------------------------------------------------
ROUTE_TRADITIONAL = "TRADITIONAL"
ROUTE_INDUSTRY_EXPERIENCE = "INDUSTRY_EXPERIENCE"
ROUTE_ALTERNATIVE = "ALTERNATIVE"

EDUCATOR_PROVISIONAL = "PROVISIONAL"
EDUCATOR_ELIGIBLE = "ELIGIBLE"
EDUCATOR_LAPSED = "LAPSED"

INDUSTRY_HOURS_MIN = 4000
ALTERNATIVE_HOURS_MIN = 2000
TRADITIONAL_HOURS_MIN = 0

SOURCE_EMPLOYER_LETTER = "EMPLOYER_LETTER"
SOURCE_PAYROLL_RECORD = "PAYROLL_RECORD"

# ---------------------------------------------------------------------------
# Alignment index tuning (PRD 3.1)
# ---------------------------------------------------------------------------
DEPTH_WEIGHT = 0.60
BRIDGE_WEIGHT = 0.30
BREADTH_BONUS = 0.10
EXPECTED_SECONDARY_CREDIT_HOURS = 4.0
ARTICULATION_FLOOR = 3.00
FEDERAL_ALIGNMENT_FLOOR = 0.7500
CONCENTRATOR_CREDIT_MIN = 2.0

# ---------------------------------------------------------------------------
# CLNA and labor-market tuning (PRD 3.2)
# ---------------------------------------------------------------------------
CLNA_VALIDITY_DAYS = 730
LABOR_MARKET_STALENESS_DAYS = 730
CLNA_STAKEHOLDER_MEETINGS_MIN = 2

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------
CLOCK_EPOCH_ISO = "2026-08-01T00:00:00Z"
CLOCK_EPOCH_DATE = "2026-08-01"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# ---------------------------------------------------------------------------
# URL paths
# ---------------------------------------------------------------------------
PROGRAMS = "/cte/programs-of-study"
SEQUENCE_COURSES = "/cte/sequence-courses"
CREDENTIALS = "/cte/credentials"
STUDENTS = "/cte/students"
CREDENTIAL_ATTAINMENTS = "/cte/credential-attainments"
ADVISORY_COMMITTEES = "/cte/advisory-committees"
COMMITTEE_MEMBERS = "/cte/committee-members"
COMMITTEE_MEETINGS = "/cte/committee-meetings"
GRANT_AWARDS = "/cte/grant-awards"
EXPENDITURES = "/cte/expenditures"
PERFORMANCE_INDICATORS = "/cte/performance-indicators"
IMPROVEMENT_PLANS = "/cte/improvement-plans"
EDUCATORS = "/cte/educators"
CLOCK_SET = "/_clock/set_current_utc"
