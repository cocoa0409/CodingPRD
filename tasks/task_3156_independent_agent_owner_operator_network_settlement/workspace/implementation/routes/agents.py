"""Agent and CustomerAccount routes."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint

from cascades import cancel_posted_loads, release_exclusive_customers
from common import (
    STATE, ApiError, add_calendar_months, bad_request, body, client_fields,
    clock_dt, fetch, find, mint, month_bounds, ok, ok_list, paginate, parse_ts,
    query_str, require_auth, require_enum, require_int, require_pct, require_role,
    require_state_code, require_text, touch,
)
from domain import (
    band_rate, cumulative_fee, effective_per_load_fee, exclusivity_status_of,
    fee_rows, marginal_fee, period_fee, present, present_all, sync_agent,
    sync_customer_account, sync_load,
)

bp = Blueprint("agents", __name__)


# ─── Agent ───────────────────────────────────────────────────────────────────
@bp.post("/network/agents")
def create_agent():
    require_role("NetworkAdministrator")
    payload = body()
    fields = client_fields(payload, [
        "agent_code", "legal_name", "home_state", "commission_rate_pct",
        "territory_codes", "customer_ownership_days",
    ])
    code = require_text(fields, "agent_code")
    for row in STATE.agents.values():
        if row["agent_code"] == code:
            raise ApiError("ERR_DUPLICATE_AGENT_CODE", 409,
                           f"agent_code {code} already exists in the network.")
    territory = fields.get("territory_codes")
    if not isinstance(territory, list) or not territory:
        raise bad_request("territory_codes must be a non-empty list of state codes.")
    codes = []
    for item in territory:
        if not isinstance(item, str) or len(item) != 2:
            raise bad_request("territory_codes must contain two-letter state codes.")
        if item.upper() in codes:
            raise bad_request("territory_codes must not contain duplicates.")
        codes.append(item.upper())
    row = mint("agents", {
        "agent_code": code,
        "legal_name": require_text(fields, "legal_name"),
        "home_state": require_state_code(fields, "home_state"),
        "commission_rate_pct": require_pct(fields, "commission_rate_pct"),
        "territory_codes": codes,
        "customer_ownership_days": require_int(
            fields, "customer_ownership_days", 365, minimum=0),
        "settlement_hold": True,
        "active_customer_count": 0,
        "awarded_load_count": 0,
        "outstanding_advance_cents": 0,
        "status": "PENDING_ENROLLMENT",
    })
    sync_agent(row, bump=False)
    return ok(present("agent", row), 201)


@bp.get("/network/agents")
def list_agents():
    require_role("FreightAgent", "AgentManager", "SettlementOperator",
                 "NetworkAdministrator")
    rows = list(STATE.agents.values())
    status = query_str("status")
    territory_state = query_str("territory_state")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if territory_state:
        rows = [r for r in rows if territory_state in r["territory_codes"]]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("agent", page), total, limit, offset)


def _load_agent(row_id):
    return fetch("agent", row_id)


@bp.get("/network/agents/<row_id>")
def get_agent(row_id):
    require_role("FreightAgent", "AgentManager", "SettlementOperator",
                 "NetworkAdministrator")
    return ok(present("agent", _load_agent(row_id)))


@bp.post("/network/agents/<row_id>/activate")
def activate_agent(row_id):
    require_role("NetworkAdministrator")
    row = _load_agent(row_id)
    if row["status"] != "PENDING_ENROLLMENT":
        raise ApiError("ERR_AGENT_NOT_ENROLLABLE", 409,
                       "The agent is not in PENDING_ENROLLMENT.")
    if not row["territory_codes"]:
        raise ApiError("ERR_AGENT_TERRITORY_EMPTY", 400,
                       "The agent holds no territory and cannot be activated.")
    row["status"] = "ACTIVE"
    sync_agent(row)
    _recompute_board_flags(row["id"])
    return ok(present("agent", row))


@bp.post("/network/agents/<row_id>/suspend")
def suspend_agent(row_id):
    require_role("NetworkAdministrator")
    row = _load_agent(row_id)
    fields = client_fields(body(), ["reason_code"])
    require_text(fields, "reason_code")
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_AGENT_NOT_ACTIVE", 409, "The agent is not ACTIVE.")
    row["status"] = "SUSPENDED"
    sync_agent(row)
    cancel_posted_loads(row["id"])
    _recompute_board_flags(row["id"])
    return ok(present("agent", row))


@bp.post("/network/agents/<row_id>/reinstate")
def reinstate_agent(row_id):
    require_role("NetworkAdministrator")
    row = _load_agent(row_id)
    client_fields(body(), [])
    if row["status"] != "SUSPENDED":
        raise ApiError("ERR_AGENT_NOT_SUSPENDED", 409, "The agent is not SUSPENDED.")
    row["status"] = "ACTIVE"
    sync_agent(row)
    _recompute_board_flags(row["id"])
    return ok(present("agent", row))


@bp.post("/network/agents/<row_id>/terminate")
def terminate_agent(row_id):
    require_role("NetworkAdministrator")
    row = _load_agent(row_id)
    fields = client_fields(body(), ["reason_code"])
    if "reason_code" in fields:
        require_text(fields, "reason_code")
    if row["status"] == "TERMINATED":
        raise ApiError("ERR_AGENT_ALREADY_TERMINATED", 409,
                       "The agent is already TERMINATED.")
    outstanding = [s for s in STATE.settlements.values()
                   if s["agent_id"] == row["id"]
                   and s["status"] in ("PENDING_APPROVAL", "APPROVED")]
    if outstanding:
        raise ApiError("ERR_AGENT_SETTLEMENTS_OUTSTANDING", 422,
                       "The agent still carries a settlement awaiting approval.")
    row["status"] = "TERMINATED"
    sync_agent(row)
    cancel_posted_loads(row["id"])
    _recompute_board_flags(row["id"])
    release_exclusive_customers(row["id"])
    sync_agent(row)
    for account in STATE.customer_accounts.values():
        if account["agent_id"] == row["id"]:
            sync_customer_account(account)
    return ok(present("agent", row))


def _recompute_board_flags(agent_id: str) -> None:
    from domain import sync_load
    for load in STATE.loads.values():
        if load["agent_id"] == agent_id:
            sync_load(load)


@bp.get("/network/agents/<row_id>/customer-accounts")
def list_agent_customer_accounts(row_id):
    require_role("FreightAgent", "AgentManager", "SettlementOperator",
                 "NetworkAdministrator")
    _load_agent(row_id)
    rows = [a for a in STATE.customer_accounts.values() if a["agent_id"] == row_id]
    status = query_str("exclusivity_status")
    if status:
        rows = [r for r in rows
                if exclusivity_status_of(r, clock_dt()) == status]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("customer_account", page), total, limit, offset)


@bp.get("/network/agents/<row_id>/loads")
def list_agent_loads(row_id):
    require_role("FreightAgent", "AgentManager", "SettlementOperator",
                 "NetworkAdministrator")
    _load_agent(row_id)
    rows = [l for l in STATE.loads.values() if l["agent_id"] == row_id]
    status = query_str("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("load", page), total, limit, offset)


@bp.get("/network/agents/<row_id>/settlements")
def list_agent_settlements(row_id):
    require_role("FreightAgent", "SettlementOperator", "NetworkAdministrator")
    _load_agent(row_id)
    rows = [s for s in STATE.settlements.values() if s["agent_id"] == row_id]
    status = query_str("status")
    method = query_str("settlement_method")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if method:
        rows = [r for r in rows if r["settlement_method"] == method]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("settlement", page), total, limit, offset)


@bp.get("/network/agents/<row_id>/settlement-summary")
def agent_settlement_summary(row_id):
    require_role("FreightAgent", "SettlementOperator", "NetworkAdministrator")
    agent = _load_agent(row_id)
    order = query_str("order") or "DELIVERY"
    rows = [s for s in STATE.settlements.values()
            if s["agent_id"] == row_id and s["status"] in ("APPROVED", "SETTLED")]

    # Only the highest-keyed revision per trip counts; earlier rows are superseded.
    latest = {}
    for settlement in rows:
        trip = STATE.trips.get(settlement["trip_id"])
        delivered = trip["delivered_at"] if trip else None
        key = (delivered or "", settlement["created_at"])
        current = latest.get(settlement["trip_id"])
        if current is None or key > current[0]:
            latest[settlement["trip_id"]] = (key, settlement)
    counted = [entry[1] for entry in latest.values()]

    if order == "CREATION":
        counted.sort(key=lambda s: s["created_at"])
    else:
        def delivery_key(settlement):
            trip = STATE.trips.get(settlement["trip_id"])
            return (trip["delivered_at"] if trip else "", settlement["created_at"])
        counted.sort(key=delivery_key)

    gross = sum(s["agent_share_cents"] or 0 for s in counted)
    return ok({
        "gross_commission_cents": gross,
        "settlement_count": len(counted),
        "last_fee_period_label": clock_dt().strftime("%Y-%m"),
    })


@bp.post("/network/agents/<row_id>/per-load-settlement-tier")
def per_load_settlement_tier(row_id):
    require_role("SettlementOperator", "NetworkAdministrator")
    _load_agent(row_id)
    fields = client_fields(body(), ["settlement_method"])
    require_text(fields, "settlement_method")
    clock = clock_dt()
    start, end = month_bounds(clock)
    from domain import fee_rows
    data = fee_rows(row_id, clock)
    count = data["count"]
    return ok({
        "tier_load_count": count,
        "marginal_fee_cents": marginal_fee(count),
        "cumulative_fee_cents": cumulative_fee(count),
        "effective_per_load_fee_cents": effective_per_load_fee(count),
        "month_start": _short(start),
        "month_end": _short(end),
    })


def _short(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── CustomerAccount ─────────────────────────────────────────────────────────
@bp.post("/network/customer-accounts")
def create_customer_account():
    require_role("FreightAgent", "NetworkAdministrator")
    payload = body()
    fields = client_fields(payload, [
        "agent_id", "customer_ref", "shipper_name", "first_booked_at",
        "released_reason",
    ])
    agent = fetch("agent", require_text(fields, "agent_id"))
    ref = require_text(fields, "customer_ref")
    for row in STATE.customer_accounts.values():
        if row["agent_id"] == agent["id"] and row["customer_ref"] == ref:
            raise ApiError("ERR_DUPLICATE_CUSTOMER_REF", 409,
                           f"customer_ref {ref} already exists for this agent.")
    reason = fields.get("released_reason")
    if reason is not None:
        if reason not in ("NON_SOLICITATION_BREACH", "AGENT_TERMINATED",
                          "CUSTOMER_REQUEST"):
            raise bad_request("released_reason is not a declared value.")
    first_booked = fields.get("first_booked_at")
    booked_dt = parse_ts(first_booked, "first_booked_at")
    row = mint("customer_accounts", {
        "agent_id": agent["id"],
        "customer_ref": ref,
        "shipper_name": require_text(fields, "shipper_name"),
        "first_booked_at": first_booked,
        "_first_booked_dt": booked_dt,
        "ownership_expires_at": None,
        "exclusivity_status": "OWNED_EXCLUSIVE",
        "released_reason": reason,
    })
    sync_customer_account(row, bump=False)
    sync_agent(agent)
    return ok(present("customer_account", row), 201)


@bp.get("/network/customer-accounts")
def list_customer_accounts():
    require_role("FreightAgent", "AgentManager", "SettlementOperator",
                 "NetworkAdministrator")
    rows = list(STATE.customer_accounts.values())
    agent_id = query_str("agent_id")
    ref = query_str("customer_ref")
    status = query_str("exclusivity_status")
    if agent_id:
        rows = [r for r in rows if r["agent_id"] == agent_id]
    if ref:
        rows = [r for r in rows if r["customer_ref"] == ref]
    if status:
        rows = [r for r in rows if exclusivity_status_of(r, clock_dt()) == status]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("customer_account", page), total, limit, offset)


@bp.get("/network/customer-accounts/<row_id>")
def get_customer_account(row_id):
    require_role("FreightAgent", "AgentManager", "SettlementOperator",
                 "NetworkAdministrator")
    row = fetch("customer_account", row_id)
    return ok(present("customer_account", row))