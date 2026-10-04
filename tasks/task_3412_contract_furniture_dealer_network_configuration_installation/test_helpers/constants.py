"""Domain constants — every value traces to a PRD.md sentence.

Line references below point at workspace/PRD.md (the contract the
implementer reads). No value here is invented or remembered.
"""

# --- Logical clock ---------------------------------------------------------
# PRD §2.4: "Before any clock-setting call has been made, the logical clock
# reads exactly 2026-09-01T00:00:00Z."
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-09-01"

# --- Module catalog / BOM (PRD §2.7, the five bullet lines) -----------------
# Each entry: part_number -> (qty_per_unit, unit_list_price_cents).
MODULE_BOM_RULES = {
    # PRD §2.7: WORKSTATION_6X6 — 85837 cents of parts per module unit.
    "WORKSTATION_6X6": {
        "PN-FRM-66": (1, 41200),
        "PN-PNL-FAB": (2, 9600),
        "PN-WRK-SRF": (1, 15800),
        "PN-PWR-PLR": (1, 7400),
        "PN-HDW-KIT": (1, 2237),
    },
    # PRD §2.7: WORKSTATION_8X8 — 104737 cents per module unit.
    "WORKSTATION_8X8": {
        "PN-FRM-88": (1, 48900),
        "PN-PNL-FAB": (3, 9600),
        "PN-WRK-SRF": (1, 17400),
        "PN-PWR-PLR": (1, 7400),
        "PN-HDW-KIT": (1, 2237),
    },
    # PRD §2.7: PRIVATE_OFFICE — 180737 cents per module unit.
    "PRIVATE_OFFICE": {
        "PN-FRM-PO": (1, 92500),
        "PN-PNL-FAB": (4, 9600),
        "PN-WRK-SRF": (1, 21500),
        "PN-DOOR": (1, 18700),
        "PN-PWR-PLR": (1, 7400),
        "PN-HDW-KIT": (1, 2237),
    },
    # PRD §2.7: STORAGE_WALL — 66300 cents per module unit; fabric must be absent.
    "STORAGE_WALL": {
        "PN-CAB-TALL": (1, 34200),
        "PN-CAB-BASE": (1, 22800),
        "PN-SHLF": (3, 3100),
    },
    # PRD §2.7: TASK_CHAIR_SET — 125000 cents per module unit.
    "TASK_CHAIR_SET": {
        "PN-CHR-TASK": (4, 25000),
        "PN-CHR-GUEST": (2, 12500),
    },
}

# PRD §2.7: "WORKSTATION_6X6, WORKSTATION_8X8, and PRIVATE_OFFICE are SYSTEMS
# modules; STORAGE_WALL is a STORAGE module; TASK_CHAIR_SET is a SEATING module."
MODULE_CATEGORY = {
    "WORKSTATION_6X6": "SYSTEMS",
    "WORKSTATION_8X8": "SYSTEMS",
    "PRIVATE_OFFICE": "SYSTEMS",
    "STORAGE_WALL": "STORAGE",
    "TASK_CHAIR_SET": "SEATING",
}

# Every catalog part number (valid for punch part_number / PARTS claims).
ALL_PART_NUMBERS = sorted(
    {pn for rule in MODULE_BOM_RULES.values() for pn in rule}
)

# --- Fabric program (PRD §2.7) ----------------------------------------------
# PRD §2.7: "A adds 0 days, B adds 7 days, C adds 14 days, and COM adds 21
# days; STORAGE modules carry no fabric and use a delta of 0."
FABRIC_LEAD_DELTA_DAYS = {"A": 0, "B": 7, "C": 14, "COM": 21}
STORAGE_FABRIC_DELTA_DAYS = 0

# PRD §2.7: "A upcharges 0 percent, B 5 percent, C 12 percent, and COM 18
# percent; STORAGE modules are upcharged at 0 percent."
FABRIC_UPCHARGE_PCT = {"A": 0, "B": 5, "C": 12, "COM": 18}
STORAGE_FABRIC_UPCHARGE_PCT = 0

# --- Dealer capability gates (PRD §2.7) --------------------------------------
# PRD §2.7: "SYSTEMS modules require level 3, SEATING modules require level 1,
# and STORAGE modules require level 2."
CAPABILITY_REQUIRED = {"SYSTEMS": 3, "SEATING": 1, "STORAGE": 2}

# --- Manufacturing / logistics (PRD §2.8) ------------------------------------
# PRD §2.8: "PLANT_GR with a daily capacity of 120 units and PLANT_DAL with a
# daily capacity of 80 units."
PLANT_DAILY_CAPACITY = {"PLANT_GR": 120, "PLANT_DAL": 80}

# PRD §2.8: "transit from plant to site takes 4 calendar days from PLANT_GR
# and 6 calendar days from PLANT_DAL."
TRANSIT_DAYS = {"PLANT_GR": 4, "PLANT_DAL": 6}

# PRD §2.8: "a phase's production date must be at least 2 calendar days after
# the current clock date."
PRODUCTION_NOTICE_DAYS = 2

# PRD §2.8: "3 queue days when the configuration totals at most 49 units, 7
# queue days when it totals at least 50 and at most 199 units, and 12 queue
# days when it totals 200 units or more."
QUEUE_SMALL_MAX_UNITS = 49
QUEUE_MEDIUM_MAX_UNITS = 199
QUEUE_DAYS_SMALL = 3
QUEUE_DAYS_MEDIUM = 7
QUEUE_DAYS_LARGE = 12

# PRD §2.8: "A freight-elevator reservation carries a 15-minute turnover
# buffer on each side of the reserved interval."
FREIGHT_TURN_BUFFER_MIN = 15

# PRD §2.8: "A building zone's installer pool supports an aggregate of at most
# 10 crew members per calendar date across overlapping reserved windows."
ZONE_MAX_CREW = 10

# PRD §2.8: "Any window booked under union labor rules requires a crew of at
# least 4 installers."
UNION_MIN_CREW = 4

# --- Volume tiers (PRD §3.2) -------------------------------------------------
# PRD §3.2: "tier 1 while cumulative_volume_cents is less than 25000000, tier 2
# once it is at least 25000000 but less than 75000000, and tier 3 once it
# reaches 75000000."
TIER2_MIN_CENTS = 25000000
TIER3_MIN_CENTS = 75000000

# --- Warranty / parts support (PRD §3.8, §3.3) --------------------------------
# PRD §3.8: "A PARTS claim is eligible only while its filed_date is on or
# before actual_install_complete_date plus 1826 days; a LABOR claim only while
# its filed_date is on or before actual_install_complete_date plus 366 days."
PARTS_WARRANTY_DAYS = 1826
LABOR_WARRANTY_DAYS = 366

# PRD §3.3: "a parts_support_until date at least 2557 days after the current
# clock date — the seven-year parts horizon."
MIN_PARTS_SUPPORT_DAYS = 2557

# --- Punch escalation (PRD §3.8) ----------------------------------------------
# PRD §3.8: "at least 5 business days have elapsed strictly after the ticket's
# creation calendar date ... a business age of exactly 5 escalates."
ESCALATION_BUSINESS_DAYS = 5

# --- Pagination (PRD §2.3) ----------------------------------------------------
# PRD §2.3: "The limit parameter defaults to 10, with a minimum of 1 and a
# maximum of 100; the offset parameter defaults to 0."
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
