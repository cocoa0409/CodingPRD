"""Service request endpoints: create, read, list, dispatch, resolve, loaner (PRD 3.5)."""
import uuid
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db as dbmod
import domain as D
from errors import ApiError
from middleware import authenticate, forbid, get_body
from response import paginate, success
from util import is_int, is_num, parse_dt, round_half_up

bp = Blueprint("service_requests", __name__)

_READ_ROLES = {
    "AccountManager",
    "LabProcurement",
    "ServiceDispatcher",
    "FieldEngineer",
    "PlatformAdmin",
}


def _request_account_id(req):
    inst = dbmod.store.instruments[req["instrument_id"]]
    return inst["account_id"]


@bp.post("/lab/service-requests")
def create_service_request():
    uid, role = authenticate({"LabProcurement", "AccountManager", "PlatformAdmin"})
    body = get_body()
    instrument_id = body.get("instrument_id")
    if not isinstance(instrument_id, str) or not instrument_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "instrument_id is required")
    inst = dbmod.store.instruments.get(instrument_id)
    if inst is None:
        raise ApiError("ERR_INSTRUMENT_NOT_FOUND", 404, "Instrument not found")
    if role == "LabProcurement" and inst["account_id"] != uid:
        forbid("LabProcurement may act only on its own account's instruments")
    if inst["placement_status"] != "INSTALLED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Instrument is not INSTALLED"
        )
    acct = dbmod.store.accounts[inst["account_id"]]
    if acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "Account is not ACTIVE")
    rtype = body.get("request_type")
    if rtype not in D.REQUEST_TYPES:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "request_type must be one of BREAK_FIX, PREVENTIVE_MAINTENANCE, APP_SUPPORT, METHOD_DEV",
        )
    severity = body.get("severity")
    if severity not in D.SEVERITIES:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "severity must be one of LOW, MEDIUM, HIGH, CRITICAL",
        )
    scheduled = None
    if rtype == "PREVENTIVE_MAINTENANCE":
        scheduled = parse_dt(body.get("scheduled_for"))
        if scheduled is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400,
                "scheduled_for is required for PREVENTIVE_MAINTENANCE",
            )
        contract = D.live_contract_for_instrument(instrument_id)
        if contract is None:
            raise ApiError(
                "ERR_CONTRACT_REQUIRED", 422,
                "PREVENTIVE_MAINTENANCE requires an ACTIVE or RENEWAL_DUE contract",
            )
        gap = timedelta(days=D.PM_MIN_GAP_DAYS)
        for r in dbmod.store.service_requests.values():
            if (
                r["instrument_id"] == instrument_id
                and r["request_type"] == "PREVENTIVE_MAINTENANCE"
                and r["status"] in ("OPEN", "DISPATCHED")
                and r["scheduled_for"] is not None
            ):
                if abs((scheduled - r["scheduled_for"]).total_seconds()) < gap.total_seconds():
                    raise ApiError(
                        "ERR_PM_GAP_VIOLATION", 422,
                        "Preventive-maintenance visits must be at least 30 days apart",
                    )
    now = dbmod.now()
    contract = D.live_contract_for_instrument(instrument_id)
    response_hours = (
        D.TIER_RESPONSE_HOURS[contract["tier"]] if contract else D.DEFAULT_RESPONSE_HOURS
    )
    req = {
        "id": str(uuid.uuid4()),
        "instrument_id": instrument_id,
        "engineer_id": None,
        "loaner_unit_id": None,
        "request_type": rtype,
        "severity": severity,
        "scheduled_for": scheduled,
        "status": "OPEN",
        "opened_at": now,
        "response_deadline": now + timedelta(hours=response_hours),
        "resolved_at": None,
        "sla_breached": False,
        "hours_on_site": None,
        "parts_cost_cents": 0,
        "billable_cents": 0,
        "covered_cents": 0,
        "credit_memo_cents": 0,
        "dispatched_day": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": dbmod.store.next_seq(),
    }
    with dbmod.store.lock:
        dbmod.store.service_requests[req["id"]] = req
    return success(D.service_request_json(req), code=201)


@bp.get("/lab/service-requests/<request_id>")
def get_service_request(request_id):
    uid, role = authenticate(_READ_ROLES)
    req = dbmod.store.service_requests.get(request_id)
    if req is None:
        raise ApiError("ERR_SERVICE_REQUEST_NOT_FOUND", 404, "Service request not found")
    if role == "LabProcurement" and _request_account_id(req) != uid:
        forbid("LabProcurement may read only its own account's service requests")
    return success(D.service_request_json(req))


@bp.get("/lab/service-requests")
def list_service_requests():
    uid, role = authenticate(_READ_ROLES)
    items = list(dbmod.store.service_requests.values())
    if role == "LabProcurement":
        items = [r for r in items if _request_account_id(r) == uid]
    f_inst = request.args.get("instrument_id")
    if f_inst is not None:
        items = [r for r in items if r["instrument_id"] == f_inst]
    f_eng = request.args.get("engineer_id")
    if f_eng is not None:
        items = [r for r in items if r["engineer_id"] == f_eng]
    f_loaner = request.args.get("loaner_unit_id")
    if f_loaner is not None:
        items = [r for r in items if r["loaner_unit_id"] == f_loaner]
    f_status = request.args.get("status")
    if f_status is not None:
        items = [r for r in items if r["status"] == f_status]
    f_type = request.args.get("request_type")
    if f_type is not None:
        items = [r for r in items if r["request_type"] == f_type]
    items = D.created_sorted(items)
    page, meta = paginate(items)
    return success(
        [D.service_request_json(r) for r in page],
        response_type="array",
        pagination=meta,
    )


@bp.post("/lab/service-requests/<request_id>/dispatch")
def dispatch_service_request(request_id):
    authenticate({"ServiceDispatcher", "PlatformAdmin"})
    req = dbmod.store.service_requests.get(request_id)
    if req is None:
        raise ApiError("ERR_SERVICE_REQUEST_NOT_FOUND", 404, "Service request not found")
    if req["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an OPEN request can be dispatched"
        )
    inst = dbmod.store.instruments[req["instrument_id"]]
    acct = dbmod.store.accounts[inst["account_id"]]
    needed_skill = D.REQUEST_TYPE_SKILL[req["request_type"]]
    eligible = [
        e
        for e in dbmod.store.engineers.values()
        if e["status"] == "ACTIVE"
        and e["territory_code"] == acct["territory_code"]
        and needed_skill in e["skills"]
    ]
    if not eligible:
        raise ApiError(
            "ERR_NO_ELIGIBLE_ENGINEER", 422,
            "No ACTIVE engineer matches the territory and required skill",
        )
    if all(
        D.engineer_dispatched_today(e["id"]) >= D.ENGINEER_DAILY_CAPACITY
        for e in eligible
    ):
        raise ApiError(
            "ERR_ENGINEER_CAPACITY_EXCEEDED", 422,
            "Every eligible engineer already holds 4 dispatched tickets today",
        )
    now = dbmod.now()
    ranked = sorted(
        eligible,
        key=lambda e: (D.engineer_open_ticket_count(e["id"]), e["created_at"], e["name"]),
    )
    pick = ranked[0]
    with dbmod.store.lock:
        req["engineer_id"] = pick["id"]
        req["status"] = "DISPATCHED"
        req["dispatched_day"] = now.date().isoformat()
        req["version"] += 1
        req["updated_at"] = now
    return success(D.service_request_json(req))


@bp.post("/lab/service-requests/<request_id>/resolve")
def resolve_service_request(request_id):
    uid, role = authenticate({"ServiceDispatcher", "FieldEngineer", "PlatformAdmin"})
    req = dbmod.store.service_requests.get(request_id)
    if req is None:
        raise ApiError("ERR_SERVICE_REQUEST_NOT_FOUND", 404, "Service request not found")
    if role == "FieldEngineer" and req["engineer_id"] != uid:
        forbid("A FieldEngineer may resolve only requests assigned to them")
    if req["status"] != "DISPATCHED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a DISPATCHED request can be resolved"
        )
    body = get_body()
    hours = body.get("hours_on_site")
    if not is_num(hours) or hours < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "hours_on_site is required and must be a non-negative number",
        )
    parts = body.get("parts_cost_cents", 0)
    if not is_int(parts) or parts < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "parts_cost_cents must be a non-negative integer",
        )
    now = dbmod.now()
    inst = dbmod.store.instruments[req["instrument_id"]]
    acct = dbmod.store.accounts[inst["account_id"]]
    labor_cents = round_half_up(Decimal(D.LABOR_RATE_CENTS_PER_HOUR) * Decimal(str(hours)))
    sla_breached = now > req["response_deadline"]
    contract = D.live_contract_for_instrument(inst["id"])
    if contract is not None:
        if (
            req["request_type"] == "PREVENTIVE_MAINTENANCE"
            and contract["used_pm_visits"] < D.TIER_PM_VISITS[contract["tier"]]
        ):
            billable = 0
            covered = labor_cents + parts
            contract["used_pm_visits"] += 1
        elif req["request_type"] == "PREVENTIVE_MAINTENANCE":
            billable = labor_cents + parts
            covered = 0
        else:
            covered_parts = round_half_up(
                Decimal(parts) * D.TIER_PARTS_PCT[contract["tier"]] / 100
            )
            covered = labor_cents + covered_parts
            billable = parts - covered_parts
    else:
        billable = labor_cents + parts + D.TRIP_CHARGE_CENTS
        covered = 0
    credit_memo = (
        round_half_up(Decimal(billable) * D.SLA_CREDIT_PCT / 100) if sla_breached else 0
    )
    with dbmod.store.lock:
        req["status"] = "RESOLVED"
        req["resolved_at"] = now
        req["sla_breached"] = sla_breached
        req["hours_on_site"] = hours
        req["parts_cost_cents"] = parts
        req["billable_cents"] = billable
        req["covered_cents"] = covered
        req["credit_memo_cents"] = credit_memo
        req["version"] += 1
        req["updated_at"] = now
        # Invoice the billable portion net of the SLA credit; credit eval runs.
        D.post_charge(acct, billable - credit_memo, now)
        # Return any reserved loaner unit to AVAILABLE.
        if req["loaner_unit_id"] is not None:
            unit = dbmod.store.loaner_units.get(req["loaner_unit_id"])
            if unit is not None and unit["status"] == "RESERVED":
                unit["status"] = "AVAILABLE"
                unit["version"] += 1
                unit["updated_at"] = now
    return success(D.service_request_json(req))


@bp.post("/lab/service-requests/<request_id>/loaner")
def reserve_loaner(request_id):
    authenticate({"ServiceDispatcher", "PlatformAdmin"})
    req = dbmod.store.service_requests.get(request_id)
    if req is None:
        raise ApiError("ERR_SERVICE_REQUEST_NOT_FOUND", 404, "Service request not found")
    if req["status"] not in ("OPEN", "DISPATCHED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "A loaner can be reserved only for an OPEN or DISPATCHED request",
        )
    inst = dbmod.store.instruments[req["instrument_id"]]
    contract = D.live_contract_for_instrument(inst["id"])
    eligible_contract = (
        contract is not None and D.TIER_LOANER_ELIGIBLE[contract["tier"]]
    )
    if (
        req["request_type"] != "BREAK_FIX"
        or req["severity"] not in ("HIGH", "CRITICAL")
        or not eligible_contract
    ):
        raise ApiError(
            "ERR_LOANER_NOT_ELIGIBLE", 422,
            "Loaner requires a HIGH/CRITICAL BREAK_FIX and a loaner-eligible contract",
        )
    pool = [
        u
        for u in dbmod.store.loaner_units.values()
        if u["status"] == "AVAILABLE" and u["model"] == inst["model"]
    ]
    if not pool:
        raise ApiError(
            "ERR_NO_LOANER_AVAILABLE", 422,
            "No AVAILABLE loaner unit matches the instrument model",
        )
    pick = min(pool, key=lambda u: (u["created_at"], u["serial_number"]))
    now = dbmod.now()
    with dbmod.store.lock:
        req["loaner_unit_id"] = pick["id"]
        pick["status"] = "RESERVED"
        pick["version"] += 1
        pick["updated_at"] = now
    return success(D.service_request_json(req))
