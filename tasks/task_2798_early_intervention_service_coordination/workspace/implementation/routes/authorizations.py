"""Provider authorizations: the funding instrument over the unit pool."""
from flask import Blueprint, request

import domain as D
from auth import STAFF_READ, endpoint
from envelope import paginate, single
from errors import fail
from helpers import (get_authorization, get_line, get_provider,
                     ser_authorization)
from services import cascades, compute
from store import db, flush, new_row, ordered, pd, set_field
from validate import Field, parse_body, v_date, v_enum, v_id, v_int

bp = Blueprint("authorizations", __name__)


@bp.route("/ei/provider-authorizations", methods=["POST"])
@endpoint(["ProgramAdmin"])
def create_authorization():
    payload = parse_body([
        Field("ifsp_service_id", v_id()),
        Field("provider_id", v_id()),
        Field("start_date", v_date()),
        Field("end_date", v_date()),
        Field("authorized_units", v_int(1, 4000)),
    ])
    line = get_line(payload["ifsp_service_id"])
    provider = get_provider(payload["provider_id"])
    plan = compute.ifsp_of_line(line)
    if plan is None or plan["status"] != "ACTIVE":
        fail("ERR_IFSP_STATE_INVALID",
             "Authorizations may only be written against an ACTIVE plan.")
    if provider["status"] != "ACTIVE":
        fail("ERR_PROVIDER_NOT_ACTIVE",
             "The provider is not in ACTIVE standing.")
    if line["status"] not in D.SERVICE_LIVE_STATUSES:
        fail("ERR_SERVICE_NOT_DELIVERABLE",
             "A service line in status '%s' accepts no new "
             "authorization." % line["status"])
    expiry = pd(provider["credential_expiry_date"])
    end = pd(payload["end_date"])
    if expiry is None or end is None or expiry < end:
        fail("ERR_PROVIDER_CREDENTIAL_EXPIRED",
             "The provider's credential lapses before the requested window "
             "ends.")
    if line["service_type"] not in (provider["qualified_service_types"] or []):
        fail("ERR_PROVIDER_SERVICE_TYPE_MISMATCH",
             "The provider is not credentialed for '%s'." % line["service_type"])
    start = pd(payload["start_date"])
    for other in compute.line_authorizations(line["id"]):
        if other["status"] not in D.AUTHORIZATION_COMMITTED:
            continue
        other_start = pd(other["start_date"])
        other_end = pd(other["end_date"])
        if start <= other_end and other_start <= end:
            fail("ERR_AUTHORIZATION_WINDOW_OVERLAP",
                 "The window collides with an existing authorization on this "
                 "service line.")
    if end < start:
        fail("ERR_INVALID_DATE_RANGE",
             "end_date must be on or after start_date.")
    if payload["authorized_units"] > (line["units_pool_remaining"] or 0):
        fail("ERR_UNITS_EXCEED_SERVICE_POOL",
             "Only %s units remain in the service line's "
             "pool." % (line["units_pool_remaining"] or 0))
    authorization = new_row({
        "ifsp_service_id": line["id"],
        "provider_id": provider["id"],
        "start_date": payload["start_date"],
        "end_date": payload["end_date"],
        "authorized_units": payload["authorized_units"],
        "unit_rate_cents": line["unit_rate_cents"],
        "units_consumed": 0,
        "units_released": 0,
        "units_remaining": payload["authorized_units"],
        "status": "ACTIVE",
        "revoked_date": None,
        "revocation_reason_code": None,
    })
    db.authorizations[authorization["id"]] = authorization
    if line["status"] == "PLANNED":
        set_field(line, "status", "AUTHORIZED")
    compute.recompute_line_pool(line)
    compute.recompute_provider_count(provider)
    flush()
    return single(ser_authorization(authorization), 201)


@bp.route("/ei/provider-authorizations/<authorization_id>", methods=["GET"])
@endpoint(STAFF_READ)
def read_authorization(authorization_id):
    return single(ser_authorization(get_authorization(authorization_id)))


@bp.route("/ei/provider-authorizations", methods=["GET"])
@endpoint(STAFF_READ)
def list_authorizations():
    rows = ordered(db.authorizations)
    ifsp_service_id = request.args.get("ifsp_service_id")
    provider_id = request.args.get("provider_id")
    status = request.args.get("status")
    if ifsp_service_id is not None:
        rows = [r for r in rows if r["ifsp_service_id"] == ifsp_service_id]
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser_authorization)


@bp.route("/ei/provider-authorizations/<authorization_id>/revoke",
          methods=["POST"])
@endpoint(["ProgramAdmin"])
def revoke_authorization(authorization_id):
    payload = parse_body([
        Field("revocation_reason_code", v_enum(D.REVOCATION_REASONS)),
    ])
    authorization = get_authorization(authorization_id)
    if authorization["status"] not in D.AUTHORIZATION_REVOCABLE:
        fail("ERR_AUTHORIZATION_NOT_ACTIVE",
             "An authorization in status '%s' is not "
             "revocable." % authorization["status"])
    cascades.release_authorization(authorization,
                                   payload["revocation_reason_code"],
                                   "CANCELLED_PROGRAM")
    line = compute.line_of_auth(authorization)
    compute.recompute_line_pool(line)
    compute.recompute_makeup(line)
    referral = compute.referral_of_line(line) if line else None
    if referral is not None:
        compute.recompute_service_gap(referral)
    flush()
    return single(ser_authorization(authorization))
