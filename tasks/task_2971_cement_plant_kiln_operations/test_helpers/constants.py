"""Business constants, enumerations and worked reference figures taken from the PRD."""

API_PREFIX = "/cement-ops"

# ---------------------------------------------------------------------------
# Roles (PRD §2.1 — spelled exactly as the document spells them)
# ---------------------------------------------------------------------------
ROLE_PLANT_ADMIN = "PlantAdmin"
ROLE_PROCESS_ENGINEER = "ProcessEngineer"
ROLE_KILN_OPERATOR = "KilnOperator"
ROLE_LAB_TECHNICIAN = "LabTechnician"
ROLE_QUALITY_MANAGER = "QualityManager"
ROLE_ENVIRONMENTAL_OFFICER = "EnvironmentalOfficer"
ROLE_LOGISTICS_PLANNER = "LogisticsPlanner"
ROLE_CUSTOMER = "Customer"

INTERNAL_ROLES = (
    ROLE_PLANT_ADMIN,
    ROLE_PROCESS_ENGINEER,
    ROLE_KILN_OPERATOR,
    ROLE_LAB_TECHNICIAN,
    ROLE_QUALITY_MANAGER,
    ROLE_ENVIRONMENTAL_OFFICER,
    ROLE_LOGISTICS_PLANNER,
)
ALL_ROLES = INTERNAL_ROLES + (ROLE_CUSTOMER,)

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
CLOCK_START = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
RAW_MATERIAL_CATEGORIES = ("LIMESTONE", "CLAY", "IRON_ORE", "SAND", "ALT_RAW")
FUEL_CATEGORIES = ("COAL", "PETCOKE", "NATURAL_GAS", "RDF", "TDF", "BIOMASS")
MATERIAL_KINDS = ("CLINKER", "CEMENT")
CEMENT_TYPES = ("TYPE_I", "TYPE_IL", "TYPE_II", "TYPE_III")
TEST_TYPES = ("FREE_LIME", "BLAINE", "COMPRESSIVE_STRENGTH_28D")
OUTAGE_SCOPES = ("REFRACTORY", "MECHANICAL", "COMBINED")
CONTRACT_STATES = ("ACTIVE", "SUSPENDED")

# ---------------------------------------------------------------------------
# Cement type specifications (PRD §2.11 — every bound inclusive)
# ---------------------------------------------------------------------------
CEMENT_TYPE_SPECS = {
    "TYPE_I": {
        "limestone_max_pct": 5.00,
        "so3_max_pct": 3.00,
        "blaine_min_m2_per_kg": 340,
        "blaine_max_m2_per_kg": 420,
        "strength_28d_min_mpa": 28.0,
    },
    "TYPE_IL": {
        "limestone_max_pct": 15.00,
        "so3_max_pct": 3.00,
        "blaine_min_m2_per_kg": 380,
        "blaine_max_m2_per_kg": 460,
        "strength_28d_min_mpa": 28.0,
    },
    "TYPE_II": {
        "limestone_max_pct": 5.00,
        "so3_max_pct": 3.00,
        "blaine_min_m2_per_kg": 320,
        "blaine_max_m2_per_kg": 400,
        "strength_28d_min_mpa": 28.0,
    },
    "TYPE_III": {
        "limestone_max_pct": 5.00,
        "so3_max_pct": 4.50,
        "blaine_min_m2_per_kg": 500,
        "blaine_max_m2_per_kg": 600,
        "strength_28d_min_mpa": 24.0,
    },
}

GYPSUM_MIN_PCT = 2.00
GYPSUM_MAX_PCT = 7.00
SO3_CLINKER_PCT = 0.60
SO3_GYPSUM_PCT = 46.50
SO3_LIMESTONE_PCT = 0.05

# ---------------------------------------------------------------------------
# Pyroprocessing constants (PRD §3.5)
# ---------------------------------------------------------------------------
SHC_TIER_1_MAX_TONNES = 600.00
SHC_TIER_1_SHC = 4.00
SHC_TIER_2_MAX_TONNES = 900.00
SHC_TIER_2_SHC = 3.70
SHC_TIER_3_SHC = 3.45
KILN_FEED_FACTOR = 1.55

# ---------------------------------------------------------------------------
# Chemical module coefficients (PRD §3.1)
# ---------------------------------------------------------------------------
LSF_COEFF_SIO2 = 2.8
LSF_COEFF_AL2O3 = 1.18
LSF_COEFF_FE2O3 = 0.65

# ---------------------------------------------------------------------------
# Emissions and distribution planning
# ---------------------------------------------------------------------------
ROLLING_WINDOW_DAYS = 30
PEAK_SEASON_FACTOR = 1.25
SHOULDER_SEASON_FACTOR = 1.00
OFF_SEASON_FACTOR = 0.70
OFF_SEASON_MONTHS = (12, 1, 2)

MAX_DESIGN_REVISIONS = 3

# ---------------------------------------------------------------------------
# Reference plant profile used by the fixtures
# ---------------------------------------------------------------------------
PLANT_REGION_CODE = "US-MW"
PLANT_PEAK_SEASON_MONTHS = [5, 6, 7, 8, 9]
PLANT_NOX_INTENSITY_CAP = 1.20
PLANT_ANNUAL_NOX_BUDGET_KG = 2000000.00
PLANT_MAX_TSR_PCT = 35.00
PLANT_MAX_CHLORINE_KG_PER_RUN = 500.00
PLANT_FREE_LIME_MAX_PCT = 1.50

# Raw material analyses used by the fixtures (PRD §3.1 worked figures)
LIMESTONE_ANALYSIS = {
    "category": "LIMESTONE",
    "cao_pct": 52.0,
    "sio2_pct": 3.5,
    "al2o3_pct": 1.0,
    "fe2o3_pct": 0.5,
    "so3_pct": 0.05,
    "moisture_pct": 2.0,
    "cost_per_tonne": 8.00,
}
CLAY_ANALYSIS = {
    "category": "CLAY",
    "cao_pct": 1.0,
    "sio2_pct": 60.0,
    "al2o3_pct": 18.0,
    "fe2o3_pct": 7.0,
    "so3_pct": 0.10,
    "moisture_pct": 12.0,
    "cost_per_tonne": 12.00,
}
IRON_ORE_ANALYSIS = {
    "category": "IRON_ORE",
    "cao_pct": 1.0,
    "sio2_pct": 8.0,
    "al2o3_pct": 2.0,
    "fe2o3_pct": 80.0,
    "so3_pct": 0.05,
    "moisture_pct": 5.0,
    "cost_per_tonne": 40.00,
}

# Fuel analyses used by the fixtures (PRD §3.3 worked figures)
NATURAL_GAS_ANALYSIS = {
    "category": "NATURAL_GAS",
    "lhv_gj_per_tonne": 48.00,
    "nox_kg_per_gj": 0.10,
    "co2_kg_per_gj": 56.0,
    "chlorine_pct": 0.00,
}
COAL_ANALYSIS = {
    "category": "COAL",
    "lhv_gj_per_tonne": 27.00,
    "nox_kg_per_gj": 0.35,
    "co2_kg_per_gj": 96.0,
    "chlorine_pct": 0.02,
}
RDF_ANALYSIS = {
    "category": "RDF",
    "lhv_gj_per_tonne": 18.00,
    "nox_kg_per_gj": 0.22,
    "co2_kg_per_gj": 40.0,
    "chlorine_pct": 0.80,
    "is_alternative": True,
}
TDF_ANALYSIS = {
    "category": "TDF",
    "lhv_gj_per_tonne": 30.00,
    "nox_kg_per_gj": 0.18,
    "co2_kg_per_gj": 85.0,
    "chlorine_pct": 0.10,
    "is_alternative": True,
}

# Reference kiln profile
KILN_NOMINAL_SHC = 3.60
KILN_COOLDOWN_BUFFER_HOURS = 12
KILN_RELINE_DUE_HOURS = 4000

# Reference silo profiles
CLINKER_SILO_CAPACITY = 20000.00
CLINKER_SILO_DRAW_RATE = 300.00
CEMENT_SILO_CAPACITY = 8000.00
CEMENT_SILO_DRAW_RATE = 250.00
CEMENT_SILO_SPOUTS = 2

# Worked reference figures for the canonical gas-fired run (45.00 t of natural gas
# through a kiln whose nominal specific heat consumption is 3.60 GJ/t)
GAS_RUN_TONNES = 45.00
GAS_RUN_GROSS_ENERGY_GJ = 2160.00
GAS_RUN_CLINKER_TONNES = 583.78
GAS_RUN_NOX_KG = 216.00
GAS_RUN_INTENSITY = 0.370

# Worked reference figures for the canonical coal-fired run (80.00 t of coal)
COAL_RUN_TONNES = 80.00
COAL_RUN_GROSS_ENERGY_GJ = 2160.00
COAL_RUN_CLINKER_TONNES = 583.78
COAL_RUN_NOX_KG = 756.00
COAL_RUN_INTENSITY = 1.295

# Worked reference figures for the canonical TYPE_IL batch
BATCH_CLINKER_DRAWN = 500.00
BATCH_GYPSUM_PCT = 5.00
BATCH_LIMESTONE_PCT = 8.00
BATCH_TOTAL_TONNES = 574.71
BATCH_GYPSUM_TONNES = 28.74
BATCH_LIMESTONE_TONNES = 45.98
BATCH_CEMENT_TONNES = 574.72
BATCH_SO3_PCT = 2.85
BATCH_BLAINE_TARGET = 400
