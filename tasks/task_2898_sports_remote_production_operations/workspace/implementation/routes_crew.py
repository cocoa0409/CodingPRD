"""Crew calls: union rules, the provisional reserve and the settled release."""

from flask import Blueprint

import domain
import store
from core import (
    ApiError,
    ALL_ROLES,
    OPERATOR_ROLES,
    Payload,
    ROLE_CREW_MEMBER,
    ROLE_PRODUCTION_MANAGER,
    actor_id,
    invalid,
    page_result,
    query_enum,
    query_string,
    require_roles,
    respond_object,
    whole_minutes,
)
from routes_production import check_occ, require_open_production

bp = Blueprint("crew", __name__, url_prefix="/broadcast-ops")


@bp.post("/crew-calls")
@require_roles(ROLE_PRODUCTION_MANAGER)
def create_crew_call():
    body = Payload()
    production_id = body.string("production_id")
    crew_member_id = body.string("crew_member_id")
    call_time = body.instant("call_time_utc")
    scheduled_release = body.instant("scheduled_release_utc")
    offer_rate = body.integer("offer_rate_cents", required=False, minimum=1)
    expected = body.integer("expected_production_version")

    # Rung 3: employment type decides the rate field. Skipped when the member does not
    # exist at all, so that an unknown member is reported as such at rung 9.
    candidate_member = (
        store.CREW_MEMBERS.get(crew_member_id) if isinstance(crew_member_id, str) else None
    )
    if candidate_member is not None:
        if candidate_member["employment_type"] == "FREELANCE" and offer_rate is None:
            raise invalid("offer_rate_cents is required for a FREELANCE crew member.")
        if candidate_member["employment_type"] == "STAFF" and offer_rate is not None:
            raise invalid("offer_rate_cents is forbidden for a STAFF crew member.")

    production = store.find_production(production_id)
    member = store.find_crew_member(crew_member_id)
    check_occ(production, expected)
    if scheduled_release <= call_time:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "scheduled_release_utc must be strictly later than call_time_utc.",
            422,
        )
    require_open_production(production)

    for other in domain.production_calls(production):
        if (
            other["crew_member_id"] == member["id"]
            and other["status"] in domain.LIVE_CALL_STATUSES
        ):
            raise ApiError(
                "ERR_DUPLICATE_CREW_CALL",
                "The member already holds a live call on this production.",
                409,
            )

    if production["event_tier"] not in member["certified_tiers"]:
        raise ApiError(
            "ERR_CREW_TIER_NOT_CERTIFIED",
            "The member is not certified for this event tier.",
            422,
        )

    prior = domain.prior_call_for_member(member["id"])
    turnaround = None
    if prior is not None:
        turnaround = whole_minutes(domain.reference_release(prior), call_time)
        if turnaround < domain.TURNAROUND_MINUTES:
            raise ApiError(
                "ERR_CREW_TURNAROUND_VIOLATION",
                "The member has not had the minimum 600-minute turnaround.",
                422,
            )

    effective_rate = offer_rate if offer_rate is not None else member["hourly_rate_cents"]
    call = store.new_row(
        production_id=production["id"],
        crew_member_id=member["id"],
        call_time_utc=call_time,
        scheduled_release_utc=scheduled_release,
        offer_rate_cents=offer_rate,
        effective_rate_cents=effective_rate,
        actual_release_utc=None,
        meal_break_start_utc=None,
        turnaround_minutes_before_call=turnaround,
        meal_penalty_units=0,
        provisional_total_cents=0,
        settled_total_cents=None,
        status="OFFERED",
    )
    provisional, units = domain.provisional_cost(call, production)
    call["provisional_total_cents"] = provisional
    call["meal_penalty_units"] = units

    committed = domain.labor_committed(production)
    if committed + provisional > production["labor_budget_total_cents"]:
        raise ApiError(
            "ERR_LABOR_BUDGET_EXCEEDED",
            "The call's provisional reserve would exceed the production's labor budget.",
            422,
        )

    store.CREW_CALLS[call["id"]] = call
    domain.recompute_production_stage(production)
    return respond_object(domain.crew_call_json(call), 201)


@bp.get("/crew-calls/<call_id>")
@require_roles(*ALL_ROLES)
def read_crew_call(call_id):
    return respond_object(domain.crew_call_json(store.find_crew_call(call_id)))


@bp.get("/crew-calls")
@require_roles(*ALL_ROLES)
def list_crew_calls():
    production_id = query_string("production_id")
    crew_member_id = query_string("crew_member_id")
    status = query_enum("status", domain.CALL_STATUSES)
    rows = store.ordered(store.CREW_CALLS)
    if production_id is not None:
        rows = [r for r in rows if r["production_id"] == production_id]
    if crew_member_id is not None:
        rows = [r for r in rows if r["crew_member_id"] == crew_member_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page_result(rows, domain.crew_call_json)


@bp.post("/crew-calls/<call_id>/respond")
@require_roles(ROLE_CREW_MEMBER)
def respond_crew_call(call_id):
    body = Payload()
    decision = body.enum("decision", ("ACCEPT", "DECLINE"))

    call = store.find_crew_call(call_id)
    if actor_id() != call["crew_member_id"]:
        raise ApiError(
            "ERR_NOT_CALL_OWNER", "Only the called member may answer this call.", 403
        )
    if call["status"] != "OFFERED":
        raise ApiError(
            "ERR_CREW_CALL_STATE_INVALID", "Only an OFFERED call may be answered.", 409
        )

    store.set_fields(call, status="ACCEPTED" if decision == "ACCEPT" else "DECLINED")
    production = store.PRODUCTIONS.get(call["production_id"])
    if production is not None:
        domain.recompute_production_stage(production)
    return respond_object(domain.crew_call_json(call))


@bp.post("/crew-calls/<call_id>/release")
@require_roles(ROLE_PRODUCTION_MANAGER)
def release_crew_call(call_id):
    body = Payload()
    actual_release = body.instant("actual_release_utc")
    meal_break = body.instant("meal_break_start_utc", required=False)

    call = store.find_crew_call(call_id)
    if actual_release <= call["call_time_utc"]:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "actual_release_utc must be strictly later than call_time_utc.",
            422,
        )
    if meal_break is not None and (
        meal_break < call["call_time_utc"] or meal_break > actual_release
    ):
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "meal_break_start_utc must lie within [call_time_utc, actual_release_utc].",
            422,
        )
    if call["status"] != "ACCEPTED":
        raise ApiError(
            "ERR_CREW_CALL_STATE_INVALID", "Only an ACCEPTED call may be released.", 409
        )

    production = store.PRODUCTIONS.get(call["production_id"])
    call["actual_release_utc"] = actual_release
    call["meal_break_start_utc"] = meal_break
    total, units = domain.settled_cost(call, production)
    store.set_fields(
        call, status="RELEASED", settled_total_cents=total, meal_penalty_units=units
    )
    member = store.CREW_MEMBERS.get(call["crew_member_id"])
    if member is not None:
        store.set_fields(
            member, lifetime_meal_penalty_units=member["lifetime_meal_penalty_units"] + units
        )
    if production is not None:
        domain.recompute_production_stage(production)
    return respond_object(domain.crew_call_json(call))


@bp.post("/crew-calls/<call_id>/cancel")
@require_roles(ROLE_PRODUCTION_MANAGER)
def cancel_crew_call(call_id):
    call = store.find_crew_call(call_id)
    if call["status"] not in ("OFFERED", "ACCEPTED"):
        raise ApiError(
            "ERR_CREW_CALL_STATE_INVALID",
            "Only an OFFERED or ACCEPTED call may be cancelled.",
            409,
        )
    store.set_fields(call, status="CANCELLED")
    production = store.PRODUCTIONS.get(call["production_id"])
    if production is not None:
        domain.recompute_production_stage(production)
    return respond_object(domain.crew_call_json(call))
