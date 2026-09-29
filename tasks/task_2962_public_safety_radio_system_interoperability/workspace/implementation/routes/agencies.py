"""Member agency registry, console configuration, fees and governance."""
from datetime import timedelta

from flask import Blueprint

import common
import compute
import db
import enums
import response
import serialize
import validate
from errors import ApiError
from validate import AGENCY_RADIO_MANAGER, SYSTEM_ADMIN

bp = Blueprint("agencies", __name__, url_prefix=common.PREFIX)


@bp.post("/agencies")
def create_agency():
    validate.authenticate([SYSTEM_ADMIN])
    body = validate.get_body()
    name = validate.req_str(body, "name", 1, 120)
    agency_code = validate.req_str(body, "agency_code", 4, 6, r"^[A-Z0-9]+$")
    agency_type = validate.req_enum(body, "agency_type", enums.AGENCY_TYPES)
    fee_basis = validate.opt_enum(body, "fee_basis", enums.FEE_BASES, "SNAPSHOT")
    privilege = validate.opt_enum(body, "interop_privilege", enums.INTEROP_PRIVILEGES, "MONITOR")
    consoles = validate.opt_int(body, "console_position_count", 1, 40, 1)
    retention = validate.opt_int(body, "recorder_retention_days", 1, 3650, 90)
    for existing in db.store.agencies.values():
        if existing["agency_code"] == agency_code:
            raise ApiError("ERR_DUPLICATE_TALKGROUP_ID", "agency_code is already registered.")
    row = db.base_row({
        "name": name,
        "agency_code": agency_code,
        "agency_type": agency_type,
        "fee_basis": fee_basis,
        "interop_privilege": privilege,
        "console_position_count": consoles,
        "recorder_retention_days": retention,
        "billing_status": "CURRENT",
        "billable_subscriber_count": 0,
        "last_assessed_fee_cents": 0,
        "fee_balance_cents": 0,
        "lifetime_assessed_cents": 0,
        "lifetime_paid_cents": 0,
        "last_assessment_period_start": None,
        "last_assessment_period_end": None,
        "payment_due_at": None,
        "governance_vote_weight": 1,
        "voting_eligible": True,
        "active_patch_request_count": 0,
    })
    db.store.agencies[row["id"]] = row
    return response.ok(serialize.agency(row), 201)


@bp.get("/agencies")
def list_agencies():
    validate.authenticate(common.ANY_ROLE)
    filters = (
        ("agency_type", validate.filter_enum("agency_type", enums.AGENCY_TYPES)),
        ("billing_status", validate.filter_enum("billing_status", enums.BILLING_STATUSES)),
        ("interop_privilege", validate.filter_enum("interop_privilege", enums.INTEROP_PRIVILEGES)),
    )
    return common.list_endpoint("agencies", serialize.agency, filters)


@bp.get("/agencies/<agency_id>")
def read_agency(agency_id):
    validate.authenticate(common.ANY_ROLE)
    agency = validate.lookup("agencies", agency_id)
    return response.ok(serialize.agency(agency))


@bp.patch("/agencies/<agency_id>/console-config")
def console_config(agency_id):
    actor = validate.authenticate([AGENCY_RADIO_MANAGER])
    agency = validate.lookup("agencies", agency_id)
    body = validate.get_body(required=False)
    consoles = validate.opt_int(body, "console_position_count", 1, 40)
    retention = validate.opt_int(body, "recorder_retention_days", 1, 3650)
    common.require_scope(actor, agency["id"])
    if retention is not None and retention < compute.retention_floor(agency):
        raise ApiError("ERR_RECORDER_RETENTION_BELOW_MINIMUM")
    if consoles is not None:
        agency["console_position_count"] = consoles
    if retention is not None:
        agency["recorder_retention_days"] = retention
    db.touch(agency)
    return response.ok(serialize.agency(agency))


@bp.post("/agencies/<agency_id>/fee-assessments")
def fee_assessment(agency_id):
    validate.authenticate([SYSTEM_ADMIN])
    agency = validate.lookup("agencies", agency_id)
    body = validate.get_body()
    period_start = validate.req_dt(body, "period_start")
    period_end = validate.req_dt(body, "period_end")
    common.check_occ(agency, "expected_agency_version", body)
    if period_end <= period_start:
        raise ApiError("ERR_FEE_PERIOD_INVALID", "period_end must be strictly after period_start.")
    if (period_end - period_start) > timedelta(days=compute.MAX_FEE_PERIOD_DAYS):
        raise ApiError("ERR_FEE_PERIOD_INVALID", "The billing period is longer than 366 days.")
    if period_end > db.now():
        raise ApiError("ERR_FEE_PERIOD_INVALID", "period_end may not lie in the future.")
    total = compute.agency_fee_assessment(agency, period_start, period_end)
    agency["last_assessed_fee_cents"] = total
    agency["lifetime_assessed_cents"] = agency["lifetime_assessed_cents"] + total
    agency["fee_balance_cents"] = agency["lifetime_assessed_cents"] - agency["lifetime_paid_cents"]
    agency["last_assessment_period_start"] = period_start
    agency["last_assessment_period_end"] = period_end
    agency["payment_due_at"] = period_end + timedelta(days=compute.PAYMENT_GRACE_DAYS)
    db.touch(agency)
    compute.recompute_billing_status(agency)
    return response.ok(serialize.agency(agency))


@bp.post("/agencies/<agency_id>/payments")
def record_payment(agency_id):
    actor = validate.authenticate([AGENCY_RADIO_MANAGER, SYSTEM_ADMIN])
    agency = validate.lookup("agencies", agency_id)
    body = validate.get_body()
    amount = validate.req_int(body, "amount_cents")
    common.require_scope(actor, agency["id"])
    if amount < 1 or amount > agency["fee_balance_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")
    agency["lifetime_paid_cents"] = agency["lifetime_paid_cents"] + amount
    agency["fee_balance_cents"] = agency["lifetime_assessed_cents"] - agency["lifetime_paid_cents"]
    db.touch(agency)
    compute.recompute_billing_status(agency)
    return response.ok(serialize.agency(agency))


@bp.get("/agencies/<agency_id>/governance-standing")
def governance_standing(agency_id):
    validate.authenticate(common.ANY_ROLE)
    agency = validate.lookup("agencies", agency_id)
    return response.ok(compute.governance_standing(agency))
