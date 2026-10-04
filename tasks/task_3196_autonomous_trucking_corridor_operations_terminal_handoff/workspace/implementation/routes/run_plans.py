"""Run plans — PRD §3.2 tendering and pricing, §3.3 dispatch/requeue/abort,
§3.4 highway segment, safe stop and completion.  Endpoints 57-69 and 166-170.
"""

from datetime import timedelta
from decimal import Decimal

import db
import core
import services
import calculations as calc
from core import ApiError, D, now_iso, parse_iso
from response import ok, page_of
from http_util import (pagination, must_get, must_resolve, get_or_none, body,
                       coerce_int, coerce_num, arg, actor_id)
from routes._common import route
from models import create

PUBLIC = ["corridor_id", "carrier_id", "origin_terminal_id", "destination_terminal_id",
          "shipper_commitment_id", "window_start_epoch_day", "window_end_epoch_day",
          "trailer_count", "posted_per_mile_cents", "hauler_team_id",
          "sacra_loadboard_slot_held"]

HAULER_ROLES = ("FIRST_MILE_DRIVER", "LAST_MILE_DRIVER", "YARD_SHUTTLE")


def register(app):

    # ------------------------------------------------------------------ create

    @route(app, "/api/run-plans", ["POST"], ["CarrierDispatcher"])
    def create_run_plan():
        raw = body()
        unknown = _unknown(raw, PUBLIC)
        if unknown:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % unknown)

        # §2.11: the corridor is resolved before anything downstream.  The path
        # names no corridor here, so the body reference carries its own code.
        corridor = db.get("corridors", raw.get("corridor_id"))
        if raw.get("corridor_id") is not None and corridor is None:
            raise ApiError("ERR_CORRIDOR_NOT_FOUND")
        if corridor is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Required field 'corridor_id' is missing.")

        # §2.11 deferred resolution of every identifier supplied outside the path.
        carrier = must_resolve("Carrier", raw.get("carrier_id"))
        origin = must_resolve("Terminal", raw.get("origin_terminal_id"))
        destination = must_resolve("Terminal", raw.get("destination_terminal_id"))
        commitment = db.get("shipper_commitments", raw.get("shipper_commitment_id"))
        if raw.get("shipper_commitment_id") is not None and commitment is None:
            raise ApiError("ERR_COMMITMENT_NOT_FOUND")
        if commitment is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Required field 'shipper_commitment_id' is missing.")
        must_resolve("DriverProspect", raw.get("hauler_team_id"))

        # §2.4 / §3.2: an operation that is merely long-lived demands the posture
        # be OPEN or RESTRICTED.
        if corridor.get("posture") == "FROZEN":
            raise ApiError("ERR_CORRIDOR_FROZEN",
                           "A FROZEN corridor rejects every child operation.")

        # Priority 28 — posted_per_mile_cents must be at least the shipper floor
        # minus the maximum band discount of 40.
        posted = coerce_num(raw.get("posted_per_mile_cents"))
        floor = D(commitment.get("shipper_floor_per_mile_cents", 0))
        if D(posted) < floor - 40:
            raise ApiError("ERR_RATE_BELOW_COMMITMENT_FLOOR",
                           "The posted rate falls below the shipper commitment floor.")

        # Priority 29 — the named commitment must cover the run window.
        start_day = coerce_int(raw.get("window_start_epoch_day"))
        end_day = coerce_int(raw.get("window_end_epoch_day"))
        if not _commitment_covers(commitment, start_day, end_day):
            raise ApiError("ERR_NO_ELIGIBLE_COMMITMENT",
                           "No shipper commitment covers the requested run window.")

        # Priority 35 — the two terminals must differ.
        if origin["id"] == destination["id"]:
            raise ApiError("ERR_INVALID_ROUTE",
                           "Origin and destination terminals must differ.")

        # Priority 36 — trailer_count is exactly 1 or exactly 2.
        trailer_count = coerce_int(raw.get("trailer_count"))
        if trailer_count not in (1, 2):
            raise ApiError("ERR_INVALID_TRAILER_COUNT",
                           "trailer_count must be exactly 1 or exactly 2.")

        row = create("RunPlan", {
            "corridor_id": corridor["id"],
            "carrier_id": carrier["id"],
            "origin_terminal_id": origin["id"],
            "destination_terminal_id": destination["id"],
            "shipper_commitment_id": commitment["id"],
            "window_start_epoch_day": start_day,
            "window_end_epoch_day": end_day,
            "trailer_count": trailer_count,
            "posted_per_mile_cents": posted,
            "hauler_team_id": raw["hauler_team_id"],
            "sacra_loadboard_slot_held": bool(raw.get("sacra_loadboard_slot_held", False)),
        })
        row["run_status"] = "DRAFT"
        row["safety_score"] = 50
        services.mark(row, "safety_band", "MEDIUM")
        services.recompute_run_plan_rates(row)
        _attach_discount(row, carrier)
        services.flush(row)
        return ok(row, 201)

    # ------------------------------------------------------------- collection

    @route(app, "/api/run-plans", ["GET"], ["Any"])
    def list_run_plans():
        limit, offset = pagination()
        rows = db.all_rows("run_plans")
        for field in ("corridor_id", "carrier_id", "shipper_commitment_id", "run_status"):
            value = arg(field)
            if value:
                rows = [r for r in rows if r.get(field) == value]
        return page_of(db.sort_created(rows), limit, offset)

    @route(app, "/api/run-plans/<rid>", ["GET"], ["Any"])
    def get_run_plan(rid):
        return ok(must_get("RunPlan", rid))

    # ----------------------------------------------------------------- submit

    @route(app, "/api/run-plans/<rid>/submit", ["POST"], ["CarrierDispatcher"])
    def submit_run_plan(rid):
        """§3.2: tendering moves the run to READINESS_PENDING once the corridor is
        not FROZEN, the trailer count is 1 or 2, the commitment has at least one
        unconsumed loadboard slot, the readiness checks are within tolerance, and a
        RESTRICTED corridor is not held back by a draft-only safety case."""
        run = must_get("RunPlan", rid)
        raw = body()
        _reject_unknown_body(raw, ())
        corridor = db.get("corridors", run.get("corridor_id"))
        if corridor is None:
            raise ApiError("ERR_CORRIDOR_NOT_FOUND")
        commitment = db.get("shipper_commitments", run.get("shipper_commitment_id"))
        if commitment is None:
            raise ApiError("ERR_COMMITMENT_NOT_FOUND")

        # Priority 11 — a FROZEN corridor rejects the submit.
        if corridor.get("posture") == "FROZEN":
            raise ApiError("ERR_CORRIDOR_FROZEN",
                           "A FROZEN corridor will not accept a tendered run.")
        # Priorities 12 and 13 — the run plan's own state.
        _require_run_state(run, ("DRAFT",))
        # Priority 14 / 15 — the corridor's calibration and securement readings.
        _checks_within_tolerance(corridor, load_securement_error=True)
        # Priority 16 — a RESTRICTED corridor will not accept a tendered run while
        # its safety case exists only in DRAFT.
        if corridor.get("posture") == "RESTRICTED" and _safety_case_only_draft(corridor):
            raise ApiError("ERR_SAFETY_CASE_STALE",
                           "The corridor's safety case is still a draft.")
        # Priority 21 — coverage exclusivity on the corridor.
        if _run_overlap(run, corridor, commitment):
            raise ApiError("ERR_RUN_PLAN_OVERLAP",
                           "The corridor already carries a covered run in transit.")
        # Priority 27 — the commitment must have an unconsumed loadboard slot.
        if int(commitment.get("remaining_slots") or 0) <= 0:
            raise ApiError("ERR_COMMITMENT_CAPACITY_EXHAUSTED",
                           "The commitment has no unconsumed loadboard slot.")
        # Priority 28 repeat and 36 repeat.
        if D(run.get("posted_per_mile_cents", 0)) < D(commitment.get("shipper_floor_per_mile_cents", 0)) - 40:
            raise ApiError("ERR_RATE_BELOW_COMMITMENT_FLOOR")
        if int(run.get("trailer_count") or 0) not in (1, 2):
            raise ApiError("ERR_INVALID_TRAILER_COUNT")

        services.mark(run, "run_status", "READINESS_PENDING")
        if commitment.get("commitment_status") == "DRAFT":
            services.mark(commitment, "commitment_status", "CONFIRMED")
        services.recompute_commitment(commitment)
        services.flush(commitment)
        services.recompute_corridor(corridor)
        services.flush(corridor)
        services.flush(run)
        return ok(run)

    # ---------------------------------------------------------- dispatch ready

    @route(app, "/api/run-plans/<rid>/dispatch-ready", ["POST"], ["CarrierDispatcher"])
    def dispatch_ready(rid):
        """§3.3: one of the two guarded writes; the request must carry
        expected_run_plan_version."""
        run = must_get("RunPlan", rid)
        raw = body()
        unknown = _unknown(raw, ("expected_run_plan_version",))
        if unknown:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % unknown)
        _check_version(raw, "expected_run_plan_version", run)
        corridor = db.get("corridors", run.get("corridor_id"))
        if corridor is None:
            raise ApiError("ERR_CORRIDOR_NOT_FOUND")
        _require_run_state(run, ("READINESS_PENDING",))
        # §3.3: every ROUTE_VALIDATION check on the corridor must carry PASS.
        for c in db.by("launch_readiness_checks", "corridor_id", corridor["id"]):
            if c.get("check_type") == "ROUTE_VALIDATION" and c.get("check_result") != "PASS":
                raise ApiError("ERR_ROUTE_NOT_VALIDATED",
                               "A ROUTE_VALIDATION check on the corridor does not pass.")
        _require_route_current(corridor)
        # Priority 34 — no dispatch into a window already committed on the same
        # corridor.
        if _dispatch_window_conflict(run, corridor):
            raise ApiError("ERR_DISPATCH_WINDOW_CONFLICT",
                           "The dispatch window is already committed on this corridor.")

        # Cascade 1 — elapsed VALIDATED checks expire.
        for c in db.by("launch_readiness_checks", "corridor_id", corridor["id"]):
            if c.get("check_status") == "VALIDATED" and _window_elapsed(c):
                services.mark(c, "check_status", "EXPIRED_FAILED")
                services.flush(c)
        # Cascade 2 — requested apron windows are re-evaluated on the spot.
        services.mark(run, "run_status", "DISPATCH_READY")
        for w in services.windows_for_run(run["id"], ("REQUESTED",)):
            services.mark(w, "window_status",
                          "DISPLACED" if w.get("yield_to_transit") else "APPROVED")
            services.flush(w)
        for tid in {w.get("terminal_id") for w in services.windows_for_run(run["id"])}:
            t = db.get("terminals", tid)
            if t is not None:
                services.recompute_terminal(t)
                services.flush(t)
        services.recompute_corridor(corridor)
        services.flush(corridor)
        db.touch(run, now_iso())
        return ok(run)

    # --------------------------------------------------------------- requeue

    @route(app, "/api/run-plans/<rid>/requeue", ["POST"], ["CarrierDispatcher"])
    def requeue(rid):
        """§3.3: 'the step is only available while the corridor posture is
        RESTRICTED — an OPEN or FROZEN corridor refuses the requeue with
        ERR_INVALID_STATE (409) and a FROZEN corridor answers with the more
        specific ERR_CORRIDOR_FROZEN (409) instead.'"""
        run = must_get("RunPlan", rid)
        raw = body()
        _reject_unknown_body(raw, ())
        corridor = db.get("corridors", run.get("corridor_id"))
        if corridor is None:
            raise ApiError("ERR_CORRIDOR_NOT_FOUND")
        if corridor.get("posture") == "FROZEN":
            raise ApiError("ERR_CORRIDOR_FROZEN",
                           "A FROZEN corridor refuses the requeue.")
        _require_run_state(run, ("DISPATCH_READY",))
        if corridor.get("posture") != "RESTRICTED":
            raise ApiError("ERR_INVALID_STATE",
                           "Only a RESTRICTED corridor accepts a requeue.")
        services.mark(run, "run_status", "READINESS_PENDING")
        terminals = set()
        for w in services.windows_for_run(run["id"], ("APPROVED",)):
            services.mark(w, "window_status", "REQUESTED")
            services.flush(w)
            terminals.add(w.get("terminal_id"))
        for tid in terminals:
            t = db.get("terminals", tid)
            if t is not None:
                services.recompute_terminal(t)
                services.flush(t)
        commitment = db.get("shipper_commitments", run.get("shipper_commitment_id"))
        if commitment is not None:
            # A requeued run still holds its loadboard slot.
            services.recompute_commitment(commitment)
            services.flush(commitment)
        services.flush(run)
        return ok(run)

    # ----------------------------------------------------------------- abort

    @route(app, "/api/run-plans/<rid>/abort", ["POST"], ["ComplianceOfficer"])
    def abort(rid):
        """§3.3: a run plan may be aborted from DRAFT, READINESS_PENDING or
        DISPATCH_READY only."""
        run = must_get("RunPlan", rid)
        raw = body()
        _reject_unknown_body(raw, ())
        if run.get("run_status") in ("COMPLETED", "ABORTED"):
            raise ApiError("ERR_RUN_PLAN_TERMINAL",
                           "A terminal run plan rejects further transitions.")
        _require_run_state(run, ("DRAFT", "READINESS_PENDING", "DISPATCH_READY"))
        services.abort_run_plan(run)
        return ok(run)

    # ------------------------------------------------------ highway segment

    @route(app, "/api/run-plans/<rid>/start-highway-segment", ["POST"],
           ["CarrierDispatcher"])
    def start_highway_segment(rid):
        """§3.4: the strictest gate in the run lifecycle."""
        run = must_get("RunPlan", rid)
        raw = body()
        _reject_unknown_body(raw, ())
        corridor = db.get("corridors", run.get("corridor_id"))
        if corridor is None:
            raise ApiError("ERR_CORRIDOR_NOT_FOUND")
        posture = corridor.get("posture")
        if posture == "FROZEN":
            raise ApiError("ERR_CORRIDOR_FROZEN",
                           "A FROZEN corridor rejects the highway segment start.")
        _require_run_state(run, ("DISPATCH_READY",))
        if posture == "RESTRICTED":
            raise ApiError("ERR_CORRIDOR_RESTRICTED",
                           "A RESTRICTED corridor rejects an operation pinned to live weather.")
        # §3.4: the human handoff must be physically reserved before the truck rolls.
        if not services.windows_for_run(run["id"], ("APPROVED",)):
            raise ApiError("ERR_NO_APPROVED_HANDOFF_WINDOW",
                           "No approved apron handoff window on the run plan.")
        # §3.4: no remote support assignment may be sitting in SCHEDULED or
        # MONITORING while declaring the STANDBY_TAKEOVER intervention protocol.
        for a in db.by("remote_support_assignments", "run_plan_id", run["id"]):
            if a.get("assignment_status") in ("SCHEDULED", "MONITORING") \
                    and a.get("intervention_protocol") == "STANDBY_TAKEOVER":
                raise ApiError("ERR_INVALID_STATE",
                               "A standby-takeover monitoring window blocks the start.")
        if D(corridor.get("weather_risk_score", 0)) > 80:
            raise ApiError("ERR_WEATHER_RESTRICTED",
                           "The corridor weather_risk_score exceeds 80.")
        if services.corridor_has_overdue_program(corridor):
            raise ApiError("ERR_MAINTENANCE_OVERDUE",
                           "A fleet unit assigned to the corridor has an OVERDUE programme.")

        services.mark(run, "run_status", "IN_TRANSIT")
        terminals = set()
        for w in services.windows_for_run(run["id"], ("APPROVED",)):
            services.mark(w, "window_status", "IN_SERVICE")
            services.flush(w)
            terminals.add(w.get("terminal_id"))
        for tid in terminals:
            t = db.get("terminals", tid)
            if t is not None:
                services.recompute_terminal(t)
                services.flush(t)
        services.flush(run)
        return ok(run)

    # -------------------------------------------------------------- complete

    @route(app, "/api/run-plans/<rid>/complete", ["POST"], ["CarrierDispatcher"])
    def complete(rid):
        """§3.4: completion closes the commercial side of the run."""
        run = must_get("RunPlan", rid)
        raw = body()
        _reject_unknown_body(raw, ())
        _require_run_state(run, ("IN_TRANSIT",))
        commitment = db.get("shipper_commitments", run.get("shipper_commitment_id"))
        services.mark(run, "run_status", "COMPLETED")
        if commitment is not None:
            commitment["commitment_status"] = "SHIPPED"
            commitment["shipped_at"] = now_iso()
            services.recompute_commitment(commitment)
            services.flush(commitment)
        carrier = services.carrier_of_run(run)
        if carrier is not None:
            services.recompute_carrier_safety_from_runs(carrier)
            services.recompute_carrier_rate_settlement(carrier)
            services.flush(carrier)
        services.flush(run)
        return ok(run)

    # -------------------------------------------------------------- safe stop

    @route(app, "/api/run-plans/<rid>/safe-stop", ["POST"], ["RemoteSupportOperator"])
    def safe_stop(rid):
        """§3.4: requires a monitoring assignment on the run to be in MONITORING
        status; executing it moves the run back to READINESS_PENDING."""
        run = must_get("RunPlan", rid)
        raw = body()
        _reject_unknown_body(raw, ())
        corridor = db.get("corridors", run.get("corridor_id"))
        if corridor is None:
            raise ApiError("ERR_CORRIDOR_NOT_FOUND")
        if corridor.get("posture") == "FROZEN":
            raise ApiError("ERR_CORRIDOR_FROZEN")
        _require_run_state(run, ("IN_TRANSIT",))
        monitoring = [a for a in db.by("remote_support_assignments", "run_plan_id", run["id"])
                      if a.get("assignment_status") == "MONITORING"]
        if not monitoring:
            raise ApiError("ERR_INVALID_STATE",
                           "No monitoring assignment on the run is in MONITORING status.")
        uid = actor_id()
        assignment = None
        for a in monitoring:
            if uid in (a.get("remote_operator_id"), a.get("safety_support_operator_id")):
                assignment = a
                break
        if assignment is None:
            # §2.1: ownership checks on any resource that references a
            # DriverProspect compare the resource's foreign-key field to X-User-ID.
            if db.get("driver_prospects", uid) is not None:
                raise ApiError("ERR_UNAUTHORIZED",
                               "The monitoring window is held by another operator.")
            assignment = monitoring[0]

        carrier = services.carrier_of_run(run)
        fee, _exposure = calc.safe_stop_fee(corridor, run, carrier) if carrier else (Decimal(0), Decimal(0))
        services.mark(assignment, "safe_stop_required", True)
        services.mark(assignment, "safe_stop_fee_cents", fee)
        services.expire_monitoring(assignment, "SAFE_STOP_EXPIRED")

        services.mark(run, "run_status", "READINESS_PENDING")
        services.cancel_run_windows(run["id"], ("REQUESTED", "APPROVED", "IN_SERVICE"))
        if carrier is not None:
            services.recompute_carrier_recordable(carrier)
            services.recompute_carrier(carrier)
            services.flush(carrier)
        services.mark(corridor, "has_blocking_incident",
                      services.compute_blocking_incident(corridor["id"]))
        services.recompute_corridor(corridor)
        services.flush(corridor)
        services.maybe_recover_limited(corridor)
        services.flush(run)
        return ok(run)

    # --------------------------------------------------------------- chassis

    @route(app, "/api/run-plans/<rid>/chassis", ["POST"], ["CarrierDispatcher"])
    def attach_chassis(rid):
        """§3.11: a CarrierDispatcher attaches a RunPlanChassis by supplying a
        chassis_code and a coverage_days of at least 1."""
        run = must_get("RunPlan", rid)
        raw = body()
        unknown = _unknown(raw, ("chassis_code", "coverage_days"))
        if unknown:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % unknown)
        if "chassis_code" not in raw or "coverage_days" not in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "chassis_code and coverage_days are required.")
        days = coerce_int(raw["coverage_days"])
        if days < 1:
            raise ApiError("ERR_INVALID_REQUEST", "coverage_days must be at least 1.")
        row = create("RunPlanChassis", {
            "run_plan_id": run["id"],
            "chassis_code": raw["chassis_code"],
            "coverage_days": days,
        })
        row["chassis_status"] = "HELD"
        rate = calc.chassis_holding_rate(run.get("per_mile_rate_cents", 0), days)
        services.mark(row, "holding_rate_cents", rate)
        services.flush(row)
        services.mark(run, "run_window_rate_cents", rate)
        services.flush(run)
        return ok(row, 201)

    @route(app, "/api/run-plans/<rid>/chassis", ["GET"], ["Any"])
    def list_chassis(rid):
        must_get("RunPlan", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("run_plan_chassis", "run_plan_id", rid)),
                       limit, offset)

    @route(app, "/api/run-plan-chassis/<rid>/recompute", ["POST"], ["CarrierDispatcher"])
    def recompute_chassis(rid):
        """§3.11: a re-price requires the chassis record's holding rate to be
        recomputed, which in turn recomputes the owning run's
        run_window_rate_cents."""
        chassis = must_get("RunPlanChassis", rid)
        raw = body()
        _reject_unknown_body(raw, ())
        run = db.get("run_plans", chassis.get("run_plan_id"))
        if run is None:
            raise ApiError("ERR_RUN_PLAN_NOT_FOUND")
        rate = calc.chassis_holding_rate(run.get("per_mile_rate_cents", 0),
                                         chassis.get("coverage_days", 0))
        services.mark(chassis, "holding_rate_cents", rate)
        services.flush(chassis)
        services.mark(run, "run_window_rate_cents", rate)
        services.flush(run)
        return ok(chassis)

    # ---------------------------------------------------------- sub-resources

    @route(app, "/api/run-plans/<rid>/launch-readiness-checks", ["GET"], ["Any"])
    def run_plan_checks(rid):
        must_get("RunPlan", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("launch_readiness_checks", "prior_run_plan_id", rid)),
                       limit, offset)

    @route(app, "/api/run-plans/<rid>/service-windows", ["GET"], ["Any"])
    def run_plan_windows(rid):
        must_get("RunPlan", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("terminal_service_windows", "run_plan_id", rid)),
                       limit, offset)

    @route(app, "/api/run-plans/<rid>/incident-reports", ["GET"], ["Any"])
    def run_plan_incidents(rid):
        must_get("RunPlan", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("incident_reports", "run_plan_id", rid)),
                       limit, offset)

    @route(app, "/api/run-plans/<rid>/shipping-instructions", ["GET"], ["Any"])
    def run_plan_instructions(rid):
        must_get("RunPlan", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("shipping_instructions", "run_plan_id", rid)),
                       limit, offset)

    @route(app, "/api/run-plans/<rid>/haulers", ["GET"], ["Any"])
    def run_plan_haulers(rid):
        must_get("RunPlan", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("run_plan_haulers", "run_plan_id", rid)),
                       limit, offset)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _unknown(raw, allowed):
    for key in raw:
        if key not in allowed:
            return key
    return None


def _reject_unknown_body(raw, allowed):
    key = _unknown(raw, tuple(allowed))
    if key:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' is not declared for this endpoint." % key)


def _check_version(raw, field, row):
    if field not in raw or raw[field] is None:
        return
    if int(raw[field]) != int(row.get("version", 1)):
        raise ApiError("ERR_STALE_VERSION",
                       "The supplied expected version does not match the current version.")


def _require_run_state(run, allowed):
    status = run.get("run_status")
    if status in ("COMPLETED", "ABORTED"):
        raise ApiError("ERR_RUN_PLAN_TERMINAL",
                       "A terminal run plan rejects further transitions.")
    if status not in allowed:
        raise ApiError("ERR_INVALID_STATE",
                       "The run plan's current state does not permit the transition.")


def _attach_discount(run, carrier):
    run["_committed_discount_cents"] = calc.discount_for_tier(carrier.get("safety_tier"))
    services.mark(run, "committed_discount_cents",
                  calc.discount_for_tier(carrier.get("safety_tier")))


def _commitment_covers(commitment, start_day, end_day):
    """§3.2: the reserved capacity interval runs from
    reserved_window_start_epoch_day, inclusive, to reserved_window_end_epoch_day,
    exclusive."""
    if not end_day > start_day:
        return False
    rs = int(commitment.get("reserved_window_start_epoch_day") or 0)
    re_ = int(commitment.get("reserved_window_end_epoch_day") or 0)
    return rs <= start_day and end_day <= re_


def _checks_within_tolerance(corridor, load_securement_error=False):
    for c in db.by("launch_readiness_checks", "corridor_id", corridor["id"]):
        if c.get("check_status") in ("CALIBRATION_PASSED", "VALIDATED"):
            if D(c.get("calibration_variance_ms", 0)) > 150 or c.get("check_result") == "FAIL":
                code = "ERR_LOAD_SECUREMENT_FAILED" if load_securement_error else "ERR_CALIBRATION_FAILED"
                raise ApiError(code,
                               "A readiness check on the corridor fails the tolerance.")
    if load_securement_error:
        for c in db.by("launch_readiness_checks", "corridor_id", corridor["id"]):
            if c.get("check_result") == "FAIL":
                raise ApiError("ERR_CALIBRATION_FAILED",
                               "A readiness check on the corridor carries result FAIL.")


def _safety_case_only_draft(corridor):
    cases = db.by("safety_cases", "corridor_id", corridor["id"])
    if not cases:
        return False
    if any(c.get("case_status") == "FILED" for c in cases):
        return False
    return all(c.get("case_status") == "DRAFT" for c in cases)


def _run_overlap(run, corridor, commitment):
    """§3.2 coverage exclusivity: the corridor may not already carry a covered run
    plan in IN_TRANSIT when a second plan for the same coverage window is
    tendered."""
    for other in db.by("run_plans", "corridor_id", corridor["id"]):
        if other["id"] == run["id"]:
            continue
        if other.get("run_status") != "IN_TRANSIT":
            continue
        if other.get("window_start_epoch_day") != run.get("window_start_epoch_day"):
            continue
        if other.get("window_end_epoch_day") != run.get("window_end_epoch_day"):
            continue
        return True
    return False


def _dispatch_window_conflict(run, corridor):
    """§3.3: 'A dispatch request into a window already committed on the same
    corridor is refused with ERR_DISPATCH_WINDOW_CONFLICT (409).'"""
    for other in db.by("run_plans", "corridor_id", corridor["id"]):
        if other["id"] == run["id"]:
            continue
        if other.get("run_status") not in ("DISPATCH_READY", "IN_TRANSIT"):
            continue
        if other.get("window_start_epoch_day") != run.get("window_start_epoch_day"):
            continue
        if other.get("window_end_epoch_day") != run.get("window_end_epoch_day"):
            continue
        return True
    return False


def _require_route_current(corridor):
    calculated = parse_iso(corridor.get("route_validation_calculated_at"))
    if calculated is None:
        raise ApiError("ERR_ROUTE_NOT_VALIDATED",
                       "The mapped route has not been validated.")
    days = None
    for c in db.by("launch_readiness_checks", "corridor_id", corridor["id"]):
        if c.get("check_type") == "ROUTE_VALIDATION":
            days = int(c.get("valid_window_days") or 0)
            break
    if days is None:
        return
    if core.now() > calculated + timedelta(days=days):
        raise ApiError("ERR_ROUTE_NOT_VALIDATED",
                       "The mapped-route validation has aged past its validity window.")


def _window_elapsed(check):
    start = parse_iso(check.get("valid_window_start_at"))
    if start is None:
        return False
    return core.now() > start + timedelta(days=int(check.get("valid_window_days") or 0))