"""Layers: restructuring, marketing, signing down and loss notification."""
from flask import Blueprint

import calc
import db
import enums
import response
import serialize
import services
import validate
from errors import fail
from middleware import BROKER_PLACEMENT_LEAD, CEDENT_UNDERWRITER, require
from routes._common import EVERY_ROLE, REINSURER_READ, ordered_filtered, paged, q
from util import dec, pct4

bp = Blueprint("layers", __name__)


@bp.route("/layers", methods=["GET"])
def list_layers():
    require(EVERY_ROLE)
    rows = ordered_filtered(db.layers, [
        ("program_id", q("program_id")),
        ("status", q("status")),
        ("layer_type", q("layer_type")),
    ])
    return paged(rows, serialize.layer)


@bp.route("/layers/<layer_id>", methods=["GET"])
def read_layer(layer_id):
    require(EVERY_ROLE)
    layer = services.get_layer(layer_id)
    return response.object_response(serialize.layer(layer), 200)


@bp.route("/layers/<layer_id>", methods=["PATCH"])
def restructure_layer(layer_id):
    require((BROKER_PLACEMENT_LEAD,))
    shape = validate.Shape(patch=True)
    layer_label = shape.string("layer_label", min_len=1, max_len=80,
                               required=False, default=None)
    attachment_minor = shape.money("attachment_minor", minimum=0,
                                   required=False, default=None)
    limit_minor = shape.money("limit_minor", minimum=None, exclusive_min=0,
                              required=False, default=None)
    base_rate_pct = shape.percent("base_rate_pct", exclusive_min=0, maximum=100,
                                  required=False, default=None)
    subject_premium_base_minor = shape.money("subject_premium_base_minor",
                                             minimum=None, exclusive_min=0,
                                             required=False, default=None)
    expected_loss_cost_minor = shape.money("expected_loss_cost_minor", minimum=0,
                                           required=False, default=None)
    cession_pct = shape.percent("cession_pct", minimum=0, maximum=100,
                                required=False, default=None)
    reinstatements_total = shape.integer("reinstatements_total", minimum=0, maximum=5,
                                         required=False, default=None)
    reinstatement_premium_pct = shape.percent("reinstatement_premium_pct", minimum=0,
                                              maximum=200, required=False, default=None)
    sublimit_minor = shape.money("sublimit_minor", minimum=0,
                                 required=False, default=None)
    ceding_commission_pct = shape.percent("ceding_commission_pct", minimum=0,
                                          maximum=60, required=False, default=None)
    excluded_perils = shape.enum_array("excluded_perils", enums.PERILS,
                                       required=False, default=None)

    layer = services.get_layer(layer_id)
    if layer["status"] != "OPEN":
        fail("ERR_LAYER_STATE_INVALID",
             "a layer may only be restructured while it is OPEN")
    program = services.program_of_layer(layer)
    if program["placement_status"] not in ("DRAFT", "SUBMISSION_READY"):
        fail("ERR_PROGRAM_STATE_INVALID",
             "the owning program must be DRAFT or SUBMISSION_READY")

    merged = dict(layer)
    if layer_label is not None:
        merged["layer_label"] = layer_label
    if attachment_minor is not None:
        merged["attachment_minor"] = attachment_minor
    if limit_minor is not None:
        merged["limit_minor"] = limit_minor
    if base_rate_pct is not None:
        merged["base_rate_pct"] = pct4(base_rate_pct)
    if subject_premium_base_minor is not None:
        merged["subject_premium_base_minor"] = subject_premium_base_minor
    if expected_loss_cost_minor is not None:
        merged["expected_loss_cost_minor"] = expected_loss_cost_minor
    if cession_pct is not None:
        merged["cession_pct"] = pct4(cession_pct)
    if reinstatements_total is not None:
        merged["reinstatements_total"] = reinstatements_total
    if reinstatement_premium_pct is not None:
        merged["reinstatement_premium_pct"] = pct4(reinstatement_premium_pct)
    if sublimit_minor is not None:
        merged["sublimit_minor"] = sublimit_minor
    if ceding_commission_pct is not None:
        merged["ceding_commission_pct"] = pct4(ceding_commission_pct)
    if excluded_perils is not None:
        merged["excluded_perils"] = list(excluded_perils)

    services.check_layer_structure(merged)

    layer.update(merged)
    services.apply_technical_premium(layer)
    db.touch(layer)
    return response.object_response(serialize.layer(layer), 200)


# ---------------------------------------------------------------------------
# Sending a layer to market (PRD 3.4)
# ---------------------------------------------------------------------------

@bp.route("/layers/<layer_id>/market-submissions", methods=["POST"])
def create_market_submission(layer_id):
    actor = require((BROKER_PLACEMENT_LEAD,))
    shape = validate.Shape()
    reinsurer_id = shape.id_ref("reinsurer_id")
    response_deadline = shape.instant("response_deadline")

    layer = services.get_layer(layer_id)
    market = services.get_reinsurer(reinsurer_id)

    if layer["status"] not in ("OPEN", "IN_MARKET"):
        fail("ERR_LAYER_STATE_INVALID",
             "a layer is offered to market only while OPEN or IN_MARKET")
    program = services.program_of_layer(layer)
    if program["placement_status"] != "IN_MARKET":
        fail("ERR_PROGRAM_STATE_INVALID", "the owning program must be IN_MARKET")
    if market["security_status"] == "SUSPENDED":
        fail("ERR_MARKET_SUSPENDED", "a suspended market may not receive submissions")
    if response_deadline <= db.now():
        fail("ERR_DEADLINE_NOT_IN_FUTURE",
             "response_deadline must be strictly after the current instant")
    for other in services.submissions_of_layer(layer["id"]):
        if other["reinsurer_id"] == reinsurer_id and other["status"] in (
                "SENT", "QUOTED"):
            fail("ERR_DUPLICATE_MARKET_SUBMISSION",
                 "this market is already holding a live submission on the layer")

    row = db.base_row()
    row.update({
        "layer_id": layer["id"],
        "reinsurer_id": reinsurer_id,
        "response_deadline": response_deadline,
        "submitted_by_user_id": actor.user_id,
        "sent_at": db.now(),
        "status": "SENT",
    })
    db.market_submissions[row["id"]] = row

    if layer["status"] == "OPEN":
        layer["status"] = "IN_MARKET"
        db.touch(layer)

    return response.object_response(serialize.market_submission(row), 201)


@bp.route("/layers/<layer_id>/market-submissions", methods=["GET"])
def list_layer_submissions(layer_id):
    require(REINSURER_READ)
    validate.pagination()
    services.get_layer(layer_id)
    rows = services.submissions_of_layer(layer_id)
    for field in ("reinsurer_id", "status"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paged(rows, serialize.market_submission)


# ---------------------------------------------------------------------------
# Signing down (PRD 3.6)
# ---------------------------------------------------------------------------

@bp.route("/layers/<layer_id>/sign-down", methods=["POST"])
def sign_down(layer_id):
    require((BROKER_PLACEMENT_LEAD,))
    layer = services.get_layer(layer_id)
    if layer["status"] in ("SIGNED_DOWN", "BOUND", "LAPSED"):
        fail("ERR_LAYER_STATE_INVALID",
             "a %s layer cannot be signed down" % layer["status"])
    program = services.program_of_layer(layer)
    if program["placement_status"] != "FIRM_ORDER":
        fail("ERR_PROGRAM_STATE_INVALID", "the owning program must be in FIRM_ORDER")
    if dec(layer["written_line_total_pct"]) <= calc.FULL_PLACEMENT_PCT:
        fail("ERR_LAYER_NOT_OVERSUBSCRIBED",
             "the layer's written line total is not above 100.0000")

    if program["signdown_method"] == "LEAD_PROTECTED":
        leads = 0
        for line in services.lines_of_layer(layer["id"]):
            if line["status"] != "PROVISIONAL":
                continue
            quote = db.quotes.get(line["quote_id"])
            if quote is not None and quote["is_lead"]:
                leads += 1
        if leads != 1:
            fail("ERR_LEAD_LINE_MISSING",
                 "LEAD_PROTECTED sign-down requires exactly one lead line")

    services.sign_down_layer(layer, program)
    return response.object_response(serialize.layer(layer), 200)


@bp.route("/layers/<layer_id>/signing-lines", methods=["GET"])
def list_layer_lines(layer_id):
    require(REINSURER_READ)
    validate.pagination()
    services.get_layer(layer_id)
    rows = services.lines_of_layer(layer_id)
    for field in ("reinsurer_id", "quote_id", "status"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paged(rows, serialize.signing_line)


# ---------------------------------------------------------------------------
# Loss notification (PRD 3.9)
# ---------------------------------------------------------------------------

@bp.route("/layers/<layer_id>/claim-advocacies", methods=["POST"])
def notify_claim(layer_id):
    require((BROKER_PLACEMENT_LEAD, CEDENT_UNDERWRITER))
    shape = validate.Shape()
    claim_reference = shape.string("claim_reference", min_len=1, max_len=60)
    event_date = shape.instant("event_date")
    gross_claim_minor = shape.money("gross_claim_minor", minimum=None, exclusive_min=0)

    layer = services.get_layer(layer_id)
    if layer["status"] != "BOUND":
        fail("ERR_LAYER_NOT_BOUND", "a loss is notified only against a BOUND layer")
    program = services.program_of_layer(layer)
    if event_date < program["inception_date"] or event_date >= program["expiry_date"]:
        fail("ERR_EVENT_DATE_OUT_OF_PERIOD",
             "event_date falls outside the treaty period")
    for other in services.advocacies_of_layer(layer["id"]):
        if other["claim_reference"] == claim_reference:
            fail("ERR_DUPLICATE_CLAIM_REFERENCE",
                 "claim_reference %s is already used on this layer" % claim_reference)
    if calc.aggregate_available_minor(layer) <= 0:
        fail("ERR_AGGREGATE_LIMIT_EXHAUSTED",
             "the layer has no aggregate cover left")

    ceded = calc.ceded_claim_minor(layer, gross_claim_minor)
    row = db.base_row()
    row.update({
        "layer_id": layer["id"],
        "claim_reference": claim_reference,
        "event_date": event_date,
        "gross_claim_minor": gross_claim_minor,
        "ceded_claim_minor": ceded,
        "disputed_minor": 0,
        "collected_minor": 0,
        "collectible_minor": ceded,
        "advocacy_route": None,
        "arbitration_cost_minor": 0,
        "reinstatement_triggered": False,
        "status": "NOTIFIED",
    })
    db.claim_advocacies[row["id"]] = row
    return response.object_response(serialize.claim_advocacy(row), 201)


@bp.route("/layers/<layer_id>/claim-advocacies", methods=["GET"])
def list_layer_advocacies(layer_id):
    require(EVERY_ROLE)
    validate.pagination()
    services.get_layer(layer_id)
    rows = services.advocacies_of_layer(layer_id)
    status = q("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paged(rows, serialize.claim_advocacy)
