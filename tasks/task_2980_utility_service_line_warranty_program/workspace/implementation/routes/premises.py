"""Premises: the partner's marketing file of service addresses."""

from flask import Blueprint

import config
import derive
import serializers
import timeutil
from errors import ApiError
from response import object_response, paginate
from routes.partners import READ_ROLES, lookup_partner
from store import create_record, ordered, store
from validation import (
    Field,
    current_user_id,
    filter_bool,
    filter_value,
    parse_body,
    require_path_uuid,
    require_role,
)

bp = Blueprint("premises", __name__)

SINGLE_READ_ROLES = READ_ROLES + (config.ROLE_POLICYHOLDER,)

CREATE_SPEC = {
    "partner_id": Field("uuid", required=True),
    "street_address": Field("string", required=True, min_len=1, max_len=200),
    "state_code": Field("state_code", required=True),
    "owned_segments": Field("enum_array", required=True, item_enum=config.OWNED_SEGMENTS, min_len=1, distinct=True),
    "do_not_mail": Field("boolean"),
    "address_status": Field("enum", enum=config.ADDRESS_STATUSES),
    "known_defect_reported_at": Field("instant"),
}


def lookup_premises(premises_id):
    record = store.premises.get(premises_id)
    if record is None:
        raise ApiError("ERR_PREMISES_NOT_FOUND", "No premises with id %s" % premises_id)
    return record


@bp.post("/premises")
def create_premises():
    current_user_id()
    require_role(config.ROLE_MARKETING_OPS, config.ROLE_PLATFORM_ADMIN)
    body = parse_body(CREATE_SPEC)
    partner = lookup_partner(body["partner_id"])
    for existing in store.premises.values():
        if existing["partner_id"] == partner["id"] and existing["street_address"] == body["street_address"]:
            raise ApiError("ERR_INVALID_REQUEST", "street_address must be unique within the partner's file")
    record = create_record(
        store.premises,
        {
            "partner_id": partner["id"],
            "street_address": body["street_address"],
            "state_code": body["state_code"],
            "owned_segments": body["owned_segments"],
            "do_not_mail": False if body["do_not_mail"] is None else body["do_not_mail"],
            "address_status": "GOOD" if body["address_status"] is None else body["address_status"],
            "known_defect_reported_at": timeutil.render_instant(body["known_defect_reported_at"]),
            "regulator_hold": False,
            "last_mail_decision": "NOT_EVALUATED",
            "last_mail_suppression_reason": None,
            "last_mailed_campaign_id": None,
            "_mail_history": [],
        },
    )
    return object_response(serializers.premises(record), 201)


@bp.get("/premises")
def list_premises():
    current_user_id()
    require_role(*READ_ROLES)
    partner_id = filter_value("partner_id")
    campaign_id = filter_value("last_mailed_campaign_id")
    suppressed = filter_bool("suppressed")

    def matches(record):
        if partner_id is not None and record["partner_id"] != partner_id:
            return False
        if campaign_id is not None and record["last_mailed_campaign_id"] != campaign_id:
            return False
        if suppressed is not None:
            is_suppressed = derive.premises_suppression_reason(record) != "NONE"
            if is_suppressed != suppressed:
                return False
        return True

    return paginate(ordered(store.premises, matches), serializers.premises)


@bp.get("/premises/<premises_id>")
def get_premises(premises_id):
    current_user_id()
    require_role(*SINGLE_READ_ROLES)
    require_path_uuid(premises_id)
    return object_response(serializers.premises(lookup_premises(premises_id)))
