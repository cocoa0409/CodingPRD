"""Provider network registration and standing."""
from flask import Blueprint

import domain as D
from auth import STAFF_READ, endpoint
from envelope import single
from errors import fail
from helpers import get_provider, not_future, ser_provider
from services import cascades
from store import db, flush, new_row, set_fields
from validate import Field, parse_body, v_date, v_enum, v_list, v_str

bp = Blueprint("providers", __name__)


@bp.route("/ei/providers", methods=["POST"])
@endpoint(["ProgramAdmin"])
def create_provider():
    payload = parse_body([
        Field("agency_name", v_str()),
        Field("qualified_service_types",
              v_list(v_enum(D.SERVICE_TYPES), min_items=1)),
        Field("credential_expiry_date", v_date()),
    ])
    provider = new_row({
        "agency_name": payload["agency_name"],
        "qualified_service_types": payload["qualified_service_types"],
        "credential_expiry_date": payload["credential_expiry_date"],
        "status": "ACTIVE",
        "suspension_reason_code": None,
        "suspended_date": None,
        "active_authorization_count": 0,
    })
    db.providers[provider["id"]] = provider
    flush()
    return single(ser_provider(provider), 201)


@bp.route("/ei/providers/<provider_id>", methods=["GET"])
@endpoint(STAFF_READ)
def read_provider(provider_id):
    return single(ser_provider(get_provider(provider_id)))


@bp.route("/ei/providers/<provider_id>/suspend", methods=["POST"])
@endpoint(["ProgramAdmin"])
def suspend_provider(provider_id):
    payload = parse_body([
        Field("suspension_reason_code", v_enum(D.SUSPENSION_REASONS)),
        Field("effective_date", v_date()),
    ])
    provider = get_provider(provider_id)
    if provider["status"] != "ACTIVE":
        fail("ERR_PROVIDER_NOT_ACTIVE",
             "Only a provider in ACTIVE standing may leave it.")
    not_future(payload["effective_date"], "effective_date")
    terminated = payload["suspension_reason_code"] == "CONTRACT_ENDED"
    set_fields(provider, {
        "status": "TERMINATED" if terminated else "SUSPENDED",
        "suspension_reason_code": payload["suspension_reason_code"],
        "suspended_date": payload["effective_date"],
    })
    cascades.provider_cascade(provider, terminated)
    flush()
    return single(ser_provider(provider))
