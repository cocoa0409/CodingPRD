# All domain constants, each defined exactly once, traced to PRD.md / SCAFFOLD.yaml.
# PRD section references inline.

# --- Logical clock (PRD 2.4) ---
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# --- Volume agreement tiers (PRD 3.2; scaffold order_pricing constants) ---
TIER2_MIN_CENTS = 25000000
TIER3_MIN_CENTS = 75000000

# --- Warranty / parts support horizons (PRD 3.8; scaffold warranty_eligibility) ---
PARTS_WARRANTY_DAYS = 1826
LABOR_WARRANTY_DAYS = 366
MIN_PARTS_SUPPORT_DAYS = 2557  # 7-year parts horizon

# --- Manufacturing queue tiers (PRD 2.8; scaffold configuration_lead_time) ---
QUEUE_DAYS_SMALL_MAX_UNITS = 49
QUEUE_DAYS_SMALL = 3
QUEUE_DAYS_MEDIUM_MAX_UNITS = 199
QUEUE_DAYS_MEDIUM = 7
QUEUE_DAYS_LARGE = 12

# --- Fabric program (PRD 2.7) ---
FABRIC_LEAD_DELTA_DAYS = {"A": 0, "B": 7, "C": 14, "COM": 21}
FABRIC_UPCHARGE_PCT = {"A": 0, "B": 5, "C": 12, "COM": 18}
FABRIC_GRADES = ("A", "B", "C", "COM")

# --- Plants (PRD 2.8) ---
PLANT_DAILY_CAPACITY = {"PLANT_GR": 120, "PLANT_DAL": 80}
TRANSIT_DAYS = {"PLANT_GR": 4, "PLANT_DAL": 6}
PRODUCTION_NOTICE_DAYS = 2
PLANT_CODES = ("PLANT_GR", "PLANT_DAL")

# --- Building logistics (PRD 2.8) ---
FREIGHT_TURN_BUFFER_MIN = 15
ZONE_MAX_CREW = 10
UNION_MIN_CREW = 4

# --- Punch escalation (PRD 3.8; scaffold punch_escalation_age) ---
ESCALATION_BUSINESS_DAYS = 5

# --- Dealer capability gate (PRD 2.7) ---
CAPABILITY_REQUIRED = {"SYSTEMS": 3, "SEATING": 1, "STORAGE": 2}

# --- Pagination (PRD 2.3) ---
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Module catalog (PRD 2.7; scaffold bom_expansion MODULE_BOM_RULES) ---
# module_type -> list of (part_number, qty_per_unit, unit_list_price_cents)
MODULE_BOM_RULES = {
    "WORKSTATION_6X6": [
        ("PN-FRM-66", 1, 41200),
        ("PN-PNL-FAB", 2, 9600),
        ("PN-WRK-SRF", 1, 15800),
        ("PN-PWR-PLR", 1, 7400),
        ("PN-HDW-KIT", 1, 2237),
    ],
    "WORKSTATION_8X8": [
        ("PN-FRM-88", 1, 48900),
        ("PN-PNL-FAB", 3, 9600),
        ("PN-WRK-SRF", 1, 17400),
        ("PN-PWR-PLR", 1, 7400),
        ("PN-HDW-KIT", 1, 2237),
    ],
    "PRIVATE_OFFICE": [
        ("PN-FRM-PO", 1, 92500),
        ("PN-PNL-FAB", 4, 9600),
        ("PN-WRK-SRF", 1, 21500),
        ("PN-DOOR", 1, 18700),
        ("PN-PWR-PLR", 1, 7400),
        ("PN-HDW-KIT", 1, 2237),
    ],
    "STORAGE_WALL": [
        ("PN-CAB-TALL", 1, 34200),
        ("PN-CAB-BASE", 1, 22800),
        ("PN-SHLF", 3, 3100),
    ],
    "TASK_CHAIR_SET": [
        ("PN-CHR-TASK", 4, 25000),
        ("PN-CHR-GUEST", 2, 12500),
    ],
}

MODULE_FAMILY_CATEGORY = {
    "WORKSTATION_6X6": "SYSTEMS",
    "WORKSTATION_8X8": "SYSTEMS",
    "PRIVATE_OFFICE": "SYSTEMS",
    "STORAGE_WALL": "STORAGE",
    "TASK_CHAIR_SET": "SEATING",
}

MODULE_TYPES = tuple(MODULE_BOM_RULES.keys())

# part_number -> unit list price (cents), and part_number -> product category.
# Every catalog part belongs to module types of exactly one category (PRD 2.7).
PART_LIST_PRICE_CENTS = {}
PART_CATEGORY = {}
for _mt, _parts in MODULE_BOM_RULES.items():
    for _pn, _q, _price in _parts:
        PART_LIST_PRICE_CENTS[_pn] = _price
        PART_CATEGORY[_pn] = MODULE_FAMILY_CATEGORY[_mt]
CATALOG_PART_NUMBERS = frozenset(PART_LIST_PRICE_CENTS.keys())

# --- Enums (PRD / scaffold entity tables) ---
ROLES = ("ManufacturerAdmin", "DealerRep", "EndUserRep")
DEALER_STATUSES = ("ACTIVE", "SUSPENDED")
AGREEMENT_STATUSES = ("DRAFT", "ACTIVE", "EXPIRED")
FAMILY_CATEGORIES = ("SYSTEMS", "SEATING", "STORAGE")
LIFECYCLE_STATUSES = ("CURRENT", "SUNSETTING", "DISCONTINUED")
SPEC_STATUSES = ("DRAFT", "LOCKED")
ORDER_STATUSES = ("DRAFT", "SUBMITTED", "ON_HOLD", "ACKNOWLEDGED", "CLOSED", "CANCELLED")
LOGISTICS_STATUSES = ("PLANNED", "SCHEDULED", "DELIVERED", "CANCELLED")
INSTALL_STATUSES = ("NOT_STARTED", "IN_PROGRESS", "COMPLETE", "CANCELLED")
WINDOW_STATUSES = ("RESERVED", "CANCELLED")
PUNCH_SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
PUNCH_STATUSES = ("OPEN", "RESOLVED", "VERIFIED", "VOID")
CLAIM_TYPES = ("PARTS", "LABOR")
CLAIM_STATUSES = ("SUBMITTED", "APPROVED", "DENIED")
VERIFY_OUTCOMES = ("CONFIRMED", "REJECTED")
REVIEW_DECISIONS = ("APPROVE", "DENY")
