"""Trips: request, complete-start, complete and cancel."""

from flask import Blueprint, request

from db import STORE, now
from errors import (ApiError, ERR_INVALID_STATE, ERR_RESOURCE_NOT_FOUND,
                    ERR_TRIP_NOT_FOUND, ERR_UNAUTHORIZED)
from middleware import body, new_id, route, stamp, touch
from response import created, read_pagination, success, success_list
from serializers import trip as serialize_trip
from services import common

bp = Blueprint("trips", __name__)


def get_trip(trip_id):
    trip = STORE.trips.get(trip_id)
    if trip is None:
        raise ApiError(*ERR_TRIP_NOT_FOUND, message="No such trip: %s" % trip_id)
    return trip


@bp.route("/safety/trips", methods=["POST"])
@route("PlatformAdmin")
def create_trip(ident):
    payload = body()
    rider = STORE.accounts.get(payload.get("rider_account_id"))
    driver = STORE.accounts.get(payload.get("driver_account_id"))
    if rider is None or driver is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="Both the rider and the driver account must exist.")

    trip = {
        "id": new_id(),
        "rider_account_id": rider.get("id"),
        "driver_account_id": driver.get("id"),
        "region_code": payload.get("region_code"),
        "requested_at": payload.get("requested_at"),
        "completed_at": None,
        "status": "REQUESTED",
        "in_app_message_count": payload.get("in_app_message_count", 0) or 0,
        "law_enforcement_contact_logged": bool(
            payload.get("law_enforcement_contact_logged", False)),
    }
    stamp(trip)
    STORE.trips[trip["id"]] = trip
    return created(serialize_trip(trip))


@bp.route("/safety/trips", methods=["GET"])
@route("PlatformAdmin", "SafetyInvestigator", "Rider", "Driver")
def list_trips(ident):
    limit, offset = read_pagination(request.args)
    items = list(STORE.trips.values())

    def keep(trip):
        acting = request.args.get("account_id")
        if acting is not None and acting not in (trip.get("rider_account_id"),
                                                 trip.get("driver_account_id")):
            return False
        for field in ("rider_account_id", "driver_account_id", "status"):
            wanted = request.args.get(field)
            if wanted is not None and trip.get(field) != wanted:
                return False
        return True

    items = [t for t in items if keep(t)]
    items.sort(key=lambda t: (t.get("created_at"), t.get("id") or ""))
    return success_list([serialize_trip(t) for t in items], limit, offset)


@bp.route("/safety/trips/<trip_id>", methods=["GET"])
@route("PlatformAdmin", "SafetyInvestigator", "Rider", "Driver")
def get_one_trip(ident, trip_id):
    return success(serialize_trip(get_trip(trip_id)))


@bp.route("/safety/trips/<trip_id>/complete-start", methods=["POST"])
@route("Driver")
def complete_start(ident, trip_id):
    trip = get_trip(trip_id)
    if trip.get("status") != "REQUESTED":
        raise ApiError(*ERR_INVALID_STATE,
                       message="A trip may only start completion from REQUESTED.")
    # The acting driver must be the trip's driver and their account must be
    # ACTIVE or RESTRICTED. A caller who is not the owning driver holds no
    # authority over the resource at all, so the refusal is an authorisation
    # failure rather than a state failure.
    if ident.user_id != trip.get("driver_account_id"):
        raise ApiError(*ERR_UNAUTHORIZED,
                       message="Only the trip's own driver may signal completion.")
    driver = STORE.accounts.get(trip.get("driver_account_id"))
    if driver is None or driver.get("status") not in ("ACTIVE", "RESTRICTED"):
        raise ApiError(*ERR_INVALID_STATE,
                       message="The driver account is not in a completable state.")
    trip["status"] = "COMPLETED_PENDING"
    touch(trip)
    return success(serialize_trip(trip))


@bp.route("/safety/trips/<trip_id>/complete", methods=["POST"])
@route("Driver")
def complete(ident, trip_id):
    trip = get_trip(trip_id)
    if trip.get("status") != "COMPLETED_PENDING":
        raise ApiError(*ERR_INVALID_STATE,
                       message="Only a COMPLETED_PENDING trip may be completed.")
    trip["status"] = "COMPLETED"
    trip["completed_at"] = now()
    touch(trip)

    for account_id in (trip.get("rider_account_id"), trip.get("driver_account_id")):
        account = STORE.accounts.get(account_id)
        if account is None:
            continue
        # Completing a trip credits both member accounts. PRD §2.4 places the
        # 2-point trip credit outside the propagation rule, so the projection is
        # re-derived first and the credit is then applied on top of it.
        propagation_excluded = 2.0
        common.recompute_credits_for_account(account_id)
        common.refresh_account(account)
        account["risk_score"] = max(
            0, round((account.get("risk_score") or 0) - propagation_excluded, 2))
        from calculations import tier_with_escape_hatch
        account["risk_tier"] = tier_with_escape_hatch(account_id, account["risk_score"])
        touch(account)
        _reevaluate_rollup(account, trip)

    return success(serialize_trip(trip))


def _reevaluate_rollup(account, trip):
    """Completion re-evaluates the region rollup threshold for the account."""
    from services.regulator import run_rollup_for_account
    run_rollup_for_account(account)


@bp.route("/safety/trips/<trip_id>/cancel", methods=["POST"])
@route("Rider")
def cancel(ident, trip_id):
    trip = get_trip(trip_id)
    if trip.get("status") != "REQUESTED":
        raise ApiError(*ERR_INVALID_STATE,
                       message="Only a REQUESTED trip may be cancelled.")
    if ident.user_id != trip.get("rider_account_id"):
        raise ApiError(*ERR_INVALID_STATE,
                       message="Only the trip's own rider may cancel it.")
    trip["status"] = "CANCELLED"
    trip["completed_at"] = None
    touch(trip)
    return success(serialize_trip(trip))