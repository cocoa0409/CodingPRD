"""Pilot orders, the two contingency dimensions, wrap and audience research."""

from flask import Blueprint, request

import domain as d
from auth import (ROLE_BUSINESS_AFFAIRS, ROLE_DEV_EXEC, ROLE_FINANCE,
                  ROLE_PLATFORM_ADMIN, ROLE_RESEARCH, authorize)
from errors import ApiError
from responses import object_response, paginated
from store import new_row, store, touch
from validators import (json_body, peek, require_body, v_date, v_decimal, v_enum,
                        v_int, v_string)

bp = Blueprint("pilot", __name__)


@bp.post("/pilot-orders")
@authorize(ROLE_DEV_EXEC)
def create_pilot_order(principal):
    body = require_body(json_body())
    project = d.get_project(body.get("project_id"))

    budget_cents = v_int(body, "budget_cents", minimum=1)
    shoot_start = v_date(body, "shoot_start_date")
    shoot_end = v_date(body, "shoot_end_date")
    casting_deadline = v_date(body, "casting_deadline_date")
    location_deadline = v_date(body, "location_deadline_date")
    if shoot_end < shoot_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "shoot_end_date must be on or after shoot_start_date.")

    # 11 -- the project must have reached SCRIPT_COMPLETE.
    if project["dev_status"] != "SCRIPT_COMPLETE":
        raise ApiError("ERR_INVALID_PROJECT_STATE")

    slate = d.slate_of_project(project)

    # 33 -- posture.
    d.require_slate_not_locked(slate)

    # 39 -- budget tolerance against the slate's pattern budget.
    variance_bps = d.budget_variance_bps_for(
        budget_cents, slate["pattern_budget_per_episode_cents"])
    if variance_bps > d.MAX_PILOT_VARIANCE_BPS:
        raise ApiError("ERR_PILOT_BUDGET_ABOVE_PATTERN")

    # 40 -- stage capacity, counting the new order.
    live = 0
    for pilot in store.pilot_orders.values():
        if pilot["production_status"] not in ("ORDERED", "GREEN_TO_SHOOT"):
            continue
        other_project = store.projects.get(pilot["project_id"])
        if other_project is not None and other_project["slate_id"] == slate["id"]:
            live += 1
    if live + 1 > slate["max_concurrent_pilot_shoots"]:
        raise ApiError("ERR_STAGE_CAPACITY_EXCEEDED")

    # 45 -- the slate must cover the pilot budget.
    if d.slate_available_dev_cents(slate) < budget_cents:
        raise ApiError("ERR_SLATE_DEV_BUDGET_EXCEEDED")

    row = new_row(
        project_id=project["id"],
        budget_cents=budget_cents,
        shoot_start_date=shoot_start,
        shoot_end_date=shoot_end,
        casting_deadline_date=casting_deadline,
        location_deadline_date=location_deadline,
        casting_status="PENDING",
        location_status="PENDING",
        production_status="ORDERED",
        collapsed_reason=None,
    )
    store.pilot_orders[row["id"]] = row

    project["dev_status"] = "PILOT_ORDERED"
    touch(project)
    touch(slate)
    return object_response(d.serialize_pilot_order(row), 201)


@bp.get("/pilot-orders/<pilot_id>")
@authorize(ROLE_PLATFORM_ADMIN, ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS, ROLE_RESEARCH,
           ROLE_FINANCE)
def read_pilot_order(principal, pilot_id):
    row = d.get_pilot_order(pilot_id)
    return object_response(d.serialize_pilot_order(row))


@bp.post("/pilot-orders/<pilot_id>/contingency-clearances")
@authorize(ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS)
def clear_contingency(principal, pilot_id):
    body = json_body()
    # 5 -- WAIVED is reserved to BusinessAffairs, and it outranks path existence.
    if peek(body, "resolution") == "WAIVED" and principal.role != ROLE_BUSINESS_AFFAIRS:
        raise ApiError("ERR_UNAUTHORIZED")

    pilot = d.get_pilot_order(pilot_id)
    require_body(body)
    kind = v_enum(body, "kind", d.CONTINGENCY_KINDS)
    resolution = v_enum(body, "resolution", d.CONTINGENCY_RESOLUTIONS)
    v_string(body, "note", required=False, max_len=500, allow_null=True, default=None)

    # 14 -- only a live pilot takes a clearance.
    if pilot["production_status"] not in ("ORDERED", "GREEN_TO_SHOOT"):
        raise ApiError("ERR_INVALID_PILOT_ORDER_STATE")

    field = "casting_status" if kind == "CASTING" else "location_status"
    other_field = "location_status" if kind == "CASTING" else "casting_status"

    # 15 -- the named dimension must still be PENDING.
    if pilot[field] != "PENDING":
        raise ApiError("ERR_CONTINGENCY_ALREADY_RESOLVED")

    pilot[field] = resolution

    if resolution == "FAILED":
        d.cascade_pilot_collapse(pilot, kind)
        return object_response(d.serialize_pilot_order(pilot))

    if pilot[other_field] in ("SATISFIED", "WAIVED") \
            and pilot["production_status"] == "ORDERED":
        pilot["production_status"] = "GREEN_TO_SHOOT"
    touch(pilot)
    return object_response(d.serialize_pilot_order(pilot))


@bp.post("/pilot-orders/<pilot_id>/wrap")
@authorize(ROLE_DEV_EXEC)
def wrap_pilot(principal, pilot_id):
    pilot = d.get_pilot_order(pilot_id)
    if pilot["production_status"] != "GREEN_TO_SHOOT":
        raise ApiError("ERR_INVALID_PILOT_ORDER_STATE")
    # 31 -- the shoot window must have elapsed.
    if store.today() < pilot["shoot_end_date"]:
        raise ApiError("ERR_SHOOT_WINDOW_NOT_ELAPSED")

    pilot["production_status"] = "WRAPPED"
    touch(pilot)
    project = d.project_of_pilot(pilot)
    project["dev_status"] = "PILOT_DELIVERED"
    touch(project)
    return object_response(d.serialize_pilot_order(pilot))


# ---------------------------------------------------------------------------
# audience research
# ---------------------------------------------------------------------------

@bp.post("/pilot-orders/<pilot_id>/test-screenings")
@authorize(ROLE_RESEARCH)
def field_screening(principal, pilot_id):
    pilot = d.get_pilot_order(pilot_id)
    body = require_body(json_body())
    panel_size = v_int(body, "panel_size", minimum=1)
    overall = v_int(body, "overall_score", minimum=0, maximum=100)
    intent = v_int(body, "intent_to_view_score", minimum=0, maximum=100)
    appeal = v_int(body, "appeal_score", minimum=0, maximum=100)
    comp_norm_index = v_decimal(body, "comp_norm_index", minimum="50.0",
                                maximum="150.0", max_places=1)
    expected_version = v_int(body, "expected_pilot_order_version", minimum=0)

    # 14 -- research is fielded only on a WRAPPED pilot.
    if pilot["production_status"] != "WRAPPED":
        raise ApiError("ERR_INVALID_PILOT_ORDER_STATE")

    # 22 -- stale-read protection on the pilot order.
    if expected_version != pilot["version"]:
        raise ApiError("ERR_STALE_PILOT_ORDER_VERSION")

    weighted_raw, norm_adjusted = d.weighted_test_score(
        overall, intent, appeal, comp_norm_index)

    row = new_row(
        pilot_order_id=pilot["id"],
        panel_size=panel_size,
        overall_score=overall,
        intent_to_view_score=intent,
        appeal_score=appeal,
        comp_norm_index=comp_norm_index,
        weighted_raw_score=weighted_raw,
        norm_adjusted_score=norm_adjusted,
        status="FIELDED",
        certified_at=None,
    )
    store.screenings[row["id"]] = row

    d.supersede_screenings(pilot, row["id"])
    touch(pilot)
    return object_response(d.serialize_screening(row), 201)


@bp.get("/pilot-orders/<pilot_id>/test-screenings")
@authorize(ROLE_PLATFORM_ADMIN, ROLE_RESEARCH, ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS,
           ROLE_FINANCE)
def list_screenings(principal, pilot_id):
    pilot = d.get_pilot_order(pilot_id)
    rows = d.screenings_of_pilot(pilot)
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, d.serialize_screening)


@bp.post("/test-screenings/<screening_id>/certify")
@authorize(ROLE_RESEARCH)
def certify_screening(principal, screening_id):
    screening = d.get_screening(screening_id)
    # 16 -- only a FIELDED screening may be certified.
    if screening["status"] != "FIELDED":
        raise ApiError("ERR_INVALID_SCREENING_STATE")
    # 27 -- the panel must be large enough.
    if screening["panel_size"] < d.MIN_TEST_PANEL_SIZE:
        raise ApiError("ERR_TEST_SAMPLE_TOO_SMALL")
    screening["status"] = "CERTIFIED"
    screening["certified_at"] = store.now()
    touch(screening)
    return object_response(d.serialize_screening(screening))
