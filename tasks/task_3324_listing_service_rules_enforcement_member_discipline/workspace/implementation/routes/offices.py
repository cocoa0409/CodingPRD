"""Office endpoints: create/list/get/close + flat list/read."""

from flask import Blueprint, request

from auth import require_roles
from db import store
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_DUPLICATE_RESOURCE,
                    ERR_ASSOCIATION_MERGED, ERR_INVALID_STATE,
                    ERR_CROSS_ASSOCIATION_REFERENCE,
                    ERR_OFFICE_HAS_OPEN_LISTINGS)
from helpers import (body, mint_common, touch, get_association, get_member,
                     get_office, page)
from response import success_object, success_list
from routes.members import check_not_merged

bp = Blueprint("offices", __name__)


@bp.route("/mls/associations/<assoc_id>/offices", methods=["POST"])
def create_office(assoc_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    check_not_merged(assoc)
    data = body()
    for f in ("office_code", "broker_member_id"):
        if data.get(f) is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f)
    broker = store.members.get(data["broker_member_id"])
    if broker is None or broker["association_id"] != assoc_id:
        raise_err(ERR_CROSS_ASSOCIATION_REFERENCE,
                  "broker_member_id must reference a member of this association")
    if broker["membership_state"] != "ACTIVE":
        raise_err(ERR_CROSS_ASSOCIATION_REFERENCE,
                  "broker_member_id must be an ACTIVE member of this association")
    for o in store.offices.values():
        if o["office_code"] == data["office_code"]:
            raise_err(ERR_DUPLICATE_RESOURCE,
                      "office_code '%s' already exists" % data["office_code"])
    office = {
        "association_id": assoc_id,
        "office_code": data["office_code"],
        "broker_member_id": data["broker_member_id"],
        "status": "ACTIVE",
    }
    mint_common(office)
    store.offices[office["id"]] = office
    return success_object(office, 201)


@bp.route("/mls/associations/<assoc_id>/offices", methods=["GET"])
def list_offices(assoc_id):
    require_roles("AssociationStaff", "Member")
    get_association(assoc_id)
    items = [o for o in store.offices.values() if o["association_id"] == assoc_id]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/associations/<assoc_id>/offices/<office_id>", methods=["GET"])
def get_office_route(assoc_id, office_id):
    require_roles("AssociationStaff", "Member")
    get_association(assoc_id)
    return success_object(get_office(office_id, assoc_id))


@bp.route("/mls/associations/<assoc_id>/offices/<office_id>/close",
          methods=["POST"])
def close_office(assoc_id, office_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    office = get_office(office_id, assoc_id)
    check_not_merged(assoc)
    if office["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE office may be closed")
    open_listings = [l for l in store.listings.values()
                     if l["office_id"] == office_id
                     and l["status"] in ("DRAFT", "ACTIVE", "PENDING")]
    if open_listings:
        raise_err(ERR_OFFICE_HAS_OPEN_LISTINGS,
                  "Office has listings in DRAFT/ACTIVE/PENDING")
    office["status"] = "CLOSED"
    touch(office)
    return success_object(office)


# --- flat office routes ---

@bp.route("/mls/offices", methods=["GET"])
def flat_list_offices():
    require_roles("AssociationStaff", "Member")
    items = list(store.offices.values())
    broker = request.args.get("broker_member_id")
    if broker is not None:
        items = [o for o in items if o["broker_member_id"] == broker]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/offices/<office_id>", methods=["GET"])
def flat_get_office(office_id):
    require_roles("AssociationStaff", "Member")
    return success_object(get_office(office_id))
