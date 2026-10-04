"""DoNotPayRecord endpoints (PRD §2.11, §3.9): listing with the closed-interval
overlap rule plus the flag/hold cascade, and removal with the release cascade."""
from flask import Blueprint

from constants import DNP_SOURCES, ROLE_TREASURY_OPERATOR, ROLE_TREASURY_SUPERVISOR
from db import STORE, new_entity, touch
from errors import (
    err_dnp_window_overlap,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
)
from middleware import authenticate, get_body, require_roles, spec_field, validate_body
from response import ok
from serializers import serialize_dnp_record
from services.cascades import dnp_create_cascade, dnp_remove_cascade, dnp_window_overlap
from util import gen_id

bp = Blueprint("dnp", __name__)


@bp.post("/do-not-pay-records")
def create_dnp_record():
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_OPERATOR)
    data = validate_body(get_body(), [
        spec_field("tin", "str", required=True),
        spec_field("list_source", "enum", required=True, enum=DNP_SOURCES),
        spec_field("effective_from", "dt", required=True),
        spec_field("effective_until", "dt", required=True),
    ])
    # Closed interval: effective_until must be on or after effective_from.
    if data["effective_until"] < data["effective_from"]:
        raise err_invalid_request("effective_until must be on or after effective_from")
    if dnp_window_overlap(
        data["tin"], data["list_source"], data["effective_from"], data["effective_until"]
    ):
        raise err_dnp_window_overlap()

    ent = new_entity()
    ent["id"] = gen_id()
    ent.update({
        "tin": data["tin"],
        "list_source": data["list_source"],
        "effective_from": data["effective_from"],
        "effective_until": data["effective_until"],
        "status": "ACTIVE",
    })
    STORE["dnp_records"][ent["id"]] = ent
    # Flag/hold cascade across the pre-execution payment population.
    dnp_create_cascade(ent["tin"])
    return ok(serialize_dnp_record(ent), 201)


@bp.post("/do-not-pay-records/<string:doNotPayRecordId>/remove")
def remove_dnp_record(doNotPayRecordId):
    """ACTIVE -> REMOVED; HELD payments with no remaining matching ACTIVE
    record at the current clock release to VERIFIED/CLEAR."""
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_SUPERVISOR)
    validate_body(get_body(), [])
    record = STORE["dnp_records"].get(doNotPayRecordId)
    if record is None:
        raise err_not_found("Do-not-pay record not found")
    if record["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE record can be removed")
    record["status"] = "REMOVED"
    touch(record)
    dnp_remove_cascade(record["tin"])
    return ok(serialize_dnp_record(record))
