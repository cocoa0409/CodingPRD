"""PRD 3.7 — field testing: immutable results, deterministic grading, link drive."""

from flask import Blueprint, g, request

import calc
import lookup
import rollups
import serial
from auth import ALL_ROLES, TEST_TECHNICIAN, require
from envelope import created, enum_filter, ok, paginate
from errors import ApiError
from store import base_record, db, now, touch
from validation import Field, body

tests_bp = Blueprint("tests", __name__)

TEST_STANDARDS = ("PERMANENT_LINK", "CHANNEL")
OUTCOMES = ("PASS", "PASS_ASTERISK", "FAIL")
TESTABLE_INSTALL_STATES = ("TERMINATED", "TESTED_PASS", "TESTED_FAIL")


@tests_bp.route("/cabling/test-results", methods=["POST"])
@require(TEST_TECHNICIAN)
def record_test_result():
    values = body([
        Field("link_id", "string"),
        Field("test_standard", "enum", enum=TEST_STANDARDS),
        Field("tester_model", "string"),
        Field("insertion_loss_db", "number", minimum=0),
        Field("next_margin_db", "number"),
        Field("return_loss_margin_db", "number"),
        Field("length_measured_m", "number"),
    ])
    link = lookup.link(values["link_id"])
    if link["install_state"] not in TESTABLE_INSTALL_STATES:
        raise ApiError("ERR_INVALID_LINK_STATE",
                       "A result may only be filed against a terminated or tested link.")
    cable_type = db.cable_types.get(link["cable_type_id"])
    permanent_limit, channel_limit = calc.length_limits(cable_type)
    if values["test_standard"] == "CHANNEL":
        graded_length = link["channel_length_m"]
        graded_limit = channel_limit
    else:
        graded_length = link["permanent_link_length_m"]
        graded_limit = permanent_limit
    budget = calc.insertion_loss_budget_db(graded_length)
    worst = calc.worst_margin_db(values["next_margin_db"],
                                values["return_loss_margin_db"])
    outcome, failure_reason = calc.grade_test(graded_length, graded_limit,
                                              values["insertion_loss_db"], budget, worst)

    result = base_record(versioned=False)
    result.update({
        "link_id": link["id"],
        "test_standard": values["test_standard"],
        "tester_model": values["tester_model"],
        "insertion_loss_db": values["insertion_loss_db"],
        "insertion_loss_budget_db": budget,
        "next_margin_db": values["next_margin_db"],
        "return_loss_margin_db": values["return_loss_margin_db"],
        "worst_margin_db": worst,
        "length_measured_m": values["length_measured_m"],
        "outcome": outcome,
        "failure_reason": failure_reason,
        "tester_user_id": g.user_id,
        "recorded_at": now(),
        "_graded_length_m": graded_length,
    })
    db.test_results[result["id"]] = result

    link["install_state"] = "TESTED_FAIL" if outcome == "FAIL" else "TESTED_PASS"
    link["test_attempt_count"] = link["test_attempt_count"] + 1
    link["latest_test_outcome"] = outcome
    touch(link)
    project = db.projects.get(link["project_id"])
    if project is not None:
        rollups.refresh_project(project)
    return created(serial.public(result))


@tests_bp.route("/cabling/test-results/<test_result_id>", methods=["GET"])
@require(*ALL_ROLES)
def read_test_result(test_result_id):
    return ok(serial.public(lookup.test_result(test_result_id)))


@tests_bp.route("/cabling/test-results", methods=["GET"])
@require(*ALL_ROLES)
def list_test_results():
    link_id = request.args.get("link_id")
    outcome = enum_filter(request.args, "outcome", OUTCOMES)
    test_standard = enum_filter(request.args, "test_standard", TEST_STANDARDS)
    rows = []
    for result in db.test_results.values():
        if link_id is not None and result["link_id"] != link_id:
            continue
        if outcome is not None and result["outcome"] != outcome:
            continue
        if test_standard is not None and result["test_standard"] != test_standard:
            continue
        rows.append(result)
    return paginate(rows, request.args, serial.public)
