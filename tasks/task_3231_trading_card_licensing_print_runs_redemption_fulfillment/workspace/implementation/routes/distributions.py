"""DistributionAllocation resource: reserve, mark-utf, ship, recall.

The recall cascade is the platform's most destructive operation (PRD 3.8): it
returns the call's payload as the ProductLine, because the line is what has
materially changed.
"""

from flask import jsonify, request

import calc
import db
import requtil
import response
from core import app
from common import serialize, sets_under_line
from constants import CHANNELS, QUALITY_RECALL_THRESHOLD
from errors import (
    ApiError,
    ERR_ALLOCATION_EXCEEDS_PRINT_RUN,
    ERR_CHANNEL_ALREADY_UTF,
    ERR_DISTRIBUTION_ALLOCATION_NOT_FOUND,
    ERR_DISTRIBUTION_WINDOW_CLOSED,
    ERR_INVALID_STATE,
    ERR_PRODUCT_LINE_NOT_FOUND,
    ERR_PRODUCT_LINE_NOT_PACKED_OUT,
    ERR_REFERENCE_NOT_FOUND,
)
from middleware import authenticate, require_role

READ_ROLES = ["DistributionManager", "ProductManager", "PlatformAdmin"]


def _get(allocation_id):
    rec = db.STORE.get("distribution_allocations", allocation_id)
    if rec is None:
        raise ApiError(
            ERR_DISTRIBUTION_ALLOCATION_NOT_FOUND,
            "No DistributionAllocation exists with id %s" % allocation_id,
        )
    return rec


def _serialize(rec):
    return serialize("distribution_allocations", rec)


def _line(allocation):
    rec = db.STORE.get("product_lines", allocation["product_line_id"])
    if rec is None:
        raise ApiError(
            ERR_PRODUCT_LINE_NOT_FOUND,
            "The parent product line does not resolve",
        )
    return rec


@app.route("/api/distribution-allocations", methods=["POST"])
def create_allocation():
    principal = authenticate(request.headers)
    require_role(principal, ["DistributionManager"])

    data = requtil.body()
    product_line_id = requtil.required_str(data, "product_line_id")
    channel = requtil.required_enum(data, "channel", CHANNELS)
    quantity_allocated = requtil.required_int(data, "quantity_allocated")
    effective_price_cents = requtil.required_int(data, "effective_price_cents")

    store = db.STORE
    line = store.get("product_lines", product_line_id)
    if line is None:
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND,
            "product_line_id %s does not resolve" % product_line_id,
        )

    # Capacity pre-check, run BEFORE the allocation is written.  Every
    # allocation for the line is counted regardless of status, and the
    # comparison is strictly greater-than so landing exactly on capacity is
    # accepted.
    if not calc.allocation_within_capacity(store, line, quantity_allocated):
        raise ApiError(
            ERR_ALLOCATION_EXCEEDS_PRINT_RUN,
            "The projected channel cases exceed the line's producible case count",
        )

    now = store.now()
    rec = db.record("distribution_allocations", {
        "product_line_id": product_line_id,
        "channel": channel,
        "quantity_allocated": quantity_allocated,
        "shipped_quantity": 0,
        "effective_price_cents": effective_price_cents,
        "status": "RESERVED",
    }, now)
    store.insert("distribution_allocations", rec)
    return jsonify(response.ok_object(_serialize(rec))), 201


@app.route("/api/distribution-allocations", methods=["GET"])
def list_allocations():
    principal = authenticate(request.headers)
    require_role(principal, ["DistributionManager", "ProductManager", "PlatformAdmin"])

    store = db.STORE
    items = list(store.all("distribution_allocations"))
    product_line_id = requtil.filter_value("product_line_id")
    channel = requtil.filter_value("channel")
    status = requtil.filter_value("status")
    if product_line_id is not None:
        items = [a for a in items if a["product_line_id"] == product_line_id]
    if channel is not None:
        items = [a for a in items if a["channel"] == channel]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(response.paginate([_serialize(a) for a in items], request.args)), 200


@app.route("/api/distribution-allocations/<allocation_id>", methods=["GET"])
def get_allocation(allocation_id):
    principal = authenticate(request.headers)
    require_role(principal, ["DistributionManager", "ProductManager", "PlatformAdmin"])
    return jsonify(response.ok_object(_serialize(_get(allocation_id)))), 200


@app.route("/api/distribution-allocations/<allocation_id>/mark-utf", methods=["POST"])
def mark_utf(allocation_id):
    principal = authenticate(request.headers)
    require_role(principal, ["DistributionManager"])

    store = db.STORE
    now = store.now()
    rec = _get(allocation_id)
    line = _line(rec)

    if line["status"] != "PACKED_OUT":
        raise ApiError(
            ERR_PRODUCT_LINE_NOT_PACKED_OUT,
            "The parent product line has not reached PACKED_OUT",
        )
    if rec["status"] != "RESERVED":
        raise ApiError(ERR_INVALID_STATE, "Allocation is not RESERVED")

    # One unable-to-fill allocation per channel per line.
    for other in store.all("distribution_allocations"):
        if other["id"] == rec["id"]:
            continue
        if (
            other["product_line_id"] == rec["product_line_id"]
            and other["channel"] == rec["channel"]
            and other["status"] == "UTF"
        ):
            raise ApiError(
                ERR_CHANNEL_ALREADY_UTF,
                "Another allocation for this line and channel is already UTF",
            )

    rec["status"] = "UTF"
    db.bump(rec, now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/distribution-allocations/<allocation_id>/ship", methods=["POST"])
def ship_allocation(allocation_id):
    principal = authenticate(request.headers)
    require_role(principal, ["DistributionManager"])

    store = db.STORE
    now = store.now()
    rec = _get(allocation_id)
    line = _line(rec)
    if rec["status"] != "UTF":
        raise ApiError(ERR_INVALID_STATE, "Allocation is not UTF")

    # Shipping is gated on the calendar, not on demand.
    if now < line["run_planned_on"]:
        raise ApiError(
            ERR_DISTRIBUTION_WINDOW_CLOSED,
            "An allocation cannot ship before the line's run_planned_on",
        )
    if rec["quantity_allocated"] > line["cases_printed"]:
        raise ApiError(
            ERR_ALLOCATION_EXCEEDS_PRINT_RUN,
            "quantity_allocated exceeds the parent product line's cases_printed",
        )

    rec["status"] = "SHIPPED"
    rec["shipped_quantity"] = rec["quantity_allocated"]
    db.bump(rec, now)

    from common import recompute_sets_per_case

    line["status"] = line["status"]
    db.bump(line, now)
    recompute_sets_per_case(store, line, now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/distribution-allocations/<allocation_id>/recall", methods=["POST"])
def recall_allocation(allocation_id):
    principal = authenticate(request.headers)
    require_role(principal, ["DistributionManager"])

    store = db.STORE
    now = store.now()
    rec = _get(allocation_id)
    line = _line(rec)
    if rec["status"] != "SHIPPED":
        raise ApiError(ERR_INVALID_STATE, "Allocation is not SHIPPED")

    rec["status"] = "RECALLED"
    rec["shipped_quantity"] = 0
    db.bump(rec, now)

    card_sets = sets_under_line(store, line["id"])
    set_ids = {s["id"] for s in card_sets}

    # PRD 3.8: "the platform repeatedly returns the parent product line to
    # `PLANNING`, once per recursion, and continues recursing while the total
    # `affected_quantity` ... exceeds the platform's `QUALITY_RECALL_THRESHOLD`."
    # The loop "continues" rather than "starts", so the recall's own cascade
    # always performs one pass — without it the recall would leave the line in
    # its shipped state, which contradicts recall being "the platform's most
    # destructive operation".  The exposure total is fixed within the call
    # (nothing in the body writes a claim), so one pass settles the condition.
    exposed = sum(
        q["affected_quantity"]
        for q in store.all("quality_claims")
        if q["card_set_id"] in set_ids and q["status"] == "APPROVED"
    )
    line["status"] = "PLANNING"
    for decision in store.all("print_run_decisions"):
        if decision["card_set_id"] in set_ids:
            decision["status"] = "SUPERSEDED"
            db.touch(decision, now)
    for card_set in card_sets:
        card_set["print_run_status"] = "UNDECIDED"
        db.touch(card_set, now)
    while exposed > QUALITY_RECALL_THRESHOLD:
        # Each further recursion repeats the same reset; the guard keeps the
        # loop bounded because the total cannot change within the call.
        line["status"] = "PLANNING"
        for decision in store.all("print_run_decisions"):
            if decision["card_set_id"] in set_ids:
                decision["status"] = "SUPERSEDED"
                db.touch(decision, now)
        for card_set in card_sets:
            card_set["print_run_status"] = "UNDECIDED"
            db.touch(card_set, now)
        break

    db.bump(line, now)
    return jsonify(response.ok_object(serialize("product_lines", line))), 200