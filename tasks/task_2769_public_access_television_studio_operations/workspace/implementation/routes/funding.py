"""Franchise fee and capital funding administration (PRD 3.8)."""

from flask import Blueprint

import calc
import constants as C
import db
import middleware
import support
import validation
from errors import ApiError, bad_request, invalid_transition

bp = Blueprint("funding", __name__)

READ_ROLES = (C.ROLE_CENTER_ADMIN, C.ROLE_FINANCE_OFFICER)
DECISIONS = ["ACCEPT", "RETURN"]


def _capital_grant_within_base(period):
    """Priority 42: the grant may not exceed the basis-selected allocable base."""
    if period["capital_grant_cents"] > calc.allocable_base(period):
        raise ApiError(
            "ERR_CAPITAL_GRANT_EXCEEDS_BASE",
            "The capital grant exceeds the allocable base it sits on top of",
        )


@bp.post("/funding-periods")
def create_period():
    middleware.authorize(C.ROLE_FINANCE_OFFICER)
    body = validation.body()
    fiscal_year = validation.req_int(body, "fiscal_year", minimum=2000)
    quarter = validation.req_int(body, "quarter", minimum=1, maximum=4)
    basis = validation.req_enum(body, "basis", C.FUNDING_BASES)
    gross = validation.req_int(body, "gross_franchise_fee_cents", minimum=0)
    earned = validation.req_int(body, "service_period_earned_cents", minimum=0)
    remitted = validation.req_int(body, "remittance_received_cents", minimum=0)
    capital_grant = validation.opt_int(body, "capital_grant_cents", minimum=0, default=0)
    # priority 38
    for row in db.all_rows("funding_periods"):
        if row["fiscal_year"] == fiscal_year and row["quarter"] == quarter:
            raise ApiError(
                "ERR_DUPLICATE_NATURAL_KEY",
                "A funding period already exists for that fiscal year and quarter",
            )
    draft = {
        "fiscal_year": fiscal_year,
        "quarter": quarter,
        "basis": basis,
        "gross_franchise_fee_cents": gross,
        "service_period_earned_cents": earned,
        "remittance_received_cents": remitted,
        "capital_grant_cents": capital_grant,
    }
    # priority 42
    _capital_grant_within_base(draft)
    draft.update(
        {
            "allocable_base_cents": 0,
            "admin_reserve_cents": 0,
            "capital_allocation_cents": 0,
            "operating_allocation_cents": 0,
            "total_program_funds_cents": 0,
            "report_status": "DRAFT",
            "revision_round": 0,
            "submitted_by_user_id": None,
            "decided_by_user_id": None,
            "decision_reason": None,
        }
    )
    row = db.new_row("funding_periods", draft)
    return support.created("funding_periods", row)


@bp.get("/funding-periods/<period_id>")
def read_period(period_id):
    middleware.authorize(*READ_ROLES)
    row = support.must_exist("funding_periods", period_id)
    return support.single("funding_periods", row)


@bp.get("/funding-periods")
def list_periods():
    middleware.authorize(*READ_ROLES)
    fiscal_year = validation.query_int("fiscal_year")
    report_status = validation.query_enum("report_status", C.FUNDING_REPORT_STATUSES)
    validation.pagination()
    rows = support.filter_rows(
        "funding_periods", [("fiscal_year", fiscal_year), ("report_status", report_status)]
    )
    return support.collection_response("funding_periods", rows)


@bp.post("/funding-periods/<period_id>/revise")
def revise_period(period_id):
    middleware.authorize(C.ROLE_FINANCE_OFFICER)
    body = validation.body()
    expected = validation.req_int(body, "expected_funding_period_version")
    basis = validation.opt_enum(body, "basis", C.FUNDING_BASES)
    earned = validation.opt_int(body, "service_period_earned_cents", minimum=0)
    remitted = validation.opt_int(body, "remittance_received_cents", minimum=0)
    capital_grant = validation.opt_int(body, "capital_grant_cents", minimum=0)
    row = support.must_exist("funding_periods", period_id)
    # priority 8, ahead of the state check
    if expected != row["version"]:
        raise ApiError(
            "ERR_STALE_FUNDING_PERIOD_VERSION", "The funding period has moved on; re-read it"
        )
    # priority 9
    if row["report_status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        raise invalid_transition("Only a draft or returned funding period may be restated")
    was_returned = row["report_status"] == "RETURNED_FOR_REVISION"
    # Whatever is supplied replaces the stored figure; whatever is omitted is left
    # alone. The replacement is staged on a candidate view so that a refusal at
    # priority 42 leaves the stored period completely untouched.
    effective = {
        "basis": row["basis"] if basis is None else basis,
        "service_period_earned_cents": (
            row["service_period_earned_cents"] if earned is None else earned
        ),
        "remittance_received_cents": (
            row["remittance_received_cents"] if remitted is None else remitted
        ),
        "capital_grant_cents": (
            row["capital_grant_cents"] if capital_grant is None else capital_grant
        ),
    }
    # priority 42, under the effective basis
    _capital_grant_within_base(effective)
    row.update(effective)
    row["revision_round"] = row["revision_round"] + 1
    row["report_status"] = "DRAFT"
    if was_returned:
        row["submitted_by_user_id"] = None
    row.update(calc.franchise_allocation(row))
    db.bump(row)
    return support.single("funding_periods", row)


@bp.post("/funding-periods/<period_id>/report-submit")
def submit_report(period_id):
    user_id, _role = middleware.authorize(C.ROLE_FINANCE_OFFICER)
    validation.body()
    row = support.must_exist("funding_periods", period_id)
    # priority 9
    if row["report_status"] != "DRAFT":
        raise invalid_transition("Only a draft funding period may be submitted")
    # priority 41
    if calc.allocable_base(row) <= 0:
        raise ApiError(
            "ERR_ALLOCABLE_BASE_NOT_POSITIVE", "The basis-selected allocable base is not positive"
        )
    row.update(calc.franchise_allocation(row))
    row["report_status"] = "SUBMITTED"
    row["submitted_by_user_id"] = user_id
    db.bump(row)
    return support.single("funding_periods", row)


@bp.post("/funding-periods/<period_id>/report-decision")
def decide_report(period_id):
    user_id, _role = middleware.authorize(C.ROLE_CENTER_ADMIN)
    body = validation.body()
    decision = validation.req_enum(body, "decision", DECISIONS)
    reason = validation.opt_string(body, "reason")
    if decision == "RETURN" and (reason is None or reason.strip() == ""):
        raise bad_request("reason is required when returning a report for revision")
    row = support.must_exist("funding_periods", period_id)
    # priority 7, ahead of the state check
    if row["submitted_by_user_id"] is not None and row["submitted_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The submitter of a report may not decide it"
        )
    # priority 9
    if row["report_status"] != "SUBMITTED":
        raise invalid_transition("Only a submitted funding period may be decided")
    if decision == "ACCEPT":
        row["report_status"] = "ACCEPTED"
        row["decided_by_user_id"] = user_id
    else:
        row["report_status"] = "RETURNED_FOR_REVISION"
        row["decided_by_user_id"] = user_id
        row["decision_reason"] = reason
    db.bump(row)
    return support.single("funding_periods", row)
