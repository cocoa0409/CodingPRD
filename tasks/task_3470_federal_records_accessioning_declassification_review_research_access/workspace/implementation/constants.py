"""All PRD/scaffold-pinned constants in one place (scaffold §1.3).

NOTE: METADATA_REQUIRED is referenced by PRD §3.2 ("the system holds, for each
metadata standard, a defined set of required element names") but the element
names are not enumerated in PRD.md or SCAFFOLD.yaml. The sets below are the
single canonical definition for this implementation; kept in exactly one place
so they are trivial to reconcile.
"""

# --- Roles (PRD §2.1, exact spellings) ---
ROLES = [
    "PlatformAdmin", "Anonymous", "RecordsOfficer", "AgencyLiaison",
    "AppraisalArchivist", "ProcessingArchivist", "DeclassReviewer",
    "ChiefArchivist", "ResearchRoomStaff", "FoiaOfficer",
    "FoiaAppealsOfficer", "Researcher",
]
ALL_READ_ROLES = [r for r in ROLES if r != "Anonymous"]

# --- Time / quota constants (scaffold §1.3) ---
REFERRAL_RESPONSE_DAYS = 21
CARD_VALIDITY_YEARS = 2
MAX_PULL_UNITS_PER_REQUEST = 24
VISIT_WINDOW_DAYS = 30
REPRO_DAILY_PAGE_LIMIT = 200
SYSTEMATIC_REVIEW_AGE_YEARS = 25
NOTICE_COOLING_DAYS = 30
APPEAL_WINDOW_DAYS = 30
PULL_OCCUPATION_DAYS = 2
READING_ROOM_DAILY_SEATS = 8
MAX_ACTIVE_PULLS_PER_RESEARCHER = 3
TRANSFER_LAG_MIN = 0
TRANSFER_LAG_MAX = 50

# --- Reproduction fee (calculations.reproduction_fee) ---
TIER1_PAGES = 20
TIER1_RATE_CENTS = 80
TIER2_PAGES = 80
TIER2_RATE_CENTS = 50
TIER3_RATE_CENTS = 25
ACADEMIC_DISCOUNT_RATE = "0.85"
RUSH_MULTIPLIER = "1.5"

# --- Digitization priority (calculations.digitization_priority) ---
AGE_POINTS_PER_YEAR = 2
AGE_CAP_YEARS = 50
PULL_POINTS = 3
PULL_CAP = 20
FOIA_POINTS = 5
FOIA_CAP = 10
REPRO_PAGES_CAP = 500
REPRO_PAGES_DIVISOR = 50
DECLASSIFIED_BONUS = 25

# --- Processing backlog score (calculations.processing_backlog_score) ---
BACKLOG_AGE_POINTS_PER_YEAR = 10
BACKLOG_AGE_CAP = 60
CLASSIFICATION_WEIGHT = {"NONE": 0, "CONFIDENTIAL": 5, "SECRET": 15, "TOP_SECRET": 30}
PRESIDENTIAL_BONUS = 20

# --- Enums ---
RECORDS_DOMAINS = ["FEDERAL", "PRESIDENTIAL"]
DISPOSITIONS = ["PERMANENT", "TEMPORARY"]
CLASSIFICATIONS = ["NONE", "CONFIDENTIAL", "SECRET", "TOP_SECRET"]
TRANSFER_METHODS = ["PHYSICAL", "ELECTRONIC"]
METADATA_STANDARDS = ["EAD_2002", "MODS_3_7", "PREMIS_3_0"]
REVIEW_TYPES = ["SYSTEMATIC", "MANDATORY"]
REFERRAL_DECISIONS = ["DECLASSIFY", "EXEMPT"]
REVIEWER_ASSESSMENTS = ["DECLASSIFY", "EXEMPT"]
AFFILIATIONS = ["ACADEMIC", "JOURNALIST", "GENEALOGIST", "COMMERCIAL", "GOVERNMENT"]
REPRO_FORMATS = ["DIGITAL_SCAN", "CERTIFIED_COPY", "PHOTOPRINT"]
FOIA_DECISIONS = ["GRANT", "PARTIAL", "DENY"]
APPEAL_DECISIONS = ["GRANT", "UPHOLD", "REMAND"]
APPRAISAL_RECOMMENDATIONS = ["APPROVE", "RETURN"]
SCHEDULE_DECISIONS = ["APPROVE", "RETURN"]
RESTRICTION_CATEGORIES = [
    "P1_NATIONAL_SECURITY", "P2_APPOINTMENTS", "P3_STATUTORY",
    "P4_TRADE_SECRETS", "P5_CONFIDENTIAL_ADVICE", "P6_PERSONAL_PRIVACY",
]
FOIA_EXEMPTION_CODES = {"B1", "B3", "B5"}

# --- Required metadata elements per standard (PRD §3.2; see NOTE above) ---
METADATA_REQUIRED = {
    "EAD_2002": ["title", "creator", "date", "extent", "scope_content"],
    "MODS_3_7": ["title", "creator", "date", "identifier", "type_of_resource"],
    "PREMIS_3_0": ["object_identifier", "object_category", "preservation_level",
                   "original_name", "format_name"],
}
