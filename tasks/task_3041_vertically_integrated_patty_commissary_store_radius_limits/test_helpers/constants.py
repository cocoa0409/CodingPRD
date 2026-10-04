"""Domain constants — every numeric threshold the PRD pins.

Sources:
- PRD section 2.4: logical-clock startup default 2026-09-01T00:00:00Z (a Tuesday).
- PRD section 2.8: haversine over Earth radius 6371.0 km; radius gate is strict <.
- PRD section 2.9: normal gap ceiling 48 hours, tightened ceiling 24 hours;
  patties in cases of 40, buns in cases of 48, produce in cases of 12;
  modifier charges rounded half-up per line then summed.
- PRD section 3.3: cold-chain limit 4.0 degrees Celsius (strictly greater fails);
  raw-beef requirement rounds patties up to a whole pound (3 patties per pound,
  hence CEIL(1000/3) == 334 in the worked example).
- PRD section 3.6: modifier unit prices 150 / 65 / 0 / 0 cents, ten percent
  WELL_DONE reduction.
- PRD section 3.6: surge window 7 days, intensity bucket of 10 PLACED orders,
  5-minute pacing step, 5-minute floor, per-day caps 45/45/45/30/30/20/20.
- PRD section 3.7: wage ladder 1750/1850/1975/2100/2250/2500/3200 cents,
  tenure gate 180 days, at-least-2 future scheduled shifts, promotion cap 6,
  coverage-critical ratio 0.60, minimum leads 1.
"""

# ─── Roles (PRD section 2.1, exact spellings) ───────────────────────────────

ROLE_SUPPLY_CHAIN_DIRECTOR = "SupplyChainDirector"
ROLE_COMMISSARY_PLANNER = "CommissaryPlanner"
ROLE_QUALITY_AUDITOR = "QualityAuditor"
ROLE_REAL_ESTATE_PLANNER = "RealEstatePlanner"
ROLE_STORE_MANAGER = "StoreManager"
ROLE_ASSOCIATE = "Associate"
ROLE_HR_DIRECTOR = "HRDirector"

ALL_ROLES = (
    ROLE_SUPPLY_CHAIN_DIRECTOR,
    ROLE_COMMISSARY_PLANNER,
    ROLE_QUALITY_AUDITOR,
    ROLE_REAL_ESTATE_PLANNER,
    ROLE_STORE_MANAGER,
    ROLE_ASSOCIATE,
    ROLE_HR_DIRECTOR,
)

# ─── Logical clock (PRD section 2.4) ────────────────────────────────────────

# Fixed startup default; 2026-09-01 is a Tuesday.
CLOCK_START = "2026-09-01T00:00:00Z"

# ─── Geography (PRD section 2.8) ────────────────────────────────────────────

EARTH_RADIUS_KM = 6371.0

# ─── Freshness cadence (PRD section 2.9 / 3.5) ─────────────────────────────

NORMAL_MAX_GAP_HOURS = 48
SURGE_MAX_GAP_HOURS = 24
COLD_CHAIN_MAX_C = 4.0
PATTY_CASE = 40
BUN_CASE = 48
PRODUCE_CASE = 12
PATTIES_PER_LB = 3

# ─── Menu modifiers (PRD section 3.6) ───────────────────────────────────────

MODIFIER_EXTRA_PATTY = "EXTRA_PATTY"
MODIFIER_ANIMAL_STYLE = "ANIMAL_STYLE"
MODIFIER_PROTEIN_STYLE = "PROTEIN_STYLE"
MODIFIER_WELL_DONE = "WELL_DONE"

MODIFIER_UNIT_CENTS = {
    MODIFIER_EXTRA_PATTY: 150,
    MODIFIER_ANIMAL_STYLE: 65,
    MODIFIER_PROTEIN_STYLE: 0,
    MODIFIER_WELL_DONE: 0,
}
WELL_DONE_DISCOUNT_PCT = 0.10

# ─── Opening surge (PRD section 3.6) ────────────────────────────────────────

SURGE_WINDOW_DAYS = 7
SURGE_BUCKET_SIZE = 10
SURGE_PACING_STEP_MIN = 5
MIN_PACING_MIN = 5
PACING_CAP_MIN = {1: 45, 2: 45, 3: 45, 4: 30, 5: 30, 6: 20, 7: 20}

# ─── Wage ladder and promotion gates (PRD section 3.7) ─────────────────────

LEVEL_1 = "LEVEL_1"
LEVEL_2 = "LEVEL_2"
LEVEL_3 = "LEVEL_3"
LEVEL_4 = "LEVEL_4"
LEVEL_5 = "LEVEL_5"
SHIFT_LEAD = "SHIFT_LEAD"
MANAGER = "MANAGER"

WAGE_CENTS = {
    LEVEL_1: 1750,
    LEVEL_2: 1850,
    LEVEL_3: 1975,
    LEVEL_4: 2100,
    LEVEL_5: 2250,
    SHIFT_LEAD: 2500,
    MANAGER: 3200,
}
LEVEL_ORDER = [LEVEL_1, LEVEL_2, LEVEL_3, LEVEL_4, LEVEL_5, SHIFT_LEAD, MANAGER]

TENURE_MIN_DAYS = 180
SHIFT_MIN_ACTIVE = 2
MAX_PROMOTIONS = 6

COVERAGE_CRITICAL_PCT = 0.60
MIN_LEADS = 1

# ─── Standard payloads used across the suite ────────────────────────────────

# A fully populated, compliant quality spec profile (PRD section 3.1).
DEFAULT_SPEC_PROFILE = {
    "lean_point_pct": 80,
    "max_fat_pct": 20,
    "max_bacterial_count_cfu_g": 10000,
    "chilled_never_frozen": True,
}

# Monday..Saturday deliveries, no Sunday routes (index 0 = Monday).
DEFAULT_DELIVERY_DAYS_MASK = [True, True, True, True, True, True, False]

# Reference geography: a commissary at (34.0, -118.0) and a store about
# 1.3 km northeast — comfortably inside any reasonable radius limit.
COMMISSARY_LAT = 34.0
COMMISSARY_LNG = -118.0
STORE_LAT = 34.01
STORE_LNG = -118.01

# Menu items used by the order tests.
MENU_HAMBURGER = {
    "sku": "HAMB",
    "name": "Hamburger",
    "base_price_cents": 350,
    "patty_count": 1,
    "produce_units": 1,
}
MENU_DOUBLE_DOUBLE = {
    "sku": "DBL-DBL",
    "name": "Double-Double",
    "base_price_cents": 495,
    "patty_count": 2,
    "produce_units": 2,
}
