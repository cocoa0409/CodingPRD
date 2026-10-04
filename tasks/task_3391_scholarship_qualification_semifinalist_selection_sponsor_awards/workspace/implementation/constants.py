"""Named constants for the Merit Scholarship Awards API.

Every numeric threshold, weight, interval, and default referenced anywhere in
the implementation is defined exactly once, here. Values are taken verbatim
from PRD.md / SCAFFOLD.yaml.
"""

# Logical clock startup default (PRD section 2.5): exactly this instant.
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# Selection index calculation (calculation: selection_index).
SECTION_WEIGHT = 2
SECTION_MIN = 8
SECTION_MAX = 38

# Apportionment (calculation: state_slot_allocation).
MIN_STATE_SLOTS = 1
QUOTA_DECIMALS = 4  # quota_raw stored to 4 decimal places, round-half-up

# Disbursement schedule (calculation: disbursement_schedule).
TERM_INTERVAL_DAYS = 180

# Award offers (PRD section 3.8).
ACCEPTANCE_WINDOW_DAYS = 30

# Notifications (PRD section 3.9).
PUBLICITY_GAP_DAYS = 2

# Renewal verification (PRD section 3.8).
RENEWAL_MIN_GPA = 2.5
GPA_MIN = 0.0
GPA_MAX = 4.0

# Confirming examination selection index bounds (entity constraints).
CONFIRMING_MIN = 48
CONFIRMING_MAX = 228

# Pagination (response_envelope.pagination_defaults).
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0

# RBAC roles, spelled exactly as declared (PRD section 2.1).
ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_SCHOOL_OFFICIAL = "SchoolOfficial"
ROLE_STUDENT = "Student"
ROLE_SPONSOR_ADMIN = "SponsorAdmin"
ROLE_COLLEGE_ADMIN = "CollegeAdmin"
ALL_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_SCHOOL_OFFICIAL,
    ROLE_STUDENT,
    ROLE_SPONSOR_ADMIN,
    ROLE_COLLEGE_ADMIN,
)

# Notification sequencing (PRD section 3.9).
NOTIFICATION_SEQUENCE = {
    "SEMIFINALIST_NOTICE": 1,
    "FINALIST_NOTICE": 2,
    "AWARD_OFFER": 3,
    "PUBLIC_ANNOUNCEMENT": 4,
}
# Cycle field whose value supplies each notice type's embargo instant.
NOTIFICATION_EMBARGO_FIELD = {
    "SEMIFINALIST_NOTICE": "semifinalist_embargo_until",
    "FINALIST_NOTICE": "finalist_embargo_until",
    "AWARD_OFFER": "award_embargo_until",
    "PUBLIC_ANNOUNCEMENT": "public_embargo_until",
}

# Award recipient states counted as "live" for pool accounting and the
# cycle-completion bubble-up (calculation: sponsor_pool_availability).
LIVE_RECIPIENT_STATES = ("OFFERED", "ACCEPTED", "ENROLLED", "RENEWED")

# Enumerations (entity field constraints).
CITIZENSHIP_STATUSES = ("US_CITIZEN", "US_NATIONAL", "LAWFUL_PERMANENT_RESIDENT", "OTHER")
ENROLLMENT_STATUSES = ("ENROLLED_FULL_TIME", "ENROLLED_PART_TIME", "NOT_ENROLLED")
EXAM_YEARS = ("SECOND_YEAR", "THIRD_YEAR")
COURSE_RIGORS = ("STANDARD", "ADVANCED", "MOST_RIGOROUS")
REPORTED_ENROLLMENTS = ("FULL_TIME", "HALF_TIME", "NOT_ENROLLED")
REVIEW_DECISIONS = ("CONFIRM", "RETURN", "DENY")
RENEWAL_DECISIONS = ("APPROVE", "REJECT")
AWARD_CATEGORIES = ("NATIONAL_SINGLE", "CORPORATE_SPONSORED", "COLLEGE_SPONSORED")
NOTICE_TYPES = ("SEMIFINALIST_NOTICE", "FINALIST_NOTICE", "AWARD_OFFER", "PUBLIC_ANNOUNCEMENT")
