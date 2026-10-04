"""Routes: logical clock, medical groups, markets, practices, providers."""

from flask import Blueprint, request

from db import store
from errors import (
    err_invalid,
    err_market_capacity,
    err_not_found,
    err_transition,
)
from middleware import get_context, require_roles
from response import created, new_entity, ok, paginate, parse_pagination, touch
from validate import (
    body_json,
    optional_int,
    optional_number,
    parse_iso_instant,
    require_enum,
    require_int,
    require_str,
)

bp = Blueprint("core", __name__)

ALL_ROLES = (
    "GroupAdministrator",
    "PayerContractingOfficer",
    "CredentialingCoordinator",
    "PracticeExecutive",
    "DistributionAccountant",
    "GroupFinancialController",
    "MarketCommitteeChair",
    "PhysicianBoardMember",
    "ComplianceOfficer",
)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("GroupAdministrator")
    data = body_json()
    if "to_iso8601" not in data:
        raise err_invalid("to_iso8601 is required")
    dt = parse_iso_instant(data["to_iso8601"])
    store.set_clock(dt)
    return ok({})


# ---------------------------------------------------------------------------
# MedicalGroup
# ---------------------------------------------------------------------------

@bp.route("/api/medical-groups", methods=["POST"])
def create_medical_group():
    require_roles("GroupAdministrator")
    data = body_json()
    g = new_entity()
    g["tin"] = require_str(data, "tin")
    g["display_name"] = require_str(data, "display_name")
    g["status"] = "FORMING"
    g["shared_services_tier1_rate"] = optional_number(data, "shared_services_tier1_rate", 0.07)
    g["shared_services_tier1_cap_cents"] = optional_int(data, "shared_services_tier1_cap_cents", 50000000)
    g["shared_services_tier2_rate"] = optional_number(data, "shared_services_tier2_rate", 0.05)
    g["distribution_hold_threshold_cents"] = optional_int(data, "distribution_hold_threshold_cents", 5000)
    g["departure_notice_days"] = optional_int(data, "departure_notice_days", 180)
    g["non_compete_term_months"] = optional_int(data, "non_compete_term_months", 24)
    g["early_exit_base_penalty_cents"] = optional_int(data, "early_exit_base_penalty_cents", 2500000)
    g["early_exit_per_month_cents"] = optional_int(data, "early_exit_per_month_cents", 250000)
    g["insufficient_notice_penalty_cents"] = optional_int(data, "insufficient_notice_penalty_cents", 500000)
    store.medical_groups[g["id"]] = g
    return created(g)


@bp.route("/api/medical-groups", methods=["GET"])
def list_medical_groups():
    get_context()
    limit, offset = parse_pagination()
    return paginate(list(store.medical_groups.values()), limit, offset)


@bp.route("/api/medical-groups/<gid>", methods=["GET"])
def get_medical_group(gid):
    get_context()
    g = store.medical_groups.get(gid)
    if g is None:
        raise err_not_found("MEDICAL_GROUP", "Medical group not found")
    return ok(g)


@bp.route("/api/medical-groups/<gid>/activate", methods=["POST"])
def activate_medical_group(gid):
    require_roles("GroupAdministrator")
    g = store.medical_groups.get(gid)
    if g is None:
        raise err_not_found("MEDICAL_GROUP", "Medical group not found")
    if g["status"] != "FORMING":
        raise err_transition("Group is not FORMING")
    g["status"] = "OPERATING"
    touch(g)
    return ok(g)


# ---------------------------------------------------------------------------
# Market
# ---------------------------------------------------------------------------

@bp.route("/api/markets", methods=["POST"])
def create_market():
    require_roles("GroupAdministrator")
    data = body_json()
    medical_group_id = require_str(data, "medical_group_id")
    name = require_str(data, "name")
    state_code = require_str(data, "state_code")
    max_practices = require_int(data, "max_practices")
    market_weight = optional_number(data, "market_weight", 1.0)
    if medical_group_id not in store.medical_groups:
        raise err_not_found("MEDICAL_GROUP", "Medical group not found")
    m = new_entity()
    m.update(
        medical_group_id=medical_group_id,
        name=name,
        state_code=state_code,
        max_practices=max_practices,
        market_weight=market_weight,
    )
    store.markets[m["id"]] = m
    return created(m)


@bp.route("/api/markets", methods=["GET"])
def list_markets():
    get_context()
    limit, offset = parse_pagination()
    items = list(store.markets.values())
    mgid = request.args.get("medical_group_id")
    if mgid is not None:
        items = [m for m in items if m["medical_group_id"] == mgid]
    return paginate(items, limit, offset)


@bp.route("/api/markets/<mid>", methods=["GET"])
def get_market(mid):
    get_context()
    m = store.markets.get(mid)
    if m is None:
        raise err_not_found("MARKET", "Market not found")
    return ok(m)


# ---------------------------------------------------------------------------
# Practice
# ---------------------------------------------------------------------------

OCCUPIED_STATUSES = {"ONBOARDING", "AFFILIATED", "SUSPENDED", "DEPARTING"}


@bp.route("/api/practices", methods=["POST"])
def create_practice():
    require_roles("GroupAdministrator")
    data = body_json()
    medical_group_id = require_str(data, "medical_group_id")
    market_id = require_str(data, "market_id")
    legal_name = require_str(data, "legal_name")
    legacy_tin = require_str(data, "legacy_tin")
    org_npi = require_str(data, "org_npi")
    if medical_group_id not in store.medical_groups:
        raise err_not_found("MEDICAL_GROUP", "Medical group not found")
    market = store.markets.get(market_id)
    if market is None:
        raise err_not_found("MARKET", "Market not found")
    occupied = sum(
        1
        for p in store.practices.values()
        if p["market_id"] == market_id and p["status"] in OCCUPIED_STATUSES
    )
    if occupied >= int(market["max_practices"]):
        raise err_market_capacity()
    p = new_entity()
    p.update(
        medical_group_id=medical_group_id,
        market_id=market_id,
        wave_id=None,
        legal_name=legal_name,
        legacy_tin=legacy_tin,
        org_npi=org_npi,
        status="PROSPECT",
        affiliation_effective_date=None,
        departure_effective_date=None,
        active_provider_count=0,
    )
    store.practices[p["id"]] = p
    return created(p)


@bp.route("/api/practices", methods=["GET"])
def list_practices():
    get_context()
    limit, offset = parse_pagination()
    items = list(store.practices.values())
    mgid = request.args.get("medical_group_id")
    if mgid is not None:
        items = [p for p in items if p["medical_group_id"] == mgid]
    mid = request.args.get("market_id")
    if mid is not None:
        items = [p for p in items if p["market_id"] == mid]
    wid = request.args.get("wave_id")
    if wid is not None:
        items = [p for p in items if p["wave_id"] == wid]
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    return paginate(items, limit, offset)


@bp.route("/api/practices/<pid>", methods=["GET"])
def get_practice(pid):
    get_context()
    p = store.practices.get(pid)
    if p is None:
        raise err_not_found("PRACTICE", "Practice not found")
    return ok(p)


@bp.route("/api/practices/<pid>/suspend", methods=["POST"])
def suspend_practice(pid):
    require_roles("GroupAdministrator")
    p = store.practices.get(pid)
    if p is None:
        raise err_not_found("PRACTICE", "Practice not found")
    if p["status"] != "AFFILIATED":
        raise err_transition("Practice is not AFFILIATED")
    p["status"] = "SUSPENDED"
    touch(p)
    return ok(p)


@bp.route("/api/practices/<pid>/reinstate", methods=["POST"])
def reinstate_practice(pid):
    require_roles("GroupAdministrator")
    p = store.practices.get(pid)
    if p is None:
        raise err_not_found("PRACTICE", "Practice not found")
    if p["status"] != "SUSPENDED":
        raise err_transition("Practice is not SUSPENDED")
    p["status"] = "AFFILIATED"
    touch(p)
    return ok(p)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

@bp.route("/api/providers", methods=["POST"])
def create_provider():
    require_roles("GroupAdministrator")
    data = body_json()
    practice_id = require_str(data, "practice_id")
    npi = require_str(data, "npi")
    full_name = require_str(data, "full_name")
    specialty = require_str(data, "specialty")
    provider_role = require_enum(data, "provider_role", {"PHYSICIAN", "APP"})
    from validate import require_date

    esd = require_date(data, "employment_start_date")
    practice = store.practices.get(practice_id)
    if practice is None:
        raise err_not_found("PRACTICE", "Practice not found")
    if practice["status"] not in ("PROSPECT", "ONBOARDING", "AFFILIATED"):
        raise err_transition("Practice must be PROSPECT, ONBOARDING, or AFFILIATED")
    pr = new_entity()
    pr.update(
        practice_id=practice_id,
        npi=npi,
        full_name=full_name,
        specialty=specialty,
        provider_role=provider_role,
        employment_start_date=esd.isoformat(),
        status="ROSTERED",
    )
    store.providers[pr["id"]] = pr
    return created(pr)


@bp.route("/api/providers", methods=["GET"])
def list_providers():
    get_context()
    limit, offset = parse_pagination()
    items = list(store.providers.values())
    pid = request.args.get("practice_id")
    if pid is not None:
        items = [p for p in items if p["practice_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    role = request.args.get("provider_role")
    if role is not None:
        items = [p for p in items if p["provider_role"] == role]
    return paginate(items, limit, offset)


@bp.route("/api/providers/<pid>", methods=["GET"])
def get_provider(pid):
    get_context()
    p = store.providers.get(pid)
    if p is None:
        raise err_not_found("PROVIDER", "Provider not found")
    return ok(p)
