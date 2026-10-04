"""Association endpoints: create/list/get."""

from flask import Blueprint, request

from auth import require_roles
from db import store
from errors import raise_err, ERR_INVALID_REQUEST, ERR_DUPLICATE_RESOURCE
from helpers import body, mint_common, get_association, page
from response import success_object, success_list

bp = Blueprint("associations", __name__)


@bp.route("/mls/associations", methods=["POST"])
def create_association():
    require_roles("AssociationStaff")
    data = body()
    for f in ("association_code", "name", "membership_dues_cents",
              "late_fee_tier1_cents", "late_fee_tier2_cents"):
        if data.get(f) is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f)
    for f in ("membership_dues_cents", "late_fee_tier1_cents", "late_fee_tier2_cents"):
        v = data[f]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an integer >= 0" % f)
    cap = data.get("sanction_credit_cap_cents", 200000)
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
        raise_err(ERR_INVALID_REQUEST,
                  "Field 'sanction_credit_cap_cents' must be an integer >= 0")
    for a in store.associations.values():
        if a["association_code"] == data["association_code"]:
            raise_err(ERR_DUPLICATE_RESOURCE,
                      "association_code '%s' already exists" % data["association_code"])
    assoc = {
        "association_code": data["association_code"],
        "name": data["name"],
        "consolidation_state": "ACTIVE",
        "consolidated_into_id": None,
        "membership_dues_cents": data["membership_dues_cents"],
        "late_fee_tier1_cents": data["late_fee_tier1_cents"],
        "late_fee_tier2_cents": data["late_fee_tier2_cents"],
        "sanction_credit_cap_cents": cap,
    }
    mint_common(assoc)
    store.associations[assoc["id"]] = assoc
    return success_object(assoc, 201)


@bp.route("/mls/associations", methods=["GET"])
def list_associations():
    require_roles("AssociationStaff")
    items = list(store.associations.values())
    state = request.args.get("consolidation_state")
    if state is not None:
        items = [a for a in items if a["consolidation_state"] == state]
    into = request.args.get("consolidated_into_id")
    if into is not None:
        items = [a for a in items if a.get("consolidated_into_id") == into]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/associations/<assoc_id>", methods=["GET"])
def get_association_route(assoc_id):
    require_roles("AssociationStaff", "Member", "GrievanceMember", "HearingPanelist")
    return success_object(get_association(assoc_id))
