"""Driver workforce transition, terminals staffing and run plan haulers —
PRD §3.8, endpoints 37-45, 154, 161-165.

The only entity-backed role in the system is `RemoteSupportOperator`, so
ownership checks on any resource that references a `DriverProspect` compare the
resource's foreign-key field to `X-User-ID` (PRD §2.1).
"""

import db
import services
import calculations as calc
from core import ApiError, D
from response import ok, page_of
from http_util import (pagination, must_get, must_resolve, get_or_none, body,
                       coerce_int, bind)
from routes._common import route
from models import create

PATHWAYS = ("FIRST_LAST_MILE", "REMOTE_SUPPORT", "FLEET_TECHNICIAN",
            "TRANSFER_HUB", "RIDE_ALONG_EVALUATOR")
HAULER_ROLES = ("FIRST_MILE_DRIVER", "LAST_MILE_DRIVER", "YARD_SHUTTLE")


def register(app):

    @route(app, "/api/driver-prospects", ["POST"], ["DriverOutreachCoordinator"])
    def create_prospect():
        raw = body()
        allowed = {"prospect_name", "home_terminal_id", "pathway"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        for key in allowed:
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        if raw["pathway"] not in PATHWAYS:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown pathway.")
        # §3.8: "The home_terminal_id must resolve to an existing terminal, or
        # registration stops with ERR_REFERENCE_NOT_FOUND".
        must_resolve("Terminal", raw["home_terminal_id"])
        row = create("DriverProspect", {
            "prospect_name": raw["prospect_name"],
            "home_terminal_id": raw["home_terminal_id"],
            "pathway": raw["pathway"],
        })
        row["hours_worked"] = 0
        row["enrollments_on_file"] = 0
        row["safety_reliability_score"] = 1000
        return ok(row, 201)

    @route(app, "/api/driver-prospects", ["GET"], ["Any"])
    def list_prospects():
        limit, offset = pagination()
        return page_of(db.sort_created(db.all_rows("driver_prospects")), limit, offset)

    @route(app, "/api/driver-prospects/<rid>", ["GET"], ["Any"])
    def get_prospect(rid):
        return ok(must_get("DriverProspect", rid))

    @route(app, "/api/driver-prospects/<rid>/driver-transitions", ["GET"], ["Any"])
    def prospect_transitions(rid):
        must_get("DriverProspect", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("driver_transitions", "prospect_id", rid)),
                       limit, offset)

    @route(app, "/api/driver-prospects/<rid>/run-plans", ["GET"], ["Any"])
    def prospect_run_plans(rid):
        must_get("DriverProspect", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("run_plans", "hauler_team_id", rid)),
                       limit, offset)

    @route(app, "/api/driver-prospects/<rid>/remote-support-assignments", ["GET"], ["Any"])
    def prospect_assignments(rid):
        must_get("DriverProspect", rid)
        limit, offset = pagination()
        rows = [a for a in db.all_rows("remote_support_assignments")
                if a.get("remote_operator_id") == rid
                or a.get("safety_support_operator_id") == rid]
        return page_of(db.sort_created(rows), limit, offset)

    # ------------------------------------------------------- transitions

    @route(app, "/api/driver-transitions", ["POST"], ["DriverOutreachCoordinator"])
    def create_transition():
        """§3.8: enrolment computes transition_end_epoch_day as the start day plus
        the day count minus one, adds hours_recorded onto the prospect's
        hours_worked, and recomputes the terminal's staffing_status."""
        raw = body()
        allowed = {"prospect_id", "terminal_id", "pathway",
                   "transition_start_epoch_day", "transition_days_count",
                   "hours_recorded"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        for key in ("prospect_id", "terminal_id", "pathway",
                    "transition_start_epoch_day", "transition_days_count"):
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        if raw["pathway"] not in PATHWAYS:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown pathway.")
        days = coerce_int(raw["transition_days_count"])
        if days < 1:
            raise ApiError("ERR_INVALID_REQUEST",
                           "transition_days_count must be at least 1.")
        prospect = must_resolve("DriverProspect", raw["prospect_id"])
        terminal = must_resolve("Terminal", raw["terminal_id"])
        start = coerce_int(raw["transition_start_epoch_day"])
        hours = int(raw.get("hours_recorded", 0) or 0)
        row = create("DriverTransition", {
            "prospect_id": prospect["id"],
            "terminal_id": terminal["id"],
            "pathway": raw["pathway"],
            "transition_start_epoch_day": start,
            "transition_days_count": days,
            "hours_recorded": hours,
            "transition_end_epoch_day": start + days - 1,
        })
        row["transition_status"] = "ENROLLED"
        row["credential_event_count"] = 0
        prospect["hours_worked"] = int(prospect.get("hours_worked") or 0) + hours
        _recompute_prospect(prospect)
        db.touch(prospect, _now())
        services.recompute_terminal(terminal)
        services.flush(terminal)
        return ok(row, 201)

    @route(app, "/api/driver-transitions", ["GET"], ["Any"])
    def list_transitions():
        limit, offset = pagination()
        rows = db.all_rows("driver_transitions")
        status = _arg("hold_status") or _arg("transition_status")
        if status:
            rows = [r for r in rows if r.get("transition_status") == status]
        return page_of(db.sort_created(rows), limit, offset)

    @route(app, "/api/driver-transitions/<rid>", ["GET"], ["Any"])
    def get_transition(rid):
        return ok(must_get("DriverTransition", rid))

    @route(app, "/api/driver-transitions/<rid>/haulers", ["GET"], ["Any"])
    def transition_haulers(rid):
        must_get("DriverTransition", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("run_plan_haulers", "driver_transition_id", rid)),
                       limit, offset)

    @route(app, "/api/driver-transitions/<rid>/ride-along", ["POST"],
           ["DriverOutreachCoordinator"])
    def ride_along(rid):
        """§3.8: a ride-along takes a run_plan_id, creates a RunPlanHauler
        evaluation plan attached to the transition, moves the transition to
        RIDE_ALONG_VERIFIED and recomputes the commitment's
        verified_ride_along_count."""
        transition = must_get("DriverTransition", rid)
        raw = body()
        for key in raw:
            if key != "run_plan_id":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if "run_plan_id" not in raw:
            raise ApiError("ERR_INVALID_REQUEST", "Required field 'run_plan_id' is missing.")
        run = must_resolve("RunPlan", raw["run_plan_id"])
        if transition.get("transition_status") in ("CANCELLED", "REJECTED"):
            raise ApiError("ERR_INVALID_STATE",
                           "A cancelled or rejected enrolment cannot be evaluated.")
        role = raw.get("hauler_role") or "FIRST_MILE_DRIVER"
        if role not in HAULER_ROLES:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown hauler_role.")
        create("RunPlanHauler", {
            "run_plan_id": run["id"],
            "driver_transition_id": transition["id"],
            "hauler_role": role,
            "hauler_status": "TRUCK_HOLDER_BLENDED",
        })
        services.mark(transition, "transition_status", "RIDE_ALONG_VERIFIED")
        services.flush(transition)
        db.sides["run_ride_along_transitions"].setdefault(run["id"], [])
        if transition["id"] not in db.sides["run_ride_along_transitions"][run["id"]]:
            db.sides["run_ride_along_transitions"][run["id"]].append(transition["id"])
        commitment = db.get("shipper_commitments", run.get("shipper_commitment_id"))
        if commitment is not None:
            services.recompute_commitment(commitment)
            services.flush(commitment)
        _recompute_prospect(db.get("driver_prospects", transition.get("prospect_id")))
        return ok(transition)

    @route(app, "/api/driver-transitions/<rid>/credential-lapse", ["POST"],
           ["CorridorOperationsManager"])
    def credential_lapse(rid):
        """§3.8: moves the transition to CREDENTIAL_LAPSED, sets
        credential_event_count to 1, and debits exactly 50 points from the owning
        prospect's safety_reliability_score, floored at 0.  The penalty is capped
        at one application per transition row."""
        transition = must_get("DriverTransition", rid)
        if transition.get("transition_status") in ("CANCELLED", "REJECTED"):
            raise ApiError("ERR_INVALID_STATE",
                           "A cancelled or rejected enrolment cannot lapse.")
        already = int(transition.get("credential_event_count") or 0) >= 1
        services.mark(transition, "transition_status", "CREDENTIAL_LAPSED")
        services.mark(transition, "credential_event_count", 1)
        services.flush(transition)
        prospect = db.get("driver_prospects", transition.get("prospect_id"))
        if prospect is not None and not already:
            score = max(int(prospect.get("safety_reliability_score") or 0) - 50, 0)
            services.mark(prospect, "safety_reliability_score", score)
            services.flush(prospect)
        return ok(transition)

    @route(app, "/api/driver-transitions/<rid>/cancel", ["POST"],
           ["DriverOutreachCoordinator"])
    def cancel_transition(rid):
        """§3.8: an optional hours_recorded supplied with the cancellation releases
        those hours, so the prospect's hours_worked recomputes downward."""
        transition = must_get("DriverTransition", rid)
        if transition.get("transition_status") in ("CANCELLED", "REJECTED"):
            raise ApiError("ERR_INVALID_STATE", "The enrolment is already terminal.")
        raw = body()
        for key in raw:
            if key != "hours_recorded":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        released = int(raw.get("hours_recorded", 0) or 0)
        services.mark(transition, "transition_status", "CANCELLED")
        services.flush(transition)
        prospect = db.get("driver_prospects", transition.get("prospect_id"))
        if prospect is not None:
            prospect["hours_worked"] = max(
                int(prospect.get("hours_worked") or 0) - released, 0)
            _recompute_prospect(prospect)
            db.touch(prospect, _now())
        terminal = db.get("terminals", transition.get("terminal_id"))
        if terminal is not None:
            services.recompute_terminal(terminal)
            services.flush(terminal)
        return ok(transition)


def _recompute_prospect(prospect):
    if prospect is None:
        return
    live = [t for t in db.by("driver_transitions", "prospect_id", prospect["id"])
            if t.get("transition_status") not in ("CANCELLED", "REJECTED")]
    services.mark(prospect, "enrollments_on_file", len(live))


def _now():
    import core
    return core.now_iso()


def _arg(name):
    from http_util import arg
    return arg(name)