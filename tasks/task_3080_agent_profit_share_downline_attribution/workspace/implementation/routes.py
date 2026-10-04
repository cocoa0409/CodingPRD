"""All route handlers for the agent profit-share domain.

Validation order per PRD §2.5: auth -> role -> path existence (left-to-right)
-> body-FK existence -> field well-formedness -> state -> temporal -> referential
-> business constraints -> fiscal -> segregation of duties -> OCC (last).
"""
from datetime import timedelta
from decimal import Decimal

from flask import request

import db
import services as svc
from helpers import (
    ApiError, get_body, invalid_state, is_number, is_string, new_entity,
    new_id, not_found, now_ts, paginate, parse_ts, require_number,
    require_string, sort_created, touch, validation, PERIOD_MONTH_RE,
)

ALL_ROLES = ["PlatformAdmin", "MarketCenterAdmin", "RegionalDirector",
             "ALCChair", "Agent"]

PA_ONLY = ["PlatformAdmin"]
PA_MCA = ["PlatformAdmin", "MarketCenterAdmin"]
MCA_ONLY = ["MarketCenterAdmin"]
RD_ONLY = ["RegionalDirector"]
ALC_ONLY = ["ALCChair"]
AGENT_ONLY = ["Agent"]

BLOCKED_TRANSFER_STATUSES = ("PRELIMINARY_CLOSED", "FINAL_CLOSE_PENDING", "FINAL_CLOSED")

AGENT_COMPUTED_FIELDS = {
    "market_center_id", "membership_status", "cap_status", "cap_year_start",
    "cap_year_end", "accrued_company_dollar", "pending_payable_profit_share",
    "lifetime_profit_share", "departure_date", "vested",
}


def _list(store_name, args, allowed_filters, base_filter=None):
    items = list(db.stores[store_name].values())
    if base_filter is not None:
        items = [e for e in items if base_filter(e)]
    for key in allowed_filters:
        v = args.get(key)
        if v is not None:
            items = [e for e in items if str(e.get(key)) == v]
    items = sort_created(items)
    return paginate(items)


def _public(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def _require_expected_version(body):
    v = body.get("expected_agent_version")
    if v is None:
        raise validation("Missing required field: expected_agent_version")
    if not isinstance(v, int) or isinstance(v, bool):
        raise validation("expected_agent_version must be an integer")
    return v


def _check_occ(agent, expected):
    if agent["version"] != expected:
        raise ApiError("ERR_STALE_AGENT_VERSION", 412,
                       "expected_agent_version %s does not match current version %s"
                       % (expected, agent["version"]))


# ================================================================ clock
def set_clock(user):
    body = get_body()
    raw = require_string(body, "to_iso8601")
    dt = parse_ts(raw, "to_iso8601")
    db.set_clock(dt)
    return {"current_utc": svc._iso(dt)}, 200, None, False


# ================================================================ market centers
def create_market_center(user):
    body = get_body()
    name = require_string(body, "name")
    region_code = require_string(body, "region_code")
    center = new_entity({
        "name": name,
        "region_code": region_code,
        "status": "ACTIVE",
    })
    db.stores["market_centers"][center["id"]] = center
    return _public(center), 201, None, False


def get_market_center(user, center_id):
    return _public(svc.get_center(center_id)), 200, None, False


def suspend_market_center(user, center_id):
    center = svc.get_center(center_id)
    if center["status"] != "ACTIVE":
        raise invalid_state("Market center is not ACTIVE")
    center["status"] = "SUSPENDED"
    touch(center)
    return _public(center), 200, None, False


def reactivate_market_center(user, center_id):
    center = svc.get_center(center_id)
    if center["status"] != "SUSPENDED":
        raise invalid_state("Market center is not SUSPENDED")
    center["status"] = "ACTIVE"
    touch(center)
    return _public(center), 200, None, False


def list_center_agents(user, center_id):
    svc.get_center(center_id)
    page, meta = _list(
        "agents", request.args, ["membership_status"],
        base_filter=lambda a: a["market_center_id"] == center_id)
    return [_public(a) for a in page], 200, meta, True


# ================================================================ agents
def create_agent(user, center_id):
    center = svc.get_center(center_id)
    body = get_body()
    if any(k in body for k in AGENT_COMPUTED_FIELDS):
        raise validation("Computed/system fields may not be supplied")
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    join_raw = require_string(body, "join_date")
    join_dt = parse_ts(join_raw, "join_date")
    sponsor_id = body.get("sponsor_agent_id")
    if sponsor_id is not None and not is_string(sponsor_id):
        raise validation("sponsor_agent_id must be a string id")
    # Referential sponsor checks first (§2.5), then the center-activity gate.
    sponsor = None
    if sponsor_id is not None:
        sponsor = db.stores["agents"].get(sponsor_id)
        if sponsor is None:
            raise not_found("ERR_AGENT_NOT_FOUND",
                            "Sponsor agent not found: %s" % sponsor_id)
        if sponsor["market_center_id"] != center_id:
            raise ApiError("ERR_SPONSOR_CROSS_CENTER", 422,
                           "Sponsor must be enrolled in the same market center")
        if (sponsor["membership_status"] != "ACTIVE"
                and user["role"] == "MarketCenterAdmin"):
            raise ApiError("ERR_SPONSOR_CROSS_CENTER", 422,
                           "Sponsor must be an ACTIVE agent of the same market center")
    if center["status"] != "ACTIVE":
        raise ApiError("ERR_CENTER_NOT_ACTIVE", 422,
                       "Market center is SUSPENDED; enrollment is blocked")
    for a in db.stores["agents"].values():
        if a["email"] == email:
            raise validation("email must be unique across the system")
    cap_start = join_dt
    cap_end = svc.add_years(join_dt, 1)
    agent = new_entity({
        "market_center_id": center_id,
        "sponsor_agent_id": sponsor_id,
        "full_name": full_name,
        "email": email,
        "join_date": svc._iso(join_dt),
        "membership_status": "ENROLLED_PENDING_DOCS",
        "cap_status": "UNCAPPED",
        "cap_year_start": svc._iso(cap_start),
        "cap_year_end": svc._iso(cap_end),
        "accrued_company_dollar": 0.00,
        "pending_payable_profit_share": 0.00,
        "lifetime_profit_share": 0.00,
        "departure_date": None,
        "vested": False,
        "_join_dt": join_dt,
        "_cap_year_start_dt": cap_start,
        "_cap_year_end_dt": cap_end,
    })
    db.stores["agents"][agent["id"]] = agent
    # 1:1 vesting schedule created at enrollment.
    vs = new_entity({
        "agent_id": agent["id"],
        "vesting_start_date": agent["join_date"],
        "service_months_provisional": 0,
        "service_days_final": 0,
        "vested_ratio_provisional": 0.0,
        "vested_ratio_final": 0.0,
        "status": "ACCRUING",
    })
    db.stores["vesting_schedules"][vs["id"]] = vs
    # Sponsorship closure (depths 1..7) when a sponsor is given.
    if sponsor_id is not None:
        svc.build_closure(agent)
    return _public(agent), 201, None, False


def list_agents(user):
    page, meta = _list("agents", request.args,
                       ["sponsor_agent_id", "market_center_id", "membership_status"])
    return [_public(a) for a in page], 200, meta, True


def get_agent(user, agent_id):
    return _public(svc.get_agent(agent_id)), 200, None, False


def create_onboarding_document(user, agent_id):
    agent = svc.get_agent(agent_id)
    body = get_body()
    document_type = require_string(body, "document_type")
    if document_type not in ("SPONSOR_ATTESTATION", "ICA_SIGNED", "W9"):
        raise validation("document_type must be SPONSOR_ATTESTATION, ICA_SIGNED, or W9")
    document_ref = require_string(body, "document_ref")
    attested = body.get("attested_sponsor_agent_id")
    if document_type == "SPONSOR_ATTESTATION":
        if attested is None:
            raise validation(
                "attested_sponsor_agent_id is required for SPONSOR_ATTESTATION")
        if not is_string(attested):
            raise validation("attested_sponsor_agent_id must be a string id")
        if attested not in db.stores["agents"]:
            raise not_found("ERR_AGENT_NOT_FOUND",
                            "Attested sponsor not found: %s" % attested)
    else:
        attested = None
    doc = new_entity({
        "agent_id": agent_id,
        "document_type": document_type,
        "document_ref": document_ref,
        "attested_sponsor_agent_id": attested,
        "received_at": now_ts(),
    })
    db.stores["onboarding_documents"][doc["id"]] = doc
    # Automatic activation when the required set is complete.
    if agent["membership_status"] == "ENROLLED_PENDING_DOCS":
        types = {d["document_type"] for d in db.stores["onboarding_documents"].values()
                 if d["agent_id"] == agent_id}
        required = {"ICA_SIGNED", "W9"}
        if agent["sponsor_agent_id"] is not None:
            required.add("SPONSOR_ATTESTATION")
        if required.issubset(types):
            agent["membership_status"] = "ACTIVE"
            touch(agent)
    return _public(doc), 201, None, False


def list_onboarding_documents(user, agent_id):
    svc.get_agent(agent_id)
    page, meta = _list("onboarding_documents", request.args, [],
                       base_filter=lambda d: d["agent_id"] == agent_id)
    return [_public(d) for d in page], 200, meta, True


def list_downline(user, agent_id):
    svc.get_agent(agent_id)
    page, meta = _list("sponsorship_edges", request.args, ["status"],
                       base_filter=lambda e: e["parent_agent_id"] == agent_id)
    return [_public(e) for e in page], 200, meta, True


def list_upline(user, agent_id):
    svc.get_agent(agent_id)
    page, meta = _list("sponsorship_edges", request.args, ["status"],
                       base_filter=lambda e: e["child_agent_id"] == agent_id)
    return [_public(e) for e in page], 200, meta, True


def get_vesting_schedule(user, agent_id):
    svc.get_agent(agent_id)
    rows = [vs for vs in db.stores["vesting_schedules"].values()
            if vs["agent_id"] == agent_id]
    return [_public(vs) for vs in sort_created(rows)], 200, None, True


def depart_agent(user, agent_id):
    agent = svc.get_agent(agent_id)
    body = get_body()
    dep_raw = require_string(body, "departure_date")
    dep_dt = parse_ts(dep_raw, "departure_date")
    if agent["membership_status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE agent may depart")
    for tr in db.stores["transfer_requests"].values():
        if tr["agent_id"] == agent_id and tr["status"] in ("REQUESTED", "APPROVED"):
            raise ApiError("ERR_TRANSFER_IN_PROGRESS", 409,
                           "A transfer request is in progress for this agent")
    svc.depart_agent_cascade(agent, dep_dt)
    return _public(agent), 200, None, False


def create_transfer_request(user, agent_id):
    agent = svc.get_agent(agent_id)
    body = get_body()
    expected = _require_expected_version(body)
    to_center_id = require_string(body, "to_market_center_id")
    eff_raw = require_string(body, "effective_date")
    eff_dt = parse_ts(eff_raw, "effective_date")
    to_center = db.stores["market_centers"].get(to_center_id)
    if to_center is None:
        raise not_found("ERR_MARKET_CENTER_NOT_FOUND",
                        "Destination market center not found: %s" % to_center_id)
    # Temporal first (§2.5): effective date must not fall inside a closed
    # source-center period.
    for p in db.stores["periods"].values():
        if p["market_center_id"] != agent["market_center_id"]:
            continue
        if p["status"] not in BLOCKED_TRANSFER_STATUSES:
            continue
        start, end = svc._month_bounds(p["period_month"])
        if start <= eff_dt.date() < end:
            raise ApiError("ERR_TRANSFER_WINDOW_CONFLICT", 422,
                           "effective_date falls inside a closed source-center period")
    if to_center_id == agent["market_center_id"]:
        raise ApiError("ERR_TRANSFER_SELF_CENTER", 422,
                       "Destination equals the agent's current market center")
    if to_center["status"] != "ACTIVE":
        raise ApiError("ERR_CENTER_NOT_ACTIVE", 422,
                       "Destination market center is SUSPENDED")
    for tr in db.stores["transfer_requests"].values():
        if tr["agent_id"] == agent_id and tr["status"] in ("REQUESTED", "APPROVED"):
            raise ApiError("ERR_TRANSFER_IN_PROGRESS", 409,
                           "Another transfer request is in progress for this agent")
    # OCC is evaluated last (§2.5).
    _check_occ(agent, expected)
    tr = new_entity({
        "agent_id": agent_id,
        "from_market_center_id": agent["market_center_id"],
        "to_market_center_id": to_center_id,
        "effective_date": svc._iso(eff_dt),
        "status": "REQUESTED",
        "downline_preserved": True,
        "_effective_dt": eff_dt,
    })
    db.stores["transfer_requests"][tr["id"]] = tr
    touch(agent)
    return _public(tr), 201, None, False


# ================================================================ sponsorship edges
def list_sponsorship_edges(user):
    args = request.args
    depth_raw = args.get("depth_level")
    depth = None
    if depth_raw is not None:
        try:
            depth = int(depth_raw)
        except (TypeError, ValueError):
            raise validation("depth_level must be an integer")
    items = list(db.stores["sponsorship_edges"].values())
    for key in ("parent_agent_id", "child_agent_id", "status"):
        v = args.get(key)
        if v is not None:
            items = [e for e in items if str(e.get(key)) == v]
    if depth is not None:
        items = [e for e in items if e["depth_level"] == depth]
    page, meta = paginate(sort_created(items))
    return [_public(e) for e in page], 200, meta, True


# ================================================================ disputes
def create_dispute(user):
    body = get_body()
    sponsored_id = require_string(body, "sponsored_agent_id")
    evidence_id = require_string(body, "evidence_document_id")
    reason = require_string(body, "reason")
    sponsored = db.stores["agents"].get(sponsored_id)
    if sponsored is None:
        raise not_found("ERR_AGENT_NOT_FOUND",
                        "Sponsored agent not found: %s" % sponsored_id)
    evidence = db.stores["onboarding_documents"].get(evidence_id)
    if evidence is None:
        raise not_found("ERR_DOCUMENT_NOT_FOUND",
                        "Evidence document not found: %s" % evidence_id)
    filer_id = user["user_id"]
    filed_dt = db.get_clock()
    deadline = sponsored["_join_dt"] + timedelta(days=svc.DISPUTE_WINDOW_DAYS)
    # Temporal window before the other filing checks (§3.4).
    if filed_dt > deadline:
        raise ApiError("ERR_DISPUTE_WINDOW_EXPIRED", 422,
                       "Dispute filed after join_date + 90 days")
    if (evidence["document_type"] != "SPONSOR_ATTESTATION"
            or evidence["agent_id"] != sponsored_id
            or evidence["attested_sponsor_agent_id"] != filer_id):
        raise ApiError("ERR_EVIDENCE_INVALID", 422,
                       "Evidence must be a SPONSOR_ATTESTATION of the sponsored "
                       "agent attesting the filer")
    filer = db.stores["agents"].get(filer_id)
    if filer is None or filer["market_center_id"] != sponsored["market_center_id"]:
        raise ApiError("ERR_SPONSOR_CROSS_CENTER", 422,
                       "Filer and sponsored agent must share a market center")
    if filer_id == sponsored_id or filer_id == sponsored["sponsor_agent_id"]:
        raise ApiError("ERR_DISPUTE_NOT_ACTIONABLE", 422,
                       "Filer is the sponsored agent or the current sponsor of record")
    dispute = new_entity({
        "filer_agent_id": filer_id,
        "sponsored_agent_id": sponsored_id,
        "current_sponsor_agent_id": sponsored["sponsor_agent_id"],
        "evidence_document_id": evidence_id,
        "reason": reason,
        "filed_at": svc._iso(filed_dt),
        "window_deadline": svc._iso(deadline),
        "status": "FILED",
        "resolution": None,
        "appeal_count": 0,
    })
    db.stores["disputes"][dispute["id"]] = dispute
    return _public(dispute), 201, None, False


def list_disputes(user):
    page, meta = _list("disputes", request.args,
                       ["filer_agent_id", "sponsored_agent_id",
                        "evidence_document_id", "status"])
    return [_public(d) for d in page], 200, meta, True


def get_dispute(user, dispute_id):
    return _public(svc.get_dispute(dispute_id)), 200, None, False


def open_dispute_review(user, dispute_id):
    dispute = svc.get_dispute(dispute_id)
    if dispute["status"] not in ("FILED", "REOPENED"):
        raise invalid_state("Dispute must be FILED or REOPENED to open review")
    dispute["status"] = "UNDER_REVIEW"
    touch(dispute)
    return _public(dispute), 200, None, False


def resolve_dispute(user, dispute_id):
    dispute = svc.get_dispute(dispute_id)
    body = get_body()
    outcome = require_string(body, "outcome")
    if outcome not in ("UPHELD", "OVERTURNED", "DISMISSED"):
        raise validation("outcome must be UPHELD, OVERTURNED, or DISMISSED")
    if dispute["status"] != "UNDER_REVIEW":
        raise invalid_state("Dispute must be UNDER_REVIEW to resolve")
    if outcome == "UPHELD":
        dispute["status"] = "RESOLVED_UPHELD"
        dispute["resolution"] = "UPHELD"
        touch(dispute)
    elif outcome == "DISMISSED":
        dispute["status"] = "DISMISSED"
        dispute["resolution"] = "DISMISSED"
        touch(dispute)
    else:
        # Cycle guard runs before any mutation (atomicity).
        svc.overturn_sponsor_tree(dispute)
        dispute["status"] = "RESOLVED_OVERTURNED"
        dispute["resolution"] = "OVERTURNED"
        touch(dispute)
    return _public(dispute), 200, None, False


def appeal_dispute(user, dispute_id):
    dispute = svc.get_dispute(dispute_id)
    if dispute["status"] not in ("RESOLVED_UPHELD", "RESOLVED_OVERTURNED"):
        raise invalid_state("Only a resolved dispute may be appealed")
    if user["user_id"] != dispute["filer_agent_id"]:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Only the original filer may appeal this dispute")
    if dispute["appeal_count"] >= 1:
        raise ApiError("ERR_APPEAL_EXHAUSTED", 422,
                       "appeal_count is already at the maximum (1)")
    dispute["status"] = "REOPENED"
    dispute["appeal_count"] += 1
    touch(dispute)
    return _public(dispute), 200, None, False


# ================================================================ commission events
def create_commission_event(user):
    body = get_body()
    expected = _require_expected_version(body)
    agent_id = require_string(body, "agent_id")
    agent = db.stores["agents"].get(agent_id)
    if agent is None:
        raise not_found("ERR_AGENT_NOT_FOUND", "Agent not found: %s" % agent_id)
    gross = require_number(body, "gross_commission")
    occurred_raw = require_string(body, "occurred_on")
    occurred_dt = parse_ts(occurred_raw, "occurred_on")
    external_ref = require_string(body, "external_ref")
    # State before business rules (§2.5): only ACTIVE agents take commissions.
    if agent["membership_status"] != "ACTIVE":
        raise invalid_state(
            "Commissions may only be posted against an ACTIVE agent")
    if occurred_dt < agent["_cap_year_start_dt"]:
        raise ApiError("ERR_BACKDATED_COMMISSION", 422,
                       "occurred_on precedes the current cap_year_start")
    if Decimal(str(gross)) <= Decimal("0"):
        raise ApiError("ERR_NONPOSITIVE_AMOUNT", 422,
                       "gross_commission must be > 0")
    _check_occ(agent, expected)
    company, retained, cap_applied = svc.post_commission_split(
        agent, gross, occurred_dt)
    event = new_entity({
        "agent_id": agent_id,
        "market_center_id": agent["market_center_id"],
        "gross_commission": gross,
        "occurred_on": svc._iso(occurred_dt),
        "external_ref": external_ref,
        "status": "POSTED",
        "company_dollar": company,
        "agent_retained": retained,
        "final_company_dollar": None,
        "cap_applied": cap_applied,
        "_occurred_dt": occurred_dt,
    })
    db.stores["commission_events"][event["id"]] = event
    touch(agent)
    return _public(event), 201, None, False


def list_commission_events(user):
    page, meta = _list("commission_events", request.args,
                       ["agent_id", "market_center_id", "status"])
    return [_public(e) for e in page], 200, meta, True


def get_commission_event(user, event_id):
    return _public(svc.get_event(event_id)), 200, None, False


def settle_commission_event(user, event_id):
    event = svc.get_event(event_id)
    if event["status"] != "POSTED":
        raise invalid_state("Only a POSTED event may be settled")
    event["status"] = "SETTLED"
    touch(event)
    return _public(event), 200, None, False


def void_commission_event(user, event_id):
    event = svc.get_event(event_id)
    if event["status"] != "POSTED":
        raise invalid_state("Only a POSTED event may be voided")
    # Void is refused when the event's month is already FINAL_CLOSED.
    month = event["_occurred_dt"].strftime("%Y-%m")
    for p in db.stores["periods"].values():
        if (p["market_center_id"] == event["market_center_id"]
                and p["period_month"] == month
                and p["status"] == "FINAL_CLOSED"):
            raise invalid_state(
                "The event's month is FINAL_CLOSED; voiding is refused")
    event["status"] = "VOID"
    touch(event)
    agent = db.stores["agents"][event["agent_id"]]
    new_accrued = (Decimal(str(agent["accrued_company_dollar"]))
                   - Decimal(str(event["company_dollar"])))
    agent["accrued_company_dollar"] = float(new_accrued.quantize(
        Decimal("0.01")))
    if new_accrued < svc.ANNUAL_CAP and agent["cap_status"] == "CAPPED":
        agent["cap_status"] = "UNCAPPED"
    touch(agent)
    # Open/preliminarily-closed periods for the month recompute.
    for p in db.stores["periods"].values():
        if (p["market_center_id"] == event["market_center_id"]
                and p["period_month"] == month
                and p["status"] in ("OPEN", "PRELIMINARY_CLOSED")):
            svc.recompute_provisional_profit(p)
            touch(p)
    return _public(event), 200, None, False


# ================================================================ periods / ledger
def create_period(user, center_id):
    center = svc.get_center(center_id)
    body = get_body()
    period_month = require_string(body, "period_month")
    if not PERIOD_MONTH_RE.match(period_month):
        raise validation("period_month must match YYYY-MM")
    if center["status"] != "ACTIVE":
        raise ApiError("ERR_CENTER_NOT_ACTIVE", 422,
                       "Market center is SUSPENDED; period creation is blocked")
    for p in db.stores["periods"].values():
        if (p["market_center_id"] == center_id
                and p["period_month"] == period_month):
            raise ApiError("ERR_PERIOD_MONTH_CONFLICT", 409,
                           "A period for this month already exists")
    period = new_entity({
        "market_center_id": center_id,
        "period_month": period_month,
        "status": "OPEN",
        "provisional_profit": 0.00,
        "final_profit": None,
        "provisional_pool": None,
        "profit_share_pool": None,
        "distributed_total": 0.00,
        "center_retained_amount": 0.00,
        "preliminary_closed_by": None,
    })
    db.stores["periods"][period["id"]] = period
    svc.recompute_provisional_profit(period)
    return _public(period), 201, None, False


def list_periods(user):
    page, meta = _list("periods", request.args, ["market_center_id", "status"])
    return [_public(p) for p in page], 200, meta, True


def get_period(user, period_id):
    return _public(svc.get_period(period_id)), 200, None, False


def create_ledger_entry(user, period_id):
    period = svc.get_period(period_id)
    body = get_body()
    entry_type = require_string(body, "entry_type")
    if entry_type not in ("EXPENSE", "ADJUSTMENT"):
        raise validation("entry_type must be EXPENSE or ADJUSTMENT")
    amount = require_number(body, "amount")
    memo = body.get("memo")
    if memo is not None and not is_string(memo):
        raise validation("memo must be a string")
    if period["status"] != "OPEN":
        raise invalid_state("Ledger entries are accepted only while the period is OPEN")
    if entry_type == "EXPENSE" and Decimal(str(amount)) <= Decimal("0"):
        raise ApiError("ERR_NONPOSITIVE_AMOUNT", 422,
                       "EXPENSE amount must be > 0")
    entry = {
        "id": new_id(),
        "period_id": period_id,
        "entry_type": entry_type,
        "amount": amount,
        "memo": memo,
        "created_at": now_ts(),
    }
    db.stores["ledger_entries"][entry["id"]] = entry
    svc.recompute_provisional_profit(period)
    touch(period)
    return entry, 201, None, False


def list_ledger_entries(user, period_id):
    svc.get_period(period_id)
    page, meta = _list("ledger_entries", request.args, [],
                       base_filter=lambda e: e["period_id"] == period_id)
    return [_public(e) for e in page], 200, meta, True


def preliminary_close_period(user, period_id):
    period = svc.get_period(period_id)
    if period["status"] != "OPEN":
        raise invalid_state("Only an OPEN period may be preliminarily closed")
    actor = db.stores["agents"].get(user["user_id"])
    if (actor is None
            or actor["market_center_id"] != period["market_center_id"]
            or actor["membership_status"] != "ACTIVE"):
        raise ApiError("ERR_MCA_NOT_CENTER_AGENT", 422,
                       "Preliminary close requires an ACTIVE agent of this center")
    profit = svc.compute_provisional_profit(period)
    if profit <= Decimal("0.00"):
        raise ApiError("ERR_PROFIT_NOT_POSITIVE", 422,
                       "provisional_profit must be > 0 at preliminary close")
    period["provisional_profit"] = float(profit)
    pool = (svc.POOL_RATE * profit).quantize(Decimal("0.01"))
    period["provisional_pool"] = float(pool)
    period["preliminary_closed_by"] = user["user_id"]
    period["status"] = "PRELIMINARY_CLOSED"
    svc.run_waterfall(period, float(pool), "PROVISIONAL")
    svc.recompute_period_totals(period)
    touch(period)
    return _public(period), 200, None, False


def list_period_distributions(user, period_id):
    svc.get_period(period_id)
    page, meta = _list("distributions", request.args, ["status", "basis"],
                       base_filter=lambda d: d["period_id"] == period_id)
    return [_public(d) for d in page], 200, meta, True


# ================================================================ governance
def create_resolution(user, period_id):
    period = svc.get_period(period_id)
    body = get_body()
    resolution_type = require_string(body, "resolution_type")
    if resolution_type != "FINAL_CLOSE_RATIFICATION":
        raise validation("resolution_type must be FINAL_CLOSE_RATIFICATION")
    if period["status"] != "PRELIMINARY_CLOSED":
        raise invalid_state(
            "A resolution may be drafted only for a PRELIMINARY_CLOSED period")
    resolution = new_entity({
        "period_id": period_id,
        "resolution_type": resolution_type,
        "status": "DRAFT",
        "notes": None,
        "proposed_by": None,
        "ratified_by": None,
    })
    db.stores["resolutions"][resolution["id"]] = resolution
    return _public(resolution), 201, None, False


def list_period_resolutions(user, period_id):
    svc.get_period(period_id)
    page, meta = _list("resolutions", request.args, [],
                       base_filter=lambda r: r["period_id"] == period_id)
    return [_public(r) for r in page], 200, meta, True


def propose_resolution(user, resolution_id):
    resolution = svc.get_resolution(resolution_id)
    period = svc.get_period(resolution["period_id"])
    if resolution["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT resolution may be proposed")
    if period["status"] != "PRELIMINARY_CLOSED":
        raise invalid_state("The owning period must be PRELIMINARY_CLOSED")
    resolution["status"] = "PROPOSED"
    resolution["proposed_by"] = user["user_id"]
    touch(resolution)
    period["status"] = "FINAL_CLOSE_PENDING"
    touch(period)
    return _public(resolution), 200, None, False


def amend_resolution(user, resolution_id):
    resolution = svc.get_resolution(resolution_id)
    body = get_body()
    notes = body.get("notes")
    if notes is not None and not is_string(notes):
        raise validation("notes must be a string")
    if resolution["status"] != "REJECTED":
        raise invalid_state("Only a REJECTED resolution may be amended")
    resolution["status"] = "DRAFT"
    if notes is not None:
        resolution["notes"] = notes
    touch(resolution)
    return _public(resolution), 200, None, False


def ratify_resolution(user, resolution_id):
    resolution = svc.get_resolution(resolution_id)
    period = svc.get_period(resolution["period_id"])
    if resolution["status"] != "PROPOSED":
        raise invalid_state("Only a PROPOSED resolution may be ratified")
    # Segregation of duties before the fiscal close (§2.5).
    if user["user_id"] == period["preliminary_closed_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The ratifier may not be the preliminary closer")
    svc.ratification_cascade(period)
    period["status"] = "FINAL_CLOSED"
    touch(period)
    resolution["status"] = "RATIFIED"
    resolution["ratified_by"] = user["user_id"]
    touch(resolution)
    return _public(resolution), 200, None, False


def reject_resolution(user, resolution_id):
    resolution = svc.get_resolution(resolution_id)
    period = svc.get_period(resolution["period_id"])
    if resolution["status"] != "PROPOSED":
        raise invalid_state("Only a PROPOSED resolution may be rejected")
    resolution["status"] = "REJECTED"
    touch(resolution)
    if period["status"] == "FINAL_CLOSE_PENDING":
        period["status"] = "PRELIMINARY_CLOSED"
        touch(period)
    return _public(resolution), 200, None, False


def get_resolution(user, resolution_id):
    return _public(svc.get_resolution(resolution_id)), 200, None, False


# ================================================================ distributions
def list_distributions(user):
    page, meta = _list("distributions", request.args,
                       ["agent_id", "period_id", "status"])
    return [_public(d) for d in page], 200, meta, True


def get_distribution(user, distribution_id):
    return _public(svc.get_distribution(distribution_id)), 200, None, False


def mark_distribution_paid(user, distribution_id):
    dist = svc.get_distribution(distribution_id)
    if dist["status"] != "PAYABLE":
        raise invalid_state("Only a PAYABLE distribution may be marked paid")
    dist["status"] = "PAID"
    touch(dist)
    agent = db.stores["agents"][dist["agent_id"]]
    svc.recompute_agent_totals(agent["id"])
    touch(agent)
    period = db.stores["periods"].get(dist["period_id"])
    if period is not None:
        svc.recompute_period_totals(period)
        touch(period)
    return _public(dist), 200, None, False


# ================================================================ transfer requests
def list_transfer_requests(user):
    page, meta = _list("transfer_requests", request.args,
                       ["agent_id", "from_market_center_id",
                        "to_market_center_id", "status"])
    return [_public(t) for t in page], 200, meta, True


def get_transfer_request(user, transfer_id):
    return _public(svc.get_transfer(transfer_id)), 200, None, False


def approve_transfer(user, transfer_id):
    tr = svc.get_transfer(transfer_id)
    if tr["status"] != "REQUESTED":
        raise invalid_state("Only a REQUESTED transfer may be approved")
    dest = db.stores["market_centers"].get(tr["to_market_center_id"])
    if dest is None or dest["status"] != "ACTIVE":
        raise ApiError("ERR_CENTER_NOT_ACTIVE", 422,
                       "Destination market center is not ACTIVE")
    tr["status"] = "APPROVED"
    touch(tr)
    return _public(tr), 200, None, False


def reject_transfer(user, transfer_id):
    tr = svc.get_transfer(transfer_id)
    if tr["status"] != "REQUESTED":
        raise invalid_state("Only a REQUESTED transfer may be rejected")
    tr["status"] = "REJECTED"
    touch(tr)
    return _public(tr), 200, None, False


def cancel_transfer(user, transfer_id):
    tr = svc.get_transfer(transfer_id)
    if tr["status"] not in ("REQUESTED", "APPROVED"):
        raise invalid_state("Only a REQUESTED or APPROVED transfer may be cancelled")
    if user["user_id"] != tr["agent_id"]:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Only the requesting agent may cancel this transfer")
    tr["status"] = "CANCELLED"
    touch(tr)
    return _public(tr), 200, None, False


def complete_transfer(user, transfer_id):
    tr = svc.get_transfer(transfer_id)
    if tr["status"] != "APPROVED":
        raise invalid_state("Only an APPROVED transfer may be completed")
    src = db.stores["market_centers"].get(tr["from_market_center_id"])
    dest = db.stores["market_centers"].get(tr["to_market_center_id"])
    if (src is None or src["status"] != "ACTIVE"
            or dest is None or dest["status"] != "ACTIVE"):
        raise ApiError("ERR_CENTER_NOT_ACTIVE", 422,
                       "Both market centers must be ACTIVE")
    if db.get_clock() < tr["_effective_dt"]:
        raise ApiError("ERR_TRANSFER_NOT_EFFECTIVE", 422,
                       "The logical clock has not reached the effective_date")
    agent = db.stores["agents"][tr["agent_id"]]
    agent["market_center_id"] = tr["to_market_center_id"]
    # membership_status, sponsorship closure, and cap year carry over unchanged.
    touch(agent)
    tr["status"] = "COMPLETED"
    touch(tr)
    return _public(tr), 200, None, False


# ================================================================ route table
ROUTES = [
    ("POST", "/_clock/set_current_utc", set_clock, PA_ONLY),
    # market centers
    ("POST", "/market-centers", create_market_center, PA_ONLY),
    ("GET", "/market-centers/<center_id>", get_market_center, ALL_ROLES),
    ("POST", "/market-centers/<center_id>/suspend", suspend_market_center, PA_ONLY),
    ("POST", "/market-centers/<center_id>/reactivate", reactivate_market_center, PA_ONLY),
    ("GET", "/market-centers/<center_id>/agents", list_center_agents, ALL_ROLES),
    ("POST", "/market-centers/<center_id>/agents", create_agent, PA_MCA),
    ("POST", "/market-centers/<center_id>/profit-share-periods", create_period, MCA_ONLY),
    # agents
    ("GET", "/agents", list_agents, ALL_ROLES),
    ("GET", "/agents/<agent_id>", get_agent, ALL_ROLES),
    ("POST", "/agents/<agent_id>/onboarding-documents", create_onboarding_document, PA_MCA),
    ("GET", "/agents/<agent_id>/onboarding-documents", list_onboarding_documents, ALL_ROLES),
    ("GET", "/agents/<agent_id>/downline", list_downline, ALL_ROLES),
    ("GET", "/agents/<agent_id>/upline", list_upline, ALL_ROLES),
    ("GET", "/agents/<agent_id>/vesting-schedule", get_vesting_schedule, ALL_ROLES),
    ("POST", "/agents/<agent_id>/depart", depart_agent, MCA_ONLY),
    ("POST", "/agents/<agent_id>/transfer-requests", create_transfer_request, AGENT_ONLY),
    # sponsorship edges
    ("GET", "/sponsorship-edges", list_sponsorship_edges, ALL_ROLES),
    # disputes
    ("POST", "/sponsorship-disputes", create_dispute, AGENT_ONLY),
    ("GET", "/sponsorship-disputes", list_disputes, ALL_ROLES),
    ("GET", "/sponsorship-disputes/<dispute_id>", get_dispute, ALL_ROLES),
    ("POST", "/sponsorship-disputes/<dispute_id>/open-review", open_dispute_review, RD_ONLY),
    ("POST", "/sponsorship-disputes/<dispute_id>/resolve", resolve_dispute, RD_ONLY),
    ("POST", "/sponsorship-disputes/<dispute_id>/appeal", appeal_dispute, AGENT_ONLY),
    # commission events
    ("POST", "/commission-events", create_commission_event, MCA_ONLY),
    ("GET", "/commission-events", list_commission_events, ALL_ROLES),
    ("GET", "/commission-events/<event_id>", get_commission_event, ALL_ROLES),
    ("POST", "/commission-events/<event_id>/settle", settle_commission_event, MCA_ONLY),
    ("POST", "/commission-events/<event_id>/void", void_commission_event, MCA_ONLY),
    # periods / ledger / governance
    ("GET", "/profit-share-periods", list_periods, ALL_ROLES),
    ("GET", "/profit-share-periods/<period_id>", get_period, ALL_ROLES),
    ("POST", "/profit-share-periods/<period_id>/ledger-entries", create_ledger_entry, MCA_ONLY),
    ("GET", "/profit-share-periods/<period_id>/ledger-entries", list_ledger_entries, ALL_ROLES),
    ("POST", "/profit-share-periods/<period_id>/preliminary-close", preliminary_close_period, MCA_ONLY),
    ("GET", "/profit-share-periods/<period_id>/distributions", list_period_distributions, ALL_ROLES),
    ("POST", "/profit-share-periods/<period_id>/governance-resolutions", create_resolution, MCA_ONLY),
    ("GET", "/profit-share-periods/<period_id>/governance-resolutions", list_period_resolutions, ALL_ROLES),
    ("POST", "/governance-resolutions/<resolution_id>/propose", propose_resolution, MCA_ONLY),
    ("POST", "/governance-resolutions/<resolution_id>/amend", amend_resolution, MCA_ONLY),
    ("POST", "/governance-resolutions/<resolution_id>/ratify", ratify_resolution, ALC_ONLY),
    ("POST", "/governance-resolutions/<resolution_id>/reject", reject_resolution, ALC_ONLY),
    ("GET", "/governance-resolutions/<resolution_id>", get_resolution, ALL_ROLES),
    # distributions
    ("GET", "/profit-share-distributions", list_distributions, ALL_ROLES),
    ("GET", "/profit-share-distributions/<distribution_id>", get_distribution, ALL_ROLES),
    ("POST", "/profit-share-distributions/<distribution_id>/mark-paid", mark_distribution_paid, MCA_ONLY),
    # transfers
    ("GET", "/transfer-requests", list_transfer_requests, ALL_ROLES),
    ("GET", "/transfer-requests/<transfer_id>", get_transfer_request, ALL_ROLES),
    ("POST", "/transfer-requests/<transfer_id>/approve", approve_transfer, MCA_ONLY),
    ("POST", "/transfer-requests/<transfer_id>/reject", reject_transfer, MCA_ONLY),
    ("POST", "/transfer-requests/<transfer_id>/cancel", cancel_transfer, AGENT_ONLY),
    ("POST", "/transfer-requests/<transfer_id>/complete", complete_transfer, MCA_ONLY),
]
