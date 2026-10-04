"""Investigative demands and negotiated consolidated responses."""
from flask import Blueprint

import auth
import db
import envelope
import errors
import serialize
import validate

bp = Blueprint("demands_responses", __name__, url_prefix="/multistate")

AG_ROLES = ("ParticipatingStateAG", "LeadStateAG")


@bp.route("/participations/<participation_id>/demands", methods=["POST"])
def create_demand(participation_id):
    role, uid = auth.authenticate()
    auth.require_roles(role, AG_ROLES)
    body = validate.body_json()
    scope_text = validate.req_str(body, "scope_text")
    part = validate.get_participation_or_404(participation_id)
    auth.require_own_office(part, uid)
    if part["status"] != "ACTIVE":
        raise errors.ApiError(
            "ERR_PARTICIPATION_INACTIVE",
            409,
            "CIA must be executed before issuing under state authority",
        )
    inv = db.investigations.get(part["investigation_id"])
    if inv is None or inv["phase"] not in ("OPEN", "DISCOVERY"):
        raise errors.invalid_phase("Demands may be issued only in OPEN or DISCOVERY phase")
    demand = db.new_entity(db.demands)
    demand.update(
        {
            "participation_id": part["id"],
            "scope_text": scope_text,
            "status": "ISSUED",
            "issued_at": db.now(),
            "consolidated_at": None,
            "consolidated_response_id": None,
        }
    )
    return envelope.success_object(serialize.serialize("demand", demand), 201)


@bp.route("/participations/<participation_id>/demands", methods=["GET"])
def list_demands(participation_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    limit, offset = validate.pagination_params()
    validate.get_participation_or_404(participation_id)
    items = [d for d in db.demands.values() if d["participation_id"] == participation_id]
    page, total = validate.paginate(items, limit, offset)
    return envelope.success_list(
        serialize.serialize_list("demand", page), limit, offset, total
    )


@bp.route("/investigations/<investigation_id>/responses", methods=["POST"])
def create_response(investigation_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("DefendantCounsel",))
    body = validate.body_json()
    demand_ids = validate.req_str_list(body, "demand_ids")
    coverage_summary = validate.req_str(body, "coverage_summary")
    inv = validate.get_investigation_or_404(investigation_id)
    if inv["phase"] not in ("DISCOVERY", "NEGOTIATION"):
        raise errors.invalid_phase(
            "Consolidated responses may be submitted only in DISCOVERY or NEGOTIATION"
        )
    if not demand_ids:
        raise errors.ApiError(
            "ERR_RESPONSE_DEMANDS_INVALID", 422, "demand_ids must be non-empty"
        )
    for demand_id in demand_ids:
        demand = db.demands.get(demand_id)
        if demand is None:
            raise errors.ApiError(
                "ERR_RESPONSE_DEMANDS_INVALID", 422, f"No Demand with id {demand_id}"
            )
        part = db.participations.get(demand["participation_id"])
        if part is None or part["investigation_id"] != inv["id"]:
            raise errors.ApiError(
                "ERR_RESPONSE_DEMANDS_INVALID",
                422,
                "demand_ids must all belong to this investigation",
            )
        if demand["status"] != "ISSUED":
            raise errors.ApiError(
                "ERR_RESPONSE_DEMANDS_INVALID",
                422,
                "Every listed demand must still be ISSUED",
            )
    resp = db.new_entity(db.responses)
    resp.update(
        {
            "investigation_id": inv["id"],
            "demand_ids": list(demand_ids),
            "coverage_summary": coverage_summary,
            "status": "SUBMITTED",
            "submitted_at": db.now(),
            "accepted_at": None,
            "fulfilled_at": None,
        }
    )
    return envelope.success_object(serialize.serialize("response", resp), 201)


@bp.route("/responses/<response_id>/accept", methods=["POST"])
def accept_response(response_id):
    role, uid = auth.authenticate()
    auth.require_roles(role, ("LeadStateAG",))
    resp = validate.get_response_or_404(response_id)
    auth.require_lead_active(resp["investigation_id"], uid)
    if resp["status"] != "SUBMITTED":
        raise errors.invalid_state("Response is not SUBMITTED")
    now = db.now()
    resp["status"] = "ACCEPTED"
    resp["accepted_at"] = now
    db.touch(resp)
    # Atomic cascade: fold every listed demand ISSUED -> CONSOLIDATED.
    for demand_id in resp["demand_ids"]:
        demand = db.demands.get(demand_id)
        if demand is None:
            continue
        demand["status"] = "CONSOLIDATED"
        demand["consolidated_at"] = now
        demand["consolidated_response_id"] = resp["id"]
        db.touch(demand)
    return envelope.success_object(serialize.serialize("response", resp))


@bp.route("/responses/<response_id>/fulfill", methods=["POST"])
def fulfill_response(response_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("DefendantCounsel",))
    resp = validate.get_response_or_404(response_id)
    if resp["status"] != "ACCEPTED":
        raise errors.invalid_state("Response is not ACCEPTED")
    resp["status"] = "FULFILLED"
    resp["fulfilled_at"] = db.now()
    db.touch(resp)
    return envelope.success_object(serialize.serialize("response", resp))
