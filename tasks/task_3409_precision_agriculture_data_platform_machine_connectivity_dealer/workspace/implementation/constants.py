"""Named constants, each defined exactly once with the PRD/scaffold value."""

from decimal import Decimal

# Data plan tiers (PRD section 2.6)
TIER_PRICE_CENTS = {"BASIC": 30000, "STANDARD": 60000, "UNLIMITED": 120000}
TIER_CAP_MB = {"BASIC": 5120, "STANDARD": 20480, "UNLIMITED": None}
THROTTLE_AT_RATIO = Decimal("0.8")
EXHAUST_AT_RATIO = Decimal("1.0")

# Uptime prediction (calculations.uptime_prediction)
UPTIME_WINDOW_HOURS = 720

# Parts recommendation (calculations.parts_recommendation)
OVERHAUL_BELOW_PCT = Decimal("70.0")
SERVICE_BELOW_PCT = Decimal("85.0")

# Prescription totals (calculations.prescription_product_totals)
ZONE_QTY_DECIMALS = 2
AVG_RATE_DECIMALS = 3

# Warranty payout waterfall (calculations.warranty_payout_allocation)
AGE_FULL_COVER_MAX_MONTHS = 24
AGE_PARTIAL_COVER_MAX_MONTHS = 60
LABOR_CAP_CENTS = {"STANDARD": 500000, "PREMIUM": 900000}
PAYOUT_MAX_CENTS = 2000000
COVERAGE_FULL = Decimal("0.90")
COVERAGE_PARTIAL = Decimal("0.70")
COVERAGE_OLD = Decimal("0.50")

# License bundle fee (calculations.license_bundle_fee)
LICENSE_BASE_FEE_CENTS = {
    "AUTO_GUIDANCE": 120000,
    "SECTION_CONTROL": 180000,
    "VARIABLE_RATE_SPREAD": 90000,
    "TELEMATICS_PREMIUM": 60000,
}
BUNDLE_DISCOUNT_2 = Decimal("0.1")
BUNDLE_DISCOUNT_3_PLUS = Decimal("0.2")

# Warranty data coverage gate (calculations.warranty_data_coverage)
WARRANTY_MIN_COVERAGE_PCT = Decimal("90.0")

# Modem provisioning (calculations.provisioning_attempt_gate)
PROVISIONING_MAX_ATTEMPTS = 5

# Time-driven expiry sweep (calculations.time_driven_expiry_sweep)
CONSENT_TTL_HOURS = 72
CERT_VALIDITY_DAYS = 365

# Roles (PRD section 2.1)
ROLES = {
    "GrowerManager",
    "DealerTechnician",
    "IndependentTechnician",
    "Agronomist",
    "CoopAnalyst",
    "PartnerApp",
    "PlatformAdmin",
    "System",
}

# Grantee type -> caller role mapping (PRD section 2.1)
GRANTEE_TO_ROLE = {
    "AGRONOMIST": "Agronomist",
    "COOPERATIVE": "CoopAnalyst",
    "DEALER": "DealerTechnician",
    "THIRD_PARTY_APP": "PartnerApp",
}
ROLE_TO_GRANTEE = {v: k for k, v in GRANTEE_TO_ROLE.items()}

# Data scopes (PRD section 3.4)
SCOPES = {"TELEMATICS", "AGRONOMIC", "DIAGNOSTICS"}
