"""The contractor network: licences, certifications and capacity."""

from flask import Blueprint

import config
import serializers
import timeutil
from errors import ApiError
from response import object_response, paginate
from store import create_record, ordered, store
from validation import Field, current_user_id, filter_enum, filter_value, parse_body, require_path_uuid, require_role

bp = Blueprint("contractors", __name__)

READ_ROLES = (
    config.ROLE_PLATFORM_ADMIN,
    config.ROLE_CUSTOMER_SERVICE_REP,
    config.ROLE_CLAIMS_ADJUSTER,
    config.ROLE_NETWORK_CONTRACTOR,
    config.ROLE_REGULATORY_AFFAIRS,
    config.ROLE_OPERATIONS_ADMIN,
)

CREATE_SPEC = {
    "name": Field("string", required=True, min_len=1, max_len=120),
    "state_code": Field("state_code", required=True),
    "license_number": Field("string", required=True, min_len=1, max_len=40),
    "license_expires_on": Field("date", required=True),
    "line_types_certified": Field(
        "enum_array", required=True, item_enum=config.LINE_TYPES, min_len=1, distinct=True
    ),
    "hourly_rate_cents": Field("integer", required=True, minimum=1000, maximum=40000),
    "sla_compliance_pct": Field("integer", required=True, minimum=0, maximum=100),
    "max_open_dispatches": Field("integer", required=True, minimum=1, maximum=50),
    "permit_pull_authorized": Field("boolean"),
}


def lookup_contractor(contractor_id):
    contractor = store.contractors.get(contractor_id)
    if contractor is None:
        raise ApiError("ERR_CONTRACTOR_NOT_FOUND", "No contractor with id %s" % contractor_id)
    return contractor


@bp.post("/contractors")
def create_contractor():
    current_user_id()
    require_role(config.ROLE_OPERATIONS_ADMIN, config.ROLE_PLATFORM_ADMIN)
    body = parse_body(CREATE_SPEC)
    record = create_record(
        store.contractors,
        {
            "name": body["name"],
            "state_code": body["state_code"],
            "license_number": body["license_number"],
            "license_expires_on": timeutil.render_date(body["license_expires_on"]),
            "line_types_certified": body["line_types_certified"],
            "hourly_rate_cents": body["hourly_rate_cents"],
            "sla_compliance_pct": body["sla_compliance_pct"],
            "max_open_dispatches": body["max_open_dispatches"],
            "permit_pull_authorized": False
            if body["permit_pull_authorized"] is None
            else body["permit_pull_authorized"],
            "status": "ACTIVE",
            "sla_breach_count": 0,
        },
    )
    return object_response(serializers.contractor(record), 201)


@bp.get("/contractors")
def list_contractors():
    current_user_id()
    require_role(*READ_ROLES)
    state_code = filter_value("state_code")
    status = filter_enum("status", config.CONTRACTOR_STATUSES)
    line_type = filter_enum("line_type", config.LINE_TYPES)

    def matches(contractor):
        if state_code is not None and contractor["state_code"] != state_code:
            return False
        if status is not None and contractor["status"] != status:
            return False
        # The line_type filter matches on membership of the certification array.
        if line_type is not None and line_type not in contractor["line_types_certified"]:
            return False
        return True

    return paginate(ordered(store.contractors, matches), serializers.contractor)


@bp.get("/contractors/<contractor_id>")
def get_contractor(contractor_id):
    current_user_id()
    require_role(*READ_ROLES)
    require_path_uuid(contractor_id)
    return object_response(serializers.contractor(lookup_contractor(contractor_id)))
