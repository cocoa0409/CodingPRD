"""Service calls and dispatches: intake, provider selection, roadside workflow,
completion with charges and settlement line creation."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB, CLOCK, new_id, stamp_new, touch, fmt_ts
from errors import (
    not_found, invalid_request, invalid_state, stale_version, business,
    ERR_WAITING_PERIOD_ACTIVE, ERR_MEMBERSHIP_NOT_SERVICEABLE,
    ERR_MEMBER_NOT_COVERED, ERR_TERRITORY_NOT_FOUND,
    ERR_DISPATCH_BEYOND_CANCEL, ERR_INSUFFICIENT_TRUCK_STOCK,
)
from middleware import require_auth
from response import ok_obj
from routes._common import list_response
from services.calculations import (
    SERVICE_TYPES, NON_TERMINAL_DISPATCH_STATES,
    tier_by_code, select_provider, effective_arrival_target_minutes,
    mileage_charge, parts_charge, interclub_gross,
)
from services.serialize import public
from services.validate import body_json, req_string, req_enum, req_int

bp = Blueprint("calls", __name__)

CALL_READ = {"Dispatcher", "MemberServicesRep", "SettlementClerk", "ProviderOps"}
DISPATCH_READ = {"Dispatcher", "ProviderOps", "SettlementClerk"}
FAILURE_REASONS = {"PROVIDER_DECLINED", "NO_PARTS", "MEMBER_NO_SHOW"}


def _get_call(callId):
    c = DB.service_calls.get(callId)
    if c is None:
        raise not_found("service call not found")
    return c


def _get_dispatch(dispatchId):
    d = DB.dispatches.get(dispatchId)
    if d is None:
        raise not_found("dispatch not found")
    return d


def _non_terminal_dispatch_for(call_id):
    for d in DB.dispatches.values():
        if d["service_call_id"] == call_id and d["status"] in NON_TERMINAL_DISPATCH_STATES:
            return d
    return None


def _resolve_servicing_club(state_code):
    matches = [c for c in DB.clubs.values()
               if c["status"] == "ACTIVE" and state_code in c["territory_state_codes"]]
    if not matches:
        return None
    matches.sort(key=lambda c: c["created_at"])
    return matches[0]


# ----------------------------------------------------------- call intake ---

@bp.post("/motor-club/service-calls")
def create_service_call():
    require_auth({"Dispatcher", "MemberServicesRep"})
    data = body_json()
    membership_id = req_string(data, "membership_id")
    requesting_member_id = req_string(data, "requesting_member_id")
    service_type = req_enum(data, "service_type", SERVICE_TYPES)
    breakdown_state = req_string(data, "breakdown_location_state")
    requested_tow_miles = data.get("requested_tow_miles", 0)
    if requested_tow_miles is None:
        requested_tow_miles = 0
    if isinstance(requested_tow_miles, bool) or not isinstance(requested_tow_miles, int) or requested_tow_miles < 0:
        raise invalid_request("requested_tow_miles must be an integer >= 0")
    if service_type == "TOW" and "requested_tow_miles" not in data:
        raise invalid_request("requested_tow_miles is required for TOW calls")

    # referential: FK targets exist
    m = DB.memberships.get(membership_id)
    if m is None:
        raise not_found("membership not found")
    hm = DB.household_members.get(requesting_member_id)
    if hm is None:
        raise not_found("requesting member not found")

    now = CLOCK.now()
    # waiting-period guard (priority 7): reject attempts to dictate a
    # post-upgrade benefit_tier_code on a pre-existing need. More generally,
    # direct manipulation of benefit_tier_code is rejected whenever the
    # requested value differs from the server-computed pin.
    pre_existing = (
        m.get("_tier_upgrade_effective_dt") is not None
        and now < m["_tier_upgrade_effective_dt"]
    )
    # benefit tier pinning: pre-existing need -> pre-upgrade tier
    if pre_existing and len(m["_tier_history"]) >= 2:
        benefit_tier_code = m["_tier_history"][-2]
    else:
        benefit_tier_code = m["tier_code"]

    if "benefit_tier_code" in data and data["benefit_tier_code"] is not None:
        requested_tier = data["benefit_tier_code"]
        if requested_tier != benefit_tier_code:
            raise business(ERR_WAITING_PERIOD_ACTIVE,
                           "cannot force post-upgrade benefits on a pre-existing need")

    # serviceability (priority 9)
    if m["status"] not in {"ACTIVE", "REINSTATED", "GRACE"}:
        raise business(ERR_MEMBERSHIP_NOT_SERVICEABLE,
                       "membership is not serviceable for new calls")
    # coverage (priority 10)
    if hm["membership_id"] != m["id"] or hm["status"] != "ACTIVE":
        raise business(ERR_MEMBER_NOT_COVERED,
                       "requesting member is not an ACTIVE household member of the membership")
    # territory (priority 11)
    club = _resolve_servicing_club(breakdown_state)
    if club is None:
        raise business(ERR_TERRITORY_NOT_FOUND,
                       "breakdown_location_state maps to no ACTIVE club territory")

    tier = tier_by_code(benefit_tier_code)

    # benefit cap check (household-level; strict <)
    cap = tier["annual_call_cap"]
    benefit_eligible = (m["status"] != "GRACE") and (m["calls_used_current_term"] < cap)

    call = {
        "id": new_id(),
        "membership_id": m["id"],
        "requesting_member_id": hm["id"],
        "service_type": service_type,
        "breakdown_location_state": breakdown_state,
        "servicing_club_id": club["id"],
        "is_pre_existing_need": pre_existing,
        "benefit_tier_code": benefit_tier_code,
        "requested_tow_miles": requested_tow_miles if service_type == "TOW" else 0,
        "benefit_eligible": benefit_eligible,
        "status": "REQUESTED",
        "cancel_reason": "NONE",
        "_created_dt": now,
        "_last_failed_provider_id": None,
    }
    stamp_new(call)
    DB.service_calls[call["id"]] = call
    return ok_obj(public(call), 201)


@bp.get("/motor-club/service-calls")
def list_calls():
    require_auth(CALL_READ)
    membership_id = request.args.get("membership_id")
    requesting_member_id = request.args.get("requesting_member_id")
    servicing_club_id = request.args.get("servicing_club_id")
    status = request.args.get("status")

    def filt(c):
        if membership_id is not None and c["membership_id"] != membership_id:
            return False
        if requesting_member_id is not None and c["requesting_member_id"] != requesting_member_id:
            return False
        if servicing_club_id is not None and c["servicing_club_id"] != servicing_club_id:
            return False
        if status is not None and c["status"] != status:
            return False
        return True

    return list_response(list(DB.service_calls.values()), filt)


@bp.get("/motor-club/service-calls/<callId>")
def get_call(callId):
    require_auth(CALL_READ)
    return ok_obj(public(_get_call(callId)))


@bp.post("/motor-club/service-calls/<callId>/dispatch")
def dispatch_call(callId):
    require_auth({"Dispatcher"})
    c = _get_call(callId)
    data = body_json()
    if c["status"] != "REQUESTED":
        raise invalid_state("dispatch is permitted only from REQUESTED")
    expected = data.get("expected_service_call_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise invalid_request("expected_service_call_version must be an integer")
        if expected != c["version"]:
            raise stale_version()

    exclude = c.get("_last_failed_provider_id")
    provider = select_provider(c, exclude_provider_id=exclude)
    now = CLOCK.now()
    if provider is None:
        # empty pool: auto-cancel with NO_PROVIDER; no dispatch row
        c["status"] = "CANCELLED"
        c["cancel_reason"] = "NO_PROVIDER"
        c["_last_failed_provider_id"] = None
        touch(c)
        return ok_obj(public(c))

    club = DB.clubs[c["servicing_club_id"]]
    target_minutes = effective_arrival_target_minutes(club, provider)
    promised = now + timedelta(minutes=target_minutes)
    prior_count = sum(1 for d in DB.dispatches.values() if d["service_call_id"] == c["id"])
    tier = tier_by_code(c["benefit_tier_code"])
    provisional = 0
    if c["service_type"] == "TOW":
        provisional = mileage_charge(c["requested_tow_miles"], tier, c["benefit_eligible"])

    dispatch = {
        "id": new_id(),
        "service_call_id": c["id"],
        "provider_id": provider["id"],
        "sequence_number": prior_count + 1,
        "assigned_at": fmt_ts(now),
        "promised_arrive_by": fmt_ts(promised),
        "arrived_at": None,
        "completed_at": None,
        "sla_met": None,
        "dispatched_tow_miles": c["requested_tow_miles"] if c["service_type"] == "TOW" else 0,
        "provisional_mileage_charge_cents": provisional,
        "actual_tow_miles": 0,
        "parts_used": [],
        "parts_charge_cents": 0,
        "mileage_charge_cents": 0,
        "total_member_charge_cents": 0,
        "status": "ASSIGNED",
        "failure_reason": "NONE",
        "_assigned_dt": now,
        "_promised_dt": promised,
    }
    stamp_new(dispatch)
    DB.dispatches[dispatch["id"]] = dispatch

    c["status"] = "DISPATCHED"
    c["_last_failed_provider_id"] = None
    touch(c)
    return ok_obj(public(dispatch))


@bp.post("/motor-club/service-calls/<callId>/cancel")
def cancel_call(callId):
    require_auth({"Dispatcher", "MemberServicesRep"})
    c = _get_call(callId)
    if c["status"] == "REQUESTED":
        c["status"] = "CANCELLED"
        c["cancel_reason"] = "MEMBER_REQUEST"
        touch(c)
        return ok_obj(public(c))
    if c["status"] == "DISPATCHED":
        d = _non_terminal_dispatch_for(c["id"])
        if d is None or d["status"] not in {"ASSIGNED", "ACCEPTED"}:
            raise business(ERR_DISPATCH_BEYOND_CANCEL,
                           "call cannot be cancelled once the provider is rolling or on scene")
        d["status"] = "CANCELLED"
        touch(d)
        c["status"] = "CANCELLED"
        c["cancel_reason"] = "MEMBER_REQUEST"
        touch(c)
        return ok_obj(public(c))
    if c["status"] in {"EN_ROUTE", "ON_SCENE"}:
        # the linked dispatch is EN_ROUTE or ARRIVED: member owes a service attempt
        raise business(ERR_DISPATCH_BEYOND_CANCEL,
                       "call cannot be cancelled once the provider is rolling or on scene")
    raise invalid_state("cancel is permitted only from REQUESTED or DISPATCHED")


@bp.get("/motor-club/service-calls/<callId>/dispatches")
def list_dispatches_of_call(callId):
    require_auth(DISPATCH_READ)
    _get_call(callId)
    rows = [d for d in DB.dispatches.values() if d["service_call_id"] == callId]
    return list_response(rows)


# -------------------------------------------------------------- dispatches ---

@bp.get("/motor-club/dispatches")
def list_dispatches():
    require_auth(DISPATCH_READ)
    sc = request.args.get("service_call_id")
    pid = request.args.get("provider_id")
    status = request.args.get("status")

    def filt(d):
        if sc is not None and d["service_call_id"] != sc:
            return False
        if pid is not None and d["provider_id"] != pid:
            return False
        if status is not None and d["status"] != status:
            return False
        return True

    return list_response(list(DB.dispatches.values()), filt)


@bp.get("/motor-club/dispatches/<dispatchId>")
def get_dispatch(dispatchId):
    require_auth(DISPATCH_READ)
    return ok_obj(public(_get_dispatch(dispatchId)))


@bp.post("/motor-club/dispatches/<dispatchId>/accept")
def accept_dispatch(dispatchId):
    require_auth({"ProviderOps"})
    d = _get_dispatch(dispatchId)
    data = body_json()
    en_route = data.get("en_route", False)
    if en_route is not None and not isinstance(en_route, bool):
        raise invalid_request("en_route must be a boolean")
    if d["status"] == "ASSIGNED":
        if en_route:
            # straight to EN_ROUTE in one call
            d["status"] = "EN_ROUTE"
            touch(d)
            c = DB.service_calls.get(d["service_call_id"])
            if c is not None and c["status"] == "DISPATCHED":
                c["status"] = "EN_ROUTE"
                touch(c)
            return ok_obj(public(d))
        d["status"] = "ACCEPTED"
        touch(d)
        return ok_obj(public(d))
    if d["status"] == "ACCEPTED":
        if en_route:
            d["status"] = "EN_ROUTE"
            touch(d)
            c = DB.service_calls.get(d["service_call_id"])
            if c is not None and c["status"] == "DISPATCHED":
                c["status"] = "EN_ROUTE"
                touch(c)
            return ok_obj(public(d))
        # accept on an already-ACCEPTED dispatch without en_route: idempotent no-op
        return ok_obj(public(d))
    raise invalid_state("accept is permitted only from ASSIGNED or ACCEPTED")


@bp.post("/motor-club/dispatches/<dispatchId>/arrive")
def arrive_dispatch(dispatchId):
    require_auth({"ProviderOps"})
    d = _get_dispatch(dispatchId)
    if d["status"] != "EN_ROUTE":
        raise invalid_state("arrive is permitted only from EN_ROUTE")
    now = CLOCK.now()
    d["status"] = "ARRIVED"
    d["arrived_at"] = fmt_ts(now)
    d["sla_met"] = now <= d["_promised_dt"]
    touch(d)
    c = DB.service_calls.get(d["service_call_id"])
    if c is not None and c["status"] == "EN_ROUTE":
        c["status"] = "ON_SCENE"
        touch(c)
    return ok_obj(public(d))


@bp.post("/motor-club/dispatches/<dispatchId>/complete")
def complete_dispatch(dispatchId):
    require_auth({"ProviderOps"})
    d = _get_dispatch(dispatchId)
    data = body_json()
    if d["status"] != "ARRIVED":
        raise invalid_state("complete is permitted only from ARRIVED")

    actual_tow_miles = data.get("actual_tow_miles", 0)
    if actual_tow_miles is None:
        actual_tow_miles = 0
    if isinstance(actual_tow_miles, bool) or not isinstance(actual_tow_miles, int) or actual_tow_miles < 0:
        raise invalid_request("actual_tow_miles must be an integer >= 0")

    parts_used = data.get("parts_used", [])
    if parts_used is None:
        parts_used = []
    if not isinstance(parts_used, list):
        raise invalid_request("parts_used must be an array")
    normalized_parts = []
    for p in parts_used:
        if not isinstance(p, dict):
            raise invalid_request("parts_used entries must be objects")
        sku = p.get("part_sku")
        qty = p.get("quantity")
        if not isinstance(sku, str) or not sku:
            raise invalid_request("parts_used entries require part_sku")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise invalid_request("parts_used entries require quantity >= 1")
        normalized_parts.append({"part_sku": sku, "quantity": qty})

    c = DB.service_calls.get(d["service_call_id"])
    if c is None:
        raise not_found("parent service call not found")

    if c["service_type"] == "TOW" and actual_tow_miles < 1:
        raise invalid_request("actual_tow_miles >= 1 is required for TOW dispatches")

    # truck stock sufficiency check against the completing provider's stock
    provider_id = d["provider_id"]
    stock_by_sku = {
        s["part_sku"]: s for s in DB.truck_part_stock.values()
        if s["provider_id"] == provider_id
    }
    for p in normalized_parts:
        s = stock_by_sku.get(p["part_sku"])
        if s is None or s["quantity_on_hand"] < p["quantity"]:
            raise business(ERR_INSUFFICIENT_TRUCK_STOCK,
                           "parts_used exceeds provider's truck stock")

    now = CLOCK.now()
    # decrement stock
    for p in normalized_parts:
        s = stock_by_sku[p["part_sku"]]
        s["quantity_on_hand"] -= p["quantity"]
        touch(s)

    m = DB.memberships.get(c["membership_id"])
    tier = tier_by_code(c["benefit_tier_code"])

    p_charge = parts_charge(normalized_parts)
    if c["service_type"] == "TOW":
        m_charge = mileage_charge(actual_tow_miles, tier, c["benefit_eligible"])
    else:
        m_charge = 0
    total = m_charge + p_charge

    d["actual_tow_miles"] = actual_tow_miles
    d["parts_used"] = normalized_parts
    d["parts_charge_cents"] = p_charge
    d["mileage_charge_cents"] = m_charge
    d["total_member_charge_cents"] = total
    d["status"] = "COMPLETED"
    d["completed_at"] = fmt_ts(now)
    d["_completed_dt"] = now
    touch(d)

    c["status"] = "COMPLETED"
    c["_completed_dt"] = now
    touch(c)

    if m is not None:
        if c["benefit_eligible"]:
            m["calls_used_current_term"] += 1
        m["account_credit_cents"] -= total
        touch(m)

    # inter-club billing trigger: foreign call -> settlement line
    if m is not None and m["home_club_id"] != c["servicing_club_id"]:
        servicing_club = DB.clubs[c["servicing_club_id"]]
        if c["benefit_eligible"]:
            gross = interclub_gross(
                servicing_club, c["benefit_tier_code"], c["service_type"],
                actual_tow_miles, p_charge,
            )
            line = {
                "id": new_id(),
                "settlement_period_id": None,
                "service_call_id": c["id"],
                "home_club_id": m["home_club_id"],
                "servicing_club_id": c["servicing_club_id"],
                "gross_amount_cents": gross,
                "excluded": False,
                "exclusion_reason": "",
                "assessed_fee_cents": 0,
                "assessed_net_cents": 0,
                "status": "PENDING",
            }
        else:
            line = {
                "id": new_id(),
                "settlement_period_id": None,
                "service_call_id": c["id"],
                "home_club_id": m["home_club_id"],
                "servicing_club_id": c["servicing_club_id"],
                "gross_amount_cents": 0,
                "excluded": True,
                "exclusion_reason": "MEMBER_PAY",
                "assessed_fee_cents": 0,
                "assessed_net_cents": 0,
                "status": "PENDING",
            }
        stamp_new(line)
        DB.settlement_lines[line["id"]] = line

    return ok_obj(public(d))


@bp.post("/motor-club/dispatches/<dispatchId>/fail")
def fail_dispatch(dispatchId):
    require_auth({"ProviderOps"})
    d = _get_dispatch(dispatchId)
    data = body_json()
    reason = data.get("failure_reason")
    if reason not in FAILURE_REASONS:
        raise invalid_request("failure_reason must be PROVIDER_DECLINED, NO_PARTS or MEMBER_NO_SHOW")
    if d["status"] not in {"ASSIGNED", "ACCEPTED", "EN_ROUTE"}:
        raise invalid_state("fail is permitted only from ASSIGNED, ACCEPTED or EN_ROUTE")
    d["status"] = "FAILED"
    d["failure_reason"] = reason
    touch(d)
    c = DB.service_calls.get(d["service_call_id"])
    if c is not None and c["status"] in {"DISPATCHED", "EN_ROUTE"}:
        c["status"] = "REQUESTED"
        c["_last_failed_provider_id"] = d["provider_id"]
        touch(c)
    return ok_obj(public(d))
