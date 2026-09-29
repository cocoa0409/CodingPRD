"""Return-line physical and financial transitions, plus refund release reads."""

from flask import Blueprint

import aggregates
import calc
import constants as K
import db
import middleware as mw
import query
import refs
import response
import serialize
import services
import shapes
from errors import ApiError

bp = Blueprint("lines", __name__)


def _context(line):
    item = refs.item_of_return_line(line)
    client = refs.client_of_return_line(line)
    if item is None or client is None:
        raise ApiError("ERR_RETURN_LINE_NOT_FOUND")
    return item, client


@bp.post("/return-lines/<return_line_id>/quarantine")
def quarantine(return_line_id):
    mw.require("ReceivingClerk", "GradingInspector", "CenterAdmin")
    body = response.body_json()
    bay_id = shapes.req_id(body, "bay_id")
    start_at = shapes.req_instant(body, "quarantine_start_at")
    end_at = shapes.req_instant(body, "quarantine_end_at")
    shapes.window(start_at, end_at, "quarantine_start_at", "quarantine_end_at")
    bay = services.must_bay(bay_id)
    line = services.must_return_line(return_line_id)
    item, _client = _context(line)
    if line["disposition_state"] != "RECEIVED_UNGRADED":
        raise ApiError("ERR_LINE_INVALID_DISPOSITION_STATE")
    if item["hazard_class"] == "NONE" and item["recall_status"] == "NONE":
        raise ApiError("ERR_QUARANTINE_NOT_APPLICABLE")
    if bay["status"] != "ACTIVE" or bay["bay_type"] not in ("HAZMAT", "QUARANTINE"):
        raise ApiError("ERR_BAY_TYPE_MISMATCH")
    services.check_quarantine_window(bay, line, start_at, end_at)
    line["bay_id"] = bay["id"]
    line["quarantine_start_at"] = db.fmt_instant(start_at)
    line["quarantine_end_at"] = db.fmt_instant(end_at)
    line["disposition_state"] = "QUARANTINED"
    db.touch(line)
    return response.ok(serialize.return_line(line))


@bp.post("/return-lines/<return_line_id>/grade")
def grade(return_line_id):
    user_id, _role = mw.require("GradingInspector", "CenterAdmin")
    body = response.body_json()
    condition_grade = shapes.req_enum(body, "condition_grade", K.GRADES)
    line = services.must_return_line(return_line_id)
    item, client = _context(line)
    services.require_active(client)
    if line["disposition_state"] not in ("RECEIVED_UNGRADED", "QUARANTINED"):
        raise ApiError("ERR_LINE_INVALID_DISPOSITION_STATE")
    if line["disposition_state"] == "RECEIVED_UNGRADED" and (
        item["hazard_class"] != "NONE" or item["recall_status"] == "MANDATORY"
    ):
        raise ApiError("ERR_QUARANTINE_REQUIRED")

    rma = refs.rma_of_return_line(line)
    line["condition_grade"] = condition_grade
    line["graded_by_user_id"] = user_id
    line["recovery_value_cents"] = calc.provisional_recovery(
        item["declared_value_cents"], condition_grade, line["reason_code"], line["quantity"]
    )
    services.run_grading_fraud_checks(line, item, client, rma)
    services.run_matrix(line, item, client)
    line["disposition_state"] = "DISPOSITION_ASSIGNED"
    refund = services.build_refund(line, item, client)
    score = line["fraud_score_release"]
    if score >= K.FRAUD_DENY_THRESHOLD:
        line["financial_state"] = "DENIED"
        refund["denial_reason"] = K.AUTO_DENIED_FRAUD_SCORE
        db.touch(refund)
    elif score >= K.FRAUD_HOLD_THRESHOLD:
        line["financial_state"] = "FRAUD_HOLD"
    else:
        line["financial_state"] = "HOLD_PENDING_DISPOSITION"
    db.touch(line)
    return response.ok(serialize.return_line(line))


@bp.post("/return-lines/<return_line_id>/override-disposition")
def override_disposition(return_line_id):
    mw.require("DispositionSupervisor", "CenterAdmin")
    body = response.body_json()
    disposition = shapes.req_enum(body, "disposition", K.DISPOSITIONS)
    shapes.req_str(body, "override_reason")
    line = services.must_return_line(return_line_id)
    item, client = _context(line)
    if line["disposition_state"] != "DISPOSITION_ASSIGNED":
        raise ApiError("ERR_LINE_INVALID_DISPOSITION_STATE")
    if item["recall_status"] == "MANDATORY":
        raise ApiError("ERR_RECALL_DISPOSITION_LOCKED")
    if disposition == "DONATE" and (
        item["regulated_flag"]
        or item["hazard_class"] != "NONE"
        or not client["donation_allowed"]
    ):
        raise ApiError("ERR_REGULATED_DONATION_FORBIDDEN")
    line["disposition"] = disposition
    line["recovery_value_cents"] = calc.provisional_recovery(
        item["declared_value_cents"],
        line["condition_grade"],
        line["reason_code"],
        line["quantity"],
    )
    services.recompute_refund(line, item, client)
    services.cancel_drifted_orders(line)
    db.touch(line)
    return response.ok(serialize.return_line(line))


@bp.post("/return-lines/<return_line_id>/clear-fraud-hold")
def clear_fraud_hold(return_line_id):
    mw.require("RefundAnalyst", "CenterAdmin")
    body = response.body_json()
    shapes.req_str(body, "resolution_note")
    line = services.must_return_line(return_line_id)
    _item, client = _context(line)
    if line["financial_state"] != "FRAUD_HOLD":
        raise ApiError("ERR_LINE_INVALID_FINANCIAL_STATE")
    if line["disposition_state"] == "DISPOSITIONED":
        line["financial_state"] = "RELEASE_PENDING"
        order = services.executed_order_of_line(line["id"])
        executed_at = db.parse_instant(order["executed_at"]) if order else None
        services.stamp_release_eligible(line, client, executed_at)
    else:
        line["financial_state"] = "HOLD_PENDING_DISPOSITION"
    services.refresh_release_score(line)
    db.touch(line)
    return response.ok(serialize.return_line(line))


@bp.post("/return-lines/<return_line_id>/release-refund")
def release_refund(return_line_id):
    user_id, _role = mw.require("RefundAnalyst")
    response.body_json()
    line = services.must_return_line(return_line_id)
    _item, client = _context(line)
    services.require_active(client)
    if line["financial_state"] not in ("RELEASE_PENDING", "FRAUD_HOLD"):
        raise ApiError("ERR_LINE_INVALID_FINANCIAL_STATE")
    if line["graded_by_user_id"] is not None and user_id == line["graded_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if line["financial_state"] == "FRAUD_HOLD":
        raise ApiError("ERR_FRAUD_HOLD_ACTIVE")
    refund = refs.refund_of_line(line["id"])
    if refund is None:
        raise ApiError("ERR_REFUND_RELEASE_NOT_FOUND")
    eligible_at = db.parse_instant(refund["release_eligible_at"])
    if eligible_at is None or db.now() < eligible_at:
        raise ApiError("ERR_REFUND_HOLD_ACTIVE")
    released_total = 0
    for other in db.all_rows("refund_releases"):
        if other["client_id"] != client["id"] or other["id"] == refund["id"]:
            continue
        other_line = db.get("return_lines", other["return_line_id"])
        if other_line is not None and other_line["financial_state"] == "REFUNDED":
            released_total += other["net_refund_cents"]
    if released_total + refund["net_refund_cents"] > client["max_refund_exposure_cents"]:
        raise ApiError("ERR_REFUND_EXCEEDS_EXPOSURE_CAP")

    services.refresh_release_score(line)
    line["financial_state"] = "REFUNDED"
    line["released_by_user_id"] = user_id
    db.touch(line)
    refund["released_at"] = db.now_str()
    refund["released_by_user_id"] = user_id
    db.touch(refund)
    aggregates.append_entry(
        client["id"],
        line["id"],
        "REFUND_DEBIT",
        -refund["net_refund_cents"],
        "refund released",
    )
    return response.ok(serialize.return_line(line))


@bp.post("/return-lines/<return_line_id>/deny-refund")
def deny_refund(return_line_id):
    user_id, _role = mw.require("RefundAnalyst")
    body = response.body_json()
    denial_reason = shapes.req_str(body, "denial_reason")
    line = services.must_return_line(return_line_id)
    _item, _client = _context(line)
    if line["financial_state"] not in (
        "HOLD_PENDING_DISPOSITION",
        "FRAUD_HOLD",
        "RELEASE_PENDING",
    ):
        raise ApiError("ERR_LINE_INVALID_FINANCIAL_STATE")
    if line["graded_by_user_id"] is not None and user_id == line["graded_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    services.refresh_release_score(line)
    line["financial_state"] = "DENIED"
    db.touch(line)
    refund = refs.refund_of_line(line["id"])
    if refund is not None:
        refund["denial_reason"] = denial_reason
        db.touch(refund)
    return response.ok(serialize.return_line(line))


@bp.post("/return-lines/<return_line_id>/reverse-refund")
def reverse_refund(return_line_id):
    mw.require("RefundAnalyst", "CenterAdmin")
    body = response.body_json()
    reversal_memo = shapes.req_str(body, "reversal_memo")
    line = services.must_return_line(return_line_id)
    _item, client = _context(line)
    if line["financial_state"] != "REFUNDED":
        raise ApiError("ERR_LINE_INVALID_FINANCIAL_STATE")
    refund = refs.refund_of_line(line["id"])
    if refund is None:
        raise ApiError("ERR_REFUND_RELEASE_NOT_FOUND")
    services.refresh_release_score(line)
    line["financial_state"] = "CLAWED_BACK"
    db.touch(line)
    refund["reversed_at"] = db.now_str()
    db.touch(refund)
    # §3.7: the REVERSAL entry's "memo carries the supplied text".
    aggregates.append_entry(
        client["id"],
        line["id"],
        "REVERSAL",
        refund["net_refund_cents"],
        "refund reversed: " + reversal_memo,
    )
    aggregates.auto_reinstate(client)
    return response.ok(serialize.return_line(line))


@bp.get("/refund-releases/<refund_release_id>")
def get_refund_release(refund_release_id):
    user_id, role = mw.require(
        "CenterAdmin", "RefundAnalyst", "DispositionSupervisor", "ClientRep"
    )
    refund = db.get("refund_releases", refund_release_id)
    if refund is not None:
        mw.scope(role, user_id, refund["client_id"])
    refund = services.must_refund(refund_release_id)
    return response.ok(serialize.refund_release(refund))


@bp.get("/refund-releases")
def list_refund_releases():
    user_id, role = mw.require(
        "CenterAdmin", "RefundAnalyst", "DispositionSupervisor", "ClientRep"
    )
    client_id = query.arg("client_id")
    if client_id is not None:
        services.must_client(client_id)
    return_line_id = query.arg("return_line_id")
    if return_line_id is not None:
        services.must_return_line(return_line_id)
    if role == mw.CLIENT_REP:
        client_id = user_id
    rows = db.sorted_rows(db.all_rows("refund_releases"))
    rows = query.eq(rows, "client_id", client_id)
    rows = query.eq(rows, "return_line_id", return_line_id)
    return response.paginate(rows, serialize.refund_release)
