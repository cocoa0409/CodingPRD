"""Business services: calculations, cascades, and time-based auto-transitions."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from db import DB, _parse_iso

ESCALATION = {"PPI_1413": 1.031, "CPI_U": 1.024}
TIER1_QTY = 5
TIER2_QTY = 20
WARRANTY_T1_DAYS = 180
WARRANTY_T2_DAYS = 365
WARRANTY_CAP_CENTS = 2500000
ZEV_TYPES = {"BEV", "FCEV"}


def round_half_up_int(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(x):
    return float(Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(x):
    return float(Decimal(str(x)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def option_escalation(contract, option_order):
    base = contract["base_unit_price_cents"]
    factor = ESCALATION[contract["escalation_index"]] ** option_order["option_year"]
    escalated = base * factor
    q = option_order["quantity"]
    if q < TIER1_QTY:
        tier = 0.0
    elif q < TIER2_QTY:
        tier = 0.02
    else:
        tier = 0.05
    return round_half_up_int(escalated * (1.0 - tier))


def domestic_content_pct(kit, variant):
    comps = []
    for cid in kit["component_ids"]:
        comps.append(DB.components.get(cid))
    comps = [c for c in comps if c is not None]
    if variant == "COST_BASED":
        total = sum(c["unit_cost_cents"] for c in comps)
        if total == 0:
            # Degenerate empty/zero-cost kit: defined as 100.0 (mirrors kit_completeness convention).
            return 100.0
        dom = sum(c["unit_cost_cents"] for c in comps if c["is_domestic"])
        return round_half_up_1dp(100.0 * dom / total)
    else:  # COMPONENT_COUNT
        if not comps:
            return 100.0
        dom = sum(1 for c in comps if c["is_domestic"])
        return round_half_up_1dp(100.0 * dom / len(comps))


def kit_completeness_pct(kit):
    required = kit["component_ids"]
    if not required:
        return 100.0
    verified = 0
    for cid in required:
        c = DB.components.get(cid)
        if c is not None and c["supplier_doc_status"] == "VERIFIED":
            verified += 1
    return round_half_up_1dp(100.0 * verified / len(required))


def warranty_approval_amount(claim, bus):
    decided = DB.clock.now()
    delivered = _parse_iso(bus["delivered_at"])
    age_days = (decided - delivered).total_seconds() / 86400.0
    if age_days <= WARRANTY_T1_DAYS:
        coverage = 1.0
    elif age_days <= WARRANTY_T2_DAYS:
        coverage = 0.5
    else:
        coverage = 0.0
    raw = claim["claimed_amount_cents"] * coverage
    capped = min(raw, WARRANTY_CAP_CENTS)
    return round_half_up_int(capped)


def agency_buses(agency_id):
    out = []
    for c in DB.contracts.values():
        if c["agency_id"] != agency_id:
            continue
        for b in DB.buses.values():
            if b["contract_id"] == c["id"]:
                out.append(b)
    return out


def agency_option_orders(agency_id):
    out = []
    for c in DB.contracts.values():
        if c["agency_id"] != agency_id:
            continue
        for o in DB.option_orders.values():
            if o["contract_id"] == c["id"]:
                out.append(o)
    return out


def recompute_zev(agency_id):
    agency = DB.agencies.get(agency_id)
    if agency is None:
        return
    buses = agency_buses(agency_id)
    accepted = [b for b in buses if b["status"] == "ACCEPTED"]
    zev_accepted = 0
    for b in accepted:
        cfg = DB.configurations.get(b["bus_configuration_id"])
        if cfg is not None and cfg["propulsion_type"] in ZEV_TYPES:
            zev_accepted += 1
    if accepted:
        agency["zev_ratio"] = round_half_up_4dp(zev_accepted / len(accepted))
    else:
        agency["zev_ratio"] = 0
    pipeline_total = 0
    pipeline_zev = 0
    for o in agency_option_orders(agency_id):
        if o["status"] == "EXERCISED":
            pipeline_total += o["quantity"]
            if o["propulsion_type"] in ZEV_TYPES:
                pipeline_zev += o["quantity"]
    denom = len(accepted) + pipeline_total
    if denom > 0:
        agency["projected_zev_ratio"] = round_half_up_4dp(
            (zev_accepted + pipeline_zev) / denom
        )
    else:
        agency["projected_zev_ratio"] = 0


def evaluate_time_transitions():
    """Evaluate option expiry and bus auto-acceptance against the logical clock."""
    now = DB.clock.now()
    expired_agencies = set()
    for o in DB.option_orders.values():
        if o["status"] != "AVAILABLE":
            continue
        deadline = _parse_iso(o["exercise_deadline"])
        if now > deadline:
            o["status"] = "EXPIRED"
            from db import touch
            touch(o)
            contract = DB.contracts.get(o["contract_id"])
            if contract is not None:
                expired_agencies.add(contract["agency_id"])
    for aid in expired_agencies:
        recompute_zev(aid)
    accepted_agencies = set()
    for b in DB.buses.values():
        if b["status"] != "DELIVERED" or b.get("acceptance_deadline") is None:
            continue
        deadline = _parse_iso(b["acceptance_deadline"])
        if now > deadline:
            b["status"] = "ACCEPTED"
            if b["payment_status"] == "UNPAID":
                b["payment_status"] = "INVOICED"
            from db import touch
            touch(b)
            contract = DB.contracts.get(b["contract_id"])
            if contract is not None:
                accepted_agencies.add(contract["agency_id"])
    for aid in accepted_agencies:
        recompute_zev(aid)


def lazy_option_check(option_order):
    """Evaluate a single option's deadline lazily (on reads)."""
    if option_order["status"] != "AVAILABLE":
        return
    now = DB.clock.now()
    deadline = _parse_iso(option_order["exercise_deadline"])
    if now > deadline:
        option_order["status"] = "EXPIRED"
        from db import touch
        touch(option_order)
        contract = DB.contracts.get(option_order["contract_id"])
        if contract is not None:
            recompute_zev(contract["agency_id"])


def lazy_bus_check(bus):
    """Evaluate a single bus's auto-acceptance lazily."""
    if bus["status"] != "DELIVERED" or bus.get("acceptance_deadline") is None:
        return
    now = DB.clock.now()
    deadline = _parse_iso(bus["acceptance_deadline"])
    if now > deadline:
        bus["status"] = "ACCEPTED"
        if bus["payment_status"] == "UNPAID":
            bus["payment_status"] = "INVOICED"
        from db import touch
        touch(bus)
        contract = DB.contracts.get(bus["contract_id"])
        if contract is not None:
            recompute_zev(contract["agency_id"])


def recompute_kit(kit):
    """Recompute a kit's completeness; auto-transition STAGING -> COMPLETE at 100.0."""
    kit["completeness_pct"] = kit_completeness_pct(kit)
    if kit["status"] == "STAGING" and kit["completeness_pct"] == 100.0:
        kit["status"] = "COMPLETE"
        from db import touch
        touch(kit)
        # Flip slot kit_status if bus is already ASSIGNED.
        for slot in DB.slots.values():
            if slot.get("bus_unit_id") == kit["bus_unit_id"] and slot["status"] == "ASSIGNED":
                if slot["kit_status"] == "NOT_KITTED":
                    slot["kit_status"] = "KITTED"
                    touch(slot)


def recompute_kits_for_component(component_id):
    for kit in DB.kits.values():
        if component_id in kit["component_ids"] and kit["status"] == "STAGING":
            recompute_kit(kit)
        elif component_id in kit["component_ids"]:
            # Keep percentage fresh even for non-staging kits (percentage recompute is universal).
            kit["completeness_pct"] = kit_completeness_pct(kit)


def stock_for(agency_id, component_id):
    for s in DB.stocks.values():
        if s["agency_id"] == agency_id and s["component_id"] == component_id:
            return s
    return None


def update_stock_status(stock):
    from db import touch
    # DEPLETED only once the physical quantity is consumed to zero (payment
    # decrements quantity); a mere reservation covering all quantity does not
    # deplete the row. Reactivation happens on restock above reserved_quantity.
    new_status = "DEPLETED" if stock["quantity"] <= 0 else "ACTIVE"
    if stock["status"] != new_status:
        stock["status"] = new_status
        touch(stock)
