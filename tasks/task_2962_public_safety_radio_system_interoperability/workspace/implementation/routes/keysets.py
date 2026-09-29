"""Encryption keyset custody, approval and the compromise cascade."""
from flask import Blueprint

import common
import compute
import db
import enums
import response
import serialize
import validate
from errors import ApiError
from validate import KEY_CUSTODIAN, SECURITY_OFFICER

bp = Blueprint("keysets", __name__, url_prefix=common.PREFIX)


@bp.post("/keysets")
def create_keyset():
    actor = validate.authenticate([KEY_CUSTODIAN])
    body = validate.get_body()
    name = validate.req_str(body, "keyset_name", 3, 40)
    algorithm = validate.req_enum(body, "algorithm", enums.ALGORITHMS)
    start = validate.req_dt(body, "crypto_period_start")
    end = validate.req_dt(body, "crypto_period_end")
    validate.window_order(start, end, "crypto_period_start", "crypto_period_end")
    for existing in db.store.keysets.values():
        if existing["keyset_name"] == name:
            raise ApiError("ERR_DUPLICATE_TALKGROUP_ID", "keyset_name is already in use.")
    row = db.base_row({
        "keyset_name": name,
        "algorithm": algorithm,
        "crypto_period_start": start,
        "crypto_period_end": end,
        "status": "PENDING_APPROVAL",
        "created_by_user_id": actor.user_id,
        "approved_by_user_id": None,
        "loaded_unit_count": 0,
        "compromised_at": None,
    })
    db.store.keysets[row["id"]] = row
    return response.ok(serialize.keyset(row), 201)


@bp.get("/keysets")
def list_keysets():
    validate.authenticate(common.ANY_ROLE)
    filters = (
        ("status", validate.filter_enum("status", enums.KEYSET_STATUSES)),
        ("algorithm", validate.filter_enum("algorithm", enums.ALGORITHMS)),
    )
    return common.list_endpoint("keysets", serialize.keyset, filters)


@bp.get("/keysets/<keyset_id>")
def read_keyset(keyset_id):
    validate.authenticate(common.ANY_ROLE)
    keyset = validate.lookup("keysets", keyset_id)
    return response.ok(serialize.keyset(keyset))


@bp.post("/keysets/<keyset_id>/approval")
def keyset_approval(keyset_id):
    actor = validate.authenticate([SECURITY_OFFICER])
    keyset = validate.lookup("keysets", keyset_id)
    body = validate.get_body()
    decision = validate.req_enum(body, "decision", enums.KEYSET_DECISIONS)
    if keyset["created_by_user_id"] is not None and actor.user_id == keyset["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if keyset["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if decision == "REJECT":
        keyset["status"] = "REJECTED"
        db.touch(keyset)
        return response.ok(serialize.keyset(keyset))
    keyset["status"] = "ACTIVE"
    keyset["approved_by_user_id"] = actor.user_id
    db.touch(keyset)
    for other in db.sort_rows(list(db.store.keysets.values())):
        if other["id"] == keyset["id"]:
            continue
        if other["status"] != "ACTIVE" or other["algorithm"] != keyset["algorithm"]:
            continue
        if other["crypto_period_end"] <= keyset["crypto_period_start"]:
            compute.apply_fields(other, status="SUPERSEDED")
    return response.ok(serialize.keyset(keyset))


@bp.post("/keysets/<keyset_id>/compromise")
def keyset_compromise(keyset_id):
    validate.authenticate([SECURITY_OFFICER])
    keyset = validate.lookup("keysets", keyset_id)
    if keyset["status"] != "ACTIVE":
        raise ApiError("ERR_KEYSET_NOT_ACTIVE")
    keyset["status"] = "COMPROMISED"
    keyset["compromised_at"] = db.now()
    keyset["loaded_unit_count"] = 0
    db.touch(keyset)
    compute.compromise_cascade(keyset)
    return response.ok(serialize.keyset(keyset))
