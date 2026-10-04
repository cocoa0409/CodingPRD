"""DisseminationRecord read endpoints (PRD §3.6)."""
from flask import Blueprint, request

from auth import authenticate, require_role
from db import STORE
from errors import api_error
from serialize import serialize
from util import envelope, list_response

bp = Blueprint("records", __name__, url_prefix="/alerts")

ANY_ROLE = ["PlatformAdmin", "Forecaster", "MeteorologistInCharge", "VerificationAnalyst", "EmergencyManager"]


def get_record_or_404(record_id):
    record = STORE["records"].get(record_id)
    if record is None:
        raise api_error(
            "ERR_DISSEMINATION_RECORD_NOT_FOUND", "DisseminationRecord %s does not exist." % record_id
        )
    return record


@bp.get("/dissemination-records/<record_id>")
def get_record(record_id):
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    return envelope(serialize(get_record_or_404(record_id)), "object", 200)


@bp.get("/dissemination-records")
def list_records():
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    rows = list(STORE["records"].values())
    for field in ("product_id", "channel_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return list_response(rows, serialize)
