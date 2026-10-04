"""Business rules: calculations, posture derivation, cascades, lazy evaluation."""
from decimal import Decimal, ROUND_HALF_UP

from errors import (
    err, fk_not_found, invalid_state,
    ERR_AGREEMENT_NOT_GOOD_STANDING, ERR_MANUFACTURER_INACTIVE,
    ERR_MFC_FLOOR_VIOLATION, ERR_OUTSIDE_VEHICLE_WINDOW,
    ERR_PRICE_LIST_NOT_ACTIVE, ERR_SCOPE_VIOLATION,
    ERR_TAA_ORIGIN_VIOLATION, ERR_TEAMING_INELIGIBLE,
    ERR_VEHICLE_CEILING_EXCEEDED,
)
from util import now_logical, bump

# ---------------------------------------------------------------------------
# Constants (scaffold §1.3)
# ---------------------------------------------------------------------------
SURCHARGE_RATE = Decimal("0.30")
SURCHARGE_FLOOR_PCT = Decimal("0.015")
SURCHARGE_CAP_CENTS = 500000
STATE_COOP_MFC_CAP = Decimal("0.25")
TAA_DESIGNATED_COUNTRIES = ["US", "CA", "MX", "GB", "DE", "FR", "JP", "AU", "IL", "KR", "NO", "CH"]
POSTURE_ON_HOLD_DEBT_CENTS = -100000
AUDIT_MATERIALITY_CENTS = 250000

TIERS = {"FEDERAL", "STATE", "LOCAL", "EDUCATION", "HEALTHCARE"}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def lookup(db, kind, entity_id):
    store = getattr(db, kind)
    e = store.get(entity_id)
    if e is None:
        raise fk_not_found(f"{kind[:-1] if kind.endswith('s') else kind} not found")
    return e


def resolve_agreement_of_vehicle(db, vehicle):
    return lookup(db, "agreements", vehicle["agreement_id"])


def resolve_manufacturer_of_agreement(db, agreement):
    return lookup(db, "manufacturers", agreement["manufacturer_id"])


def active_price_list_for_vehicle(db, vehicle_id):
    for pl in db.price_lists.values():
        if pl["vehicle_id"] == vehicle_id and pl["status"] == "ACTIVE":
            return pl
    return None


# ---------------------------------------------------------------------------
# Lazy evaluation
# ---------------------------------------------------------------------------
def maybe_expire_vehicle(db, vehicle):
    """Lazy EXPIRED flip: AUTHORIZED vehicle whose window has passed expires on touch."""
    if vehicle["status"] == "AUTHORIZED" and now_logical(db) >= vehicle["_to"]:
        vehicle["status"] = "EXPIRED"
        bump(vehicle)
        for pl in db.price_lists.values():
            if pl["vehicle_id"] == vehicle["id"] and pl["status"] == "ACTIVE":
                pl["status"] = "SUPERSEDED"
                bump(pl)
        for o in db.orders.values():
            if o["vehicle_id"] == vehicle["id"] and o["compliance_status"] in ("DRAFT", "SCREENING"):
                o["compliance_status"] = "CANCELLED"
                bump(o)


def lazy_invoice_overdue(db, invoice):
    """Lazy OVERDUE flip: ISSUED invoice past due_at flips on read/sweep."""
    if invoice["status"] == "ISSUED" and now_logical(db) > invoice["_due"]:
        invoice["status"] = "OVERDUE"
        bump(invoice)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def to_decimal_pct(v):
    return Decimal(str(v))


def effective_mfc(agreement, vehicle):
    mfc = to_decimal_pct(agreement["mfc_discount_pct"])
    if vehicle["vehicle_kind"] in ("STATE_COOP", "COOP_PURCHASING"):
        return min(mfc, STATE_COOP_MFC_CAP)
    return mfc


def mfc_floor_cents(agreement, vehicle, basis):
    return int((Decimal(int(basis)) * (Decimal(1) - effective_mfc(agreement, vehicle))).to_integral_value(rounding="ROUND_FLOOR"))


def mfc_floor_ok(agreement, vehicle, basis, offered):
    return int(offered) <= mfc_floor_cents(agreement, vehicle, basis)


def compute_origin_flag(db, vehicle, manufacturer, line_origins):
    """Return TAA_PASS / TAA_FAIL / NOT_APPLICABLE for the given origin list."""
    if not vehicle["taa_required"]:
        return "NOT_APPLICABLE"
    if vehicle["vehicle_kind"] == "FED_SCHEDULE":
        whitelist = set(manufacturer.get("designated_countries") or [])
    else:
        whitelist = set(TAA_DESIGNATED_COUNTRIES)
    return "TAA_PASS" if all(o in whitelist for o in line_origins) else "TAA_FAIL"


def price_line_origin_ok(vehicle, manufacturer, origin):
    return compute_origin_flag_for_origin(vehicle, manufacturer, origin) is True


def compute_origin_flag_for_origin(vehicle, manufacturer, origin):
    if not vehicle["taa_required"]:
        return True
    if vehicle["vehicle_kind"] == "FED_SCHEDULE":
        return origin in set(manufacturer.get("designated_countries") or [])
    return origin in set(TAA_DESIGNATED_COUNTRIES)


def sku_matches_scope(sku, product_scope):
    return any(isinstance(p, str) and sku.startswith(p) for p in (product_scope or []))


def recompute_prc(db, vehicle_id):
    """PRC accumulator over the vehicle's ACTIVE price list lines, sorted (sku, created_at)."""
    vehicle = db.vehicles.get(vehicle_id)
    if vehicle is None:
        return
    total = 0
    active = active_price_list_for_vehicle(db, vehicle_id)
    if active is not None:
        lines = sorted(
            (l for l in db.price_lines.values() if l["price_list_id"] == active["id"]),
            key=lambda l: (l["sku"], l["created_at"]),
        )
        for l in lines:
            delta = max(0, int(l["basis_price_cents"]) - int(l["offered_price_cents"]))
            total += delta * int(l["sold_qty"])
    vehicle["prc_accumulator_cents"] = total


def recompute_posture(agreement):
    if agreement["status"] in ("TERMINATED", "SUSPENDED"):
        agreement["posture"] = "SUSPENDED"
    elif int(agreement["dispute_credit_cents"]) < POSTURE_ON_HOLD_DEBT_CENTS:
        agreement["posture"] = "ON_HOLD"
    else:
        agreement["posture"] = "GOOD_STANDING"


def teaming_surcharge_cents(order_total, arrangement):
    """Non-SB teaming uplift: min(cap, max(total*share*0.30, total*0.015)), round-half-up."""
    if arrangement is None or arrangement["small_business"]:
        return 0
    base = Decimal(int(order_total))
    raw = base * to_decimal_pct(arrangement["revenue_share_pct"]) * SURCHARGE_RATE
    floored = base * SURCHARGE_FLOOR_PCT
    return int(min(Decimal(SURCHARGE_CAP_CENTS), max(raw, floored)).to_integral_value(rounding=ROUND_HALF_UP))


def recompute_sales_report(db, report):
    """Recompute totals from invoices + delivered orders, then sb_goal_met."""
    agreement = db.agreements.get(report["agreement_id"])
    vehicle_ids = [v["id"] for v in db.vehicles.values() if v["agreement_id"] == report["agreement_id"]]
    order_ids = [o["id"] for o in db.orders.values() if o["vehicle_id"] in vehicle_ids]
    total = 0
    for inv in db.invoices.values():
        if inv["order_id"] in order_ids and inv["period_label"] == report["period_label"] \
                and inv["status"] in ("ISSUED", "PAID", "OVERDUE"):
            total += int(inv["amount_cents"])
    report["total_sales_cents"] = total
    _, end = report["_period_bounds"]
    sb = 0
    for o in db.orders.values():
        if o["vehicle_id"] in vehicle_ids and o["compliance_status"] == "CLEARED" \
                and o["billing_status"] in ("DELIVERED", "INVOICED", "PAID") \
                and o.get("_delivered_at") is not None and o["_delivered_at"] < end:
            sb += int(o.get("subcontract_cents", 0))
    report["total_sb_subcontract_cents"] = sb
    recompute_sb_goal(db, report, agreement)


def recompute_sb_goal(db, report, agreement=None):
    if agreement is None:
        agreement = db.agreements.get(report["agreement_id"])
    total = int(report["total_sales_cents"])
    if total == 0:
        report["sb_goal_met"] = True
    else:
        goal = (Decimal(str(agreement["small_business_goal_pct"])) * Decimal(total)).to_integral_value(rounding=ROUND_HALF_UP)
        report["sb_goal_met"] = int(report["total_sb_subcontract_cents"]) >= int(goal)


def refresh_sales_reports_for_order(db, order, period_label):
    """Upsert DRAFT report for (agreement, period_label) and recompute it."""
    from util import new_entity, period_bounds
    vehicle = db.vehicles[order["vehicle_id"]]
    agreement_id = vehicle["agreement_id"]
    report = next((r for r in db.sales_reports.values()
                   if r["agreement_id"] == agreement_id and r["period_label"] == period_label), None)
    if report is None:
        report = new_entity(db, db.sales_reports, {}, agreement_id=agreement_id,
                            period_label=period_label, total_sales_cents=0,
                            total_sb_subcontract_cents=0, sb_goal_met=True, status="DRAFT")
        report["_period_bounds"] = period_bounds(period_label)
    recompute_sales_report(db, report)
    return report


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------
def assert_agreement_good_standing(agreement):
    if agreement["posture"] != "GOOD_STANDING":
        raise err(ERR_AGREEMENT_NOT_GOOD_STANDING, "agreement posture is not GOOD_STANDING", 422)


def assert_manufacturer_active(db, agreement):
    manufacturer = resolve_manufacturer_of_agreement(db, agreement)
    if manufacturer["status"] != "ACTIVE":
        raise err(ERR_MANUFACTURER_INACTIVE, "manufacturer is not ACTIVE", 422)


def assert_vehicle_authorized(db, vehicle):
    maybe_expire_vehicle(db, vehicle)
    if vehicle["status"] != "AUTHORIZED":
        raise invalid_state("vehicle is not AUTHORIZED")


def assert_vehicle_window_open(db, vehicle):
    now = now_logical(db)
    if not (vehicle["_from"] <= now < vehicle["_to"]):
        raise err(ERR_OUTSIDE_VEHICLE_WINDOW, "logical clock is outside the vehicle effective window", 422)


def assert_active_list_for_order(db, vehicle, price_list_id):
    maybe_expire_vehicle(db, vehicle)
    active = active_price_list_for_vehicle(db, vehicle["id"])
    if active is None or active["id"] != price_list_id:
        raise err(ERR_PRICE_LIST_NOT_ACTIVE, "referenced price list is not the vehicle's ACTIVE list", 422)
    return active


def assert_teaming_eligible(db, teaming, vehicle_id, skus):
    """Shared by order create and order submit. Raises ERR_TEAMING_INELIGIBLE."""
    if teaming["status"] != "APPROVED":
        raise err(ERR_TEAMING_INELIGIBLE, "teaming arrangement is not APPROVED", 422)
    scopes = [s for s in db.teaming_scopes.values() if s["teaming_id"] == teaming["id"]]
    for s in scopes:
        if s["vehicle_id"] == vehicle_id and all(sku_matches_scope(sku, s["sku_prefixes"]) for sku in skus):
            return
    raise err(ERR_TEAMING_INELIGIBLE, "teaming scope does not cover vehicle and all order skus", 422)


def scope_subset(values, allowed):
    return all(v in set(allowed) for v in values)


def assert_scope_contained(buyer_tiers, scope_tiers):
    if not scope_subset(buyer_tiers, scope_tiers):
        raise err(ERR_SCOPE_VIOLATION, "buyer_tiers must be a subset of agreement scope_tiers", 422)


def assert_mfc_ok(agreement, vehicle, basis, offered):
    if not mfc_floor_ok(agreement, vehicle, basis, offered):
        raise err(ERR_MFC_FLOOR_VIOLATION, "offered price exceeds the MFC floor", 422)


def assert_taa_ok(vehicle, manufacturer, origins):
    if compute_origin_flag(db_dummy, vehicle, manufacturer, origins) == "TAA_FAIL":
        raise err(ERR_TAA_ORIGIN_VIOLATION, "order line origin fails TAA evaluation for this vehicle", 422)


# compute_origin_flag does not use db; keep signature but ignore first param callers pass.
db_dummy = None


def deliver_ceiling_check(db, vehicle, order):
    consumed = 0
    for o in db.orders.values():
        if o["id"] == order["id"]:
            continue
        if o["vehicle_id"] == vehicle["id"] and o["buyer_tier"] == order["buyer_tier"] \
                and o["billing_status"] in ("DELIVERED", "INVOICED", "PAID") \
                and o["compliance_status"] not in ("CANCELLED", "BLOCKED"):
            consumed += int(o["order_total_cents"])
    if consumed + int(order["order_total_cents"]) > int(vehicle["ceiling_cents"]):
        raise err(ERR_VEHICLE_CEILING_EXCEEDED, "buyer-tier consumption would exceed the vehicle ceiling", 422)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def cascade_suspend_agreement(db, agreement):
    for v in db.vehicles.values():
        if v["agreement_id"] == agreement["id"] and v["status"] == "AUTHORIZED":
            v["status"] = "SUSPENDED"
            v["_cascade_suspended"] = True
            bump(v)
    for t in db.teaming.values():
        if t["agreement_id"] == agreement["id"] and t["status"] == "APPROVED":
            t["status"] = "SUSPENDED"
            bump(t)


def cascade_reinstate_agreement(db, agreement):
    for v in db.vehicles.values():
        if v["agreement_id"] == agreement["id"] and v["status"] == "SUSPENDED" and v.get("_cascade_suspended"):
            v["status"] = "AUTHORIZED"
            v["_cascade_suspended"] = False
            bump(v)


def cancel_order(db, order):
    order["compliance_status"] = "CANCELLED"
    bump(order)
    recompute_prc(db, order["vehicle_id"])


def expire_vehicle_cascade(db, vehicle):
    vehicle["status"] = "EXPIRED"
    vehicle["_cascade_suspended"] = False
    bump(vehicle)
    for pl in db.price_lists.values():
        if pl["vehicle_id"] == vehicle["id"] and pl["status"] == "ACTIVE":
            pl["status"] = "SUPERSEDED"
            bump(pl)
    for o in db.orders.values():
        if o["vehicle_id"] == vehicle["id"] and o["compliance_status"] in ("DRAFT", "SCREENING"):
            o["compliance_status"] = "CANCELLED"
            bump(o)


def cascade_terminate_agreement(db, agreement):
    for v in db.vehicles.values():
        if v["agreement_id"] == agreement["id"] and v["status"] != "EXPIRED":
            expire_vehicle_cascade(db, v)
    for t in db.teaming.values():
        if t["agreement_id"] == agreement["id"] and t["status"] != "TERMINATED":
            t["status"] = "TERMINATED"
            bump(t)
    vehicle_ids = {v["id"] for v in db.vehicles.values() if v["agreement_id"] == agreement["id"]}
    for pl in db.price_lists.values():
        if pl["vehicle_id"] in vehicle_ids and pl["status"] == "ACTIVE":
            pl["status"] = "SUPERSEDED"
            bump(pl)
    for o in db.orders.values():
        if o["vehicle_id"] in vehicle_ids and o["billing_status"] == "UNBILLED" \
                and o["compliance_status"] in ("DRAFT", "SCREENING", "CLEARED"):
            cancel_order(db, o)
