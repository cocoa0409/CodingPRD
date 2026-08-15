"""Domain constants from PRD.md / SCAFFOLD.yaml calculations and enum sets."""

from decimal import Decimal

ROLES = [
    "OrderingPhysician",
    "BloodBankTechnologist",
    "BloodBankSupervisor",
    "SupplierCoordinator",
    "QualityOfficer",
]

PRODUCT_TYPES = ["RBC", "WHOLE_BLOOD", "PLT_APHERESIS", "PLT_POOL", "FFP", "CRYO"]
RBC_CLASS = {"RBC", "WHOLE_BLOOD"}
PLASMA_CLASS = {"PLT_APHERESIS", "PLT_POOL", "FFP", "CRYO"}
ABO_TYPES = ["O", "A", "B", "AB"]
RH_TYPES = ["POS", "NEG"]
SPECIAL_REQUIREMENTS = ["IRRADIATED", "CMV_NEGATIVE", "WASHED"]
ANTIGENS = ["K", "k", "C", "c", "E", "e", "Jka", "Jkb", "Fya", "Fyb", "S", "s"]

REACTION_TYPES = [
    "FEBRILE_NON_HEMOLYTIC", "ALLERGIC_MILD", "ALLERGIC_ANAPHYLAXIS",
    "HEMOLYTIC_ACUTE", "HEMOLYTIC_DELAYED", "TRALI", "TACO", "SEPTIC", "OTHER",
]
SEVERITIES = ["MILD", "MODERATE", "SEVERE", "LIFE_THREATENING"]
SEVERE_REACTION_TYPES = {"HEMOLYTIC_ACUTE", "TRALI", "SEPTIC"}

URGENCIES = ["ROUTINE", "URGENT", "EMERGENCY"]

UNIT_STATUSES = [
    "QUARANTINED", "AVAILABLE", "RESERVED", "ISSUED", "TRANSFUSED",
    "EXPIRED", "DISCARDED", "REJECTED", "RETURNED_TO_SUPPLIER", "QUARANTINED_HOLD",
]
HOLD_REASONS = ["REACTION_PRECAUTION", "RECALL", "SUPPLIER_SUSPENSION"]

WASTAGE_REASONS = [
    "EXPIRED", "RETURNED_OVER_30MIN", "RETURNED_COMPROMISED",
    "PARTIAL_TRANSFUSION", "REACTION_INVESTIGATION", "RECALL_DESTRUCTION", "MANUAL",
]

# --- calculations.unit_expiration_at_receive ---
CLASS_SHELF_HOURS = {
    "RBC": 1008, "WHOLE_BLOOD": 840, "PLT_APHERESIS": 120,
    "PLT_POOL": 120, "FFP": 8760, "CRYO": 8760,
}
THAWED_FFP_HOURS = 24
THAWED_CRYO_HOURS = 6
POOLED_PLT_HOURS = 4

# --- calculations.supplier_order_estimated_cost ---
PRICE_CENTS = {
    "RBC": 21997, "WHOLE_BLOOD": 34995, "PLT_APHERESIS": 54995,
    "PLT_POOL": 47995, "FFP": 7995, "CRYO": 6495,
}
TIER2_QTY = 50
TIER1_QTY = 20
DISCOUNT_TIER2 = Decimal("0.10")
DISCOUNT_TIER1 = Decimal("0.05")
EMERGENCY_SURCHARGE = Decimal("1.25")

# --- time windows ---
TS_VALIDITY_HOURS = 72
XM_HOLD_HOURS = 72
TRANSFUSION_START_WINDOW_HOURS = 4
EMERGENCY_ACK_WINDOW_HOURS = 24
RETURN_RESTOCK_WINDOW_MINUTES = 30
COOLER_REDISPATCH_BUFFER_MINUTES = 60
MAX_CHECKOUT_DURATION_HOURS = 12
DEFAULT_MIN_SHELF_HOURS = 4
INBOUND_HORIZON_HOURS = 24

# --- calculations.rolling_wastage_rate ---
WASTAGE_WINDOW_DAYS = 30
EXCESSIVE_RATE = Decimal("0.05")
RATE_SCALE = Decimal("0.0001")

# --- calculations.unit_compatibility_decision (ABO matrices) ---
ABO_RBC_ALLOWED = {
    "O": {"O"},
    "A": {"O", "A"},
    "B": {"O", "B"},
    "AB": {"O", "A", "B", "AB"},
}
ABO_PLASMA_ALLOWED = {
    "O": {"O", "A", "B", "AB"},
    "A": {"A", "AB"},
    "B": {"B", "AB"},
    "AB": {"AB"},
}
ALLOW_EMERGENCY_RH_MISMATCH = True

# --- calculations.mtp_pack_constitution ---
PACK_SPEC = [("RBC", 4), ("FFP", 2), ("PLT_APHERESIS", 1)]

POSTURES = ["NORMAL", "WATCH", "SHORTAGE", "CRITICAL"]
