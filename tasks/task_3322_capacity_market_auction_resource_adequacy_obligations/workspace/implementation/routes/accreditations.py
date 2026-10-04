"""Accreditations routes."""
from flask import Blueprint, request

from db import db
from middleware import require_roles, require_any
from response import success_object, success_list
from util import (base_entity, touch, dec, require_fields, is_number, get_body,
                  strip_internal, paginate, sort_created)
from errors import (err_not_found, err_invalid_request, err_invalid_state,
                    err_accreditation_conflict)
from services.calcs import accreditation_ucap, recompute_must_offer

bp = Blueprint("accreditations", __name__)

METHODS = ("CLASS_AVG", "UNIT_SPECIFIC")


def _serialize(a):
    return strip_internal(a)


@bp.route("/capacity-market/accreditations", methods=["POST"])
def create_accreditation():
    user_id, role = require_roles("ResourceOwner")
    body = get_body()
    require_fields(body, ["resource_id", "delivery_year_id", "method",
                          "forced_outage_rate", "scarcity_hours_sampled"])
    resource = db.resources.get(body["resource_id"])
    if resource is None:
        raise err_not_found("resource not found")
    dy = db.delivery_years.get(body["delivery_year_id"])
    if dy is None:
        raise err_not_found("delivery year not found")
    # ownership
    if user_id != resource["owner_id"]:
        from errors import err_ownership
        raise err_ownership()

    method = body["method"]
    if method not in METHODS:
        raise err_invalid_request("method must be CLASS_AVG or UNIT_SPECIFIC")
    class_avg = body.get("class_avg_factor")
    unit_elcc = body.get("unit_elcc_factor")
    forc = body["forced_outage_rate"]
    hours = body["scarcity_hours_sampled"]

    if method == "CLASS_AVG":
        if class_avg is None or not is_number(class_avg) or not (dec(class_avg) > 0 and dec(class_avg) <= 1):
            raise err_invalid_request("class_avg_factor required in (0,1] for CLASS_AVG")
    else:
        if unit_elcc is None or not is_number(unit_elcc) or not (dec(unit_elcc) > 0 and dec(unit_elcc) <= 1):
            raise err_invalid_request("unit_elcc_factor required in (0,1] for UNIT_SPECIFIC")
    if not is_number(forc) or not (dec(forc) >= 0 and dec(forc) < 1):
        raise err_invalid_request("forced_outage_rate must be in [0,1)")
    if isinstance(hours, bool) or not isinstance(hours, int) or hours < 1:
        raise err_invalid_request("scarcity_hours_sampled must be an integer >= 1")

    a = base_entity()
    a.update({
        "resource_id": resource["id"],
        "delivery_year_id": dy["id"],
        "method": method,
        "class_avg_factor": dec(class_avg) if class_avg is not None else None,
        "unit_elcc_factor": dec(unit_elcc) if unit_elcc is not None else None,
        "forced_outage_rate": dec(forc),
        "scarcity_hours_sampled": hours,
        "accreditation_factor": None,
        "ucap_mw": None,
        "status": "PENDING_REVIEW",
    })
    db.accreditations[a["id"]] = a
    return success_object(_serialize(a), 201)


@bp.route("/capacity-market/accreditations", methods=["GET"])
def list_accreditations():
    require_any()
    items = list(db.accreditations.values())
    for key in ("resource_id", "delivery_year_id", "status"):
        v = request.args.get(key)
        if v:
            items = [a for a in items if a.get(key) == v]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize(a) for a in page], limit, offset, total)


@bp.route("/capacity-market/accreditations/<acc_id>", methods=["GET"])
def get_accreditation(acc_id):
    require_any()
    a = db.accreditations.get(acc_id)
    if a is None:
        raise err_not_found("accreditation not found")
    return success_object(_serialize(a))


@bp.route("/capacity-market/accreditations/<acc_id>/approve", methods=["POST"])
def approve_accreditation(acc_id):
    require_roles("MarketAdmin")
    a = db.accreditations.get(acc_id)
    if a is None:
        raise err_not_found("accreditation not found")
    resource = db.resources.get(a["resource_id"])
    if resource is None:
        raise err_not_found("resource not found")
    if a["status"] != "PENDING_REVIEW":
        raise err_invalid_state("accreditation is not PENDING_REVIEW")
    dy = db.delivery_years.get(a["delivery_year_id"])
    if dy is None:
        raise err_not_found("delivery year not found")
    # business: uniqueness of EFFECTIVE accreditation per (resource, delivery year)
    # PRD §3.2 names ERR_ACCREDITATION_CONFLICT for a second effective
    # accreditation; because approval cascades the resource REGISTERED ->
    # ACCREDITED, checking resource state first would make the named conflict
    # error unreachable, so uniqueness is evaluated before it here.
    for other in db.accreditations.values():
        if (other["id"] != acc_id and other["resource_id"] == a["resource_id"]
                and other["delivery_year_id"] == a["delivery_year_id"]
                and other["status"] == "EFFECTIVE"):
            raise err_accreditation_conflict()
    # state: resource REGISTERED, delivery year DRAFT or FORECAST_LOCKED
    if resource["status"] != "REGISTERED":
        raise err_invalid_state("resource is not REGISTERED")
    if dy["status"] not in ("DRAFT", "FORECAST_LOCKED"):
        raise err_invalid_state("accreditation's delivery year is not in DRAFT or FORECAST_LOCKED")

    factor, ucap = accreditation_ucap(a, resource)
    a["accreditation_factor"] = factor
    a["ucap_mw"] = ucap
    a["status"] = "EFFECTIVE"
    touch(a)
    # cascade to resource
    resource["status"] = "ACCREDITED"
    resource["accredited_ucap_mw"] = ucap
    recompute_must_offer(resource)
    touch(resource)
    return success_object(_serialize(a))


@bp.route("/capacity-market/accreditations/<acc_id>/reject", methods=["POST"])
def reject_accreditation(acc_id):
    require_roles("MarketAdmin")
    a = db.accreditations.get(acc_id)
    if a is None:
        raise err_not_found("accreditation not found")
    if a["status"] != "PENDING_REVIEW":
        raise err_invalid_state("accreditation is not PENDING_REVIEW")
    a["status"] = "REJECTED"
    touch(a)
    return success_object(_serialize(a))
