"""Collection objects (PRD 3.4/3.5): direct accession, read, and release
from conservation hold."""

from flask import Blueprint

import db
import serializers
import util
from envelope import success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("collection_objects", __name__)

OBJECT_READ_ROLES = [
    "PlatformAdmin",
    "Registrar",
    "LoansOfficer",
    "Curator",
    "CommitteeChair",
    "Scholar",
]


@bp.post("/campus/collection-objects")
def create_object():
    _uid, role = auth()
    require_role(role, ["Registrar"])
    b = util.body()
    accession_number = util.req_str(b, "accession_number")
    title = util.req_str(b, "title")
    declared_value_cents = util.req_int(b, "declared_value_cents", minimum=0)
    is_cultural_property = util.opt_bool(b, "is_cultural_property", False)
    for o in db.STORE["collection_objects"].values():
        if o["accession_number"] == accession_number:
            fail("ERR_INVALID_REQUEST", "accession_number must be unique")
    o = db.new_entity(
        {
            "accession_number": accession_number,
            "title": title,
            "declared_value_cents": declared_value_cents,
            "is_cultural_property": is_cultural_property,
            "status": "IN_COLLECTION",
        }
    )
    db.STORE["collection_objects"][o["id"]] = o
    return success(serializers.collection_object(o), 201)


@bp.get("/campus/collection-objects/<oid>")
def get_object(oid):
    _uid, role = auth()
    require_role(role, OBJECT_READ_ROLES)
    o = get_or_404("collection_objects", oid, "CollectionObject")
    return success(serializers.collection_object(o))


@bp.post("/campus/collection-objects/<oid>/release-conservation")
def release_conservation(oid):
    _uid, role = auth()
    require_role(role, ["Registrar"])
    o = get_or_404("collection_objects", oid, "CollectionObject")
    if o["status"] != "UNDER_CONSERVATION":
        fail(
            "ERR_INVALID_STATE",
            "Only an UNDER_CONSERVATION object can be released to the collection",
        )
    o["status"] = "IN_COLLECTION"
    db.touch(o)
    return success(serializers.collection_object(o))
