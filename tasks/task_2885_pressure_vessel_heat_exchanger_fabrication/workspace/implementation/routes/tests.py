"""Pressure testing: bay scheduling, the witness and the settled result."""

from flask import Blueprint

import db
import validation
from errors import fail
from middleware import ALL_ROLES, guard
from routes import common
from routes.exams import raise_nonconformance
from services import calc, derive

bp = Blueprint("tests", __name__)

TEST_SIDES = ("SHELL_SIDE", "TUBE_SIDE")
TEST_TYPES = ("HYDROSTATIC", "PNEUMATIC")
TEST_BAYS = ("BAY_1", "BAY_2")


def _overlapping(bay_code, start, end):
    occupants = []
    for other in db.all_of("tests"):
        if other["test_bay_code"] != bay_code or other["result"] != "PENDING":
            continue
        other_start = calc.parse_instant(other["scheduled_start"])
        other_end = calc.parse_instant(other["scheduled_end"])
        if start < other_end and end > other_start:
            occupants.append(other)
    return occupants


def _weld_map_gate(job):
    for weld in derive.job_welds(job["id"]):
        if weld["fab_status"] != "WELDED":
            fail("ERR_NDE_INCOMPLETE",
                 "Joint %s has not been welded." % weld["weld_number"])
        if weld["nde_status"] != "ACCEPTED":
            exempt = (weld["nde_status"] == "NOT_PLANNED"
                      and weld["required_volumetric_pct"] == 0
                      and weld["required_surface_method"] is None)
            if not exempt:
                fail("ERR_NDE_INCOMPLETE",
                     "Joint %s has not been examined and accepted."
                     % weld["weld_number"])
    for weld in derive.job_welds(job["id"]):
        if weld["pwht_status"] != "NOT_REQUIRED" and weld["pwht_status"] != "COMPLETE":
            fail("ERR_PWHT_INCOMPLETE",
                 "Joint %s has not been stress-relieved." % weld["weld_number"])
    if derive.nonconformance_open_count(job["id"]) > 0:
        fail("ERR_OPEN_NONCONFORMANCE",
             "The job still carries an open nonconformance.")


@bp.post("/pressure-tests")
@guard(["QCInspector"])
def create_test(ctx):
    body = validation.body()
    job_id = validation.string_field(body, "job_id")
    test_side = validation.enum_field(body, "test_side", TEST_SIDES)
    test_type = validation.enum_field(body, "test_type", TEST_TYPES)
    bay_code = validation.enum_field(body, "test_bay_code", TEST_BAYS)
    scheduled_start = validation.instant_field(body, "scheduled_start")
    scheduled_end = validation.instant_field(body, "scheduled_end")
    if scheduled_end <= scheduled_start:
        fail("ERR_INVALID_REQUEST",
             "Field 'scheduled_end' must fall strictly after 'scheduled_start'.")

    job = db.get("jobs", job_id)
    if job is None:
        fail("ERR_JOB_NOT_FOUND", "No job carries id %s." % job_id)
    if job["status"] not in ("FABRICATION", "TESTING"):
        fail("ERR_INVALID_JOB_STATE",
             "Scheduling a test needs the job in FABRICATION or TESTING.")
    if job["status"] == "FABRICATION":
        _weld_map_gate(job)
    else:
        for other in derive.job_tests(job_id):
            if other["test_side"] == test_side and other["result"] == "PENDING":
                fail("ERR_INVALID_JOB_STATE",
                     "A test on the %s is already pending." % test_side)
    if test_side not in job["required_test_sides"]:
        fail("ERR_TEST_SIDE_NOT_APPLICABLE",
             "This vessel has no %s to test." % test_side)
    if test_type == "PNEUMATIC":
        justification = job["pneumatic_justification"]
        if justification is None or not justification.strip():
            fail("ERR_PNEUMATIC_JUSTIFICATION_REQUIRED",
                 "A pneumatic test needs a recorded justification.")

    occupants = _overlapping(bay_code, scheduled_start, scheduled_end)
    if test_type == "PNEUMATIC":
        if occupants:
            fail("ERR_TEST_BAY_CAPACITY_EXCEEDED",
                 "A pneumatic test needs %s to itself." % bay_code)
    else:
        if any(o["test_type"] == "PNEUMATIC" for o in occupants):
            fail("ERR_TEST_BAY_CAPACITY_EXCEEDED",
                 "A pneumatic test already holds %s over that window." % bay_code)
        if len([o for o in occupants if o["test_type"] == "HYDROSTATIC"]) >= 2:
            fail("ERR_TEST_BAY_CAPACITY_EXCEEDED",
                 "%s already holds two concurrent hydrostatic tests." % bay_code)

    pressure, hold_minutes, medium_temp = calc.test_parameters(
        test_type, job["mawp_psi"], job["stress_ratio"], job["mdmt_f"])
    record = db.insert("tests", {
        "job_id": job_id,
        "test_side": test_side,
        "test_type": test_type,
        "test_bay_code": bay_code,
        "scheduled_start": db.iso_instant(scheduled_start),
        "scheduled_end": db.iso_instant(scheduled_end),
        "test_pressure_psi": pressure,
        "min_hold_minutes": hold_minutes,
        "min_medium_temp_f": medium_temp,
        "test_medium_temp_f": None,
        "observed_hold_minutes": None,
        "observed_pressure_psi": None,
        "witnessed_by_personnel_id": None,
        "ai_witness_confirmed": False,
        "result": "PENDING",
    })
    changes = {"status": "TESTING"} if job["status"] == "FABRICATION" else {}
    derive.recompute_job(job, changes)
    derive.sync_job_reports(job)
    return common.created("tests", record)


@bp.get("/pressure-tests/<test_id>")
@guard(ALL_ROLES)
def get_test(ctx, test_id):
    return common.one("tests", common.must_exist("tests", test_id))


@bp.get("/pressure-tests")
@guard(ALL_ROLES)
def list_tests(ctx):
    return common.listing("tests", ["job_id", "witnessed_by_personnel_id",
                                    "test_bay_code", "test_side", "test_type",
                                    "result"])


@bp.post("/pressure-tests/<test_id>/witness")
@guard(["AuthorizedInspector"])
def witness_test(ctx, test_id):
    test = common.must_exist("tests", test_id)
    if test["result"] != "PENDING" or test["ai_witness_confirmed"]:
        fail("ERR_INVALID_TEST_STATE",
             "The witness may be recorded once on a PENDING test.")
    job = db.get("jobs", test["job_id"])
    certificate = db.get("certificates", job["certificate_id"])
    if derive.certificate_expired(certificate):
        fail("ERR_CERTIFICATE_EXPIRED",
             "The Certificate of Authorization has expired.")
    if not derive.certificate_authorized(certificate):
        fail("ERR_STAMPING_NOT_AUTHORIZED",
             "The certificate no longer confers stamping authority.")

    db.mutate(test, {"ai_witness_confirmed": True,
                     "witnessed_by_personnel_id": ctx.user_id})
    return common.one("tests", test)


@bp.post("/pressure-tests/<test_id>/result")
@guard(["QCInspector"])
def record_test_result(ctx, test_id):
    body = validation.body()
    result = validation.enum_field(body, "result", ("PASS", "FAIL"))
    observed_pressure = validation.decimal_field(body, "observed_pressure_psi",
                                                 scale=1, minimum=0)
    observed_hold = validation.int_field(body, "observed_hold_minutes", minimum=0)
    medium_temp = validation.decimal_field(body, "test_medium_temp_f")

    test = common.must_exist("tests", test_id)
    if test["result"] != "PENDING":
        fail("ERR_INVALID_TEST_STATE", "This test has already been settled.")
    job = db.get("jobs", test["job_id"])
    if job["status"] != "TESTING":
        fail("ERR_INVALID_JOB_STATE", "Recording a result needs the job in TESTING.")
    if not test["ai_witness_confirmed"]:
        fail("ERR_AI_WITNESS_REQUIRED",
             "The Authorized Inspector has not witnessed this test.")

    if result == "PASS":
        if observed_pressure < test["test_pressure_psi"]:
            fail("ERR_TEST_PRESSURE_INSUFFICIENT",
                 "The test pressure never reached %s psi." % test["test_pressure_psi"])
        if observed_hold < test["min_hold_minutes"]:
            fail("ERR_HOLD_TIME_INSUFFICIENT",
                 "The hold fell short of %s minutes." % test["min_hold_minutes"])
        if medium_temp < test["min_medium_temp_f"]:
            fail("ERR_MEDIUM_TEMP_TOO_LOW",
                 "The medium was colder than %s degrees F."
                 % test["min_medium_temp_f"])
        if derive.nonconformance_open_count(job["id"]) > 0:
            fail("ERR_OPEN_NONCONFORMANCE",
                 "The job still carries an open nonconformance.")

    db.mutate(test, {"result": result, "observed_pressure_psi": observed_pressure,
                     "observed_hold_minutes": observed_hold,
                     "test_medium_temp_f": medium_temp})

    changes = {}
    if result == "PASS":
        if _every_side_passed(job):
            changes["status"] = "DATA_PACKAGE"
    else:
        raise_nonconformance(job, None, "PRESSURE_TEST_FAIL")
        changes["status"] = "NDE_HOLD"
    derive.recompute_job(job, changes)
    derive.sync_job_reports(job)
    return common.one("tests", test)


def _every_side_passed(job):
    tests = derive.job_tests(job["id"])
    for side in job["required_test_sides"]:
        latest = None
        for candidate in tests:
            if candidate["test_side"] == side:
                latest = candidate
        if latest is None or latest["result"] != "PASS":
            return False
    return True
