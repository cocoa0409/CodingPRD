"""The standing registry: agencies, slates, writers and holding deals."""

import re

from flask import Blueprint, request

import domain as d
from auth import (ROLE_AGENCY_REP, ROLE_BUSINESS_AFFAIRS, ROLE_DEV_EXEC,
                  ROLE_FINANCE, ROLE_PLATFORM_ADMIN, agency_scope_guard, authorize)
from errors import ApiError
from responses import object_response, paginated
from store import fmt_date, new_row, store, touch
from validators import (json_body, require_body, v_bool, v_date, v_enum, v_int,
                        v_string)

bp = Blueprint("registry", __name__)

_AGENCY_CODE_RE = re.compile(r"^[A-Z]{2,6}$")


# ---------------------------------------------------------------------------
# agencies
# ---------------------------------------------------------------------------

@bp.post("/agencies")
@authorize(ROLE_PLATFORM_ADMIN)
def create_agency(principal):
    body = require_body(json_body())
    name = v_string(body, "name", max_len=120)
    code = v_string(body, "agency_code")
    if not _AGENCY_CODE_RE.match(code):
        raise ApiError("ERR_INVALID_REQUEST",
                       "agency_code must be 2 to 6 uppercase letters A-Z.")
    tier = v_enum(body, "relationship_tier", d.RELATIONSHIP_TIERS)
    packaging_allowed = v_bool(body, "packaging_allowed", default=False)
    cap = v_int(body, "annual_submission_cap", minimum=1)
    for existing in store.agencies.values():
        if existing["agency_code"] == code:
            raise ApiError("ERR_INVALID_REQUEST", "agency_code must be unique.")

    row = new_row(
        name=name,
        agency_code=code,
        relationship_tier=tier,
        packaging_allowed=packaging_allowed,
        annual_submission_cap=cap,
    )
    store.agencies[row["id"]] = row
    return object_response(d.serialize_agency(row), 201)


@bp.get("/agencies/<agency_id>")
@authorize(ROLE_PLATFORM_ADMIN, ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS, ROLE_AGENCY_REP)
def read_agency(principal, agency_id):
    row = d.get_agency(agency_id)
    return object_response(d.serialize_agency(row))


# ---------------------------------------------------------------------------
# slates
# ---------------------------------------------------------------------------

@bp.post("/slates")
@authorize(ROLE_PLATFORM_ADMIN)
def create_slate(principal):
    body = require_body(json_body())
    row = new_row(
        platform=v_enum(body, "platform", d.PLATFORMS),
        season_year=v_int(body, "season_year", minimum=2026, maximum=2035),
        total_dev_budget_cents=v_int(body, "total_dev_budget_cents", minimum=0),
        pattern_budget_per_episode_cents=v_int(
            body, "pattern_budget_per_episode_cents", minimum=1),
        license_fee_cap_per_episode_cents=v_int(
            body, "license_fee_cap_per_episode_cents", minimum=1),
        max_deficit_per_episode_cents=v_int(
            body, "max_deficit_per_episode_cents", minimum=0),
        episode_capacity=v_int(body, "episode_capacity", minimum=1),
        default_episode_count=v_int(body, "default_episode_count", minimum=1),
        max_backend_points_bps=v_int(body, "max_backend_points_bps",
                                     minimum=0, maximum=10000),
        max_concurrent_pilot_shoots=v_int(body, "max_concurrent_pilot_shoots", minimum=1),
    )
    store.slates[row["id"]] = row
    return object_response(d.serialize_slate(row), 201)


@bp.get("/slates/<slate_id>")
@authorize(ROLE_PLATFORM_ADMIN, ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS, ROLE_FINANCE)
def read_slate(principal, slate_id):
    row = d.get_slate(slate_id)
    return object_response(d.serialize_slate(row))


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------

@bp.post("/writers")
@authorize(ROLE_PLATFORM_ADMIN, ROLE_AGENCY_REP)
def create_writer(principal):
    body = json_body()
    # Validation 3 compares the submitted agency_id before existence (7/8).
    if principal.is_agency_rep:
        raw_agency_id = body.get("agency_id") if isinstance(body, dict) else None
        agency_scope_guard(principal, raw_agency_id)
    require_body(body)
    agency = d.get_agency(body.get("agency_id"))
    row = new_row(
        full_name=v_string(body, "full_name", max_len=120),
        agency_id=agency["id"],
        guild_minimum_tier=v_enum(body, "guild_minimum_tier", d.GUILD_TIERS),
        quote_per_step_cents=v_int(body, "quote_per_step_cents", minimum=0),
    )
    store.writers[row["id"]] = row
    return object_response(d.serialize_writer(row), 201)


@bp.get("/writers/<writer_id>")
@authorize(ROLE_PLATFORM_ADMIN, ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS, ROLE_AGENCY_REP)
def read_writer(principal, writer_id):
    row = d.get_writer(writer_id)
    agency_scope_guard(principal, row["agency_id"])
    return object_response(d.serialize_writer(row))


@bp.get("/writers")
@authorize(ROLE_PLATFORM_ADMIN, ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS, ROLE_AGENCY_REP)
def list_writers(principal):
    agency_id = request.args.get("agency_id")
    exclusivity = request.args.get("exclusivity_status")
    if principal.is_agency_rep:
        if agency_id is not None and agency_id != principal.user_id:
            raise ApiError("ERR_AGENCY_SCOPE_VIOLATION")
        agency_id = principal.user_id

    rows = d.ordered(list(store.writers.values()))
    if agency_id is not None:
        rows = [r for r in rows if r["agency_id"] == agency_id]
    if exclusivity is not None:
        rows = [r for r in rows if d.writer_exclusivity_status(r) == exclusivity]
    return paginated(rows, d.serialize_writer)


# ---------------------------------------------------------------------------
# holding deals
# ---------------------------------------------------------------------------

def _terms_overlap(start_a, end_a, start_b, end_b):
    """Half-open [start, end) intersection."""
    return start_a < end_b and start_b < end_a


@bp.post("/holding-deals")
@authorize(ROLE_BUSINESS_AFFAIRS)
def create_holding_deal(principal):
    body = require_body(json_body())
    writer = d.get_writer(body.get("writer_id"))
    slate = d.get_slate(body.get("slate_id"))
    annual_cost_cents = v_int(body, "annual_cost_cents", minimum=1)
    term_start = v_date(body, "term_start_date")
    term_end = v_date(body, "term_end_date")
    if term_end <= term_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "term_end_date must be strictly after term_start_date.")

    # 29 -- overlapping active hold on the same writer.
    for existing in store.holding_deals.values():
        if existing["writer_id"] != writer["id"] or existing["status"] != "ACTIVE":
            continue
        if _terms_overlap(term_start, term_end,
                          existing["term_start_date"], existing["term_end_date"]):
            raise ApiError("ERR_HOLDING_DEAL_OVERLAP")

    # 45 -- the funding slate must cover the annual cost.
    if d.slate_available_dev_cents(slate) < annual_cost_cents:
        raise ApiError("ERR_SLATE_DEV_BUDGET_EXCEEDED")

    row = new_row(
        writer_id=writer["id"],
        slate_id=slate["id"],
        annual_cost_cents=annual_cost_cents,
        term_start_date=term_start,
        term_end_date=term_end,
        status="ACTIVE",
        termination_reason=None,
    )
    store.holding_deals[row["id"]] = row
    touch(slate)
    touch(writer)
    return object_response(d.serialize_holding_deal(row), 201)


@bp.get("/holding-deals/<deal_id>")
@authorize(ROLE_PLATFORM_ADMIN, ROLE_BUSINESS_AFFAIRS, ROLE_DEV_EXEC)
def read_holding_deal(principal, deal_id):
    row = d.get_holding_deal(deal_id)
    return object_response(d.serialize_holding_deal(row))


@bp.get("/holding-deals")
@authorize(ROLE_PLATFORM_ADMIN, ROLE_BUSINESS_AFFAIRS, ROLE_DEV_EXEC)
def list_holding_deals(principal):
    rows = d.ordered(list(store.holding_deals.values()))
    writer_id = request.args.get("writer_id")
    slate_id = request.args.get("slate_id")
    status = request.args.get("status")
    if writer_id is not None:
        rows = [r for r in rows if r["writer_id"] == writer_id]
    if slate_id is not None:
        rows = [r for r in rows if r["slate_id"] == slate_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, d.serialize_holding_deal)


@bp.post("/holding-deals/<deal_id>/terminate")
@authorize(ROLE_BUSINESS_AFFAIRS)
def terminate_holding_deal(principal, deal_id):
    row = d.get_holding_deal(deal_id)
    body = require_body(json_body())
    reason = v_string(body, "termination_reason", max_len=500)
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_DEAL_STATE")
    row["status"] = "TERMINATED"
    row["termination_reason"] = reason
    touch(row)
    touch(store.slates[row["slate_id"]])
    writer = store.writers.get(row["writer_id"])
    if writer is not None:
        touch(writer)
    return object_response(d.serialize_holding_deal(row))


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@authorize(ROLE_PLATFORM_ADMIN)
def set_clock(principal):
    from validators import v_instant
    body = require_body(json_body())
    instant = v_instant(body, "to_iso8601")
    store.set_clock(instant)
    from store import iso3
    return object_response({"current_utc": iso3(store.now())})
