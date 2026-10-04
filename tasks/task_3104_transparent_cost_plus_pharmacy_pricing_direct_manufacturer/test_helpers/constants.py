"""Domain thresholds and test defaults for the cost-plus pharmacy API.

All money is integer cents.
"""

# ─── Order pricing constants ──────────────────────────
MARKUP_RATE = 0.15
PHARMACY_FEE_CENTS = 800
SHIPPING_FEE_CENTS = 500
FREE_SHIPPING_THRESHOLD_CENTS = 1500

# ─── Shipment interval constants ──────────────────────
BASE_A_DAYS = 7
BASE_B_DAYS = 14
BASE_C_DAYS = 21
ADJ_UNITS_GE_200 = -7
ADJ_UNITS_GE_50 = 0
ADJ_UNITS_LT_50 = 14

# ─── Expansion score constants ────────────────────────
EXPANSION_GATE_MIN_SCORE = 2
SUPPLY_TIGHT_MULTIPLIER = 2
SUPPLY_BAND_MULTIPLIER = 10

# ─── Carrier slot constants ───────────────────────────
SLOT_CAPACITY = 2
QUARANTINE_BUFFER_DAYS = 1

# ─── Demand window constants ──────────────────────────
DEMAND_WINDOW_DAYS = 30
STALE_DEADLINE_DAYS = 30

THRESHOLDS = {
    "MARKUP_RATE": MARKUP_RATE,
    "PHARMACY_FEE_CENTS": PHARMACY_FEE_CENTS,
    "SHIPPING_FEE_CENTS": SHIPPING_FEE_CENTS,
    "FREE_SHIPPING_THRESHOLD_CENTS": FREE_SHIPPING_THRESHOLD_CENTS,
    "BASE_A_DAYS": BASE_A_DAYS,
    "BASE_B_DAYS": BASE_B_DAYS,
    "BASE_C_DAYS": BASE_C_DAYS,
    "ADJ_UNITS_GE_200": ADJ_UNITS_GE_200,
    "ADJ_UNITS_GE_50": ADJ_UNITS_GE_50,
    "ADJ_UNITS_LT_50": ADJ_UNITS_LT_50,
    "EXPANSION_GATE_MIN_SCORE": EXPANSION_GATE_MIN_SCORE,
    "SUPPLY_TIGHT_MULTIPLIER": SUPPLY_TIGHT_MULTIPLIER,
    "SUPPLY_BAND_MULTIPLIER": SUPPLY_BAND_MULTIPLIER,
    "SLOT_CAPACITY": SLOT_CAPACITY,
    "QUARANTINE_BUFFER_DAYS": QUARANTINE_BUFFER_DAYS,
    "DEMAND_WINDOW_DAYS": DEMAND_WINDOW_DAYS,
    "STALE_DEADLINE_DAYS": STALE_DEADLINE_DAYS,
}

# ─── The logical clock ────────────────────────────────
# The system's startup default instant. Every time-gated rule resolves
# against whatever instant the clock has been explicitly set to.
CLOCK_START = "2026-09-01T00:00:00Z"

# Pre-created substantiation deadlines used across the suite.
FAR_FUTURE = "2027-09-01T00:00:00Z"

TEST_DEFAULTS = {
    "drug_name": "Metformin HCL",
    "strength": "500MG",
    "dosage_form": "Tablet",
    "retail_reference_price_cents": 4200,
    "insured_reference_price_cents": 3600,
    "pharmacy_name": "Sunbelt Mail Pharmacy",
    "domicile_state_code": "TX",
    "ship_state_code": "CA",
    "patient_name": "Ada Reyes",
    "patient_email": "ada@example.com",
    "prescriber_name": "Dr. Lin",
    "prescriber_npi": "1407001234",
    "license_number": "CA-MP-1001",
    "unit_cost_cents": 12,
    "available_units": 600,
}