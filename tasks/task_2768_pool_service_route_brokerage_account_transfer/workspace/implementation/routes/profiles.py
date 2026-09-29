"""State licensing regimes (PRD section 3.1)."""

import re

from flask import Blueprint, request

from auth import begin
from calc import PERMIT_TYPES
from errors import ApiError
from responses import list_response, object_response, pagination
from serializers import profile_json
from services import get_profile, profile_for_state
from store import new_record, ordered, store
from validators import (bad, body, path_uuid, req_bool, req_int, req_str, req_str_array)

bp = Blueprint("profiles", __name__)

STATE_CODE_RE = r"^[A-Z]{2}$"


@bp.post("/state-license-profiles")
def create_profile():
    begin("PlatformAdmin")
    data = body()
    state_code = req_str(data, "state_code", min_len=2, max_len=2)
    if not re.match(STATE_CODE_RE, state_code):
        bad("Field 'state_code' must be exactly two uppercase letters.")
    permits = req_str_array(data, "required_permit_types", min_items=1,
                           allowed=PERMIT_TYPES, unique=True)
    reciprocity = req_str_array(data, "reciprocity_states", item_pattern=STATE_CODE_RE)
    processing_days = req_int(data, "transfer_processing_days", minimum=1, maximum=180)
    cooling_off = req_int(data, "cooling_off_days", minimum=0, maximum=180)
    provisional = req_bool(data, "provisional_operation_allowed")

    if profile_for_state(state_code) is not None:
        raise ApiError("ERR_DUPLICATE_STATE_PROFILE",
                       "A licensing profile already exists for state %s." % state_code)

    record = new_record()
    record.update({"state_code": state_code, "required_permit_types": permits,
                   "reciprocity_states": reciprocity,
                   "transfer_processing_days": processing_days,
                   "cooling_off_days": cooling_off,
                   "provisional_operation_allowed": provisional})
    store.state_license_profiles[record["id"]] = record
    return object_response(profile_json(record), 201)


@bp.get("/state-license-profiles/<identifier>")
def read_profile(identifier):
    begin("PlatformAdmin", "Broker", "Seller", "Buyer")
    path_uuid(identifier)
    return object_response(profile_json(get_profile(identifier)))


@bp.get("/state-license-profiles")
def list_profiles():
    begin("PlatformAdmin", "Broker", "Seller", "Buyer")
    limit, offset = pagination()
    state_code = request.args.get("state_code")
    rows = ordered(store.state_license_profiles,
                   lambda r: state_code is None or r["state_code"] == state_code)
    return list_response(rows, profile_json, limit, offset)
