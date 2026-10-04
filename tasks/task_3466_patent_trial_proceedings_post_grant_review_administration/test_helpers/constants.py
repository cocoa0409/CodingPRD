"""Domain thresholds and constants, all carrying PRD-stated values.

Sources: PRD §2.4 (clock default), §3.3 (fees, time bar), §3.4 (merits
thresholds, Fintiv, panel capacity, institution window), §3.5 (brief
windows and page limits), §3.6 (Garmin factors), §3.7 (turnover buffer),
§3.8 (final-decision deadline and extension).
"""

# Logical clock (PRD §2.4): default reading before any clock-set call.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# Merits thresholds (PRD §3.4): 40 for IPR, 51 for PGR.
IPR_THRESHOLD = 40
PGR_THRESHOLD = 51
AGGREGATE_MAX_WEIGHT = 0.7
AGGREGATE_MEAN_WEIGHT = 0.3

# Fintiv discretionary screen (PRD §3.4).
FINTIV_BASE = 20
FINTIV_PROXIMITY = 40
FINTIV_INVESTMENT = 20
FINTIV_STAY_CREDIT = -20
FINTIV_DENIAL_THRESHOLD = 70
FINTIV_INVESTMENT_DAYS = 180
PROJECTED_FWD_DAYS = 365

# Final-written-decision deadline (PRD §3.8).
FWD_BASE_DAYS = 365
FWD_EXTENSION_DAYS = 183

# Briefing windows in days from the cycle anchor (PRD §3.5).
PO_RESPONSE_DAYS = 90
PETITIONER_REPLY_DAYS = 132
PO_SUR_REPLY_DAYS = 146

# Brief page rules (PRD §3.5): fee-free limits and absolute hard caps.
PO_RESPONSE_LIMIT = 90
PETITIONER_REPLY_LIMIT = 45
PO_SUR_REPLY_LIMIT = 20
PO_RESPONSE_CAP = 110
PETITIONER_REPLY_CAP = 65
PO_SUR_REPLY_CAP = 40
OVERAGE_RATE_CENTS_PER_PAGE = 316.25

# Garmin interest-of-justice score (PRD §3.6).
GARMIN_GRANT_THRESHOLD = 6
GARMIN_EMPTY_FACTOR_CAP = 4
GARMIN_REPLY_BONUS = 1
GARMIN_MAX = 10
GARMIN_FACTOR_COUNT = 5

# Petition filing fee (PRD §3.3): base covers up to 20 challenged claims.
BASE_FEE_CENTS = 1_900_000
INCLUDED_CLAIMS = 20
EXCESS_CLAIM_FEE_CENTS = 15_000

# Statutory screens.
TIME_BAR_DAYS = 365          # PRD §3.3: strictly more than 365 bars
INSTITUTION_WINDOW_DAYS = 93  # PRD §3.4: on or before accorded + 93 is timely
TURNOVER_BUFFER_MINUTES = 30  # PRD §3.7
PANEL_LEAD_CAPACITY = 2       # PRD §3.4

# Extension requests (PRD §3.8): justification must run >= 20 characters.
JUSTIFICATION_MIN_CHARS = 20
