"""Substitution proposals: manual offers, the approval clock, and the
customer's approve / decline decision (PRD 3.6)."""

from datetime import timedelta

from flask import Blueprint

import db as store
from db import db
from errors import ApiError
import response as resp
import validation as v
from middleware import endpoint, must_get, require_ownership
from services import cascade, derive, money, selectors

bp = Blueprint("subs", __name__)

OPERATOR = ["PickOperator"]
PLANNER = ["WavePlanner"]
CUSTOMER = ["Customer"]
PROPOSAL_READERS = ["FulfillmentAdmin", "WavePlanner", "PickOperator", "Customer"]


@bp.route("/substitution-proposals", methods=["POST"])
@endpoint(roles=OPERATOR, mutating=True)
def create_proposal():
    body = v.read_body()
    # gate 6 -- in declared field order
    line = v.fk(body, "order_line_id", db.lines, "ERR_ORDER_LINE_NOT_FOUND")
    substitute = v.fk(body, "substitute_sku_id", db.skus, "ERR_SKU_NOT_FOUND")
    superseded = v.fk(
        body, "supersedes_proposal_id", db.proposals, "ERR_PROPOSAL_NOT_FOUND"
    )
    data = v.check_body(body, [
        v.f_id("order_line_id"),
        v.f_id("substitute_sku_id"),
        v.f_int("expected_order_line_version", 0, None),
        v.f_id("supersedes_proposal_id", required=False),
    ])
    # gate 10
    if data["expected_order_line_version"] != line["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", "the order line has been modified since it was read"
        )
    # gate 11
    if line["substitution_resolution"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE", "the line is not awaiting a substitution decision"
        )
    # gate 20
    ordered = db.skus[line["sku_id"]]
    if (substitute["id"] == ordered["id"]
            or substitute["temperature_zone"] != ordered["temperature_zone"]
            or substitute["substitution_group_code"] != ordered["substitution_group_code"]):
        raise ApiError(
            "ERR_SUBSTITUTE_NOT_COMPARABLE", "the substitute is not comparable"
        )
    # gate 21
    if superseded is not None:
        if (superseded["order_line_id"] != line["id"]
                or superseded["status"] not in ("DECLINED", "EXPIRED")):
            raise ApiError(
                "ERR_SUPERSEDE_TARGET_INVALID",
                "the superseded proposal is not a retired proposal on this line",
            )
    # gate 30
    for existing in derive.line_proposals(line):
        if existing["status"] in ("DRAFT", "PROPOSED"):
            raise ApiError(
                "ERR_PROPOSAL_ALREADY_OPEN", "the line already has an open proposal"
            )

    proposal = cascade.create_proposal(
        line, substitute,
        supersedes_proposal_id=(superseded["id"] if superseded is not None else None),
    )
    derive.recompute_order_flags(derive.line_order(line))
    return resp.created(proposal)


@bp.route("/substitution-proposals/<proposal_id>", methods=["GET"])
@endpoint(roles=PROPOSAL_READERS)
def read_proposal(proposal_id):
    return resp.obj(must_get(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND"))


@bp.route("/substitution-proposals", methods=["GET"])
@endpoint(roles=PROPOSAL_READERS)
def list_proposals():
    items = resp.filtered(list(db.proposals.values()), {
        "order_line_id": "order_line_id",
        "substitute_sku_id": "substitute_sku_id",
        "supersedes_proposal_id": "supersedes_proposal_id",
        "status": "status",
    })
    return resp.listing(items)


@bp.route("/substitution-proposals/<proposal_id>/propose", methods=["POST"])
@endpoint(roles=OPERATOR, mutating=True)
def propose(proposal_id):
    proposal = must_get(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
    v.check_body(v.read_body(), [])
    line = db.lines[proposal["order_line_id"]]
    substitute = db.skus[proposal["substitute_sku_id"]]
    # gate 11
    if proposal["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "only a DRAFT proposal can be proposed")
    if line["substitution_resolution"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE", "the line is not awaiting a substitution decision"
        )
    # gate 31
    if substitute["on_hand_units"] < line["ordered_qty"]:
        raise ApiError(
            "ERR_INSUFFICIENT_INVENTORY", "the substitute has insufficient stock"
        )

    proposal["status"] = "PROPOSED"
    proposal["expires_at"] = db.clock + timedelta(minutes=store.PROPOSAL_TTL_MINUTES)
    return resp.obj(proposal)


@bp.route("/substitution-proposals/<proposal_id>/approve", methods=["POST"])
@endpoint(roles=CUSTOMER, mutating=True)
def approve(proposal_id):
    proposal = must_get(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
    line = db.lines[proposal["order_line_id"]]
    order = db.orders[line["order_id"]]
    require_ownership(order)
    v.check_body(v.read_body(), [])
    substitute = db.skus[proposal["substitute_sku_id"]]
    # gate 11
    if proposal["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "only a PROPOSED proposal can be approved")
    wave = derive.order_wave(order)
    if wave is None or wave["status"] != "PICKING":
        raise ApiError("ERR_INVALID_STATE", "the line's wave is not PICKING")
    # gate 13
    zone = db.zones[substitute["grid_zone_id"]]
    if zone["status"] != "OPERATIONAL":
        raise ApiError(
            "ERR_ZONE_NOT_OPERATIONAL", "the substitute's grid zone is not OPERATIONAL"
        )
    # gate 25
    if proposal["expires_at"] is not None and db.clock >= proposal["expires_at"]:
        raise ApiError("ERR_PROPOSAL_EXPIRED", "the proposal's approval window has closed")
    # gate 27
    station = selectors.select_station(substitute)
    if station is None:
        raise ApiError(
            "ERR_NO_ELIGIBLE_PICK_STATION", "no pick station can serve the substitute"
        )
    # gate 31
    if substitute["on_hand_units"] < line["ordered_qty"]:
        raise ApiError(
            "ERR_INSUFFICIENT_INVENTORY", "the substitute has insufficient stock"
        )

    proposal["status"] = "APPROVED"
    line["line_status"] = "PENDING"
    line["substitution_resolution"] = "SUBSTITUTED"
    line["picked_units"] = None
    line["final_line_price_cents"] = money.final_price_from_substitution(
        substitute, line["ordered_qty"]
    )
    store.insert(db.tasks, {
        "order_line_id": line["id"],
        "sku_id": substitute["id"],
        "grid_zone_id": substitute["grid_zone_id"],
        "pick_station_id": station["id"],
        "tote_id": None,
        "sequence_index": selectors.next_sequence_index(wave),
        "allocated_units": line["ordered_qty"],
        "status": "QUEUED",
        "picked_units": None,
        "actual_weight_grams": None,
    })
    derive.recompute_all_sku_ledgers()
    derive.recompute_order_flags(order)
    money.run_waterfall(order)
    store.bump(order)
    return resp.obj(proposal)


@bp.route("/substitution-proposals/<proposal_id>/decline", methods=["POST"])
@endpoint(roles=CUSTOMER, mutating=True)
def decline(proposal_id):
    proposal = must_get(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
    line = db.lines[proposal["order_line_id"]]
    order = db.orders[line["order_id"]]
    require_ownership(order)
    v.check_body(v.read_body(), [])
    # gate 11
    if proposal["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "only a PROPOSED proposal can be declined")
    # gate 25
    if proposal["expires_at"] is not None and db.clock >= proposal["expires_at"]:
        raise ApiError("ERR_PROPOSAL_EXPIRED", "the proposal's approval window has closed")

    proposal["status"] = "DECLINED"
    derive.recompute_order_flags(order)
    return resp.obj(proposal)


@bp.route("/substitution-proposals/<proposal_id>/expire", methods=["POST"])
@endpoint(roles=PLANNER, mutating=True)
def expire(proposal_id):
    proposal = must_get(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
    line = db.lines[proposal["order_line_id"]]
    order = db.orders[line["order_id"]]
    v.check_body(v.read_body(), [])
    # gate 11
    if proposal["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "only a PROPOSED proposal can be retired")
    # gate 25
    if proposal["expires_at"] is None or db.clock < proposal["expires_at"]:
        raise ApiError("ERR_PROPOSAL_NOT_EXPIRED", "the proposal has not expired yet")

    proposal["status"] = "EXPIRED"
    derive.recompute_order_flags(order)
    return resp.obj(proposal)
