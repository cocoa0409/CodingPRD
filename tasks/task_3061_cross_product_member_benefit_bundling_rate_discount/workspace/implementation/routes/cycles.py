"""Requalification cycle lifecycle routes."""

from flask import Blueprint

from db import DB
from errors import ERR_INVALID_STATE, ApiError
from middleware import auth
from response import ok_object
from routes.common import fetch, guard_member_view, list_response
from services import serialize, workflows

BP = Blueprint("cycles", __name__)


@BP.route("/benefits/requalification-cycles", methods=["GET"])
def list_cycles():
    auth(("PlatformAdmin", "BenefitsAdmin", "ComplianceOfficer"))
    items = list(DB.cycles.values())
    filters = {"member_id": "member_id", "status": "status"}
    return list_response(items, serialize.cycle, filters)


@BP.route("/benefits/requalification-cycles/<cycle_id>", methods=["GET"])
def get_cycle(cycle_id):
    user_id, role = auth(("PlatformAdmin", "BenefitsAdmin", "ComplianceOfficer", "Member"))
    cycle = fetch("cycles", cycle_id)
    guard_member_view(user_id, role, cycle["member_id"])
    return ok_object(serialize.cycle(cycle))


@BP.route("/benefits/requalification-cycles/<cycle_id>/evaluate", methods=["POST"])
def evaluate_cycle(cycle_id):
    auth(("PlatformAdmin",))
    cycle = fetch("cycles", cycle_id)
    if cycle["status"] not in ("OPEN", "REMEDIATION"):
        raise ApiError(ERR_INVALID_STATE)
    workflows.evaluate_cycle(cycle)
    return ok_object(serialize.cycle(cycle))


@BP.route("/benefits/requalification-cycles/<cycle_id>/open-remediation", methods=["POST"])
def open_remediation(cycle_id):
    auth(("PlatformAdmin",))
    cycle = fetch("cycles", cycle_id)
    if cycle["status"] != "FAILED":
        raise ApiError(ERR_INVALID_STATE)
    workflows.open_remediation(cycle)
    return ok_object(serialize.cycle(cycle))


@BP.route("/benefits/requalification-cycles/<cycle_id>/close", methods=["POST"])
def close_cycle(cycle_id):
    auth(("PlatformAdmin",))
    cycle = fetch("cycles", cycle_id)
    if cycle["status"] not in ("PASSED", "FAILED"):
        raise ApiError(ERR_INVALID_STATE)
    successor = workflows.close_cycle(cycle)
    return ok_object(serialize.cycle(successor))