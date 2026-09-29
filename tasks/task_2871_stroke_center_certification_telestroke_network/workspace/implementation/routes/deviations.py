"""Protocol deviations: manual creation and the bounded review loop (PRD 3.8)."""
from flask import Blueprint

import db
import response as resp
from constants import (
    DEVIATION_OUTCOMES,
    DEVIATION_SEVERITIES,
    DEVIATION_TYPES,
    MAX_REVIEW_ROUNDS,
)
from errors import fail
from middleware import (
    Field,
    apply_filters,
    authenticate,
    load_path,
    load_ref,
    pagination,
    read_body,
)
from services import derive
from services import reporting

bp = Blueprint("deviations", __name__)

CREATE_SPEC = [
    Field("case_id", "str"),
    Field("deviation_type", "str", enum=DEVIATION_TYPES),
    Field("severity", "str", enum=DEVIATION_SEVERITIES),
    Field("narrative", "str", min_len=1, max_len=500),
]

RETURN_SPEC = [Field("info_request", "str", min_len=1)]
RESUBMIT_SPEC = [Field("additional_info", "str", min_len=1)]
DEBRIEF_SPEC = [Field("debrief_summary", "str", min_len=1)]
DECIDE_SPEC = [Field("outcome", "str", enum=DEVIATION_OUTCOMES)]


@bp.route("/deviations", methods=["POST"])
def create_deviation():
    user_id, _role = authenticate(("QualityAbstractor", "EdPhysician"))
    body = read_body(CREATE_SPEC)
    case = load_ref("cases", body["case_id"])
    record = {
        "case_id": case["id"],
        "deviation_type": body["deviation_type"],
        "severity": body["severity"],
        "narrative": body["narrative"],
        "source": "MANUAL",
        "status": "OPEN",
        "opened_by_user_id": user_id,
        "reviewed_by_user_id": None,
        "review_round": 0,
        "info_request": None,
        "additional_info": None,
        "debrief_completed": False,
        "debrief_summary": None,
    }
    db.insert("deviations", record)
    derive.recompute_case_deviation_count(case)
    return resp.object_response(record, 201)


@bp.route("/deviations/<record_id>", methods=["GET"])
def read_deviation(record_id):
    authenticate("any")
    return resp.object_response(load_path("deviations", record_id))


@bp.route("/deviations", methods=["GET"])
def list_deviations():
    authenticate("any")
    limit, offset = pagination()
    records = apply_filters(db.all_of("deviations"), {
        "case_id": "case_id",
        "status": "status",
        "severity": "severity",
        "deviation_type": "deviation_type",
        "source": "source",
    })
    return resp.list_response(records, limit, offset)


@bp.route("/deviations/<record_id>/start-review", methods=["POST"])
def start_review(record_id):
    user_id, _role = authenticate(("CertificationReviewer",))
    record = load_path("deviations", record_id)
    read_body([])
    if record["status"] != "OPEN":
        fail("ERR_INVALID_DEVIATION_STATE",
             "No review start is declared from %s." % record["status"])
    if record["review_round"] >= MAX_REVIEW_ROUNDS:
        fail("ERR_REVIEW_ROUND_LIMIT",
             "The deviation has already used %d review rounds." % MAX_REVIEW_ROUNDS)
    record["status"] = "UNDER_REVIEW"
    record["review_round"] = record["review_round"] + 1
    record["reviewed_by_user_id"] = user_id
    db.touch(record)
    return resp.object_response(record)


@bp.route("/deviations/<record_id>/return-for-info", methods=["POST"])
def return_for_info(record_id):
    user_id, _role = authenticate(("CertificationReviewer",))
    record = load_path("deviations", record_id)
    body = read_body(RETURN_SPEC)
    if record["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_DEVIATION_STATE",
             "No return for information is declared from %s." % record["status"])
    if record["review_round"] >= MAX_REVIEW_ROUNDS:
        fail("ERR_REVIEW_ROUND_LIMIT",
             "review_round has already reached %d." % MAX_REVIEW_ROUNDS)
    record["status"] = "RETURNED_FOR_INFO"
    record["info_request"] = body["info_request"]
    record["reviewed_by_user_id"] = user_id
    db.touch(record)
    return resp.object_response(record)


@bp.route("/deviations/<record_id>/resubmit", methods=["POST"])
def resubmit(record_id):
    authenticate(("QualityAbstractor",))
    record = load_path("deviations", record_id)
    body = read_body(RESUBMIT_SPEC)
    if record["status"] != "RETURNED_FOR_INFO":
        fail("ERR_INVALID_DEVIATION_STATE",
             "No resubmission is declared from %s." % record["status"])
    if record["review_round"] >= MAX_REVIEW_ROUNDS:
        fail("ERR_REVIEW_ROUND_LIMIT",
             "The deviation has already used %d review rounds." % MAX_REVIEW_ROUNDS)
    record["status"] = "UNDER_REVIEW"
    record["review_round"] = record["review_round"] + 1
    record["additional_info"] = body["additional_info"]
    db.touch(record)
    return resp.object_response(record)


@bp.route("/deviations/<record_id>/debrief", methods=["POST"])
def debrief(record_id):
    authenticate(("QualityAbstractor", "EdPhysician"))
    record = load_path("deviations", record_id)
    body = read_body(DEBRIEF_SPEC)
    # The debrief is the only write that ever touches these two fields.
    record["debrief_summary"] = body["debrief_summary"]
    record["debrief_completed"] = True
    db.touch(record)
    return resp.object_response(record)


@bp.route("/deviations/<record_id>/decide", methods=["POST"])
def decide(record_id):
    user_id, _role = authenticate(("CertificationReviewer",))
    record = load_path("deviations", record_id)
    body = read_body(DECIDE_SPEC)
    if record["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_DEVIATION_STATE",
             "No decision is declared from %s." % record["status"])
    outcome = body["outcome"]
    if (outcome == "SUBSTANTIATE" and record["severity"] == "SENTINEL"
            and not record["debrief_completed"]):
        fail("ERR_DEBRIEF_REQUIRED",
             "A SENTINEL deviation requires a completed debrief before it is "
             "substantiated.")
    record["status"] = "SUBSTANTIATED" if outcome == "SUBSTANTIATE" else "DISMISSED"
    record["reviewed_by_user_id"] = user_id
    db.touch(record)
    case = db.get("cases", record["case_id"])
    if case is not None:
        if outcome == "SUBSTANTIATE":
            for report in reporting.substantiation_targets(case):
                reporting.recompute_substantiated_counts(report)
        else:
            # A dismissed row leaves the deviation_count filter.
            derive.recompute_case_deviation_count(case)
    return resp.object_response(record)
