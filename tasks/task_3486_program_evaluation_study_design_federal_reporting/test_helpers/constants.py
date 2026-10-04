"""Domain constants — exact values stated in the PRD.

Every value here is grep-verified against PRD.md. Only constants the test
suite actually references are defined (no dead scaffold leftovers).
"""

# --- Logical clock (PRD logical-clock section) ---
CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"

# --- Power analysis (PRD design-planning section) ---
Z_ALPHA_CRIT = 1.96          # two-sided alpha=0.05 critical value
Z_POWER_CRIT = 0.84          # power=0.80 critical value
QED_VARIANCE_INFLATION = 1.44  # quasi-experimental variance inflation (1.2^2)

# --- Recruitment feasibility yields (PRD site-recruitment section) ---
YIELD_PROSPECTED = 0.10
YIELD_CONTACTED = 0.35

# --- Human-subjects / burden (PRD data-collection section) ---
MAX_TOTAL_BURDEN_MINUTES = 480  # per-participant billed-burden cap (480 exact allowed)
MODE_FACTOR_SURVEY = 1.0
MODE_FACTOR_SITE_VISIT = 1.25
MODE_FACTOR_ADMIN_RECORDS = 0.5

# --- Site-visit spacing (PRD wave-planning section) ---
SITE_VISIT_MIN_GAP_DAYS = 7  # gap >= 7 days passes

# --- IRB windows (PRD IRB section) ---
IRB_MAX_APPROVAL_DAYS = 365  # window length must not exceed 365 days

# --- Report timelines (PRD reporting/publication sections) ---
PEER_REVIEW_DAYS = 45   # peer_review_due = submitted_at + 45 days (informational)
AGENCY_COMMENT_DAYS = 30  # informational comment window
REVISION_DAYS = 60      # revision_due = decision time + 60 days
PUBLICATION_DAYS = 90   # publication_due = accepted_at + 90 days

# --- Disclosure risk (PRD restricted-use-file section) ---
K_ANONYMITY_MIN = 5         # cells with count < 5 are suppressed
MAX_DISCLOSURE_RISK = 0.20  # release gate: max_risk <= 0.20 (exactly 0.20 passes)

# --- PRD worked-example inputs (power analysis illustration) ---
# mde=0.5, cluster_size=10, icc=0.05, attrition_rate=0.15
WORKED_MDE = 0.5
WORKED_CLUSTER_SIZE = 10
WORKED_ICC = 0.05
WORKED_ATTRITION_RATE = 0.15
# PRD-stated results for those inputs
WORKED_RCT_N_PER_ARM = 107
WORKED_RCT_REQUIRED_TOTAL_N = 214
WORKED_QED_N_PER_ARM = 155
WORKED_QED_REQUIRED_TOTAL_N = 310

# --- PRD worked-example inputs (disclosure risk illustration) ---
# cell_counts [5, 4, 12, 30], weights [1.0, 1.0, 0.5, 0.5]
WORKED_RUF_CELL_COUNTS = [5, 4, 12, 30]
WORKED_RUF_SENSITIVITY_WEIGHTS = [1.0, 1.0, 0.5, 0.5]
WORKED_RUF_SUPPRESSED_CELL_COUNT = 1
WORKED_RUF_MAX_RISK = 0.20
WORKED_RUF_MEAN_RISK = 0.0426

# --- Shared temporal anchors used by composite fixtures ---
# All recipe-referenced dates are at or after the clock default, so fixtures
# set the clock explicitly before opening windows.
IRB_APPROVAL_START = "2026-09-01T00:00:00Z"
IRB_APPROVAL_END = "2027-09-01T00:00:00Z"  # exactly 365 days after start
WAVE_OPEN_AT = "2026-10-01T00:00:00Z"
WAVE_CLOSE_AT = "2026-11-01T00:00:00Z"
CLOCK_WITHIN_WAVE = "2026-10-15T00:00:00Z"
