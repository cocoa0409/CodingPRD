"""Capacity resources routes."""
from flask import Blueprint, request

from db import db
from middleware import require_roles, require_any
from response import success_object, success_list
from util import (base_entity, touch, dec, require_fields, is_number, get_body,
                  strip_internal, paginate, sort_created)
from errors import (err_not_found, err_invalid_request, err_invalid_state,
                    err_ownership)
from services.calcs import recompute_must_offer

bp = Blueprint("resources", __name__)

RESOURCE_TYPES = ("GEN", "DR", "EE")


def _serialize(r):
    return strip_internal(r)


@bp.route("/capacity-market/resources", methods=["POST"])
def create_resource():
    user_id, role = require_roles("ResourceOwner")
    body = get_body()
    require_fields(body, ["owner_id", "zone_id", "resource_type", "nameplate_mw"])
    owner_id = body["owner_id"]
    zone_id = body["zone_id"]
    owner = db.owners.get(owner_id)
    if owner is None:
        raise err_not_found("owner not found")
    zone = db.zones.get(zone_id)
    if zone is None:
        raise err_not_found("zone not found")
    # ownership: acting owner must equal owner_id
    if user_id != owner_id:
        raise err_ownership()
    rtype = body["resource_type"]
    nameplate = body["nameplate_mw"]
    if rtype not in RESOURCE_TYPES:
        raise err_invalid_request("resource_type must be one of GEN, DR, EE")
    if not is_number(nameplate) or dec(nameplate) <= 0:
        raise err_invalid_request("nameplate_mw must be > 0")
    r = base_entity()
    r.update({
        "owner_id": owner_id,
        "zone_id": zone_id,
        "resource_type": rtype,
        "nameplate_mw": dec(nameplate),
        "status": "REGISTERED",
        "accredited_ucap_mw": 0,
        "must_offer": False,
    })
    db.resources[r["id"]] = r
    return success_object(_serialize(r), 201)


@bp.route("/capacity-market/resources", methods=["GET"])
def list_resources():
    require_any()
    items = list(db.resources.values())
    for key in ("owner_id", "zone_id", "resource_type", "status"):
        v = request.args.get(key)
        if v:
            items = [r for r in items if r.get(key) == v]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize(r) for r in page], limit, offset, total)


@bp.route("/capacity-market/resources/<res_id>", methods=["GET"])
def get_resource(res_id):
    require_any()
    r = db.resources.get(res_id)
    if r is None:
        raise err_not_found("resource not found")
    return success_object(_serialize(r))


@bp.route("/capacity-market/resources/<res_id>/retire", methods=["POST"])
def retire_resource(res_id):
    user_id, role = require_roles("ResourceOwner")
    r = db.resources.get(res_id)
    if r is None:
        raise err_not_found("resource not found")
    if r["status"] != "ACCREDITED":
        raise err_invalid_state("resource is not ACCREDITED")
    if user_id != r["owner_id"]:
        raise err_ownership()
    # business: no ACTIVE or REPLACEMENT_PENDING commitments
    for c in db.commitments.values():
        if c["resource_id"] == res_id and c["status"] in ("ACTIVE", "REPLACEMENT_PENDING"):
            raise err_invalid_state("resource has live commitments")
    r["status"] = "RETIRED"
    touch(r)
    for o in db.offers.values():
        if o["resource_id"] == res_id and o["status"] == "SUBMITTED":
            o["status"] = "WITHDRAWN"
            touch(o)
    return success_object(_serialize(r))
