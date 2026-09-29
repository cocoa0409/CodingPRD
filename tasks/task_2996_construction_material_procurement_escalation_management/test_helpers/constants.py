"""Domain thresholds and shared literals drawn from the PRD's own rules."""

# ─── Logical clock (PRD §2.5) ─────────────────────────────────────────────
# "Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z".
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00.000Z"

# ─── Numeric thresholds named in the PRD ──────────────────────────────────
THRESHOLDS = {
    # §3.1 release-for-fabrication schedule
    "LONG_LEAD_THRESHOLD_DAYS": 90,
    "RFF_CRITICAL_FLOAT_DAYS": 0,
    "RFF_AT_RISK_MAX_FLOAT_DAYS": 14,
    "RFF_ON_TRACK_MIN_FLOAT_DAYS": 15,
    "DEFAULT_SUBMITTAL_REVIEW_DAYS": 21,
    # §3.2 supplier exposure
    "TARIFF_WEIGHT": 1.6,
    "TARIFF_COMPONENT_CAP": 40,
    "EVENT_WEIGHT": 20,
    "EVENT_COMPONENT_CAP": 40,
    "NON_DOMESTIC_PENALTY": 20,
    "EXPOSURE_HIGH_THRESHOLD": 60,
    "EXPOSURE_ELEVATED_THRESHOLD": 30,
    # §3.3 price holds
    "MIN_PRICE_HOLD_DAYS": 1,
    "MAX_PRICE_HOLD_DAYS": 120,
    # §3.4 negotiation
    "MAX_NEGOTIATION_ROUNDS": 3,
    "DEFAULT_DEADBAND_PCT": 2.0,
    "MAX_CAP_PCT": 25,
    "MAX_DEADBAND_PCT": 20,
    # §3.5 fiscal ceiling
    "MAX_BUYOUT_OVERRUN_PCT": 15,
    # §3.7 storage
    "INSURANCE_RATE_PCT": 0.0175,
    "HANDLING_BUFFER_DAYS": 3,
    "MANDATORY_DOC_TYPE_COUNT": 3,
    "MAX_MONTHLY_STORAGE_RATE_PCT": 5,
    # §3.8 substitutions
    "MAX_SUBSTITUTION_REVISION_ROUNDS": 2,
    "MAX_ABS_COST_DELTA": 5000000,
    "MAX_ABS_SCHEDULE_DELTA_DAYS": 180,
    # §3.9 change-order admin fee tiers
    "SMALL_CLAIM_FEE_PCT": 5.0,
    "MID_CLAIM_FEE_PCT": 3.5,
    "LARGE_CLAIM_FEE_PCT": 2.0,
    "FEE_TIER_1_CEILING": 10000.00,
    "FEE_TIER_2_CEILING": 50000.00,
    # §2.3 pagination
    "DEFAULT_PAGE_LIMIT": 10,
    "MIN_PAGE_LIMIT": 1,
    "MAX_PAGE_LIMIT": 100,
}

MANDATORY_DOC_TYPES = ["BAILMENT_AGREEMENT", "INSURANCE_CERTIFICATE", "LIEN_WAIVER"]

# ─── Default fixture literals (all format-legal per the PRD) ──────────────
TEST_DEFAULTS = {
    "PROJECT_NAME": "Riverside Medical Tower",
    "CONTRACT_NUMBER": "GC-2996-A",
    "OWNER_NAME": "Riverside Health System",
    "SCHEDULE_DATA_DATE": "2026-08-01T00:00:00.000Z",
    "CONTINGENCY_BUDGET": 500000.00,
    "SCOPE_CODE": "STRUCT-STEEL-01",
    "PACKAGE_DESCRIPTION": "Structural steel frame package",
    "COMMODITY_INDEX_CODE": "PPI_STEEL_MILL",
    "ESTIMATED_COST": 1200000.00,
    "REQUIRED_ONSITE_DATE": "2027-03-01T00:00:00.000Z",
    "FABRICATION_DURATION_DAYS": 70,
    "DELIVERY_TRANSIT_DAYS": 20,
    "SUBMITTAL_REVIEW_DAYS": 21,
    "SUPPLIER_NAME": "Ironworks Fabricators LLC",
    "COUNTRY_OF_ORIGIN": "US",
    "DECLARED_TARIFF_RATE_PCT": 0.00,
    "BASE_PRICE": 1150000.00,
    "RECEIVED_AT": "2026-08-01T00:00:00.000Z",
    "PRICE_HOLD_DAYS": 45,
    "PO_NUMBER": "PO-2996-0001",
    "CAP_PCT": 8.0,
    "CONTRACTOR_SHARE_PCT": 40.0,
    "DEADBAND_PCT": 2.0,
    "PRICE_HOLD_THROUGH": "2026-09-15T00:00:00.000Z",
    "PROPOSED_TERMS_NOTE": "Mill index escalation with 2 pct deadband and shared band",
    "WAREHOUSE_NAME": "Harbor Yard 7",
    "WAREHOUSE_ADDRESS": "1400 Harbor Industrial Way, Tacoma WA",
    "MONTHLY_STORAGE_RATE_PCT": 0.1875,
    "SUBSTITUTION_PRODUCT": "Alternate mill-certified plate assembly",
    "CHANGE_ORDER_NARRATIVE": (
        "Documented mill index escalation on the structural steel buyout, substantiated "
        "against the published PPI reading for the delivery month."
    ),
}

# Published PPI_STEEL_MILL readings used across the escalation fixtures.
STEEL_READINGS = [
    ("2026-07", 310.00),
    ("2026-08", 322.00),
    ("2026-09", 331.00),
    ("2026-12", 344.50),
]
