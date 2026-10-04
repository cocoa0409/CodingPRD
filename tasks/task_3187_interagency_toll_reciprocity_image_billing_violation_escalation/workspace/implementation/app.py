"""Flask entry point: route registration and error handlers."""

import os
from decimal import Decimal

from flask import Flask, request

from db import store
from errors import (
    ApiError,
    ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_VERSION, ERR_ACCOUNT_SUSPENDED, ERR_ACCOUNT_CLOSED,
    ERR_TRANSPONDER_NOT_ACTIVE, ERR_AGENCY_SUSPENDED, ERR_RATE_NOT_FOUND,
    ERR_PLAN_NOT_APPLICABLE, ERR_PLATE_LOOKUP_NOT_AVAILABLE,
    ERR_NOTICE_TOO_SOON, ERR_NOTICE_LIMIT_REACHED, ERR_DUPLICATE_TRANSACTION,
    ERR_DUPLICATE_TAG, ERR_DUPLICATE_PLAN_CODE, ERR_SCHEDULE_OVERLAP,
    ERR_AGREEMENT_OVERLAP, ERR_TRANSACTION_ALREADY_SETTLED,
    ERR_IMAGE_BILL_HAS_ACTIVE_DISPUTE, ERR_DISPUTE_WINDOW_CLOSED,
    ERR_BALANCE_BELOW_THRESHOLD, ERR_ACCOUNT_HAS_UNRESOLVED_VIOLATIONS,
    ERR_ACCOUNT_HAS_UNSETTLED_TRANSACTIONS, ERR_INVALID_AMOUNT,
    ERR_SETTLEMENT_HAS_EXCEPTIONS, ERR_AGENCY_HAS_PENDING_SETTLEMENT,
)
from middleware import require_roles
from response import (
    success_object, success_list, error_response, parse_pagination, paginate,
    parse_iso8601, iso3,
)
from services import (
    new_id, round_half_up_cents, stamp_new, touch, get_or_404,
    agency_view, rate_schedule_view, discount_plan_view, account_view,
    transponder_view, transaction_view, image_bill_view, violation_view,
    dispute_view, settlement_file_view, agreement_view,
    find_active_rate_schedule, find_transponder_by_tag, compute_fare,
    debit_account, credit_account, replenishment_decision, suspend_account,
    create_violation, escalate_to_hold_referred, run_advance_day_sweeps,
)

app = Flask(__name__)

ALL_ROLES = ["SettlementOfficer", "AgencyOperations", "ViolationsOfficer",
             "PlateLookupAgent", "AccountHolder"]

VEHICLE_CLASSES = {"CLASS_2", "CLASS_5", "CLASS_7"}


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(ERR_NOT_FOUND, "Method not allowed", 404)


def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return b


def require_fields(b, fields):
    for f in fields:
        if f not in b or b[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {f}", 400)


def require_int(b, f):
    v = b[f]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {f} must be an integer", 400)
    return v


def opt_int(b, f, default):
    if f not in b or b[f] is None:
        return default
    return require_int(b, f)


def sort_by_created(items):
    return sorted(items, key=lambda x: (x.get("created_at", ""), x.get("_seq", 0)))


def list_response(items, view_fn):
    limit, offset = parse_pagination(request.args)
    ordered = sort_by_created(items)
    page, total = paginate(ordered, limit, offset)
    return success_list([view_fn(i) for i in page], limit, offset, total)


# ===========================================================================
# Clock
# ===========================================================================

@app.post("/toll/_clock/set_current_utc")
def set_clock():
    require_roles(["SettlementOfficer"])
    b = body()
    require_fields(b, ["to_iso8601"])
    dt = parse_iso8601(b["to_iso8601"])
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be ISO-8601", 400)
    store.set_clock(dt)
    # re-evaluate agreement expiry on clock set
    for g in store.plate_data_agreements.values():
        if g["status"] == "ACTIVE" and store.current_dt >= g["_et_dt"]:
            g["status"] = "EXPIRED"
            touch(g)
    return success_object({"current_utc": store.current_iso()})


@app.post("/toll/_clock/advance_day")
def advance_day():
    require_roles(["SettlementOfficer"])
    b = body()
    require_fields(b, ["days"])
    days = require_int(b, "days")
    if days < 0:
        raise ApiError(ERR_INVALID_REQUEST, "days must be non-negative", 400)
    month_rolled = store.advance_days(days)
    run_advance_day_sweeps(month_rolled)
    return success_object({"epoch_day": store.epoch_day})


# ===========================================================================
# Agencies
# ===========================================================================

@app.post("/toll/agencies")
def create_agency():
    require_roles(["SettlementOfficer"])
    b = body()
    require_fields(b, ["agency_code", "name", "home_state", "reciprocity_fee_bps"])
    fee = require_int(b, "reciprocity_fee_bps")
    a = {
        "id": new_id(),
        "agency_code": b["agency_code"],
        "name": b["name"],
        "home_state": b["home_state"],
        "reciprocity_fee_bps": fee,
        "settlement_currency": b.get("settlement_currency", "USD"),
        "status": "ACTIVE",
    }
    stamp_new(a)
    a["_seq"] = store.next_seq()
    store.agencies[a["id"]] = a
    return success_object(agency_view(a), 201)


@app.get("/toll/agencies/<agencyId>")
def get_agency(agencyId):
    require_roles(ALL_ROLES)
    a = get_or_404(store.agencies, agencyId, "agency")
    return success_object(agency_view(a))


@app.get("/toll/agencies")
def list_agencies():
    require_roles(ALL_ROLES)
    items = list(store.agencies.values())
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    return list_response(items, agency_view)


@app.post("/toll/agencies/<agencyId>/suspend")
def suspend_agency(agencyId):
    require_roles(["SettlementOfficer"])
    a = get_or_404(store.agencies, agencyId, "agency")
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Agency not ACTIVE", 409)
    for f in store.settlement_files.values():
        if f["status"] in ("GENERATED", "TRANSMITTED") and (
                f["from_agency_id"] == agencyId or f["to_agency_id"] == agencyId):
            raise ApiError(ERR_AGENCY_HAS_PENDING_SETTLEMENT,
                           "Agency has pending settlement files", 409)
    a["status"] = "SUSPENDED"
    touch(a)
    return success_object(agency_view(a))


@app.post("/toll/agencies/<agencyId>/reactivate")
def reactivate_agency(agencyId):
    require_roles(["SettlementOfficer"])
    a = get_or_404(store.agencies, agencyId, "agency")
    if a["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Agency not SUSPENDED", 409)
    a["status"] = "ACTIVE"
    touch(a)
    return success_object(agency_view(a))


# ===========================================================================
# Rate schedules
# ===========================================================================

@app.post("/toll/agencies/<agencyId>/rate-schedules")
def create_rate_schedule(agencyId):
    require_roles(["AgencyOperations"])
    agency = get_or_404(store.agencies, agencyId, "agency")
    b = body()
    require_fields(b, ["plaza_code", "vehicle_class", "base_rate_cents",
                       "axle_multiplier", "effective_from", "effective_to"])
    if b["vehicle_class"] not in VEHICLE_CLASSES:
        raise ApiError(ERR_INVALID_REQUEST, "invalid vehicle_class", 400)
    ef = parse_iso8601(b["effective_from"])
    et = parse_iso8601(b["effective_to"])
    if ef is None or et is None:
        raise ApiError(ERR_INVALID_REQUEST, "invalid effective window", 400)
    if not et > ef:
        raise ApiError(ERR_INVALID_REQUEST, "effective_to must be after effective_from", 400)
    base_rate = require_int(b, "base_rate_cents")
    image_fee = opt_int(b, "image_fee_cents", 100)
    peak_mult = b.get("peak_multiplier", 1.0)
    # overlap check vs existing ACTIVE schedules same agency+plaza+class
    for r in store.rate_schedules.values():
        if r["agency_id"] == agencyId and r["status"] == "ACTIVE" \
                and r["plaza_code"] == b["plaza_code"] \
                and r["vehicle_class"] == b["vehicle_class"]:
            if ef < r["_et_dt"] and et > r["_ef_dt"]:
                raise ApiError(ERR_SCHEDULE_OVERLAP,
                               "Schedule window overlaps existing ACTIVE schedule", 409)
    rec = {
        "id": new_id(),
        "agency_id": agencyId,
        "plaza_code": b["plaza_code"],
        "vehicle_class": b["vehicle_class"],
        "base_rate_cents": base_rate,
        "axle_multiplier": b["axle_multiplier"],
        "peak_multiplier": peak_mult,
        "image_fee_cents": image_fee,
        "effective_from": iso3(ef),
        "effective_to": iso3(et),
        "status": "ACTIVE",
        "_ef_dt": ef,
        "_et_dt": et,
    }
    stamp_new(rec)
    rec["_seq"] = store.next_seq()
    store.rate_schedules[rec["id"]] = rec
    return success_object(rate_schedule_view(rec), 201)


@app.get("/toll/rate-schedules/<scheduleId>")
def get_rate_schedule(scheduleId):
    require_roles(ALL_ROLES)
    r = get_or_404(store.rate_schedules, scheduleId, "rate schedule")
    return success_object(rate_schedule_view(r))


def _filter_schedules(items):
    agency_id = request.args.get("agency_id")
    plaza = request.args.get("plaza_code")
    vc = request.args.get("vehicle_class")
    status = request.args.get("status")
    if agency_id:
        items = [r for r in items if r["agency_id"] == agency_id]
    if plaza:
        items = [r for r in items if r["plaza_code"] == plaza]
    if vc:
        items = [r for r in items if r["vehicle_class"] == vc]
    if status:
        items = [r for r in items if r["status"] == status]
    return items


@app.get("/toll/agencies/<agencyId>/rate-schedules")
def list_agency_rate_schedules(agencyId):
    require_roles(ALL_ROLES)
    get_or_404(store.agencies, agencyId, "agency")
    items = [r for r in store.rate_schedules.values() if r["agency_id"] == agencyId]
    return list_response(_filter_schedules(items), rate_schedule_view)


@app.get("/toll/rate-schedules")
def list_rate_schedules():
    require_roles(ALL_ROLES)
    return list_response(_filter_schedules(list(store.rate_schedules.values())),
                         rate_schedule_view)


# ===========================================================================
# Discount plans
# ===========================================================================

@app.post("/toll/agencies/<agencyId>/discount-plans")
def create_discount_plan(agencyId):
    require_roles(["AgencyOperations"])
    get_or_404(store.agencies, agencyId, "agency")
    b = body()
    require_fields(b, ["plan_code", "discount_pct", "daily_discount_cap_cents",
                       "applies_to_agency_codes"])
    cap = require_int(b, "daily_discount_cap_cents")
    applies = b["applies_to_agency_codes"]
    if not isinstance(applies, list):
        raise ApiError(ERR_INVALID_REQUEST, "applies_to_agency_codes must be a list", 400)
    for p in store.discount_plans.values():
        if p["agency_id"] == agencyId and p["plan_code"] == b["plan_code"]:
            raise ApiError(ERR_DUPLICATE_PLAN_CODE,
                           "plan_code already exists within agency", 409)
    rec = {
        "id": new_id(),
        "agency_id": agencyId,
        "plan_code": b["plan_code"],
        "discount_pct": b["discount_pct"],
        "daily_discount_cap_cents": cap,
        "applies_to_agency_codes": list(applies),
        "min_trips_per_month": opt_int(b, "min_trips_per_month", 0),
        "status": "ACTIVE",
    }
    stamp_new(rec)
    rec["_seq"] = store.next_seq()
    store.discount_plans[rec["id"]] = rec
    return success_object(discount_plan_view(rec), 201)


@app.get("/toll/discount-plans/<planId>")
def get_discount_plan(planId):
    require_roles(ALL_ROLES)
    p = get_or_404(store.discount_plans, planId, "discount plan")
    return success_object(discount_plan_view(p))


def _filter_plans(items):
    agency_id = request.args.get("agency_id")
    status = request.args.get("status")
    if agency_id:
        items = [p for p in items if p["agency_id"] == agency_id]
    if status:
        items = [p for p in items if p["status"] == status]
    return items


@app.get("/toll/agencies/<agencyId>/discount-plans")
def list_agency_discount_plans(agencyId):
    require_roles(ALL_ROLES)
    get_or_404(store.agencies, agencyId, "agency")
    items = [p for p in store.discount_plans.values() if p["agency_id"] == agencyId]
    return list_response(_filter_plans(items), discount_plan_view)


@app.get("/toll/discount-plans")
def list_discount_plans():
    require_roles(ALL_ROLES)
    return list_response(_filter_plans(list(store.discount_plans.values())),
                         discount_plan_view)


# ===========================================================================
# Accounts
# ===========================================================================

@app.post("/toll/accounts")
def create_account():
    require_roles(["AgencyOperations"])
    b = body()
    require_fields(b, ["home_agency_id", "holder_name", "holder_email",
                       "discount_plan_id"])
    agency = store.agencies.get(b["home_agency_id"])
    if agency is None:
        raise ApiError(ERR_NOT_FOUND, "home agency not found", 404)
    plan = store.discount_plans.get(b["discount_plan_id"])
    if plan is None or plan["agency_id"] != b["home_agency_id"] \
            or plan["status"] == "RETIRED":
        raise ApiError(ERR_PLAN_NOT_APPLICABLE,
                       "Discount plan not applicable to home agency", 422)
    opening = opt_int(b, "opening_balance_cents", 0)
    a = {
        "id": new_id(),
        "home_agency_id": b["home_agency_id"],
        "holder_name": b["holder_name"],
        "holder_email": b["holder_email"],
        "discount_plan_id": b["discount_plan_id"],
        "balance_cents": opening,
        "low_balance_threshold_cents": opt_int(b, "low_balance_threshold_cents", 1000),
        "replenishment_amount_cents": opt_int(b, "replenishment_amount_cents", 2500),
        "replenishment_fail_count": 0,
        "discount_used_today_cents": 0,
        "trips_this_month": 0,
        "status": "ACTIVE",
        "suspended_reason": None,
    }
    stamp_new(a)
    a["_seq"] = store.next_seq()
    store.accounts[a["id"]] = a
    return success_object(account_view(a), 201)


@app.get("/toll/accounts/<accountId>")
def get_account(accountId):
    require_roles(["SettlementOfficer", "AgencyOperations", "ViolationsOfficer",
                   "AccountHolder"])
    a = get_or_404(store.accounts, accountId, "account")
    return success_object(account_view(a))


@app.get("/toll/accounts")
def list_accounts():
    require_roles(["SettlementOfficer", "AgencyOperations", "ViolationsOfficer"])
    items = list(store.accounts.values())
    hag = request.args.get("home_agency_id")
    status = request.args.get("status")
    plan = request.args.get("discount_plan_id")
    if hag:
        items = [a for a in items if a["home_agency_id"] == hag]
    if status:
        items = [a for a in items if a["status"] == status]
    if plan:
        items = [a for a in items if a["discount_plan_id"] == plan]
    return list_response(items, account_view)


def _check_occ(account, b):
    expected = b.get("expected_account_version")
    if expected is not None and expected != account["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_account_version does not match current version", 412)


@app.post("/toll/accounts/<accountId>/replenishments")
def record_replenishment(accountId):
    user_id, role = require_roles(["AgencyOperations", "AccountHolder"])
    a = get_or_404(store.accounts, accountId, "account")
    if role == "AccountHolder" and user_id != accountId:
        from errors import ERR_FORBIDDEN_FOR_ROLE
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, "Not your account", 403)
    b = body()
    require_fields(b, ["amount_cents", "outcome"])
    _check_occ(a, b)
    amount = require_int(b, "amount_cents")
    if amount <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, "amount_cents must be positive", 409)
    outcome = b["outcome"]
    if outcome not in ("SUCCEEDED", "FAILED"):
        raise ApiError(ERR_INVALID_REQUEST, "outcome must be SUCCEEDED or FAILED", 400)
    if outcome == "SUCCEEDED":
        a["balance_cents"] += amount
        a["replenishment_fail_count"] = 0
    else:
        a["replenishment_fail_count"] += 1
        if a["replenishment_fail_count"] >= 3 and a["status"] == "ACTIVE":
            a["status"] = "SUSPENDED"
            a["suspended_reason"] = "REPLENISHMENT_FAILED"
    touch(a)
    return success_object({
        "balance_cents": a["balance_cents"],
        "replenishment_fail_count": a["replenishment_fail_count"],
        "status": a["status"],
    }, 201)


@app.post("/toll/accounts/<accountId>/adjustments")
def record_adjustment(accountId):
    require_roles(["AgencyOperations"])
    a = get_or_404(store.accounts, accountId, "account")
    b = body()
    require_fields(b, ["delta_cents", "reason"])
    _check_occ(a, b)
    delta = require_int(b, "delta_cents")
    if a["balance_cents"] + delta < 0:
        raise ApiError(ERR_INVALID_AMOUNT,
                       "Adjustment would drive balance negative", 409)
    a["balance_cents"] += delta
    touch(a)
    return success_object({"balance_cents": a["balance_cents"]}, 201)


@app.post("/toll/accounts/<accountId>/reinstate")
def reinstate_account(accountId):
    require_roles(["AgencyOperations"])
    a = get_or_404(store.accounts, accountId, "account")
    if a["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Account not SUSPENDED", 409)
    if a["balance_cents"] < a["low_balance_threshold_cents"]:
        raise ApiError(ERR_BALANCE_BELOW_THRESHOLD,
                       "Balance below low-balance threshold", 409)
    for v in store.violations.values():
        if v["account_id"] == accountId and v["status"] in ("ESCALATED", "HOLD_REFERRED") \
                and v["total_outstanding_cents"] > 0:
            raise ApiError(ERR_ACCOUNT_HAS_UNRESOLVED_VIOLATIONS,
                           "Account has unresolved violations", 409)
    a["status"] = "ACTIVE"
    a["replenishment_fail_count"] = 0
    a["suspended_reason"] = None
    touch(a)
    return success_object(account_view(a))


@app.post("/toll/accounts/<accountId>/close")
def close_account(accountId):
    user_id, role = require_roles(["AccountHolder"])
    a = get_or_404(store.accounts, accountId, "account")
    if user_id != accountId:
        from errors import ERR_FORBIDDEN_FOR_ROLE
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, "Not your account", 403)
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Account not ACTIVE", 409)
    for v in store.violations.values():
        if v["account_id"] == accountId and v["status"] in (
                "OPEN", "NOTICED", "ESCALATED", "HOLD_REFERRED"):
            raise ApiError(ERR_ACCOUNT_HAS_UNRESOLVED_VIOLATIONS,
                           "Account has unresolved violations", 409)
    for t in store.toll_transactions.values():
        if t["account_id"] == accountId and t["status"] == "POSTED":
            raise ApiError(ERR_ACCOUNT_HAS_UNSETTLED_TRANSACTIONS,
                           "Account has unsettled transactions", 409)
    a["status"] = "CLOSED"
    a["balance_cents"] = 0
    touch(a)
    for t in store.transponders.values():
        if t["account_id"] == accountId and t["status"] == "ACTIVE":
            t["status"] = "RETIRED"
            touch(t)
    return success_object(account_view(a))


# ===========================================================================
# Transponders
# ===========================================================================

@app.post("/toll/accounts/<accountId>/transponders")
def create_transponder(accountId):
    require_roles(["AgencyOperations"])
    get_or_404(store.accounts, accountId, "account")
    b = body()
    require_fields(b, ["tag_number", "vehicle_class", "plate_number", "plate_state"])
    if b["vehicle_class"] not in VEHICLE_CLASSES:
        raise ApiError(ERR_INVALID_REQUEST, "invalid vehicle_class", 400)
    if find_transponder_by_tag(b["tag_number"]) is not None:
        raise ApiError(ERR_DUPLICATE_TAG, "tag_number already issued", 409)
    t = {
        "id": new_id(),
        "account_id": accountId,
        "tag_number": b["tag_number"],
        "vehicle_class": b["vehicle_class"],
        "plate_number": b["plate_number"],
        "plate_state": b["plate_state"],
        "status": "ACTIVE",
    }
    stamp_new(t)
    t["_seq"] = store.next_seq()
    store.transponders[t["id"]] = t
    return success_object(transponder_view(t), 201)


@app.get("/toll/transponders/<transponderId>")
def get_transponder(transponderId):
    require_roles(ALL_ROLES)
    t = get_or_404(store.transponders, transponderId, "transponder")
    return success_object(transponder_view(t))


def _filter_transponders(items):
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id:
        items = [t for t in items if t["account_id"] == account_id]
    if status:
        items = [t for t in items if t["status"] == status]
    return items


@app.get("/toll/accounts/<accountId>/transponders")
def list_account_transponders(accountId):
    require_roles(ALL_ROLES)
    get_or_404(store.accounts, accountId, "account")
    items = [t for t in store.transponders.values() if t["account_id"] == accountId]
    return list_response(_filter_transponders(items), transponder_view)


@app.get("/toll/transponders")
def list_transponders():
    require_roles(ALL_ROLES)
    return list_response(_filter_transponders(list(store.transponders.values())),
                         transponder_view)


def _own_transponder(user_id, t):
    if t["account_id"] != user_id:
        from errors import ERR_FORBIDDEN_FOR_ROLE
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, "Not your transponder", 403)


@app.post("/toll/transponders/<transponderId>/report_lost")
def report_lost(transponderId):
    user_id, role = require_roles(["AccountHolder"])
    t = get_or_404(store.transponders, transponderId, "transponder")
    _own_transponder(user_id, t)
    if t["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Transponder not ACTIVE", 409)
    t["status"] = "REPORTED_LOST"
    touch(t)
    return success_object(transponder_view(t))


@app.post("/toll/transponders/<transponderId>/report_found")
def report_found(transponderId):
    user_id, role = require_roles(["AccountHolder"])
    t = get_or_404(store.transponders, transponderId, "transponder")
    _own_transponder(user_id, t)
    if t["status"] != "REPORTED_LOST":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Transponder not REPORTED_LOST", 409)
    t["status"] = "ACTIVE"
    touch(t)
    return success_object(transponder_view(t))


@app.post("/toll/transponders/<transponderId>/retire")
def retire_transponder(transponderId):
    user_id, role = require_roles(["AccountHolder"])
    t = get_or_404(store.transponders, transponderId, "transponder")
    _own_transponder(user_id, t)
    if t["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Transponder not ACTIVE", 409)
    t["status"] = "RETIRED"
    touch(t)
    return success_object(transponder_view(t))


# ===========================================================================
# Toll transactions
# ===========================================================================

@app.post("/toll/toll-transactions")
def post_toll_transaction():
    require_roles(["AgencyOperations"])
    b = body()
    require_fields(b, ["away_agency_id", "plaza_code", "trip_timestamp",
                       "is_peak", "idempotency_key"])
    away = store.agencies.get(b["away_agency_id"])
    if away is None:
        raise ApiError(ERR_NOT_FOUND, "away agency not found", 404)
    trip_dt = parse_iso8601(b["trip_timestamp"])
    if trip_dt is None:
        raise ApiError(ERR_INVALID_REQUEST, "trip_timestamp invalid", 400)
    if not isinstance(b["is_peak"], bool):
        raise ApiError(ERR_INVALID_REQUEST, "is_peak must be boolean", 400)
    tag = b.get("tag_number")
    plate_number = b.get("plate_number")
    plate_state = b.get("plate_state")
    if not tag and not (plate_number and plate_state):
        raise ApiError(ERR_INVALID_REQUEST,
                       "tag_number or plate_number+plate_state required", 400)

    # idempotency
    ident = tag if tag else f"{plate_number}|{plate_state}"
    for t in store.toll_transactions.values():
        if t["away_agency_id"] == b["away_agency_id"] \
                and t["plaza_code"] == b["plaza_code"] \
                and t["trip_timestamp"] == iso3(trip_dt) \
                and t["idempotency_key"] == b["idempotency_key"] \
                and t.get("_ident") == ident:
            raise ApiError(ERR_DUPLICATE_TRANSACTION,
                           "Duplicate transaction", 409)

    # agency suspended check
    if away["status"] == "SUSPENDED":
        raise ApiError(ERR_AGENCY_SUSPENDED, "Away agency suspended", 409)

    # resolve vehicle
    transponder = None
    account = None
    detection = "IMAGE"
    billed_class = None
    if tag:
        transponder = find_transponder_by_tag(tag)
        if transponder is not None and transponder["status"] == "ACTIVE":
            account = store.accounts.get(transponder["account_id"])
            detection = "TRANSPONDER"
            billed_class = transponder["vehicle_class"]
        elif transponder is not None and transponder["status"] == "REPORTED_LOST":
            # lost-tag reroute: treat as image path using the tag's plate
            account = None
            detection = "IMAGE"
            plate_number = transponder["plate_number"]
            plate_state = transponder["plate_state"]
            billed_class = transponder["vehicle_class"]
        elif transponder is not None and transponder["status"] == "RETIRED":
            raise ApiError(ERR_TRANSPONDER_NOT_ACTIVE,
                           "Transponder retired", 409)
        else:
            # unknown tag: image path requires plate info
            if not (plate_number and plate_state):
                raise ApiError(ERR_INVALID_REQUEST,
                               "Unknown tag requires plate_number/plate_state", 400)
            detection = "IMAGE"
    else:
        detection = "IMAGE"

    # account safety checks (transponder path debits the account now)
    if detection == "TRANSPONDER":
        if account["status"] == "SUSPENDED":
            raise ApiError(ERR_ACCOUNT_SUSPENDED, "Account suspended", 409)
        if account["status"] == "CLOSED":
            raise ApiError(ERR_ACCOUNT_CLOSED, "Account closed", 409)

    # For IMAGE path with no class known, default to CLASS_2 rate lookup
    if billed_class is None:
        billed_class = "CLASS_2"

    rate = find_active_rate_schedule(b["away_agency_id"], b["plaza_code"],
                                     billed_class, trip_dt)
    if rate is None:
        raise ApiError(ERR_RATE_NOT_FOUND, "No rate schedule covers trip", 422)

    if detection == "TRANSPONDER":
        gross, discount, charged = compute_fare(rate, b["is_peak"],
                                                "TRANSPONDER", account, away)
    else:
        # image: price without an account; discount always 0
        dummy = {"discount_plan_id": None, "trips_this_month": 0,
                 "discount_used_today_cents": 0, "home_agency_id": None}
        gross, discount, charged = compute_fare(rate, b["is_peak"], "IMAGE",
                                                dummy, away)

    txn = {
        "id": new_id(),
        "account_id": account["id"] if (detection == "TRANSPONDER" and account) else None,
        "transponder_id": transponder["id"] if detection == "TRANSPONDER" else None,
        "away_agency_id": b["away_agency_id"],
        "rate_schedule_id": rate["id"],
        "plaza_code": b["plaza_code"],
        "trip_timestamp": iso3(trip_dt),
        "is_peak": b["is_peak"],
        "billed_vehicle_class": billed_class,
        "detection_method": detection,
        "gross_amount_cents": gross,
        "discount_amount_cents": discount,
        "charged_amount_cents": charged,
        "status": "POSTED",
        "settlement_file_id": None,
        "idempotency_key": b["idempotency_key"],
        "_ident": ident,
        "_plate_number": plate_number,
        "_plate_state": plate_state,
    }
    # TollTransaction carries only id + created_at (no updated_at/version)
    txn["created_at"] = iso3(store.current_dt_wall())
    txn["_seq"] = store.next_seq()
    store.toll_transactions[txn["id"]] = txn

    if detection == "TRANSPONDER":
        account["discount_used_today_cents"] += discount
        account["trips_this_month"] += 1
        debit_account(account, charged)
    else:
        # create ImageBill in PENDING_LOOKUP
        bill = {
            "id": new_id(),
            "account_id": None,
            "plate_number": plate_number,
            "plate_state": plate_state,
            "toll_transaction_id": txn["id"],
            "lookup_agency_id": None,
            "billed_amount_cents": charged,
            "misread_flag": False,
            "status": "PENDING_LOOKUP",
        }
        stamp_new(bill)
        bill["_seq"] = store.next_seq()
        store.image_bills[bill["id"]] = bill

    return success_object(transaction_view(txn), 201)


@app.get("/toll/toll-transactions/<transactionId>")
def get_toll_transaction(transactionId):
    require_roles(ALL_ROLES)
    t = get_or_404(store.toll_transactions, transactionId, "toll transaction")
    return success_object(transaction_view(t))


@app.get("/toll/toll-transactions")
def list_toll_transactions():
    require_roles(ALL_ROLES)
    items = list(store.toll_transactions.values())
    for f in ("account_id", "away_agency_id", "settlement_file_id", "status",
              "transponder_id", "rate_schedule_id"):
        v = request.args.get(f)
        if v:
            items = [t for t in items if t.get(f) == v]
    return list_response(items, transaction_view)


@app.post("/toll/toll-transactions/<transactionId>/void")
def void_toll_transaction(transactionId):
    require_roles(["AgencyOperations"])
    t = get_or_404(store.toll_transactions, transactionId, "toll transaction")
    if t["status"] == "SETTLED" or t["settlement_file_id"]:
        raise ApiError(ERR_TRANSACTION_ALREADY_SETTLED,
                       "Transaction already settled", 409)
    if t["status"] != "POSTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Transaction not POSTED", 409)
    t["status"] = "VOIDED"
    if t["account_id"]:
        account = store.accounts.get(t["account_id"])
        if account is not None:
            credit_account(account, t["charged_amount_cents"])
    return success_object(transaction_view(t))


# ===========================================================================
# Image bills
# ===========================================================================

@app.get("/toll/image-bills/<imageBillId>")
def get_image_bill(imageBillId):
    require_roles(ALL_ROLES)
    b = get_or_404(store.image_bills, imageBillId, "image bill")
    return success_object(image_bill_view(b))


@app.get("/toll/image-bills")
def list_image_bills():
    require_roles(ALL_ROLES)
    items = list(store.image_bills.values())
    for f in ("account_id", "status", "toll_transaction_id", "lookup_agency_id"):
        v = request.args.get(f)
        if v:
            items = [i for i in items if i.get(f) == v]
    return list_response(items, image_bill_view)


def _find_covering_agreement(away_agency_id, plate_state):
    """ACTIVE agreement: requesting == away agency, covers plate_state,
    logical clock inside [effective_from, effective_to)."""
    for g in store.plate_data_agreements.values():
        if g["status"] != "ACTIVE":
            continue
        if g["requesting_agency_id"] != away_agency_id:
            continue
        if plate_state not in g["covers_states"]:
            continue
        if g["_ef_dt"] <= store.current_dt < g["_et_dt"]:
            return g
    return None


@app.post("/toll/image-bills/<imageBillId>/resolve")
def resolve_image_bill(imageBillId):
    require_roles(["PlateLookupAgent"])
    bill = get_or_404(store.image_bills, imageBillId, "image bill")
    if bill["status"] != "PENDING_LOOKUP":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Image bill not PENDING_LOOKUP", 409)
    txn = store.toll_transactions.get(bill["toll_transaction_id"])
    away_agency_id = txn["away_agency_id"] if txn else None
    agreement = _find_covering_agreement(away_agency_id, bill["plate_state"])
    if agreement is None:
        raise ApiError(ERR_PLATE_LOOKUP_NOT_AVAILABLE,
                       "No ACTIVE covering plate data agreement", 409)
    b = body()
    resolved_account_id = b.get("resolved_account_id")
    account = None
    if resolved_account_id:
        account = store.accounts.get(resolved_account_id)
        if account is None:
            raise ApiError(ERR_NOT_FOUND, "resolved account not found", 404)
    if account is not None and account["status"] == "ACTIVE":
        bill["status"] = "BILLED"
        bill["account_id"] = account["id"]
        bill["lookup_agency_id"] = agreement["providing_agency_id"]
        touch(bill)
        debit_account(account, bill["billed_amount_cents"])
    else:
        # no account, or suspended at resolve time -> escalation path
        bill["status"] = "ESCALATED"
        bill["lookup_agency_id"] = agreement["providing_agency_id"]
        touch(bill)
        create_violation(
            account_id=account["id"] if account else None,
            plate_number=bill["plate_number"],
            plate_state=bill["plate_state"],
            toll_transaction_id=bill["toll_transaction_id"],
            image_bill_id=bill["id"],
            toll_amount_cents=bill["billed_amount_cents"],
        )
    return success_object(image_bill_view(bill))


@app.post("/toll/image-bills/<imageBillId>/void")
def void_image_bill(imageBillId):
    require_roles(["AgencyOperations"])
    bill = get_or_404(store.image_bills, imageBillId, "image bill")
    if bill["status"] not in ("PENDING_LOOKUP", "BILLED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Image bill cannot be voided from current state", 409)
    if bill["status"] == "BILLED":
        for d in store.disputes.values():
            if d.get("image_bill_id") == imageBillId \
                    and d["status"] in ("FILED", "UNDER_REVIEW"):
                raise ApiError(ERR_IMAGE_BILL_HAS_ACTIVE_DISPUTE,
                               "Image bill has active dispute", 409)
        if bill["account_id"]:
            account = store.accounts.get(bill["account_id"])
            if account is not None:
                credit_account(account, bill["billed_amount_cents"])
    bill["status"] = "VOIDED"
    touch(bill)
    return success_object(image_bill_view(bill))


# ===========================================================================
# Violations
# ===========================================================================

@app.get("/toll/violations/<violationId>")
def get_violation(violationId):
    require_roles(ALL_ROLES)
    v = get_or_404(store.violations, violationId, "violation")
    return success_object(violation_view(v))


@app.get("/toll/violations")
def list_violations():
    require_roles(ALL_ROLES)
    items = list(store.violations.values())
    for f in ("account_id", "status", "toll_transaction_id", "image_bill_id"):
        val = request.args.get(f)
        if val:
            items = [i for i in items if i.get(f) == val]
    return list_response(items, violation_view)


NOTICE_FEES = {0: 500, 1: 2500, 2: 5000}


@app.post("/toll/violations/<violationId>/issue_notice")
def issue_notice(violationId):
    require_roles(["ViolationsOfficer"])
    v = get_or_404(store.violations, violationId, "violation")
    if v["status"] not in ("OPEN", "NOTICED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Violation not in a noticable state", 409)
    if v["notice_count"] >= 3:
        raise ApiError(ERR_NOTICE_LIMIT_REACHED, "Notice limit reached", 409)
    if v["notice_count"] >= 1:
        if store.epoch_day < v["current_notice_day"] + 30:
            raise ApiError(ERR_NOTICE_TOO_SOON,
                           "30-day spacing not elapsed", 409)
    fee = NOTICE_FEES[v["notice_count"]]
    if v["notice_count"] == 0:
        v["first_notice_day"] = store.epoch_day
        v["status"] = "NOTICED"
    v["notice_count"] += 1
    v["admin_fees_cents"] += fee
    v["total_outstanding_cents"] += fee
    v["current_notice_day"] = store.epoch_day
    touch(v)
    return success_object(violation_view(v))


@app.post("/toll/violations/<violationId>/pay")
def pay_violation(violationId):
    require_roles(["AccountHolder", "ViolationsOfficer"])
    v = get_or_404(store.violations, violationId, "violation")
    if v["status"] not in ("OPEN", "NOTICED", "ESCALATED", "HOLD_REFERRED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Violation cannot be paid from current state", 409)
    v["status"] = "PAID"
    v["total_outstanding_cents"] = 0
    touch(v)
    return success_object(violation_view(v))


@app.post("/toll/violations/<violationId>/dismiss")
def dismiss_violation(violationId):
    require_roles(["ViolationsOfficer"])
    v = get_or_404(store.violations, violationId, "violation")
    if v["status"] not in ("OPEN", "NOTICED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Violation cannot be dismissed from current state", 409)
    v["status"] = "DISMISSED"
    touch(v)
    return success_object(violation_view(v))


# ===========================================================================
# Disputes
# ===========================================================================

DISPUTE_TYPES = {"VEHICLE_CLASSIFICATION", "MISREAD_PLATE", "RENTAL_VEHICLE"}


def _find_account_by_plate(plate_number, plate_state):
    for t in store.transponders.values():
        if t["plate_number"] == plate_number and t["plate_state"] == plate_state:
            return store.accounts.get(t["account_id"])
    return None


@app.post("/toll/disputes")
def file_dispute():
    user_id, role = require_roles(["AccountHolder"])
    b = body()
    require_fields(b, ["dispute_type"])
    dtype = b["dispute_type"]
    if dtype not in DISPUTE_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, "invalid dispute_type", 400)
    account_id = b.get("account_id")
    if account_id is not None and account_id != user_id:
        from errors import ERR_FORBIDDEN_FOR_ROLE
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, "Not your account", 403)

    txn = None
    bill = None
    violation = None
    if dtype == "VEHICLE_CLASSIFICATION":
        require_fields(b, ["toll_transaction_id", "claimed_vehicle_class"])
        txn = store.toll_transactions.get(b["toll_transaction_id"])
        if txn is None:
            raise ApiError(ERR_NOT_FOUND, "toll transaction not found", 404)
        if b["claimed_vehicle_class"] not in VEHICLE_CLASSES:
            raise ApiError(ERR_INVALID_REQUEST, "invalid claimed_vehicle_class", 400)
        if b["claimed_vehicle_class"] == txn["billed_vehicle_class"]:
            raise ApiError(ERR_INVALID_REQUEST,
                           "claimed class must differ from billed", 400)
        if txn["status"] != "POSTED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION,
                           "Transaction not POSTED", 409)
    elif dtype == "MISREAD_PLATE":
        require_fields(b, ["image_bill_id", "claimed_plate_number"])
        bill = store.image_bills.get(b["image_bill_id"])
        if bill is None:
            raise ApiError(ERR_NOT_FOUND, "image bill not found", 404)
    else:  # RENTAL_VEHICLE
        require_fields(b, ["image_bill_id", "rental_agreement_ref"])
        bill = store.image_bills.get(b["image_bill_id"])
        if bill is None:
            raise ApiError(ERR_NOT_FOUND, "image bill not found", 404)

    if b.get("violation_id"):
        violation = store.violations.get(b["violation_id"])
        if violation is None:
            raise ApiError(ERR_NOT_FOUND, "violation not found", 404)

    # dispute window: filed within 90 days of trip
    if txn is not None:
        trip_dt = parse_iso8601(txn["trip_timestamp"])
    elif bill is not None:
        txn2 = store.toll_transactions.get(bill["toll_transaction_id"])
        trip_dt = parse_iso8601(txn2["trip_timestamp"]) if txn2 else None
    elif violation is not None:
        txn3 = store.toll_transactions.get(violation["toll_transaction_id"])
        trip_dt = parse_iso8601(txn3["trip_timestamp"]) if txn3 else None
    else:
        trip_dt = None
    if trip_dt is not None:
        trip_epoch_day = store.epoch_day_of(trip_dt)
        if trip_epoch_day is not None and store.epoch_day - trip_epoch_day > 90:
            raise ApiError(ERR_DISPUTE_WINDOW_CLOSED,
                           "Dispute filed more than 90 days after trip", 409)

    d = {
        "id": new_id(),
        "account_id": account_id,
        "dispute_type": dtype,
        "toll_transaction_id": b.get("toll_transaction_id"),
        "image_bill_id": b.get("image_bill_id"),
        "violation_id": b.get("violation_id"),
        "claimed_vehicle_class": b.get("claimed_vehicle_class"),
        "claimed_plate_number": b.get("claimed_plate_number"),
        "rental_agreement_ref": b.get("rental_agreement_ref"),
        "filed_day": store.epoch_day,
        "status": "FILED",
    }
    stamp_new(d)
    d["_seq"] = store.next_seq()
    store.disputes[d["id"]] = d

    if dtype == "VEHICLE_CLASSIFICATION" and txn is not None:
        txn["status"] = "DISPUTED"

    return success_object(dispute_view(d), 201)


@app.get("/toll/disputes/<disputeId>")
def get_dispute(disputeId):
    require_roles(ALL_ROLES)
    d = get_or_404(store.disputes, disputeId, "dispute")
    return success_object(dispute_view(d))


@app.get("/toll/disputes")
def list_disputes():
    require_roles(ALL_ROLES)
    items = list(store.disputes.values())
    for f in ("account_id", "status", "dispute_type", "toll_transaction_id",
              "image_bill_id", "violation_id"):
        val = request.args.get(f)
        if val:
            items = [i for i in items if i.get(f) == val]
    return list_response(items, dispute_view)


def _return_txn_to_posted(d):
    if d["dispute_type"] == "VEHICLE_CLASSIFICATION" and d.get("toll_transaction_id"):
        txn = store.toll_transactions.get(d["toll_transaction_id"])
        if txn is not None and txn["status"] == "DISPUTED":
            txn["status"] = "POSTED"


@app.post("/toll/disputes/<disputeId>/begin_review")
def begin_review(disputeId):
    require_roles(["ViolationsOfficer"])
    d = get_or_404(store.disputes, disputeId, "dispute")
    if d["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Dispute not FILED", 409)
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return success_object(dispute_view(d))


@app.post("/toll/disputes/<disputeId>/uphold")
def uphold_dispute(disputeId):
    require_roles(["ViolationsOfficer"])
    d = get_or_404(store.disputes, disputeId, "dispute")
    if d["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Dispute not UNDER_REVIEW", 409)
    d["status"] = "UPHOLD"
    touch(d)

    if d["dispute_type"] == "VEHICLE_CLASSIFICATION":
        txn = store.toll_transactions.get(d["toll_transaction_id"])
        if txn is not None and txn["status"] == "DISPUTED":
            account = store.accounts.get(txn["account_id"])
            away = store.agencies.get(txn["away_agency_id"])
            rate = store.rate_schedules.get(txn["rate_schedule_id"])
            new_class = d["claimed_vehicle_class"]
            # re-price at claimed class: find schedule for claimed class
            trip_dt = parse_iso8601(txn["trip_timestamp"])
            new_rate = find_active_rate_schedule(
                txn["away_agency_id"], txn["plaza_code"], new_class, trip_dt)
            use_rate = new_rate if new_rate is not None else rate
            if account is not None:
                gross, discount, charged = compute_fare(
                    use_rate, txn["is_peak"], txn["detection_method"],
                    account, away)
                old_charged = txn["charged_amount_cents"]
                delta = old_charged - charged
                txn["billed_vehicle_class"] = new_class
                txn["gross_amount_cents"] = gross
                txn["discount_amount_cents"] = discount
                txn["charged_amount_cents"] = charged
                if new_rate is not None:
                    txn["rate_schedule_id"] = new_rate["id"]
                txn["status"] = "POSTED"
                if delta != 0:
                    credit_account(account, delta)
            else:
                txn["billed_vehicle_class"] = new_class
                txn["status"] = "POSTED"
    else:
        # MISREAD_PLATE / RENTAL_VEHICLE
        bill = store.image_bills.get(d["image_bill_id"])
        if bill is not None and bill["status"] == "BILLED":
            # net-credit original account exactly once
            if bill["account_id"]:
                account = store.accounts.get(bill["account_id"])
                if account is not None:
                    credit_account(account, bill["billed_amount_cents"])
            if d["dispute_type"] == "MISREAD_PLATE":
                bill["misread_flag"] = True
            bill["status"] = "REBILLED"
            touch(bill)
            # new image bill for corrected plate / rental liable party
            new_plate = d["claimed_plate_number"] or bill["plate_number"]
            new_state = bill["plate_state"]
            new_account = _find_account_by_plate(new_plate, new_state)
            new_bill = {
                "id": new_id(),
                "account_id": new_account["id"] if new_account else None,
                "plate_number": new_plate,
                "plate_state": new_state,
                "toll_transaction_id": bill["toll_transaction_id"],
                "lookup_agency_id": None,
                "billed_amount_cents": bill["billed_amount_cents"],
                "misread_flag": False,
                "status": "PENDING_LOOKUP",
            }
            stamp_new(new_bill)
            new_bill["_seq"] = store.next_seq()
            store.image_bills[new_bill["id"]] = new_bill
        # dismiss linked violation
        if d.get("violation_id"):
            v = store.violations.get(d["violation_id"])
            if v is not None and v["status"] in ("OPEN", "NOTICED", "ESCALATED",
                                                 "HOLD_REFERRED"):
                v["status"] = "DISMISSED"
                v["total_outstanding_cents"] = 0
                touch(v)

    return success_object(dispute_view(d))


@app.post("/toll/disputes/<disputeId>/reject")
def reject_dispute(disputeId):
    require_roles(["ViolationsOfficer"])
    d = get_or_404(store.disputes, disputeId, "dispute")
    if d["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Dispute not UNDER_REVIEW", 409)
    d["status"] = "REJECTED"
    touch(d)
    _return_txn_to_posted(d)
    return success_object(dispute_view(d))


@app.post("/toll/disputes/<disputeId>/withdraw")
def withdraw_dispute(disputeId):
    user_id, role = require_roles(["AccountHolder"])
    d = get_or_404(store.disputes, disputeId, "dispute")
    if d.get("account_id") is not None and d["account_id"] != user_id:
        from errors import ERR_FORBIDDEN_FOR_ROLE
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, "Not your dispute", 403)
    if d["status"] not in ("FILED", "UNDER_REVIEW"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Dispute cannot be withdrawn from current state", 409)
    d["status"] = "WITHDRAWN"
    touch(d)
    _return_txn_to_posted(d)
    return success_object(dispute_view(d))


# ===========================================================================
# Settlement files
# ===========================================================================

@app.post("/toll/settlement-files/generate")
def generate_settlement_file():
    require_roles(["SettlementOfficer"])
    b = body()
    require_fields(b, ["from_agency_id", "to_agency_id"])
    from_ag = get_or_404(store.agencies, b["from_agency_id"], "from agency")
    to_ag = get_or_404(store.agencies, b["to_agency_id"], "to agency")

    lines = []
    for t in store.toll_transactions.values():
        if t["status"] != "POSTED" or t["settlement_file_id"] is not None:
            continue
        if t["away_agency_id"] != to_ag["id"]:
            continue
        account = store.accounts.get(t["account_id"])
        if account is None or account["home_agency_id"] != from_ag["id"]:
            continue
        lines.append(t)
    lines.sort(key=lambda t: (t["trip_timestamp"], t["created_at"], t["_seq"]))

    gross = sum(t["charged_amount_cents"] for t in lines)
    fee = sum(round_half_up_cents(
        Decimal(t["charged_amount_cents"]) * Decimal(to_ag["reciprocity_fee_bps"])
        / Decimal(10000)) for t in lines)

    f = {
        "id": new_id(),
        "from_agency_id": from_ag["id"],
        "to_agency_id": to_ag["id"],
        "settlement_day": store.epoch_day,
        "line_count": len(lines),
        "gross_amount_cents": gross,
        "fee_amount_cents": fee,
        "net_amount_cents": gross - fee,
        "exception_count": 0,
        "status": "GENERATED",
    }
    stamp_new(f)
    f["_seq"] = store.next_seq()
    store.settlement_files[f["id"]] = f

    for t in lines:
        t["status"] = "SETTLED"
        t["settlement_file_id"] = f["id"]

    return success_object(settlement_file_view(f), 201)


@app.get("/toll/settlement-files/<settlementFileId>")
def get_settlement_file(settlementFileId):
    require_roles(["SettlementOfficer", "AgencyOperations"])
    f = get_or_404(store.settlement_files, settlementFileId, "settlement file")
    return success_object(settlement_file_view(f))


@app.get("/toll/settlement-files")
def list_settlement_files():
    require_roles(["SettlementOfficer", "AgencyOperations"])
    items = list(store.settlement_files.values())
    for k in ("from_agency_id", "to_agency_id", "status"):
        v = request.args.get(k)
        if v:
            items = [i for i in items if i.get(k) == v]
    return list_response(items, settlement_file_view)


@app.post("/toll/settlement-files/<settlementFileId>/transmit")
def transmit_settlement_file(settlementFileId):
    require_roles(["SettlementOfficer"])
    f = get_or_404(store.settlement_files, settlementFileId, "settlement file")
    if f["status"] != "GENERATED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "File not GENERATED", 409)
    f["status"] = "TRANSMITTED"
    touch(f)
    return success_object(settlement_file_view(f))


@app.post("/toll/settlement-files/<settlementFileId>/acknowledge")
def acknowledge_settlement_file(settlementFileId):
    require_roles(["SettlementOfficer"])
    f = get_or_404(store.settlement_files, settlementFileId, "settlement file")
    if f["status"] != "TRANSMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "File not TRANSMITTED", 409)
    f["status"] = "ACKNOWLEDGED"
    touch(f)
    return success_object(settlement_file_view(f))


@app.post("/toll/settlement-files/<settlementFileId>/flag_exception")
def flag_exception(settlementFileId):
    require_roles(["SettlementOfficer"])
    f = get_or_404(store.settlement_files, settlementFileId, "settlement file")
    if f["status"] != "TRANSMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "File not TRANSMITTED", 409)
    f["status"] = "DISPUTED_SETTLEMENT"
    f["exception_count"] += 1
    touch(f)
    return success_object(settlement_file_view(f))


@app.post("/toll/settlement-files/<settlementFileId>/resolve_exceptions")
def resolve_exceptions(settlementFileId):
    require_roles(["SettlementOfficer"])
    f = get_or_404(store.settlement_files, settlementFileId, "settlement file")
    if f["status"] != "DISPUTED_SETTLEMENT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "File not DISPUTED_SETTLEMENT", 409)
    f["status"] = "ACKNOWLEDGED"
    f["exception_count"] = 0
    touch(f)
    return success_object(settlement_file_view(f))


@app.post("/toll/settlement-files/<settlementFileId>/reconcile")
def reconcile_settlement_file(settlementFileId):
    require_roles(["SettlementOfficer"])
    f = get_or_404(store.settlement_files, settlementFileId, "settlement file")
    if f["status"] != "ACKNOWLEDGED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "File not ACKNOWLEDGED", 409)
    if f["exception_count"] != 0:
        raise ApiError(ERR_SETTLEMENT_HAS_EXCEPTIONS,
                       "Settlement has unresolved exceptions", 409)
    f["status"] = "RECONCILED"
    touch(f)
    return success_object(settlement_file_view(f))


# ===========================================================================
# Plate data agreements
# ===========================================================================

@app.post("/toll/plate-data-agreements")
def create_agreement():
    require_roles(["SettlementOfficer"])
    b = body()
    require_fields(b, ["requesting_agency_id", "providing_agency_id",
                       "effective_from", "effective_to", "covers_states"])
    get_or_404(store.agencies, b["requesting_agency_id"], "requesting agency")
    get_or_404(store.agencies, b["providing_agency_id"], "providing agency")
    ef = parse_iso8601(b["effective_from"])
    et = parse_iso8601(b["effective_to"])
    if ef is None or et is None:
        raise ApiError(ERR_INVALID_REQUEST, "invalid effective window", 400)
    covers = b["covers_states"]
    if not isinstance(covers, list):
        raise ApiError(ERR_INVALID_REQUEST, "covers_states must be a list", 400)
    # overlap check
    for g in store.plate_data_agreements.values():
        if g["status"] != "ACTIVE":
            continue
        if g["requesting_agency_id"] != b["requesting_agency_id"]:
            continue
        if g["providing_agency_id"] != b["providing_agency_id"]:
            continue
        shared = set(g["covers_states"]) & set(covers)
        if shared and ef < g["_et_dt"] and et > g["_ef_dt"]:
            raise ApiError(ERR_AGREEMENT_OVERLAP,
                           "Agreement overlaps existing ACTIVE agreement", 409)
    rec = {
        "id": new_id(),
        "requesting_agency_id": b["requesting_agency_id"],
        "providing_agency_id": b["providing_agency_id"],
        "effective_from": iso3(ef),
        "effective_to": iso3(et),
        "covers_states": list(covers),
        "per_lookup_fee_cents": opt_int(b, "per_lookup_fee_cents", 25),
        "status": "ACTIVE",
        "_ef_dt": ef,
        "_et_dt": et,
    }
    stamp_new(rec)
    rec["_seq"] = store.next_seq()
    store.plate_data_agreements[rec["id"]] = rec
    return success_object(agreement_view(rec), 201)


@app.get("/toll/plate-data-agreements/<agreementId>")
def get_agreement(agreementId):
    require_roles(["SettlementOfficer", "AgencyOperations", "PlateLookupAgent"])
    g = get_or_404(store.plate_data_agreements, agreementId, "agreement")
    return success_object(agreement_view(g))


@app.get("/toll/plate-data-agreements")
def list_agreements():
    require_roles(["SettlementOfficer", "AgencyOperations", "PlateLookupAgent"])
    items = list(store.plate_data_agreements.values())
    for k in ("requesting_agency_id", "providing_agency_id", "status"):
        v = request.args.get(k)
        if v:
            items = [i for i in items if i.get(k) == v]
    return list_response(items, agreement_view)


@app.post("/toll/plate-data-agreements/<agreementId>/revoke")
def revoke_agreement(agreementId):
    require_roles(["SettlementOfficer"])
    g = get_or_404(store.plate_data_agreements, agreementId, "agreement")
    if g["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Agreement not ACTIVE", 409)
    g["status"] = "REVOKED"
    touch(g)
    return success_object(agreement_view(g))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
