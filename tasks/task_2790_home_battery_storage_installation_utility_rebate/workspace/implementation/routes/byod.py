"""Bring-your-own-device: enrollments, dispatch events, participations, settlement."""

from flask import Blueprint, request

import cascades
import rules
import shape
import store
from calc import delivery_figures, settlement_money
from common import (
    EVENT_TYPES,
    RESERVE_SOC_MAX_PCT,
    SEASONS,
    TERRITORIES,
    dec,
    kw,
    ratio4,
)
from envelope import collection, created, ok
from errors import ApiError
from security import guard, path_ref, ref

bp = Blueprint("byod", __name__)

ENROLLMENT_READ_ROLES = (
    "CertifiedInstaller",
    "Homeowner",
    "UtilityInterconnectionReviewer",
)

DISPATCH_READ_ROLES = (
    "UtilityInterconnectionReviewer",
    "CertifiedInstaller",
    "Homeowner",
)


def _enrollment_state_error(enrollment, action):
    return ApiError(
        "ERR_ENROLLMENT_STATE_INVALID",
        "An enrollment in %s cannot be %s." % (enrollment["status"], action),
    )


def _event_state_error(event, action):
    return ApiError(
        "ERR_EVENT_STATE_INVALID",
        "An event in %s cannot be %s." % (event["status"], action),
    )


# --------------------------------------------------------------------------- #
# Enrollments
# --------------------------------------------------------------------------- #

@bp.route("/byod-enrollments", methods=["POST"])
@guard("CertifiedInstaller")
def create_enrollment(actor):
    payload = shape.body()
    system_id = payload.fk("battery_system_id")
    system = ref("battery_system", system_id)
    pledged_kw = payload.number("pledged_kw")
    reserve_soc_pct = payload.integer("reserve_soc_pct")
    season = payload.enum("season", SEASONS)

    if system["build_status"] != "COMMISSIONED" or system["grid_status"] != "PTO_GRANTED":
        raise ApiError(
            "ERR_ENROLLMENT_REQUIRES_PTO",
            "Only a commissioned bank with permission to operate may enroll.",
        )

    for existing in store.rows("enrollments"):
        if (
            existing["battery_system_id"] == system["id"]
            and existing["season"] == season
            and existing["status"] != "WITHDRAWN"
        ):
            raise ApiError(
                "ERR_DUPLICATE_ENROLLMENT",
                "The bank already holds a live enrollment for %s." % season,
            )

    if (
        pledged_kw <= 0
        or pledged_kw > dec(system["continuous_kw"])
        or reserve_soc_pct > RESERVE_SOC_MAX_PCT
    ):
        raise ApiError(
            "ERR_PLEDGE_EXCEEDS_CAPACITY",
            "The pledge or the reserve floor is outside the permitted band.",
        )

    record = store.insert(
        "enrollments",
        {
            "battery_system_id": system_id,
            "pledged_kw": kw(pledged_kw),
            "reserve_soc_pct": reserve_soc_pct,
            "season": season,
            "status": "PENDING_CONSENT",
            "consented_by_user_id": None,
            "consented_at": None,
            "cumulative_credited_kw": kw(0),
            "cumulative_pledged_kw": kw(0),
            "season_compliance_ratio": ratio4(0),
            "settled_event_count": 0,
            "performance_payment_cents_total": 0,
        },
    )
    return created(store.view(record))


@bp.route("/byod-enrollments/<enrollment_id>", methods=["GET"])
@guard(*ENROLLMENT_READ_ROLES)
def read_enrollment(actor, enrollment_id):
    record = path_ref(actor, "enrollment", enrollment_id)
    return ok(store.view(record))


@bp.route("/byod-enrollments", methods=["GET"])
@guard(*ENROLLMENT_READ_ROLES)
def list_enrollments(actor):
    records = store.where(
        "enrollments",
        battery_system_id=request.args.get("battery_system_id"),
        season=request.args.get("season"),
        status=request.args.get("status"),
    )
    return collection(records)


@bp.route("/byod-enrollments/<enrollment_id>/consent", methods=["POST"])
@guard("Homeowner")
def consent_enrollment(actor, enrollment_id):
    enrollment = path_ref(actor, "enrollment", enrollment_id)
    if enrollment["status"] != "PENDING_CONSENT":
        raise _enrollment_state_error(enrollment, "consented to")

    system = store.get("battery_systems", enrollment["battery_system_id"])
    if system is None or system["grid_status"] != "PTO_GRANTED":
        raise ApiError(
            "ERR_SYSTEM_GRID_STATE_INVALID",
            "The bank no longer holds permission to operate.",
        )

    enrollment["status"] = "ENROLLED"
    enrollment["consented_by_user_id"] = actor.user_id
    enrollment["consented_at"] = store.now()
    store.touch(enrollment)
    return ok(store.view(enrollment))


@bp.route("/byod-enrollments/<enrollment_id>/withdraw", methods=["POST"])
@guard("Homeowner", "CertifiedInstaller")
def withdraw_enrollment(actor, enrollment_id):
    enrollment = path_ref(actor, "enrollment", enrollment_id)
    payload = shape.body()
    payload.str_("reason", required=False, allow_empty=True)

    if enrollment["status"] not in ("PENDING_CONSENT", "ENROLLED"):
        raise _enrollment_state_error(enrollment, "withdrawn")

    was_enrolled = enrollment["status"] == "ENROLLED"
    enrollment["status"] = "WITHDRAWN"
    store.touch(enrollment)
    if was_enrolled:
        cascades.release_participations_for_withdrawal(enrollment)
    return ok(store.view(enrollment))


# --------------------------------------------------------------------------- #
# Dispatch events
# --------------------------------------------------------------------------- #

@bp.route("/dispatch-events", methods=["POST"])
@guard("UtilityInterconnectionReviewer")
def create_event(actor):
    payload = shape.body()
    territory_code = payload.enum("territory_code", TERRITORIES)
    window_start, window_end = shape.window(payload)
    event_type = payload.enum("event_type", EVENT_TYPES)
    target_kw = payload.number("target_kw", exclusive_min=True)
    payment_rate = payload.integer("payment_rate_cents_per_kw", exclusive_min=True)

    rules.require_territory_capacity(
        territory_code, window_start, window_end, target_kw
    )

    record = store.insert(
        "events",
        {
            "territory_code": territory_code,
            "window_start": window_start,
            "window_end": window_end,
            "event_type": event_type,
            "target_kw": kw(target_kw),
            "payment_rate_cents_per_kw": payment_rate,
            "status": "SCHEDULED",
            "enrolled_pledged_kw": kw(0),
            "total_net_payment_cents": 0,
            "settled_at": None,
        },
    )
    return created(store.view(record))


@bp.route("/dispatch-events/<event_id>", methods=["GET"])
@guard(*DISPATCH_READ_ROLES)
def read_event(actor, event_id):
    record = path_ref(actor, "event", event_id)
    return ok(store.view(record))


@bp.route("/dispatch-events", methods=["GET"])
@guard(*DISPATCH_READ_ROLES)
def list_events(actor):
    records = store.where(
        "events",
        territory_code=request.args.get("territory_code"),
        status=request.args.get("status"),
        event_type=request.args.get("event_type"),
    )
    return collection(records)


@bp.route("/dispatch-events/<event_id>/participations", methods=["POST"])
@guard("UtilityInterconnectionReviewer")
def create_participation(actor, event_id):
    event = path_ref(actor, "event", event_id)
    payload = shape.body()
    enrollment_id = payload.fk("byod_enrollment_id")
    enrollment = ref("enrollment", enrollment_id)
    expected_version = payload.integer("expected_dispatch_event_version", minimum=0)

    if event["status"] != "SCHEDULED":
        raise _event_state_error(event, "called upon for another participation")
    if enrollment["status"] != "ENROLLED":
        raise _enrollment_state_error(enrollment, "called into a dispatch event")
    if expected_version != event["version"]:
        raise ApiError(
            "ERR_STALE_EVENT_VERSION",
            "The dispatch event has version %d." % event["version"],
        )
    for existing in store.rows("performances"):
        if (
            existing["dispatch_event_id"] == event["id"]
            and existing["byod_enrollment_id"] == enrollment["id"]
        ):
            raise ApiError(
                "ERR_PARTICIPATION_DUPLICATE",
                "That enrollment already participates in this event.",
            )

    snapshot = kw(enrollment["pledged_kw"])
    record = store.insert(
        "performances",
        {
            "dispatch_event_id": event["id"],
            "byod_enrollment_id": enrollment["id"],
            "pledged_kw_snapshot": snapshot,
            "delivered_kwh": None,
            "avg_delivered_kw": None,
            "credited_kw": None,
            "performance_ratio": None,
            "gross_payment_cents": None,
            "shortfall_penalty_cents": None,
            "bonus_cents": None,
            "net_payment_cents": None,
            "status": "PENDING",
        },
    )
    rules.add_pledged_capacity(event, snapshot)
    return created(store.view(record))


# --------------------------------------------------------------------------- #
# Dispatch performances
# --------------------------------------------------------------------------- #

@bp.route("/dispatch-performances/<performance_id>", methods=["GET"])
@guard(*DISPATCH_READ_ROLES)
def read_performance(actor, performance_id):
    record = path_ref(actor, "performance", performance_id)
    return ok(store.view(record))


@bp.route("/dispatch-performances", methods=["GET"])
@guard(*DISPATCH_READ_ROLES)
def list_performances(actor):
    records = store.where(
        "performances",
        dispatch_event_id=request.args.get("dispatch_event_id"),
        byod_enrollment_id=request.args.get("byod_enrollment_id"),
        status=request.args.get("status"),
    )
    return collection(records)


@bp.route("/dispatch-performances/<performance_id>/report-delivery", methods=["POST"])
@guard("UtilityInterconnectionReviewer")
def report_delivery(actor, performance_id):
    performance = path_ref(actor, "performance", performance_id)
    payload = shape.body()
    delivered_kwh = payload.number("delivered_kwh")

    if performance["status"] != "PENDING":
        raise ApiError(
            "ERR_PERFORMANCE_STATE_INVALID",
            "A participation in %s cannot report delivery." % performance["status"],
        )
    event = store.get("events", performance["dispatch_event_id"])
    if event is None or event["status"] != "SCHEDULED":
        raise _event_state_error(event or {"status": "SETTLED"}, "reported against")
    if not rules.clock_reached(event["window_end"]):
        raise ApiError(
            "ERR_PERFORMANCE_STATE_INVALID",
            "The dispatch window has not closed yet.",
        )

    avg, credited, ratio = delivery_figures(event, performance, delivered_kwh)
    performance["delivered_kwh"] = kw(delivered_kwh)
    performance["avg_delivered_kw"] = avg
    performance["credited_kw"] = credited
    performance["performance_ratio"] = ratio
    performance["status"] = "REPORTED"
    store.touch(performance)
    return ok(store.view(performance))


@bp.route("/dispatch-events/<event_id>/settle", methods=["POST"])
@guard("UtilityInterconnectionReviewer")
def settle_event(actor, event_id):
    event = path_ref(actor, "event", event_id)
    if event["status"] != "SCHEDULED":
        raise _event_state_error(event, "settled")
    if not rules.clock_reached(event["window_end"]):
        raise _event_state_error(event, "settled before its window has closed")

    participations = [
        performance
        for performance in store.rows("performances")
        if performance["dispatch_event_id"] == event["id"]
        and performance["status"] != "CANCELLED"
    ]
    for performance in participations:
        if performance["status"] != "REPORTED":
            raise ApiError(
                "ERR_PERFORMANCE_STATE_INVALID",
                "Every participation must report delivery before settlement.",
            )

    total = 0
    for performance in participations:
        enrollment = store.get("enrollments", performance["byod_enrollment_id"])
        if enrollment is None:
            continue
        figures = settlement_money(event, performance, enrollment)
        performance["gross_payment_cents"] = figures["gross_payment_cents"]
        performance["shortfall_penalty_cents"] = figures["shortfall_penalty_cents"]
        performance["bonus_cents"] = figures["bonus_cents"]
        performance["net_payment_cents"] = figures["net_payment_cents"]
        performance["status"] = "SETTLED"
        store.touch(performance)

        enrollment["cumulative_credited_kw"] = figures["cumulative_credited_kw"]
        enrollment["cumulative_pledged_kw"] = figures["cumulative_pledged_kw"]
        enrollment["season_compliance_ratio"] = figures["season_compliance_ratio"]
        enrollment["settled_event_count"] += 1
        enrollment["performance_payment_cents_total"] += figures["net_payment_cents"]
        store.touch(enrollment)

        total += figures["net_payment_cents"]

    event["status"] = "SETTLED"
    event["settled_at"] = store.now()
    event["total_net_payment_cents"] = total
    store.touch(event)
    return ok(store.view(event))
