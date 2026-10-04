"""Launch readiness check actions — PRD §2.6, §3.1, endpoints 51-56."""

from datetime import timedelta

import db
import core
import services
import calculations as calc
from core import ApiError, D, now_iso, parse_iso
from response import ok, page_of
from http_util import pagination, must_get, body, arg
from routes._common import route


def register(app):

    @route(app, "/api/launch-readiness-checks", ["GET"], ["Any"])
    def list_checks():
        limit, offset = pagination()
        rows = db.all_rows("launch_readiness_checks")
        corridor_id = arg("corridor_id")
        if corridor_id:
            rows = [c for c in rows if c.get("corridor_id") == corridor_id]
        check_type = arg("check_type")
        if check_type:
            rows = [c for c in rows if c.get("check_type") == check_type]
        check_status = arg("check_status")
        if check_status:
            rows = [c for c in rows if c.get("check_status") == check_status]
        return page_of(db.sort_created(rows), limit, offset)

    @route(app, "/api/launch-readiness-checks/<rid>", ["GET"], ["Any"])
    def get_check(rid):
        return ok(_with_contribution(must_get("LaunchReadinessCheck", rid)))

    @route(app, "/api/launch-readiness-checks/<rid>/calibrate", ["POST"],
           ["CorridorOperationsManager"])
    def calibrate(rid):
        """§3.1: driving the sensor calibration step moves the check to
        CALIBRATION_PASSED and recomputes calibration_variance_ms,
        check_pass_count, the corridor's posture and the readiness score."""
        check = must_get("LaunchReadinessCheck", rid)
        if check.get("check_status") != "INITIALIZED":
            raise ApiError("ERR_INVALID_STATE",
                           "Only an INITIALIZED check can be calibrated.")
        services.mark(check, "calibration_variance_ms", _variance(check))
        services.mark(check, "check_status", "CALIBRATION_PASSED")
        services.flush(check)
        _recompute_corridor(check.get("corridor_id"))
        return ok(_with_contribution(check))

    @route(app, "/api/launch-readiness-checks/<rid>/validate", ["POST"],
           ["CorridorOperationsManager"])
    def validate_check(rid):
        """§3.1: validating the mapped-route window requires the client's
        expected_check_version to match the check's current version and refreshes
        the corridor's route_validation_calculated_at."""
        check = must_get("LaunchReadinessCheck", rid)
        raw = body()
        for key in raw:
            if key != "expected_check_version":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if "expected_check_version" in raw and raw["expected_check_version"] is not None:
            if int(raw["expected_check_version"]) != int(check.get("version", 1)):
                raise ApiError("ERR_STALE_VERSION",
                               "The check version has advanced since it was read.")
        if check.get("check_status") not in ("CALIBRATION_PASSED", "VALIDATED"):
            raise ApiError("ERR_INVALID_STATE",
                           "Only a calibrated check can have its route window validated.")
        services.mark(check, "check_status", "VALIDATED")
        services.flush(check)
        corridor = db.get("corridors", check.get("corridor_id"))
        if corridor is not None:
            services.mark(corridor, "route_validation_calculated_at", now_iso())
        _recompute_corridor(check.get("corridor_id"))
        return ok(_with_contribution(check))

    @route(app, "/api/launch-readiness-checks/<rid>/expire", ["POST"],
           ["ComplianceOfficer"])
    def expire_check(rid):
        """§3.1: expiring a check whose validity window has elapsed moves it to
        EXPIRED_FAILED and recomputes check_pass_count, posture and score."""
        check = must_get("LaunchReadinessCheck", rid)
        if check.get("check_status") == "EXPIRED_FAILED":
            raise ApiError("ERR_INVALID_STATE", "The check has already expired.")
        if not _window_elapsed(check):
            raise ApiError("ERR_INVALID_STATE",
                           "The check's validity window has not yet elapsed.")
        services.mark(check, "check_status", "EXPIRED_FAILED")
        services.flush(check)
        _recompute_corridor(check.get("corridor_id"))
        return ok(_with_contribution(check))


def _recompute_corridor(corridor_id):
    corridor = db.get("corridors", corridor_id)
    if corridor is None:
        return
    services.recompute_corridor(corridor)
    services.flush(corridor)


def _variance(check):
    from decimal import Decimal
    return calc.floor_dec(D(check.get("suite_latitude", 0)) * Decimal("2.4")
                          + D(check.get("suite_longitude", 0)) * Decimal("1.6"), 3)


def _window_elapsed(check):
    start = parse_iso(check.get("valid_window_start_at"))
    if start is None:
        return False
    return core.now() > start + timedelta(days=int(check.get("valid_window_days") or 0))


def _with_contribution(check):
    services.mark(check, "check_contribution", calc.check_contribution(check))
    return check