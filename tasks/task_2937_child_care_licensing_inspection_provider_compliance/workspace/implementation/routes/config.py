"""Logical clock, the checklist catalog and the inspector roll (PRD §2.4, §3.1)."""

from flask import Blueprint, request

import clock
import constants as K
import envelope
import helpers
import serialize
import store
import validate
from auth import authenticate
from errors import ApiError
from validate import F

bp = Blueprint("config", __name__)

CHECKLIST_READERS = (
    "AgencyAdmin",
    "LicensingInspector",
    "LicensingSupervisor",
    "ComplaintInvestigator",
    "PublicPortalReader",
)
INSPECTOR_READERS = (
    "AgencyAdmin",
    "LicensingSupervisor",
    "LicensingInspector",
    "ComplaintInvestigator",
)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(("AgencyAdmin",))
    vals = validate.body([F("to_iso8601", "instant", required=True)])
    current = clock.set_clock(clock.parse_instant(vals["to_iso8601"]))
    return envelope.ok({"current_utc": current})


CHECKLIST_INPUT = [
    F("code", "string", required=True, pattern=K.CODE_PATTERN),
    F("title", "string", required=True, min_len=1, max_len=160, not_blank=True),
    F("category", "enum", required=True, values=K.CHECKLIST_CATEGORIES),
    F("default_severity", "enum", required=True, values=K.SEVERITIES),
    F(
        "age_groups_applicable",
        "enum_array",
        required=True,
        values=K.AGE_GROUPS,
        non_empty=True,
        unique=True,
    ),
    F("infant_sensitive", "bool"),
]


@bp.post("/licensing/checklist-items")
def create_checklist_item():
    authenticate(("AgencyAdmin",))
    vals = validate.body(CHECKLIST_INPUT)
    if store.checklist_by_code(vals["code"]) is not None:
        raise ApiError("ERR_INVALID_REQUEST", "Checklist code already registered.")
    record = {
        "code": vals["code"],
        "title": vals["title"],
        "category": vals["category"],
        "default_severity": vals["default_severity"],
        "age_groups_applicable": list(vals["age_groups_applicable"]),
        "infant_sensitive": bool(vals.get("infant_sensitive", False)),
    }
    store.create(store.checklist_items, record, versioned=False)
    return envelope.created(serialize.checklist_item(record))


@bp.get("/licensing/checklist-items")
def list_checklist_items():
    authenticate(CHECKLIST_READERS)
    limit, offset = envelope.pagination(request.args)
    category = validate.query_enum("category", K.CHECKLIST_CATEGORIES)
    severity = validate.query_enum("default_severity", K.SEVERITIES)
    code = validate.query_str("code")
    rows = store.ordered(store.checklist_items)
    if code is not None:
        rows = [r for r in rows if r["code"] == code]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if severity is not None:
        rows = [r for r in rows if r["default_severity"] == severity]
    return helpers.listing(rows, serialize.checklist_item, limit, offset)


@bp.get("/licensing/checklist-items/<checklist_item_id>")
def read_checklist_item(checklist_item_id):
    authenticate(CHECKLIST_READERS)
    record = helpers.need("checklist_item", checklist_item_id)
    return envelope.ok(serialize.checklist_item(record))


INSPECTOR_INPUT = [
    F("full_name", "string", required=True, min_len=1, max_len=120, not_blank=True),
    F("county_code", "string", required=True, pattern=K.COUNTY_PATTERN),
    F(
        "certified_age_groups",
        "enum_array",
        required=True,
        values=K.AGE_GROUPS,
        non_empty=True,
        unique=True,
    ),
    F("max_daily_visits", "int", min_val=1, max_val=8),
]


@bp.post("/licensing/inspectors")
def create_inspector():
    authenticate(("AgencyAdmin",))
    vals = validate.body(INSPECTOR_INPUT)
    record = {
        "full_name": vals["full_name"],
        "county_code": vals["county_code"],
        "certified_age_groups": list(vals["certified_age_groups"]),
        "max_daily_visits": vals.get("max_daily_visits", 3),
        "status": "ACTIVE",
        "scheduled_visit_count": 0,
    }
    store.create(store.inspectors, record)
    return envelope.created(serialize.inspector(record))


@bp.get("/licensing/inspectors")
def list_inspectors():
    authenticate(("AgencyAdmin", "LicensingSupervisor"))
    limit, offset = envelope.pagination(request.args)
    status = validate.query_enum("status", K.INSPECTOR_STATUSES)
    county = validate.query_str("county_code")
    rows = store.ordered(store.inspectors)
    if county is not None:
        rows = [r for r in rows if r["county_code"] == county]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return helpers.listing(rows, serialize.inspector, limit, offset)


@bp.get("/licensing/inspectors/<inspector_id>")
def read_inspector(inspector_id):
    authenticate(INSPECTOR_READERS)
    record = helpers.need("inspector", inspector_id)
    return envelope.ok(serialize.inspector(record))


@bp.post("/licensing/inspectors/<inspector_id>/leave-status")
def set_leave_status(inspector_id):
    authenticate(("AgencyAdmin",))
    vals = validate.body([F("status", "enum", required=True, values=K.INSPECTOR_STATUSES)])
    record = helpers.need("inspector", inspector_id)
    record["status"] = vals["status"]
    store.touch(record)
    return envelope.ok(serialize.inspector(record))
