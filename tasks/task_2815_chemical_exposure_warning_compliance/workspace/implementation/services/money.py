"""The settlement money waterfall (PRD 3.8) - penalty, then cap, then fees."""
from util import D, rhu, floor_cents, whole_days_between
import db
from services import calc

FEE_REQUEST_CEILING_CENTS = 5000000
PER_DAY_CENTS = D(250000)
PER_UNIT_CENTS = D(500)
WARRANTY_FACTOR = D("0.60")
CURE_FACTOR = D("0.50")
REFORMULATION_FACTOR = D("0.75")
MITIGATION_FLOOR = D("0.25")
MITIGATION_DP = 4
STATE_SHARE = D("0.75")
SETTLEMENT_ROUND_CEILING = 3
QUIET_PERIOD_DAYS = 1095

SCOPE_COVERS = {
    "ALL_MATERIALS": ("RAW_MATERIAL", "PACKAGING", "MANUFACTURING_AID"),
    "RAW_MATERIAL_ONLY": ("RAW_MATERIAL",),
    "PACKAGING_ONLY": ("PACKAGING",),
}


def warranty_window_covers(supplier, instant):
    """Warranty coverage is HALF-OPEN: [from, to)."""
    start = supplier.get("warranty_effective_from")
    end = supplier.get("warranty_effective_to")
    if start is None or instant < start:
        return False
    if end is not None and not instant < end:
        return False
    return True


def scope_covers(supplier, material):
    scope = supplier.get("warranty_scope")
    if scope is None:
        return False
    return material.get("material_class") in SCOPE_COVERS.get(scope, ())


def supplier_qualifies(supplier, material, instant, require_pass_through=True):
    if supplier is None or supplier.get("warranty_status") != "ACTIVE":
        return False
    if not warranty_window_covers(supplier, instant):
        return False
    if not scope_covers(supplier, material):
        return False
    if require_pass_through and not supplier.get("pass_through_warning_obligation"):
        return False
    return True


def warranty_defence_holds(product, instant):
    """Every ACTIVE component's supplier must qualify; an empty product never does."""
    components = calc.active_components(product["id"])
    if not components:
        return False
    for component in components:
        material = db.get("materials", component["material_id"])
        if material is None:
            return False
        supplier = db.get("suppliers", material.get("supplier_id"))
        if not supplier_qualifies(supplier, material, instant):
            return False
    return True


def available_indemnity_cents(product):
    """Summed cap of every supplier with an ACTIVE warranty behind the product."""
    seen = set()
    total = 0
    for component in calc.active_components(product["id"]):
        material = db.get("materials", component["material_id"])
        if material is None:
            continue
        supplier = db.get("suppliers", material.get("supplier_id"))
        if supplier is None or supplier.get("warranty_status") != "ACTIVE":
            continue
        if supplier["id"] in seen:
            continue
        seen.add(supplier["id"])
        total += int(supplier.get("indemnity_cap_cents") or 0)
    return total


def violation_days(notice):
    return whole_days_between(notice["earliest_violation_date"], db.now())


def base_penalty(notice, days):
    day_measure = PER_DAY_CENTS * D(days)
    unit_measure = PER_UNIT_CENTS * D(notice.get("alleged_units") or 0)
    return int(min(day_measure, unit_measure))


def cure_branch_taken(notice):
    return bool(notice.get("cure_attempted")) or notice.get("cure_completed_at") is not None


def mitigation_factor(settlement, notice, product):
    factor = D(1)
    warranty_applied = warranty_defence_holds(product, notice["served_at"])
    if warranty_applied:
        factor = factor * WARRANTY_FACTOR
    if cure_branch_taken(notice):
        factor = factor * CURE_FACTOR
    if settlement.get("reformulation_commitment"):
        factor = factor * REFORMULATION_FACTOR
    factor = max(factor, MITIGATION_FLOOR)
    return rhu(factor, MITIGATION_DP), warranty_applied


def fee_cap(adjusted):
    value = D(adjusted)
    if value < D(100000):
        return floor_cents(value * D("1.50"))
    if value < D(1000000):
        return floor_cents(value * D("1.00"))
    return floor_cents(value * D("0.60"))


def recompute_from_mitigation(settlement, notice, product):
    """Steps three through eight, in the pinned order."""
    factor, warranty_applied = mitigation_factor(settlement, notice, product)
    settlement["mitigation_factor"] = factor
    settlement["_warranty_applied"] = warranty_applied
    adjusted = int(rhu(D(settlement["base_penalty_cents"]) * factor, 0))
    settlement["adjusted_penalty_cents"] = adjusted
    cap = fee_cap(adjusted)
    settlement["fee_cap_cents"] = cap
    allowed = min(int(settlement["requested_attorney_fees_cents"]), cap)
    settlement["allowed_fees_cents"] = allowed
    state_share = floor_cents(D(adjusted) * STATE_SHARE)
    settlement["state_share_cents"] = state_share
    settlement["noticing_party_share_cents"] = adjusted - state_share
    settlement["total_settlement_cents"] = adjusted + allowed
    return settlement


def compute_at_create(settlement, notice, product, days):
    settlement["violation_days"] = days
    settlement["base_penalty_cents"] = base_penalty(notice, days)
    return recompute_from_mitigation(settlement, notice, product)


def quiet_period_settlement_exists(notice):
    """An EXECUTED settlement on the same product and chemical inside the window."""
    from util import days as day_delta
    window_start = notice["served_at"] - day_delta(QUIET_PERIOD_DAYS)
    for other in db.rows("notices"):
        if other["product_id"] != notice["product_id"] or \
                other["chemical_id"] != notice["chemical_id"]:
            continue
        for settlement in calc.settlements_of(other["id"]):
            if settlement["status"] != "EXECUTED":
                continue
            executed_at = settlement.get("executed_at")
            if executed_at is None:
                continue
            if window_start <= executed_at <= notice["served_at"]:
                return True
    return False
