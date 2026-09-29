"""The certificate of eligibility lifecycle and quality control."""

from flask import Blueprint

import calc
import flows
from auth import caller_id, caller_recruiter, read_only, require
from errors import ApiError
from envelope import success, success_list
from store import bump, mark_fresh, store
from support import fetch, matches, paginate
from validation import (get_bool, get_date, get_enum, get_id, get_string,
                        get_string_list, iso_date, pagination_params,
                        parse_iso_date, query_bool, query_enum, query_string,
                        read_body)

bp = Blueprint("coes", __name__)

COE_STATUSES = ("DRAFT", "SUBMITTED", "QC_SELECTED", "QC_PASSED", "APPROVED",
                "RETURNED_FOR_CORRECTION", "INVALIDATED")
LIVE_COE_STATUSES = ("SUBMITTED", "QC_SELECTED", "QC_PASSED", "APPROVED")
REVIEW_STATUSES = ("OPEN", "PASSED", "FAILED")
SELECTION_REASONS = ("MANDATORY_RISK_FLAG", "SAMPLE_QUOTA")
QC_DECISIONS = ("PASS", "FAIL")
DISCREPANCY_CODES = ("MOVE_DATE", "WORK_TYPE", "RESIDENCY_DATE", "INFORMANT", "DISTANCE")


def _require_owner(coe):
    if coe["initiating_recruiter_id"] != caller_id():
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Only the recruiter who initiated this certificate may act on it",
        )


# =========================================================================
# certificates
# =========================================================================

@bp.route("/mep/coes", methods=["POST"])
@require("Recruiter")
def create_coe():
    body = read_body()
    student_id = get_id(body, "student_id", required=True)
    move_id = get_id(body, "move_id", required=True)
    residency_date = get_date(body, "residency_date", required=True)
    qc_hold_exempt = get_bool(body, "qc_hold_exempt", default=False)

    fetch("student", student_id)
    move = fetch("move", move_id)

    if move["student_id"] != student_id:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "The referenced qualifying move does not belong to this student",
        )
    if move["work_type"] == "NONE":
        raise ApiError(
            "ERR_MOVE_NOT_QUALIFYING",
            "A certificate cannot rest on a move whose work_type is NONE",
        )
    if residency_date < parse_iso_date(move["move_date"]):
        raise ApiError(
            "ERR_RESIDENCY_DATE_BEFORE_MOVE",
            "'residency_date' precedes the qualifying move date",
        )

    created = store.now_iso()
    row = {
        "id": store.new_id(),
        "student_id": student_id,
        "move_id": move_id,
        "initiating_recruiter_id": caller_id(),
        "residency_date": iso_date(residency_date),
        "qc_hold_exempt": qc_hold_exempt,
        "status": "DRAFT",
        "correction_round_count": 0,
        "risk_flag_count": 0,
        "provisional_eligibility_end_on": None,
        "eligibility_start_on": None,
        "eligibility_end_on": None,
        "age_out_capped": None,
        "invalidation_reason": None,
        "created_at": created,
        "updated_at": created,
        "version": 1,
    }
    store.coes[row["id"]] = row
    mark_fresh(row)
    return success(row, 201)


@bp.route("/mep/coes/<coe_id>", methods=["GET"])
@read_only
def read_coe(coe_id):
    return success(fetch("coe", coe_id))


@bp.route("/mep/coes", methods=["GET"])
@read_only
def list_coes():
    limit, offset = pagination_params()
    filters = {
        "student_id": query_string("student_id"),
        "move_id": query_string("move_id"),
        "initiating_recruiter_id": query_string("initiating_recruiter_id"),
        "status": query_enum("status", COE_STATUSES),
        "qc_hold_exempt": query_bool("qc_hold_exempt"),
    }
    rows = [row for row in store.coes.values() if matches(row, filters)]
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/mep/coes/<coe_id>", methods=["PATCH"])
@require("Recruiter")
def correct_coe(coe_id):
    coe = fetch("coe", coe_id)
    _require_owner(coe)
    body = read_body()
    residency_date = get_date(body, "residency_date")
    qc_hold_exempt = get_bool(body, "qc_hold_exempt")

    if coe["status"] not in ("DRAFT", "RETURNED_FOR_CORRECTION"):
        raise ApiError(
            "ERR_COE_NOT_IN_DRAFT",
            "Certificate is %s and cannot be corrected" % coe["status"],
        )

    if residency_date is not None:
        move = store.moves.get(coe["move_id"])
        if move is not None and residency_date < parse_iso_date(move["move_date"]):
            raise ApiError(
                "ERR_RESIDENCY_DATE_BEFORE_MOVE",
                "'residency_date' precedes the qualifying move date",
            )
        coe["residency_date"] = iso_date(residency_date)
    if qc_hold_exempt is not None:
        coe["qc_hold_exempt"] = qc_hold_exempt

    coe["status"] = "DRAFT"
    bump(coe)
    return success(coe)


@bp.route("/mep/coes/<coe_id>/submit", methods=["POST"])
@require("Recruiter")
def submit_coe(coe_id):
    coe = fetch("coe", coe_id)
    _require_owner(coe)

    if coe["status"] != "DRAFT":
        raise ApiError(
            "ERR_COE_NOT_IN_DRAFT",
            "Certificate is %s, not DRAFT" % coe["status"],
        )

    move = store.moves.get(coe["move_id"])
    student = store.students.get(coe["student_id"])

    # rung 11
    if move is None or move["status"] != "VERIFIED":
        raise ApiError(
            "ERR_MOVE_NOT_VERIFIED",
            "The linked qualifying move is not in VERIFIED status",
        )
    # rung 10 is guaranteed by verification, but stated for completeness
    if move["work_type"] == "NONE":
        raise ApiError("ERR_MOVE_NOT_QUALIFYING", "The linked move is not a qualifying move")

    # rung 12
    supported = any(
        row["student_id"] == coe["student_id"]
        and row["move_id"] == coe["move_id"]
        and row["interview_kind"] == "INITIAL"
        and row["outcome"] == "SUPPORTS_ELIGIBILITY"
        for row in store.interviews.values()
    )
    if not supported:
        raise ApiError(
            "ERR_INTERVIEW_DOCUMENTATION_MISSING",
            "No supporting INITIAL interview is on file for this student and move",
        )

    # rung 14
    for sibling in store.coes.values():
        if sibling["id"] == coe["id"]:
            continue
        if (sibling["student_id"] == coe["student_id"]
                and sibling["move_id"] == coe["move_id"]
                and sibling["status"] in LIVE_COE_STATUSES):
            raise ApiError(
                "ERR_DUPLICATE_ACTIVE_COE",
                "Another live certificate already exists for this student and move",
            )

    coe["status"] = "SUBMITTED"
    coe["provisional_eligibility_end_on"] = iso_date(
        calc.provisional_window_end(move["move_date"]))
    coe["risk_flag_count"] = calc.risk_flag_count(coe, move, student)
    bump(coe)

    if student is not None and student["eligibility_status"] in ("NOT_ELIGIBLE", "TERM_EXPIRED"):
        student["eligibility_status"] = "PENDING_DETERMINATION"
        bump(student)
    return success(coe)


@bp.route("/mep/coes/<coe_id>/approve", methods=["POST"])
@require("StateProgramAdmin")
def approve_coe(coe_id):
    coe = fetch("coe", coe_id)

    if coe["status"] == "SUBMITTED":
        open_review = any(
            review["coe_id"] == coe["id"] and review["status"] == "OPEN"
            for review in store.qc_reviews.values()
        )
        if open_review:
            raise ApiError(
                "ERR_COE_INVALID_STATE",
                "A quality-control review for this certificate is still OPEN",
            )
    elif coe["status"] != "QC_PASSED":
        raise ApiError(
            "ERR_COE_INVALID_STATE",
            "Certificate is %s and cannot be approved" % coe["status"],
        )

    student = store.students.get(coe["student_id"])
    if student is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND", "Student not found")
    flows.approval_cascade(coe, student)
    return success(coe)


@bp.route("/mep/coes/<coe_id>/invalidate", methods=["POST"])
@require("StateProgramAdmin")
def invalidate_coe(coe_id):
    coe = fetch("coe", coe_id)
    body = read_body()
    reason = get_string(body, "invalidation_reason", required=True, min_len=1, max_len=240)

    if coe["status"] != "APPROVED":
        raise ApiError(
            "ERR_COE_INVALID_STATE",
            "Only an APPROVED certificate may be invalidated; this one is %s" % coe["status"],
        )

    student = store.students.get(coe["student_id"])
    flows.invalidation_cascade(coe, student, reason)
    return success(coe)


# =========================================================================
# quality control
# =========================================================================

@bp.route("/mep/qc-selections", methods=["POST"])
@require("StateProgramAdmin")
def run_qc_selection():
    candidates = calc.qc_candidates()
    if not candidates:
        raise ApiError(
            "ERR_NO_QC_CANDIDATES",
            "No SUBMITTED, non-exempt certificates are available for sampling",
        )

    target_n, selected = calc.qc_sample(candidates)
    selected_coe_ids = []
    review_ids = []
    for coe in selected:
        coe["status"] = "QC_SELECTED"
        bump(coe)
        created = store.now_iso()
        review = {
            "id": store.new_id(),
            "coe_id": coe["id"],
            "status": "OPEN",
            "selection_reason": ("MANDATORY_RISK_FLAG"
                                 if (coe.get("risk_flag_count") or 0) >= 1
                                 else "SAMPLE_QUOTA"),
            "reviewer_recruiter_id": None,
            "reinterview_id": None,
            "discrepancy_codes": [],
            "decided_on": None,
            "created_at": created,
            "updated_at": created,
            "version": 1,
        }
        store.qc_reviews[review["id"]] = review
        mark_fresh(review)
        selected_coe_ids.append(coe["id"])
        review_ids.append(review["id"])

    return success({
        "candidate_count": len(candidates),
        "target_n": target_n,
        "selected_count": len(selected),
        "selected_coe_ids": selected_coe_ids,
        "review_ids": review_ids,
    }, 201)


@bp.route("/mep/qc-reviews/<review_id>", methods=["GET"])
@read_only
def read_review(review_id):
    return success(fetch("review", review_id))


@bp.route("/mep/qc-reviews", methods=["GET"])
@read_only
def list_reviews():
    limit, offset = pagination_params()
    filters = {
        "coe_id": query_string("coe_id"),
        "reviewer_recruiter_id": query_string("reviewer_recruiter_id"),
        "reinterview_id": query_string("reinterview_id"),
        "status": query_enum("status", REVIEW_STATUSES),
        "selection_reason": query_enum("selection_reason", SELECTION_REASONS),
    }
    rows = [row for row in store.qc_reviews.values() if matches(row, filters)]
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/mep/qc-reviews/<review_id>/decide", methods=["POST"])
@require("QualityControlReviewer")
def decide_review(review_id):
    review = fetch("review", review_id)
    body = read_body()
    decision = get_enum(body, "decision", QC_DECISIONS, required=True)
    reinterview_id = get_id(body, "reinterview_id", required=True)
    codes = get_string_list(body, "discrepancy_codes", DISCREPANCY_CODES, default=None)

    if decision == "PASS" and codes:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "'discrepancy_codes' must be absent or empty on a PASS decision",
        )
    if decision == "FAIL" and not codes:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "'discrepancy_codes' must contain at least one element on a FAIL decision",
        )

    reinterview = fetch("interview", reinterview_id)

    if review["status"] != "OPEN":
        raise ApiError(
            "ERR_QC_REVIEW_ALREADY_DECIDED",
            "Review has already been decided as %s" % review["status"],
        )
    coe = store.coes.get(review["coe_id"])
    if coe is None or coe["status"] != "QC_SELECTED":
        raise ApiError(
            "ERR_COE_INVALID_STATE",
            "The certificate under review is no longer QC_SELECTED",
        )

    if caller_id() == coe["initiating_recruiter_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "A reviewer may not decide a certificate they initiated",
        )

    recruiter = caller_recruiter()
    if recruiter is None or recruiter["credential_level"] != "QC_CERTIFIED":
        raise ApiError(
            "ERR_QC_CREDENTIAL_REQUIRED",
            "Quality-control decisions require the QC_CERTIFIED credential",
        )

    if (reinterview["interview_kind"] != "QC_REINTERVIEW"
            or reinterview["student_id"] != coe["student_id"]
            or reinterview.get("coe_id") != coe["id"]):
        raise ApiError(
            "ERR_REINTERVIEW_STUDENT_MISMATCH",
            "The referenced re-interview does not belong to this certificate",
        )

    review["reviewer_recruiter_id"] = caller_id()
    review["reinterview_id"] = reinterview_id
    review["decided_on"] = store.clock_instant()

    if decision == "PASS":
        review["status"] = "PASSED"
        review["discrepancy_codes"] = []
        bump(review)
        coe["status"] = "QC_PASSED"
        bump(coe)
    else:
        review["status"] = "FAILED"
        review["discrepancy_codes"] = list(codes)
        bump(review)
        coe["status"] = "RETURNED_FOR_CORRECTION"
        coe["correction_round_count"] = (coe.get("correction_round_count") or 0) + 1
        coe["provisional_eligibility_end_on"] = None
        bump(coe)

        student = store.students.get(coe["student_id"])
        if student is not None and student["eligibility_status"] == "PENDING_DETERMINATION":
            live_term = any(
                term["student_id"] == student["id"] and term["status"] in ("ACTIVE", "EXPIRING")
                for term in store.terms.values()
            )
            if not live_term:
                student["eligibility_status"] = "NOT_ELIGIBLE"
                bump(student)

    return success(review)
