# Shared constants for the actuarial progression API.
# Every value here is pinned by PRD.md / SCAFFOLD.yaml.

CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# Roles (PRD §2.1)
ROLES = [
    "Anonymous",
    "Candidate",
    "Registrar",
    "ExamCommittee",
    "AcademicReviewer",
    "Grader",
    "DisciplineBoard",
]

# Scoring (PRD §3.3)
MAX_RAW_SCORE = 60

# Fees (PRD §3.3, calculations.registration_fee_cents / refund_cents)
LATE_FEE_WINDOW_DAYS = 14
PROCESSING_RATE = "0.015"   # Decimal string, 1.5%
LATE_REFUND_RATIO = "0.5"   # Decimal string, 50%

# VEE (PRD §3.4)
VEE_GRADE_MIN = 2.7
VEE_TOPICS = ["ECONOMICS", "CORPORATE_FINANCE", "APPLIED_STATISTICS"]

# Tracks / modules (PRD §3.5)
TRACK_CODES = ["QFI", "ILA", "CFE", "RET", "GH"]
NONCAPSTONE_WEIGHT = 2
CAPSTONE_WEIGHT = 3
PROJECT_WEIGHT = 2
DEFAULT_COOLDOWN_DAYS = 14

# Projects (PRD §3.6, calculations.consensus_grade)
CONSENSUS_TOLERANCE = 10
PROJECT_PASS_SCORE = 70

# CPD (PRD §3.8, calculations.cpd_required_hours)
CPD_BASE_HOURS = 30
CPD_CARRYOVER_CAP = 10

# Transfer credit (PRD §3.8, calculations.transfer_equivalency)
BILATERAL_CAP = 30
NON_BILATERAL_CAP = 15
NON_BILATERAL_RATIO = "0.5"  # Decimal string
SOURCE_BODIES = ["IFOA", "CIA", "IAA", "CAS", "OTHER"]
BILATERAL_BODIES = ["IFOA", "CIA"]
NON_BILATERAL_BODIES = ["IAA", "CAS"]

# Credential evaluation (PRD §3.9, calculations.credential_evaluation)
ASA_MIN_TOTAL_CREDITS = 10
ASA_TRANSFER_CREDIT_CAP = 15
CREDENTIALS = ["ASA", "FSA"]
DEFICIENCY_ORDER = [
    "MISSING_PRELIM_CREDIT",
    "MISSING_VEE_TOPIC",
    "INSUFFICIENT_TOTAL_CREDITS",
    "MISSING_ASA",
    "TRACK_INCOMPLETE",
    "MISSING_PROJECT_PASS",
    "MISSING_PROFESSIONALISM",
]

# Discipline resolutions
RESOLUTIONS = ["DISMISSED", "REPRIMAND", "SUSPENSION", "EXPULSION"]

# Course attendance outcomes
ATTENDANCE_OUTCOMES = ["ATTENDED", "NO_SHOW"]

# VEE review decisions
VEE_DECISIONS = ["APPROVE", "REJECT"]
