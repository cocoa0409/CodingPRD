"""Domain constants for the Federal Water Allocation API.

The first sections are literals the contract itself states (PRD §2 and §3).
The later sections carry the shared fixture data the tests build on - the
two reservoir profiles, the three districts, the standard contracts, the
hydrology postings and the clock waypoints - together with the figures those
setups are specified to produce, each with its derivation in a comment so a
test reads as the rule it exercises instead of a magic number.
"""

# ── Logical clock (PRD §2.4) ───────────────────────────────────────────────
# "Before the clock has ever been set, the logical clock reads exactly
# 2026-09-01T00:00:00Z - a fixed startup default that never falls back to
# wall-clock time."
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

# ── Pagination (PRD §2.3) ──────────────────────────────────────────────────
# "The limit parameter ... defaults to 10, with a minimum of 1 and a maximum
# of 100. The offset parameter ... defaults to 0."
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── Roles (PRD §2.1 names exactly seven) ───────────────────────────────────
ROLE_SYSTEM_ADMIN = "SystemAdmin"
ROLE_RECLAMATION_OPERATOR = "ReclamationOperator"
ROLE_HYDROLOGY_OFFICER = "HydrologyOfficer"
ROLE_DISTRICT_MANAGER = "DistrictManager"
ROLE_ENVIRONMENTAL_OFFICER = "EnvironmentalOfficer"
ROLE_FINANCE_OFFICER = "FinanceOfficer"
ROLE_REGIONAL_DIRECTOR = "RegionalDirector"

ALL_ROLES = (
    ROLE_SYSTEM_ADMIN,
    ROLE_RECLAMATION_OPERATOR,
    ROLE_HYDROLOGY_OFFICER,
    ROLE_DISTRICT_MANAGER,
    ROLE_ENVIRONMENTAL_OFFICER,
    ROLE_FINANCE_OFFICER,
    ROLE_REGIONAL_DIRECTOR,
)

# ── Conversion rate and thresholds (PRD §2.6, §3.1, §3.3) ─────────────────
# "a fixed rate of 1.9835 acre-feet per cubic-foot-per-second sustained for
# one day"
CFS_DAY_TO_AF = 1.9835
# "the flood-control months of November, December, January, February, and
# March"
FLOOD_MONTHS = (11, 12, 1, 2, 3)
# "a flood-control holdback equal to flood_control_max_storage_af multiplied
# by one tenth, rounded half up to whole acre-feet"
FLOOD_HOLDBACK_PCT = 0.10
# "strictly below 0.50 classifies TIER_2; otherwise strictly below 0.75
# classifies TIER_1; otherwise NONE ... exactly 0.50 classifies TIER_1, and
# exactly 0.75 classifies NONE"
TIER_1_RATIO = 0.75
TIER_2_RATIO = 0.50
# "a hard cap of three revision rounds applies"
TRANSFER_REVISION_LIMIT = 3
# "a seventy-two-hour objection window before execution"
OBJECTION_WINDOW_HOURS = 72

# ═══════════════════════════════════════════════════════════════════════════
# Fixture-armed setup data shared by the tests
# ═══════════════════════════════════════════════════════════════════════════

# ── Clock waypoints ────────────────────────────────────────────────────────
CLOCK_OCTOBER = "2026-10-01T00:00:00Z"          # project seeding instant
CLOCK_JANUARY = "2027-01-15T00:00:00Z"          # publish instant (flood month)
CLOCK_JANUARY_16 = "2027-01-16T00:00:00Z"       # second order, one day later
CLOCK_JANUARY_20 = "2027-01-20T00:00:00Z"       # revision publish instant
CLOCK_APRIL = "2027-04-01T00:00:00Z"            # non-flood-month publish
CLOCK_JAN31_EOD = "2027-01-31T23:59:59Z"        # one second before a Feb 1 window
CLOCK_FEBRUARY_01_NOON = "2027-02-01T12:00:00Z"
CLOCK_FEBRUARY_03 = "2027-02-03T00:00:00Z"
CLOCK_FEBRUARY_03_10 = "2027-02-03T10:00:00Z"
CLOCK_FEBRUARY_05 = "2027-02-05T00:00:00Z"
CLOCK_MARCH_02 = "2027-03-02T00:00:00Z"
CLOCK_BEFORE_WINDOW_END = "2027-01-17T23:00:00Z"   # 71 h after a Jan 15 approval
CLOCK_WINDOW_END = "2027-01-18T00:00:00Z"          # Jan 15 approval + 72 h
OBSERVED_ON_BASE = "2027-01-10T00:00:00Z"
OBSERVED_ON_REVISION = "2027-01-20T00:00:00Z"

# ── The water year (PRD §3.2: unique integer label, start precedes end) ────
YEAR_LABEL = 2027
SEASON_START = "2026-10-01T00:00:00Z"
SEASON_END = "2027-09-30T00:00:00Z"

# ── Reservoir profiles ─────────────────────────────────────────────────────
# Small unit: usable storage 10,500 - 5,000 = 5,500; flood holdback
# round_half_up(20,000 * 0.10) = 2,000 when the publish month is a flood month.
RESERVOIR_SMALL = {
    "name": "Shasta Unit",
    "capacity_af": 50_000,
    "dead_pool_af": 5_000,
    "flood_control_max_storage_af": 20_000,
    "initial_storage_af": 10_500,
    "outlet_capacity_cfs": 15_000,
    "power_conversion_mwh_per_af": 0.5,
}
# Big unit: usable 3,000,000 - 200,000 = 2,800,000; holdback
# round_half_up(3,600,000 * 0.10) = 360,000 in flood months. Storage starts at
# or below the flood max, so the flood gate never fires on this profile.
RESERVOIR_BIG = {
    "name": "Shasta Unit",
    "capacity_af": 4_552_000,
    "dead_pool_af": 200_000,
    "flood_control_max_storage_af": 3_600_000,
    "initial_storage_af": 3_000_000,
    "outlet_capacity_cfs": 15_000,
    "power_conversion_mwh_per_af": 0.5,
}
# Flood unit: storage starts ABOVE the flood max (4,000,000 > 3,600,000) so the
# flood-control gate engages whenever the clock sits in a flood month.
RESERVOIR_FLOOD = {
    "name": "Flood Unit",
    "capacity_af": 4_552_000,
    "dead_pool_af": 200_000,
    "flood_control_max_storage_af": 3_600_000,
    "initial_storage_af": 4_000_000,
    "outlet_capacity_cfs": 15_000,
    "power_conversion_mwh_per_af": 0.5,
}

# ── Districts ──────────────────────────────────────────────────────────────
DISTRICT_SR = {
    "name": "Senior Irrigation District",
    "service_area_acres": 42_000,
    "contact_email": "ops@senior.example",
}
DISTRICT_JR = {
    "name": "Junior Water District",
    "service_area_acres": 18_000,
    "contact_email": "ops@junior.example",
}
DISTRICT_TP = {
    "name": "Third Party District",
    "service_area_acres": 9_000,
    "contact_email": "ops@third.example",
}

# ── Standard contracts ─────────────────────────────────────────────────────
# Total maximum 6,000 + 4,000 = 10,000 acre-feet, the denominator of every
# shortage-tier ratio in the shared setups.
CONTRACT_SR = {
    "contract_number": "C-100",
    "priority_class": "SENIOR",
    "max_annual_quantity_af": 6_000,
    "repayment_obligation_cents": 120_000_000,
}
CONTRACT_JR = {
    "contract_number": "C-200",
    "priority_class": "JUNIOR",
    "max_annual_quantity_af": 4_000,
    "repayment_obligation_cents": 80_000_000,
}
CONTRACT_TP = {
    "contract_number": "C-300",
    "priority_class": "JUNIOR",
    "max_annual_quantity_af": 1_000,
    "repayment_obligation_cents": 5_000_000,
}
# Repayment-settlement trio: obligations 7M / 5M / 3M cents, total 15M, chosen
# so a 1-cent settlement rounds every per-contract credit to 0 and leaves a
# 1-cent remainder for the largest-outstanding rule (PRD §3.7).
CONTRACT_A = {
    "contract_number": "C-A",
    "priority_class": "SENIOR",
    "max_annual_quantity_af": 1_000,
    "repayment_obligation_cents": 7_000_000,
}
CONTRACT_B = {
    "contract_number": "C-B",
    "priority_class": "JUNIOR",
    "max_annual_quantity_af": 1_000,
    "repayment_obligation_cents": 5_000_000,
}
CONTRACT_C = {
    "contract_number": "C-C",
    "priority_class": "JUNIOR",
    "max_annual_quantity_af": 1_000,
    "repayment_obligation_cents": 3_000_000,
}

# ── Hydrology postings ─────────────────────────────────────────────────────
SNOWPACK_BASE = 80
RUNOFF_BASE = 5_000
SNOWPACK_SHORTAGE = 50
RUNOFF_SHORTAGE = 3_000
RUNOFF_BOUNDARY = 4_999        # one forecast acre-foot below the 0.75 boundary
RUNOFF_REVISION = 4_000
RUNOFF_LATE = 3_000            # same value as shortage, observed later
INFLOW_CREDIT = 50_000

# ── Shortage-sharing agreement (PRD §3.4) ──────────────────────────────────
AGREEMENT_NAME = "Drought Plan 2027"
TIER_1_SENIOR_PCT = 70
TIER_1_JUNIOR_PCT = 40
TIER_2_SENIOR_PCT = 55
TIER_2_JUNIOR_PCT = 25
QUORUM_TWO = 2
QUORUM_ONE = 1

# ── Revenue-period rates ───────────────────────────────────────────────────
RATE_STANDARD = 4_500          # cents per MWh
RATE_ROUNDING = 100
RATE_ONE_CENT = 1
PERIOD_FEBRUARY = "2027-02"
PERIOD_MARCH = "2027-03"

# ═══════════════════════════════════════════════════════════════════════════
# Derived figures the shared setups produce (derivation in each comment)
# ═══════════════════════════════════════════════════════════════════════════

# Declared supply (PRD §3.3 step 1), small reservoir, publish in a flood month:
# usable 5,500 + round_half_up(F * P / 100) - holdback 2,000.
DECLARED_BASE = 7_500          # 5,500 + round(5,000*80/100)=4,000 - 2,000
TIER_BASE = "NONE"             # ratio 7,500 / 10,000 = 0.75 exactly -> NONE
ALLOC_BASE_SR = 6_000          # waterfall: min(6,000, 7,500)
ALLOC_BASE_JR = 1_500          # waterfall: min(4,000, 1,500)

DECLARED_BOUNDARY = 7_499      # 5,500 + round(4,999*80/100)=3,999 - 2,000
TIER_BOUNDARY = "TIER_1"       # ratio 0.7499 < 0.75
ALLOC_BOUNDARY_JR = 1_499      # waterfall: min(4,000, 1,499)

DECLARED_SHORTAGE = 5_000      # 5,500 + round(3,000*50/100)=1,500 - 2,000
TIER_SHORTAGE = "TIER_1"       # ratio 0.50 exactly -> TIER_1
ALLOC_SHORTAGE_WATERFALL_SR = 5_000
ALLOC_SHORTAGE_WATERFALL_JR = 0
# Sharing at TIER_1 with 70/40 guarantees (PRD §3.4): raw shares
# round(6,000*0.70)=4,200 and round(4,000*0.40)=1,600 total 5,800 > 5,000, so
# the JUNIOR line absorbs the whole 800 excess; SENIOR lines are never reduced.
ALLOC_SHORTAGE_SHARING_SR = 4_200
ALLOC_SHORTAGE_SHARING_JR = 800

DECLARED_REVISION = 6_700      # 5,500 + round(4,000*80/100)=3,200 - 2,000
ALLOC_REVISION_JR = 700        # waterfall: min(4,000, 700)

DECLARED_APRIL = 9_500         # identical observations, April publish: 5,500 + 4,000 - 0

DECLARED_LATE_OBS = 5_900      # latest runoff 3,000 governs: 5,500 + 2,400 - 2,000

# Big reservoir, base observations, January publish:
# (3,000,000 - 200,000) + 4,000 - 360,000
DECLARED_BIG = 2_444_000

# Release volumes (PRD §2.6 / §3.5): round_half_up(cfs * days * 1.9835).
VOLUME_R1 = 19_835             # 1,000 cfs x 10 days = 19,835.0
VOLUME_R2 = 3_967              # 500 cfs x 4 days = 3,967.0
VOLUME_WEAK = 3_967            # 400 cfs x 5 days = 3,967.0
VOLUME_333 = 661               # 333 x 1 x 1.9835 = 660.5055 -> 661
VOLUME_7X3 = 42                # 7 x 3 x 1.9835 = 41.6535 -> 42
VOLUME_TINY = 2                # 1 x 1 x 1.9835 = 1.9835 -> 2
VOLUME_100X2 = 397             # 100 x 2 x 1.9835 = 396.7 -> 397

# Storage ledger (PRD §2.10): initial + inflows - executed volumes.
STORAGE_AFTER_INFLOW_AND_R1 = 3_030_165   # 3,000,000 + 50,000 - 19,835
STORAGE_AFTER_WEAK = 2_996_033            # 3,000,000 - 3,967

# Hydropower revenue (PRD §3.7): per-release integer volumes summed first,
# then mwh = round_half_up(volume * 0.5, 2), then cents = round_half_up(mwh * rate).
PROJECTED_MWH_FEB = 11_901.0              # (19,835 + 3,967) * 0.5
PROJECTED_REVENUE_FEB_CENTS = 53_554_500  # 11,901.0 * 4,500
SETTLED_MWH_FEB = 9_917.5                 # 19,835 * 0.5 (EXECUTED only)
SETTLED_REVENUE_FEB_CENTS = 44_628_750    # 9,917.5 * 4,500
SETTLED_MWH_ROUNDING = 661.0              # (661 + 661) * 0.5, per-release rounding first
SETTLED_REVENUE_ROUNDING_CENTS = 66_100   # 661.0 * 100
SETTLED_MWH_ONE_CENT = 1.0                # 2 * 0.5
SETTLED_REVENUE_ONE_CENT = 1              # 1.0 * 1

# Repayment settlement of the 1-cent period over the 7M/5M/3M trio: every
# rounded per-contract credit is 0 and the 1-cent remainder lands on the
# largest outstanding balance (C-A), so the unrecovered balance drops to:
TOTAL_OBLIGATION_TRIO_CENTS = 15_000_000
UNRECOVERED_AFTER_ONE_CENT = 14_999_999
