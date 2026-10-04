"""Entity serializers: public dicts with derived/computed fields.

Two timestamp families (PRD §2.5): created_at/updated_at render with exactly
three fractional digits; domain datetimes render verbatim as supplied (raw
strings stored on the entity) or in the clock's own precision when computed.
"""
from decimal import Decimal, ROUND_HALF_UP

import store

CENT2 = Decimal("0.01")


def num_out(x):
    """Decimal -> int when integral else float, for JSON output."""
    if x is None:
        return None
    if isinstance(x, Decimal):
        if x == x.to_integral_value():
            return int(x)
        return float(x)
    return x


def round2(x):
    return x.quantize(CENT2, rounding=ROUND_HALF_UP)


def _common(e, out):
    out["id"] = e["id"]
    out["created_at"] = store.render_system_ts(e["created_at"])
    out["updated_at"] = store.render_system_ts(e["updated_at"])
    out["version"] = e["version"]
    return out


# ---------------------------------------------------------------------------
# Circulating side
# ---------------------------------------------------------------------------
def denomination(d):
    return _common(d, {
        "code": d["code"],
        "face_value_cents": d["face_value_cents"],
        "blank_budget_cost_cents": num_out(d["blank_budget_cost_cents"]),
        "striking_cost_cents": num_out(d["striking_cost_cents"]),
        "blanks_per_tonne": d["blanks_per_tonne"],
        "blank_stock_pieces": d["blank_stock_pieces"],
        "budgeted_unit_seigniorage_cents": num_out(d["budgeted_unit_seigniorage_cents"]),
    })


def fed_order(o):
    return _common(o, {
        "fiscal_year": o["fiscal_year"],
        "denomination_code": o["denomination_code"],
        "quantity_ordered_pieces": o["quantity_ordered_pieces"],
        "due_date": o["due_date"],
        "status": o["status"],
        "quantity_fulfilled_pieces": o["quantity_fulfilled_pieces"],
        "budgeted_seigniorage_cents": num_out(o["budgeted_seigniorage_cents"]),
        "realized_seigniorage_cents": num_out(o["realized_seigniorage_cents"]),
    })


def lot(l):
    return _common(l, {
        "commodity": l["commodity"],
        "denomination_code": l["denomination_code"],
        "quantity_tonnes": l["quantity_tonnes"],
        "budget_price_cents_per_tonne": l["budget_price_cents_per_tonne"],
        "locked_unit_price_cents_per_tonne": l["locked_unit_price_cents_per_tonne"],
        "order_spot_cents_per_tonne": l["order_spot_cents_per_tonne"],
        "vault": l["vault"],
        "planned_delivery_date": l["planned_delivery_date"],
        "status": l["status"],
        "blanks_produced": l["blanks_produced"],
        "realized_cost_cents": l["realized_cost_cents"],
    })


def run(r):
    return _common(r, {
        "fed_order_id": r["fed_order_id"],
        "denomination_code": r["denomination_code"],
        "facility": r["facility"],
        "press_line": r["press_line"],
        "planned_start": r["planned_start"],
        "planned_end": r["planned_end"],
        "planned_quantity": r["planned_quantity"],
        "status": r["status"],
        "reserved_blanks": r["reserved_blanks"],
        "produced_pieces": r["produced_pieces"],
        "scrapped_pieces": r["scrapped_pieces"],
        "rework_count": r["rework_count"],
    })


def error_case(c):
    return _common(c, {
        "production_run_id": c["production_run_id"],
        "error_pieces": c["error_pieces"],
        "description": c["description"],
        "reported_by_user_id": c["reported_by_user_id"],
        "status": c["status"],
        "destroyed_by_user_ids": c["destroyed_by_user_ids"],
    })


# ---------------------------------------------------------------------------
# Numismatic side
# ---------------------------------------------------------------------------
def program(p):
    gross, accrued, net = program_financials(p)
    return _common(p, {
        "name": p["name"],
        "statute_reference": p["statute_reference"],
        "max_mintage_legal": p["max_mintage_legal"],
        "surcharge_cents_per_unit": p["surcharge_cents_per_unit"],
        "beneficiary_name": p["beneficiary_name"],
        "beneficiary_cap_cents": p["beneficiary_cap_cents"],
        "direct_costs_cents": p["direct_costs_cents"],
        "sales_window_start": p["sales_window_start"],
        "sales_window_end": p["sales_window_end"],
        "status": p["status"],
        "design_revision_count": p["design_revision_count"],
        "created_by_user_id": p["created_by_user_id"],
        "gross_receipts_cents": gross,
        "surcharge_accrued_cents": accrued,
        "net_proceeds_cents": net,
        "disbursed_cents": p["disbursed_cents"],
    })


def program_financials(p):
    """Computed on read (PRD §3.5): gross receipts, surcharge accrued, and
    net proceeds with the pinned evaluation order."""
    gross = 0
    paid_units = 0
    for o in store.db["orders"].values():
        if o["payment_status"] != "PAID":
            continue
        prod = store.db["products"].get(o["product_id"])
        if prod is None or prod["program_id"] != p["id"]:
            continue
        gross += o["quantity"] * prod["price_cents"]
        paid_units += o["quantity"]
    accrued = paid_units * p["surcharge_cents_per_unit"]
    base = gross - p["direct_costs_cents"]
    fee = int((Decimal(base) * Decimal("0.05")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return gross, accrued, base - fee


def allocated_units(product_id):
    return sum(o["quantity"] for o in store.db["orders"].values()
               if o["product_id"] == product_id and o["allocation_status"] == "ALLOCATED")


def product(pr):
    alloc = allocated_units(pr["id"])
    return _common(pr, {
        "product_code": pr["product_code"],
        "program_id": pr["program_id"],
        "product_family": pr["product_family"],
        "product_type": pr["product_type"],
        "price_cents": pr["price_cents"],
        "mintage_limit": pr["mintage_limit"],
        "household_order_limit": pr["household_order_limit"],
        "release_datetime": pr["release_datetime"],
        "subscription_eligible": pr["subscription_eligible"],
        "status": pr["status"],
        "allocated_units": alloc,
        "remaining_units": pr["mintage_limit"] - alloc,
    })


def collector(c):
    return _common(c, {
        "full_name": c["full_name"],
        "email": c["email"],
        "household_id": c["household_id"],
    })


def order_status(o):
    if o["allocation_status"] == "RELEASED":
        return "CANCELLED"
    if o["payment_status"] == "PAID" and o["allocation_status"] == "ALLOCATED":
        return "COMPLETED"
    return "ACTIVE"


def order(o):
    return _common(o, {
        "collector_id": o["collector_id"],
        "product_id": o["product_id"],
        "quantity": o["quantity"],
        "total_cents": o["total_cents"],
        "payment_status": o["payment_status"],
        "allocation_status": o["allocation_status"],
        "status": order_status(o),
    })


def subscription(s):
    return _common(s, {
        "collector_id": s["collector_id"],
        "product_id": s["product_id"],
        "units_per_cycle": s["units_per_cycle"],
        "frequency": s["frequency"],
        "status": s["status"],
        "next_billing_date": s["next_billing_date"],
        "cycles_billed": s["cycles_billed"],
    })


def invoice(i):
    return _common(i, {
        "subscription_id": i["subscription_id"],
        "period_index": i["period_index"],
        "amount_cents": i["amount_cents"],
        "attempts": i["attempts"],
        "status": i["status"],
    })


# ---------------------------------------------------------------------------
# Bullion side
# ---------------------------------------------------------------------------
def bullion_issue(b):
    return _common(b, {
        "name": b["name"],
        "metal": b["metal"],
        "unit_weight_oz": num_out(b["unit_weight_oz"]),
        "total_pool_units": b["total_pool_units"],
        "remaining_pool_units": b["remaining_pool_units"],
        "offer_window_hours": b["offer_window_hours"],
        "status": b["status"],
    })


def authorized_purchaser(a):
    return _common(a, {
        "name": a["name"],
        "tier": a["tier"],
        "status": a["status"],
    })


def allocation(a):
    return _common(a, {
        "bullion_issue_id": a["bullion_issue_id"],
        "authorized_purchaser_id": a["authorized_purchaser_id"],
        "quantity_units": a["quantity_units"],
        "offered_by_user_id": a["offered_by_user_id"],
        "offer_expires_at": a["offer_expires_at"],
        "total_price_cents": a["total_price_cents"],
        "status": a["status"],
    })
