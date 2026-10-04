"""PurchaseOrder, VendorShipment, Parcel, ReturnRequest, the monolith read and
the logical-clock endpoints (SCAFFOLD §1.5).
"""

from datetime import timedelta

from flask import Blueprint
import auth
import calc
import requtil as R
import services as S
from errors import fail, invalid_request
from response import base_list, created, ok
from store import db, iso, now, ordered, set_clock, stamp, touch
from views import ser, ser_all

bp = Blueprint("buying", __name__)

REASON_CODES = ("DAMAGED", "WRONG_ITEM", "NOT_AS_DESCRIBED", "CHANGED_MIND", "LATE_DELIVERY")
DEFECT_REASONS = ("DAMAGED", "WRONG_ITEM", "NOT_AS_DESCRIBED")
RETURN_WINDOW_DAYS = 30
ESCALATION_WINDOW_HOURS = 72


# ==========================================================================
# PurchaseOrder
# ==========================================================================

@bp.route("/purchase-orders", methods=["POST"])
def create_po():
    auth.require_role(["InventoryPlanner"])
    data = R.body()
    vendor_id = R.bstr(data, "vendor_id")
    event_id = R.bstr(data, "event_id")
    vendor = S.get_or_404("vendors", vendor_id)
    event = S.get_or_404("events", event_id)
    expected = data.get("expected_vendor_version")
    if expected is None:
        invalid_request("expected_vendor_version is required.")
    if not isinstance(expected, int) or isinstance(expected, bool):
        invalid_request("expected_vendor_version must be an integer.")
    if expected != vendor["version"]:
        fail("ERR_STALE_VERSION")
    if vendor["standing"] == "SUSPENDED":
        fail("ERR_VENDOR_SUSPENDED")
    po = {
        "vendor_id": vendor["id"],
        "event_id": event["id"],
        "po_status": "DRAFT",
        "quantity_ordered": 0,
        "quantity_shipped": 0,
        "fill_rate_pct": None,
        "fill_rate_floor_pct": None,
        "due_at": None,
        "issued_at": None,
        "closed_at": None,
    }
    stamp(po)
    db.purchase_orders[po["id"]] = po
    touch(vendor)
    calc.recompute_event_totals(event)
    return created(ser("purchase_orders", po))


@bp.route("/purchase-orders/<po_id>", methods=["GET"])
def read_po(po_id):
    auth.require_role(["Any"])
    po = S.get_or_404("purchase_orders", po_id)
    return ok(ser("purchase_orders", po))


@bp.route("/purchase-orders", methods=["GET"])
def list_pos():
    auth.require_role(["Any"])
    limit, offset = R.pagination()
    vendor_id = R.q("vendor_id")
    event_id = R.q("event_id")
    status = R.q("po_status")
    items = list(db.purchase_orders.values())
    if vendor_id is not None:
        items = [p for p in items if p["vendor_id"] == vendor_id]
    if event_id is not None:
        items = [p for p in items if p["event_id"] == event_id]
    if status is not None:
        items = [p for p in items if p["po_status"] == status]
    return base_list(ser_all("purchase_orders", ordered(items)), limit, offset)


@bp.route("/purchase-orders/<po_id>/lines", methods=["GET"])
def list_po_lines(po_id):
    auth.require_role(["Any"])
    po = S.get_or_404("purchase_orders", po_id)
    limit, offset = R.pagination()
    status = R.q("poline_status")
    items = calc.polines_of_po(po["id"])
    if status is not None:
        items = [l for l in items if l["poline_status"] == status]
    return base_list(ser_all("polines", ordered(items)), limit, offset)


@bp.route("/purchase-orders/<po_id>/shipments", methods=["GET"])
def list_po_shipments(po_id):
    auth.require_role(["Any"])
    po = S.get_or_404("purchase_orders", po_id)
    limit, offset = R.pagination()
    status = R.q("shipment_status")
    items = calc.shipments_of_po(po["id"])
    if status is not None:
        items = [s for s in items if s["shipment_status"] == status]
    return base_list(ser_all("shipments", ordered(items)), limit, offset)


@bp.route("/purchase-orders/<po_id>/add-line", methods=["POST"])
def add_poline(po_id):
    auth.require_role(["InventoryPlanner"])
    data = R.body()
    po = S.get_or_404("purchase_orders", po_id)
    listing_id = R.bstr(data, "listing_id")
    quantity = R.bint(data, "quantity_ordered")
    listing = S.get_or_404("listings", listing_id)
    if quantity < 0:
        invalid_request("quantity_ordered must be non-negative.")
    if po["po_status"] not in ("DRAFT",):
        fail("ERR_INVALID_STATE")
    if listing["event_id"] != po["event_id"]:
        fail("ERR_LISTING_EVENT_MISMATCH")
    line = {
        "purchase_order_id": po["id"],
        "listing_id": listing["id"],
        "quantity_ordered": quantity,
        "quantity_confirmed": 0,
        "quantity_shipped": 0,
        "poline_status": "OPEN",
    }
    stamp(line)
    db.polines[line["id"]] = line
    po["quantity_ordered"] = sum(
        l["quantity_ordered"] for l in calc.polines_of_po(po["id"])
    )
    touch(po)
    calc.recompute_event_totals(db.events.get(po["event_id"]))
    return created(ser("polines", line))


@bp.route("/purchase-orders/<po_id>/issue", methods=["POST"])
def issue_po(po_id):
    auth.require_role(["InventoryPlanner"])
    data = R.body()
    po = S.get_or_404("purchase_orders", po_id)
    vendor = S.get_or_404("vendors", po["vendor_id"])
    event = S.get_or_404("events", po["event_id"])
    if po["po_status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    expected = data.get("expected_vendor_version")
    if expected is None:
        invalid_request("expected_vendor_version is required.")
    if not isinstance(expected, int) or isinstance(expected, bool):
        invalid_request("expected_vendor_version must be an integer.")
    if expected != vendor["version"]:
        fail("ERR_STALE_VERSION")
    allow_probation = R.bbool(data, "allow_probation_vendor", False)
    if vendor["standing"] == "SUSPENDED":
        fail("ERR_VENDOR_SUSPENDED")
    if vendor["standing"] == "PROBATION" and not allow_probation:
        fail("ERR_VENDOR_STANDING_BLOCKED")
    if event["event_status"] != "LIVE":
        fail("ERR_INVALID_STATE")
    polines = calc.polines_of_po(po["id"])
    if not any(l["quantity_ordered"] > 0 for l in polines):
        fail("ERR_EMPTY_PURCHASE_ORDER")
    po["po_status"] = "ISSUED"
    po["issued_at"] = now()
    po["due_at"] = now() + timedelta(days=calc.DUE_DAYS_TOTAL)
    po["fill_rate_floor_pct"] = vendor["fill_rate_floor_pct"]
    po["quantity_ordered"] = sum(l["quantity_ordered"] for l in polines)
    po["fill_rate_pct"] = calc.projected_rate(po)
    touch(po)
    touch(vendor)
    for listing_id in {l["listing_id"] for l in polines}:
        for line in calc.lines_of_listing(listing_id):
            if line["confirmation_status"] != "VENDOR_CONFIRMED":
                continue
            line["confirmation_status"] = "PURCHASE_ORDER_ISSUED"
            touch(line)
            order = db.orders.get(line["customer_order_id"])
            if order is not None:
                order["cancellation_waived"] = True
                touch(order)
    calc.recompute_event_totals(event)
    return ok(ser("purchase_orders", po))


@bp.route("/purchase-orders/<po_id>/close-short", methods=["POST"])
def close_short(po_id):
    auth.require_role(["InventoryPlanner"])
    data = R.body()
    po = S.get_or_404("purchase_orders", po_id)
    force = R.bbool(data, "force_close", False)
    if po["po_status"] not in ("ISSUED", "PARTIALLY_FILLED"):
        fail("ERR_INVALID_STATE")
    if not force:
        due_at = po.get("due_at")
        if due_at is None or now() < due_at:
            fail("ERR_INVALID_STATE")
    vendor = db.vendors.get(po["vendor_id"])
    po["po_status"] = "CLOSED_SHORT"
    po["closed_at"] = now()
    ordered_units = po["quantity_ordered"] or 0
    shipped_units = po["quantity_shipped"] or 0
    if ordered_units > 0:
        po["fill_rate_pct"] = float(calc.rhu(
            __import__("decimal").Decimal(shipped_units) / __import__("decimal").Decimal(ordered_units), 4
        ))
    touch(po)
    if vendor is not None:
        vendor["rolling_fill_rate_units_shipped"] += shipped_units
        vendor["rolling_fill_rate_units_ordered"] += ordered_units
        touch(vendor)

    # CASCADE 1 -> 2: POLines short of their confirmed quantity
    short_polines = []
    for line in calc.polines_of_po(po["id"]):
        if line["quantity_shipped"] < line["quantity_confirmed"]:
            line["poline_status"] = "CLOSED_SHORT"
            touch(line)
            short_polines.append(line)

    # CASCADE 2 -> 3: Confirmations on those listings short of their quantity
    affected_orders = []
    for poline in short_polines:
        for line in calc.lines_of_listing(poline["listing_id"]):
            if line["confirmation_status"] in ("CANCELLED", "SHORT_SHIPPED"):
                continue
            if line["confirmation_status"] not in (
                "VENDOR_CONFIRMED", "PURCHASE_ORDER_ISSUED",
                "IN_TRANSIT_TO_CROSS_DOCK", "RECEIVED_AT_CROSS_DOCK",
            ):
                continue
            confirmed = line.get("confirmed_units")
            if confirmed is None or confirmed >= line["quantity"]:
                continue
            line["confirmation_status"] = "SHORT_SHIPPED"
            line["short_shipped_units"] = line["quantity"] - confirmed
            touch(line)
            calc.recompute_line_refund(line)
            if line["customer_order_id"] not in affected_orders:
                affected_orders.append(line["customer_order_id"])
            for parcel in db.parcels.values():
                if line["id"] in parcel["contained_line_ids"]:
                    parcel["contained_line_ids"] = [
                        i for i in parcel["contained_line_ids"] if i != line["id"]
                    ]
                    touch(parcel)

    # CASCADE 3 -> 4: recompute affected orders; drop the short lines from parcels
    for order_id in affected_orders:
        order = db.orders.get(order_id)
        if order is None:
            continue
        calc.recompute_order_total(order)
        calc.recompute_order_refund(order)
        touch(order)
        if order["order_status"] in ("AWAITING_VENDOR", "PARTIALLY_FILLED"):
            order["order_status"] = "PARTIALLY_FILLED"
            order["payment_status"] = "PARTIALLY_REFUNDED"
            touch(order)
    calc.recompute_event_totals(db.events.get(po["event_id"]))
    return ok(ser("purchase_orders", po))


@bp.route("/purchase-orders/<po_id>/reopen", methods=["POST"])
def reopen_po(po_id):
    auth.require_role(["InventoryPlanner"])
    po = S.get_or_404("purchase_orders", po_id)
    if po["po_status"] != "CLOSED_SHORT":
        fail("ERR_INVALID_STATE")
    event = S.get_or_404("events", po["event_id"])
    if event["event_status"] not in ("LIVE", "CLOSED"):
        fail("ERR_INVALID_STATE")
    closed_at = po.get("closed_at")
    for shipment in calc.shipments_of_po(po["id"]):
        reported_at = shipment.get("created_at")
        if closed_at is not None and reported_at is not None and reported_at > closed_at:
            fail("ERR_INVALID_STATE")

    demand_by_listing = {}
    for poline in calc.polines_of_po(po["id"]):
        listing = db.listings.get(poline["listing_id"])
        if listing is None:
            continue
        demand_by_listing[listing["id"]] = calc.computed_units_ordered(listing["id"])

    po["po_status"] = "ISSUED"
    po["quantity_shipped"] = 0
    po["fill_rate_pct"] = None
    po["closed_at"] = None
    po["quantity_ordered"] = sum(demand_by_listing.values())
    touch(po)
    for poline in calc.polines_of_po(po["id"]):
        poline["quantity_confirmed"] = 0
        poline["quantity_shipped"] = 0
        poline["quantity_ordered"] = demand_by_listing.get(poline["listing_id"], 0)
        poline["poline_status"] = (
            "OPEN" if poline["quantity_ordered"] > 0 else "OPEN"
        )
        touch(poline)
    for listing_id in demand_by_listing:
        for line in calc.lines_of_listing(listing_id):
            if line["confirmation_status"] == "SHORT_SHIPPED":
                line["confirmation_status"] = "VENDOR_CONFIRMED"
                line["confirmed_units"] = None
                line["short_shipped_units"] = 0
                touch(line)
                calc.recompute_line_refund(line)
                order = db.orders.get(line["customer_order_id"])
                if order is not None:
                    S.refresh_order_derived(order)
                    touch(order)
    calc.recompute_event_totals(event)
    return ok(ser("purchase_orders", po))


@bp.route("/purchase-orders/<po_id>/cancel", methods=["POST"])
def cancel_po(po_id):
    auth.require_role(["InventoryPlanner"])
    data = R.body()
    R.bstr(data, "reason_code", required=False)
    po = S.get_or_404("purchase_orders", po_id)
    if po["po_status"] not in ("DRAFT", "ISSUED"):
        fail("ERR_INVALID_STATE")
    if (po["quantity_shipped"] or 0) != 0:
        fail("ERR_INVALID_STATE")
    po["po_status"] = "CANCELLED"
    po["closed_at"] = now()
    touch(po)
    S.revert_buy_commitment(po)
    calc.recompute_event_totals(db.events.get(po["event_id"]))
    return ok(ser("purchase_orders", po))


# ==========================================================================
# VendorShipment
# ==========================================================================

def _covered_lines_for(po, allocations):
    """The Confirmations whose listing this shipment's allocations name.

    Derived at the moment it is needed rather than frozen at report time, so a
    line that is bought after the shipment was reported still receives its
    transit/receipt transitions.
    """
    listing_ids = {a["listing_id"] for a in allocations}
    covered = []
    for line in calc.all_confirmations():
        if line["listing_id"] not in listing_ids:
            continue
        if line["confirmation_status"] in (
            "PURCHASE_ORDER_ISSUED", "IN_TRANSIT_TO_CROSS_DOCK",
            "RECEIVED_AT_CROSS_DOCK",
        ):
            covered.append(line["id"])
    return covered


@bp.route("/vendor-shipments", methods=["POST"])
def create_shipment():
    uid, role = auth.require_role(["Vendor"])
    data = R.body()
    po_id = R.bstr(data, "purchase_order_id")
    po = S.get_or_404("purchase_orders", po_id)
    if role == "Vendor":
        auth.require_owner(uid, role, po["vendor_id"])
    else:
        fail("ERR_FORBIDDEN_FOR_ROLE")
    vendor = S.get_or_404("vendors", po["vendor_id"])
    if vendor["standing"] == "SUSPENDED":
        fail("ERR_VENDOR_SUSPENDED")
    if vendor["standing"] == "PROBATION" and not R.bbool(data, "allow_probation_vendor", False):
        fail("ERR_VENDOR_STANDING_BLOCKED")
    if po["po_status"] not in ("ISSUED", "PARTIALLY_FILLED"):
        fail("ERR_INVALID_STATE")
    quantity = R.bint(data, "quantity_shipped")
    if quantity <= 0:
        invalid_request("quantity_shipped must be strictly positive.")
    tracking = R.bstr(data, "carrier_tracking_code")
    shipped_at = R.btime(data, "shipped_at")
    allocations = data.get("allocations")
    if allocations is None:
        invalid_request("allocations is required.")
    if not isinstance(allocations, list):
        invalid_request("allocations must be an array.")
    normalized = []
    for entry in allocations:
        if not isinstance(entry, dict):
            invalid_request("Each allocation must be an object.")
        listing_id = entry.get("listing_id")
        qty = entry.get("quantity")
        if not isinstance(listing_id, str) or not isinstance(qty, int) or isinstance(qty, bool):
            invalid_request("Each allocation needs a listing_id and an integer quantity.")
        listing = S.get_or_404("listings", listing_id)
        if listing["event_id"] != po["event_id"]:
            fail("ERR_LISTING_EVENT_MISMATCH")
        poline = None
        for candidate in calc.polines_of_po(po["id"]):
            if candidate["listing_id"] == listing["id"]:
                poline = candidate
                break
        if poline is None:
            fail("ERR_SHIPMENT_PO_MISMATCH")
        normalized.append({"listing_id": listing["id"], "quantity": qty})

    cumulative = sum(
        s["quantity_shipped"] for s in calc.shipments_of_po(po["id"])
        if s["shipment_status"] != "REJECTED"
    )
    if cumulative + quantity > (po["quantity_ordered"] or 0):
        fail("ERR_SHIPMENT_EXCEEDS_PO")
    for entry in normalized:
        poline = None
        for candidate in calc.polines_of_po(po["id"]):
            if candidate["listing_id"] == entry["listing_id"]:
                poline = candidate
                break
        if poline is None:
            fail("ERR_SHIPMENT_PO_MISMATCH")
        if poline["quantity_shipped"] + entry["quantity"] > poline["quantity_confirmed"]:
            fail("ERR_SHIPMENT_EXCEEDS_PO")
    # fill-rate ramp gate
    if not calc.shipment_admitted(po, quantity):
        fail("ERR_FILL_RATE_BELOW_FLOOR")

    shipment = {
        "purchase_order_id": po["id"],
        "quantity_shipped": quantity,
        "carrier_tracking_code": tracking,
        "shipped_at": shipped_at,
        "arrived_at": None,
        "shipment_status": "REPORTED",
        "allocations": normalized,
        "rejection_reason_code": None,
        "covered_line_ids": _covered_lines_for(po, normalized),
    }
    stamp(shipment)
    db.shipments[shipment["id"]] = shipment

    po["quantity_shipped"] = cumulative + quantity
    if po["po_status"] == "ISSUED":
        po["po_status"] = "PARTIALLY_FILLED"
    if po["fill_rate_pct"] is None:
        po["fill_rate_pct"] = float(calc.projected_rate(po))
    else:
        po["fill_rate_pct"] = float(calc.projected_rate(po))
    touch(po)
    for entry in normalized:
        for candidate in calc.polines_of_po(po["id"]):
            if candidate["listing_id"] == entry["listing_id"]:
                candidate["quantity_shipped"] += entry["quantity"]
                if (candidate["quantity_shipped"] >= candidate["quantity_confirmed"]
                        and candidate["quantity_confirmed"] > 0):
                    candidate["poline_status"] = "FILLED"
                touch(candidate)
    _maybe_fill_po(po)
    return created(ser("shipments", shipment))


def _maybe_fill_po(po, vendor=None):
    """A buy fills only when every line's confirmed quantity equals its ordered
    quantity and every line has shipped what it confirmed.

    A line that reaches quantity_shipped == quantity_confirmed is FILLED on its
    own record, but the *buy* is not: its fill_rate_pct would not be 1.0000, and
    an under-confirmed buy is exactly the case close-short exists for.
    """
    polines = calc.polines_of_po(po["id"])
    if not polines:
        return False
    relevant = [l for l in polines if l["quantity_ordered"] > 0]
    if not relevant:
        return False
    for line in relevant:
        if line["quantity_confirmed"] != line["quantity_ordered"]:
            return False
        if line["quantity_shipped"] < line["quantity_confirmed"]:
            return False
    if po["po_status"] not in ("ISSUED", "PARTIALLY_FILLED"):
        return False
    po["po_status"] = "FILLED"
    po["closed_at"] = now()
    po["fill_rate_pct"] = 1.0000
    touch(po)
    vendor = vendor or db.vendors.get(po["vendor_id"])
    if vendor is not None:
        vendor["rolling_fill_rate_units_shipped"] += po["quantity_ordered"]
        vendor["rolling_fill_rate_units_ordered"] += po["quantity_ordered"]
        touch(vendor)
    for line in calc.all_confirmations():
        if line["confirmation_status"] in (
            "PURCHASE_ORDER_ISSUED", "IN_TRANSIT_TO_CROSS_DOCK",
        ):
            listing = db.listings.get(line["listing_id"])
            if listing is None or listing["event_id"] != po["event_id"]:
                continue
            line["confirmation_status"] = "IN_TRANSIT_TO_CROSS_DOCK"
            touch(line)
    return True


@bp.route("/vendor-shipments/<shipment_id>", methods=["GET"])
def read_shipment(shipment_id):
    auth.require_role(["Any"])
    shipment = S.get_or_404("shipments", shipment_id)
    return ok(ser("shipments", shipment))


@bp.route("/vendor-shipments", methods=["GET"])
def list_shipments():
    auth.require_role(["Any"])
    limit, offset = R.pagination()
    po_id = R.q("purchase_order_id")
    status = R.q("shipment_status")
    items = list(db.shipments.values())
    if po_id is not None:
        items = [s for s in items if s["purchase_order_id"] == po_id]
    if status is not None:
        items = [s for s in items if s["shipment_status"] == status]
    return base_list(ser_all("shipments", ordered(items)), limit, offset)


@bp.route("/vendor-shipments/<shipment_id>/receive", methods=["POST"])
def receive_shipment(shipment_id):
    auth.require_role(["CrossDockOperator"])
    data = R.body()
    shipment = S.get_or_404("shipments", shipment_id)
    po = S.get_or_404("purchase_orders", shipment["purchase_order_id"])
    arrived = R.btime(data, "arrived_at", required=False) or now()
    # `bucket_units_reported` is accepted for compatibility; the bucket occupied
    # figure is always derived from the shipments actually in RECEIVED state.
    status = shipment["shipment_status"]
    covered = _covered_lines_for(po, shipment["allocations"])

    if status == "REJECTED":
        fail("ERR_INVALID_STATE")

    if status == "REPORTED":
        # Hop 1: REPORTED -> IN_TRANSIT, admitted when the reported instant has
        # arrived (PRD §3.5). The same call then continues into hop 2 below, so
        # one receive "advances it to IN_TRANSIT or RECEIVED" — a receive landing
        # after the shipment has already arrived reaches RECEIVED directly.
        shipped_at = shipment.get("shipped_at")
        if shipped_at is not None and shipped_at > now():
            fail("ERR_INVALID_STATE")
        shipment["shipment_status"] = "IN_TRANSIT"
        shipment["arrived_at"] = arrived
        touch(shipment)
        for line_id in covered:
            line = db.confirmations.get(line_id)
            if line is not None and line["confirmation_status"] == "PURCHASE_ORDER_ISSUED":
                line["confirmation_status"] = "IN_TRANSIT_TO_CROSS_DOCK"
                touch(line)
        status = "IN_TRANSIT"

    if status != "IN_TRANSIT":
        # Already RECEIVED: the receive is idempotent and changes nothing.
        return ok(ser("shipments", shipment))

    for line_id in covered:
        line = db.confirmations.get(line_id)
        if line is None:
            continue
        if line["confirmation_status"] not in ("IN_TRANSIT_TO_CROSS_DOCK", "RECEIVED_AT_CROSS_DOCK"):
            fail("ERR_INVALID_STATE")

    if calc.bucket_occupied(arrived, exclude_id=shipment["id"]) + shipment["quantity_shipped"] \
            > calc.BUCKET_CAPACITY_UNITS:
        fail("ERR_DOCK_BUCKET_CAPACITY_EXCEEDED")

    shipment["shipment_status"] = "RECEIVED"
    # The received instant is the request's arrived_at — the same instant the
    # bucket capacity above was judged against, so the shipment lands in the
    # bucket it was admitted into. (It defaults to the logical clock.)
    shipment["arrived_at"] = arrived
    touch(shipment)
    for line_id in covered:
        line = db.confirmations.get(line_id)
        if line is not None:
            line["confirmation_status"] = "RECEIVED_AT_CROSS_DOCK"
            touch(line)
    # cascade: POLine.quantity_shipped += the per-listing allocation, capped
    for entry in shipment["allocations"]:
        for poline in calc.polines_of_po(po["id"]):
            if poline["listing_id"] != entry["listing_id"]:
                continue
            cap = poline["quantity_confirmed"]
            gain = min(entry["quantity"], max(0, cap - poline["quantity_shipped"]))
            poline["quantity_shipped"] += gain
            if (poline["quantity_confirmed"] > 0
                    and poline["quantity_shipped"] >= poline["quantity_confirmed"]):
                poline["poline_status"] = "FILLED"
            touch(poline)
    _maybe_fill_po(po)
    for parcel in db.parcels.values():
        if parcel["parcel_status"] == "FORMING":
            parcel["vendor_shipment_count"] += 1
            touch(parcel)
    return ok(ser("shipments", shipment))


@bp.route("/vendor-shipments/<shipment_id>/reject", methods=["POST"])
def reject_shipment(shipment_id):
    auth.require_role(["CrossDockOperator"])
    data = R.body()
    shipment = S.get_or_404("shipments", shipment_id)
    po = S.get_or_404("purchase_orders", shipment["purchase_order_id"])
    reason = R.bstr(data, "reason_code", required=False)
    if reason is None:
        invalid_request("A rejection reason code is required.")
    if shipment["shipment_status"] not in ("REPORTED", "IN_TRANSIT"):
        fail("ERR_INVALID_STATE")
    shipment["shipment_status"] = "REJECTED"
    shipment["rejection_reason_code"] = reason
    touch(shipment)
    remaining = sum(
        s["quantity_shipped"] for s in calc.shipments_of_po(po["id"])
        if s["shipment_status"] != "REJECTED"
    )
    po["quantity_shipped"] = remaining
    if remaining == 0 and po["po_status"] == "PARTIALLY_FILLED":
        po["po_status"] = "ISSUED"
    po["fill_rate_pct"] = float(calc.projected_rate(po))
    touch(po)
    for line_id in _covered_lines_for(po, shipment["allocations"]):
        line = db.confirmations.get(line_id)
        if line is None:
            continue
        if line["confirmation_status"] != "IN_TRANSIT_TO_CROSS_DOCK":
            continue
        still_covered = False
        for other in calc.shipments_of_po(po["id"]):
            if other["id"] == shipment["id"] or other["shipment_status"] == "REJECTED":
                continue
            if line_id in _covered_lines_for(po, other["allocations"]):
                still_covered = True
                break
        if not still_covered:
            line["confirmation_status"] = "PURCHASE_ORDER_ISSUED"
            touch(line)
    return ok(ser("shipments", shipment))


# ==========================================================================
# Parcel
# ==========================================================================

@bp.route("/parcels/<parcel_id>", methods=["GET"])
def read_parcel(parcel_id):
    auth.require_role(["Any"])
    parcel = S.get_or_404("parcels", parcel_id)
    return ok(ser("parcels", parcel))


@bp.route("/parcels", methods=["GET"])
def list_parcels():
    auth.require_role(["Any"])
    limit, offset = R.pagination()
    order_id = R.q("customer_order_id")
    status = R.q("parcel_status")
    items = list(db.parcels.values())
    if order_id is not None:
        items = [p for p in items if p["customer_order_id"] == order_id]
    if status is not None:
        items = [p for p in items if p["parcel_status"] == status]
    return base_list(ser_all("parcels", ordered(items)), limit, offset)


@bp.route("/parcels/<parcel_id>/seal", methods=["POST"])
def seal_parcel(parcel_id):
    auth.require_role(["CrossDockOperator"])
    parcel = S.get_or_404("parcels", parcel_id)
    if parcel["parcel_status"] != "FORMING":
        fail("ERR_INVALID_STATE")
    order = S.get_or_404("orders", parcel["customer_order_id"])
    if order["payment_status"] not in ("CAPTURED", "PARTIALLY_REFUNDED"):
        fail("ERR_INVALID_STATE")
    calc.recompute_order_refund(order)
    if order["refund_due_cents"] != 0:
        fail("ERR_REFUND_OUTSTANDING")
    for line_id in parcel["contained_line_ids"]:
        line = db.confirmations.get(line_id)
        if line is None or line["confirmation_status"] != "SHIPPED":
            fail("ERR_INVALID_STATE")
        if not __import__("routes_orders")._line_has_received_shipment(line):
            fail("ERR_INVALID_STATE")
    parcel["parcel_status"] = "SEALED"
    parcel["sealed_at"] = now()
    parcel["dispatch_eta"] = calc.dispatch_eta(parcel, parcel["sealed_at"])
    touch(parcel)
    return ok(ser("parcels", parcel))


@bp.route("/parcels/<parcel_id>/dispatch", methods=["POST"])
def dispatch_parcel(parcel_id):
    auth.require_role(["CrossDockOperator"])
    parcel = S.get_or_404("parcels", parcel_id)
    if parcel["parcel_status"] != "SEALED":
        fail("ERR_INVALID_STATE")
    parcel["parcel_status"] = "DISPATCHED"
    parcel["dispatch_eta"] = calc.dispatch_eta(parcel, parcel.get("sealed_at") or now())
    touch(parcel)
    order = db.orders.get(parcel["customer_order_id"])
    if order is not None:
        order["order_status"] = "SHIPPED"
        touch(order)
    return ok(ser("parcels", parcel))


@bp.route("/parcels/<parcel_id>/deliver", methods=["POST"])
def deliver_parcel(parcel_id):
    auth.require_role(["CrossDockOperator"])
    parcel = S.get_or_404("parcels", parcel_id)
    if parcel["parcel_status"] != "DISPATCHED":
        fail("ERR_INVALID_STATE")
    parcel["parcel_status"] = "DELIVERED"
    touch(parcel)
    order = db.orders.get(parcel["customer_order_id"])
    if order is not None and order["order_status"] != "CANCELLED":
        order["order_status"] = "DELIVERED"
        order["cancellation_waived"] = True
        touch(order)
    return ok(ser("parcels", parcel))


# ==========================================================================
# ReturnRequest
# ==========================================================================

@bp.route("/returns", methods=["POST"])
def create_return():
    uid, role = auth.require_role(["Customer", "CustomerService"])
    data = R.body()
    confirmation_id = R.bstr(data, "confirmation_id")
    reason = R.benum(data, "reason_code", REASON_CODES)
    line = S.get_or_404("confirmations", confirmation_id)
    order = S.get_or_404("orders", line["customer_order_id"])
    if role == "Customer":
        auth.require_owner(uid, role, order["customer_id"])
    expected = data.get("expected_confirmation_version")
    if expected is None:
        invalid_request("expected_confirmation_version is required.")
    if not isinstance(expected, int) or isinstance(expected, bool):
        invalid_request("expected_confirmation_version must be an integer.")
    if expected != line["version"]:
        fail("ERR_STALE_VERSION")
    if line["confirmation_status"] not in ("SHIPPED", "SHORT_SHIPPED"):
        fail("ERR_INVALID_STATE")
    request_row = {
        "confirmation_id": line["id"],
        "reason_code": reason,
        "return_status": "REQUESTED",
        "settlement_basis": None,
        "settlement_amount_cents": None,
        "cs_user_id": None,
        "decided_at": None,
        "ai_decided_at": None,
        "goodwill_cents": None,
    }
    stamp(request_row)
    db.returns[request_row["id"]] = request_row
    touch(line)
    return created(ser("returns", request_row))


@bp.route("/returns/<return_id>", methods=["GET"])
def read_return(return_id):
    auth.require_role(["Any"])
    request_row = S.get_or_404("returns", return_id)
    return ok(ser("returns", request_row))


@bp.route("/returns", methods=["GET"])
def list_returns():
    auth.require_role(["Any"])
    limit, offset = R.pagination()
    status = R.q("return_status")
    reason = R.q("reason_code")
    items = list(db.returns.values())
    if status is not None:
        items = [r for r in items if r["return_status"] == status]
    if reason is not None:
        items = [r for r in items if r["reason_code"] == reason]
    return base_list(ser_all("returns", ordered(items)), limit, offset)


def _delivered_at(order_id):
    latest = None
    for parcel in db.parcels.values():
        if parcel["customer_order_id"] != order_id:
            continue
        if parcel["parcel_status"] != "DELIVERED":
            continue
        stamp_at = parcel.get("updated_at") or parcel.get("created_at")
        if latest is None or (stamp_at and stamp_at > latest):
            latest = stamp_at
    return latest


def _is_partial_multi_line_return(order, line):
    lines = [l for l in calc.lines_of_order(order["id"])
             if l["confirmation_status"] != "CANCELLED"]
    if len(lines) <= 1:
        return False
    for other in lines:
        if other["id"] == line["id"]:
            continue
        if not calc.returns_of_confirmation(other["id"]):
            return True
    return False


@bp.route("/returns/<return_id>/adjudicate", methods=["POST"])
def adjudicate_return(return_id):
    auth.require_role(["CustomerService"])
    request_row = S.get_or_404("returns", return_id)
    if request_row["return_status"] != "REQUESTED":
        fail("ERR_INVALID_STATE")
    line = S.get_or_404("confirmations", request_row["confirmation_id"])
    order = S.get_or_404("orders", line["customer_order_id"])
    reason = request_row["reason_code"]

    if _is_partial_multi_line_return(order, line):
        request_row["return_status"] = "CS_REVIEW"
        touch(request_row)
        return ok(ser("returns", request_row))

    if reason in DEFECT_REASONS:
        delivered = _delivered_at(order["id"])
        if delivered is not None and now() > delivered + timedelta(days=RETURN_WINDOW_DAYS):
            request_row["return_status"] = "CS_REVIEW"
            touch(request_row)
            return ok(ser("returns", request_row))
        request_row["return_status"] = "AI1_APPROVED"
        request_row["settlement_basis"] = "REFUND"
        request_row["settlement_amount_cents"] = (
            (line.get("line_unit_price_cents") or 0) * (line.get("confirmed_units") or 0)
        )
        request_row["ai_decided_at"] = now()
        touch(request_row)
        return ok(ser("returns", request_row))

    if reason == "CHANGED_MIND":
        request_row["return_status"] = "AI1_DENIED"
        request_row["settlement_basis"] = "NONE"
        request_row["settlement_amount_cents"] = 0
        request_row["ai_decided_at"] = now()
        touch(request_row)
        return ok(ser("returns", request_row))

    # LATE_DELIVERY: neither branch applies automatically
    request_row["return_status"] = "CS_REVIEW"
    touch(request_row)
    return ok(ser("returns", request_row))


@bp.route("/returns/<return_id>/escalate", methods=["POST"])
def escalate_return(return_id):
    uid, role = auth.require_role(["Customer", "CustomerService"])
    request_row = S.get_or_404("returns", return_id)
    line = S.get_or_404("confirmations", request_row["confirmation_id"])
    order = S.get_or_404("orders", line["customer_order_id"])
    if role == "Customer":
        auth.require_owner(uid, role, order["customer_id"])
    if request_row["return_status"] != "AI1_DENIED":
        fail("ERR_INVALID_STATE")
    if S.escalate_count(request_row["id"]) >= 2:
        fail("ERR_INVALID_STATE")
    S.record_escalation(request_row["id"])
    request_row["return_status"] = "CS_REVIEW"
    request_row["cs_user_id"] = None
    touch(request_row)
    return ok(ser("returns", request_row))


@bp.route("/returns/<return_id>/decide", methods=["POST"])
def decide_return(return_id):
    uid, role = auth.require_role(["CustomerService"])
    data = R.body()
    request_row = S.get_or_404("returns", return_id)
    decision = R.benum(data, "decision", ("APPROVE", "DENY"))
    if request_row["return_status"] != "CS_REVIEW":
        fail("ERR_INVALID_STATE")
    line = S.get_or_404("confirmations", request_row["confirmation_id"])
    order = S.get_or_404("orders", line["customer_order_id"])
    customer = S.get_or_404("customers", order["customer_id"])

    if decision == "DENY":
        request_row["return_status"] = "DENIED"
        request_row["settlement_basis"] = "NONE"
        request_row["settlement_amount_cents"] = 0
        request_row["cs_user_id"] = uid
        request_row["decided_at"] = now()
        request_row["goodwill_cents"] = None
        touch(request_row)
        return ok(ser("returns", request_row))

    goodwill_requested = data.get("goodwill_adjustment_cents")
    if goodwill_requested is None:
        goodwill_requested = 0
    if not isinstance(goodwill_requested, int) or isinstance(goodwill_requested, bool):
        invalid_request("goodwill_adjustment_cents must be an integer.")
    if goodwill_requested < 0:
        invalid_request("goodwill_adjustment_cents may not be negative.")

    headroom = calc.ANNUAL_CAP_CENTS - (customer["lifetime_credit_issued_cents"] or 0)
    if goodwill_requested > 0:
        if headroom <= 0:
            fail("ERR_GOODWILL_CAP_EXCEEDED")
        granted = min(goodwill_requested, headroom)
    else:
        granted = 0

    reason = request_row["reason_code"]
    basis = "STORE_CREDIT" if reason == "CHANGED_MIND" else "REFUND"
    goods = (line.get("line_unit_price_cents") or 0) * (line.get("confirmed_units") or 0)
    request_row["return_status"] = "APPROVED"
    request_row["settlement_basis"] = basis
    request_row["settlement_amount_cents"] = goods + granted
    request_row["goodwill_cents"] = granted
    request_row["cs_user_id"] = uid
    request_row["decided_at"] = now()
    touch(request_row)
    return ok(ser("returns", request_row))


@bp.route("/returns/<return_id>/receive", methods=["POST"])
def receive_return(return_id):
    auth.require_role(["CrossDockOperator"])
    request_row = S.get_or_404("returns", return_id)
    # AI1_APPROVED is the automatic first pass's flavour of APPROVED — only
    # AI1_DENIED has a separate later closure step (PRD §3.8) — so both reach
    # RECEIVED.
    if request_row["return_status"] not in ("APPROVED", "AI1_APPROVED"):
        fail("ERR_INVALID_STATE")
    request_row["return_status"] = "RECEIVED"
    touch(request_row)
    line = db.confirmations.get(request_row["confirmation_id"])
    if line is not None:
        order = db.orders.get(line["customer_order_id"])
        if order is not None:
            all_refunded = True
            for other in calc.lines_of_order(order["id"]):
                if other["confirmation_status"] == "CANCELLED":
                    continue
                if not calc.has_refunded_return(other):
                    all_refunded = False
                    break
            if all_refunded:
                order["order_status"] = "RETURNED"
                touch(order)
    return ok(ser("returns", request_row))


@bp.route("/returns/<return_id>/settle", methods=["POST"])
def settle_return(return_id):
    auth.require_role(["InventoryPlanner", "CustomerService"])
    data = R.body()
    request_row = S.get_or_404("returns", return_id)
    key = R.bstr(data, "idempotency_key")
    if key in db.idem:
        row = db.ledger.get(db.idem[key])
        if row is not None:
            return ok(ser("returns", request_row))
    if request_row["return_status"] != "RECEIVED":
        fail("ERR_INVALID_STATE")
    if request_row["settlement_basis"] not in ("REFUND", "STORE_CREDIT"):
        fail("ERR_INVALID_STATE")
    line = S.get_or_404("confirmations", request_row["confirmation_id"])
    order = S.get_or_404("orders", line["customer_order_id"])
    customer = S.get_or_404("customers", order["customer_id"])
    amount = request_row["settlement_amount_cents"] or 0
    if amount <= 0:
        fail("ERR_INVALID_STATE")
    row, _ = S.ledger_issue(
        customer["id"], "RETURN_GOODWILL", request_row["id"], amount,
        idempotency_key=key,
    )
    customer["lifetime_credit_issued_cents"] += request_row.get("goodwill_cents") or 0
    touch(customer)
    request_row["return_status"] = "REFUNDED"
    touch(request_row)
    S.reconcile_customer(customer)
    order_check = order
    all_refunded = True
    for other in calc.lines_of_order(order_check["id"]):
        if other["confirmation_status"] == "CANCELLED":
            continue
        if not calc.has_refunded_return(other):
            all_refunded = False
            break
    if all_refunded and order_check["order_status"] not in ("CANCELLED",):
        order_check["order_status"] = "RETURNED"
        touch(order_check)
    return ok(ser("returns", request_row))


# ==========================================================================
# Monolith read
# ==========================================================================

@bp.route("/vendor-orders/<order_id>", methods=["GET"])
def vendor_order_view(order_id):
    auth.require_role(["Any"])
    order = S.get_or_404("orders", order_id)
    lines = calc.lines_of_order(order["id"])
    pos = []
    shipments = []
    seen = set()
    for line in lines:
        po, _poline = calc.po_of_listing(line["listing_id"])
        if po is not None and po["id"] not in seen:
            seen.add(po["id"])
            pos.append(po)
            shipments.extend(calc.shipments_of_po(po["id"]))
    parcels = [p for p in db.parcels.values() if p["customer_order_id"] == order["id"]]
    returns = []
    for line in lines:
        returns.extend(calc.returns_of_confirmation(line["id"]))
    return ok({
        "order": ser("orders", order),
        "lines": ser_all("confirmations", ordered(lines)),
        "purchase_orders": ser_all("purchase_orders", ordered(pos)),
        "shipments": ser_all("shipments", ordered(shipments)),
        "parcel": ser("parcels", ordered(parcels)[-1]) if parcels else None,
        "returns": ser_all("returns", ordered(returns)),
    })


# ==========================================================================
# Logical clock
# ==========================================================================

CLOCK_ROLES = ["Any", "Merchandiser", "InventoryPlanner", "CrossDockOperator", "CustomerService"]


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth.require_role(CLOCK_ROLES)
    data = R.body()
    instant = R.btime(data, "current_utc")
    set_clock(instant)
    return ok({"current_utc": iso(instant)})


@bp.route("/_clock/current_utc", methods=["GET"])
def read_current_utc():
    auth.require_role(CLOCK_ROLES)
    return ok({"current_utc": iso(now())})