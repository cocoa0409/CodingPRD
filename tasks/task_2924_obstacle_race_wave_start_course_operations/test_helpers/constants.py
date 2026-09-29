"""Domain vocabulary and the numeric constants the PRD pins by name.

One symbol per concept. Every enum member below is spelled exactly as the PRD
spells it, and every test file imports the constant rather than repeating the
literal, so a rename can never leave a minority spelling behind.
"""

# ─── Roles (PRD §2.1: exactly seven declared roles) ──────────────────────

ROLE_PERMIT_OFFICER = "PermitOfficer"
ROLE_COURSE_DESIGNER = "CourseDesigner"
ROLE_RACE_DIRECTOR = "RaceDirector"
ROLE_SAFETY_OFFICER = "SafetyOfficer"
ROLE_SITE_OPS_LEAD = "SiteOpsLead"
ROLE_OBSTACLE_MARSHAL = "ObstacleMarshal"
ROLE_PARTICIPANT = "Participant"

ALL_ROLES = [
    ROLE_PERMIT_OFFICER,
    ROLE_COURSE_DESIGNER,
    ROLE_RACE_DIRECTOR,
    ROLE_SAFETY_OFFICER,
    ROLE_SITE_OPS_LEAD,
    ROLE_OBSTACLE_MARSHAL,
    ROLE_PARTICIPANT,
]

UNDECLARED_ROLE = "CourseSweeper"

# ─── Venue (PRD §3.1) ───────────────────────────────────────────────────

TERRAIN_FIELD = "FIELD"
TERRAIN_FOREST = "FOREST"
TERRAIN_QUARRY = "QUARRY"
TERRAIN_SKI_SLOPE = "SKI_SLOPE"

WATER_ACCESS_NONE = "NONE"
WATER_ACCESS_POND = "POND"
WATER_ACCESS_RIVER = "RIVER"

SITE_POSTURE_OPEN = "OPEN"
SITE_POSTURE_FROZEN = "FROZEN"
SITE_POSTURE_CLOSED_OUT = "CLOSED_OUT"

# ─── LandUsePermit (PRD §3.1) ───────────────────────────────────────────

PERMIT_DRAFT = "DRAFT"
PERMIT_SUBMITTED = "SUBMITTED"
PERMIT_REVISION_REQUESTED = "REVISION_REQUESTED"
PERMIT_APPROVED = "APPROVED"
PERMIT_DENIED = "DENIED"
PERMIT_EXPIRED = "EXPIRED"

DECISION_APPROVED = "APPROVED"
DECISION_REVISION_REQUESTED = "REVISION_REQUESTED"
DECISION_DENIED = "DENIED"

# ─── Course (PRD §3.2) ──────────────────────────────────────────────────

COURSE_DRAFT = "DRAFT"
COURSE_VALIDATED = "VALIDATED"
COURSE_PUBLISHED = "PUBLISHED"
COURSE_SUSPENDED = "SUSPENDED"
COURSE_COMPLETED = "COMPLETED"

READINESS_OPEN = "OPEN"
READINESS_RESTRICTED = "RESTRICTED"
READINESS_FROZEN = "FROZEN"

# ─── Obstacle (PRD §3.2, §3.3) ──────────────────────────────────────────

BYPASS_MODE_NONE = "NONE"
BYPASS_MODE_PENALTY_LOOP = "PENALTY_LOOP"
BYPASS_MODE_TIMED_PENALTY = "TIMED_PENALTY"
BYPASS_MODE_MANDATORY = "MANDATORY"

STAFFING_UNSTAFFED = "UNSTAFFED"
STAFFING_PARTIAL = "PARTIAL"
STAFFING_MARSHALED = "MARSHALED"

# ─── StaffAssignment (PRD §3.3) ─────────────────────────────────────────

STAFF_ROLE_MARSHAL = "MARSHAL"
STAFF_ROLE_MEDIC = "MEDIC"
STAFF_ROLE_WATER_SAFETY = "WATER_SAFETY"
STAFF_ROLE_SWEEP = "SWEEP"

CERT_BASIC = "BASIC"
CERT_ADVANCED = "ADVANCED"
CERT_PARAMEDIC = "PARAMEDIC"
CERT_LIFEGUARD = "LIFEGUARD"

ASSIGNMENT_CONFIRMED = "CONFIRMED"
ASSIGNMENT_VACATED = "VACATED"

# ─── Division (PRD §3.4) ────────────────────────────────────────────────

DIVISION_COMPETITIVE = "COMPETITIVE"
DIVISION_OPEN = "OPEN"
DIVISION_TEAM = "TEAM"

BYPASS_POLICY_ALLOWED_WITH_PENALTY = "ALLOWED_WITH_PENALTY"
BYPASS_POLICY_DQ_ON_BYPASS = "DQ_ON_BYPASS"
BYPASS_POLICY_MANDATORY_COMPLETION = "MANDATORY_COMPLETION"

SCORING_GUN_TIME = "GUN_TIME"
SCORING_CHIP_TIME = "CHIP_TIME"

# ─── Wave: two orthogonal dimensions (PRD §3.6) ─────────────────────────

RELEASE_SCHEDULED = "SCHEDULED"
RELEASE_HELD = "HELD"
RELEASE_RELEASED = "RELEASED"
RELEASE_STARTED = "STARTED"
RELEASE_CLOSED = "CLOSED"

ROSTER_OPEN = "OPEN"
ROSTER_LOCKED = "LOCKED"
ROSTER_SEALED = "SEALED"

HOLD_REASON_VENUE_FROZEN = "VENUE_FROZEN"
HOLD_REASON_COURSE_RESTRICTED = "COURSE_RESTRICTED"

# ─── Participant (PRD §3.5) ─────────────────────────────────────────────

CLEARANCE_PENDING = "PENDING"
CLEARANCE_CLEARED = "CLEARED"
CLEARANCE_MEDICALLY_HELD = "MEDICALLY_HELD"

MEDICAL_FLAG_CARDIAC = "CARDIAC"
MEDICAL_FLAG_PREGNANCY = "PREGNANCY"
MEDICAL_FLAG_RECENT_SURGERY = "RECENT_SURGERY"
MEDICAL_FLAG_ASTHMA = "ASTHMA"

BLOCKING_MEDICAL_FLAGS = [
    MEDICAL_FLAG_CARDIAC,
    MEDICAL_FLAG_PREGNANCY,
    MEDICAL_FLAG_RECENT_SURGERY,
]

# ─── Entry: two orthogonal dimensions (PRD §3.5–§3.8) ───────────────────

PROGRESS_REGISTERED = "REGISTERED"
PROGRESS_CHECKED_IN = "CHECKED_IN"
PROGRESS_STARTED = "STARTED"
PROGRESS_FINISHED = "FINISHED"
PROGRESS_DNS = "DNS"
PROGRESS_DNF = "DNF"

RESULT_PENDING = "PENDING"
RESULT_PROVISIONAL = "PROVISIONAL"
RESULT_UNDER_PROTEST = "UNDER_PROTEST"
RESULT_OFFICIAL = "OFFICIAL"
RESULT_DISQUALIFIED = "DISQUALIFIED"
RESULT_NOT_CLASSIFIED = "NOT_CLASSIFIED"

DQ_REASON_BYPASS_IN_DQ_DIVISION = "BYPASS_IN_DQ_DIVISION"
DQ_REASON_ADJUDICATED_DQ = "ADJUDICATED_DQ"

# ─── ObstacleAttempt (PRD §3.7) ─────────────────────────────────────────

OUTCOME_COMPLETED = "COMPLETED"
OUTCOME_BYPASSED = "BYPASSED"
OUTCOME_FAILED_PENALTY = "FAILED_PENALTY"
OUTCOME_SKIPPED_UNMARSHALED = "SKIPPED_UNMARSHALED"

# ─── Adjudication rulings (PRD §3.8) ────────────────────────────────────

RULING_UPHELD_ADJUSTED = "UPHELD_ADJUSTED"
RULING_DENIED_OFFICIAL = "DENIED_OFFICIAL"
RULING_DISQUALIFIED = "DISQUALIFIED"

# ─── FestivalService (PRD §3.9) ─────────────────────────────────────────

SERVICE_BAG_CHECK = "BAG_CHECK"
SERVICE_RINSE_STATION = "RINSE_STATION"
SERVICE_SPECTATOR_ZONE = "SPECTATOR_ZONE"

SERVICE_OPEN = "OPEN"
SERVICE_CLOSED = "CLOSED"

# ─── RestorationTask (PRD §3.9) ─────────────────────────────────────────

TASK_TYPE_RESEED = "RESEED"
TASK_TYPE_DECOMPACT = "DECOMPACT"
TASK_TYPE_SILT_REMOVAL = "SILT_REMOVAL"
TASK_TYPE_DEBRIS_SWEEP = "DEBRIS_SWEEP"

TASK_PENDING = "PENDING"
TASK_VERIFIED = "VERIFIED"
TASK_REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"

INSPECTION_VERIFIED = "VERIFIED"
INSPECTION_REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"

SETTLEMENT_PROGRESSIVE = "PROGRESSIVE"
SETTLEMENT_FINAL = "FINAL"

# ─── Numeric constants the PRD pins by name ─────────────────────────────

#: PRD §3.3 "shift intervals are compared after being inflated by a travel
#: buffer of 15 minutes on both sides".
STAFF_TRAVEL_BUFFER_MINUTES = 15

#: PRD §3.4 "Each heat occupies the corral for a half-open window of 6 minutes".
CORRAL_OCCUPANCY_MINUTES = 6

#: PRD §3.3/§3.6 "divided by 250 participants per medic".
PARTICIPANTS_PER_MEDIC = 250

#: PRD §3.3 "2 swimmers for each obstacle on the course whose `water_contact` is true".
WATER_SAFETY_PER_WET_OBSTACLE = 2

#: PRD §3.3 "the logical clock advanced by the 45-minute holdback window".
HOLDBACK_WINDOW_MINUTES = 45

#: PRD §3.4/§3.6 "Heats are planned on a 15-minute grid".
WAVE_GRID_MINUTES = 15

#: PRD §3.2/§3.3 the design and effective relief cap.
RELIEF_CAP_PER_MIN = 8.00

#: PRD §3.3 the two non-unit staffing factors.
STAFFING_FACTOR_FULL = 1.00
STAFFING_FACTOR_PARTIAL = 0.60
STAFFING_FACTOR_NONE = 0.00

#: PRD §3.2 "Its `difficulty_progression_score`, as rounded, must be at least 0.50".
MIN_PROGRESSION_SCORE = 0.50

#: PRD §3.2 "at least 3 primary obstacles".
MIN_PRIMARY_OBSTACLES = 3

#: PRD §3.2 "A drop of exactly 2 is a permitted breather; a drop of 3 is a regression."
MAX_PERMITTED_DROP = 2

#: PRD §3.9 "The late penalty is 25,000 cents (250 currency units) for each late day".
LATE_PENALTY_CENTS_PER_DAY = 25000

#: PRD §3.8 "The entry's `protest_rounds` must be strictly fewer than 2".
MAX_PROTEST_ROUNDS = 2

#: PRD §2.3 pagination defaults and bounds.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

#: PRD §2.5 "Before the clock has ever been set, it reads exactly
#: `2026-08-01T00:00:00Z`".
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ─── Operator identifiers (PRD §2.1: opaque for the six operator roles) ──

USER_OFFICER_1 = "officer-1"
USER_OFFICER_2 = "officer-2"
USER_DESIGNER_1 = "designer-1"
USER_DESIGNER_2 = "designer-2"
USER_DIRECTOR_1 = "director-1"
USER_DIRECTOR_2 = "director-2"
USER_SAFETY_1 = "safety-1"
USER_SAFETY_2 = "safety-2"
USER_OPS_1 = "ops-1"
USER_OPS_2 = "ops-2"
USER_MARSHAL_1 = "marshal-1"
USER_MARSHAL_2 = "marshal-2"
USER_MARSHAL_7 = "marshal-7"

#: An identifier that wears two hats: it files the permit as a CourseDesigner
#: and then tries to rule on it as a PermitOfficer (PRD §2.7).
USER_DUAL_HAT = "dual-hat-1"

# ─── Rostered humans (PRD §3.3 `staff_person_id`) ────────────────────────

STAFF_PERSON_1 = "person-1"
STAFF_PERSON_2 = "person-2"
STAFF_PERSON_3 = "person-3"
STAFF_PERSON_4 = "person-4"
STAFF_PERSON_5 = "person-5"
STAFF_MEDIC_1 = "medic-1"
STAFF_MEDIC_2 = "medic-2"
STAFF_SWIMMER_1 = "swimmer-1"
STAFF_SWIMMER_2 = "swimmer-2"
STAFF_SWEEP_1 = "sweep-1"
