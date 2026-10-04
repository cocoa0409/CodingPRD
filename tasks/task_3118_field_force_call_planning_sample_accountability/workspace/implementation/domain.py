"""Domain logic: field validators, cascades, calculations for the Field Force API."""

import datetime as dt
from decimal import Decimal, ROUND_HALF_UP

import store
from store import now
from util import fail, bump, now_iso, parse_dt, fresh_entity


# ---------------------------------------------------------------------------
# Field requirement validators (ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def req_field(body, name):
    v = body.get(name)
    if v is None:
        fail("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % name)
    return v


def req_str(body, name, minlen=None):
    v = req_field(body, name)
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", 400, "Field %s must be a string" % name)
    if minlen is not None and len(v) < minlen:
        fail("ERR_INVALID_REQUEST", 400,
             "Field %s must be at least %d characters" % (name, minlen))
    return v


def opt_str(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", 400, "Field %s must be a string" % name)
    return v


def req_int(body, name, minimum=None):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", 400,
             "Field %s must be >= %d" % (name, minimum))
    return v


def opt_int(body, name, minimum=None):
    v = body.get(name)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", 400,
             "Field %s must be >= %d" % (name, minimum))
    return v


def req_num(body, name):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail("ERR_INVALID_REQUEST", 400, "Field %s must be a number" % name)
    return v


def req_bool(body, name):
    v = req_field(body, name)
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", 400, "Field %s must be a boolean" % name)
    return v


def req_enum(body, name, allowed):
    v = req_str(body, name)
    if v not in allowed:
        fail("ERR_INVALID_REQUEST", 400,
             "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def req_dt(body, name):
    v = req_str(body, name)
    try:
        return parse_dt(v)
    except ValueError:
        fail("ERR_INVALID_REQUEST", 400, "Field %s must be an ISO-8601 datetime" % name)


# ---------------------------------------------------------------------------
# Entity lookups (ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def find(table, entity_id, label):
    e = table.get(entity_id)
    if e is None:
        fail("ERR_NOT_FOUND", 404, "%s not found: %s" % (label, entity_id))
    return e


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------
def get_or_create_balance(rep_id, lot):
    """Return the (rep, lot) balance row, creating an empty one on first use."""
    for b in store.lot_balances.values():
        if b["representative_id"] == rep_id and b["lot_id"] == lot["id"]:
            return b
    b = fresh_entity({
        "representative_id": rep_id,
        "lot_id": lot["id"],
        "product_id": lot["product_id"],
        "qty_issued": 0,
        "qty_dispensed": 0,
        "qty_returned": 0,
        "qty_transferred_out": 0,
        "qty_transferred_in": 0,
        "qty_in_transit_out": 0,
        "qty_available_forward": 0,
        "qty_available_confirmed": 0,
    })
    store.lot_balances[b["id"]] = b
    return b


def find_balance(rep_id, lot_id):
    for b in store.lot_balances.values():
        if b["representative_id"] == rep_id and b["lot_id"] == lot_id:
            return b
    return None


def recalc_balance(b):
    b["qty_available_forward"] = (
        b["qty_issued"] - b["qty_dispensed"] - b["qty_returned"]
        - b["qty_transferred_out"] - b["qty_in_transit_out"]
        + b["qty_transferred_in"]
    )
    b["qty_available_confirmed"] = (
        b["qty_issued"] - b["qty_dispensed"] - b["qty_returned"]
        - b["qty_transferred_out"] + b["qty_transferred_in"]
    )


# ---------------------------------------------------------------------------
# Lot releasability
# ---------------------------------------------------------------------------
def check_lot_releasable(lot):
    if lot["status"] != "RELEASED":
        fail("ERR_LOT_NOT_RELEASABLE", 422,
             "Lot %s is not RELEASED" % lot["id"])
    exp = parse_dt(lot["expiration_date"])
    if exp <= now():
        fail("ERR_LOT_NOT_RELEASABLE", 422,
             "Lot %s has expired" % lot["id"])


# ---------------------------------------------------------------------------
# Attainment recompute (2 decimal places, round-half-up)
# ---------------------------------------------------------------------------
def _round2(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def recompute_attainment(entry):
    delivered = entry["delivered_calls"]
    planned = entry["planned_calls_per_cycle"]
    entry["call_attainment_pct_planned_basis"] = _round2(
        delivered * 100.0 / planned if planned else 0.0
    )
    open_sched = sum(
        1 for v in store.call_visits.values()
        if v["target_list_entry_id"] == entry["id"] and v["call_status"] == "SCHEDULED"
    )
    denom = max(delivered + open_sched, 1)
    entry["call_attainment_pct_delivered_basis"] = _round2(delivered * 100.0 / denom)


# ---------------------------------------------------------------------------
# Prescriber YTD usage (calendar year of the logical clock, SIGNED only)
# ---------------------------------------------------------------------------
def prescriber_ytd(prescriber_id):
    year = now().year
    total = 0
    for d in store.disbursements.values():
        if d["prescriber_id"] != prescriber_id:
            continue
        if d["reconciliation_status"] != "SIGNED":
            continue
        try:
            sd = parse_dt(d["signed_at"])
        except ValueError:
            continue
        if sd.year == year:
            total += d["quantity"]
    return total


# ---------------------------------------------------------------------------
# Prescriber eligibility (eligibility + DEA for controlled products)
# ---------------------------------------------------------------------------
def check_prescriber_eligible(presc, product=None):
    if presc["eligibility_status"] != "ELIGIBLE":
        fail("ERR_PRESCRIBER_NOT_ELIGIBLE", 422,
             "Prescriber %s is not ELIGIBLE" % presc["id"])
    if product is not None and product.get("controlled") and not presc.get("dea_number"):
        fail("ERR_PRESCRIBER_NOT_ELIGIBLE", 422,
             "Prescriber %s lacks DEA number for controlled product" % presc["id"])


# ---------------------------------------------------------------------------
# Disbursement reservation release (REJECTED / VOIDED transitions)
# ---------------------------------------------------------------------------
def release_disbursement(dis):
    dis["reconciliation_status"] = dis["_target_status"]
    del dis["_target_status"]
    bump(dis)


def void_pending_disbursements_for_visit(visit):
    for d in store.disbursements.values():
        if d["call_visit_id"] == visit["id"] and d["reconciliation_status"] == "PENDING_SIGNATURE":
            d["_target_status"] = "VOIDED"
            release_disbursement(d)


def void_pending_disbursements_for_lot(lot_id):
    for d in store.disbursements.values():
        if d["lot_id"] == lot_id and d["reconciliation_status"] == "PENDING_SIGNATURE":
            d["_target_status"] = "VOIDED"
            release_disbursement(d)


# ---------------------------------------------------------------------------
# Rep SUSPENDED cascade (hop 3 of reconciliation discipline)
# ---------------------------------------------------------------------------
def suspend_rep_cascade(rep):
    rep["compliance_standing"] = "SUSPENDED"
    bump(rep)
    for v in store.call_visits.values():
        if v["representative_id"] == rep["id"] and v["call_status"] == "SCHEDULED":
            v["call_status"] = "CANCELLED"
            bump(v)
            entry = store.target_entries.get(v["target_list_entry_id"])
            if entry is not None:
                recompute_attainment(entry)
                bump(entry)
            void_pending_disbursements_for_visit(v)
    for t in store.transfers.values():
        if t["from_rep_id"] == rep["id"] and t["status"] == "REQUESTED":
            t["status"] = "CANCELLED"
            bump(t)
            b = find_balance(rep["id"], t["lot_id"])
            if b is not None:
                b["qty_in_transit_out"] = max(b["qty_in_transit_out"] - t["quantity"], 0)
                recalc_balance(b)
                bump(b)


# ---------------------------------------------------------------------------
# Plan supersede cascade
# ---------------------------------------------------------------------------
def supersede_plan(old_plan):
    old_plan["status"] = "SUPERSEDED"
    bump(old_plan)
    for v in store.call_visits.values():
        if v["call_plan_id"] == old_plan["id"] and v["call_status"] == "SCHEDULED":
            v["call_status"] = "CANCELLED"
            bump(v)
            entry = store.target_entries.get(v["target_list_entry_id"])
            if entry is not None:
                recompute_attainment(entry)
                bump(entry)
            void_pending_disbursements_for_visit(v)


# ---------------------------------------------------------------------------
# Temperature severity (1 decimal on the outside distance; strict > as written)
# ---------------------------------------------------------------------------
def temperature_severity(product, observed_temp_c, excursion_minutes):
    outside = max(
        Decimal(str(observed_temp_c)) - Decimal(str(product["storage_temp_max_c"])),
        Decimal(str(product["storage_temp_min_c"])) - Decimal(str(observed_temp_c)),
        Decimal("0"),
    )
    outside = outside.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if outside > Decimal("5.0") or excursion_minutes > 240:
        return "CRITICAL"
    if (outside > Decimal("2.0") and outside <= Decimal("5.0")) or (
        outside <= Decimal("2.0") and excursion_minutes > 30
    ):
        return "MAJOR"
    return "MINOR"


# ---------------------------------------------------------------------------
# Temperature excursion quarantine cascade (CRITICAL, depth 3)
# ---------------------------------------------------------------------------
def quarantine_cascade(rep_id, product_id):
    affected_lots = set()
    for b in store.lot_balances.values():
        if b["representative_id"] != rep_id:
            continue
        lot = store.sample_lots.get(b["lot_id"])
        if lot is None or lot["product_id"] != product_id:
            continue
        if b["qty_available_forward"] > 0 and lot["status"] == "RELEASED":
            lot["status"] = "QUARANTINED"
            lot["quarantine_reason"] = "TEMPERATURE_EXCURSION"
            lot["quantity_available"] = 0
            bump(lot)
            affected_lots.add(lot["id"])
    # Hop 2: void pending disbursements on quarantined lots
    for lot_id in affected_lots:
        void_pending_disbursements_for_lot(lot_id)
    # Hop 3: auto-cancel REQUESTED transfers on quarantined lots
    for t in store.transfers.values():
        if t["lot_id"] in affected_lots and t["status"] == "REQUESTED":
            t["status"] = "CANCELLED"
            bump(t)
            b = find_balance(t["from_rep_id"], t["lot_id"])
            if b is not None:
                b["qty_in_transit_out"] = max(b["qty_in_transit_out"] - t["quantity"], 0)
                recalc_balance(b)
                bump(b)
