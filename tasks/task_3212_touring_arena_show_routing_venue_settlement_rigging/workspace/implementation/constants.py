"""System-wide constants for the touring-arena-shows API."""
from decimal import Decimal

# Logical clock
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# Holds
HOLD_TTL_HOURS = 72

# Trucks
TRUCKS_PER_DOOR = 2
TRUCK_ARRIVAL_GRACE_HOURS = 2

# Labor / union rules
UNION_CANCEL_NOTICE_HOURS = 24
LATE_CANCEL_FEE_PCT = Decimal("0.25")
UNION_RULES = {
    "IATSE": {"minimum_hours": 4, "ot_threshold": 8, "ot_multiplier": Decimal("1.5")},
    "TEAMSTERS": {"minimum_hours": 5, "ot_threshold": 10, "ot_multiplier": Decimal("1.5")},
    "NON_UNION": {"minimum_hours": 1, "ot_threshold": 8, "ot_multiplier": Decimal("1.25")},
}

# Ticketing
FAMILY_PACK_SIZE = 4

# Rigging
HIGH_RISK_DYNAMIC_KG = 500

# Enums
ROLES = [
    "TourManager", "VenueBooker", "ProductionEngineer", "LaborSteward",
    "BoxOfficeManager", "LicensingManager", "ComplianceOfficer", "PlatformAdmin",
]
ALL_ROLES = list(ROLES)

UNION_RULE_SETS = ["IATSE", "TEAMSTERS", "NON_UNION"]
DEAL_TYPES = ["FLAT_RENT", "PERCENTAGE"]
LABOR_DEPARTMENTS = ["RIGGERS", "LOADERS", "WARDROBE", "ANIMAL_HANDLERS", "ELECTRICS"]
CARGO_KINDS = ["VEHICLES", "ANIMALS", "PROPS", "RIGGING", "WARDROBE"]
INSPECTION_KINDS = ["RIGGING", "PYRO", "ANIMAL", "VEHICLE_STUNT", "ELECTRICAL"]
PERMIT_REQUIRED_KINDS = ["PYRO", "ANIMAL", "VEHICLE_STUNT"]
