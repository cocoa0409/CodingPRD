"""Core helpers: record creation, serializers, derived counters, gates."""
import uuid
from decimal import Decimal, ROUND_HALF_UP

import db
from clock import clock, now_iso
from errors import raise_err

ALLERGEN_TAGS = {"PEANUT", "TREE_NUT", "MILK", "EGG", "WHEAT", "SOY", "SESAME"}


# ---------------------------------------------------------------------------
# record creation / mutation
# ---------------------------------------------------------------------------

def new_record(coll_name, fields):
    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "created_seq": db.next_seq(coll_name),
    }
    rec.update(fields)
    db.insert(coll_name, rec)
    return rec


def touch(rec, bump=True):
    rec["updated_at"] = now_iso()
    if bump:
        rec["version"] += 1


# ---------------------------------------------------------------------------
# requirement / validation helpers
# ---------------------------------------------------------------------------

def get_body():
    from flask import request
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise_err("ERR_INVALID_REQUEST", "request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def _present(body, key):
    return key in body and body[key] is not None


def req_str(body, key):
    if not _present(body, key) or not isinstance(body[key], str):
        raise_err("ERR_INVALID_REQUEST", f"missing or invalid field: {key}")
    return body[key]


def opt_str(body, key, default=None):
    if not _present(body, key):
        return default
    if not isinstance(body[key], str):
        raise_err("ERR_INVALID_REQUEST", f"invalid field: {key}")
    return body[key]


def req_bool(body, key):
    if not _present(body, key) or not isinstance(body[key], bool):
        raise_err("ERR_INVALID_REQUEST", f"missing or invalid field: {key}")
    return body[key]


def req_int(body, key):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err("ERR_INVALID_REQUEST", f"missing or invalid field: {key}")
    return v


def opt_int(body, key, default=None):
    if not _present(body, key):
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err("ERR_INVALID_REQUEST", f"invalid field: {key}")
    return v


def req_enum(body, key, allowed):
    v = req_str(body, key)
    if v not in allowed:
        raise_err("ERR_INVALID_REQUEST", f"unknown value for {key}: {v}")
    return v


def opt_dt(body, key, default=None):
    if not _present(body, key):
        return default
    from clock import parse_dt
    try:
        return parse_dt(body[key])
    except Exception:
        raise_err("ERR_INVALID_REQUEST", f"invalid datetime: {key}")


def req_dt(body, key):
    v = opt_dt(body, key)
    if v is None:
        raise_err("ERR_INVALID_REQUEST", f"missing field: {key}")
    return v


def find_or_404(coll_name, rid, label):
    rec = db.get(coll_name, rid)
    if rec is None:
        raise_err("ERR_NOT_FOUND", f"{label} not found: {rid}")
    return rec


# ---------------------------------------------------------------------------
# season derived counters (PRD §2.5)
# ---------------------------------------------------------------------------

def season_counters(season_id):
    purchased = 0
    for po in db.all_recs("pos"):
        if po["season_id"] == season_id and po["status"] in (
                "ORDERED", "PARTIALLY_DELIVERED", "DELIVERED"):
            purchased += po["quantity"]
    initial_commit = 0
    pending_commit = 0
    for order in db.all_recs("orders"):
        if order["season_id"] != season_id:
            continue
        if order["status"] in ("CONFIRMED", "FULFILLED"):
            initial_commit += order["total_units"]
        elif order["status"] == "SUBMITTED":
            pending_commit += order["total_units"]
    remaining = purchased - initial_commit - pending_commit
    if purchased == 0:
        attainment = None
        provisional = None
    else:
        attainment = float(
            (Decimal(100) * Decimal(initial_commit) / Decimal(purchased))
            .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        provisional = float(
            (Decimal(100) * Decimal(initial_commit + pending_commit) / Decimal(purchased))
            .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return {
        "purchased_units": purchased,
        "initial_commit_units": initial_commit,
        "pending_commit_units": pending_commit,
        "remaining_units": remaining,
        "forecast_attainment_pct": attainment,
        "provisional_attainment_pct": provisional,
    }


def check_auto_selling(season):
    """Automatic OPEN -> SELLING when attainment >= 80 and clock >= opens."""
    if season["status"] != "OPEN":
        return
    c = season_counters(season["id"])
    att = c["forecast_attainment_pct"]
    if att is None:
        return
    if att >= 80.00 and clock.now() >= season["ordering_opens_at"]:
        season["status"] = "SELLING"
        touch(season, bump=True)


def season_json(season):
    c = season_counters(season["id"])
    over_commit = (
        c["forecast_attainment_pct"] is not None
        and c["forecast_attainment_pct"] > 120.00
    )
    return {
        "id": season["id"],
        "code": season["code"],
        "name": season["name"],
        "status": season["status"],
        "ordering_opens_at": season["ordering_opens_at_raw"],
        "ordering_closes_at": season["ordering_closes_at_raw"],
        "initial_commit_units": c["initial_commit_units"],
        "pending_commit_units": c["pending_commit_units"],
        "purchased_units": c["purchased_units"],
        "remaining_units": c["remaining_units"],
        "forecast_attainment_pct": c["forecast_attainment_pct"],
        "provisional_attainment_pct": c["provisional_attainment_pct"],
        "over_commit": over_commit,
        "created_at": season["created_at"],
        "updated_at": season["updated_at"],
        "version": season["version"],
    }


# ---------------------------------------------------------------------------
# site derived fields (PRD §2.8)
# ---------------------------------------------------------------------------

def site_received_units(site):
    total = 0
    for po in db.all_recs("pos"):
        if po["delivery_site_id"] == site["id"] and po["status"] in (
                "PARTIALLY_DELIVERED", "DELIVERED"):
            total += po["delivered_qty"]
    return total


def site_transfer_sums(site):
    hold = 0
    shipped = 0
    for t in db.all_recs("transfers"):
        if t.get("site_id") != site["id"]:
            continue
        if t.get("source_troop_id") is not None:
            continue  # only site-sourced transfers
        if t["status"] in ("REQUESTED", "SHIPPER_SIGNED"):
            # A ship-signature retraction explicitly releases the site hold
            # (PRD §3.4) even though the transfer returns to REQUESTED.
            if t["status"] == "REQUESTED" and t.get("hold_released"):
                continue
            hold += t["package_qty"]
        elif t["status"] in ("RECEIVER_SIGNED", "COMPLETED"):
            shipped += t["package_qty"]
    return hold, shipped


def site_json(site):
    season = db.get("seasons", site["season_id"])
    received = site_received_units(site)
    hold, shipped = site_transfer_sums(site)
    available = received - hold - shipped
    if available < 0:
        available = 0
    if season and season["status"] in ("RECONCILIATION", "CLOSED", "CANCELLED"):
        posture = "FROZEN"
    elif season and season["status"] == "DRAFT":
        posture = "DRAFT"
    elif received >= site["capacity_units"]:
        posture = "FULL"
    else:
        posture = "RECEIVING"
    return {
        "id": site["id"],
        "season_id": site["season_id"],
        "name": site["name"],
        "address": site["address"],
        "capacity_units": site["capacity_units"],
        "received_units": received,
        "hold_units": hold,
        "available_units": available,
        "posture": posture,
        "created_at": site["created_at"],
        "updated_at": site["updated_at"],
        "version": site["version"],
    }


# ---------------------------------------------------------------------------
# account derived fields (PRD §3.7)
# ---------------------------------------------------------------------------

def find_account(troop_id, season_id):
    for a in db.all_recs("accounts"):
        if a["troop_id"] == troop_id and a["season_id"] == season_id:
            return a
    return None


def account_uncollected(account):
    total = 0
    for ag in db.all_recs("agreements"):
        if (ag["troop_id"] == account["troop_id"]
                and ag["season_id"] == account["season_id"]
                and ag["status"] in ("PENDING", "DISPUTED")):
            total += ag["outstanding_cents"]
    return total


def account_json(account):
    return {
        "id": account["id"],
        "troop_id": account["troop_id"],
        "season_id": account["season_id"],
        "balance_cents": account["balance_cents"],
        "proceeds_accrued_cents": account["proceeds_accrued_cents"],
        "uncollected_amount_cents": account_uncollected(account),
        "deposit_cents": account["deposit_cents"],
        "created_at": account["created_at"],
        "updated_at": account["updated_at"],
        "version": account["version"],
    }


# ---------------------------------------------------------------------------
# product / order / misc serializers
# ---------------------------------------------------------------------------

def product_json(p):
    return {
        "id": p["id"],
        "season_id": p["season_id"],
        "variety_code": p["variety_code"],
        "name": p["name"],
        "unit_price_cents": p["unit_price_cents"],
        "troop_proceeds_cents": p["troop_proceeds_cents"],
        "allergen_tags": p["allergen_tags"],
        "packages_per_case": p["packages_per_case"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def troop_json(t):
    return {
        "id": t["id"],
        "troop_number": t["troop_number"],
        "name": t["name"],
        "status": t["status"],
        "service_unit": t["service_unit"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def active_recall_covers(product_id):
    """True when an ACTIVE recall with effective_at <= now covers product."""
    now = clock.now()
    for r in db.all_recs("recalls"):
        if (r["product_id"] == product_id and r["status"] == "ACTIVE"
                and r["effective_at"] <= now):
            return True
    return False


def order_review_required(order):
    """True when a SUBMITTED order contains a product under ACTIVE recall."""
    if order["status"] != "SUBMITTED":
        return False
    for line in db.all_recs("lines"):
        if line["order_id"] == order["id"] and active_recall_covers(line["product_id"]):
            return True
    return False


def order_json(order):
    return {
        "id": order["id"],
        "season_id": order["season_id"],
        "troop_id": order["troop_id"],
        "kind": order["kind"],
        "status": order["status"],
        "total_units": order["total_units"],
        "total_amount_cents": order["total_amount_cents"],
        "rejection_reason": order.get("rejection_reason"),
        "review_required": order_review_required(order),
        "created_at": order["created_at"],
        "updated_at": order["updated_at"],
        "version": order["version"],
    }


def line_json(line):
    return {
        "id": line["id"],
        "order_id": line["order_id"],
        "product_id": line["product_id"],
        "package_qty": line["package_qty"],
        "created_at": line["created_at"],
        "updated_at": line["updated_at"],
        "version": line["version"],
    }


def po_json(po):
    return {
        "id": po["id"],
        "season_id": po["season_id"],
        "baker_name": po["baker_name"],
        "product_id": po["product_id"],
        "quantity": po["quantity"],
        "delivery_site_id": po["delivery_site_id"],
        "status": po["status"],
        "delivered_qty": po["delivered_qty"],
        "created_at": po["created_at"],
        "updated_at": po["updated_at"],
        "version": po["version"],
    }


def transfer_json(t):
    return {
        "id": t["id"],
        "season_id": t["season_id"],
        "source_troop_id": t.get("source_troop_id"),
        "dest_troop_id": t.get("dest_troop_id"),
        "site_id": t.get("site_id"),
        "product_id": t["product_id"],
        "package_qty": t["package_qty"],
        "status": t["status"],
        "shipper_signed_by_troop_id": t.get("shipper_signed_by_troop_id"),
        "receiver_signed_by_troop_id": t.get("receiver_signed_by_troop_id"),
        "counter_transfer_id": t.get("counter_transfer_id"),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def location_json(loc):
    return {
        "id": loc["id"],
        "season_id": loc["season_id"],
        "host_business_name": loc["host_business_name"],
        "address": loc["address"],
        "host_permission_granted": loc["host_permission_granted"],
        "blackout_dates": loc["blackout_dates"],
        "created_at": loc["created_at"],
        "updated_at": loc["updated_at"],
        "version": loc["version"],
    }


def slot_json(slot):
    approved = sum(
        1 for r in db.all_recs("requests")
        if r["slot_id"] == slot["id"] and r["status"] == "APPROVED")
    return {
        "id": slot["id"],
        "location_id": slot["location_id"],
        "start_at": slot["start_at_raw"],
        "end_at": slot["end_at_raw"],
        "capacity_troops": slot["capacity_troops"],
        "approved_count": approved,
        "created_at": slot["created_at"],
        "updated_at": slot["updated_at"],
        "version": slot["version"],
    }


def request_json(r):
    return {
        "id": r["id"],
        "slot_id": r["slot_id"],
        "troop_id": r["troop_id"],
        "mode": r["mode"],
        "lottery_rank": r.get("lottery_rank"),
        "status": r["status"],
        "decision_reason": r.get("decision_reason"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def digital_order_json(o):
    return {
        "id": o["id"],
        "season_id": o["season_id"],
        "troop_id": o["troop_id"],
        "customer_email": o["customer_email"],
        "fulfillment_type": o["fulfillment_type"],
        "donation_units": o["donation_units"],
        "payment_status": o["payment_status"],
        "fulfillment_status": o["fulfillment_status"],
        "total_amount_cents": o["total_amount_cents"],
        "items": o["items"],
        "agreement_id": o.get("agreement_id"),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def season_avg_unit_price(season_id):
    """Average unit price of season products, rounded half-up to integer
    cents exactly once (PRD §2.6)."""
    prods = [p for p in db.all_recs("products") if p["season_id"] == season_id]
    if not prods:
        return 0
    total = sum(p["unit_price_cents"] for p in prods)
    avg = (Decimal(total) / Decimal(len(prods))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(avg)


def agreement_outstanding(ag):
    return max(0, ag["assigned_packages"] * ag["unit_price_at_assignment_cents"]
               - ag["paid_amount_cents"])


def incentive_tier(assigned_packages):
    if assigned_packages >= 100:
        return "GOLD"
    if assigned_packages >= 50:
        return "SILVER"
    if assigned_packages >= 20:
        return "BRONZE"
    return "NONE"


def agreement_json(ag):
    return {
        "id": ag["id"],
        "troop_id": ag["troop_id"],
        "season_id": ag["season_id"],
        "participant_name": ag["participant_name"],
        "parent_name": ag["parent_name"],
        "signed_responsibility": ag["signed_responsibility"],
        "assigned_packages": ag["assigned_packages"],
        "paid_amount_cents": ag["paid_amount_cents"],
        "outstanding_cents": ag["outstanding_cents"],
        "incentive_tier": incentive_tier(ag["assigned_packages"]),
        "status": ag["status"],
        "dispute_reason": ag.get("dispute_reason"),
        "created_at": ag["created_at"],
        "updated_at": ag["updated_at"],
        "version": ag["version"],
    }


def recall_json(r):
    return {
        "id": r["id"],
        "season_id": r["season_id"],
        "product_id": r["product_id"],
        "reason": r["reason"],
        "effective_at": r["effective_at_raw"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
