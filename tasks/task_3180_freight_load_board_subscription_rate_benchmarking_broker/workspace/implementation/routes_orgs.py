from flask import Blueprint, request

from db import db
from middleware import get_context, require_role
from response import APIError, success
from services import (
    apply_eager_clock_transitions,
    check_org_active,
    find_active_subscription,
    get_broker,
    get_carrier,
    new_resource,
    paginate,
    parse_limit_offset,
    recompute_broker_credit,
    recompute_contribution_flag,
    sorted_by_created,
    suspend_broker,
    suspend_carrier,
    touch,
)
from util import iso_ms, parse_dt

bp = Blueprint("orgs", __name__)

READ_ROLES = ("PlatformAdmin", "ComplianceAnalyst", "DataOps", "BrokerAdmin", "CarrierAdmin")


def broker_view(org):
    recompute_broker_credit(db, org)
    recompute_contribution_flag(db, org, is_broker=True)
    return org


def carrier_view(org):
    recompute_contribution_flag(db, org, is_broker=False)
    return org


@bp.post("/_clock/set_current_utc")
def set_clock():
    user_id, role = get_context()
    require_role(role, ("PlatformAdmin",))
    body = request.get_json(silent=True) or {}
    to = parse_dt(body.get("to_iso8601"))
    if to is None:
        raise APIError("ERR_INVALID_REQUEST", 400, "to_iso8601 must be a valid ISO 8601 datetime")
    db.clock = to
    apply_eager_clock_transitions(db)
    return success({"current_utc": iso_ms(db.clock)})


@bp.post("/broker-orgs")
def create_broker():
    get_context_role = get_context()
    require_role(get_context_role[1], ("PlatformAdmin",))
    body = request.get_json(silent=True) or {}
    legal_name = body.get("legal_name")
    mc_number = body.get("mc_number")
    if not legal_name or not mc_number or not isinstance(mc_number, str):
        raise APIError("ERR_INVALID_REQUEST", 400, "legal_name and mc_number are required")
    for o in db.broker_orgs.values():
        if o["mc_number"] == mc_number:
            raise APIError("ERR_DUPLICATE_MC_NUMBER", 409, "mc_number already registered")
    org = new_resource(db, {
        "legal_name": legal_name,
        "mc_number": mc_number,
        "status": "ACTIVE",
        "credit_score": 70,
        "credit_badge": "STANDARD",
        "days_to_pay_simple": None,
        "days_to_pay_weighted": None,
        "credit_event_count": 0,
        "included_amount_cents": 0,
        "under_dispute_amount_cents": 0,
        "removed_amount_cents": 0,
        "data_contribution_flag": False,
    })
    db.broker_orgs[org["id"]] = org
    return success(org, 201)


@bp.get("/broker-orgs")
def list_brokers():
    _, role = get_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_limit_offset()
    status = request.args.get("status")
    items = [broker_view(o) for o in db.broker_orgs.values()]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, 200, meta)


@bp.get("/broker-orgs/<org_id>")
def get_broker_route(org_id):
    _, role = get_context()
    require_role(role, READ_ROLES)
    return success(broker_view(get_broker(db, org_id)))


@bp.post("/broker-orgs/<org_id>/suspend")
def suspend_broker_route(org_id):
    _, role = get_context()
    require_role(role, ("PlatformAdmin",))
    org = get_broker(db, org_id)
    if org["status"] != "ACTIVE":
        raise APIError("ERR_ORG_NOT_ACTIVE", 409, "Broker org is not ACTIVE")
    suspend_broker(db, org)
    return success(broker_view(org))


@bp.post("/broker-orgs/<org_id>/reinstate")
def reinstate_broker(org_id):
    _, role = get_context()
    require_role(role, ("PlatformAdmin",))
    org = get_broker(db, org_id)
    if org["status"] != "SUSPENDED":
        raise APIError("ERR_ORG_NOT_ACTIVE", 409, "Broker org is not SUSPENDED")
    for a in db.fraud_alerts.values():
        if a["status"] == "CONFIRMED" and a.get("target_broker_org_id") == org["id"]:
            raise APIError("ERR_ORG_HAS_CONFIRMED_FRAUD", 409, "A CONFIRMED fraud alert targets this broker")
    org["status"] = "ACTIVE"
    touch(db, org)
    for load in db.load_posts.values():
        if load["broker_org_id"] == org["id"] and load["visibility"] == "DELISTED" and load["status"] == "BOOKED":
            load["visibility"] = "LISTED"
            touch(db, load)
    sub = find_active_subscription(db, broker_org_id=org["id"])
    if sub is not None and sub["status"] == "SUSPENDED":
        sub["status"] = "ACTIVE"
        touch(db, sub)
    return success(broker_view(org))


@bp.post("/broker-orgs/<org_id>/deactivate")
def deactivate_broker(org_id):
    _, role = get_context()
    require_role(role, ("PlatformAdmin",))
    org = get_broker(db, org_id)
    if org["status"] not in ("ACTIVE", "SUSPENDED"):
        raise APIError("ERR_ORG_NOT_ACTIVE", 409, "Broker org cannot be deactivated from its current state")
    org["status"] = "DEACTIVATED"
    touch(db, org)
    return success(broker_view(org))


@bp.post("/carrier-orgs")
def create_carrier():
    _, role = get_context()
    require_role(role, ("PlatformAdmin",))
    body = request.get_json(silent=True) or {}
    legal_name = body.get("legal_name")
    dot_number = body.get("dot_number")
    if not legal_name or not dot_number or not isinstance(dot_number, str):
        raise APIError("ERR_INVALID_REQUEST", 400, "legal_name and dot_number are required")
    for o in db.carrier_orgs.values():
        if o["dot_number"] == dot_number:
            raise APIError("ERR_DUPLICATE_DOT_NUMBER", 409, "dot_number already registered")
    org = new_resource(db, {
        "legal_name": legal_name,
        "dot_number": dot_number,
        "status": "ACTIVE",
        "data_contribution_flag": False,
    })
    db.carrier_orgs[org["id"]] = org
    return success(org, 201)


@bp.get("/carrier-orgs")
def list_carriers():
    _, role = get_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_limit_offset()
    status = request.args.get("status")
    items = [carrier_view(o) for o in db.carrier_orgs.values()]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, 200, meta)


@bp.get("/carrier-orgs/<org_id>")
def get_carrier_route(org_id):
    _, role = get_context()
    require_role(role, READ_ROLES)
    return success(carrier_view(get_carrier(db, org_id)))


@bp.post("/carrier-orgs/<org_id>/suspend")
def suspend_carrier_route(org_id):
    _, role = get_context()
    require_role(role, ("PlatformAdmin",))
    org = get_carrier(db, org_id)
    if org["status"] != "ACTIVE":
        raise APIError("ERR_ORG_NOT_ACTIVE", 409, "Carrier org is not ACTIVE")
    suspend_carrier(db, org)
    return success(carrier_view(org))


@bp.post("/carrier-orgs/<org_id>/reinstate")
def reinstate_carrier(org_id):
    _, role = get_context()
    require_role(role, ("PlatformAdmin",))
    org = get_carrier(db, org_id)
    if org["status"] != "SUSPENDED":
        raise APIError("ERR_ORG_NOT_ACTIVE", 409, "Carrier org is not SUSPENDED")
    for a in db.fraud_alerts.values():
        if a["status"] == "CONFIRMED" and a.get("target_carrier_org_id") == org["id"]:
            raise APIError("ERR_ORG_HAS_CONFIRMED_FRAUD", 409, "A CONFIRMED fraud alert targets this carrier")
    org["status"] = "ACTIVE"
    touch(db, org)
    sub = find_active_subscription(db, carrier_org_id=org["id"])
    if sub is not None and sub["status"] == "SUSPENDED":
        sub["status"] = "ACTIVE"
        touch(db, sub)
    return success(carrier_view(org))


@bp.post("/carrier-orgs/<org_id>/deactivate")
def deactivate_carrier(org_id):
    _, role = get_context()
    require_role(role, ("PlatformAdmin",))
    org = get_carrier(db, org_id)
    if org["status"] not in ("ACTIVE", "SUSPENDED"):
        raise APIError("ERR_ORG_NOT_ACTIVE", 409, "Carrier org cannot be deactivated from its current state")
    org["status"] = "DEACTIVATED"
    touch(db, org)
    return success(carrier_view(org))
