"""PhantomTest endpoints (PRD §3.4, §4)."""

import flask

import db
import response
from errors import fail
from middleware import require
from services import calculations, common

SCORE_MIN = 0
SCORE_MAX = 10


def _window(test):
    start = db.parse_ts(test["acquired_at"])
    end = db.add_minutes(start, test["duration_minutes"])
    return start, end


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open on the right: [start, end) — touching endpoints do not overlap."""
    return a_start < b_end and b_start < a_end


def _window_conflict(unit, acquired_at, duration_minutes, exclude_id=None):
    new_start = db.parse_ts(acquired_at)
    new_end = db.add_minutes(new_start, duration_minutes)
    for other in common.unit_phantom_tests(unit["id"]):
        if other["id"] == exclude_id:
            continue
        if other["result_status"] != "ACQUIRED":
            continue
        start, end = _window(other)
        if _overlaps(new_start, new_end, start, end):
            return True
    return False


def _score_value(payload, name):
    value = payload.get(name)
    if value is None:
        fail("ERR_INVALID_REQUEST", f"{name} is required")
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", f"{name} must be an integer")
    if numeric != int(numeric):
        fail("ERR_INVALID_REQUEST", f"{name} must be an integer")
    integer = int(numeric)
    if integer < SCORE_MIN or integer > SCORE_MAX:
        fail("ERR_INVALID_REQUEST", f"{name} is outside 0..10")
    return integer


def register_routes(app):

    @app.route("/accreditation/phantom-tests", methods=["POST"])
    @require(["FacilityAdmin"])
    def create_phantom_test(principal):
        payload = common.body()
        common.require_fields(
            payload, ["unit_id", "phantom_serial_code", "acquired_at", "duration_minutes"]
        )
        unit = common.get_unit(payload["unit_id"])
        if unit["unit_status"] != "ENROLLED":
            fail("ERR_UNIT_DEFERRED", "the owning modality unit is not ENROLLED")

        deadline = unit.get("testing_deadline_at")
        if deadline is not None and db.parse_ts(deadline) < db.now():
            fail("ERR_SUBMISSION_WINDOW_CLOSED", "the phantom testing window has closed")

        duration = common.as_int(payload, "duration_minutes")
        if _window_conflict(unit, payload["acquired_at"], duration):
            fail("ERR_PHANTOM_SCHEDULE_CONFLICT", "the acquisition window overlaps another test")

        test = common.make_record(
            id=db.new_id(),
            unit_id=unit["id"],
            phantom_serial_code=payload["phantom_serial_code"],
            acquired_at=db.as_ts(payload["acquired_at"]),
            duration_minutes=duration,
            spatial_resolution_score=None,
            contrast_score=None,
            artifact_score=None,
            phantom_total_score=None,
            result_status="ACQUIRED",
            scored_at=None,
        )
        db.PHANTOM_TESTS[test["id"]] = test
        common.touch(unit)
        return response.ok(common.serialize(test), 201)

    @app.route("/accreditation/phantom-tests", methods=["GET"])
    @require(["Any"])
    def list_phantom_tests(principal):
        rows = list(db.PHANTOM_TESTS.values())
        for field in ("unit_id", "result_status"):
            wanted = flask.request.args.get(field)
            if wanted:
                rows = [r for r in rows if r.get(field) == wanted]
        rows.sort(key=lambda r: r["created_at"])
        page, meta = response.paginate(rows, flask.request.args)
        return response.ok(common.serialize_many(page), 200, meta)

    @app.route("/accreditation/phantom-tests/<phantom_test_id>", methods=["GET"])
    @require(["Any"])
    def read_phantom_test(principal, phantom_test_id):
        return response.ok(common.serialize(common.get_phantom_test(phantom_test_id)))

    @app.route("/accreditation/phantom-tests/<phantom_test_id>/score", methods=["POST"])
    @require(["FacilityAdmin"])
    def score_phantom_test(principal, phantom_test_id):
        test = common.get_phantom_test(phantom_test_id)
        payload = common.body()
        unit = common.get_unit(test["unit_id"])
        facility = common.facility_of_unit(unit)

        if test["result_status"] in ("SCORED", "PASS", "FAIL", "VOIDED"):
            fail("ERR_ALREADY_TERMINAL", "the phantom test has already reached a terminal state")
        if test["result_status"] != "ACQUIRED":
            fail("ERR_INVALID_STATE", "the phantom test is not ACQUIRED")
        if unit["unit_status"] != "ENROLLED":
            fail("ERR_UNIT_DEFERRED", "the owning modality unit is not ENROLLED")
        if facility is not None and facility["accreditation_currency"] in ("LAPSED", "SUSPENDED"):
            fail("ERR_ACCREDITATION_LAPSED", "the facility's accreditation has lapsed")

        spatial = _score_value(payload, "spatial_resolution_score")
        contrast = _score_value(payload, "contrast_score")
        artifact = _score_value(payload, "artifact_score")
        if "scored_at" not in payload or payload["scored_at"] is None:
            fail("ERR_INVALID_REQUEST", "scored_at is required")
        scored_at_value = db.as_ts(payload["scored_at"])

        if _window_conflict(unit, test["acquired_at"], test["duration_minutes"], exclude_id=test["id"]):
            fail("ERR_PHANTOM_TEST_CONFLICT", "another acquired test overlaps this window")

        total = calculations.phantom_composite_score(spatial, contrast, artifact)

        stamp = db.now()
        test["spatial_resolution_score"] = spatial
        test["contrast_score"] = contrast
        test["artifact_score"] = artifact
        test["phantom_total_score"] = total
        test["scored_at"] = scored_at_value
        passed = calculations.phantom_passed(total)
        common.set_field(test, "result_status", "SCORED" if passed else "FAIL", stamp)

        common.recompute_phantom_counts(unit)
        unit["last_phantom_score"] = total
        if not passed:
            unit["testing_deadline_at"] = db.shift_days(scored_at_value, 30)
            if facility is not None:
                facility["payer_participation_status"] = "AT_RISK"
        common.touch(unit, stamp)
        return response.ok(common.serialize(test))

    @app.route("/accreditation/phantom-tests/<phantom_test_id>/void", methods=["POST"])
    @require(["FacilityAdmin", "AccreditationBody"])
    def void_phantom_test(principal, phantom_test_id):
        test = common.get_phantom_test(phantom_test_id)
        if test["result_status"] in ("SCORED", "PASS", "FAIL", "VOIDED"):
            fail("ERR_ALREADY_TERMINAL", "the phantom test has already reached a terminal state")
        if test["result_status"] != "ACQUIRED":
            fail("ERR_INVALID_STATE", "the phantom test is not ACQUIRED")

        unit = common.get_unit(test["unit_id"])
        stamp = db.now()
        common.set_field(test, "result_status", "VOIDED", stamp)
        common.recompute_phantom_counts(unit)
        common.touch(unit, stamp)
        return response.ok(common.serialize(test))