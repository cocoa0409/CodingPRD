"""Domain thresholds and test defaults drawn from the PRD computations."""
from datetime import datetime, timedelta, timezone

# Logical clock origin — the service starts its clock here (PRD §2.5).
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# Canonical posture ladder (PRD §3.2) as fractions, not percentages.
POSTURE_LADDER_DEFAULT = {
    "SLIP_RELEASE_AT": 0.02,
    "SLIP_RECOVERY_AT": 0.05,
    "SLIP_HOLD_AT": 0.10,
    "SLIP_FREEZE_AT": 0.15,
}

# Revision cost impact constants (PRD §3.7).
REVISION_SCOPE_DIVISOR = 4
KLUDGE_RATE_PER_HOUR_CENTS = 8500
NEGOTIATED_RATE_PER_HOUR_CENTS = 7800
SUBMITTED_MARKUP_PCT = 0.18

# Craft / capacity constants (PRD §3.2, §3.3).
INSTALL_PRODUCTIVITY_FLOOR = 0.40
RACK_STAGING_DURATION_FACTOR = 3
RACK_CAPACITY_MARGIN = 0.95

# Shop capacity ladder (PRD §3.3).
SHOP_CAPACITY_LADDER = [(0.85, 1.0), (1.00, 1.2), (float("inf"), 1.5)]

# Stage window table: clash slots and trade count per distribution stage (PRD §3.3).
STAGE_WINDOW = {
    "FIRST_STAGE": {"clash_slots": 4, "trade_count": 2},
    "SECOND_STAGE": {"clash_slots": 3, "trade_count": 1},
    "TRIM_OUT": {"clash_slots": 2, "trade_count": 0},
}

# Idle weight ladder (PRD §3.8).
IDLE_WEIGHT_LADDER = [(0.70, 0.85), (0.85, 0.75), (float("inf"), 0.60)]

# Effective flow factor (PRD §3.8).
EFFECTIVE_FLOW_FACTOR_HIGH = 11
EFFECTIVE_FLOW_FACTOR_LOW = 16

# Apprentice upgrade contract hours — the strict greater-than threshold (PRD §3.6).
APPLICABLE_CONTRACT_HOURS = 8000.0
SAFETY_VERIFICATION_DAYS = 90

# A-STRAP reference assembly used by the empty-set fixtures.
DEFAULT_ASSEMBLY = {
    "assembly_code": "A-RACK",
    "assembly_kind": "RACK",
    "unit_of_measure": "LINEAR_FEET",
    "prefab_hours_per_unit": 2.0,
    "field_hours_per_unit": 3.0,
    "supported_field_hours_per_unit": 3.0,
    "field_productivity_factor": 1.0,
    "ideal_conduit_type_codes": ["RC50", "RC75"],
    "conduit_labor_factors": {"RIGID_RACK": 1.0, "MC_CABLE": 1.0},
    "material_price_cents": 4200,
    "core_charge_cents": 150,
    "recycled_credit_cents": 75,
    "is_switchgear": False,
}

STRAP_ASSEMBLY = dict(
    DEFAULT_ASSEMBLY,
    assembly_code="A-STRAP",
    assembly_kind="DEVICE_STRAP",
    unit_of_measure="EACH",
    ideal_conduit_type_codes=["MC12"],
    conduit_labor_factors={"MC_CABLE": 1.0},
)

# Labor-agreement rate effective date used when building rate rows (PRD §3.6).
# Kept as a module-level name because factories import it directly.
RATE_EFFECTIVE_FROM_ISO = "2026-01-01T00:00:00Z"

TEST_DEFAULTS = {
    "JURISDICTION": "J1",
    "POWER_ON_ISO": "2026-12-01T00:00:00Z",
    "PLANNED_VALUE_CENTS": 100_000_000,
    "TOTAL_QUANTITY": 100,
    "LAYDOWN_SLOTS": 2,
    "SHOP_UTILIZATION_PCT": 0.50,
    "FLOAT_BAND_LOW_PCT": 0.10,
    "BURDEN_PCT": 0.42,
    "JOURNEYMAN_RATE_CENTS": 6800,
    "RATE_EFFECTIVE_FROM_ISO": "2026-01-01T00:00:00Z",
    "WORK_DATE_ISO": "2026-10-01T00:00:00Z",
    "REQUIRED_ON_SITE_ISO": "2026-11-20T00:00:00Z",
    "INSTALL_WINDOW_START_ISO": "2026-11-21T00:00:00Z",
    "RACK_HOIST_DATE_ISO": "2026-11-15T00:00:00Z",
    "RACK_CAPACITY_CF": 400.0,
    "MATERIAL_PLANNED_RELEASE_ISO": "2026-10-15T00:00:00Z",
}

NON_EXISTENT_ID = "00000000-0000-4000-8000-000000000000"


def shift_iso(iso: str, days: int) -> str:
    """Return `iso` shifted by whole days, keeping the same UTC formatting."""
    base = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (base + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")