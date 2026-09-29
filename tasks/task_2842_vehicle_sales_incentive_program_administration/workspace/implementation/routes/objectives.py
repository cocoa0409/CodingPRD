"""Stair-step objective proposal, the protest cycle and finalization."""

from flask import Blueprint, request

import db
import errors
import response
import serializers
import validate
from middleware import ROLE_DEALER as DEALER
from middleware import ROLE_FIELD_SALES_MANAGER as FIELD
from middleware import ROLE_INCENTIVE_CONTROLLER as CONTROLLER
from middleware import ROLE_PROGRAM_DESIGNER as DESIGNER
from middleware import caller_id, require_roles, touch
from routes import helpers
from services import calc, ledger

bp = Blueprint("objectives", __name__)

OBJECTIVE_STATUSES = ("PROPOSED", "PROTESTED", "REVISED", "FINAL", "VOID")
PROTEST_STATUSES = ("OPEN", "UPHELD", "DENIED")
RESOLUTIONS = ("UPHELD", "DENIED")


@bp.route("/programs/<program_id>/objectives", methods=["POST"])
@require_roles(FIELD)
def assign_objective(program_id):
    program = helpers.get_program(program_id)
    payload = validate.body()
    dealer_id = validate.get_string(payload, "dealer_id", min_len=1)
    stretch_bps = validate.get_int(
        payload, "stretch_bps", required=False, default=0, minimum=0, maximum=10000
    )

    dealer = helpers.get_dealer(dealer_id)

    if program["status"] != "ACTIVE":
        raise errors.ApiError("ERR_PROGRAM_NOT_ACTIVE")

    basis_units = dealer["historical_volume_units"]
    objective_units = calc.objective_units_from_basis(
        basis_units, dealer["market_opportunity_bps"], stretch_bps
    )
    objective = db.insert(
        db.objectives,
        "objective",
        {
            "program_id": program_id,
            "dealer_id": dealer_id,
            "stretch_bps": stretch_bps,
            "basis_units": basis_units,
            "objective_units": objective_units,
            "status": "PROPOSED",
            "protest_round": 0,
            "achieved_units": 0,
            "attainment_bps": 0,
            "tier_attained": 0,
            "payout_cents": 0,
            "paid_payout_cents": 0,
        },
    )
    # A mid-month objective is born at the dealer's month-to-date position.
    ledger.recompute_objective(objective, bump=False)
    return response.object_response(serializers.objective(objective), 201)


@bp.route("/programs/<program_id>/objectives", methods=["GET"])
@require_roles(FIELD, CONTROLLER, DESIGNER)
def list_program_objectives(program_id):
    helpers.get_program(program_id)
    status = validate.query_enum("status", OBJECTIVE_STATUSES)
    rows = calc.program_objectives(program_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.listing(rows, request.args, serializers.objective)


@bp.route("/objectives", methods=["GET"])
@require_roles(FIELD, CONTROLLER, DESIGNER, DEALER)
def list_objectives():
    dealer_id = validate.query_string("dealer_id")
    program_id = validate.query_string("program_id")
    status = validate.query_enum("status", OBJECTIVE_STATUSES)
    rows = db.ordered(list(db.objectives.values()))
    if dealer_id is not None:
        rows = [r for r in rows if r["dealer_id"] == dealer_id]
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.listing(rows, request.args, serializers.objective)


@bp.route("/objectives/<objective_id>", methods=["GET"])
@require_roles(FIELD, CONTROLLER, DESIGNER, DEALER)
def read_objective(objective_id):
    objective = helpers.get_objective(objective_id)
    return response.object_response(serializers.objective(objective))


# --------------------------------------------------------------------------
# The protest cycle
# --------------------------------------------------------------------------

@bp.route("/objectives/<objective_id>/protests", methods=["POST"])
@require_roles(DEALER)
def file_protest(objective_id):
    objective = helpers.get_objective(objective_id)
    helpers.require_dealer_ownership(objective["dealer_id"])
    payload = validate.body()
    claimed_basis_units = validate.get_int(payload, "claimed_basis_units", minimum=0)
    reason = validate.get_string(payload, "reason", min_len=1, max_len=500)

    if objective["status"] not in ("PROPOSED", "REVISED", "FINAL"):
        raise errors.ApiError("ERR_OBJECTIVE_INVALID_STATE")
    program = db.programs[objective["program_id"]]
    if program["status"] != "ACTIVE":
        raise errors.ApiError("ERR_PROGRAM_NOT_ACTIVE")
    if objective["protest_round"] >= calc.MAX_PROTEST_ROUNDS:
        raise errors.ApiError("ERR_PROTEST_LIMIT_REACHED")

    protest = db.insert(
        db.protests,
        "protest",
        {
            "objective_id": objective_id,
            "round_index": objective["protest_round"] + 1,
            "claimed_basis_units": claimed_basis_units,
            "reason": reason,
            "status": "OPEN",
            "resolved_units": None,
            "resolved_by_user_id": None,
        },
    )
    objective["protest_round"] = objective["protest_round"] + 1
    objective["status"] = "PROTESTED"
    touch(objective)
    return response.object_response(serializers.protest(protest), 201)


@bp.route("/objectives/<objective_id>/protests", methods=["GET"])
@require_roles(FIELD, CONTROLLER, DEALER)
def list_protests(objective_id):
    helpers.get_objective(objective_id)
    status = validate.query_enum("status", PROTEST_STATUSES)
    rows = calc.objective_protests(objective_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.listing(rows, request.args, serializers.protest)


@bp.route("/objectives/<objective_id>/protests/<protest_id>/resolve", methods=["POST"])
@require_roles(FIELD)
def resolve_protest(objective_id, protest_id):
    objective = helpers.get_objective(objective_id)
    protest = helpers.get_protest(protest_id)
    if protest["objective_id"] != objective_id:
        raise errors.ApiError("ERR_PROTEST_NOT_FOUND")

    payload = validate.body()
    resolution = validate.get_enum(payload, "resolution", RESOLUTIONS)
    expected_version = validate.get_int(payload, "expected_objective_version")

    if expected_version != objective["version"]:
        raise errors.ApiError("ERR_STALE_OBJECTIVE_VERSION")

    if protest["status"] != "OPEN":
        raise errors.ApiError("ERR_PROTEST_ALREADY_RESOLVED")
    if objective["status"] != "PROTESTED":
        raise errors.ApiError("ERR_OBJECTIVE_INVALID_STATE")

    protest["resolved_by_user_id"] = caller_id()

    if resolution == "UPHELD":
        protest["status"] = "UPHELD"
        objective["status"] = "REVISED"
        ledger.uphold_cascade(objective, protest)
    else:
        protest["status"] = "DENIED"
        protest["resolved_units"] = None
        objective["status"] = "PROPOSED" if protest["round_index"] == 1 else "REVISED"

    touch(protest)
    touch(objective)
    return response.object_response(serializers.protest(protest))


@bp.route("/objectives/<objective_id>/finalize", methods=["POST"])
@require_roles(FIELD)
def finalize_objective(objective_id):
    objective = helpers.get_objective(objective_id)
    validate.body()
    if objective["status"] not in ("PROPOSED", "REVISED"):
        raise errors.ApiError("ERR_OBJECTIVE_INVALID_STATE")
    for protest in calc.objective_protests(objective_id):
        if protest["status"] == "OPEN":
            raise errors.ApiError("ERR_OBJECTIVE_INVALID_STATE")
    objective["status"] = "FINAL"
    touch(objective)
    return response.object_response(serializers.objective(objective))
