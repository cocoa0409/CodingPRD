"""Business calculations (SCAFFOLD Table 3) and cross-entity cascades.

All money is integer cents. Energy/duration quantities use Decimal with
round-half-up at the precision the PRD pins (2dp capacities, 4dp RTE).
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

import db
from util import parse_dt, clock_dt, stamp_for_clock, touch, new_id, now_iso

TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")
CENT = Decimal("1")

SPARE_PARTS_POOL_PCT = Decimal("0.30")
AUGMENTATION_PENALTY = Decimal("0.005")
AUGMENTATION_CAPACITY_FLOOR_MWH = Decimal("80")

DEGRADATION = {
    "ENERGY_ARBITRAGE": {
        "ONE_CYCLE_DAILY": Decimal("0.0006"),
        "TWO_CYCLES_DAILY": Decimal("0.0012"),
        "CONTINUOUS": Decimal("0.0015"),
    },
    "FREQUENCY_REGULATION": {
        "ONE_CYCLE_DAILY": Decimal("0.0004"),
        "TWO_CYCLES_DAILY": Decimal("0.0008"),
        "CONTINUOUS": Decimal("0.0010"),
    },
    "CAPACITY_FIRMING": {
        "ONE_CYCLE_DAILY": Decimal("0.0005"),
        "TWO_CYCLES_DAILY": Decimal("0.0010"),
        "CONTINUOUS": Decimal("0.0012"),
    },
}


def D(x):
    return Decimal(str(x))


def r2(x):
    return D(x).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def r4(x):
    return D(x).quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def as_float2(dec):
    """Render a 2dp Decimal as a JSON float."""
    return float(dec)


# ---------------------------------------------------------------- sizing
def compute_duration_hours(rated_energy_mwh, rated_power_mw):
    return D(rated_energy_mwh) / D(rated_power_mw)


def compute_sizing_status(market_application, duty_cycle_profile, duration_hours_unrounded):
    duration = duration_hours_unrounded.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    if market_application == "CAPACITY_FIRMING":
        ok = duration >= Decimal("4.00") and duty_cycle_profile == "ONE_CYCLE_DAILY"
    elif market_application == "FREQUENCY_REGULATION":
        ok = duty_cycle_profile == "CONTINUOUS"
    else:  # ENERGY_ARBITRAGE
        ok = duration >= Decimal("2.00") and duty_cycle_profile != "CONTINUOUS"
    return "VALID" if ok else "INVALID"


# ------------------------------------------------------------- projection
def recompute_projection(project):
    """augmentation_requirement: projected capacity from commissioned baseline,
    EXECUTED augmentation events, degradation, and the planning penalty."""
    commissioned = D(project.get("commissioned_capacity_mwh") or 0)
    executed_added = Decimal(0)
    executed_count = 0
    for ev in db.augmentations.values():
        if ev["project_id"] == project["id"] and ev["status"] == "EXECUTED":
            executed_added += D(ev["added_capacity_mwh"])
            executed_count += 1
    rate = DEGRADATION[project["market_application"]][project["duty_cycle_profile"]]
    cycles = Decimal(project.get("equivalent_cycles") or 0)
    before_penalty = commissioned + executed_added - rate * cycles
    penalty = (
        Decimal(executed_count)
        * AUGMENTATION_PENALTY
        * max(Decimal(0), before_penalty - AUGMENTATION_CAPACITY_FLOOR_MWH)
    )
    projected = (before_penalty - penalty).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    project["projected_capacity_mwh"] = as_float2(projected)


def recompute_augmentation_count(project):
    count = 0
    for ev in db.augmentations.values():
        if ev["project_id"] == project["id"] and ev["status"] in ("PLANNED", "EXECUTED"):
            count += 1
    project["augmentation_count"] = count


# ------------------------------------------------------ liquidated damages
def whole_days_late(planned_iso, actual_iso):
    """Whole calendar days after planned up to and including actual; any
    crossing into a new calendar day counts as a full day; 0 when on time."""
    p = parse_dt(planned_iso)
    a = parse_dt(actual_iso)
    if a <= p:
        return 0
    delta_seconds = Decimal(str((a - p).total_seconds()))
    days = delta_seconds / Decimal(86400)
    return int(days.to_integral_value(rounding=ROUND_CEILING))


def apply_liquidated_damages(esa, days_late):
    """Cap-aware LD accrual for a MISSED milestone. Returns ld_applied_cents."""
    rate = esa["ld_rate_per_day_cents"]
    headroom = esa["ld_cap_cents"] - esa["accrued_ld_cents"]
    if rate == 0:
        effective_days = 0
    else:
        effective_days = min(days_late, headroom // rate)
        if effective_days < 0:
            effective_days = 0
    ld_applied = effective_days * rate
    esa["accrued_ld_cents"] += ld_applied
    esa["net_ld_due_cents"] = esa["accrued_ld_cents"] - esa["waived_ld_cents"]
    return ld_applied


# ------------------------------------------------------------ ESA cascade
def terminate_esa(esa):
    """EXECUTED -> TERMINATED with full cascade (accrued LD reached cap)."""
    esa["status"] = "TERMINATED"
    touch(esa)
    # Cascade 1: every still-SCHEDULED milestone -> CANCELLED
    for m in db.milestones.values():
        if m["esa_id"] == esa["id"] and m["status"] == "SCHEDULED":
            m["status"] = "CANCELLED"
            touch(m)
    # Cascade 3: claims in SUBMITTED or UNDER_REVIEW -> REJECTED
    claim_ids_of_esa = set()
    for c in db.claims.values():
        if c["esa_id"] == esa["id"]:
            claim_ids_of_esa.add(c["id"])
            if c["status"] in ("SUBMITTED", "UNDER_REVIEW"):
                c["status"] = "REJECTED"
                touch(c)
    # Cascade 2: ORDERED spare-part orders linked to claims of this ESA -> CANCELLED
    for o in db.orders.values():
        if (
            o.get("warranty_claim_id") in claim_ids_of_esa
            and o.get("warranty_claim_id")
            and o["status"] == "ORDERED"
        ):
            o["status"] = "CANCELLED"
            if o.get("covered_by_credit"):
                ltsa = db.ltsas.get(o["service_agreement_id"])
                if ltsa is not None:
                    ltsa["credit_drawn_cents"] -= o["part_cost_cents"]
                    touch(ltsa)
            touch(o)


# ------------------------------------------------------------- lazy expiry
def expire_ltsa(ltsa):
    """ACTIVE/SUSPENDED -> EXPIRED with spare-part cascade."""
    ltsa["status"] = "EXPIRED"
    for o in db.orders.values():
        if o["service_agreement_id"] == ltsa["id"] and o["status"] in ("ORDERED", "SHIPPED"):
            o["status"] = "CANCELLED"
            if o.get("covered_by_credit"):
                ltsa["credit_drawn_cents"] -= o["part_cost_cents"]
            touch(o)
    touch(ltsa)


def lazy_expire_ltsa(ltsa):
    """Flip an ACTIVE/SUSPENDED agreement to EXPIRED when the logical clock is
    past its end_date. Returns True when expiry fired."""
    if ltsa["status"] in ("ACTIVE", "SUSPENDED"):
        end = parse_dt(ltsa["end_date"])
        if clock_dt() > end:
            expire_ltsa(ltsa)
            return True
    return False


# ----------------------------------------------------------- auto augment
def create_auto_augmentation(project, esa, evaluated_capacity_mwh):
    """On CAPACITY_TEST FAIL: auto AugmentationEvent (origin AUTO, PLANNED)
    sized with the 1/(1-penalty) gross-up, window [clock, clock+30d)."""
    guaranteed = D(esa["guaranteed_capacity_mwh"])
    projected = D(project.get("projected_capacity_mwh") or 0)
    evaluated = D(evaluated_capacity_mwh)
    shortfall = guaranteed - min(projected, evaluated)
    if shortfall < 0:
        shortfall = Decimal(0)
    grossed = shortfall / (Decimal(1) - AUGMENTATION_PENALTY)
    added = (grossed * 100).to_integral_value(rounding=ROUND_CEILING) / Decimal(100)
    now = clock_dt()
    end = now + timedelta(days=30)
    ts = now_iso()
    event = {
        "id": new_id(),
        "project_id": project["id"],
        "planned_window_start": stamp_for_clock(now),
        "planned_window_end": stamp_for_clock(end),
        "added_capacity_mwh": float(added),
        "origin": "AUTO",
        "status": "PLANNED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.augmentations[event["id"]] = event
    recompute_augmentation_count(project)
    recompute_projection(project)
    touch(project)
    return event


# -------------------------------------------------------- spare-part pool
def compute_credit_pool(annual_fee_cents):
    return int((Decimal(annual_fee_cents) * SPARE_PARTS_POOL_PCT).to_integral_value(rounding=ROUND_FLOOR))


# -------------------------------------------------------- warranty credit
def compute_warranty_credit(variant, claimed_loss_mwh, esa, throughput_mwh=None):
    """Exact arithmetic, single final rounding to integer cents."""
    price = Decimal(esa["price_per_mwh_cents"])
    loss = D(claimed_loss_mwh)
    if variant == "STRAIGHT_LINE":
        raw = loss * price
        return int(raw.to_integral_value(rounding=ROUND_CEILING))
    # OUTPUT_BASED
    rte = D(esa["guaranteed_rte_pct"])
    degradation_rate = Decimal(1) - rte
    raw = loss * D(throughput_mwh) * rte * price * degradation_rate
    return int(raw.quantize(CENT, rounding=ROUND_HALF_UP))


# -------------------------------------------------------------- dispatch
def compute_cleared_mwh(session, project):
    """dispatch_optimization clearing step: price floor before capacity cap."""
    clearing_price = session["clearing_price_cents_per_mwh"]
    offer_price = session["offer_price_cents_per_mwh"]
    if clearing_price < offer_price:
        return Decimal("0.00")
    projected = D(project.get("projected_capacity_mwh") or 0)
    market_cleared = D(session["market_cleared_mwh"])
    capacity_cap = min(projected, market_cleared)
    cleared = min(D(session["offer_mwh"]), capacity_cap)
    return cleared.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def compute_revenue_cents(cleared_mwh, clearing_price_cents_per_mwh):
    raw = D(cleared_mwh) * Decimal(clearing_price_cents_per_mwh)
    return int(raw.quantize(CENT, rounding=ROUND_HALF_UP))


# ------------------------------------------------------------ RTE / tests
def compute_measured_rte(rte_intervals):
    total_discharge = sum(D(iv["discharge_mwh"]) for iv in rte_intervals)
    total_charge = sum(D(iv["charge_mwh"]) for iv in rte_intervals)
    return (total_discharge / total_charge).quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def compute_evaluated_capacity(test, project):
    measured = D(test["measured_capacity_mwh"])
    if test["measurement_basis"] == "POI":
        measured -= D(test["aux_load_mwh"])
    return measured.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def active_esa_for_project(project_id):
    """The project's ESA in EXECUTED or COMPLETED status, if any."""
    for esa in db.esas.values():
        if esa["project_id"] == project_id and esa["status"] in ("EXECUTED", "COMPLETED"):
            return esa
    return None
