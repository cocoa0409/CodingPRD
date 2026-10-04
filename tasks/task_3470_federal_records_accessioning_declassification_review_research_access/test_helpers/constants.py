"""Domain constants — every literal traced to a verbatim PRD.md statement.

Nothing here is invented or carried from memory: each value is the number the
PRD prose pins, with the section noted in a comment.  Defaults for synthetic
test data (names, emails, cutoff dates, visit dates) live in factories.py,
not here — this module holds only contract constants.
"""

# ─── Mount points (PRD §1, §2.4, §4) ─────────────────────────────────────────
# "The API is mounted under `/records`; one administrative capability outside
# that mount sets the logical clock."
API_PREFIX = "/records"
# The logical-clock capability lives OUTSIDE the /records mount — do not prefix.
CLOCK_PATH = "/_clock/set_current_utc"

# ─── Logical clock (PRD §2.4) ────────────────────────────────────────────────
# "Before any such call, the server's startup default is exactly
# 2026-09-01T00:00:00Z; the clock must never fall back to wall-clock time."
STARTUP_CLOCK_UTC = "2026-09-01T00:00:00Z"

# ─── Pagination (PRD §2.3) ───────────────────────────────────────────────────
# "defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
# maximum of 100. The `offset` parameter ... defaults to 0."
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# ─── Schedules (PRD §3.1) ────────────────────────────────────────────────────
# transfer_lag_years "must lie between 0 and 50 inclusive".
TRANSFER_LAG_YEARS_MIN = 0
TRANSFER_LAG_YEARS_MAX = 50

# ─── Accession backlog score (PRD §3.3) ──────────────────────────────────────
# "ten points per whole year of records age ... counting at most sixty years;
# adds a classification weight of 0 for NONE, 5 for CONFIDENTIAL, 15 for
# SECRET, or 30 for TOP_SECRET; and adds a further 20 points when the
# collection's domain is PRESIDENTIAL."
BACKLOG_AGE_POINTS_PER_YEAR = 10
BACKLOG_AGE_CAP_YEARS = 60
BACKLOG_CLASSIFICATION_WEIGHTS = {
    "NONE": 0,
    "CONFIDENTIAL": 5,
    "SECRET": 15,
    "TOP_SECRET": 30,
}
BACKLOG_PRESIDENTIAL_BONUS = 20

# ─── Digitization priority (PRD §3.4) ────────────────────────────────────────
# "2 points per whole year of records age, counting at most 50 years; plus 3
# points per fulfilled pull request ... at most 20 pulls; plus 5 points per
# FOIA release ... at most 10 releases; plus 1 point per 50 fulfilled
# reproduction pages, where the page count is capped at 500 before being
# divided by 50 and rounded down; plus a bonus of 25 points when the
# collection's declass_outcome is DECLASSIFIED."
DIGI_AGE_POINTS_PER_YEAR = 2
DIGI_AGE_CAP_YEARS = 50
DIGI_PULL_POINTS = 3
DIGI_PULL_CAP = 20
DIGI_FOIA_POINTS = 5
DIGI_FOIA_CAP = 10
DIGI_REPRO_PAGES_CAP = 500
DIGI_REPRO_PAGES_DIVISOR = 50
DIGI_DECLASSIFIED_BONUS = 25

# ─── Declassification review (PRD §3.5) ──────────────────────────────────────
# "response_due_at computed as 21 days after sent_at".
REFERRAL_RESPONSE_DAYS = 21
# "the records' whole-year age ... must be at least 25 years, with the
# boundary inclusive".
SYSTEMATIC_REVIEW_AGE_YEARS = 25

# ─── Presidential restrictions (PRD §3.6) ────────────────────────────────────
# "release is allowed only once the clock has reached notified_at plus 30
# days, with the boundary inclusive".
NOTICE_COOLING_DAYS = 30
# "The category is one of six statutory grounds, spelled exactly: ..."
RESTRICTION_CATEGORIES = [
    "P1_NATIONAL_SECURITY",
    "P2_APPOINTMENTS",
    "P3_STATUTORY",
    "P4_TRADE_SECRETS",
    "P5_CONFIDENTIAL_ADVICE",
    "P6_PERSONAL_PRIVACY",
]

# ─── Researcher registration and research room (PRD §3.7) ────────────────────
# "the research card is valid for two years" (activation instant + 2 years,
# anniversary arithmetic).
CARD_VALIDITY_YEARS = 2
# visit_date "on or after the clock's current instant and no later than 30
# days out".
VISIT_WINDOW_DAYS = 30
# "the reserved span ... may not exceed 24 units".
MAX_PULL_UNITS_PER_REQUEST = 24
# "must remain within the room's 8 seats; the eighth pull seated on a day
# succeeds and the ninth is rejected".
READING_ROOM_DAILY_SEATS = 8
# "a researcher may hold fewer than 3 pulls in REQUESTED or PULLED status, so
# a third active pull succeeds while a fourth is rejected".
MAX_ACTIVE_PULLS_PER_RESEARCHER = 3
# "A pull's occupation window is the half-open interval from its visit_date
# through two days later".
PULL_OCCUPATION_DAYS = 2
# "due_back_at computed as its visit_date plus 24 hours".
PULL_DUE_BACK_HOURS = 24
# "The affiliation is one of ACADEMIC, JOURNALIST, GENEALOGIST, COMMERCIAL,
# or GOVERNMENT".
AFFILIATIONS = [
    "ACADEMIC",
    "JOURNALIST",
    "GENEALOGIST",
    "COMMERCIAL",
    "GOVERNMENT",
]
# suspension_reason value set by the late-return cascade.
SUSPENSION_REASON_LATE_RETURN = "LATE_RETURN"

# ─── Reproduction services (PRD §3.8) ────────────────────────────────────────
# "the committed pages plus the new request's page_count must not exceed 200
# pages, with the boundary inclusive".
REPRO_DAILY_PAGE_LIMIT = 200
# "the first 20 pages at 80 cents per page, the next 80 pages (pages 21
# through 100) at 50 cents per page, and every page beyond 100 at 25 cents
# per page".
FEE_TIER1_PAGES = 20
FEE_TIER1_RATE_CENTS = 80
FEE_TIER2_PAGES = 80
FEE_TIER2_RATE_CENTS = 50
FEE_TIER3_RATE_CENTS = 25
# "each tier's subtotal is multiplied by 0.85 and rounded half up".
ACADEMIC_DISCOUNT_RATE = 0.85
# "the summed amount is multiplied by 1.5 and rounded half up".
RUSH_MULTIPLIER = 1.5
# "The format is one of DIGITAL_SCAN, CERTIFIED_COPY, or PHOTOPRINT".
REPRO_FORMATS = ["DIGITAL_SCAN", "CERTIFIED_COPY", "PHOTOPRINT"]

# ─── FOIA (PRD §3.9) ─────────────────────────────────────────────────────────
# "claimed_exemptions must be a non-empty subset of the recognized exemption
# codes B1, B3, and B5".
FOIA_EXEMPTION_CODES = ["B1", "B3", "B5"]
# "The appeal window is thirty days: the appeal must arrive while the clock
# stands at or before decided_at plus 30 days, with the boundary inclusive".
APPEAL_WINDOW_DAYS = 30
# close_reason set by the posture-flip cascade.
FOIA_CLOSE_REASON_RECORDS_MADE_PUBLIC = "RECORDS_MADE_PUBLIC"

# ─── Transfer methods and metadata standards (PRD §3.2) ──────────────────────
# "The transfer_method is PHYSICAL or ELECTRONIC; the metadata_standard is one
# of EAD_2002, MODS_3_7, or PREMIS_3_0. An ELECTRONIC transfer requires the
# PREMIS_3_0 standard, while a PHYSICAL transfer requires EAD_2002 or
# MODS_3_7".
TRANSFER_METHODS = ["PHYSICAL", "ELECTRONIC"]
METADATA_STANDARDS = ["EAD_2002", "MODS_3_7", "PREMIS_3_0"]

# ─── Schedule enumerations (PRD §3.1) ────────────────────────────────────────
# records_domain "is either FEDERAL or PRESIDENTIAL".
RECORDS_DOMAINS = ["FEDERAL", "PRESIDENTIAL"]
# disposition "is either PERMANENT or TEMPORARY".
DISPOSITIONS = ["PERMANENT", "TEMPORARY"]
# classification_default "is one of NONE, CONFIDENTIAL, SECRET, or
# TOP_SECRET".
CLASSIFICATION_LEVELS = ["NONE", "CONFIDENTIAL", "SECRET", "TOP_SECRET"]
