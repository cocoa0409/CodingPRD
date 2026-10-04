"""Domain thresholds — every value appears verbatim in PRD.md.

Generic NON_EXISTENT_UUID comes from the framework, not here.
"""

# --- Logical clock (PRD §2.5) ---
# "Before any operator intervention the clock reads exactly 2026-09-01T00:00:00Z"
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- Position grading (PRD §3.1) ---
# "knowledge contributes 300 points per level, supervision 200, complexity 250, and impact 250"
WEIGHT_KNOWLEDGE = 300
WEIGHT_SUPERVISION = 200
WEIGHT_COMPLEXITY = 250
WEIGHT_IMPACT = 250
# Narrative caps: "level 1 caps at grade 5, level 2 at grade 7, level 3 at grade 9,
# level 4 at grade 11, level 5 at grade 13"
LEVEL_GRADE_CAP = {1: 5, 2: 7, 3: 9, 4: 11, 5: 13}
# Point-factor bands, inclusive both ends (PRD §3.1):
# 1000–1599→5, 1600–2199→7, 2200–2799→9, 2800–3399→11,
# 3400–3899→12, 3900–4299→13, 4300–4699→14, 4700–5000→15
GRADE_BANDS = {
    5: (1000, 1599),
    7: (1600, 2199),
    9: (2200, 2799),
    11: (2800, 3399),
    12: (3400, 3899),
    13: (3900, 4299),
    14: (4300, 4699),
    15: (4700, 5000),
}
# Series grade span: "min_grade and max_grade, each between 5 and 15" (PRD §3.1)
GRADE_MIN = 5
GRADE_MAX = 15

# --- SME scoring (PRD §3.5) ---
# "knowledge carries weight 0.30, skill 0.20, and ability 0.50 ... scale factor 6 ...
#  then add the base of 70"
SME_WEIGHT_KNOWLEDGE = 0.30
SME_WEIGHT_SKILL = 0.20
SME_WEIGHT_ABILITY = 0.50
SME_SCALE = 6
SME_BASE = 70
# "the resulting score always lands between 76 and 100"
SME_SCORE_MIN = 76
SME_SCORE_MAX = 100

# --- Announcement cut points and validity (PRD §3.2) ---
# "bq_cut defaulting to 95, wq_cut defaulting to 85, and certificate_validity_days
#  defaulting to 60. Cut points must sit within 70 to 100 with wq_cut strictly
#  below bq_cut, and the validity window must be between 30 and 90 days"
DEFAULT_BQ_CUT = 95
DEFAULT_WQ_CUT = 85
CUT_MIN = 70
CUT_MAX = 100
DEFAULT_CERTIFICATE_VALIDITY_DAYS = 60
CERTIFICATE_VALIDITY_MIN_DAYS = 30
CERTIFICATE_VALIDITY_MAX_DAYS = 90

# --- Certificate roster (PRD §3.6) ---
# "while it still holds fewer than three names and a lower non-empty category exists"
RULE_OF_MANY_MIN = 3

# --- Certificate extension (PRD §3.7) ---
# "between 1 and 30 days per extension, at most two extensions"
EXTENSION_MIN_DAYS = 1
EXTENSION_MAX_DAYS = 30
MAX_EXTENSIONS = 2

# --- Appeal window (PRD §3.9) ---
# "deadline_at is computed and stored as the application's notified_at plus fourteen days"
APPEAL_WINDOW_DAYS = 14

# --- Offer response window (PRD §3.8) ---
# "response_due_at set five days later"
OFFER_RESPONSE_DAYS = 5

# --- Preference points (PRD §3.3) ---
# "5 for a verified FIVE_POINT claim, and 10 for a verified ten-point claim of either kind"
PREFERENCE_POINTS_FIVE = 5
PREFERENCE_POINTS_TEN = 10

# --- Sustained rating appeal return reason (PRD §3.5 / §3.9) ---
RETURN_REASON_APPEAL_SUSTAINED = "APPEAL_SUSTAINED"

# --- Pagination (PRD §2.3) ---
# "when omitted it defaults to 10, and it is bounded below by 1 and above by 100.
#  offset ... defaults to 0"
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
