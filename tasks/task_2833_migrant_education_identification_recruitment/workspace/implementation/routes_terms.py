"""Continuation-of-eligibility terms, reidentification and the national exchange."""

from decimal import Decimal

from flask import Blueprint

import calc
import flows
from auth import caller_id, read_only, require
from errors import ApiError
from envelope import success, success_list
from store import bump, mark_fresh, store
from support import fetch, matches, paginate
from validation import (get_date, get_decimal, get_id, get_state_code,
                        get_string, iso_date, pagination_params, parse_iso_date,
                        query_enum, query_string, read_body, round_half_up)

bp = Blueprint("terms", __name__)

ZERO = Decimal("0.00")

TERM_STATUSES = ("ACTIVE", "EXPIRING", "EXPIRED", "REIDENTIFIED", "LAPSED", "TERMINATED")
TRANSFER_STATUSES = ("INITIATED", "MATCHED", "NO_MATCH", "RECEIVED", "RECONCILED", "REJECTED")


# =========================================================================
# eligibility terms
# =========================================================================

@bp.route("/mep/eligibility-terms/<term_id>", methods=["GET"])
@read_only
def read_term(term_id):
    return success(fetch("term", term_id))


@bp.route("/mep/eligibility-terms", methods=["GET"])
@read_only
def list_terms():
    limit, offset = pagination_params()
    filters = {
        "student_id": query_string("student_id"),
        "coe_id": query_string("coe_id"),
        "superseded_by_term_id": query_string("superseded_by_term_id"),
        "status": query_enum("status", TERM_STATUSES),
    }
    rows = [row for row in store.terms.values() if matches(row, filters)]
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/mep/eligibility-terms/sweep", methods=["POST"])
@require("StateProgramAdmin")
def sweep_terms():
    return success(flows.run_sweep())


@bp.route("/mep/eligibility-terms/<term_id>/reidentify", methods=["POST"])
@require("Recruiter")
def reidentify(term_id):
    term = fetch("term", term_id)
    body = read_body()
    new_move_id = get_id(body, "new_move_id", required=True)
    residency_date = get_date(body, "residency_date", required=True)

    move = fetch("move", new_move_id)

    if term["status"] != "EXPIRED":
        raise ApiError(
            "ERR_TERM_INVALID_STATE",
            "Term is %s; only an EXPIRED term may be reidentified" % term["status"],
        )

    if move["student_id"] != term["student_id"] or move["status"] != "VERIFIED":
        raise ApiError(
            "ERR_MOVE_NOT_VERIFIED",
            "The named move must belong to this child and be in VERIFIED status",
        )

    if residency_date < parse_iso_date(move["move_date"]):
        raise ApiError(
            "ERR_RESIDENCY_DATE_BEFORE_MOVE",
            "'residency_date' precedes the qualifying move date",
        )

    due = term.get("reidentification_due_on")
    if due is None or store.clock_date() > parse_iso_date(due):
        raise ApiError(
            "ERR_REIDENTIFICATION_WINDOW_CLOSED",
            "The reidentification grace period for this term has closed",
        )

    term["status"] = "REIDENTIFIED"
    bump(term)

    created = store.now_iso()
    coe = {
        "id": store.new_id(),
        "student_id": term["student_id"],
        "move_id": new_move_id,
        "initiating_recruiter_id": caller_id(),
        "residency_date": iso_date(residency_date),
        "qc_hold_exempt": False,
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
    store.coes[coe["id"]] = coe
    mark_fresh(coe)

    student = store.students.get(term["student_id"])
    if student is not None:
        student["eligibility_status"] = "PENDING_DETERMINATION"
        bump(student)

    return success(term)


# =========================================================================
# national record exchange
# =========================================================================

@bp.route("/mep/transfer-requests", methods=["POST"])
@require("ExchangeLiaison")
def create_transfer():
    body = read_body()
    student_id = get_id(body, "student_id", required=True)
    requesting = get_state_code(body, "requesting_state_code", required=True)
    holding = get_state_code(body, "holding_state_code", required=True)
    reference = get_string(body, "exchange_reference", required=True, min_len=1, max_len=64)
    reported = get_decimal(body, "reported_prior_credits", minimum=ZERO,
                           maximum=Decimal("40.00"), default=ZERO)
    if holding == requesting:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "'holding_state_code' must differ from 'requesting_state_code'",
        )

    fetch("student", student_id)

    created = store.now_iso()
    row = {
        "id": store.new_id(),
        "student_id": student_id,
        "requesting_state_code": requesting,
        "holding_state_code": holding,
        "exchange_reference": reference,
        "reported_prior_credits": round_half_up(reported),
        "status": "INITIATED",
        "matched_prior_student_id": None,
        "applied_transferred_credits": ZERO,
        "rejection_reason": None,
        "created_at": created,
        "updated_at": created,
        "version": 1,
    }
    store.transfers[row["id"]] = row
    mark_fresh(row)
    return success(row, 201)


@bp.route("/mep/transfer-requests/<request_id>", methods=["GET"])
@read_only
def read_transfer(request_id):
    return success(fetch("transfer", request_id))


@bp.route("/mep/transfer-requests", methods=["GET"])
@read_only
def list_transfers():
    limit, offset = pagination_params()
    filters = {
        "student_id": query_string("student_id"),
        "matched_prior_student_id": query_string("matched_prior_student_id"),
        "status": query_enum("status", TRANSFER_STATUSES),
        "exchange_reference": query_string("exchange_reference"),
    }
    rows = [row for row in store.transfers.values() if matches(row, filters)]
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/mep/transfer-requests/<request_id>/match", methods=["POST"])
@require("ExchangeLiaison")
def match_transfer(request_id):
    request_row = fetch("transfer", request_id)
    body = read_body()
    matched_id = get_id(body, "matched_prior_student_id")

    if matched_id is not None:
        fetch("student", matched_id)

    if request_row["status"] != "INITIATED":
        raise ApiError(
            "ERR_TRANSFER_INVALID_STATE",
            "Transfer request is %s, not INITIATED" % request_row["status"],
        )

    if matched_id is not None and matched_id == request_row["student_id"]:
        raise ApiError(
            "ERR_TRANSFER_SELF_MATCH",
            "A record cannot be its own predecessor",
        )

    if matched_id is None:
        request_row["status"] = "NO_MATCH"
        bump(request_row)
        return success(request_row)

    request_row["status"] = "MATCHED"
    request_row["matched_prior_student_id"] = matched_id
    bump(request_row)

    student = store.students.get(request_row["student_id"])
    if student is not None:
        student["prior_record_student_id"] = matched_id
        bump(student)
    return success(request_row)


@bp.route("/mep/transfer-requests/<request_id>/receive", methods=["POST"])
@require("ExchangeLiaison")
def receive_transfer(request_id):
    request_row = fetch("transfer", request_id)
    if request_row["status"] != "MATCHED":
        raise ApiError(
            "ERR_TRANSFER_INVALID_STATE",
            "Transfer request is %s, not MATCHED" % request_row["status"],
        )
    request_row["status"] = "RECEIVED"
    bump(request_row)
    return success(request_row)


@bp.route("/mep/transfer-requests/<request_id>/reconcile", methods=["POST"])
@require("ExchangeLiaison")
def reconcile_transfer(request_id):
    request_row = fetch("transfer", request_id)
    if request_row["status"] != "RECEIVED":
        raise ApiError(
            "ERR_TRANSFER_INVALID_STATE",
            "Transfer request is %s, not RECEIVED" % request_row["status"],
        )

    student = store.students.get(request_row["student_id"])
    result = calc.reconcile_credits(
        request_row["student_id"], request_row["reported_prior_credits"])

    request_row["status"] = "RECONCILED"
    request_row["applied_transferred_credits"] = result["accepted_transfer"]
    bump(request_row)

    if student is not None:
        student["locally_accrued_credits"] = result["locally_accrued_credits"]
        student["transferred_credits_count"] = result["accepted_transfer"]
        student["total_awarded_credits"] = result["awarded_total"]
        bump(student)
    return success(request_row)


@bp.route("/mep/transfer-requests/<request_id>/reject", methods=["POST"])
@require("ExchangeLiaison")
def reject_transfer(request_id):
    request_row = fetch("transfer", request_id)
    body = read_body()
    reason = get_string(body, "rejection_reason", required=True, min_len=1, max_len=240)

    if request_row["status"] not in ("RECEIVED", "RECONCILED"):
        raise ApiError(
            "ERR_TRANSFER_INVALID_STATE",
            "Transfer request is %s and cannot be rejected" % request_row["status"],
        )

    applied = request_row.get("applied_transferred_credits") or ZERO
    request_row["status"] = "REJECTED"
    request_row["applied_transferred_credits"] = ZERO
    request_row["rejection_reason"] = reason
    bump(request_row)

    student = store.students.get(request_row["student_id"])
    if student is not None:
        remaining = round_half_up((student.get("transferred_credits_count") or ZERO) - applied)
        student["transferred_credits_count"] = remaining
        student["total_awarded_credits"] = round_half_up(
            (student.get("locally_accrued_credits") or ZERO) + remaining)
        student["prior_record_student_id"] = None
        bump(student)
    return success(request_row)
