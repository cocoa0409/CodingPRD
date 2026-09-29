"""The quality system: proficiency testing and nonconformances."""
from flask import Blueprint, g

import serialize
import services as S
from auth import ANALYST, CASE_MANAGER, QUALITY_MANAGER, endpoint
from envelope import object_response
from errors import ApiError
from store import db, new_row, touch
from util import add_days, dec, q2
from validate import Field, parse

bp = Blueprint("quality", __name__)


# ------------------------------------------------------- proficiency tests
@bp.route("/lab/proficiency-tests", methods=["POST"])
@endpoint(QUALITY_MANAGER)
def create_proficiency_test():
    body = parse([
        Field("analyst_id", "string", required=True, min_length=1),
        Field("method_id", "string", required=True, min_length=1),
        Field("test_cycle", "string", required=True, min_length=1, max_length=20),
        Field("due_utc", "instant", required=True),
    ])
    analyst = S.find_analyst(body["analyst_id"])
    method = S.find_method(body["method_id"])
    for existing in db.proficiency_tests.values():
        if (existing["analyst_id"] == analyst["id"]
                and existing["method_id"] == method["id"]
                and existing["test_cycle"] == body["test_cycle"]):
            raise ApiError("ERR_DUPLICATE_RESOURCE")
    row = new_row()
    row.update({
        "analyst_id": analyst["id"],
        "method_id": method["id"],
        "test_cycle": body["test_cycle"],
        "due_utc": body["due_utc"],
        "status": "ASSIGNED",
        "submitted_at_utc": None,
        "score_pct": None,
        "result": None,
        "late_submission": False,
        "scored_at_utc": None,
    })
    db.proficiency_tests[row["id"]] = row
    return object_response(serialize.proficiency_test(row), 201)


@bp.route("/lab/proficiency-tests/<proficiency_test_id>/submit",
          methods=["POST"])
@endpoint(ANALYST)
def submit_proficiency_test(proficiency_test_id):
    test = S.find_proficiency_test(proficiency_test_id)
    parse([])
    if test["analyst_id"] != g.user_id:
        raise ApiError("ERR_ANALYST_IDENTITY_MISMATCH")
    if test["status"] != "ASSIGNED":
        raise ApiError("ERR_PT_INVALID_STATE")
    submitted = db.now()
    test["status"] = "SUBMITTED"
    test["submitted_at_utc"] = submitted
    test["late_submission"] = submitted > test["due_utc"]
    touch(test)
    return object_response(serialize.proficiency_test(test), 200)


def _grade(test, score):
    if test["late_submission"]:
        return "FAIL"
    if score >= S.PT_PASS_THRESHOLD:
        return "PASS"
    if score >= S.PT_INCONCLUSIVE_THRESHOLD:
        return "INCONCLUSIVE"
    return "FAIL"


def _apply_pt_result(analyst, result):
    """The two-stage standing cascade of PRD section 3.8."""
    if result == "FAIL":
        analyst["consecutive_pt_failures"] = analyst["consecutive_pt_failures"] + 1
        touch(analyst)
    elif result == "PASS":
        if analyst["consecutive_pt_failures"] != 0:
            analyst["consecutive_pt_failures"] = 0
            touch(analyst)
    state = analyst["qualification_state"]
    if result == "FAIL":
        if state == "QUALIFIED":
            S.enter_probation(analyst)
        elif state == "PROBATION":
            if analyst["consecutive_pt_failures"] >= S.PT_SUSPENSION_THRESHOLD:
                analyst["qualification_state"] = "SUSPENDED"
                analyst["suspended_at_utc"] = db.now()
                touch(analyst)
                S.full_release(analyst)
        elif state == "SUSPENDED":
            analyst["qualification_state"] = "DECERTIFIED"
            touch(analyst)
            S.full_release(analyst)
    elif result == "PASS" and state == "PROBATION":
        S.restore_to_qualified(analyst)


@bp.route("/lab/proficiency-tests/<proficiency_test_id>/score",
          methods=["POST"])
@endpoint(QUALITY_MANAGER)
def score_proficiency_test(proficiency_test_id):
    test = S.find_proficiency_test(proficiency_test_id)
    body = parse([
        Field("score_pct", "number", required=True,
              minimum="0.00", maximum="100.00"),
    ])
    if test["status"] != "SUBMITTED":
        raise ApiError("ERR_PT_INVALID_STATE")
    score = q2(body["score_pct"])
    result = _grade(test, score)
    test["status"] = "SCORED"
    test["score_pct"] = score
    test["result"] = result
    test["scored_at_utc"] = db.now()
    touch(test)
    analyst = db.analysts.get(test["analyst_id"])
    if analyst is not None:
        _apply_pt_result(analyst, result)
        if result == "INCONCLUSIVE":
            S.open_nonconformance(
                "PT_INCONCLUSIVE", "MINOR",
                "Inconclusive proficiency test %s." % test["id"],
                analyst_id=analyst["id"],
            )
        elif result == "FAIL":
            S.open_nonconformance(
                "PT_FAILURE", "MAJOR",
                "Failed proficiency test %s." % test["id"],
                analyst_id=analyst["id"],
            )
    return object_response(serialize.proficiency_test(test), 200)


# ---------------------------------------------------------- nonconformances
@bp.route("/lab/nonconformances", methods=["POST"])
@endpoint(QUALITY_MANAGER)
def create_nonconformance():
    body = parse([
        Field("source", "enum", required=True, choices=S.NC_SOURCES),
        Field("severity", "enum", required=True, choices=S.NC_SEVERITIES),
        Field("description", "string", required=True, min_length=1, max_length=500),
        Field("examination_request_id", "string", default=None,
              nullable=True, min_length=1),
        Field("analyst_id", "string", default=None, nullable=True, min_length=1),
    ])
    request_id = None
    if body["examination_request_id"] is not None:
        request_id = S.find_examination_request(body["examination_request_id"])["id"]
    analyst = None
    if body["analyst_id"] is not None:
        analyst = S.find_analyst(body["analyst_id"])
    row = S.open_nonconformance(
        body["source"], body["severity"], body["description"],
        examination_request_id=request_id,
        analyst_id=analyst["id"] if analyst is not None else None,
    )
    if analyst is not None and body["severity"] in ("MAJOR", "CRITICAL"):
        S.enter_probation(analyst)
    return object_response(serialize.nonconformance(row), 201)


@bp.route("/lab/nonconformances/<nonconformance_id>/root-cause",
          methods=["POST"])
@endpoint(CASE_MANAGER)
def submit_root_cause(nonconformance_id):
    finding = S.find_nonconformance(nonconformance_id)
    body = parse([
        Field("root_cause_category", "enum", required=True,
              choices=S.ROOT_CAUSE_CATEGORIES),
        Field("corrective_action_plan", "string", required=True,
              min_length=1, max_length=500),
    ])
    if finding["status"] != "OPEN":
        raise ApiError("ERR_NONCONFORMANCE_INVALID_STATE")
    finding["root_cause_category"] = body["root_cause_category"]
    finding["corrective_action_plan"] = body["corrective_action_plan"]
    finding["status"] = "ROOT_CAUSE_SUBMITTED"
    touch(finding)
    return object_response(serialize.nonconformance(finding), 200)


@bp.route("/lab/nonconformances/<nonconformance_id>/capa-decision",
          methods=["POST"])
@endpoint(QUALITY_MANAGER)
def capa_decision(nonconformance_id):
    finding = S.find_nonconformance(nonconformance_id)
    body = parse([
        Field("decision", "enum", required=True, choices=("APPROVE", "REJECT")),
        Field("rationale", "string", required=True, min_length=1, max_length=500),
    ])
    if finding["status"] != "ROOT_CAUSE_SUBMITTED":
        raise ApiError("ERR_NONCONFORMANCE_INVALID_STATE")
    if body["decision"] == "APPROVE":
        finding["status"] = "CAPA_APPROVED"
    else:
        finding["status"] = "OPEN"
        finding["capa_rejection_count"] = finding["capa_rejection_count"] + 1
        finding["root_cause_category"] = None
        finding["corrective_action_plan"] = None
        if finding["capa_rejection_count"] == S.CAPA_ESCALATION_THRESHOLD:
            finding["severity"] = S.SEVERITY_ESCALATION[finding["severity"]]
            finding["due_utc"] = add_days(
                finding["opened_at_utc"], S.CAPA_SLA_DAYS[finding["severity"]]
            )
    touch(finding)
    return object_response(serialize.nonconformance(finding), 200)


@bp.route("/lab/nonconformances/<nonconformance_id>/verify-close",
          methods=["POST"])
@endpoint(QUALITY_MANAGER)
def verify_close(nonconformance_id):
    finding = S.find_nonconformance(nonconformance_id)
    parse([Field("closure_note", "string")])
    if finding["status"] != "CAPA_APPROVED":
        raise ApiError("ERR_NONCONFORMANCE_INVALID_STATE")
    finding["status"] = "CLOSED"
    finding["closed_at_utc"] = db.now()
    finding["overdue"] = False
    touch(finding)
    if finding["analyst_id"] is not None:
        analyst = db.analysts.get(finding["analyst_id"])
        S.restore_to_qualified(analyst)
    return object_response(serialize.nonconformance(finding), 200)
