"""Run planning, stop booking, crew coordination, dispatch and delivery
outcomes (PRD 3.7, 3.8).
"""

from decimal import Decimal

from flask import Blueprint

from auth import authenticate, require_self_scope, resolve
from core import (
    COUNTIES, MIN_FILL_RATIO_TO_SCHEDULE, RUN_HOURS, clock, dec,
)
from db import (
    db, new_entity, serialize, touch, crew_of_run, stops_of_run,
    client_of_voucher, referral_of_voucher,
)
from envelope import object_response
from errors import ApiError
from routes._common import filtered, respond_list
from services.delivery import (
    apply_crew_auto_transition, dispatch_run, recompute_run, record_outcome,
)
from services.donations import volunteer_rest_conflict
from validation import (
    Field, pagination_params, require_window, validate_body,
)

bp = Blueprint("runs", __name__)

CREW_ROLES = ("DRIVER", "LIFTER")
CREW_RESPONSES = ("CONFIRM", "DECLINE", "WITHDRAW")
OUTCOMES = ("DELIVERED", "NO_SHOW", "REFUSED")


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------
@bp.route("/delivery-runs", methods=["POST"])
def plan_run():
    authenticate(["DispatchPlanner"])
    payload = validate_body([
        Field("truck_id", "string"),
        Field("service_date", "date"),
        Field("window_start", "datetime"),
        Field("window_end", "datetime"),
        Field("county", "enum", members=COUNTIES),
        Field("rescheduled_from_run_id", "string", required=False, default=None),
    ])
    require_window(payload, "window_start", "window_end")

    truck = resolve("truck", payload["truck_id"])
    if payload["rescheduled_from_run_id"] is not None:
        resolve("run", payload["rescheduled_from_run_id"])

    run = new_entity(
        truck_id=truck["id"],
        service_date=payload["service_date"],
        window_start=payload["window_start"],
        window_end=payload["window_end"],
        county=payload["county"],
        rescheduled_from_run_id=payload["rescheduled_from_run_id"],
        status="PLANNED",
        load_cubic_feet=Decimal("0.0"),
        confirmed_crew_count=0,
        has_confirmed_driver=False,
        stop_count=0,
    )
    db.delivery_runs[run["id"]] = run
    return object_response(serialize(run), 201)


@bp.route("/delivery-runs/<run_id>", methods=["GET"])
def get_run(run_id):
    authenticate(["DispatchPlanner", "PlatformAdmin"])
    run = resolve("run", run_id)
    return object_response(serialize(run))


@bp.route("/delivery-runs", methods=["GET"])
def list_runs():
    authenticate(["DispatchPlanner", "PlatformAdmin"])
    limit, offset = pagination_params()
    rows = filtered(list(db.delivery_runs.values()), {
        "truck_id": "truck_id",
        "status": "status",
        "service_date": "service_date",
        "rescheduled_from_run_id": "rescheduled_from_run_id",
    })
    return respond_list(rows, limit, offset)


# --------------------------------------------------------------------------
# Stops
# --------------------------------------------------------------------------
@bp.route("/delivery-runs/<run_id>/stops", methods=["POST"])
def book_stop(run_id):
    authenticate(["DispatchPlanner"])
    payload = validate_body([
        Field("voucher_id", "string"),
        Field("sequence", "integer", minimum=1, maximum=40),
        Field("expected_run_version", "integer"),
    ])
    run = resolve("run", run_id)
    voucher = resolve("voucher", payload["voucher_id"])

    # (10) optimistic concurrency on the run's version
    if payload["expected_run_version"] != run["version"]:
        raise ApiError("ERR_STALE_RUN_VERSION",
                       "`expected_run_version` does not match the run's version.")
    # (11) state gates - the run first, then the voucher
    if run["status"] not in ("PLANNED", "CREWED"):
        raise ApiError("ERR_RUN_INVALID_STATE",
                       "Only a PLANNED or CREWED run may take a new stop.")
    if voucher["status"] not in ("ALLOCATED", "PARTIALLY_ALLOCATED"):
        raise ApiError("ERR_VOUCHER_INVALID_STATE",
                       "Only an ALLOCATED or PARTIALLY_ALLOCATED voucher may be booked.")

    client = client_of_voucher(voucher)
    referral = referral_of_voucher(voucher)
    # (13) bed-bug block
    if client["bed_bug_status"] == "CONFIRMED":
        raise ApiError("ERR_CLIENT_BED_BUG_BLOCK",
                       "The household is under a confirmed bed-bug infestation.")
    # (14) delivery ban
    banned = client["status"] != "ACTIVE" or (
        client["delivery_ban_until"] is not None
        and client["delivery_ban_until"] > clock.now())
    if banned:
        raise ApiError("ERR_CLIENT_DELIVERY_BANNED",
                       "The household is under a delivery ban.")
    # (17) referral expiry
    if referral["expires_at"] is not None and clock.now() > referral["expires_at"]:
        raise ApiError("ERR_REFERRAL_EXPIRED", "The referral has expired.")
    # (22) routing position must be free
    for existing in stops_of_run(run["id"], ("SCHEDULED",)):
        if existing["sequence"] == payload["sequence"]:
            raise ApiError("ERR_STOP_SEQUENCE_CONFLICT",
                           "That routing position is already occupied on this run.")
    # (23) scheduling floor for a partially allocated voucher
    if voucher["status"] == "PARTIALLY_ALLOCATED" and \
            dec(voucher["fill_ratio"]) < MIN_FILL_RATIO_TO_SCHEDULE:
        raise ApiError("ERR_VOUCHER_UNDERFILLED",
                       "This voucher is filled below the scheduling floor.")

    stop = new_entity(
        run_id=run["id"],
        voucher_id=voucher["id"],
        sequence=payload["sequence"],
        status="SCHEDULED",
        pest_observed_at_residence=False,
        chargeback_cents=0,
        outcome_recorded_at=None,
    )
    db.delivery_stops[stop["id"]] = stop
    voucher["status"] = "SCHEDULED"
    touch(voucher)
    recompute_run(run)
    touch(run)
    return object_response(serialize(stop), 201)


@bp.route("/delivery-runs/<run_id>/stops", methods=["GET"])
def list_run_stops(run_id):
    authenticate(["DispatchPlanner", "PlatformAdmin"])
    limit, offset = pagination_params()
    run = resolve("run", run_id)
    rows = filtered(stops_of_run(run["id"]), {"status": "status"})
    return respond_list(rows, limit, offset,
                        key=lambda s: (s["sequence"], s["created_at"], s["_seq"]))


# --------------------------------------------------------------------------
# Crew
# --------------------------------------------------------------------------
@bp.route("/delivery-runs/<run_id>/crew", methods=["POST"])
def invite_crew(run_id):
    authenticate(["DispatchPlanner"])
    payload = validate_body([
        Field("volunteer_id", "string"),
        Field("role_on_crew", "enum", members=CREW_ROLES),
    ])
    run = resolve("run", run_id)
    volunteer = resolve("volunteer", payload["volunteer_id"])

    # (11) state gate
    if run["status"] not in ("PLANNED", "CREWED"):
        raise ApiError("ERR_RUN_INVALID_STATE",
                       "Only a PLANNED or CREWED run may take crew invitations.")
    # (19) volunteer rest window
    if volunteer_rest_conflict(volunteer["id"], run):
        raise ApiError("ERR_VOLUNTEER_WINDOW_CONFLICT",
                       "The volunteer is not rested for this run's window.")
    # (21) one live assignment per volunteer per run
    for existing in crew_of_run(run["id"], ("INVITED", "CONFIRMED")):
        if existing["volunteer_id"] == volunteer["id"]:
            raise ApiError("ERR_DUPLICATE_CREW_ASSIGNMENT",
                           "This volunteer already holds a seat on this run.")
    # (24) a DRIVER seat needs a lift-certified volunteer
    if payload["role_on_crew"] == "DRIVER" and not volunteer["lift_certified"]:
        raise ApiError("ERR_DRIVER_NOT_CERTIFIED",
                       "A DRIVER seat requires a lift-certified volunteer.")

    assignment = new_entity(
        run_id=run["id"],
        volunteer_id=volunteer["id"],
        role_on_crew=payload["role_on_crew"],
        status="INVITED",
    )
    db.crew_assignments[assignment["id"]] = assignment
    return object_response(serialize(assignment), 201)


@bp.route("/delivery-runs/<run_id>/crew", methods=["GET"])
def list_run_crew(run_id):
    authenticate(["DispatchPlanner", "PlatformAdmin"])
    limit, offset = pagination_params()
    run = resolve("run", run_id)
    rows = filtered(crew_of_run(run["id"]), {"status": "status"})
    return respond_list(rows, limit, offset)


@bp.route("/crew-assignments/<assignment_id>/respond", methods=["POST"])
def respond_to_invitation(assignment_id):
    actor = authenticate(["Volunteer"])
    payload = validate_body([Field("response", "enum", members=CREW_RESPONSES)])
    assignment = resolve("crew_assignment", assignment_id)
    # (8) a volunteer answers only their own invitation
    require_self_scope(actor, assignment["volunteer_id"])

    run = db.delivery_runs.get(assignment["run_id"])
    volunteer = db.volunteers.get(assignment["volunteer_id"])
    response = payload["response"]

    # (11) state gate
    if response in ("CONFIRM", "DECLINE"):
        if assignment["status"] != "INVITED":
            raise ApiError("ERR_CREW_ASSIGNMENT_INVALID_STATE",
                           "Only an INVITED assignment may be confirmed or declined.")
    else:
        if assignment["status"] != "CONFIRMED":
            raise ApiError("ERR_CREW_ASSIGNMENT_INVALID_STATE",
                           "Only a CONFIRMED assignment may be withdrawn.")

    if response == "CONFIRM":
        if run["status"] != "PLANNED":
            raise ApiError("ERR_RUN_INVALID_STATE",
                           "A confirmation is only accepted while the run is PLANNED.")
        assignment["status"] = "CONFIRMED"
        touch(assignment)
        volunteer["assigned_hours_month"] = dec(volunteer["assigned_hours_month"]) + RUN_HOURS
        touch(volunteer)
        recompute_run(run)
        apply_crew_auto_transition(run)
    elif response == "DECLINE":
        assignment["status"] = "DECLINED"
        touch(assignment)
    else:
        if run["status"] not in ("PLANNED", "CREWED"):
            raise ApiError("ERR_RUN_INVALID_STATE",
                           "A withdrawal is only accepted while the run is PLANNED or CREWED.")
        assignment["status"] = "RELEASED"
        touch(assignment)
        volunteer["assigned_hours_month"] = max(
            dec(volunteer["assigned_hours_month"]) - RUN_HOURS, Decimal("0.0"))
        touch(volunteer)
        recompute_run(run)
        apply_crew_auto_transition(run)

    return object_response(serialize(assignment))


# --------------------------------------------------------------------------
# Dispatch and outcomes
# --------------------------------------------------------------------------
@bp.route("/delivery-runs/<run_id>/dispatch", methods=["POST"])
def dispatch(run_id):
    authenticate(["DispatchPlanner"])
    validate_body([])
    run = resolve("run", run_id)
    truck = db.trucks.get(run["truck_id"])
    # Read the derived numbers without moving the run: a rejected dispatch
    # must not leave a version bump behind.
    recompute_run(run, silent=True)

    # (11) state gate
    if run["status"] not in ("PLANNED", "CREWED"):
        raise ApiError("ERR_RUN_INVALID_STATE", "This run can no longer be dispatched.")
    if run["stop_count"] < 1:
        raise ApiError("ERR_RUN_INVALID_STATE",
                       "A run carrying no scheduled stops cannot be dispatched.")
    # (15) truck bed-bug lockout
    lockout = truck["bed_bug_lockout_until"] if truck else None
    if lockout is not None and lockout > run["window_start"]:
        raise ApiError("ERR_TRUCK_BED_BUG_LOCKOUT",
                       "The truck is locked out of service for that window.")
    # (25) load must fit
    if dec(run["load_cubic_feet"]) > dec(truck["capacity_cubic_feet"]):
        raise ApiError("ERR_TRUCK_CAPACITY_EXCEEDED",
                       "The run's load exceeds the truck's capacity.")
    # (26) crew must be complete
    if run["confirmed_crew_count"] < truck["crew_minimum"] or not run["has_confirmed_driver"]:
        raise ApiError("ERR_CREW_BELOW_MINIMUM",
                       "The run does not carry the minimum confirmed crew.")

    dispatch_run(run)
    return object_response(serialize(run))


@bp.route("/delivery-stops/<stop_id>/outcome", methods=["POST"])
def stop_outcome(stop_id):
    authenticate(["DispatchPlanner"])
    payload = validate_body([
        Field("outcome", "enum", members=OUTCOMES),
        Field("pest_observed_at_residence", "boolean", required=False, default=False),
    ])
    stop = resolve("stop", stop_id)
    run = db.delivery_runs.get(stop["run_id"])

    # (11) state gate
    if stop["status"] != "SCHEDULED" or run is None or run["status"] != "DISPATCHED":
        raise ApiError("ERR_STOP_INVALID_STATE",
                       "Only a SCHEDULED stop on a DISPATCHED run may be closed.")

    record_outcome(stop, payload["outcome"], bool(payload["pest_observed_at_residence"]))
    return object_response(serialize(stop))
