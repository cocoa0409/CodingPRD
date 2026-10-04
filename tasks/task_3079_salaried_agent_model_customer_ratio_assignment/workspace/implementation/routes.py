"""Resource routing and the service layer (state machines, cascades, RBAC)."""

from datetime import timedelta

from flask import Blueprint

import calculations as calc
import serializers as ser
from constants import (
    ALLOWED_ENUMS, ASSOCIATE_CAPACITY_LIMIT, LIST_FEE_RATE_CEILING,
    MAX_REFERRAL_FEE_BPS, MIN_LIST_PRICE_CENTS, NO_SHOW_GRACE_MINUTES,
    OPEN_TRANSACTION_STATES, PAGINATION_DEFAULT_LIMIT, ROLES,
)
from db import (
    audit, db, get_agent_or_404, get_client_or_404, get_listing_or_404,
    get_region_or_404, get_referral_or_404, get_survey_or_404,
    get_tour_or_404, get_transaction_or_404, stamp,
)
from errors import ApiError
from http_util import (
    acting_agent_id, as_int, as_number, body, enum, identity, optional_int,
    optional_identity_require_role, pagination, q, require, require_int,
    require_role, require_str, score_in_range,
)
from response import error_response, page_meta, paginate, success
from utils import clock_now, dec, iso_z, new_id, next_seq, parse_iso, set_clock

bp = Blueprint("api", __name__)


# ===========================================================================
# Creation helpers for the two companion rows every Agent carries
# ===========================================================================
def _new_open_client_count(agent_id):
    row = {
        "id": new_id(),
        "agent_id": agent_id,
        "active_client_count": 0,
        "ratio_state": "UNDER_TARGET",
        "created_at": iso_z(clock_now()),
        "updated_at": iso_z(clock_now()),
        "version": 1,
    }
    db.open_client_counts[agent_id] = row
    return row


def _new_lead_capacity(agent):
    row = {
        "id": new_id(),
        "agent_id": agent["id"],
        "region_id": agent["region_id"],
        "current_state": "OPEN",
        "tours_in_week": 0,
        "associate_capacity_used": 0,
        "close_rate": 0.0,
        "graded_transactions": 0,
        "trailing_tours": 0,
        "unassigned_tours": 0,
        "created_at": iso_z(clock_now()),
        "updated_at": iso_z(clock_now()),
        "version": 1,
        "_created_dt": clock_now(),
    }
    db.lead_capacities[agent["id"]] = row
    return row


# ===========================================================================
# Errors
# ===========================================================================
@bp.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@bp.errorhandler(404)
def handle_404(_exc):
    return error_response("ERR_REGION_NOT_FOUND", "No resource matches the requested path.", 404)


@bp.errorhandler(405)
def handle_405(_exc):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed on this path.", 400)


@bp.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)
    return error_response("ERR_INVALID_REQUEST", "The request could not be processed.", 400)


# ===========================================================================
# Shared cascade helpers
# ===========================================================================
def _refresh_agent_derived(agent):
    calc.refresh_open_client_count(agent)
    calc.compute_bonus(agent)
    calc.compute_salary_commitment(agent)
    calc.compute_referral_fee_bps(agent)
    calc.refresh_lead_capacity(agent)
    stamp(agent)


def _verify_region_version(data, region):
    expected = require_int(data, "expected_region_version")
    if region["version"] != expected:
        raise ApiError("ERR_STALE_VERSION", http_status=412)


def _listing_agent_listing_gate(user_id, listing):
    """A listing belongs to its client, so the acting agent must own that client."""
    acting_agent_id(user_id)
    client = db.clients.get(listing["client_id"])
    if client is not None and client.get("assigned_agent_id") != user_id:
        raise ApiError("ERR_FORBIDDEN",
                       "The acting agent does not own the listing's client.", http_status=403)


def _listing_agent_client_gate(user_id, client_id):
    acting_agent_id(user_id)
    client = db.clients.get(client_id)
    if client is not None and client.get("assigned_agent_id") != user_id:
        raise ApiError("ERR_FORBIDDEN",
                       "The acting agent does not own the referenced client.", http_status=403)
    return client


# ===========================================================================
# Region routes
# ===========================================================================
@bp.route("/regions", methods=["POST"])
def create_region():
    optional_identity_require_role("PlatformAdmin")
    data = body()
    name = require_str(data, "name")
    codes = require(data, "service_area_codes")
    if not isinstance(codes, list) or not codes or not all(
            isinstance(c, str) and c.strip() for c in codes):
        raise ApiError("ERR_INVALID_REQUEST", "service_area_codes must be a non-empty array of strings.")
    commission = as_number(require(data, "traditional_commission_pct"), "traditional_commission_pct")
    if not (0 < commission <= 1):
        raise ApiError("ERR_INVALID_REQUEST", "traditional_commission_pct must satisfy 0 < x <= 1.")
    ratio = as_number(require(data, "target_client_ratio"), "target_client_ratio")
    if ratio <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "target_client_ratio must be > 0.")
    capacity = optional_int(data, "capacity", 10)
    enrol = bool(data.get("enrolment_is_required", False))
    # Inert until a region switches it on, exactly like enrolment_is_required:
    # the selector only demands a satisfaction score when the region says so.
    satisfaction_required = bool(data.get("satisfaction_is_required", False))

    row = {
        "id": new_id(),
        "_seq": next_seq(),
        "name": name,
        "service_area_codes": list(codes),
        "traditional_commission_pct": commission,
        "target_client_ratio": ratio,
        "capacity": capacity,
        "enrolment_is_required": enrol,
        "satisfaction_is_required": satisfaction_required,
        "agent_count": 0,
        "clients_in_pipeline": 0,
        "occupancy_pct": 0.0,
        "occupancy_band": "UNDER_TARGET",
        "referral_count": 0,
        "open_referral_count": 0,
        "created_at": iso_z(clock_now()),
        "updated_at": iso_z(clock_now()),
        "version": 1,
        "_created_dt": clock_now(),
    }
    db.regions[row["id"]] = row
    db.region_order.append(row["id"])
    db.ops_run_index[row["id"]] = 0
    db.agent_registry_orders[row["id"]] = []
    return success(ser.region(row), status=201)


@bp.route("/regions/<region_id>", methods=["GET"])
def get_region(region_id):
    optional_identity_require_role("PlatformAdmin", "OperationsCoordinator", "TransactionCoordinator")
    row = get_region_or_404(region_id)
    return success(ser.region(row), status=200)


@bp.route("/regions/<region_id>/agents", methods=["GET"])
def list_region_agents(region_id):
    require_role("PlatformAdmin", "OperationsCoordinator", "TransactionCoordinator")
    get_region_or_404(region_id)
    limit, offset = pagination()
    kind = q("agent_kind")
    status = q("status")
    items = [a for a in _agents_in_region(region_id)]
    items = _filter_enum(items, "agent_kind", kind)
    items = _filter_enum(items, "status", status)
    items.sort(key=lambda a: a["_created_dt"])
    total = items
    page = paginate(total, limit, offset)
    return success([ser.agent(a) for a in page], status=200, is_list=True,
                   page=page_meta(total, limit, offset))


@bp.route("/regions/<region_id>/referrals", methods=["GET"])
def list_region_referrals(region_id):
    require_role("PlatformAdmin", "OperationsCoordinator", "TransactionCoordinator")
    get_region_or_404(region_id)
    limit, offset = pagination()
    settlement = q("settlement_status")
    items = [r for r in db.referrals.values() if r["region_id"] == region_id]
    items = _filter_enum(items, "settlement_status", settlement)
    items.sort(key=lambda r: r["_created_dt"])
    page = paginate(items, limit, offset)
    return success([ser.referral(r) for r in page], status=200, is_list=True,
                   page=page_meta(items, limit, offset))


@bp.route("/regions/<region_id>/activity-audits", methods=["GET"])
def region_audits(region_id):
    require_role("PlatformAdmin", "TransactionCoordinator", "OperationsCoordinator")
    get_region_or_404(region_id)
    limit, offset = pagination()
    items = [a for a in db.audits.values() if a["region_id"] == region_id]
    items.sort(key=lambda a: a["_seq"])
    page = paginate(items, limit, offset)
    return success([ser.activity_audit(a) for a in page], status=200, is_list=True,
                   page=page_meta(items, limit, offset))


@bp.route("/regions/<region_id>/run-ops", methods=["POST"])
def run_ops(region_id):
    require_role("PlatformAdmin")
    region = get_region_or_404(region_id)
    db.ops_run_index[region_id] = db.ops_run_index.get(region_id, 0) + 1
    now = clock_now()

    # 1. Age dispatched surveys through two ops runs.
    for survey in list(db.surveys.values()):
        if survey["agent_id"] not in db.agents:
            continue
        agent = db.agents[survey["agent_id"]]
        if agent["region_id"] != region_id:
            continue
        if survey["response_status"] == "DISPATCHED":
            survey["_ops_seen"] += 1
            if survey["_ops_seen"] >= 2:
                survey["response_status"] = "EXPIRED_DISPATCH"
                stamp(survey)

    # 2. No-show sweep for confirmed tours.
    for tour in list(db.tours.values()):
        if tour["status"] != "CONFIRMED":
            continue
        lead = db.agents.get(tour["lead_agent_id"])
        if lead is None or lead["region_id"] != region_id:
            continue
        deadline = tour["_scheduled_at"] + timedelta(minutes=NO_SHOW_GRACE_MINUTES)
        if now >= deadline:
            tour["status"] = "CANCELLED_NO_SHOW"
            stamp(tour)
            calc.refresh_lead_capacity(lead)

    # 2b. Service-commitment breach sweep. MLS_ONLY (a zero-hour window) is
    #     exempt, so it can never breach.
    for listing in db.listings.values():
        if listing["region_id"] != region_id:
            continue
        if listing.get("_breach_recorded"):
            continue
        if calc.service_window_breached(listing):
            listing["_breach_recorded"] = True
            calc.refresh_service_commitment(listing)
            stamp(listing)
            audit(region_id, "ListingAgreement", listing["id"], "SERVICE_COMMITMENT_BREACH",
                  "First response missed the service-level window; commitment revised to %d hours."
                  % listing["service_commitment_hours"])

    # 3. Recompute every agent's score, then the derived compensation fields.
    for agent in _agents_in_region(region_id):
        agent["satisfaction_score"] = calc.compute_satisfaction_score(agent["id"])
        agent["close_rate"] = calc.compute_close_rate(agent["id"])
        calc.compute_bonus(agent)
        calc.compute_salary_commitment(agent)
        calc.compute_referral_fee_bps(agent)
        agent["open_referral_count"] = region["open_referral_count"]
        calc.refresh_open_client_count(agent)
        calc.refresh_lead_capacity(agent)
        stamp(agent)

    # 4. Region roll-up, then the referral backfill.
    calc.compute_region_rollup(region)
    calc.referral_backfill(region)
    # The backfill draws the ledger down, so the per-agent mirror is refreshed
    # without a second version bump in the same checkpoint.
    for agent in _agents_in_region(region_id):
        agent["open_referral_count"] = region["open_referral_count"]

    # 5. Coordination reconcile sweep for the capacity ledgers.
    pre = calc.transaction_snapshot()
    for agent in _agents_in_region(region_id):
        row = db.lead_capacities.get(agent["id"])
        if row is not None:
            row["close_rate"] = calc.close_rate_over(agent["id"], pre)
            row["graded_transactions"] = calc.graded_count(agent["id"], pre)
            row["trailing_tours"] = calc.trailing_tours(agent["id"])
            stamp(row)

    calc.compute_region_rollup(region)
    region["version"] += 1
    region["updated_at"] = iso_z(now)
    return success(ser.region(region), status=200)


def _agents_in_region(region_id):
    return [a for a in db.agents.values() if a["region_id"] == region_id]


def _filter_enum(items, field, value):
    if value is None:
        return items
    return [i for i in items if i.get(field) == value]


# ===========================================================================
# Agent routes
# ===========================================================================
@bp.route("/agents", methods=["POST"])
def create_agent():
    require_role("PlatformAdmin")
    data = body()
    region_id = require_str(data, "region_id")
    region = get_region_or_404(region_id)
    full_name = require_str(data, "full_name")
    agent_kind = enum(data, "agent_kind", ALLOWED_ENUMS["agent_kind"])
    home_zip = require_str(data, "home_zip")
    base_salary = require_int(data, "base_salary_cents")
    if base_salary <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "base_salary_cents must be > 0.")
    benefits = optional_int(data, "benefits_cents", 0)
    expenses = optional_int(data, "expense_allowance_cents", 0)
    if benefits < 0 or expenses < 0:
        raise ApiError("ERR_INVALID_REQUEST", "benefits and expense allowance must be >= 0.")
    if home_zip not in region["service_area_codes"]:
        raise ApiError("ERR_GEOGRAPHY_MISMATCH", http_status=409)

    agent = {
        "id": new_id(),
        "region_id": region_id,
        "full_name": full_name,
        "agent_kind": agent_kind,
        "home_zip": home_zip,
        "base_salary_cents": base_salary,
        "benefits_cents": benefits,
        "expense_allowance_cents": expenses,
        "satisfaction_score": None,
        "close_rate": 0.0,
        "bonus_pct": 0.0,
        "bonus_cents": 0,
        "salary_commitment_cents": base_salary + benefits + expenses,
        "open_referral_count": 0,
        "referral_fee_bps": 0,
        "status": "ACTIVE",
        "created_at": iso_z(clock_now()),
        "updated_at": iso_z(clock_now()),
        "version": 1,
        "_created_dt": clock_now(),
    }
    db.agents[agent["id"]] = agent
    db.agent_order.append(agent["id"])
    db.agent_registry_orders.setdefault(region_id, []).append(agent["id"])
    _new_open_client_count(agent["id"])
    _new_lead_capacity(agent)

    calc.compute_region_rollup(region)
    calc.compute_referral_fee_bps(agent)
    agent["open_referral_count"] = region["open_referral_count"]
    calc.compute_salary_commitment(agent)
    calc.refresh_lead_capacity(agent)
    region["version"] += 1
    region["updated_at"] = iso_z(clock_now())
    return success(ser.agent(agent), status=201)


@bp.route("/agents/<agent_id>", methods=["GET"])
def get_agent(agent_id):
    require_role(*ROLES)
    agent = get_agent_or_404(agent_id)
    return success(ser.agent(agent), status=200)


@bp.route("/agents", methods=["GET"])
def list_agents():
    require_role(*ROLES)
    limit, offset = pagination()
    items = list(db.agent_order)
    region_id = q("region_id")
    kind = q("agent_kind")
    status = q("status")
    rows = [db.agents[a] for a in items]
    if region_id is not None:
        rows = [r for r in rows if r["region_id"] == region_id]
    rows = _filter_enum(rows, "agent_kind", kind)
    rows = _filter_enum(rows, "status", status)
    rows.sort(key=lambda r: r["_created_dt"])
    page = paginate(rows, limit, offset)
    return success([ser.agent(r) for r in page], status=200, is_list=True,
                   page=page_meta(rows, limit, offset))


@bp.route("/agents/<agent_id>/status", methods=["POST"])
def set_agent_status(agent_id):
    require_role("PlatformAdmin")
    agent = get_agent_or_404(agent_id)
    data = body()
    new_status = enum(data, "new_status", ALLOWED_ENUMS["agent_status"])
    expected = require_int(data, "expected_agent_version")
    if agent["version"] != expected:
        raise ApiError("ERR_STALE_VERSION", http_status=412)
    acknowledged = bool(data.get("enrolment_acknowledged", False))
    region = db.regions.get(agent["region_id"])
    if region is not None and region["enrolment_is_required"] and not acknowledged:
        raise ApiError("ERR_ENROLMENT_NOT_CONFIRMED", http_status=409)

    current = agent["status"]
    if current == new_status:
        pass
    elif current == "ON_LEAVE" and new_status in ("ACTIVE", "AT_CAPACITY"):
        agent["status"] = "ACTIVE"
    elif new_status == "ON_LEAVE":
        agent["status"] = "ON_LEAVE"
    elif new_status == "AT_CAPACITY":
        if current != "ON_LEAVE":
            raise ApiError("ERR_INVALID_STATE", http_status=409)
    else:
        agent["status"] = new_status

    calc.compute_bonus(agent)
    calc.compute_salary_commitment(agent)
    calc.compute_referral_fee_bps(agent)
    calc.refresh_lead_capacity(agent)
    stamp(agent)
    if region is not None:
        calc.compute_region_rollup(region)
        region["version"] += 1
        region["updated_at"] = iso_z(clock_now())
    return success(ser.agent(agent), status=200)


@bp.route("/agents/<agent_id>/open-client-counts", methods=["GET"])
def get_open_client_counts(agent_id):
    require_role(*ROLES)
    agent = get_agent_or_404(agent_id)
    row = db.open_client_counts.get(agent["id"])
    rows = [ser.open_client_count(row)] if row else []
    return success(rows, status=200, is_list=True,
                   page=page_meta(rows, PAGINATION_DEFAULT_LIMIT, 0))


@bp.route("/agents/<agent_id>/lead-capacity", methods=["GET"])
def get_lead_capacity(agent_id):
    require_role(*ROLES)
    agent = get_agent_or_404(agent_id)
    row = db.lead_capacities.get(agent["id"])
    rows = [ser.lead_capacity(row)] if row else []
    return success(rows, status=200, is_list=True,
                   page=page_meta(rows, PAGINATION_DEFAULT_LIMIT, 0))


# ===========================================================================
# Client routes
# ===========================================================================
@bp.route("/clients", methods=["POST"])
def create_client():
    require_role("OperationsCoordinator")
    data = body()
    full_name = require_str(data, "full_name")
    email = require_str(data, "email")
    code = require_str(data, "service_area_code")
    need_kind = enum(data, "need_kind", ALLOWED_ENUMS["need_kind"])
    for existing in db.clients.values():
        if existing["email"] == email:
            raise ApiError("ERR_CLIENT_EMAIL_DUPLICATE", http_status=409)
    region = None
    for candidate in db.region_order:
        row = db.regions[candidate]
        if code in row["service_area_codes"]:
            region = row
            break
    if region is None:
        raise ApiError("ERR_REGION_NOT_FOUND", http_status=404)

    client = {
        "id": new_id(),
        "region_id": region["id"],
        "full_name": full_name,
        "email": email,
        "service_area_code": code,
        "need_kind": need_kind,
        "assigned_agent_id": None,
        "assignment_mode": "UNASSIGNED",
        "assignment_reason": None,
        "status": "UNASSIGNED",
        "created_at": iso_z(clock_now()),
        "updated_at": iso_z(clock_now()),
        "version": 1,
        "_created_dt": clock_now(),
    }
    db.clients[client["id"]] = client
    calc.compute_region_rollup(region)
    region["version"] += 1
    region["updated_at"] = iso_z(clock_now())
    return success(ser.client(client), status=201)


@bp.route("/clients/<client_id>", methods=["GET"])
def get_client(client_id):
    role, user_id = require_role("PlatformAdmin", "OperationsCoordinator",
                                 "TransactionCoordinator", "ListingAgent")
    client = get_client_or_404(client_id)
    if role == "ListingAgent":
        _listing_agent_client_gate(user_id, client_id)
    return success(ser.client(client), status=200)


@bp.route("/clients", methods=["GET"])
def list_clients():
    role, user_id = require_role("PlatformAdmin", "OperationsCoordinator",
                                 "TransactionCoordinator", "ListingAgent")
    limit, offset = pagination()
    rows = list(db.clients.values())
    if role == "ListingAgent" and user_id in db.agents:
        rows = [r for r in rows if r["assigned_agent_id"] == user_id]
    region_id = q("region_id")
    status = q("status")
    code = q("service_area_code")
    need = q("need_kind")
    assigned = q("assigned_agent_id")
    if region_id is not None:
        rows = [r for r in rows if r["region_id"] == region_id]
    if code is not None:
        rows = [r for r in rows if r["service_area_code"] == code]
    if assigned is not None:
        rows = [r for r in rows if r["assigned_agent_id"] == assigned]
    rows = _filter_enum(rows, "status", status)
    rows = _filter_enum(rows, "need_kind", need)
    rows.sort(key=lambda r: r["_created_dt"])
    page = paginate(rows, limit, offset)
    return success([ser.client(r) for r in page], status=200, is_list=True,
                   page=page_meta(rows, limit, offset))


@bp.route("/clients/<client_id>/assign-agent", methods=["POST"])
def assign_agent(client_id):
    require_role("OperationsCoordinator")
    client = get_client_or_404(client_id)
    data = body()
    manual_partner = bool(data.get("manual_partner", False))
    region = get_region_or_404(client["region_id"])

    if client["status"] not in ("UNASSIGNED",):
        raise ApiError("ERR_INVALID_STATE", http_status=409)

    if manual_partner:
        return _route_to_partner(client, region, reason=None)

    # Pre-request occupancy is computed once (§1.3 step 1-3) so the persisted
    # rollup is consistent with the gate's reading.
    calc.compute_region_rollup(region)

    in_geo = [a for a in db.agents.values()
              if a["region_id"] == region["id"] and a["home_zip"] in region["service_area_codes"]]
    if not in_geo:
        client["assignment_reason"] = "NO_IN_GEOGRAPHY_AGENT"
        stamp(client)
        raise ApiError("ERR_NO_ELIGIBLE_AGENT", "No agent has a home_zip inside the region service area.",
                       http_status=409)

    # Lead agents carry clients; associate agents staff tours and are never
    # candidates. Candidates are ranked by load below.
    lead_agents = [a for a in in_geo if a["agent_kind"] == "LEAD"]

    # When no in-geography lead agent exists the selection refuses and the
    # client stays UNASSIGNED with a reasoned `assignment_reason` (§3.3). A
    # client is only sent to a partner on the explicit `manual_partner` path or
    # through the referral-creation operation.
    if not lead_agents:
        client["assignment_reason"] = "ALL_AT_CAPACITY"
        stamp(client)
        region["version"] += 1
        region["updated_at"] = iso_z(clock_now())
        raise ApiError("ERR_NO_ELIGIBLE_AGENT", "Every in-geography agent is at capacity.",
                       http_status=409)

    # The satisfaction-score gate is inert unless the region demands it.
    if region.get("satisfaction_is_required"):
        candidates = [a for a in lead_agents if a.get("satisfaction_score") is not None]
        if not candidates:
            client["assignment_reason"] = "NO_SATISFACTION_SCORE"
            stamp(client)
            raise ApiError("ERR_AGENT_NOT_ELIGIBLE",
                           "No candidate agent carries a satisfaction score.", http_status=409)
    else:
        candidates = lead_agents

    candidates.sort(key=lambda a: (db.open_client_counts[a["id"]]["active_client_count"],
                                   a["_created_dt"]))
    winner = candidates[0]

    client["assigned_agent_id"] = winner["id"]
    client["assignment_mode"] = "ASSIGNED_DIRECT"
    client["assignment_reason"] = "GEOGRAPHY_MATCH"
    client["status"] = "ASSIGNED"
    stamp(client)

    occ = db.open_client_counts[winner["id"]]
    occ["active_client_count"] += 1
    stamp(occ)
    calc.refresh_open_client_count(winner)

    target = dec(region["target_client_ratio"])
    from utils import ceil_ratio
    if occ["active_client_count"] >= ceil_ratio(target):
        winner["status"] = "AT_CAPACITY"
    calc.refresh_lead_capacity(winner)
    _refresh_agent_derived(winner)

    calc.compute_region_rollup(region)
    region["version"] += 1
    region["updated_at"] = iso_z(clock_now())
    return success(ser.client(client), status=200)


def _route_to_partner(client, region, reason):
    calc.compute_region_rollup(region)
    if region["enrolment_is_required"] and region["open_referral_count"] >= region["capacity"]:
        raise ApiError("ERR_REGION_CAPACITY_EXCEEDED", http_status=409)
    if region["open_referral_count"] >= region["capacity"]:
        raise ApiError("ERR_REGION_CAPACITY_EXCEEDED", http_status=409)
    client["status"] = "REFERRED"
    client["assignment_mode"] = "REFERRED_PARTNER"
    client["assigned_agent_id"] = None
    if reason is not None:
        client["assignment_reason"] = reason
    elif client["assignment_reason"] is None:
        client["assignment_reason"] = "MANUAL_PARTNER"
    stamp(client)
    calc.compute_region_rollup(region)
    region["version"] += 1
    region["updated_at"] = iso_z(clock_now())
    return success(ser.client(client), status=200)


# ===========================================================================
# Transaction routes
# ===========================================================================
@bp.route("/clients/<client_id>/transactions", methods=["POST"])
def create_transaction(client_id):
    require_role("TransactionCoordinator")
    client = get_client_or_404(client_id)
    region = get_region_or_404(client["region_id"])

    for tx in db.transactions.values():
        if tx["client_id"] == client_id and tx["coordination_status"] in OPEN_TRANSACTION_STATES:
            raise ApiError("ERR_TRANSACTION_ALREADY_OPEN", http_status=409)

    now = clock_now()
    prior_closed = [tx for tx in db.transactions.values()
                    if tx["client_id"] == client_id and tx["coordination_status"] == "CLOSED"]
    if client["status"] == "CLOSED":
        if not prior_closed:
            raise ApiError("ERR_INVALID_STATE", http_status=409)
        if calc.satisfaction_credit_for_client(client_id) <= 0.0:
            raise ApiError("ERR_INVALID_STATE", http_status=409)

    credit = calc.satisfaction_credit_for_client(client_id)
    lead_agent_id = client["assigned_agent_id"]
    tx = {
        "id": new_id(),
        "client_id": client_id,
        "lead_agent_id": lead_agent_id,
        "coordination_status": "ASSIGNED" if lead_agent_id else "UNASSIGNED",
        "contract_price_cents": 0,
        "closed_at": None,
        "agent_satisfaction_credit": credit,
        "created_at": iso_z(now),
        "updated_at": iso_z(now),
        "version": 1,
        "_created_dt": now,
        "_closed_dt": None,
    }
    db.transactions[tx["id"]] = tx
    client["status"] = "IN_TRANSACTION"
    stamp(client)
    audit(region["id"], "Transaction", tx["id"], "TRANSACTION_CREATED",
          "Transaction opened for client %s." % client_id)
    calc.compute_region_rollup(region)
    region["version"] += 1
    region["updated_at"] = iso_z(now)
    return success(ser.transaction(tx), status=201)


@bp.route("/transactions/<tx_id>", methods=["GET"])
def get_transaction(tx_id):
    require_role("PlatformAdmin", "TransactionCoordinator", "OperationsCoordinator")
    tx = get_transaction_or_404(tx_id)
    return success(ser.transaction(tx), status=200)


@bp.route("/transactions", methods=["GET"])
def list_transactions():
    require_role("PlatformAdmin", "TransactionCoordinator", "OperationsCoordinator")
    limit, offset = pagination()
    rows = list(db.transactions.values())
    lead = q("lead_agent_id")
    client = q("client_id")
    status = q("coordination_status")
    if lead is not None:
        rows = [r for r in rows if r["lead_agent_id"] == lead]
    if client is not None:
        rows = [r for r in rows if r["client_id"] == client]
    rows = _filter_enum(rows, "coordination_status", status)
    rows.sort(key=lambda r: r["_created_dt"])
    page = paginate(rows, limit, offset)
    return success([ser.transaction(r) for r in page], status=200, is_list=True,
                   page=page_meta(rows, limit, offset))


@bp.route("/clients/<client_id>/transactions", methods=["GET"])
def list_client_transactions(client_id):
    require_role("PlatformAdmin", "TransactionCoordinator", "OperationsCoordinator")
    get_client_or_404(client_id)
    limit, offset = pagination()
    status = q("coordination_status")
    rows = [r for r in db.transactions.values() if r["client_id"] == client_id]
    rows = _filter_enum(rows, "coordination_status", status)
    rows.sort(key=lambda r: r["_created_dt"])
    page = paginate(rows, limit, offset)
    return success([ser.transaction(r) for r in page], status=200, is_list=True,
                   page=page_meta(rows, limit, offset))


@bp.route("/transactions/<tx_id>/coordination", methods=["POST"])
def advance_coordination(tx_id):
    require_role("TransactionCoordinator")
    tx = get_transaction_or_404(tx_id)
    data = body()
    target = enum(data, "coordination_status", ALLOWED_ENUMS["coordination_status"])

    allowed = {
        "UNASSIGNED": ("ASSIGNED",),
        "ASSIGNED": ("REVIEW",),
        "REVIEW": ("ASSIGNED", "CLOSED"),
    }
    current = tx["coordination_status"]
    if current not in allowed or target not in allowed[current]:
        raise ApiError("ERR_INVALID_STATE", http_status=409)

    contract_price = data.get("contract_price_cents")
    if contract_price is not None:
        tx["contract_price_cents"] = as_int(contract_price, "contract_price_cents")

    now = clock_now()
    # Pre-write set for the pinned reconcile ordering.
    pre_transactions = calc.transaction_snapshot()
    client = db.clients.get(tx["client_id"])
    agent = db.agents.get(tx["lead_agent_id"]) if tx["lead_agent_id"] else None
    region = db.regions.get(client["region_id"]) if client else None

    if target == "CLOSED":
        if tx["contract_price_cents"] <= 0:
            raise ApiError("ERR_CONTRACT_PRICE_MISSING", http_status=409)
        _close_transaction(tx, client, agent, region, now, pre_transactions)
    else:
        tx["coordination_status"] = target
        stamp(tx)
        if region is not None:
            audit(region["id"], "Transaction", tx["id"], "TRANSACTION_STATUS_CHANGED",
                  "Transaction coordination moved to %s." % target)
        if agent is not None:
            calc.compute_bonus(agent)
            calc.compute_salary_commitment(agent)
            _reconcile_lead_capacity(agent, pre_transactions)
    return success(ser.transaction(tx), status=200)


def _reconcile_lead_capacity(agent, snapshot=None):
    """transaction_coordination_reconcile, PINNED ordering: the sweep reads the
    agent's transactions as observed at request entry (the frozen pre-write
    snapshot), then the request's own transition is applied and the derived
    fields are written once. A post-write sweep would count one transaction more."""
    if snapshot is None:
        snapshot = calc.transaction_snapshot()
    row = db.lead_capacities.get(agent["id"])
    if row is None:
        return
    calc.refresh_lead_capacity(agent)
    row["graded_transactions"] = calc.graded_count(agent["id"], snapshot)
    row["close_rate"] = calc.close_rate_over(agent["id"], snapshot)
    row["trailing_tours"] = calc.trailing_tours(agent["id"])
    stamp(row)


def _release_capacity(client, agent, region, now):
    """Drop the client's originating OpenClientCount and cascade the posture."""
    if agent is None:
        return
    occ = db.open_client_counts.get(agent["id"])
    if occ is None:
        return
    occ["active_client_count"] = max(0, occ["active_client_count"] - 1)
    stamp(occ)
    calc.refresh_open_client_count(agent)
    from utils import ceil_ratio
    target = dec(region["target_client_ratio"]) if region else dec(1)
    if occ["active_client_count"] < ceil_ratio(target) and agent["status"] == "AT_CAPACITY":
        agent["status"] = "ACTIVE"
    calc.refresh_lead_capacity(agent)
    audit(region["id"] if region else None, "OpenClientCount", occ["id"],
          "CLIENT_CAPACITY_RELEASED",
          "Active client count released to %d." % occ["active_client_count"])
    if region is not None:
        calc.compute_region_rollup(region)


def _close_transaction(tx, client, agent, region, now, snapshot=None):
    tx["coordination_status"] = "CLOSED"
    tx["closed_at"] = iso_z(now)
    tx["_closed_dt"] = now
    stamp(tx)
    if region is not None:
        audit(region["id"], "Transaction", tx["id"], "TRANSACTION_STATUS_CHANGED",
              "Transaction closed.")
    if client is not None:
        client["status"] = "CLOSED"
        stamp(client)
    _release_capacity(client, agent, region, now)
    if client is not None:
        listing = _listing_for_client(client["id"])
        if listing is not None and listing["status"] != "CLOSED":
            listing["status"] = "CLOSED"
            calc.compute_listing_fees(listing)
            stamp(listing)
    if agent is not None:
        calc.compute_bonus(agent)
        calc.compute_salary_commitment(agent)
        _reconcile_lead_capacity(agent, snapshot)
    if region is not None:
        region["version"] += 1
        region["updated_at"] = iso_z(now)


def _listing_for_client(client_id):
    for listing in db.listings.values():
        if listing["client_id"] == client_id and listing["status"] != "WITHDRAWN":
            return listing
    return None


@bp.route("/transactions/<tx_id>/close", methods=["POST"])
def close_transaction(tx_id):
    require_role("TransactionCoordinator")
    tx = get_transaction_or_404(tx_id)
    if tx["coordination_status"] != "REVIEW":
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    if tx["contract_price_cents"] <= 0:
        raise ApiError("ERR_CONTRACT_PRICE_MISSING", http_status=409)
    client = db.clients.get(tx["client_id"])
    agent = db.agents.get(tx["lead_agent_id"]) if tx["lead_agent_id"] else None
    region = db.regions.get(client["region_id"]) if client else None
    pre_transactions = calc.transaction_snapshot()
    _close_transaction(tx, client, agent, region, clock_now(), pre_transactions)
    return success(ser.transaction(tx), status=200)


@bp.route("/clients/<client_id>/transactions/<tx_id>/close", methods=["POST"])
def close_client_transaction(client_id, tx_id):
    require_role("TransactionCoordinator")
    get_client_or_404(client_id)
    tx = db.transactions.get(tx_id)
    if tx is None or tx["client_id"] != client_id:
        raise ApiError("ERR_TRANSACTION_NOT_FOUND", http_status=404)
    if tx["coordination_status"] not in ("ASSIGNED", "REVIEW"):
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    client = db.clients.get(tx["client_id"])
    agent = db.agents.get(tx["lead_agent_id"]) if tx["lead_agent_id"] else None
    region = db.regions.get(client["region_id"]) if client else None
    pre_transactions = calc.transaction_snapshot()
    _close_transaction(tx, client, agent, region, clock_now(), pre_transactions)
    return success(ser.transaction(tx), status=200)


@bp.route("/transactions/<tx_id>/cancel", methods=["POST"])
def cancel_transaction(tx_id):
    require_role("TransactionCoordinator")
    tx = get_transaction_or_404(tx_id)
    current = tx["coordination_status"]
    if current not in ("ASSIGNED", "REVIEW"):
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    if tx["contract_price_cents"] > 0:
        raise ApiError("ERR_INVALID_STATE", "A transaction that carries a contract price cannot be cancelled.",
                       http_status=409)
    now = clock_now()
    client = db.clients.get(tx["client_id"])
    agent = db.agents.get(tx["lead_agent_id"]) if tx["lead_agent_id"] else None
    region = db.regions.get(client["region_id"]) if client else None
    tx["coordination_status"] = "CANCELLED"
    stamp(tx)
    if region is not None:
        audit(region["id"], "Transaction", tx["id"], "TRANSACTION_STATUS_CHANGED",
              "Transaction cancelled.")
    _release_capacity(client, agent, region, now)
    if client is not None:
        still_open = any(t["client_id"] == client["id"]
                         and t["coordination_status"] in OPEN_TRANSACTION_STATES
                         and t["id"] != tx["id"]
                         for t in db.transactions.values())
        if not still_open:
            client["status"] = "UNASSIGNED"
        stamp(client)
    if agent is not None:
        calc.compute_bonus(agent)
        calc.compute_salary_commitment(agent)
        _reconcile_lead_capacity(agent)
    return success(ser.transaction(tx), status=200)


# ===========================================================================
# Survey routes
# ===========================================================================
@bp.route("/transactions/<tx_id>/surveys", methods=["POST"])
def create_survey(tx_id):
    require_role("TransactionCoordinator")
    get_transaction_or_404(tx_id)
    data = body()
    agent_id = require_str(data, "agent_id")
    agent = get_agent_or_404(agent_id)
    score = data.get("score")
    now = clock_now()

    if score is None:
        survey = {
            "id": new_id(), "transaction_id": tx_id, "agent_id": agent_id, "score": None,
            "response_status": "DISPATCHED", "bonus_eligible": False,
            "dispatched_at": iso_z(now), "responded_at": None,
            "created_at": iso_z(now), "updated_at": iso_z(now), "version": 1,
            "_created_dt": now, "_ops_seen": 0,
        }
    else:
        value = score_in_range(score, "score")
        survey = {
            "id": new_id(), "transaction_id": tx_id, "agent_id": agent_id, "score": value,
            "response_status": "RESPONDED", "bonus_eligible": True,
            "dispatched_at": iso_z(now), "responded_at": iso_z(now),
            "created_at": iso_z(now), "updated_at": iso_z(now), "version": 1,
            "_created_dt": now, "_ops_seen": 0,
        }
    db.surveys[survey["id"]] = survey
    if survey["response_status"] == "RESPONDED":
        calc.compute_bonus(agent)
        calc.compute_salary_commitment(agent)
        if agent["region_id"] in db.regions:
            region = db.regions[agent["region_id"]]
            calc.compute_region_rollup(region)
            region["version"] += 1
    return success(ser.survey(survey), status=201)


@bp.route("/transactions/<tx_id>/surveys", methods=["GET"])
def list_transaction_surveys(tx_id):
    require_role("PlatformAdmin", "TransactionCoordinator", "OperationsCoordinator")
    get_transaction_or_404(tx_id)
    rows = [s for s in db.surveys.values() if s["transaction_id"] == tx_id]
    rows.sort(key=lambda s: s["_created_dt"])
    page = paginate(rows, PAGINATION_DEFAULT_LIMIT, 0)
    return success([ser.survey(s) for s in page], status=200, is_list=True,
                   page=page_meta(rows, PAGINATION_DEFAULT_LIMIT, 0))


@bp.route("/surveys/<survey_id>/respond", methods=["POST"])
def respond_survey(survey_id):
    require_role("TransactionCoordinator")
    survey = get_survey_or_404(survey_id)
    data = body()
    value = score_in_range(require(data, "score"), "score")
    if survey["response_status"] not in ("DISPATCHED", "EXPIRED_DISPATCH"):
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    survey["score"] = value
    survey["response_status"] = "RESPONDED"
    survey["responded_at"] = iso_z(clock_now())
    stamp(survey)
    agent = db.agents.get(survey["agent_id"])
    if agent is not None:
        calc.compute_bonus(agent)
        calc.compute_salary_commitment(agent)
        calc.refresh_lead_capacity(agent)
        region = db.regions.get(agent["region_id"])
        if region is not None:
            calc.compute_region_rollup(region)
            region["version"] += 1
    return success(ser.survey(survey), status=200)


@bp.route("/surveys/<survey_id>", methods=["GET"])
def get_survey(survey_id):
    require_role("PlatformAdmin", "TransactionCoordinator", "OperationsCoordinator")
    survey = get_survey_or_404(survey_id)
    return success(ser.survey(survey), status=200)


@bp.route("/surveys", methods=["GET"])
def list_surveys():
    require_role("PlatformAdmin", "TransactionCoordinator", "OperationsCoordinator")
    limit, offset = pagination()
    rows = list(db.surveys.values())
    agent_id = q("agent_id")
    tx_id = q("transaction_id")
    status = q("response_status")
    if agent_id is not None:
        rows = [r for r in rows if r["agent_id"] == agent_id]
    if tx_id is not None:
        rows = [r for r in rows if r["transaction_id"] == tx_id]
    rows = _filter_enum(rows, "response_status", status)
    rows.sort(key=lambda r: r["_created_dt"])
    page = paginate(rows, limit, offset)
    return success([ser.survey(r) for r in page], status=200, is_list=True,
                   page=page_meta(rows, limit, offset))


# ===========================================================================
# Listing routes
# ===========================================================================
@bp.route("/listing-agreements", methods=["POST"])
def create_listing():
    role, user_id = require_role("ListingAgent")
    data = body()
    client_id = require_str(data, "client_id")
    client = get_client_or_404(client_id)
    _listing_agent_client_gate(user_id, client_id)
    list_price = require_int(data, "list_price_cents")
    rate = as_number(require(data, "list_fee_rate_pct"), "list_fee_rate_pct")
    tier = enum(data, "service_tier", ALLOWED_ENUMS["service_tier"])
    region = get_region_or_404(client["region_id"])
    _verify_region_version(data, region)

    if client["need_kind"] != "SELL":
        raise ApiError("ERR_LISTING_CLIENT_MISMATCH", http_status=409)
    if list_price < MIN_LIST_PRICE_CENTS:
        raise ApiError("ERR_LIST_PRICE_OUT_OF_BAND", http_status=409)
    if rate <= 0 or dec(rate) > LIST_FEE_RATE_CEILING:
        raise ApiError("ERR_LIST_FEE_RATE_EXCEEDED", http_status=409)

    now = clock_now()
    listing = {
        "id": new_id(),
        "region_id": region["id"],
        "client_id": client_id,
        "list_price_cents": list_price,
        "list_fee_rate_pct": rate,
        "service_tier": tier,
        "traditional_listing_fee_cents": 0,
        "partner_referral_fee_cents": 0,
        "gross_listing_fee_cents": 0,
        "savings_amount_cents": 0,
        "savings_pct": 0.0,
        "final_listing_fee_cents": 0,
        "service_commitment_hours": 0,
        "posted_at": None,
        "first_response_at": None,
        "status": "DRAFT",
        "created_at": iso_z(now), "updated_at": iso_z(now), "version": 1,
        "_created_dt": now,
        "_breach_recorded": False,
        "window_days": None,
        "registered_from": None,
        "registered_to": None,
    }
    calc.compute_listing_fees(listing)
    listing["final_listing_fee_cents"] = listing["gross_listing_fee_cents"]
    db.listings[listing["id"]] = listing
    region["version"] += 1
    region["updated_at"] = iso_z(now)
    return success(ser.listing(listing), status=201)


@bp.route("/listing-agreements/<listing_id>", methods=["GET"])
def get_listing(listing_id):
    require_role("PlatformAdmin", "ListingAgent", "OperationsCoordinator")
    listing = get_listing_or_404(listing_id)
    return success(ser.listing(listing), status=200)


@bp.route("/listing-agreements", methods=["GET"])
def list_listings():
    require_role("PlatformAdmin", "ListingAgent", "OperationsCoordinator")
    limit, offset = pagination()
    rows = list(db.listings.values())
    region_id = q("region_id")
    client_id = q("client_id")
    status = q("status")
    if region_id is not None:
        rows = [r for r in rows if r["region_id"] == region_id]
    if client_id is not None:
        rows = [r for r in rows if r["client_id"] == client_id]
    rows = _filter_enum(rows, "status", status)
    rows.sort(key=lambda r: r["_created_dt"])
    page = paginate(rows, limit, offset)
    return success([ser.listing(r) for r in page], status=200, is_list=True,
                   page=page_meta(rows, limit, offset))


@bp.route("/listing-agreements/<listing_id>/publish", methods=["POST"])
def publish_listing(listing_id):
    require_role("ListingAgent")
    listing = get_listing_or_404(listing_id)
    _, _uid = identity()
    _listing_agent_listing_gate(_uid, listing)
    if listing["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    client = get_client_or_404(listing["client_id"])
    if client["status"] not in ("UNASSIGNED", "ASSIGNED", "IN_TRANSACTION"):
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    if listing["gross_listing_fee_cents"] <= 0:
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    now = clock_now()
    listing["status"] = "ACTIVE"
    listing["posted_at"] = iso_z(now)
    calc.refresh_service_commitment(listing)
    stamp(listing)
    region = db.regions.get(listing["region_id"])
    if region is not None:
        calc.compute_region_rollup(region)
        region["version"] += 1
        region["updated_at"] = iso_z(now)
    return success(ser.listing(listing), status=200)


@bp.route("/listing-agreements/<listing_id>/accept-offer", methods=["POST"])
def accept_offer(listing_id):
    require_role("ListingAgent")
    listing = get_listing_or_404(listing_id)
    _, _uid = identity()
    _listing_agent_listing_gate(_uid, listing)
    data = body()
    price = require_int(data, "contract_price_cents")
    if listing["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    if price < 1:
        raise ApiError("ERR_INVALID_REQUEST", "contract_price_cents must be >= 1.")
    listing["first_response_at"] = iso_z(clock_now())
    listing["_last_contract_price_cents"] = price
    calc.refresh_service_commitment(listing)
    listing["status"] = "UNDER_CONTRACT"
    referral = calc.referral_for_client(listing["client_id"])
    if listing["client_id"] is not None:
        client_for_listing = db.clients.get(listing["client_id"])
        if client_for_listing is not None:
            _propagate_contract_price(client_for_listing["id"], price)
            # A registered referral starts at PENDING; the first contract price
            # for the client is what turns it into COMPUTED.
            if referral is None:
                referral = _auto_compute_referrals_for_client(client_for_listing, price, listing)
    if referral is not None:
        referral["_contract_price_cents"] = price
        calc.compute_referral_split(referral, price)
        if referral["settlement_status"] == "PENDING":
            referral["settlement_status"] = "COMPUTED"
        stamp(referral)
    calc.compute_listing_fees(listing)
    stamp(listing)
    return success(ser.listing(listing), status=200)


@bp.route("/listing-agreements/<listing_id>/revert-to-active", methods=["POST"])
def revert_listing(listing_id):
    require_role("ListingAgent")
    listing = get_listing_or_404(listing_id)
    _, _uid = identity()
    _listing_agent_listing_gate(_uid, listing)
    if listing["status"] != "UNDER_CONTRACT":
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    client_id = listing["client_id"]
    if any(tx["client_id"] == client_id and tx["coordination_status"] == "CLOSED"
           for tx in db.transactions.values()):
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    listing["status"] = "ACTIVE"
    referral = calc.referral_for_client(client_id)
    if referral is not None:
        referral["settlement_status"] = "PENDING"
        stamp(referral)
    calc.compute_listing_fees(listing)
    listing["final_listing_fee_cents"] = listing["gross_listing_fee_cents"]
    stamp(listing)
    return success(ser.listing(listing), status=200)


@bp.route("/listing-agreements/<listing_id>/withdraw", methods=["POST"])
def withdraw_listing(listing_id):
    require_role("ListingAgent")
    listing = get_listing_or_404(listing_id)
    _, _uid = identity()
    _listing_agent_listing_gate(_uid, listing)
    if listing["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    listing["status"] = "WITHDRAWN"
    stamp(listing)
    referral = calc.referral_for_client(listing["client_id"])
    if referral is not None:
        referral["settlement_status"] = "PENDING"
        stamp(referral)
    return success(ser.listing(listing), status=200)


@bp.route("/listing-agreements/<listing_id>/register", methods=["POST"])
def register_listing(listing_id):
    require_role("ListingAgent")
    listing = get_listing_or_404(listing_id)
    _, _uid = identity()
    _listing_agent_listing_gate(_uid, listing)
    data = body()
    acknowledged = bool(data.get("enrolment_acknowledged", False))
    window_days = require_int(data, "window_days")
    if window_days <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "window_days must be > 0.")
    region = db.regions.get(listing["region_id"])
    if region is not None and region["enrolment_is_required"] and not acknowledged:
        raise ApiError("ERR_ENROLMENT_NOT_CONFIRMED", http_status=409)
    listing["window_days"] = window_days
    listing["registered_from"] = iso_z(clock_now())
    listing["registered_to"] = iso_z(clock_now() + timedelta(days=window_days))
    stamp(listing)
    if region is not None:
        region["version"] += 1
        region["updated_at"] = iso_z(clock_now())
    return success(ser.listing(listing), status=200)


# ===========================================================================
# Tour routes
# ===========================================================================
@bp.route("/tours", methods=["POST"])
def create_tour():
    require_role("OperationsCoordinator")
    data = body()
    client_id = require_str(data, "client_id")
    client = get_client_or_404(client_id)
    scheduled_raw = require(data, "scheduled_at")
    scheduled = parse_iso(scheduled_raw)
    if scheduled is None:
        raise ApiError("ERR_INVALID_REQUEST", "scheduled_at must be an ISO 8601 instant.")
    instructions = require_str(data, "access_instructions")
    if not (1 <= len(instructions) <= 500):
        raise ApiError("ERR_INVALID_REQUEST", "access_instructions must be 1..500 characters.")
    associate_id = data.get("associate_agent_id")
    if associate_id is not None:
        associate_id = str(associate_id)
        if associate_id not in db.agents:
            raise ApiError("ERR_AGENT_NOT_FOUND", http_status=404)

    now = clock_now()
    lead_agent_id = client["assigned_agent_id"]
    if lead_agent_id is None:
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    if client["status"] not in ("ASSIGNED", "IN_TRANSACTION"):
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    if scheduled <= now:
        raise ApiError("ERR_INVALID_REQUEST", "scheduled_at must be later than the logical clock.")

    for tour in db.tours.values():
        if tour["lead_agent_id"] != lead_agent_id:
            continue
        if tour["status"] not in ("ACCESS_PENDING", "CONFIRMED", "COMPLETED"):
            continue
        start = tour["_scheduled_at"]
        end = start + timedelta(minutes=60)
        if start < scheduled + timedelta(minutes=60) and scheduled < end:
            raise ApiError("ERR_TOUR_SCHEDULE_CONFLICT", http_status=409)

    region = get_region_or_404(client["region_id"])
    lead = db.agents.get(lead_agent_id)
    threshold = calc.tour_block_threshold(region)
    unsupported = calc.uni_serviced_tour_count(lead_agent_id)
    if unsupported >= threshold and associate_id is None:
        raise ApiError("ERR_ASSOCIATE_AGENT_REQUIRED", http_status=409)

    listing = _listing_for_client(client_id)
    tour = {
        "id": new_id(),
        "lead_agent_id": lead_agent_id,
        "client_id": client_id,
        "listing_agreement_id": listing["id"] if listing else None,
        "associate_agent_id": associate_id,
        "access_instructions": instructions,
        "access_code": "KX-%06d" % (next_seq() % 1000000),
        "status": "ACCESS_PENDING",
        "feedback_rating": None,
        "feedback_notes": None,
        "tours_next_36_hours": calc.tours_next_36_hours(scheduled),
        "created_at": iso_z(now), "updated_at": iso_z(now), "version": 1,
        "_created_dt": now,
        "_scheduled_at": scheduled,
        "_access_code_issued": True,
    }
    db.tours[tour["id"]] = tour

    if lead is not None:
        # Workload safety: a staffing push that would carry the associate past
        # the limit is force-routed and the associate is cleared instead.
        if associate_id is not None \
                and calc.associate_capacity_used(lead["id"]) >= ASSOCIATE_CAPACITY_LIMIT:
            tour["associate_agent_id"] = None
        calc.refresh_lead_capacity(lead)
    return success(ser.tour(tour), status=201)


@bp.route("/tours", methods=["GET"])
def list_tours():
    require_role("PlatformAdmin", "OperationsCoordinator", "AssociateAgent")
    limit, offset = pagination()
    rows = list(db.tours.values())
    for field in ("lead_agent_id", "client_id", "status", "listing_agreement_id", "associate_agent_id"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    rows.sort(key=lambda r: r["_created_dt"])
    page = paginate(rows, limit, offset)
    return success([ser.tour(r) for r in page], status=200, is_list=True,
                   page=page_meta(rows, limit, offset))


@bp.route("/tours/<tour_id>", methods=["GET"])
def get_tour(tour_id):
    require_role("PlatformAdmin", "OperationsCoordinator", "AssociateAgent")
    tour = get_tour_or_404(tour_id)
    return success(ser.tour(tour), status=200)


@bp.route("/tours/<tour_id>/confirm", methods=["POST"])
def confirm_tour(tour_id):
    require_role("AssociateAgent")
    tour = get_tour_or_404(tour_id)
    if tour["status"] != "ACCESS_PENDING":
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    now = clock_now()
    if now < calc.access_release_at(tour["_scheduled_at"]):
        raise ApiError("ERR_ACCESS_WINDOW_NOT_OPEN", http_status=409)
    lead = db.agents.get(tour["lead_agent_id"])
    if lead is not None:
        region = db.regions.get(lead["region_id"])
        if region is not None:
            threshold = calc.tour_block_threshold(region)
            if calc.uni_serviced_tour_count(lead["id"]) >= threshold \
                    and tour["associate_agent_id"] is None:
                raise ApiError("ERR_ASSOCIATE_AGENT_REQUIRED", http_status=409)
    tour["status"] = "CONFIRMED"
    stamp(tour)
    if lead is not None:
        calc.refresh_lead_capacity(lead)
    return success(ser.tour(tour), status=200)


@bp.route("/tours/<tour_id>/complete", methods=["POST"])
def complete_tour(tour_id):
    require_role("AssociateAgent")
    tour = get_tour_or_404(tour_id)
    if tour["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    data = body()
    rating = score_in_range(require(data, "feedback_rating"), "feedback_rating")
    notes = data.get("feedback_notes")
    tour["feedback_rating"] = rating
    tour["feedback_notes"] = notes
    tour["status"] = "COMPLETED"
    stamp(tour)

    lead = db.agents.get(tour["lead_agent_id"])
    if lead is None:
        return success(ser.tour(tour), status=200)

    tx = _latest_transaction_for_client(tour["client_id"])
    now = clock_now()
    if tx is not None:
        survey = {
            "id": new_id(), "transaction_id": tx["id"], "agent_id": lead["id"], "score": rating,
            "response_status": "RESPONDED", "bonus_eligible": True,
            "dispatched_at": iso_z(now), "responded_at": iso_z(now),
            "created_at": iso_z(now), "updated_at": iso_z(now), "version": 1,
            "_created_dt": now, "_ops_seen": 0,
        }
        db.surveys[survey["id"]] = survey

    calc.compute_bonus(lead)
    calc.compute_salary_commitment(lead)
    calc.refresh_lead_capacity(lead)
    region = db.regions.get(lead["region_id"])
    if region is not None:
        calc.compute_region_rollup(region)
        region["version"] += 1
    return success(ser.tour(tour), status=200)


def _latest_transaction_for_client(client_id):
    rows = [t for t in db.transactions.values() if t["client_id"] == client_id]
    if not rows:
        return None
    rows.sort(key=lambda t: t["_created_dt"], reverse=True)
    return rows[0]


@bp.route("/tours/<tour_id>/no-show", methods=["POST"])
def no_show_tour(tour_id):
    require_role("AssociateAgent")
    tour = get_tour_or_404(tour_id)
    if tour["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    tour["status"] = "CANCELLED_NO_SHOW"
    stamp(tour)
    lead = db.agents.get(tour["lead_agent_id"])
    if lead is not None:
        calc.refresh_lead_capacity(lead)
    return success(ser.tour(tour), status=200)


@bp.route("/tours/<tour_id>/cancel", methods=["POST"])
def cancel_tour(tour_id):
    require_role("OperationsCoordinator")
    tour = get_tour_or_404(tour_id)
    if tour["status"] not in ("ACCESS_PENDING", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    tour["status"] = "CANCELLED"
    stamp(tour)
    lead = db.agents.get(tour["lead_agent_id"])
    if lead is not None:
        calc.refresh_lead_capacity(lead)
    return success(ser.tour(tour), status=200)


# ===========================================================================
# Referral routes
# ===========================================================================
@bp.route("/referrals", methods=["POST"])
def create_referral():
    require_role("OperationsCoordinator")
    data = body()
    client_id = require_str(data, "client_id")
    client = get_client_or_404(client_id)
    partner_name = require_str(data, "partner_name")
    bps = require_int(data, "referral_fee_bps")
    split_policy = enum(data, "split_policy", ALLOWED_ENUMS["split_policy"])
    region = get_region_or_404(client["region_id"])
    _verify_region_version(data, region)

    if bps <= 0 or bps > MAX_REFERRAL_FEE_BPS:
        raise ApiError("ERR_REFERRAL_FEE_EXCEEDED", http_status=409)
    calc.compute_region_rollup(region)
    if region["enrolment_is_required"] and region["open_referral_count"] >= region["capacity"]:
        raise ApiError("ERR_REGION_CAPACITY_EXCEEDED", http_status=409)
    if region["open_referral_count"] >= region["capacity"]:
        raise ApiError("ERR_REGION_CAPACITY_EXCEEDED", http_status=409)

    # The basis is the client's contract price when one is already recorded.
    contract_price = _client_contract_price(client_id)
    now = clock_now()
    referral = {
        "id": new_id(),
        "region_id": region["id"],
        "client_id": client_id,
        "partner_name": partner_name,
        "referral_fee_bps": bps,
        "referral_fee_cents": 0,
        "settlement_status": "PENDING",
        "split_policy": split_policy,
        "partner_cents": 0,
        "house_cents": 0,
        "settlement_reference": None,
        "created_at": iso_z(now), "updated_at": iso_z(now), "version": 1,
        "_created_dt": now,
        "_contract_price_cents": contract_price,
    }
    calc.compute_referral_split(referral, contract_price)
    db.referrals[referral["id"]] = referral

    if client["status"] != "REFERRED":
        client["status"] = "REFERRED"
        client["assignment_mode"] = "REFERRED_PARTNER"
        # An overflow client never had an agent; a client that was already
        # assigned keeps the agent it was routed to.
        if not client.get("assignment_reason"):
            client["assignment_reason"] = "MANUAL_PARTNER"
        stamp(client)

    calc.compute_region_rollup(region)
    _sync_referral_ledger(region)
    region["version"] += 1
    region["updated_at"] = iso_z(now)
    return success(ser.referral(referral), status=201)


def _client_contract_price(client_id):
    price = 0
    for listing in db.listings.values():
        if listing["client_id"] == client_id:
            price = max(price, listing.get("_last_contract_price_cents", 0) or 0)
    for tx in db.transactions.values():
        if tx["client_id"] == client_id:
            price = max(price, tx["contract_price_cents"] or 0)
    return price


def _propagate_contract_price(client_id, price):
    """A contract price is shared across the client's listing and transactions."""
    for listing in db.listings.values():
        if listing["client_id"] == client_id:
            listing["_last_contract_price_cents"] = price
    for tx in db.transactions.values():
        if tx["client_id"] == client_id and (tx["contract_price_cents"] or 0) < price:
            tx["contract_price_cents"] = price


def _auto_compute_referrals_for_client(client, price, listing):
    """First contract price for a referred client moves its PENDING referral to
    COMPUTED and re-derives the split, then the listing fee follows."""
    computed = None
    for referral in db.referrals.values():
        if referral["client_id"] != client["id"]:
            continue
        if referral["settlement_status"] == "SETTLED":
            continue
        referral["_contract_price_cents"] = price
        calc.compute_referral_split(referral, price)
        if referral["settlement_status"] == "PENDING":
            referral["settlement_status"] = "COMPUTED"
        stamp(referral)
        computed = referral
    return computed


def _sync_referral_ledger(region):
    for agent in _agents_in_region(region["id"]):
        agent["open_referral_count"] = region["open_referral_count"]


@bp.route("/referrals/<referral_id>", methods=["GET"])
def get_referral(referral_id):
    require_role("PlatformAdmin", "OperationsCoordinator", "TransactionCoordinator")
    referral = get_referral_or_404(referral_id)
    return success(ser.referral(referral), status=200)


@bp.route("/referrals", methods=["GET"])
def list_referrals():
    require_role("PlatformAdmin", "OperationsCoordinator", "TransactionCoordinator")
    limit, offset = pagination()
    rows = list(db.referrals.values())
    region_id = q("region_id")
    client_id = q("client_id")
    settlement = q("settlement_status")
    if region_id is not None:
        rows = [r for r in rows if r["region_id"] == region_id]
    if client_id is not None:
        rows = [r for r in rows if r["client_id"] == client_id]
    rows = _filter_enum(rows, "settlement_status", settlement)
    rows.sort(key=lambda r: r["_created_dt"])
    page = paginate(rows, limit, offset)
    return success([ser.referral(r) for r in page], status=200, is_list=True,
                   page=page_meta(rows, limit, offset))


@bp.route("/referrals/<referral_id>/reconcile", methods=["POST"])
def reconcile_referral(referral_id):
    require_role("TransactionCoordinator")
    referral = get_referral_or_404(referral_id)
    data = body()
    if referral["settlement_status"] == "SETTLED":
        raise ApiError("ERR_INVALID_STATE", http_status=409)

    supplied = data.get("contract_price_cents")
    if supplied is not None:
        price = as_int(supplied, "contract_price_cents")
    else:
        price = referral["_contract_price_cents"]
    if price <= 0:
        raise ApiError("ERR_NO_CONTRACT_PRICE",
                       "No contract price exists for the referred client.", http_status=409)

    referral["_contract_price_cents"] = price
    calc.compute_referral_split(referral, price)
    # PENDING -> COMPUTED on the first derivation; an already-COMPUTED referral
    # is re-derived in place when a superseding price arrives.
    if referral["settlement_status"] == "PENDING":
        referral["settlement_status"] = "COMPUTED"
    referral["recomputed_times"] = referral.get("recomputed_times", 0) + 1
    stamp(referral)

    for row in db.listings.values():
        if row["client_id"] == referral["client_id"]:
            calc.compute_listing_fees(row)
            stamp(row)
    region = db.regions.get(referral["region_id"])
    if region is not None:
        calc.compute_region_rollup(region)
        region["version"] += 1
    return success(ser.referral(referral), status=200)


@bp.route("/referrals/<referral_id>/settle", methods=["POST"])
def settle_referral(referral_id):
    require_role("TransactionCoordinator")
    referral = get_referral_or_404(referral_id)
    data = body()
    reference = require_str(data, "settlement_reference")
    if referral["settlement_status"] != "COMPUTED":
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    referral["settlement_reference"] = reference
    referral["settlement_status"] = "SETTLED"
    stamp(referral)
    region = db.regions.get(referral["region_id"])
    if region is not None:
        calc.compute_region_rollup(region)
        region["version"] += 1
    return success(ser.referral(referral), status=200)


@bp.route("/referrals/<referral_id>/manual-referral", methods=["POST"])
def manual_referral(referral_id):
    require_role("OperationsCoordinator")
    referral = get_referral_or_404(referral_id)
    data = body()
    require_str(data, "partner_name")
    bps = require_int(data, "referral_fee_bps")
    enum(data, "split_policy", ALLOWED_ENUMS["split_policy"])
    if bps <= 0 or bps > MAX_REFERRAL_FEE_BPS:
        raise ApiError("ERR_REFERRAL_FEE_EXCEEDED", http_status=409)
    client = get_client_or_404(referral["client_id"])
    region = get_region_or_404(client["region_id"])
    calc.compute_region_rollup(region)

    # Pass-through: the client already carries a referral, so nothing is written.
    if client["status"] in ("ASSIGNED", "IN_TRANSACTION") or calc.referral_for_client(client["id"]):
        if region["enrolment_is_required"] and region["open_referral_count"] >= region["capacity"]:
            raise ApiError("ERR_REGION_CAPACITY_EXCEEDED", http_status=409)
        return success(ser.client(client), status=200)

    if region["enrolment_is_required"] and region["open_referral_count"] >= region["capacity"]:
        raise ApiError("ERR_REGION_CAPACITY_EXCEEDED", http_status=409)
    if region["open_referral_count"] >= region["capacity"]:
        raise ApiError("ERR_REGION_CAPACITY_EXCEEDED", http_status=409)
    client["status"] = "REFERRED"
    client["assignment_mode"] = "REFERRED_PARTNER"
    stamp(client)
    calc.compute_region_rollup(region)
    region["version"] += 1
    return success(ser.client(client), status=200)


@bp.route("/referrals/<referral_id>/accept", methods=["POST"])
def accept_referral(referral_id):
    require_role("TransactionCoordinator")
    referral = get_referral_or_404(referral_id)
    data = body()
    require_str(data, "accepted_partner")
    expected = require_int(data, "expected_region_version")
    region = get_region_or_404(referral["region_id"])
    if region["version"] != expected:
        raise ApiError("ERR_STALE_VERSION", http_status=412)
    calc.compute_region_rollup(region)
    if referral["settlement_status"] not in ("PENDING", "COMPUTED"):
        raise ApiError("ERR_INVALID_STATE", http_status=409)
    if region["enrolment_is_required"] and region["open_referral_count"] >= region["capacity"]:
        raise ApiError("ERR_REGION_CAPACITY_EXCEEDED", http_status=409)
    if region["open_referral_count"] > region["capacity"]:
        raise ApiError("ERR_REGION_CAPACITY_EXCEEDED", http_status=409)
    calc.compute_region_rollup(region)
    region["version"] += 1
    return success(ser.referral(referral), status=200)


# ===========================================================================
# Activity audits
# ===========================================================================
@bp.route("/activity-audits", methods=["GET"])
def list_audits():
    require_role("PlatformAdmin", "TransactionCoordinator", "OperationsCoordinator")
    limit, offset = pagination()
    rows = list(db.audits.values())
    region_id = q("region_id")
    entity_type = q("entity_type")
    if region_id is not None:
        rows = [r for r in rows if r["region_id"] == region_id]
    if entity_type is not None:
        rows = [r for r in rows if r["entity_type"] == entity_type]
    rows.sort(key=lambda r: r["_seq"])
    page = paginate(rows, limit, offset)
    return success([ser.activity_audit(r) for r in page], status=200, is_list=True,
                   page=page_meta(rows, limit, offset))


# ===========================================================================
# Logical clock
# ===========================================================================
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_role("PlatformAdmin")
    data = body()
    raw = require(data, "current_utc")
    dt = parse_iso(raw)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 instant.")
    set_clock(dt)
    return success({}, status=200)