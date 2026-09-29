"""
Domain constants: the named catalogue figures, thresholds and multipliers of the
specification under test.

Every value here is quoted from the specification. Tests import these names rather
than restating literals, so that a threshold change is a one-line edit and so that
the provenance of each magic number is visible in one place.
"""

# ── The logical clock ────────────────────────────────
# "Before any client sets it, the logical clock reads exactly 2026-08-01T00:00:00Z".
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ── Pagination ───────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── Basis points ─────────────────────────────────────
# "a basis-point figure is always divided by 10000 to obtain the multiplier".
BP_DENOMINATOR = 10000

# ── Units and precision ──────────────────────────────
POWER_ENERGY_DECIMALS = 2
RATIO_DECIMALS = 4

# ── The model catalogue (§2.11) ──────────────────────
# usable kWh per unit, continuous kW per unit, maximum units in one bank,
# and the minimum firmware the model requires.
MODEL_CATALOG = {
    "PWX_A": {
        "usable_kwh_per_unit": 13.5,
        "continuous_kw_per_unit": 5.0,
        "max_units": 10,
        "min_firmware": "24.4.0",
        "gateway_family": "GW2",
    },
    "PWX_B": {
        "usable_kwh_per_unit": 13.5,
        "continuous_kw_per_unit": 11.5,
        "max_units": 4,
        "min_firmware": "25.2.0",
        "gateway_family": "GW3",
    },
    "PWX_C": {
        "usable_kwh_per_unit": 11.9,
        "continuous_kw_per_unit": 4.6,
        "max_units": 12,
        "min_firmware": "24.4.0",
        "gateway_family": "GW2",
    },
}

# "The GW2_HOME inverter belongs to gateway family GW2 and the GW3_HOME inverter
# belongs to gateway family GW3."
GATEWAY_FAMILY = {"GW2_HOME": "GW2", "GW3_HOME": "GW3"}

# A model code that is not in the catalogue, for the certification-coverage probes.
UNCERTIFIED_MODEL_CODE = "PWX_D"

# ── Load sizing (§3.2) ───────────────────────────────
LIGHTING_VA_PER_SQFT = 3
DEMAND_FIRST_TIER_VA = 3000
DEMAND_REMAINDER_FACTOR = 0.40
MEASURED_HEADROOM_FACTOR = 1.25
WHOLE_HOME_SURGE_FACTOR = 1.75
ESSENTIAL_TOP_CIRCUIT_COUNT = 2
ESSENTIAL_REMAINDER_FACTOR = 0.50
MOTOR_INRUSH_FACTOR = 3.0
ESSENTIAL_SURGE_CONTINUOUS_FACTOR = 0.25
VA_PER_KW = 1000

# ── Site (§3.1) ──────────────────────────────────────
SERVICE_PANEL_AMPS_CHOICES = [100, 125, 200, 400]
MAX_COMPANY_NAME_LENGTH = 120

# ── Permitting (§3.4) ────────────────────────────────
# "an authority may only request further corrections while correction_round_count
# is still below 3, so the fourth request is rejected".
PERMIT_CORRECTION_LIMIT = 3

# ── Commissioning (§3.6) ─────────────────────────────
BACKUP_TRANSITION_MAX_MS = 200
ANTI_ISLANDING_MAX_MS = 2000
CAPACITY_DISCHARGE_MIN_RATIO = 0.90
# "Both sides of every window are padded by 30 minutes of travel buffer".
TEST_TRAVEL_BUFFER_MINUTES = 30
REQUIRED_TEST_TYPE_COUNT = 4

# ── Warranty (§3.6) ──────────────────────────────────
# "The deadline is commissioned_at plus 30 days and the boundary is inclusive".
WARRANTY_REGISTRATION_GRACE_DAYS = 30

# ── Incentives (§3.7) ────────────────────────────────
# "7500 basis points for NON_EXPORT, 9000 basis points for LIMITED_EXPORT,
# and 10000 basis points for FULL_EXPORT".
EXPORT_MULTIPLIER_BP = {
    "NON_EXPORT": 7500,
    "LIMITED_EXPORT": 9000,
    "FULL_EXPORT": 10000,
}
MIN_STACK_PCT_BP = 1
MAX_STACK_PCT_BP = 10000
# "the third hop fires when that installer's clawback_count is 2 or more".
CLAWBACK_SUSPENSION_THRESHOLD = 2

# ── BYOD dispatch (§3.9) ─────────────────────────────
# "the aggregate target_kw of time-overlapping events in the same territory_code
# may not exceed 1500 kW at any instant".
TERRITORY_CAPACITY_CAP_KW = 1500
MIN_RESERVE_SOC_PCT = 0
MAX_RESERVE_SOC_PCT = 50
# "The event multiplier is 12500 basis points when the event's event_type is
# EMERGENCY and 10000 basis points otherwise."
EVENT_MULTIPLIER_BP = {"ECONOMIC": 10000, "EMERGENCY": 12500}
SHORTFALL_RATIO_FLOOR = 0.80
SHORTFALL_PENALTY_FACTOR = 0.50
BONUS_TIER_HIGH_RATIO = 0.95
BONUS_TIER_HIGH_BP = 1000
BONUS_TIER_LOW_RATIO = 0.85
BONUS_TIER_LOW_BP = 500
