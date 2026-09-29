"""Claims advocacy, the dispute overlay and collections (PRD 3.9)."""
from flask import Blueprint

import calc
import db
import enums
import response
import serialize
import services
import validate
from errors import fail
from middleware import (
    BROKER_ACCOUNTANT,
    BROKER_PLACEMENT_LEAD,
    CEDENT_UNDERWRITER,
    REINSURER_UNDERWRITER,
    own_cedent,
    own_reinsurer,
    require,
)
from routes._common import EVERY_ROLE, ordered_filtered, paged, q

bp = Blueprint("claims", __name__)

DISPUTE_RESOLUTIONS = ("UPHELD", "WITHDRAWN", "SETTLED_PARTIAL")
COLLECTION_STATES = (
    "UNDER_REVIEW",
    "DISPUTED",
    "ADVOCACY_NEGOTIATION",
    "ADVOCACY_ARBITRATION",
    "RESOLVED",
)
BRANCH_STATES = ("ADVOCACY_NEGOTIATION", "ADVOCACY_ARBITRATION")


@bp.route("/claim-advocacies", methods=["GET"])
def list_advocacies():
    require(EVERY_ROLE)
    rows = ordered_filtered(db.claim_advocacies, [
        ("layer_id", q("layer_id")),
        ("status", q("status")),
        ("advocacy_route", q("advocacy_route")),
    ])
    return paged(rows, serialize.claim_advocacy)


@bp.route("/claim-advocacies/<claim_advocacy_id>", methods=["GET"])
def read_advocacy(claim_advocacy_id):
    require(EVERY_ROLE)
    row = services.get_advocacy(claim_advocacy_id)
    return response.object_response(serialize.claim_advocacy(row), 200)


@bp.route("/claim-advocacies/<claim_advocacy_id>/review", methods=["POST"])
def review_advocacy(claim_advocacy_id):
    require((BROKER_PLACEMENT_LEAD,))
    advocacy = services.get_advocacy(claim_advocacy_id)
    if advocacy["status"] != "NOTIFIED":
        fail("ERR_ADVOCACY_STATE_INVALID",
             "only a NOTIFIED file may be taken under review")
    layer = db.layers[advocacy["layer_id"]]
    if layer["status"] != "BOUND":
        fail("ERR_LAYER_NOT_BOUND", "the layer is no longer bound")

    advocacy["status"] = "UNDER_REVIEW"
    db.touch(advocacy)
    return response.object_response(serialize.claim_advocacy(advocacy), 200)


@bp.route("/claim-advocacies/<claim_advocacy_id>/withdraw", methods=["POST"])
def withdraw_advocacy(claim_advocacy_id):
    actor = require((CEDENT_UNDERWRITER,))
    existing = db.claim_advocacies.get(claim_advocacy_id)
    if existing is not None:
        layer = db.layers.get(existing["layer_id"])
        if layer is not None:
            program = db.programs.get(layer["program_id"])
            if program is not None:
                own_cedent(actor, program["cedent_id"])

    advocacy = services.get_advocacy(claim_advocacy_id)
    if advocacy["status"] != "NOTIFIED":
        fail("ERR_ADVOCACY_STATE_INVALID",
             "only a NOTIFIED file may be withdrawn")

    advocacy["status"] = "WITHDRAWN"
    db.touch(advocacy)
    return response.object_response(serialize.claim_advocacy(advocacy), 200)


@bp.route("/claim-advocacies/<claim_advocacy_id>/advocacy-route", methods=["POST"])
def choose_route(claim_advocacy_id):
    require((BROKER_PLACEMENT_LEAD,))
    shape = validate.Shape()
    route = shape.enum("route", enums.ADVOCACY_ROUTES)

    advocacy = services.get_advocacy(claim_advocacy_id)
    if advocacy["status"] != "DISPUTED":
        fail("ERR_ADVOCACY_STATE_INVALID",
             "an advocacy branch is chosen only from DISPUTED")

    advocacy["advocacy_route"] = route
    advocacy["arbitration_cost_minor"] = calc.arbitration_cost_minor(
        advocacy["ceded_claim_minor"], route)
    if route == "ARBITRATION":
        advocacy["status"] = "ADVOCACY_ARBITRATION"
    else:
        advocacy["status"] = "ADVOCACY_NEGOTIATION"
    db.touch(advocacy)
    return response.object_response(serialize.claim_advocacy(advocacy), 200)


# ---------------------------------------------------------------------------
# The dispute overlay
# ---------------------------------------------------------------------------

@bp.route("/claim-advocacies/<claim_advocacy_id>/cession-disputes", methods=["POST"])
def raise_dispute(claim_advocacy_id):
    actor = require((REINSURER_UNDERWRITER,))
    payload = validate.body()
    raw_line = payload.get("signing_line_id")
    if isinstance(raw_line, str):
        candidate = db.signing_lines.get(raw_line)
        if candidate is not None:
            own_reinsurer(actor, candidate["reinsurer_id"])

    shape = validate.Shape(payload=payload)
    signing_line_id = shape.id_ref("signing_line_id")
    disputed_minor = shape.money("disputed_minor", minimum=None, exclusive_min=0)
    dispute_reason = shape.enum("dispute_reason", enums.DISPUTE_REASONS)

    advocacy = services.get_advocacy(claim_advocacy_id)
    line = services.get_signing_line(signing_line_id)
    if advocacy["status"] not in ("UNDER_REVIEW", "DISPUTED"):
        fail("ERR_ADVOCACY_STATE_INVALID",
             "a dispute is raised only against a file under review or disputed")
    if line["layer_id"] != advocacy["layer_id"]:
        fail("ERR_LINE_LAYER_MISMATCH",
             "the signing line does not sit on the advocacy's layer")

    contested = 0
    for other in services.disputes_of_advocacy(advocacy["id"]):
        if other["status"] in ("RAISED", "UPHELD", "SETTLED_PARTIAL"):
            contested += other["disputed_minor"]
    if contested + disputed_minor > advocacy["ceded_claim_minor"]:
        fail("ERR_DISPUTE_EXCEEDS_CESSION",
             "the markets may not dispute more than was ceded to them")

    row = db.base_row()
    row.update({
        "claim_advocacy_id": advocacy["id"],
        "signing_line_id": signing_line_id,
        "disputed_minor": disputed_minor,
        "dispute_reason": dispute_reason,
        "settled_minor": 0,
        "resolution_note": None,
        "status": "RAISED",
    })
    db.cession_disputes[row["id"]] = row

    if advocacy["status"] == "UNDER_REVIEW":
        advocacy["status"] = "DISPUTED"
    services.recompute_advocacy_figures(advocacy)
    db.touch(advocacy)
    return response.object_response(serialize.cession_dispute(row), 201)


@bp.route("/claim-advocacies/<claim_advocacy_id>/cession-disputes", methods=["GET"])
def list_advocacy_disputes(claim_advocacy_id):
    require(EVERY_ROLE)
    validate.pagination()
    services.get_advocacy(claim_advocacy_id)
    rows = services.disputes_of_advocacy(claim_advocacy_id)
    for field in ("signing_line_id", "status", "dispute_reason"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paged(rows, serialize.cession_dispute)


@bp.route("/cession-disputes", methods=["GET"])
def list_disputes():
    require(EVERY_ROLE)
    rows = ordered_filtered(db.cession_disputes, [
        ("claim_advocacy_id", q("claim_advocacy_id")),
        ("signing_line_id", q("signing_line_id")),
        ("status", q("status")),
        ("dispute_reason", q("dispute_reason")),
    ])
    return paged(rows, serialize.cession_dispute)


@bp.route("/cession-disputes/<dispute_id>", methods=["GET"])
def read_dispute(dispute_id):
    require(EVERY_ROLE)
    row = services.get_dispute(dispute_id)
    return response.object_response(serialize.cession_dispute(row), 200)


@bp.route("/cession-disputes/<dispute_id>/resolve", methods=["POST"])
def resolve_dispute(dispute_id):
    require((BROKER_PLACEMENT_LEAD,))
    shape = validate.Shape()
    resolution = shape.enum("resolution", DISPUTE_RESOLUTIONS)
    settled_minor = shape.money("settled_minor", minimum=0)
    resolution_note = shape.string("resolution_note", min_len=1, max_len=500,
                                   required=False, default=None)

    dispute = services.get_dispute(dispute_id)
    if dispute["status"] != "RAISED":
        fail("ERR_DISPUTE_STATE_INVALID", "only a RAISED dispute may be resolved")

    contested = dispute["disputed_minor"]
    if resolution == "UPHELD":
        ok = settled_minor == 0
    elif resolution == "WITHDRAWN":
        ok = settled_minor == contested
    else:
        ok = 0 < settled_minor < contested
    if not ok:
        fail("ERR_RESOLUTION_AMOUNT_INVALID",
             "settled_minor does not match the resolution chosen")

    dispute["status"] = resolution
    dispute["settled_minor"] = settled_minor
    dispute["resolution_note"] = resolution_note
    db.touch(dispute)

    advocacy = db.claim_advocacies.get(dispute["claim_advocacy_id"])
    if advocacy is not None:
        services.recompute_advocacy_figures(advocacy)
        still_raised = any(d["status"] == "RAISED"
                           for d in services.disputes_of_advocacy(advocacy["id"]))
        if not still_raised and advocacy["status"] in BRANCH_STATES:
            advocacy["status"] = "RESOLVED"
            layer = db.layers.get(advocacy["layer_id"])
            if layer is not None and services.recompute_layer_incurred(layer):
                db.touch(layer)
        db.touch(advocacy)
    return response.object_response(serialize.cession_dispute(dispute), 200)


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

@bp.route("/claim-advocacies/<claim_advocacy_id>/collections", methods=["POST"])
def book_collection(claim_advocacy_id):
    actor = require((BROKER_ACCOUNTANT,))
    shape = validate.Shape()
    signing_line_id = shape.id_ref("signing_line_id")
    amount_minor = shape.money("amount_minor", minimum=None, exclusive_min=0)

    advocacy = services.get_advocacy(claim_advocacy_id)
    line = services.get_signing_line(signing_line_id)
    if advocacy["status"] not in COLLECTION_STATES:
        fail("ERR_ADVOCACY_STATE_INVALID",
             "a collection cannot be booked against a %s file" % advocacy["status"])
    if line["layer_id"] != advocacy["layer_id"]:
        fail("ERR_LINE_LAYER_MISMATCH",
             "the signing line does not sit on the advocacy's layer")
    if advocacy["status"] == "ADVOCACY_ARBITRATION":
        fail("ERR_COLLECTION_BLOCKED_BY_ARBITRATION",
             "collections are frozen while the file is in arbitration")
    if advocacy["collected_minor"] + amount_minor > advocacy["collectible_minor"]:
        fail("ERR_COLLECTION_EXCEEDS_COLLECTIBLE",
             "the collection would exceed the file's collectible amount")

    program = services.program_of_advocacy(advocacy)
    txn = services.new_transaction(program, "CLAIM_COLLECTION", amount_minor,
                                   actor.user_id, signing_line_id=signing_line_id)

    services.recompute_advocacy_collected(advocacy)
    if advocacy["collected_minor"] >= advocacy["collectible_minor"]:
        services.collected_cascade(advocacy, program, actor.user_id)
    db.touch(advocacy)
    return response.object_response(serialize.fiduciary_transaction(txn), 201)
