"""Corridors, launch readiness and the launch gate — PRD §2.4, §2.6, §3.1.

Endpoints 22-36 of §4, plus the readiness checks at 51-56.
"""

from decimal import Decimal

import db
import core
import models
import services
import calculations as calc
from core import ApiError, D, rhu, parse_iso, now_iso, to_iso, try_iso
from response import ok, page_of
from http_util import (bind, pagination, must_get, get_or_none, must_resolve,
                       body, coerce_int, coerce_num, check_occ, arg)
from routes._common import route
from models import create

PUBLIC = ["corridor_name", "origin_terminal_id", "destination_terminal_id",
          "highway_segment_miles", "mapped_route", "weather_profile",
          "weather_risk_score"]

WEATHER_PROFILES = ("CLEAR_DEFAULT", "HIGH_WIND", "HEAVY_PRECIPITATION",
                    "LOW_VISIBILITY", "WINTER_SURFACE")

CHECK_TYPES = ("SENSOR_CALIBRATION", "ROUTE_VALIDATION", "LOAD_SECUREMENT")
CHECK_RESULTS = ("PASS", "FAIL", "PENDING")


def register(app):

    # ------------------------------------------------------------------ CRUD

    @route(app, "/api/corridors", ["POST"], ["CorridorOperationsManager"])
    def create_corridor():
        payload = bind("Corridor", PUBLIC)
        origin = must_resolve("Terminal", payload.get("origin_terminal_id"))
        destination = must_resolve("Terminal", payload.get("destination_terminal_id"))
        # §3.1: "the two terminal identifiers must be different terminals".
        if origin["id"] == destination["id"]:
            raise ApiError("ERR_INVALID_ROUTE",
                           "Origin and destination terminals must differ.")
        profile = payload.get("weather_profile")
        if profile not in WEATHER_PROFILES:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown weather_profile.")
        payload["highway_segment_miles"] = coerce_num(payload.get("highway_segment_miles"))
        payload["weather_risk_score"] = coerce_int(payload.get("weather_risk_score", 0))
        if not isinstance(payload.get("mapped_route"), dict):
            raise ApiError("ERR_INVALID_REQUEST", "mapped_route must be an object.")
        row = create("Corridor", payload)
        # §3.1: "A newly registered corridor is PLANNED, its derived
        # check_pass_count and check_count are both 0, and its posture reads
        # FROZEN — a corridor with no calibration evidence is inert by
        # construction."
        row["corridor_status"] = "PLANNED"
        services.recompute_corridor(row)
        services.flush(row)
        return ok(row, 201)

    @route(app, "/api/corridors", ["GET"], ["Any"])
    def list_corridors():
        limit, offset = pagination()
        return page_of(db.sort_created(db.all_rows("corridors")), limit, offset)

    @route(app, "/api/corridors/<rid>", ["GET"], ["Any"])
    def get_corridor(rid):
        return ok(must_get("Corridor", rid))

    # ------------------------------------------------- launch readiness start

    @route(app, "/api/corridors/<rid>/launch-readiness/start", ["POST"],
           ["CorridorOperationsManager"])
    def start_readiness(rid):
        """§3.1: three preconditions bind the open; the SUSPENDED recovery route
        requires no incident report on the corridor to remain in INVESTIGATING or
        SUBMITTED."""
        corridor = must_get("Corridor", rid)
        status = corridor.get("corridor_status")
        if status not in ("PLANNED", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE",
                           "Launch readiness can only be opened from PLANNED or SUSPENDED.")
        if status == "SUSPENDED":
            if services.compute_blocking_incident(rid) or _has_open_incident(rid):
                raise ApiError("ERR_BLOCKED_BY_INCIDENT",
                               "An incident report on the corridor is still open.")
        else:
            for tid in (corridor.get("origin_terminal_id"), corridor.get("destination_terminal_id")):
                terminal = db.get("terminals", tid)
                if terminal is None or terminal.get("terminal_state") != "OPERATIONAL":
                    raise ApiError("ERR_INVALID_STATE",
                                   "Both hub terminals must be OPERATIONAL.")
            if not D(corridor.get("highway_segment_miles", 0)) > 0:
                raise ApiError("ERR_INVALID_STATE",
                               "highway_segment_miles must be greater than zero.")
        # §3.1: re-entering review is deliberately destructive — every readiness
        # check on the corridor that has not yet reached a terminal result moves to
        # EXPIRED_FAILED and check_pass_count resets to 0.
        if status == "SUSPENDED":
            for c in db.by("launch_readiness_checks", "corridor_id", rid):
                if c.get("check_status") != "EXPIRED_FAILED":
                    services.mark(c, "check_status", "EXPIRED_FAILED")
                    services.flush(c)
        corridor["corridor_status"] = "READINESS_REVIEW"
        services.mark(corridor, "launch_authorized_at", None)
        services.recompute_corridor(corridor)
        services.flush(corridor)
        return ok(corridor)

    # ------------------------------------------------------- launch validate

    @route(app, "/api/corridors/<rid>/launch-readiness/validate", ["POST"],
           ["CorridorOperationsManager"])
    def validate_readiness(rid):
        corridor = must_get("Corridor", rid)
        raw = body()
        for key in raw:
            if key != "expected_corridor_version":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        # §2.9 OCC — a pure equality test against the current version.
        if "expected_corridor_version" in raw and raw["expected_corridor_version"] is not None:
            if int(raw["expected_corridor_version"]) != int(corridor.get("version", 1)):
                raise ApiError("ERR_STALE_VERSION",
                               "The corridor version has advanced since it was read.")
        status = corridor.get("corridor_status")
        if status == "READINESS_REVIEW":
            _gate_full(corridor, raw)
        elif status == "LIMITED":
            _gate_recovery(corridor, raw)
        else:
            raise ApiError("ERR_INVALID_STATE",
                           "Launch readiness can only be validated from READINESS_REVIEW or LIMITED.")
        corridor["corridor_status"] = "ACTIVE"
        corridor["launch_authorized_at"] = now_iso()
        for c in db.by("launch_readiness_checks", "corridor_id", rid):
            if c.get("check_status") == "CALIBRATION_PASSED":
                services.mark(c, "check_status", "VALIDATED")
                services.flush(c)
        services.recompute_corridor(corridor)
        db.touch(corridor, now_iso())
        return ok(corridor)

    # ----------------------------------------------------------- launch fail

    @route(app, "/api/corridors/<rid>/launch-readiness/fail", ["POST"],
           ["ComplianceOfficer"])
    def fail_readiness(rid):
        corridor = must_get("Corridor", rid)
        raw = body()
        for key in raw:
            if key != "expected_corridor_version":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if "expected_corridor_version" in raw and raw["expected_corridor_version"] is not None:
            if int(raw["expected_corridor_version"]) != int(corridor.get("version", 1)):
                raise ApiError("ERR_STALE_VERSION",
                               "The corridor version has advanced since it was read.")
        if corridor.get("corridor_status") not in ("ACTIVE", "LIMITED"):
            raise ApiError("ERR_INVALID_STATE",
                           "Only an ACTIVE or LIMITED corridor can be failed.")
        # §3.1: the precondition is exactly that has_blocking_incident is true.
        if not services.compute_blocking_incident(rid):
            raise ApiError("ERR_BLOCKED_BY_INCIDENT",
                           "The corridor carries no blocking incident.")
        services.suspend_corridor(corridor)
        db.touch(corridor, now_iso())
        return ok(corridor)

    # -------------------------------------------------------------- retire

    @route(app, "/api/corridors/<rid>/retire", ["POST"], ["ComplianceOfficer"])
    def retire_corridor(rid):
        corridor = must_get("Corridor", rid)
        if corridor.get("corridor_status") not in ("READINESS_REVIEW", "ACTIVE"):
            raise ApiError("ERR_INVALID_STATE",
                           "Only a READINESS_REVIEW or ACTIVE corridor can be retired.")
        for run in db.by("run_plans", "corridor_id", rid):
            if run.get("run_status") == "IN_TRANSIT":
                raise ApiError("ERR_RUN_PLAN_IN_TRANSIT",
                               "A run plan on this corridor is still on the highway segment.")
        carriers = set()
        for run in db.by("run_plans", "corridor_id", rid):
            if run.get("run_status") not in ("COMPLETED", "ABORTED"):
                carriers.add(run.get("carrier_id"))
                services.abort_run_plan(run)
        corridor["corridor_status"] = "RETIRED"
        services.recompute_corridor(corridor)
        services.flush(corridor)
        # §3.1: retiring an ACTIVE corridor moves the carriers referenced by its
        # runs to OFFBOARDED when the carrier has no other ACTIVE corridor left.
        for cid in carriers:
            carrier = db.get("carriers", cid)
            if carrier is None:
                continue
            if not _carrier_has_active_corridor(cid, exclude=rid):
                services.mark(carrier, "carrier_status", "OFFBOARDED")
            services.flush(carrier)
        return ok(corridor)

    # ----------------------------------------------------- sub-resource reads

    @route(app, "/api/corridors/<rid>/launch-readiness-checks", ["GET"], ["Any"])
    def corridor_checks(rid):
        must_get("Corridor", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("launch_readiness_checks", "corridor_id", rid)),
                       limit, offset)

    @route(app, "/api/corridors/<rid>/state-authorities", ["GET"], ["Any"])
    def corridor_authorities(rid):
        corridor = must_get("Corridor", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(services.corridor_state_authorities(corridor)),
                       limit, offset)

    @route(app, "/api/corridors/<rid>/state-authorities/<said>", ["GET"], ["Any"])
    def corridor_authority(rid, said):
        corridor = must_get("Corridor", rid)
        authority = db.get("state_authorities", said)
        if authority is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND")
        if authority not in services.corridor_state_authorities(corridor):
            raise ApiError("ERR_REFERENCE_NOT_FOUND")
        return ok(authority)

    @route(app, "/api/corridors/<rid>/run-plans", ["GET"], ["Any"])
    def corridor_run_plans(rid):
        must_get("Corridor", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("run_plans", "corridor_id", rid)), limit, offset)

    @route(app, "/api/corridors/<rid>/safety-cases", ["GET"], ["Any"])
    def corridor_safety_cases(rid):
        must_get("Corridor", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("safety_cases", "corridor_id", rid)), limit, offset)

    @route(app, "/api/corridors/<rid>/incident-reports", ["GET"], ["Any"])
    def corridor_incidents(rid):
        must_get("Corridor", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("incident_reports", "corridor_id", rid)),
                       limit, offset)

    @route(app, "/api/corridors/<rid>/regulatory-engagements", ["GET"], ["Any"])
    def corridor_engagements(rid):
        must_get("Corridor", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("regulatory_engagements", "corridor_id", rid)),
                       limit, offset)

    @route(app, "/api/corridors/<rid>/remote-support-assignments", ["GET"], ["Any"])
    def corridor_assignments(rid):
        must_get("Corridor", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("remote_support_assignments", "corridor_id", rid)),
                       limit, offset)

    # ------------------------------------------------- readiness check create

    @route(app, "/api/corridors/<rid>/launch-readiness-checks", ["POST"],
           ["CorridorOperationsManager"])
    def create_check(rid):
        corridor = must_get("Corridor", rid)
        raw = body()
        allowed = {"check_type", "check_result", "suite_latitude", "suite_longitude",
                   "load_payload_lbs", "prior_run_plan_id", "valid_window_days",
                   "is_test_payload", "correlation_key"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        for key in ("check_type", "check_result", "correlation_key"):
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        if raw["check_type"] not in CHECK_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown check_type.")
        if raw["check_result"] not in CHECK_RESULTS:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown check_result.")

        # §2.6 / §2.12 idempotency: SENSOR_CALIBRATION and ROUTE_VALIDATION rows
        # are deduplicated on (corridor_id, correlation_key, epoch_start_at); a
        # repeat within the same epoch returns the original row with HTTP 200.
        # The pairwise comparison is the primary mechanism, so a twin offered
        # with the same check type and correlation key is answered with 200 even
        # before the active epoch is settled.
        epoch_start = core.active_epoch_start()
        if raw["check_type"] in ("SENSOR_CALIBRATION", "ROUTE_VALIDATION"):
            for c in db.by("launch_readiness_checks", "corridor_id", rid):
                if c.get("check_type") != raw["check_type"]:
                    continue
                if c.get("correlation_key") != raw["correlation_key"]:
                    continue
                same_epoch = (c.get("epoch_start_at") is None or epoch_start is None
                              or c.get("epoch_start_at") == epoch_start)
                if same_epoch:
                    return ok(c, 200)

        prior_run_plan_id = raw.get("prior_run_plan_id")
        if prior_run_plan_id is not None:
            if get_or_none("RunPlan", prior_run_plan_id) is None:
                raise ApiError("ERR_REFERENCE_NOT_FOUND")
            # §3.1: a corridor may store at most one such plan.
            for c in db.by("launch_readiness_checks", "corridor_id", rid):
                if c.get("prior_run_plan_id"):
                    raise ApiError("ERR_INVALID_STATE",
                                   "The corridor already stores a prior run plan.")

        payload = {
            "corridor_id": rid,
            "check_type": raw["check_type"],
            "check_result": raw["check_result"],
            "suite_latitude": round(float(raw.get("suite_latitude", 0)), 3),
            "suite_longitude": round(float(raw.get("suite_longitude", 0)), 3),
            "load_payload_lbs": int(raw.get("load_payload_lbs", 0) or 0),
            "prior_run_plan_id": prior_run_plan_id,
            "valid_window_days": int(raw.get("valid_window_days", 180) or 0),
            "is_test_payload": bool(raw.get("is_test_payload", False)),
            "correlation_key": raw["correlation_key"],
        }
        row = create("LaunchReadinessCheck", payload)
        row["check_status"] = "INITIALIZED"
        row["valid_window_start_at"] = now_iso()
        row["epoch_start_at"] = epoch_start
        services.mark(row, "calibration_variance_ms", _variance(row))
        services.flush(row)
        services.recompute_corridor(corridor)
        services.flush(corridor)
        return ok(row, 201)


def _variance(check):
    """§2.6: floor(2.4 * suite_latitude + 1.6 * suite_longitude, 3)."""
    return calc.floor_dec(D(check.get("suite_latitude", 0)) * Decimal("2.4")
                          + D(check.get("suite_longitude", 0)) * Decimal("1.6"), 3)


def _has_open_incident(corridor_id):
    return any(r.get("report_status") in ("INVESTIGATING", "SUBMITTED")
               for r in db.by("incident_reports", "corridor_id", corridor_id))


def _carrier_has_active_corridor(carrier_id, exclude=None):
    for run in db.by("run_plans", "carrier_id", carrier_id):
        if run.get("corridor_id") == exclude:
            continue
        corridor = db.get("corridors", run.get("corridor_id"))
        if corridor is not None and corridor.get("corridor_status") == "ACTIVE":
            return True
    return False


# ---------------------------------------------------------------------------
# The launch gate — §3.1, evaluated in the order the PRD fixes.
# ---------------------------------------------------------------------------


def _gate_full(corridor, raw):
    cid = corridor["id"]

    # Step 1 — the corridor's own readiness arithmetic: check_pass_count must be
    # at least check_count with check_count at least 1, and no check on the
    # corridor may carry check_result FAIL.
    checks = [c for c in db.by("launch_readiness_checks", "corridor_id", cid)
              if not c.get("is_test_payload")]
    if int(corridor.get("check_pass_count") or 0) < int(corridor.get("check_count") or 0) \
            or int(corridor.get("check_count") or 0) < 1:
        raise ApiError("ERR_READINESS_CHECK_FAILED",
                       "The corridor's readiness checks are unresolved.")
    if any(c.get("check_result") == "FAIL" for c in checks):
        raise ApiError("ERR_READINESS_CHECK_FAILED",
                       "A readiness check on the corridor carries result FAIL.")

    # Step 2 — calibration integrity: every check in CALIBRATION_PASSED or
    # VALIDATED must sit at or under the 150 millisecond variance tolerance.
    for c in checks:
        if c.get("check_status") in ("CALIBRATION_PASSED", "VALIDATED"):
            if D(c.get("calibration_variance_ms", 0)) > 150:
                raise ApiError("ERR_CALIBRATION_FAILED",
                               "A calibration reading exceeds the 150 ms tolerance.")

    # Step 3 — load securement.
    secured = [c for c in checks if c.get("check_type") == "LOAD_SECUREMENT"
               and int(c.get("load_payload_lbs") or 0) >= 40000
               and c.get("check_result") == "PASS"]
    if not secured:
        raise ApiError("ERR_LOAD_SECUREMENT_FAILED",
                       "No passing LOAD_SECUREMENT check reaches 40000 lbs.")

    # Steps 4 and 5 — the safety case and the weather ceiling of 80.
    _gate_safety_case(corridor, raw)
    if D(corridor.get("weather_risk_score", 0)) > 80:
        raise ApiError("ERR_WEATHER_RESTRICTED",
                       "The corridor weather_risk_score exceeds 80.")

    # Step 6 — an unresolved blocking incident.
    if services.compute_blocking_incident(cid):
        raise ApiError("ERR_BLOCKED_BY_INCIDENT",
                       "The corridor carries an unresolved blocking incident.")

    # Step 7 — route validation.
    _gate_route_validation(corridor)

    # Step 8 — maintenance standing.
    if services.corridor_has_overdue_program(corridor):
        raise ApiError("ERR_MAINTENANCE_OVERDUE",
                       "A fleet unit assigned to the corridor has an OVERDUE programme.")


def _gate_recovery(corridor, raw):
    """§3.1: the LIMITED recovery route requires no inspection programme in
    OVERDUE status, weather_risk_score below 80 and has_blocking_incident false.
    """
    if services.corridor_has_overdue_program(corridor):
        raise ApiError("ERR_MAINTENANCE_OVERDUE",
                       "A fleet unit assigned to the corridor has an OVERDUE programme.")
    if D(corridor.get("weather_risk_score", 0)) >= 80:
        raise ApiError("ERR_WEATHER_RESTRICTED",
                       "The corridor weather_risk_score is 80 or above.")
    if services.compute_blocking_incident(corridor["id"]):
        raise ApiError("ERR_BLOCKED_BY_INCIDENT",
                       "The corridor carries an unresolved blocking incident.")
    _gate_safety_case(corridor, raw)
    _gate_route_validation(corridor)


def _gate_safety_case(corridor, raw):
    """§3.7: a corridor whose filed case has aged past the engagement window —
    measured inclusively — is refused with ERR_SAFETY_CASE_STALE, as is a corridor
    with no filed case at all."""
    if not services.supervising_requires_safety_case(corridor):
        return
    filed = services.filed_case_for(corridor["id"])
    if filed is None:
        raise ApiError("ERR_SAFETY_CASE_STALE",
                       "The corridor has no filed safety case.")
    window = services.supervising_window_days(corridor)
    filed_at = parse_iso(filed.get("filed_date"))
    if filed_at is None or window is None:
        return
    age = (core.now().date() - filed_at.date()).days
    if age > window:
        raise ApiError("ERR_SAFETY_CASE_STALE",
                       "The filed safety case has aged past the engagement window.")


def _gate_route_validation(corridor):
    """§3.1 step seven: refuse with ERR_ROUTE_NOT_VALIDATED when the mapped route
    has not been validated or its validation has aged past the check's validity
    window, and require either has_hov_lane to be true or
    requires_tunnel_clearance to be false."""
    route = corridor.get("mapped_route") or {}
    if not bool(route.get("has_hov_lane")) and bool(route.get("requires_tunnel_clearance")):
        raise ApiError("ERR_ROUTE_NOT_VALIDATED",
                       "The mapped route fails validation.")
    calculated_at = parse_iso(corridor.get("route_validation_calculated_at"))
    if calculated_at is None:
        raise ApiError("ERR_ROUTE_NOT_VALIDATED",
                       "The mapped route has not been validated.")
    days = None
    for c in db.by("launch_readiness_checks", "corridor_id", corridor["id"]):
        if c.get("check_type") == "ROUTE_VALIDATION":
            days = int(c.get("valid_window_days") or 0)
            break
    if days is None:
        return
    from datetime import timedelta
    if core.now() > calculated_at + timedelta(days=days):
        raise ApiError("ERR_ROUTE_NOT_VALIDATED",
                       "The mapped-route validation has aged past its validity window.")