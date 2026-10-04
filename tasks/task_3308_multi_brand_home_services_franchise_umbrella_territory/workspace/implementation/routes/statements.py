"""RoyaltyStatement endpoints -- dual-variant accrual (PRD 3.10, 2.8).

POST /franchise/royalty-statements, GET /franchise/royalty-statements[/{id}]
GET /franchise/royalty-statements/{id}/preview
POST /franchise/royalty-statements/{id}/issue|pay|void
"""
from flask import Blueprint

import derived
from auth import guard
from errors import ApiError
from fetch import get_agreement, get_statement, paged
from response import created, ok
from store import common_fields, db, now_dt, parse_instant, touch
from validate import (
    body,
    reject_unknown,
    req_id,
    req_int,
    req_str,
)
from calculations import royalty_draft, royalty_final

bp = Blueprint("statements", __name__)

CREATE_INPUT = ["agreement_id", "period_start", "period_end", "gross_revenue_cents"]


def _started_statement(statement_id):
    statement = get_statement(statement_id)
    if statement.get("status") in ("PAID", "VOIDED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    return statement


def _require_status(statement, allowed):
    if statement.get("status") not in allowed:
        raise ApiError("ERR_INVALID_STATE")


def _periods_overlap(start_a, end_a, start_b, end_b):
    return start_a < end_b and start_b < end_a


@bp.post("/franchise/royalty-statements")
def create_statement():
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, CREATE_INPUT)
    agreement_id = req_id(b, "agreement_id")
    period_start = req_str(b, "period_start")
    period_end = req_str(b, "period_end")
    gross_revenue = req_int(b, "gross_revenue_cents", minimum=0)

    start = parse_instant(period_start)
    end = parse_instant(period_end)
    if start is None or end is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "period_start and period_end must be ISO 8601 UTC instants.")
    get_agreement(agreement_id)
    if not end > start:
        raise ApiError("ERR_INVALID_PERIOD")

    for other in db.statements.values():
        if other.get("agreement_id") != agreement_id:
            continue
        if other.get("status") == "VOIDED":
            continue
        other_start = parse_instant(other.get("period_start") or "")
        other_end = parse_instant(other.get("period_end") or "")
        if other_start is None or other_end is None:
            continue
        if _periods_overlap(start, end, other_start, other_end):
            raise ApiError("ERR_STATEMENT_PERIOD_OVERLAP")

    record = common_fields()
    record.update({
        "_kind": "RoyaltyStatement",
        "agreement_id": agreement_id,
        "period_start": period_start,
        "period_end": period_end,
        "gross_revenue_cents": gross_revenue,
        "royalty_cents": 0,
        "ad_fund_cents": 0,
        "referral_offset_cents": 0,
        "net_remittance_cents": 0,
        "accrual_variant": "DRAFT_PROPORTIONAL",
        "issued_clock_iso": None,
        "status": "DRAFT",
    })
    db.statements[record["id"]] = record
    return created(record)


@bp.get("/franchise/royalty-statements/<statement_id>")
def read_statement(statement_id):
    guard(["FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor"])
    return ok(get_statement(statement_id))


@bp.get("/franchise/royalty-statements/<statement_id>/preview")
def preview_statement(statement_id):
    guard(["FranchiseAdmin"])
    statement = get_statement(statement_id)
    return ok(royalty_draft(statement))


@bp.get("/franchise/royalty-statements")
def list_statements():
    guard(["FranchiseAdmin", "ComplianceAuditor"])
    return paged(db.statements, "agreement_id", "status")


@bp.post("/franchise/royalty-statements/<statement_id>/issue")
def issue_statement(statement_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    statement = _started_statement(statement_id)
    _require_status(statement, ["DRAFT"])
    start = parse_instant(statement.get("period_start") or "")
    end = parse_instant(statement.get("period_end") or "")
    if start is None or end is None or not end > start:
        raise ApiError("ERR_INVALID_PERIOD")

    figures = royalty_final(statement)
    statement.update(figures)
    statement["status"] = "ISSUED"
    statement["issued_clock_iso"] = derived.now_iso()
    touch(statement)

    agreement = get_agreement(statement.get("agreement_id"))
    derived.refresh_agreement(agreement)
    agreement["cumulative_royalty_cents"] = int(
        agreement.get("cumulative_royalty_cents") or 0) + int(statement.get("royalty_cents") or 0)
    touch(agreement)
    return ok(statement)


@bp.post("/franchise/royalty-statements/<statement_id>/pay")
def pay_statement(statement_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    statement = _started_statement(statement_id)
    _require_status(statement, ["ISSUED"])
    statement["status"] = "PAID"
    touch(statement)
    return ok(statement)


@bp.post("/franchise/royalty-statements/<statement_id>/void")
def void_statement(statement_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    statement = _started_statement(statement_id)
    _require_status(statement, ["ISSUED"])
    statement["status"] = "VOIDED"
    touch(statement)

    agreement = get_agreement(statement.get("agreement_id"))
    derived.refresh_agreement(agreement)
    agreement["cumulative_royalty_cents"] = int(
        agreement.get("cumulative_royalty_cents") or 0) - int(statement.get("royalty_cents") or 0)
    touch(agreement)
    return ok(statement)