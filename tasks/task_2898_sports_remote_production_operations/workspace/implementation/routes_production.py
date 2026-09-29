"""Productions (open, read, list, truck assignment, wrap, settle) and the venue-survey loop."""

from flask import Blueprint

import domain
import store
from core import (
    ApiError,
    OPERATOR_ROLES,
    Payload,
    ROLE_LEAGUE_OPERATIONS,
    ROLE_PRODUCTION_MANAGER,
    ROLE_TECHNICAL_DIRECTOR,
    ROLE_UNION_STEWARD,
    actor_id,
    invalid,
    now_utc,
    page_result,
    query_enum,
    query_string,
    require_roles,
    respond_object,
)

bp = Blueprint("production", __name__, url_prefix="/broadcast-ops")


def check_occ(production, expected_version):
    if expected_version != production["version"]:
        raise ApiError(
            "ERR_STALE_PRODUCTION_VERSION",
            "expected_production_version does not match the production's current version.",
            412,
        )


def require_open_production(production):
    """Rung 19 for the endpoints that require a stage below ON_AIR."""
    if production["status"] in domain.CLOSED_PRODUCTION_STATUSES:
        raise ApiError(
            "ERR_PRODUCTION_STATE_INVALID",
            "The production stage does not permit this operation.",
            409,
        )


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------
@bp.post("/productions")
@require_roles(ROLE_PRODUCTION_MANAGER)
def create_production():
    body = Payload()
    event_tier = body.enum("event_tier", domain.EVENT_TIERS)
    league_code = body.string("league_code")
    venue_name = body.string("venue_name")
    capacity = body.integer("venue_power_capacity_amps", minimum=1)
    roof = body.enum("venue_roof_type", domain.ROOF_TYPES)
    curfew = body.instant("venue_curfew_utc")
    start = body.instant("scheduled_start_utc")
    end = body.instant("scheduled_end_utc")
    budget = body.integer("labor_budget_total_cents", minimum=0)
    if end <= start:
        raise invalid("scheduled_end_utc must be strictly later than scheduled_start_utc.")
    if curfew <= end:
        raise invalid("venue_curfew_utc must be strictly later than scheduled_end_utc.")

    row = store.new_row(
        event_tier=event_tier,
        league_code=league_code,
        venue_name=venue_name,
        venue_power_capacity_amps=capacity,
        venue_roof_type=roof,
        venue_curfew_utc=curfew,
        scheduled_start_utc=start,
        scheduled_end_utc=end,
        truck_id=None,
        labor_budget_total_cents=budget,
        labor_committed_cents=0,
        labor_available_cents=budget,
        labor_variance_cents=0,
        readiness_score_preflight=0,
        readiness_score_certified=0,
        required_crew_positions=domain.REQUIRED_CREW_POSITIONS[event_tier],
        required_validated_preps=domain.REQUIRED_VALIDATED_PREPS[event_tier],
        settlement_total_cents=0,
        overrun_fee_cents=0,
        wrapped_by_user_id=None,
        status="PLANNED",
    )
    store.PRODUCTIONS[row["id"]] = row
    row["readiness_score_preflight"] = domain.readiness_preflight(row)
    row["readiness_score_certified"] = domain.readiness_certified(row)
    return respond_object(domain.production_json(row), 201)


@bp.get("/productions/<production_id>")
@require_roles(*OPERATOR_ROLES)
def read_production(production_id):
    return respond_object(domain.production_json(store.find_production(production_id)))


@bp.get("/productions")
@require_roles(*OPERATOR_ROLES)
def list_productions():
    truck_id = query_string("truck_id")
    status = query_enum("status", domain.PRODUCTION_STATUSES)
    tier = query_enum("event_tier", domain.EVENT_TIERS)
    rows = store.ordered(store.PRODUCTIONS)
    if truck_id is not None:
        rows = [r for r in rows if r["truck_id"] == truck_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if tier is not None:
        rows = [r for r in rows if r["event_tier"] == tier]
    return page_result(rows, domain.production_json)


@bp.post("/productions/<production_id>/truck-assignment")
@require_roles(ROLE_PRODUCTION_MANAGER)
def assign_truck(production_id):
    body = Payload()
    truck_id = body.string("truck_id")
    expected = body.integer("expected_production_version")

    production = store.find_production(production_id)
    truck = store.find_truck(truck_id)
    check_occ(production, expected)
    require_open_production(production)
    if truck["status"] not in ("AVAILABLE", "ASSIGNED"):
        raise ApiError(
            "ERR_TRUCK_STATE_INVALID",
            "The truck status does not permit an assignment.",
            409,
        )

    survey = domain.approved_survey(production)
    if survey is not None:
        if (
            truck["power_draw_amps"] + survey["total_power_draw_amps"]
            > production["venue_power_capacity_amps"]
        ):
            raise ApiError(
                "ERR_VENUE_POWER_INSUFFICIENT",
                "The venue cannot power the truck plus the approved camera plot.",
                422,
            )
    if domain.TIER_ORDER[truck["tier_rating"]] > domain.TIER_ORDER[production["event_tier"]]:
        raise ApiError(
            "ERR_TRUCK_TIER_INSUFFICIENT",
            "The truck's tier rating does not cover this event tier.",
            422,
        )
    if survey is not None and survey["camera_position_count"] > truck["camera_channel_capacity"]:
        raise ApiError(
            "ERR_TRUCK_CHANNEL_CAPACITY_EXCEEDED",
            "The approved camera plot exceeds the truck's camera-channel capacity.",
            422,
        )
    if domain.travel_window_conflict(production, truck):
        raise ApiError(
            "ERR_TRUCK_TRAVEL_WINDOW_CONFLICT",
            "The truck's occupation window overlaps another remote it already holds.",
            409,
        )

    previous_id = production["truck_id"]
    store.touch(production)
    production["truck_id"] = truck["id"]
    if previous_id is not None and previous_id != truck["id"]:
        previous = store.TRUCKS.get(previous_id)
        if previous is not None:
            still_held = False
            for other in store.ordered(store.PRODUCTIONS):
                if other["id"] == production["id"]:
                    continue
                if other["truck_id"] == previous["id"] and other["status"] not in (
                    "WRAPPED",
                    "SETTLED",
                ):
                    still_held = True
                    break
            if not still_held:
                store.set_fields(previous, status="AVAILABLE")
    store.set_fields(truck, status="ASSIGNED")
    domain.recompute_production_stage(production)
    return respond_object(domain.production_json(production))


@bp.post("/productions/<production_id>/wrap")
@require_roles(ROLE_PRODUCTION_MANAGER)
def wrap_production(production_id):
    production = store.find_production(production_id)
    show = domain.production_show(production)
    if production["status"] != "ON_AIR" or show is None or show["air_status"] != "OFF_AIR":
        raise ApiError(
            "ERR_PRODUCTION_STATE_INVALID",
            "Wrap requires an ON_AIR production whose show execution has reached OFF_AIR.",
            409,
        )

    for call in domain.production_calls(production):
        if call["status"] != "ACCEPTED":
            continue
        call["actual_release_utc"] = call["scheduled_release_utc"]
        call["meal_break_start_utc"] = None
        total, units = domain.settled_cost(call, production)
        store.set_fields(
            call, status="RELEASED", settled_total_cents=total, meal_penalty_units=units
        )
        member = store.CREW_MEMBERS.get(call["crew_member_id"])
        if member is not None:
            store.set_fields(
                member,
                lifetime_meal_penalty_units=member["lifetime_meal_penalty_units"] + units,
            )

    if production["truck_id"] is not None:
        truck = store.TRUCKS.get(production["truck_id"])
        if truck is not None:
            domain.accrue_truck_hours(truck, show["air_minutes_total"])
            store.set_fields(truck, status="IN_TRANSIT")

    store.set_fields(production, wrapped_by_user_id=actor_id(), status="WRAPPED")
    domain.recompute_production_stage(production)
    return respond_object(domain.production_json(production))


@bp.post("/productions/<production_id>/settle")
@require_roles(ROLE_UNION_STEWARD)
def settle_production(production_id):
    production = store.find_production(production_id)
    if production["wrapped_by_user_id"] is not None and actor_id() == production["wrapped_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The operator who wrapped the production may not settle it.",
            403,
        )
    if production["status"] != "WRAPPED":
        raise ApiError(
            "ERR_PRODUCTION_STATE_INVALID", "Settlement requires a WRAPPED production.", 409
        )

    released = [c for c in domain.production_calls(production) if c["status"] == "RELEASED"]
    labor_subtotal = sum((c["settled_total_cents"] or 0) for c in released)
    provisional_subtotal = sum(c["provisional_total_cents"] for c in released)

    show = domain.production_show(production)
    overrun_minutes = 0
    if show is not None:
        overrun_minutes = show["weather_hold_minutes"] + show["extended_play_minutes"]
    overrun_fee = domain.overrun_rate(labor_subtotal) * overrun_minutes

    store.set_fields(
        production,
        overrun_fee_cents=overrun_fee,
        settlement_total_cents=labor_subtotal + overrun_fee,
        labor_variance_cents=labor_subtotal - provisional_subtotal,
        status="SETTLED",
    )

    for booking in domain.production_bookings(production):
        if booking["status"] in domain.ACTIVE_BOOKING_STATUSES:
            store.set_fields(booking, status="RELEASED")
            path = store.PATHS.get(booking["path_id"])
            if path is not None:
                domain.recompute_path_aggregates(path)
    domain.recompute_production_scalars(production)
    return respond_object(domain.production_json(production))


# ---------------------------------------------------------------------------
# VenueSurvey
# ---------------------------------------------------------------------------
@bp.post("/venue-surveys")
@require_roles(ROLE_TECHNICAL_DIRECTOR)
def create_survey():
    body = Payload()
    production_id = body.string("production_id")
    surveyor_name = body.string("surveyor_name")
    fiber_drops = body.integer("fiber_drops_required", minimum=0)

    production = store.find_production(production_id)
    require_open_production(production)

    existing = domain.production_surveys(production)
    for row in existing:
        if row["status"] in domain.OPEN_SURVEY_STATUSES:
            raise ApiError(
                "ERR_SURVEY_ALREADY_OPEN",
                "The production already has a survey in flight.",
                409,
            )

    survey = store.new_row(
        production_id=production["id"],
        surveyor_name=surveyor_name,
        fiber_drops_required=fiber_drops,
        revision=1,
        submitted_by_user_id=None,
        reviewed_by_user_id=None,
        camera_position_count=0,
        total_cable_run_feet=0,
        total_signal_loss_db=0,
        total_power_draw_amps=0,
        power_headroom_amps=production["venue_power_capacity_amps"],
        status="DRAFT",
    )
    store.SURVEYS[survey["id"]] = survey

    superseded = False
    for row in existing:
        if row["status"] == "APPROVED":
            store.set_fields(row, status="SUPERSEDED")
            superseded = True
    if superseded:
        if production["status"] == "SURVEYED":
            store.set_fields(production, status="PLANNED")
            domain.abort_scheduled_rehearsals(production)
            domain.set_readiness_hold(production, True)
        domain.recompute_production_stage(production)
    return respond_object(domain.survey_json(survey), 201)


@bp.get("/venue-surveys/<survey_id>")
@require_roles(*OPERATOR_ROLES)
def read_survey(survey_id):
    return respond_object(domain.survey_json(store.find_survey(survey_id)))


@bp.get("/productions/<production_id>/venue-surveys")
@require_roles(*OPERATOR_ROLES)
def list_production_surveys(production_id):
    production = store.find_production(production_id)
    status = query_enum("status", domain.SURVEY_STATUSES)
    rows = domain.production_surveys(production)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page_result(rows, domain.survey_json)


@bp.post("/venue-surveys/<survey_id>/camera-positions")
@require_roles(ROLE_TECHNICAL_DIRECTOR)
def create_camera_position(survey_id):
    body = Payload()
    label = body.string("label")
    position_type = body.enum("position_type", domain.POSITION_TYPES)
    cable_run_feet = body.integer("cable_run_feet", minimum=1)
    power_draw_amps = body.integer("power_draw_amps", minimum=0)

    survey = store.find_survey(survey_id)
    if survey["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError(
            "ERR_SURVEY_STATE_INVALID",
            "Camera positions may only be added to a DRAFT or CHANGES_REQUESTED survey.",
            409,
        )

    if survey["status"] == "CHANGES_REQUESTED":
        store.set_fields(
            survey,
            status="DRAFT",
            revision=survey["revision"] + 1,
            submitted_by_user_id=None,
        )

    position = store.new_row(
        versioned=False,
        survey_id=survey["id"],
        label=label,
        position_type=position_type,
        cable_run_feet=cable_run_feet,
        power_draw_amps=power_draw_amps,
        signal_loss_db=domain.position_signal_loss(cable_run_feet),
        requires_operator=position_type in domain.OPERATOR_POSITION_TYPES,
    )
    store.CAMERA_POSITIONS[position["id"]] = position
    domain.recompute_survey_aggregates(survey)
    return respond_object(domain.camera_position_json(position), 201)


@bp.get("/venue-surveys/<survey_id>/camera-positions")
@require_roles(*OPERATOR_ROLES)
def list_camera_positions(survey_id):
    survey = store.find_survey(survey_id)
    position_type = query_enum("position_type", domain.POSITION_TYPES)
    rows = [
        r for r in store.ordered(store.CAMERA_POSITIONS) if r["survey_id"] == survey["id"]
    ]
    if position_type is not None:
        rows = [r for r in rows if r["position_type"] == position_type]
    return page_result(rows, domain.camera_position_json)


@bp.post("/venue-surveys/<survey_id>/submit")
@require_roles(ROLE_TECHNICAL_DIRECTOR)
def submit_survey(survey_id):
    survey = store.find_survey(survey_id)
    if survey["status"] != "DRAFT":
        raise ApiError(
            "ERR_SURVEY_STATE_INVALID", "Only a DRAFT survey may be submitted.", 409
        )
    if survey["revision"] > domain.MAX_SURVEY_REVISIONS:
        raise ApiError(
            "ERR_SURVEY_REVISION_LIMIT",
            "The survey has exhausted its revision allowance.",
            409,
        )
    if survey["camera_position_count"] == 0:
        raise ApiError(
            "ERR_SURVEY_NO_CAMERA_POSITIONS",
            "A survey with an empty camera plot cannot be submitted.",
            422,
        )
    if domain.survey_total_loss_decimal(survey) > domain.MAX_SIGNAL_LOSS_BUDGET_DB:
        raise ApiError(
            "ERR_SIGNAL_LOSS_BUDGET_EXCEEDED",
            "The camera plot exceeds the signal-loss budget.",
            422,
        )
    if survey["power_headroom_amps"] < 0:
        raise ApiError(
            "ERR_VENUE_POWER_INSUFFICIENT",
            "The venue cannot power the camera plot.",
            422,
        )
    store.set_fields(survey, status="SUBMITTED", submitted_by_user_id=actor_id())
    return respond_object(domain.survey_json(survey))


@bp.post("/venue-surveys/<survey_id>/review")
@require_roles(ROLE_LEAGUE_OPERATIONS)
def review_survey(survey_id):
    body = Payload()
    decision = body.enum("decision", ("APPROVE", "REQUEST_CHANGES"))
    body.string("notes", required=False, allow_blank=True)

    survey = store.find_survey(survey_id)
    if survey["submitted_by_user_id"] is not None and actor_id() == survey["submitted_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The operator who submitted the survey may not review it.",
            403,
        )
    if survey["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_SURVEY_STATE_INVALID", "Only a SUBMITTED survey may be reviewed.", 409
        )

    production = store.PRODUCTIONS.get(survey["production_id"])
    if decision == "APPROVE":
        store.set_fields(survey, status="APPROVED", reviewed_by_user_id=actor_id())
        if production is not None:
            if production["status"] == "PLANNED":
                store.set_fields(production, status="SURVEYED")
            domain.recompute_production_stage(production)
    else:
        store.set_fields(survey, status="CHANGES_REQUESTED", reviewed_by_user_id=actor_id())
    return respond_object(domain.survey_json(survey))
