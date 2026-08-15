"""TourStop endpoints: OCC-guarded booking, updates, lifecycle transitions,
and supervisor assignment. Booking rejections fire in the fixed PRD §3.2
order: stale version, venue double-booking, refurbishment gap, window shape.
"""

from datetime import timedelta

from flask import Blueprint

import calc
import db
import system
from envelope import ok_object
from errors import fail
from security import require_roles, ALL_ROLES
from serializers import stop_out
from validate import (json_body, req_int, req_dt, req_version, opt_int,
                      get_tour, get_stop, paginate, apply_filters,
                      sorted_created)

bp = Blueprint("stops", __name__)

_LIVE_FOR_OVERLAP = ("TENTATIVE", "CONTRACTED", "INSTALLING", "OPEN", "TEARDOWN")


# --- booking (PRD §3.2) --------------------------------------------------------

@bp.route("/tours/<tour_id>/stops", methods=["POST"])
def book_stop(tour_id):
    require_roles("TourManager")
    tour = get_tour(tour_id)
    data = json_body()

    venue_id = data.get("venue_id")
    if not isinstance(venue_id, str) or not venue_id:
        fail("ERR_INVALID_REQUEST", "Missing or invalid required field: venue_id")
    venue = db.venues.get(venue_id)
    if venue is None:
        fail("ERR_INVALID_REQUEST", "venue_id does not reference a venue")
    install_start = req_dt(data, "install_start")
    open_date = req_dt(data, "open_date")
    close_date = req_dt(data, "close_date")
    teardown_end = req_dt(data, "teardown_end")
    projected = req_int(data, "projected_attendance")
    expected_version = req_version(data, "expected_tour_version")

    # 1. OCC stale-version check (priority 4) — before any business rule.
    if expected_version != tour["version"]:
        fail("ERR_STALE_VERSION",
             "expected_tour_version does not match the tour's current version")

    new_install = db.parse_dt(install_start)
    new_teardown = db.parse_dt(teardown_end)

    # 2. Venue double-booking on half-open [install_start, teardown_end).
    for other in db.stops.values():
        if other["venue_id"] != venue["id"] \
                or other["status"] not in _LIVE_FOR_OVERLAP:
            continue
        if new_install < db.parse_dt(other["teardown_end"]) \
                and db.parse_dt(other["install_start"]) < new_teardown:
            fail("ERR_VENUE_DOUBLE_BOOKED",
                 "Venue already committed to an overlapping window")

    # 3. Refurbishment gap against route neighbours (any status).
    gap = timedelta(days=tour["refurbishment_gap_days"])
    tour_stops = system.stops_of_tour(tour["id"])
    tour_stops.sort(key=lambda s: (db.parse_dt(s["install_start"]),
                                   s["created_at"]))
    # Every existing stop sorts strictly before the new one on install_start
    # ties: the new stop's created_at is assigned at creation, later than all
    # existing stops (route_sequence tie-break is created_at ascending).
    pred, succ = None, None
    for s in tour_stops:
        if db.parse_dt(s["install_start"]) <= new_install:
            pred = s  # tour_stops is sorted, so the last one is the nearest
        else:
            succ = s
            break
    if pred is not None and new_install - db.parse_dt(pred["teardown_end"]) < gap:
        fail("ERR_REFURBISHMENT_GAP_VIOLATED",
             "Gap after previous stop is below refurbishment_gap_days")
    if succ is not None and db.parse_dt(succ["install_start"]) - new_teardown < gap:
        fail("ERR_REFURBISHMENT_GAP_VIOLATED",
             "Gap before next stop is below refurbishment_gap_days")

    # 4. Window shape: install_start < open_date < close_date < teardown_end.
    if not (new_install < db.parse_dt(open_date) < db.parse_dt(close_date)
            < new_teardown):
        fail("ERR_WINDOW_MALFORMED",
             "install_start < open_date < close_date < teardown_end violated")

    stop = db.stamp_new({
        "id": db.new_id(),
        "tour_id": tour["id"],
        "venue_id": venue["id"],
        "seq": None,
        "install_start": install_start,
        "open_date": open_date,
        "close_date": close_date,
        "teardown_end": teardown_end,
        "projected_attendance": projected,
        "actual_attendance": None,
        "status": "TENTATIVE",
        "supervision_required": calc.supervision_required(venue, tour),
        "supervisor_user_id": None,
    })
    db.stops[stop["id"]] = stop
    calc.assign_route_seqs(tour["id"])
    db.touch(tour)  # a successful booking bumps tour.version by exactly 1
    return ok_object(stop_out(stop), status=201)


@bp.route("/tours/<tour_id>/stops", methods=["GET"])
def list_stops(tour_id):
    require_roles(*ALL_ROLES)
    tour = get_tour(tour_id)
    items = [s for s in db.stops.values() if s["tour_id"] == tour["id"]]
    items = apply_filters(items, [("venue_id", "venue_id"),
                                  ("status", "status")])
    return paginate([stop_out(s) for s in sorted_created(items)])


@bp.route("/tours/<tour_id>/stops/<stop_id>", methods=["GET"])
def get_one_stop(tour_id, stop_id):
    require_roles(*ALL_ROLES)
    tour = get_tour(tour_id)
    return ok_object(stop_out(get_stop(tour, stop_id)))


# --- update (PRD §3.2) ---------------------------------------------------------

@bp.route("/tours/<tour_id>/stops/<stop_id>", methods=["PATCH"])
def update_stop(tour_id, stop_id):
    require_roles("TourManager", "VenueRegistrar")
    tour = get_tour(tour_id)
    stop = get_stop(tour, stop_id)
    data = json_body()
    projected = opt_int(data, "projected_attendance")
    actual = opt_int(data, "actual_attendance", minimum=0)
    changed = False
    if projected is not None:
        if stop["status"] != "TENTATIVE":
            fail("ERR_INVALID_STATE",
                 "projected_attendance is mutable only while TENTATIVE")
        stop["projected_attendance"] = projected
        changed = True
        # Recompute an already-computed provisional fee on the live contract.
        contract = system.live_contract(stop["id"])
        if contract is not None and contract["provisional_fee_cents"] is not None:
            contract["provisional_fee_cents"] = \
                system.compute_provisional(contract, stop)
            db.touch(contract)
    if actual is not None:
        stop["actual_attendance"] = actual
        changed = True
    if changed:
        db.touch(stop)
    return ok_object(stop_out(stop))


# --- supervisor assignment (PRD §3.2) -------------------------------------------

@bp.route("/tours/<tour_id>/stops/<stop_id>/assign-supervisor", methods=["POST"])
def assign_supervisor(tour_id, stop_id):
    require_roles("TourManager")
    tour = get_tour(tour_id)
    stop = get_stop(tour, stop_id)
    data = json_body()
    supervisor = data.get("supervisor_user_id")
    if not isinstance(supervisor, str) or not supervisor:
        fail("ERR_INVALID_REQUEST",
             "Missing or invalid required field: supervisor_user_id")
    stop["supervisor_user_id"] = supervisor
    db.touch(stop)
    return ok_object({"supervisor_user_id": supervisor,
                      "tour_stop_id": stop["id"]}, status=201)


# --- lifecycle transitions (PRD §3.8) ---------------------------------------------

def _inbound_shipment(tour, stop):
    """The inbound leg for BEGIN_INSTALL/OPEN_TO_PUBLIC: the latest-created
    shipment bound for this stop in {RECEIVED, CLEARED}. Returns None when no
    shipment is bound for the stop. Raises ERR_INVALID_STATE when shipments
    exist but none is receivable/cleared or one sits in DAMAGE_HOLD."""
    inbound = [sh for sh in system.shipments_of_tour(tour["id"])
               if sh["destination_stop_id"] == stop["id"]]
    if not inbound:
        return None
    if any(sh["status"] == "DAMAGE_HOLD" for sh in inbound):
        fail("ERR_INVALID_STATE",
             "Inbound shipment is in DAMAGE_HOLD until its claims resolve")
    ready = [sh for sh in inbound if sh["status"] in ("RECEIVED", "CLEARED")]
    if not ready:
        fail("ERR_INVALID_STATE",
             "Inbound shipment is not yet RECEIVED or CLEARED")
    ready.sort(key=lambda sh: sh["created_at"])
    return ready[-1]


@bp.route("/tours/<tour_id>/stops/<stop_id>/transition", methods=["POST"])
def stop_transition(tour_id, stop_id):
    require_roles("TourManager")
    tour = get_tour(tour_id)
    stop = get_stop(tour, stop_id)
    data = json_body()
    action = data.get("action")
    if action not in ("CANCEL", "BEGIN_INSTALL", "OPEN_TO_PUBLIC",
                      "BEGIN_TEARDOWN", "REOPEN", "CLOSE_STOP"):
        fail("ERR_INVALID_REQUEST", "Unrecognized action: %r" % action)

    if action == "CANCEL":
        if stop["status"] not in ("TENTATIVE", "CONTRACTED"):
            fail("ERR_INVALID_STATE",
                 "CANCEL is only permitted from TENTATIVE or CONTRACTED")
        if stop["status"] == "CONTRACTED":
            blocking = [sh for sh in system.shipments_of_tour(tour["id"])
                        if sh["destination_stop_id"] == stop["id"]
                        and sh["status"] in ("DISPATCHED", "IN_TRANSIT",
                                             "RECEIVED", "DAMAGE_HOLD")]
            if blocking:
                fail("ERR_INVALID_STATE",
                     "A shipment bound for this stop is in flight")
        system.cancel_stop(stop)
        return ok_object(stop_out(stop))

    if action == "BEGIN_INSTALL":
        if stop["status"] != "CONTRACTED":
            fail("ERR_INVALID_STATE",
                 "BEGIN_INSTALL is only permitted from CONTRACTED")
        if tour["status"] not in ("BOOKING", "ON_TOUR", "IN_REFURBISHMENT"):
            fail("ERR_INVALID_STATE",
                 "Tour posture does not permit installation")
        leg = _inbound_shipment(tour, stop)
        # Business checks in fixed order: insurance, then supervision.
        certs = [c for c in system.certs_of_tour(tour["id"])
                 if c["tour_stop_id"] == stop["id"]]
        if not any(calc.cert_covers_leg(c, tour, leg) for c in certs):
            fail("ERR_NO_INSURANCE_COVERAGE",
                 "No certificate covers this stop for the inbound leg")
        if stop["supervision_required"] and not stop.get("supervisor_user_id"):
            fail("ERR_SUPERVISOR_REQUIRED",
                 "A supervisor must be assigned before installation")
        if tour["status"] == "IN_REFURBISHMENT":
            for crate in system.crates_of_tour(tour["id"]):
                if crate["location_status"] == "IN_REFURBISHMENT":
                    crate["location_status"] = "IN_TRANSIT"
                    crate["current_stop_id"] = stop["id"]
                    db.touch(crate)
        if leg is not None:
            for cid in leg["crate_ids"]:
                crate = db.crates.get(cid)
                if crate is not None:
                    crate["location_status"] = "AT_VENUE"
                    crate["current_stop_id"] = stop["id"]
                    db.touch(crate)
        if tour["status"] in ("BOOKING", "IN_REFURBISHMENT"):
            tour["status"] = "ON_TOUR"
            db.touch(tour)
        stop["status"] = "INSTALLING"
        db.touch(stop)
        return ok_object(stop_out(stop))

    if action == "OPEN_TO_PUBLIC":
        if stop["status"] != "INSTALLING":
            fail("ERR_INVALID_STATE",
                 "OPEN_TO_PUBLIC is only permitted from INSTALLING")
        leg = _inbound_shipment(tour, stop)
        if leg is not None:
            accepted = {(r["crate_id"]) for r in
                        system.reports_of_shipment(leg["id"])
                        if r["phase"] == "UNPACK" and r["status"] == "ACCEPTED"}
            if any(cid not in accepted for cid in leg["crate_ids"]):
                fail("ERR_INVALID_STATE",
                     "Every crate on the inbound shipment needs an ACCEPTED "
                     "UNPACK report")
        stop["status"] = "OPEN"
        db.touch(stop)
        return ok_object(stop_out(stop))

    if action == "BEGIN_TEARDOWN":
        if stop["status"] != "OPEN":
            fail("ERR_INVALID_STATE",
                 "BEGIN_TEARDOWN is only permitted from OPEN")
        stop["status"] = "TEARDOWN"
        db.touch(stop)
        return ok_object(stop_out(stop))

    if action == "REOPEN":
        if stop["status"] != "TEARDOWN":
            fail("ERR_INVALID_STATE", "REOPEN is only permitted from TEARDOWN")
        contract = system.live_contract(stop["id"])
        if contract is None:
            finalized = [c for c in system.contracts_of_stop(stop["id"])
                         if c["status"] == "FINALIZED"]
            if finalized:
                fail("ERR_INVALID_STATE",
                     "The finalized contract seals the stop's outcome")
        stop["status"] = "OPEN"
        db.touch(stop)
        return ok_object(stop_out(stop))

    # CLOSE_STOP
    if stop["status"] != "TEARDOWN":
        fail("ERR_INVALID_STATE", "CLOSE_STOP is only permitted from TEARDOWN")
    crates_here = [c for c in system.crates_of_tour(tour["id"])
                   if c["current_stop_id"] == stop["id"]
                   and c["location_status"] == "AT_VENUE"]
    for crate in crates_here:
        packed = any(r["crate_id"] == crate["id"] and r["phase"] == "PACK"
                     and r["status"] == "ACCEPTED"
                     for sh in system.shipments_of_tour(tour["id"])
                     for r in system.reports_of_shipment(sh["id"]))
        if not packed:
            fail("ERR_INVALID_STATE",
                 "Every crate on the stop needs an ACCEPTED PACK report")
    if stop["actual_attendance"] is None:
        fail("ERR_ATTENDANCE_MISSING",
             "actual_attendance must be reported before closing")
    stop["status"] = "CLOSED"
    db.touch(stop)
    system.close_stop_effects(stop, tour)
    return ok_object(stop_out(stop))
