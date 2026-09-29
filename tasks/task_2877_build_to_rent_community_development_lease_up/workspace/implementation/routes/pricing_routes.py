"""Market rent schedule publication and concession programs (PRD sections 3.5, 3.6)."""
from __future__ import annotations

from flask import Blueprint

import repo
import serializers
from db import PRODUCT_TYPES, mark, mark_created, new_record, set_field, set_instant, store
from errors import ApiError
from middleware import acting_user_id, endpoint
from response import created
from services import community as community_service, pricing
from validation import (MISSING, bad, body, opt_int, raw_id, req_bool, req_enum, req_instant,
                        req_int, req_str)

bp = Blueprint("pricing", __name__)

REPRICING_MODES = ("MANUAL", "ABSORPTION_INDEXED")
CONCESSION_TIERS = ("NONE", "LIGHT", "MODERATE", "AGGRESSIVE")
AMORTIZATION_MODES = ("STRAIGHT_LINE_NET_EFFECTIVE", "UPFRONT_FREE_RENT")
PROGRAM_CODE_MIN = 2
PROGRAM_CODE_MAX = 24
MAX_FREE_WEEKS = 12


def _check_occ(community, payload):
    """expected_community_version is required on exactly these two writes (PRD 2.7)."""
    expected = req_int(payload, "expected_community_version", minimum=0)
    if expected != community["version"]:
        raise ApiError("ERR_STALE_COMMUNITY_VERSION")


@bp.post("/market-rent-schedules")
@endpoint("AssetManager")
def publish_schedule():
    payload = body()
    community_ref = raw_id(payload, "community_id")
    community = repo.get_community(community_ref) if community_ref is not MISSING else None
    if community is None:
        raise bad("community_id is required")

    product_type = req_enum(payload, "product_type", PRODUCT_TYPES)
    effective_from = req_instant(payload, "effective_from")
    repricing_mode = req_enum(payload, "repricing_mode", REPRICING_MODES)
    manual_rent = None
    if repricing_mode == "MANUAL":
        manual_rent = opt_int(payload, "asking_rent_cents", None, minimum=0)
        if manual_rent is None or manual_rent < 1:
            raise bad("a MANUAL publication needs asking_rent_cents of at least 1")
    _check_occ(community, payload)

    if repricing_mode == "MANUAL":
        asking_rent_cents = manual_rent
        applied_growth_bps = 0
    else:
        baseline = pricing.baseline_schedule(community, product_type)
        if baseline is None:
            raise ApiError("ERR_RENT_SCHEDULE_NOT_FOUND",
                           "No schedule exists for this community and product type")
        if baseline["status"] != "PUBLISHED":
            raise ApiError("ERR_SCHEDULE_ALREADY_SUPERSEDED")
        review = pricing.latest_review(community, product_type)
        if review is None:
            raise ApiError("ERR_ABSORPTION_REVIEW_NOT_FOUND")
        applied_growth_bps = review["recommended_growth_bps"]
        step = pricing.repricing_step_cents(baseline["asking_rent_cents"], applied_growth_bps)
        asking_rent_cents = baseline["asking_rent_cents"] + step

    community_service.require_not_frozen(community)
    for existing in repo.schedules_of_community(community):
        if (existing["product_type"] == product_type
                and existing["_effective_from"] == effective_from):
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "A schedule for this community, product type and effective_from exists")
    if asking_rent_cents < 1:
        raise bad("the repriced asking_rent_cents would fall below 1 cent")

    superseded = [s for s in repo.schedules_of_community(community)
                  if s["product_type"] == product_type and s["status"] == "PUBLISHED"]
    schedule = new_record("MarketRentSchedule", {
        "community_id": community["id"],
        "product_type": product_type,
        "effective_from": None,
        "repricing_mode": repricing_mode,
        "asking_rent_cents": asking_rent_cents,
        "applied_growth_bps": applied_growth_bps,
        "status": "PUBLISHED",
        "superseded_at": None,
        "_superseded_at": None,
        "published_by_user_id": acting_user_id(),
    })
    store.schedules[schedule["id"]] = schedule
    mark_created(schedule)
    set_instant(schedule, "effective_from", effective_from)
    for prior in superseded:
        set_field(prior, "status", "SUPERSEDED")
        set_instant(prior, "superseded_at", store.now())
    # Publication retires a child of the community, so the community's version moves.
    mark(community)
    community_service.recompute_community(community)
    return created(serializers.schedule, schedule)


@bp.post("/concession-programs")
@endpoint("AssetManager")
def create_program():
    payload = body()
    community_ref = raw_id(payload, "community_id")
    community = repo.get_community(community_ref) if community_ref is not MISSING else None
    if community is None:
        raise bad("community_id is required")

    program_code = req_str(payload, "program_code", PROGRAM_CODE_MIN, PROGRAM_CODE_MAX)
    tier = req_enum(payload, "tier", CONCESSION_TIERS)
    free_weeks = req_int(payload, "free_weeks", 0, MAX_FREE_WEEKS)
    amortization_mode = req_enum(payload, "amortization_mode", AMORTIZATION_MODES)
    eligible = payload.get("eligible_product_types")
    if "eligible_product_types" not in payload or eligible is None:
        raise bad("eligible_product_types is required")
    if not isinstance(eligible, list) or not eligible:
        raise bad("eligible_product_types must be a non-empty array")
    for member in eligible:
        if member not in PRODUCT_TYPES:
            raise bad("eligible_product_types must be a subset of %s"
                      % ", ".join(PRODUCT_TYPES))
    max_budget_cents = req_int(payload, "max_budget_cents", minimum=0)
    restricted_posture_eligible = req_bool(payload, "restricted_posture_eligible", False)
    _check_occ(community, payload)

    # Program creation is refused while frozen and, uniquely, also while restricted.
    community_service.require_open(community)
    for existing in repo.programs_of_community(community):
        if existing["program_code"] == program_code:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "program_code must be unique within the community")

    prior_active = [p for p in repo.programs_of_community(community) if p["status"] == "ACTIVE"]
    program = new_record("ConcessionProgram", {
        "community_id": community["id"],
        "program_code": program_code,
        "tier": tier,
        "free_weeks": free_weeks,
        "amortization_mode": amortization_mode,
        "eligible_product_types": list(eligible),
        "restricted_posture_eligible": restricted_posture_eligible,
        "max_budget_cents": max_budget_cents,
        "committed_cents": 0,
        "status": "ACTIVE",
        "superseded_at": None,
        "_superseded_at": None,
    })
    store.programs[program["id"]] = program
    mark_created(program)
    for prior in prior_active:
        set_field(prior, "status", "SUPERSEDED")
        set_instant(prior, "superseded_at", store.now())
    mark(community)
    community_service.recompute_community(community)
    return created(serializers.program, program)
