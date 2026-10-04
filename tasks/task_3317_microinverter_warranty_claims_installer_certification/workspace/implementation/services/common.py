"""Shared constants, exact-money helpers and the derived-field recomputations.

Every rounding rule here comes from PRD 2.9 and the calculation tables: money is
integer cents rounded half-up, ratios carry four decimals, percentages two.
"""

from decimal import Decimal, ROUND_HALF_UP

import db
from errors import fail
from respond import (
    CLOCK,
    add_months,
    iso,
    new_id,
    new_request_id,
    now_iso,
    parse_iso,
    supersede_updated_at,
    whole_months_between,
)

# --------------------------------------------------------------------- constants

CERT_TERM_MONTHS = 36
BASE_TERM_MONTHS = 300
MAX_REPLACEMENT_RATIO = Decimal("0.50")
REPLACEMENT_EXT_THRESHOLD = Decimal("0.30")
FULL_EXTENSION_MONTHS = 120
PARTIAL_EXTENSION_MONTHS = 60
REPLACEMENT_LIMIT_PER_SYSTEM = 5

MICRO_AC_WATTS = 350
MAX_DC_AC_RATIO = Decimal("1.50")

UNDERPERFORMANCE_RATIO = Decimal("0.95")
FAILURE_STREAK_HOURS = 24

DEFAULT_DEFECT_THRESHOLD_PCT = Decimal("5.0")
WATCH_BAND_DIVISOR = Decimal("2")
LOT_TRAILING_WINDOW_DAYS = 90
LOT_RECALL_MIN_UNITS = 10

LABOR_EXTENDED_MONTHS = 120
CLAIMS_FOR_LEVEL_UP = 100
CLAIM_RATE_FLOOR_PCT = Decimal("0.00")

METERING_BASE_RATE_CENTS = 250
METERING_FREE_MONTHS = 60
ENTITLEMENT_MONTHS = 3
RECONCILIATION_TOLERANCE_BPS = 500

LEVELS = ["CERTIFIED", "GOLD", "PLATINUM"]
LEVEL_BASE_RATE_CENTS = {"CERTIFIED": 7500, "GOLD": 8500, "PLATINUM": 9500}
LEVEL_FACTOR = {
    "CERTIFIED": Decimal("1.00"),
    "GOLD": Decimal("1.10"),
    "PLATINUM": Decimal("1.25"),
}
LEVEL_CAP_HOURS = {
    "CERTIFIED": Decimal("2.0"),
    "GOLD": Decimal("4.0"),
    "PLATINUM": Decimal("6.0"),
}
DIAGNOSTIC_FEE_CENTS_BY_LEVEL = {
    "CERTIFIED": 6500,
    "GOLD": 8500,
    "PLATINUM": 12500,
}

AGE_BAND_1_MONTHS = 60
AGE_BAND_2_MONTHS = 120
AGE_BAND_3_MONTHS = 144
AGE_FACTOR_BAND_1 = Decimal("1.000")
AGE_FACTOR_BAND_2 = Decimal("0.750")
AGE_FACTOR_BAND_3 = Decimal("0.375")
AGE_FACTOR_BAND_4 = Decimal("0.000")

GEN1_MODELS = ("IQ7", "IQ7X_DISCONTINUED")
GEN2_MODELS = ("IQ8", "IQ8HC")
# Every generation is still serviceable except the retired one: an IQ7 unit is
# promoted to IQ8 rather than left unreplaceable.
SUPPORTABLE_MODELS = ("IQ7", "IQ8", "IQ8HC")
DISCONTINUED_MODEL = "IQ7X_DISCONTINUED"

UNIT_MODELS = ("IQ7", "IQ8", "IQ8HC", "IQ7X_DISCONTINUED")
CLAIM_KINDS = ("DEFECT", "UNDERPERFORMANCE", "NO_POWER", "COMMUNICATION")
TRANSFER_KINDS = ("SALE", "INHERITANCE", "FORECLOSURE")

# ----------------------------------------------------------------- rounding


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def money(value):
    """Round a cents amount half-up to a whole number of cents."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ratio4(value):
    """Four decimal places, round half-up (PRD 2.9)."""
    return float(dec(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def pct2(value):
    """Two decimal places, round half-up (PRD 2.9)."""
    return float(dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def hours2(value):
    return float(dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def bps(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------- clock helpers


def now():
    return CLOCK.now()


def age_factor_for_months(age_months):
    """The single age-band table shared by labor and metering (PRD 3.8/3.4)."""
    if age_months <= AGE_BAND_1_MONTHS:
        return AGE_FACTOR_BAND_1
    if age_months <= AGE_BAND_2_MONTHS:
        return AGE_FACTOR_BAND_2
    if age_months <= AGE_BAND_3_MONTHS:
        return AGE_FACTOR_BAND_3
    return AGE_FACTOR_BAND_4


def system_age_months(system, at):
    """Whole months from warranty_start_at to `at`."""
    if not system or not system.get("warranty_start_at"):
        return 0
    return whole_months_between(parse_iso(system["warranty_start_at"]), at)


# --------------------------------------------------------------- change tracking


def set_many(record, values, bump=True):
    """Write derived fields, touching updated_at only on a real change."""
    changed = False
    for key, value in values.items():
        if record.get(key) != value:
            record[key] = value
            changed = True
    if changed and bump:
        supersede_updated_at(record)
    return changed


def touch(record):
    """Explicit mutation marker for the audited entities."""
    supersede_updated_at(record)


# ------------------------------------------------------------ unit recomputation


def installed_orders_of_system(system_id):
    return [o for o in db.DB.replacement_orders.values()
            if o.get("status") == "INSTALLED" and _unit_system_id(o.get("unit_id")) == system_id]


def _unit_system_id(unit_id):
    unit = db.DB.units.get(unit_id)
    return unit.get("system_id") if unit else None


def system_unit_count(system_id):
    """Units on the system that are not DECOMMISSIONED -- the ratio denominator."""
    return len([u for u in db.DB.units.values()
                if u.get("system_id") == system_id
                and u.get("commissioning_state") != "DECOMMISSIONED"])


def replacement_window_position(system_id):
    """Five unscheduled slots, less one per replacement installed on the system."""
    used = len(installed_orders_of_system(system_id))
    return max(0, REPLACEMENT_LIMIT_PER_SYSTEM - used)


def recompute_unit(unit):
    """Recompute every derived flag on a Unit and return whether anything moved."""
    system = db.DB.systems.get(unit.get("system_id"))
    lot = db.DB.production_lots.get(unit.get("production_lot_id")) if unit.get("production_lot_id") else None
    supportable = unit.get("model_code") in SUPPORTABLE_MODELS
    status = unit.get("monitored_status")

    # PRD 3.3 counts the INSTALLED replacement orders that targeted the unit's
    # position; PRD 3.7 adds that recording a billed-replacement entitlement also
    # increments the count.  An entitlement reserves one position, and installing
    # the order that reservation created is the same position, so it is counted
    # once -- not once for the reservation and again for the install.
    replacement_count = 0
    for order in db.DB.replacement_orders.values():
        if order.get("unit_id") != unit.get("id"):
            continue
        if order.get("status") == "INSTALLED":
            replacement_count += 1
    for entitlement in db.DB.entitlements.values():
        if entitlement.get("unit_id") != unit.get("id"):
            continue
        reservation = db.DB.replacement_orders.get(entitlement.get("reservation_order_id"))
        if reservation is None or reservation.get("status") != "INSTALLED":
            replacement_count += 1
    return set_many(unit, {
        "rma_eligible": bool(
            status == "FAILED"
            and system is not None
            and system.get("warranty_status") == "ACTIVE"
            and supportable
        ),
        "campaign_eligible": bool(
            status in ("ONLINE", "UNDERPERFORMING")
            and lot is not None
            and lot.get("lot_status") == "RECALL"
        ),
        "retired_generation": unit.get("model_code") == DISCONTINUED_MODEL,
        "direct_replacement_unsupported": bool(
            status in ("ONLINE", "UNDERPERFORMING")
            and unit.get("model_code") == DISCONTINUED_MODEL
        ),
        "replacement_count": replacement_count,
        "replacement_window_position": replacement_window_position(unit.get("system_id")),
    })


def recompute_units_of_system(system_id):
    for unit in db.DB.units.values():
        if unit.get("system_id") == system_id:
            recompute_unit(unit)


def recompute_units_of_lot(lot_id):
    for unit in db.DB.units.values():
        if unit.get("production_lot_id") == lot_id:
            recompute_unit(unit)


# ------------------------------------------------------------- system coverage


def coverage_figures(system):
    """compute_warranty_coverage, steps 1..5, in the fixed order (PRD 3.3)."""
    start = parse_iso(system["warranty_start_at"])
    base_end = add_months(start, BASE_TERM_MONTHS)
    unit_count = system_unit_count(system["id"])

    installed_in_base = 0
    for order in db.DB.replacement_orders.values():
        if order.get("status") != "INSTALLED":
            continue
        if _unit_system_id(order.get("unit_id")) != system["id"]:
            continue
        installed_at = order.get("installed_at")
        if installed_at is None:
            continue
        if parse_iso(installed_at) <= base_end:
            installed_in_base += 1

    if unit_count == 0:
        ratio = Decimal(0)
    else:
        ratio = dec(installed_in_base) / dec(unit_count)

    if ratio >= MAX_REPLACEMENT_RATIO:
        extension_months = 0
    elif ratio >= REPLACEMENT_EXT_THRESHOLD:
        extension_months = PARTIAL_EXTENSION_MONTHS
    else:
        extension_months = FULL_EXTENSION_MONTHS

    extended_end = add_months(base_end, extension_months)
    return {
        "warranty_start_at": iso(start),
        "base_warranty_end_at": iso(base_end),
        "extended_warranty_end_at": iso(extended_end),
        "extension_months": extension_months,
        "replacement_ratio": ratio4(ratio),
        "unit_count": unit_count,
        "coverage_window": {
            "start_at": iso(start),
            "end_at": iso(extended_end),
        },
        "installed_in_base_count": installed_in_base,
    }


def recompute_system(system):
    figures = coverage_figures(system)
    figures.pop("installed_in_base_count", None)
    return set_many(system, figures)


# ---------------------------------------------------------- installer rollups


def labor_totals(installer_id):
    approved = 0
    reversed_total = 0
    paid = 0
    for row in db.DB.reimbursements.values():
        if row.get("installer_id") != installer_id:
            continue
        status = row.get("status")
        amount = int(row.get("net_amount_cents") or 0)
        if status in ("APPROVED", "PAID"):
            approved += amount
        if status == "PAID":
            paid += amount
        if row.get("reversed"):
            reversed_total += amount
    return approved, reversed_total, paid


def decided_claims(installer_id):
    return [c for c in db.DB.claims.values()
            if c.get("installer_id") == installer_id and c.get("status") in ("APPROVED", "DENIED")]


def claim_approval_rate_pct(installer_id):
    decided = decided_claims(installer_id)
    if not decided:
        return 100.00
    approved = len([c for c in decided if c.get("status") == "APPROVED"])
    return pct2(dec(approved) * dec(100) / dec(len(decided)))


def active_system_count(installer_id):
    return len([s for s in db.DB.systems.values()
                if s.get("installer_id") == installer_id
                and s.get("warranty_status") in ("ACTIVE", "TRANSFERRED")])


def completed_design_count(installer_id):
    """Design projects that are finished enough to unlock commissioning."""
    return len([p for p in db.DB.design_projects.values()
                if p.get("installer_id") == installer_id
                and p.get("status") == "APPROVED"])


def recompute_installer(installer):
    status = installer.get("certification_status")
    level = installer.get("certification_level")
    approved, reversed_total, paid = labor_totals(installer["id"])
    return set_many(installer, {
        "certification_level": level,
        "certification_status": status,
        "design_tool_enabled": bool(status == "ACTIVE" and level in ("GOLD", "PLATINUM")),
        "commissioning_enabled": bool(
            status == "ACTIVE" and completed_design_count(installer["id"]) >= 1
        ),
        "active_system_count": active_system_count(installer["id"]),
        "claim_approval_rate_pct": claim_approval_rate_pct(installer["id"]),
        "labor_approved_cents_total": approved,
        "labor_reversed_cents_total": reversed_total,
        "labor_paid_cents_total": paid,
    })


def lazy_installer(installer):
    """Lazy certification expiry on read (PRD 3.1)."""
    if installer.get("certification_status") == "ACTIVE":
        certified_until = installer.get("certified_until")
        if certified_until and now() > parse_iso(certified_until):
            set_many(installer, {
                "certification_status": "EXPIRED",
                "design_tool_enabled": False,
                "commissioning_enabled": False,
            })
    recompute_installer(installer)
    return installer


def require_active_certification(installer):
    """Priority 8: the installer's certification must be ACTIVE."""
    if installer.get("certification_status") != "ACTIVE":
        fail("ERR_INSTALLER_NOT_CERTIFIED")


def require_certification_not_expired(installer):
    """Priority 28: certified_until must be strictly after the logical clock.

    The comparison reads the raw stored instant rather than the lazily derived
    status, so an installer whose stored status is still ACTIVE but whose term
    has passed is reported as expired (PRD 2.6).
    """
    certified_until = installer.get("certified_until")
    if certified_until is None:
        return
    if not now() < parse_iso(certified_until):
        fail("ERR_CERTIFICATION_EXPIRED")


def gate_certification(installer):
    """The ACTIVE check followed by the raw-term expiry check (PRD 3.6)."""
    require_active_certification(installer)
    require_certification_not_expired(installer)


def commissioning_enabled_for(installer):
    """ACTIVE certification plus at least one completed design project."""
    if installer.get("certification_status") != "ACTIVE":
        return False
    return completed_design_count(installer["id"]) >= 1


def require_commissioning_enabled(installer):
    if not commissioning_enabled_for(installer):
        fail("ERR_COMMISSIONING_NOT_ENABLED")