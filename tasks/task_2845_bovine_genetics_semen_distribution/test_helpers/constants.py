"""Domain constants taken directly from the PRD.

Every literal here is quoted from the contract: role names, enum members, the
pinned calculation coefficients of PRD 2.8 / 3.6 / 3.8 / 3.9, the base health
assay list of PRD 2.9 and the default logical clock of PRD 2.5.
"""

# --------------------------------------------------------------------- roles
ROLE_PROGRAM_DIRECTOR = "ProgramDirector"
ROLE_FACILITY_MANAGER = "FacilityManager"
ROLE_STAFF_VETERINARIAN = "StaffVeterinarian"
ROLE_LAB_TECHNICIAN = "LabTechnician"
ROLE_EXPORT_COORDINATOR = "ExportCoordinator"
ROLE_DISTRIBUTOR = "Distributor"
ROLE_BREEDING_ADVISOR = "BreedingAdvisor"

ALL_ROLES = (
    ROLE_PROGRAM_DIRECTOR,
    ROLE_FACILITY_MANAGER,
    ROLE_STAFF_VETERINARIAN,
    ROLE_LAB_TECHNICIAN,
    ROLE_EXPORT_COORDINATOR,
    ROLE_DISTRIBUTOR,
    ROLE_BREEDING_ADVISOR,
)

# --------------------------------------------------------------- logical clock
# PRD 2.5: "At server startup the logical clock is set to exactly
# 2026-08-01T00:00:00Z."
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
SECONDS_PER_DAY = 86400

# ------------------------------------------------------------------ pagination
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# ----------------------------------------------------------------------- enums
BREEDS = ("HOLSTEIN", "JERSEY", "ANGUS")

ACQUISITION_STATUSES = ("PROSPECT", "CONTRACTED", "RESIDENT", "RETIRED")
COLLECTION_STATUSES = (
    "NOT_HOUSED",
    "ISOLATION",
    "ELIGIBLE",
    "SUSPENDED",
    "WITHDRAWN",
)
SUSPENSION_REASONS = (
    "MANUAL",
    "POSITIVE_TEST_RESULT",
    "REQUIRED_TEST_EXPIRED",
    "FACILITY_SUSPENDED",
)

FACILITY_STATUSES = ("APPROVED", "SUSPENDED")

TEST_TYPES = (
    "BLUETONGUE",
    "IBR",
    "BVD",
    "TRICHOMONIASIS",
    "EBL",
    "BRUCELLOSIS",
)
# PRD 2.9: the four base required assays.
REQUIRED_BASE_TEST_TYPES = ("BLUETONGUE", "IBR", "BVD", "TRICHOMONIASIS")
NON_BASE_TEST_TYPES = ("EBL", "BRUCELLOSIS")
TEST_RESULTS = ("PENDING", "NEGATIVE", "POSITIVE", "INCONCLUSIVE", "EXPIRED")

BOOKING_STATUSES = ("SCHEDULED", "CANCELLED", "VOIDED", "COMPLETED")
BOOKING_VOID_REASONS = ("SIRE_SUSPENDED", "FACILITY_SUSPENDED")

EJACULATE_QC_STATUSES = ("PENDING_QC", "ACCEPTED", "REJECTED")
QC_VERDICTS = ("ACCEPTED", "REJECTED")

PRODUCT_LINES = ("CONVENTIONAL", "SEXED", "EMBRYO")
LOT_STATUSES = ("QUARANTINE", "RELEASED", "REJECTED", "DEPLETED")
VALUATION_BASES = ("STANDARD_COST", "MARKET_REVALUED")

EVALUATION_STATUSES = ("DRAFT", "PUBLISHED", "SUPERSEDED", "ROLLED_BACK")
EVALUATION_BASES = ("GENOMIC_ONLY", "PROGENY_BLENDED")

CERTIFICATE_STATUSES = ("DRAFT", "SUBMITTED", "ISSUED", "REJECTED", "REVOKED")
CERTIFICATE_REVOKE_REASONS = ("SIRE_SUSPENDED", "LOT_REJECTED")

TANK_STATUSES = ("IN_SERVICE", "SERVICE_DUE", "OUT_OF_SERVICE")

TRANSFER_STATUSES = (
    "REQUESTED",
    "APPROVED",
    "IN_TRANSIT",
    "RECEIVED",
    "RECONCILED",
    "REJECTED",
    "RETURNED",
)

RECOMMENDATION_STATUSES = ("PROPOSED", "ACCEPTED", "WITHDRAWN")
RECOMMENDATION_DECISIONS = ("ACCEPTED", "WITHDRAWN")

# ------------------------------------------------------- genetic index (3.6)
W_MILK = 0.02
W_FAT = 0.60
W_PROTEIN = 0.80
W_SCS = 8.0
SCS_BASELINE = 3.00
W_FERT = 6.0
W_LONG = 1.5
SHRINK_MIN = 0.30
SHRINK_MAX = 0.95
PROGENY_BLEND_MIN = 50
PAW_BASE = 0.50
PAW_SLOPE = 0.004
PAW_CAP_DAUGHTERS = 100
PAW_FLOOR = 0.10
W_PROD_BLEND = 0.60
W_HEALTH_BLEND = 0.40

# ------------------------------------------------- lot market basis (3.6)
BASE_CENTS_PER_INDEX_POINT = 45
PRODUCT_MULTIPLIER = {"CONVENTIONAL": 1.00, "SEXED": 1.85, "EMBRYO": 3.40}
SEXED_PURITY_REF_PCT = 90.0
MARKET_FLOOR_CENTS = 800

# ------------------------------------------------------ ejaculate yield (3.4)
DOSE_SPERM_MILLIONS = 15

# ---------------------------------------------------- QC thresholds (3.5)
QC_MIN_POST_THAW_MOTILITY_PCT = 35.0
QC_MIN_MORPHOLOGY_NORMAL_PCT = 70.0

# -------------------------------------------------------- settlement (3.8)
LN2_SERVICE_FEE_CENTS = 12000
REBATE_TIERS = ((0, 0.00), (500000, 0.03), (1500000, 0.06))

# --------------------------------------------------------- tank decay (3.8)
LN2_DECAY_PCT_PER_DAY = 2.0
LN2_SERVICE_DUE_PCT = 25.0
TANK_DEFAULT_SERVICE_INTERVAL_DAYS = 60
TANK_DEFAULT_INITIAL_FILL_PCT = 95.0

# ------------------------------------------------- breeding advisory (3.9)
PEDIGREE_MAX_DEPTH = 3
BASE_CR = {"CONVENTIONAL": 0.60, "SEXED": 0.48, "EMBRYO": 0.42}
INDEX_BONUS_PER_POINT = 0.0004
INBREEDING_PENALTY_PER_PCT = 0.012
CR_FLOOR = 0.2000
CR_CEILING = 0.7500
HERD_DEFAULT_MAX_INBREEDING_PCT = 6.25
HERD_MAX_INBREEDING_CEILING = 25

# ------------------------------------------------------------ export (3.7)
MAX_SUBMISSION_ROUNDS = 3
PLANT_COUNTRY_CODE = "US"

# ---------------------------------------------------------- sexing purity
SEXING_PURITY_MIN_PCT = 50.0
SEXING_PURITY_MAX_PCT = 99.9
