"""Numeric constants, program defaults and precision rules from the contract.

Every value here is quoted from the PRD narrative so tests never re-derive an
arithmetic constant by hand.
"""

# ---------------------------------------------------- §3.1 monitoring sample load
# "multiply the measured concentration by the flow, multiply that product by the
#  concentration-to-pounds-per-day conversion factor of 5.393, multiply again by
#  365 days in the year"
LB_PER_DAY_FACTOR = 5.393
DAYS_PER_YEAR = 365

# --------------------------------------------------- §3.3 the allocation waterfall
# "The reserve set-aside is 5 percent of the allocable load"
RESERVE_FRACTION = 0.0500
# "point_pool_lbs_yr is 60 percent of the distributable load"
POINT_POOL_SHARE = 0.6000

# -------------------------------------------- §3.4 compliance-schedule tier table
TIER_A_MAX_PCT = 20.00
TIER_B_MAX_PCT = 50.00
TIER_RELIEF = {"TIER_A": 0.00, "TIER_B": 0.25, "TIER_C": 0.50}
TIER_SCHEDULE_YEARS = {"TIER_A": 0, "TIER_B": 3, "TIER_C": 5}

# ----------------------------------------------------- §3.8 geographic path limit
# "if the path has grown beyond ten reaches without arriving at the buyer reach"
MAX_PATH_DEPTH = 10

# ---------------------------------------------------- §3.9 review window spacing
# "separated ... by at least one clear calendar day on both sides"
REVIEW_GAP_DAYS = 1

# ------------------------------------------------------- §3.1 watershed defaults
DEFAULT_INTERIM_TARGET_PCT = 25.00
DEFAULT_UNCERTAINTY_RATIO = 2.0000
DEFAULT_RETIREMENT_RATIO = 0.1000
DEFAULT_EQUIVALENCE_RATIO = 1.0000

# ---------------------------------------------------------- §2.4 the logical clock
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
# Pinned instant every fixture chain in this suite runs at.
CLOCK_BASE = "2026-06-15T00:00:00Z"
CLOCK_BASE_STAMP = "2026-06-15T00:00:00.000Z"

# ---------------------------------------------------------------- §2.5 precision
LOAD_DP = 2       # pounds per year
RATIO_DP = 4      # uncertainty / retirement / equivalence / delivery / verified
PCT_DP = 2        # interim_target_pct, required_reduction_pct, achieved_reduction_pct
MOS_PCT_DP = 4    # margin_of_safety_pct is a fraction of capacity to 4 dp
FLOW_MGD_DP = 4   # design_flow_mgd
CONC_DP = 4       # measured_conc_mg_l
FLOW_CFS_DP = 2   # flow_cfs

# ------------------------------------------------------------- §2.3 pagination
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --------------------------------------------------- unknown-identifier probes
# Distinct well-formed UUIDs so a multi-probe test never reuses one id.
UNKNOWN_UUIDS = [
    "00000000-0000-4000-8000-00000000000{}".format(c)
    for c in "123456789ab"
]
UNKNOWN_UUID_A = "00000000-0000-4000-8000-000000000000"
UNKNOWN_UUID_AA = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_UUID_FF = "00000000-0000-4000-8000-0000000000ff"
UNKNOWN_UUID_C1 = "00000000-0000-4000-8000-0000000000c1"
