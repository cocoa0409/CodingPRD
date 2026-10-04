"""ProductLine resource: CRUD, readiness, production and pack-out."""

from flask import jsonify, request

import calc
import db
import requtil
import response
from core import app
from common import (
    license_in_force,
    license_of_product_line,
    print_run_locked,
    recompute_allocated_cards,
    recompute_license_counts,
    recompute_license_counts_for_line,
    recompute_sets_per_case,
    serialize,
    sets_under_line,
)
from constants import CARDS_PER_SET, LINE_KINDS, LINE_STATUSES
from errors import (
    ApiError,
    ERR_ALLOCATION_EXCEEDS_PRINT_RUN,
    ERR_AUTOGRAPH_QUANTITY_SHORT,
    ERR_BOX_CONFIGURATION_INVALID,
    ERR_INVALID_STATE,
    ERR_LICENSE_NOT_IN_FORCE,
    ERR_NO_LOCKED_PRINT_RUN,
    ERR_PACK_CONFIG_MISSING,
    ERR_PRODUCT_LINE_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
)
from middleware import authenticate, require_role

READ_ROLES = ["ProductManager", "ProductionPlanner", "PlatformAdmin"]


def _get(line_id):
    rec = db.STORE.get("product_lines", line_id)
    if rec is None:
        raise ApiError(
            ERR_PRODUCT_LINE_NOT_FOUND, "No ProductLine exists with id %s" % line_id
        )
    return rec


def _serialize(rec):
    return serialize("product_lines", rec)


def _require_license_in_force(line):
    store = db.STORE
    lic = license_of_product_line(store, line)
    if not license_in_force(lic, store.now()):
        raise ApiError(
            ERR_LICENSE_NOT_IN_FORCE,
            "The license behind this product line is not in force",
        )
    return lic


def _cases_factor(line):
    return line["boxes_per_case"] * line["packs_per_box"] * line["cards_per_pack"]


def _require_divisible(line):
    if _cases_factor(line) % CARDS_PER_SET != 0:
        raise ApiError(
            ERR_BOX_CONFIGURATION_INVALID,
            "boxes_per_case * packs_per_box * cards_per_pack must be divisible by %d"
            % CARDS_PER_SET,
        )


def _require_channel_capacity(line):
    """Priority 13 channel capacity, which also applies to starting line
    production (PRD 3.9).  Every allocation for the line is counted regardless
    of status, and the comparison is strict greater-than."""
    store = db.STORE
    cases = calc.projected_cases(store, line["id"], 0)
    sets_per_case = line["sets_per_case"]
    if cases * sets_per_case > line["cases_printed"] * sets_per_case:
        raise ApiError(
            ERR_ALLOCATION_EXCEEDS_PRINT_RUN,
            "Channel allocations exceed the line's producible case count",
        )


@app.route("/api/product-lines", methods=["POST"])
def create_product_line():
    principal = authenticate(request.headers)
    require_role(principal, ["ProductManager"])

    data = requtil.body()
    license_id = requtil.required_str(data, "license_id")
    line_name = requtil.required_str(data, "line_name")
    line_kind = requtil.required_enum(data, "line_kind", LINE_KINDS)
    packs_per_box = requtil.required_int(data, "packs_per_box")
    cards_per_pack = requtil.required_int(data, "cards_per_pack")
    boxes_per_case = requtil.required_int(data, "boxes_per_case")
    cases_printed = requtil.required_int(data, "cases_printed")
    run_planned_on = requtil.required_dt(data, "run_planned_on")

    store = db.STORE
    if not store.exists("licenses", license_id):
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "license_id %s does not resolve" % license_id
        )

    # PRD 3.2: "A new line opens in `PLANNING` and has its `sets_per_case`
    # derived immediately. ... it is required to be an exact multiple of
    # `CARDS_PER_SET` ... a configuration whose product is not divisible by 100
    # is refused with `ERR_BOX_CONFIGURATION_INVALID`."  The requirement is
    # stated at creation, so the divisibility check bites there as well as at
    # ready-for-approval.
    now = store.now()
    rec = db.record("product_lines", {
        "license_id": license_id,
        "line_name": line_name,
        "line_kind": line_kind,
        "packs_per_box": packs_per_box,
        "cards_per_pack": cards_per_pack,
        "boxes_per_case": boxes_per_case,
        "cases_printed": cases_printed,
        "run_planned_on": run_planned_on,
        "sets_per_case": boxes_per_case * packs_per_box * cards_per_pack,
        "allocated_cards": 0,
        "status": "PLANNING",
    }, now)
    _require_divisible(rec)
    store.insert("product_lines", rec)
    recompute_allocated_cards(store, rec, now)
    return jsonify(response.ok_object(_serialize(rec))), 201


@app.route("/api/product-lines", methods=["GET"])
def list_product_lines():
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)

    store = db.STORE
    items = list(store.all("product_lines"))
    license_id = requtil.filter_value("license_id")
    line_kind = requtil.filter_value("line_kind")
    status = requtil.filter_value("status")
    if license_id is not None:
        items = [r for r in items if r["license_id"] == license_id]
    if line_kind is not None:
        items = [r for r in items if r["line_kind"] == line_kind]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(response.paginate([_serialize(r) for r in items], request.args)), 200


@app.route("/api/product-lines/<line_id>", methods=["GET"])
def get_product_line(line_id):
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    return jsonify(response.ok_object(_serialize(_get(line_id)))), 200


@app.route("/api/product-lines/<line_id>", methods=["PATCH"])
def update_product_line(line_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductManager"])

    data = requtil.body()
    store = db.STORE
    now = store.now()
    rec = _get(line_id)
    if rec["status"] != "PLANNING":
        raise ApiError(
            ERR_INVALID_STATE, "A product line is only editable while it is PLANNING"
        )

    if "line_name" in data and data["line_name"] is not None:
        rec["line_name"] = requtil.as_str(data["line_name"], "line_name")
    for field in ("packs_per_box", "cards_per_pack", "boxes_per_case", "cases_printed"):
        if field in data and data[field] is not None:
            rec[field] = requtil.as_int(data[field], field)
    if "run_planned_on" in data and data["run_planned_on"] is not None:
        rec["run_planned_on"] = requtil.as_dt(data["run_planned_on"], "run_planned_on")

    recompute_sets_per_case(store, rec, now)
    db.bump(rec, now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/product-lines/<line_id>/ready-for-approval", methods=["POST"])
def ready_for_approval(line_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductManager"])

    store = db.STORE
    now = store.now()
    rec = _get(line_id)

    if rec["status"] == "PLANNING":
        _require_license_in_force(rec)
        _require_divisible(rec)
        rec["status"] = "READY_FOR_APPROVAL"
        recompute_sets_per_case(store, rec, now)
        db.bump(rec, now)
        return jsonify(response.ok_object(_serialize(rec))), 200

    if rec["status"] == "PACKED_OUT":
        # Re-entry from PACKED_OUT is a destructive reset with entirely
        # different preconditions.
        _require_license_in_force(rec)
        card_sets = sets_under_line(store, rec["id"])
        for card_set in card_sets:
            has_published = any(
                p["card_set_id"] == card_set["id"] and p["status"] == "PUBLISHED"
                for p in store.all("pack_configurations")
            )
            if not has_published:
                raise ApiError(
                    ERR_PACK_CONFIG_MISSING,
                    "Card set %s has no PUBLISHED pack configuration" % card_set["id"],
                )
        rec["status"] = "READY_FOR_APPROVAL"
        db.bump(rec, now)
        # Every card set loses its frozen print run and announced flag; every
        # pack configuration and print-run decision under those sets is
        # superseded wholesale.
        for card_set in card_sets:
            card_set["print_run_status"] = "UNDECIDED"
            card_set["announced"] = False
            db.touch(card_set, now)
        for pack_config in store.all("pack_configurations"):
            if any(pack_config["card_set_id"] == s["id"] for s in card_sets):
                pack_config["status"] = "SUPERSEDED"
                db.touch(pack_config, now)
        for decision in store.all("print_run_decisions"):
            if any(decision["card_set_id"] == s["id"] for s in card_sets):
                decision["status"] = "SUPERSEDED"
                db.touch(decision, now)
        return jsonify(response.ok_object(_serialize(rec))), 200

    raise ApiError(
        ERR_INVALID_STATE,
        "A product line can only enter READY_FOR_APPROVAL from PLANNING or PACKED_OUT",
    )


@app.route("/api/product-lines/<line_id>/start-production", methods=["POST"])
def start_line_production(line_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductionPlanner"])

    store = db.STORE
    now = store.now()
    rec = _get(line_id)

    _require_license_in_force(rec)
    # The scaffold declares `from: APPROVED` for this transition, but no
    # transition or endpoint in the platform ever moves a ProductLine into
    # APPROVED -- readiness lands the line in READY_FOR_APPROVAL and nothing
    # advances it from there.  Requiring APPROVED alone would make line
    # production, pack-out and therefore the whole distribution chain
    # unreachable, so both statuses are accepted.  A line in PLANNING or
    # PACKED_OUT is still refused with ERR_INVALID_STATE.
    if rec["status"] not in ("APPROVED", "READY_FOR_APPROVAL"):
        raise ApiError(ERR_INVALID_STATE, "Product line is not APPROVED")

    card_sets = sets_under_line(store, rec["id"])
    if not any(print_run_locked(store, s) for s in card_sets):
        raise ApiError(
            ERR_NO_LOCKED_PRINT_RUN,
            "No card set under this line has a locked print run",
        )
    _require_channel_capacity(rec)

    rec["status"] = "IN_PRODUCTION"
    db.bump(rec, now)

    # This transition reaches across to the license.
    lic = license_of_product_line(store, rec)
    if lic is not None:
        db.bump(lic, now)
        recompute_license_counts(store, lic["id"], now)

    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/product-lines/<line_id>/pack-out", methods=["POST"])
def pack_out_line(line_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductionPlanner"])

    store = db.STORE
    now = store.now()
    rec = _get(line_id)
    if rec["status"] != "IN_PRODUCTION":
        raise ApiError(ERR_INVALID_STATE, "Product line is not IN_PRODUCTION")

    card_sets = sets_under_line(store, rec["id"])
    for card_set in card_sets:
        if card_set["autograph_planned_count"] > 0:
            secured = _secured(store, card_set)
            if secured < card_set["autograph_planned_count"]:
                raise ApiError(
                    ERR_AUTOGRAPH_QUANTITY_SHORT,
                    "Card set %s has not secured its planned autograph quantity"
                    % card_set["id"],
                )

    rec["status"] = "PACKED_OUT"
    db.bump(rec, now)

    set_ids = {s["id"] for s in card_sets}
    # Every FULFILLED redemption under the line's sets is closed.  Closing a
    # child's state field here is a cascade effect that does not name a
    # version bump, so no cross-entity version increment occurs.
    for redemption in store.all("redemptions"):
        if redemption["card_set_id"] in set_ids and redemption["status"] == "FULFILLED":
            redemption["status"] = "CLOSED"
            db.touch(redemption, now)
    for card_set in card_sets:
        card_set["autograph_redemptions_outstanding"] = sum(
            1
            for r in store.all("redemptions")
            if r["card_set_id"] == card_set["id"] and r["status"] in ("ISSUED", "FULFILLED")
        )
        db.touch(card_set, now)

    return jsonify(response.ok_object(_serialize(rec))), 200


def _secured(store, card_set):
    total = 0
    for session in store.all("signing_sessions"):
        if session["status"] in ("SCHEDULED", "CANCELLED"):
            continue
        for line in session["allocation_lines"]:
            if line["card_set_id"] == card_set["id"]:
                total += line["quantity_delivered"]
    return total


@app.route("/api/product-lines/<line_id>/card-sets", methods=["GET"])
def list_line_card_sets(line_id):
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    _get(line_id)

    store = db.STORE
    items = [s for s in store.all("card_sets") if s["product_line_id"] == line_id]
    set_tier = requtil.filter_value("set_tier")
    status = requtil.filter_value("status")
    if set_tier is not None:
        items = [s for s in items if s["set_tier"] == set_tier]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(
        response.paginate([serialize("card_sets", s) for s in items], request.args)
    ), 200


@app.route("/api/product-lines/<line_id>/distribution-allocations", methods=["GET"])
def list_line_allocations(line_id):
    principal = authenticate(request.headers)
    require_role(principal, ["DistributionManager", "ProductManager", "PlatformAdmin"])
    _get(line_id)

    store = db.STORE
    items = [
        a for a in store.all("distribution_allocations") if a["product_line_id"] == line_id
    ]
    channel = requtil.filter_value("channel")
    status = requtil.filter_value("status")
    if channel is not None:
        items = [a for a in items if a["channel"] == channel]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(
        response.paginate(
            [serialize("distribution_allocations", a) for a in items], request.args
        )
    ), 200