"""Market submissions, quoting and the bounded negotiation cycle (PRD 3.4-3.5)."""
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
    BROKER_PLACEMENT_LEAD,
    REINSURER_UNDERWRITER,
    own_reinsurer,
    require,
)
from routes._common import REINSURER_READ, ordered_filtered, paged, q
from util import dec, pct4

bp = Blueprint("quotes", __name__)


# ---------------------------------------------------------------------------
# Market submissions
# ---------------------------------------------------------------------------

@bp.route("/market-submissions", methods=["GET"])
def list_market_submissions():
    require(REINSURER_READ)
    rows = ordered_filtered(db.market_submissions, [
        ("layer_id", q("layer_id")),
        ("reinsurer_id", q("reinsurer_id")),
        ("status", q("status")),
    ])
    return paged(rows, serialize.market_submission)


@bp.route("/market-submissions/<market_submission_id>", methods=["GET"])
def read_market_submission(market_submission_id):
    require(REINSURER_READ)
    row = services.get_market_submission(market_submission_id)
    return response.object_response(serialize.market_submission(row), 200)


@bp.route("/market-submissions/<market_submission_id>/quotes", methods=["GET"])
def list_submission_quotes(market_submission_id):
    require(REINSURER_READ)
    validate.pagination()
    services.get_market_submission(market_submission_id)
    rows = [r for r in db.ordered(db.quotes)
            if r["market_submission_id"] == market_submission_id]
    status = q("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paged(rows, serialize.quote)


# ---------------------------------------------------------------------------
# Quoting
# ---------------------------------------------------------------------------

def _read_terms(shape):
    """The seven negotiable terms plus the two optional inputs (PRD 3.4)."""
    terms = {}
    terms["offered_line_pct"] = shape.percent("offered_line_pct",
                                              exclusive_min=0, maximum=100)
    terms["quoted_rate_pct"] = shape.percent("quoted_rate_pct",
                                             exclusive_min=0, maximum=100)
    terms["ceding_commission_pct"] = shape.percent("ceding_commission_pct",
                                                   minimum=0, maximum=60)
    terms["reinstatements_offered"] = shape.integer("reinstatements_offered",
                                                    minimum=0, maximum=5)
    terms["sublimit_minor"] = shape.money("sublimit_minor", minimum=0)
    terms["expires_at"] = shape.instant("expires_at")
    terms["is_lead"] = shape.boolean("is_lead", required=False, default=False)
    terms["additional_exclusions"] = shape.enum_array(
        "additional_exclusions", enums.PERILS, required=False, default=[])
    return terms


def _check_lead(market, is_lead):
    """Priority 38: a RESTRICTED market may follow but never lead."""
    if not is_lead:
        return
    if not market["lead_authorised"] or market["security_status"] != "APPROVED":
        fail("ERR_LEAD_NOT_AUTHORISED",
             "the quoting market is not authorised to lead")


@bp.route("/market-submissions/<market_submission_id>/quotes", methods=["POST"])
def create_quote(market_submission_id):
    actor = require((REINSURER_UNDERWRITER,))
    existing = db.market_submissions.get(market_submission_id)
    if existing is not None:
        own_reinsurer(actor, existing["reinsurer_id"])

    shape = validate.Shape()
    terms = _read_terms(shape)

    submission = services.get_market_submission(market_submission_id)
    if submission["status"] != "SENT":
        fail("ERR_MARKET_SUBMISSION_CLOSED",
             "the submission is no longer open for quoting")
    layer = services.get_layer(submission["layer_id"])
    program = services.program_of_layer(layer)
    if program["placement_status"] != "IN_MARKET":
        fail("ERR_PROGRAM_STATE_INVALID", "the owning program must be IN_MARKET")

    market = db.reinsurers[submission["reinsurer_id"]]
    _check_lead(market, terms["is_lead"])

    if terms["expires_at"] <= db.now():
        fail("ERR_DEADLINE_NOT_IN_FUTURE",
             "expires_at must be strictly after the current instant")
    if db.now() > submission["response_deadline"]:
        fail("ERR_RESPONSE_DEADLINE_PASSED",
             "the submission's response_deadline has passed")

    row = db.base_row()
    row.update({
        "market_submission_id": submission["id"],
        "layer_id": submission["layer_id"],
        "reinsurer_id": submission["reinsurer_id"],
        "offered_line_pct": pct4(terms["offered_line_pct"]),
        "quoted_rate_pct": pct4(terms["quoted_rate_pct"]),
        "ceding_commission_pct": pct4(terms["ceding_commission_pct"]),
        "reinstatements_offered": terms["reinstatements_offered"],
        "sublimit_minor": terms["sublimit_minor"],
        "additional_exclusions": list(terms["additional_exclusions"]),
        "is_lead": terms["is_lead"],
        "expires_at": terms["expires_at"],
        "negotiation_round": 0,
        "last_counter_note": None,
        "accepted_line_pct": None,
        "status": "QUOTED",
    })
    db.quotes[row["id"]] = row

    submission["status"] = "QUOTED"
    db.touch(submission)
    return response.object_response(serialize.quote(row), 201)


@bp.route("/quotes", methods=["GET"])
def list_quotes():
    require(REINSURER_READ)
    rows = ordered_filtered(db.quotes, [
        ("market_submission_id", q("market_submission_id")),
        ("layer_id", q("layer_id")),
        ("reinsurer_id", q("reinsurer_id")),
        ("status", q("status")),
    ])
    return paged(rows, serialize.quote)


@bp.route("/quotes/<quote_id>", methods=["GET"])
def read_quote(quote_id):
    require(REINSURER_READ)
    row = services.get_quote(quote_id)
    return response.object_response(serialize.quote(row), 200)


# ---------------------------------------------------------------------------
# The negotiation cycle
# ---------------------------------------------------------------------------

@bp.route("/quotes/<quote_id>/counter", methods=["POST"])
def counter_quote(quote_id):
    require((BROKER_PLACEMENT_LEAD,))
    shape = validate.Shape()
    counter_note = shape.string("counter_note", min_len=1, max_len=500)

    quote = services.get_quote(quote_id)
    if quote["status"] not in ("QUOTED", "REQUOTED"):
        fail("ERR_QUOTE_STATE_INVALID",
             "only a QUOTED or REQUOTED quote may be countered")
    if db.now() >= quote["expires_at"]:
        fail("ERR_QUOTE_EXPIRED", "the quote has already lapsed")
    if quote["negotiation_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
        fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
             "the quote has exhausted its negotiation rounds")

    quote["negotiation_round"] = quote["negotiation_round"] + 1
    quote["last_counter_note"] = counter_note
    quote["status"] = "COUNTERED"
    db.touch(quote)
    return response.object_response(serialize.quote(quote), 200)


@bp.route("/quotes/<quote_id>/requote", methods=["POST"])
def requote(quote_id):
    actor = require((REINSURER_UNDERWRITER,))
    existing = db.quotes.get(quote_id)
    if existing is not None:
        own_reinsurer(actor, existing["reinsurer_id"])

    shape = validate.Shape()
    terms = _read_terms(shape)

    quote = services.get_quote(quote_id)
    if quote["status"] != "COUNTERED":
        fail("ERR_QUOTE_STATE_INVALID", "only a COUNTERED quote may be requoted")

    market = db.reinsurers[quote["reinsurer_id"]]
    _check_lead(market, terms["is_lead"])

    if terms["expires_at"] <= db.now():
        fail("ERR_DEADLINE_NOT_IN_FUTURE",
             "expires_at must be strictly after the current instant")

    quote["offered_line_pct"] = pct4(terms["offered_line_pct"])
    quote["quoted_rate_pct"] = pct4(terms["quoted_rate_pct"])
    quote["ceding_commission_pct"] = pct4(terms["ceding_commission_pct"])
    quote["reinstatements_offered"] = terms["reinstatements_offered"]
    quote["sublimit_minor"] = terms["sublimit_minor"]
    quote["additional_exclusions"] = list(terms["additional_exclusions"])
    quote["is_lead"] = terms["is_lead"]
    quote["expires_at"] = terms["expires_at"]
    quote["status"] = "REQUOTED"
    db.touch(quote)
    return response.object_response(serialize.quote(quote), 200)


@bp.route("/quotes/<quote_id>/decline", methods=["POST"])
def decline_quote(quote_id):
    actor = require((REINSURER_UNDERWRITER,))
    existing = db.quotes.get(quote_id)
    if existing is not None:
        own_reinsurer(actor, existing["reinsurer_id"])

    shape = validate.Shape(patch=True)
    shape.string("decline_reason", min_len=1, max_len=500,
                 required=False, default=None)

    quote = services.get_quote(quote_id)
    if quote["status"] not in ("QUOTED", "COUNTERED", "REQUOTED"):
        fail("ERR_QUOTE_STATE_INVALID", "a %s quote may not be declined"
             % quote["status"])

    quote["status"] = "DECLINED"
    db.touch(quote)
    submission = db.market_submissions.get(quote["market_submission_id"])
    if submission is not None and submission["status"] in ("SENT", "QUOTED"):
        submission["status"] = "DECLINED"
        db.touch(submission)
    return response.object_response(serialize.quote(quote), 200)


# ---------------------------------------------------------------------------
# Firm orders (PRD 3.5)
# ---------------------------------------------------------------------------

@bp.route("/quotes/<quote_id>/firm-order", methods=["POST"])
def firm_order(quote_id):
    require((BROKER_PLACEMENT_LEAD,))
    shape = validate.Shape()
    accepted_line_pct = shape.percent("accepted_line_pct",
                                      exclusive_min=0, maximum=100)
    expected_layer_version = shape.integer("expected_layer_version", minimum=0)

    quote = services.get_quote(quote_id)
    if quote["status"] not in ("QUOTED", "REQUOTED"):
        fail("ERR_QUOTE_STATE_INVALID",
             "only a QUOTED or REQUOTED quote may be firm-ordered")
    layer = services.get_layer(quote["layer_id"])
    program = services.program_of_layer(layer)
    if program["placement_status"] != "IN_MARKET":
        fail("ERR_PROGRAM_STATE_INVALID", "the owning program must be IN_MARKET")
    if expected_layer_version != layer["version"]:
        fail("ERR_STALE_LAYER_VERSION",
             "expected_layer_version does not match the layer's current version")

    market = db.reinsurers[quote["reinsurer_id"]]
    if market["security_status"] not in ("APPROVED", "RESTRICTED"):
        fail("ERR_MARKET_SUSPENDED", "a suspended market cannot be firm-ordered")
    if db.now() >= quote["expires_at"]:
        fail("ERR_QUOTE_EXPIRED", "the quote has already lapsed")
    if dec(accepted_line_pct) > dec(quote["offered_line_pct"]):
        fail("ERR_LINE_EXCEEDS_OFFER",
             "accepted_line_pct exceeds the line the market offered")
    if dec(accepted_line_pct) > dec(market["max_line_pct"]):
        fail("ERR_LINE_EXCEEDS_MAX_LINE",
             "accepted_line_pct exceeds the market's max_line_pct")

    windowed = services.windowed_committed_capacity(market["id"], program)
    this_line = calc.line_capacity_minor(layer["limit_minor"], accepted_line_pct)
    if windowed + this_line > market["capacity_limit_minor"]:
        fail("ERR_CAPACITY_EXCEEDED",
             "the line would breach the market's aggregate capacity")

    line = services.firm_order_cascade(layer, quote, accepted_line_pct, program)
    return response.object_response(serialize.signing_line(line), 201)
