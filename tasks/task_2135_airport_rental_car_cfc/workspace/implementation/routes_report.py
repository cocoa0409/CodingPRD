"""Transaction-day reporting, the audit cycle and CFC remittances."""

import datetime

from flask import Blueprint, g

import calc
import serializers as ser
from domain import agreement_or_404, auto_fund_one, bump, check_owner, rows_of
from errors import ApiError
from store import all_rows, db, get, new_row
from validation import (ALL_ROLES, body, endpoint, pagination, paginate, q_enum,
                        q_int, q_str, req_enum, req_int, req_str)
import response as resp

bp = Blueprint("report", __name__)

REPORT_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_AUDIT", "REJECTED", "ACCEPTED",
                   "SUPERSEDED")
OPEN_REPORT_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_AUDIT", "REJECTED")
REMITTANCE_STATUSES = ("PENDING", "DELINQUENT", "RECEIVED", "RECONCILED")
REMITTANCE_BASES = ("PROVISIONAL", "FINAL")


# --------------------------------------------------------------------------
# TransactionDayReport
# --------------------------------------------------------------------------

@bp.route("/rac/transaction-day-reports", methods=["POST"])
@endpoint(["ConcessionaireOperator", "FacilityAdmin"])
def create_report():
    data = body()
    agreement_id = req_str(data, "agreement_id")
    period_year = req_int(data, "period_year", minimum=2000, maximum=2100)
    period_month = req_int(data, "period_month", minimum=1, maximum=12)
    reported_revenue = req_int(data, "reported_gross_revenue_cents", minimum=0)
    reported_days = req_int(data, "reported_on_airport_transaction_days", minimum=0)

    agreement = agreement_or_404(agreement_id)
    check_owner(agreement)

    for existing in all_rows("reports"):
        if existing["agreement_id"] != agreement["id"]:
            continue
        if existing["period_year"] != period_year or existing["period_month"] != period_month:
            continue
        if existing["status"] in OPEN_REPORT_STATUSES:
            raise ApiError("ERR_DUPLICATE_REPORT_PERIOD")

    row = new_row("reports", {
        "agreement_id": agreement["id"],
        "period_year": period_year,
        "period_month": period_month,
        "reported_gross_revenue_cents": reported_revenue,
        "reported_on_airport_transaction_days": reported_days,
        "audited_gross_revenue_cents": None,
        "audited_on_airport_transaction_days": None,
        "revenue_variance_cents": None,
        "variance_assessment_cents": 0,
        "period_rent_installment_cents": 0,
        "status": "DRAFT",
        "audited_by_user_id": None,
        "rejection_reason": None,
        "submission_count": 0,
    })
    return resp.created(ser.report(row))


@bp.route("/rac/transaction-day-reports/<report_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_report(report_id):
    return resp.ok(ser.report(get("reports", report_id, "ERR_REPORT_NOT_FOUND")))


@bp.route("/rac/transaction-day-reports", methods=["GET"])
@endpoint(ALL_ROLES)
def list_reports():
    limit, offset = pagination()
    rows = rows_of("reports",
                   agreement_id=q_str("agreement_id"),
                   status=q_enum("status", REPORT_STATUSES),
                   period_year=q_int("period_year"),
                   period_month=q_int("period_month"))
    items, limit, offset, total = paginate(rows, limit, offset, ser.report)
    return resp.listing(items, limit, offset, total)


@bp.route("/rac/transaction-day-reports/<report_id>/submit", methods=["POST"])
@endpoint(["ConcessionaireOperator", "FacilityAdmin"])
def submit_report(report_id):
    row = get("reports", report_id, "ERR_REPORT_NOT_FOUND")
    agreement = db.agreements[row["agreement_id"]]
    check_owner(agreement)
    if row["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if agreement["contract_status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE",
                       "The agreement must be ACTIVE or SUSPENDED to submit a report.")
    row["status"] = "SUBMITTED"
    row["submission_count"] += 1
    bump(row)
    return resp.ok(ser.report(row))


@bp.route("/rac/transaction-day-reports/<report_id>/begin-audit", methods=["POST"])
@endpoint(["AuditOfficer"])
def begin_audit(report_id):
    row = get("reports", report_id, "ERR_REPORT_NOT_FOUND")
    if row["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    row["status"] = "UNDER_AUDIT"
    bump(row)
    return resp.ok(ser.report(row))


@bp.route("/rac/transaction-day-reports/<report_id>/reject", methods=["POST"])
@endpoint(["AuditOfficer"])
def reject_report(report_id):
    data = body()
    rejection_reason = req_str(data, "rejection_reason")
    row = get("reports", report_id, "ERR_REPORT_NOT_FOUND")
    if row["status"] != "UNDER_AUDIT":
        raise ApiError("ERR_INVALID_STATE")
    row["status"] = "REJECTED"
    row["rejection_reason"] = rejection_reason
    bump(row)
    return resp.ok(ser.report(row))


@bp.route("/rac/transaction-day-reports/<report_id>/reopen", methods=["POST"])
@endpoint(["ConcessionaireOperator", "FacilityAdmin"])
def reopen_report(report_id):
    row = get("reports", report_id, "ERR_REPORT_NOT_FOUND")
    agreement = db.agreements[row["agreement_id"]]
    check_owner(agreement)
    if row["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_STATE")
    row["status"] = "DRAFT"
    row["rejection_reason"] = None
    bump(row)
    return resp.ok(ser.report(row))


@bp.route("/rac/transaction-day-reports/<report_id>/accept", methods=["POST"])
@endpoint(["AuditOfficer"])
def accept_report(report_id):
    data = body()
    audited_revenue = req_int(data, "audited_gross_revenue_cents", minimum=0)
    audited_days = req_int(data, "audited_on_airport_transaction_days", minimum=0)

    row = get("reports", report_id, "ERR_REPORT_NOT_FOUND")
    if row["status"] != "UNDER_AUDIT":
        raise ApiError("ERR_INVALID_STATE")

    agreement = db.agreements[row["agreement_id"]]

    # Housekeeping: demote an earlier ACCEPTED report for the same period.
    for other in all_rows("reports"):
        if other["id"] == row["id"]:
            continue
        if other["agreement_id"] != agreement["id"]:
            continue
        if other["period_year"] != row["period_year"] or \
                other["period_month"] != row["period_month"]:
            continue
        if other["status"] != "ACCEPTED":
            continue
        other["status"] = "SUPERSEDED"
        bump(other)
        agreement["gross_revenue_ytd_cents"] -= (other["audited_gross_revenue_cents"] or 0)
        agreement["transaction_days_ytd"] -= (other["audited_on_airport_transaction_days"] or 0)
        agreement["accepted_report_count"] -= 1

    # Hop one — write the audit onto the report.
    row["audited_gross_revenue_cents"] = audited_revenue
    row["audited_on_airport_transaction_days"] = audited_days
    row["revenue_variance_cents"] = audited_revenue - row["reported_gross_revenue_cents"]
    row["variance_assessment_cents"] = calc.bps_of(
        max(0, row["revenue_variance_cents"]), agreement["percentage_rent_rate_bps"])
    row["audited_by_user_id"] = g.user_id
    row["status"] = "ACCEPTED"

    # Hop two — roll into the agreement ledger and compute the installment.
    tier_before = agreement["rent_tier"]
    agreement["accepted_report_count"] += 1
    agreement["gross_revenue_ytd_cents"] += audited_revenue
    agreement["transaction_days_ytd"] += audited_days
    calc.percentage_rent_accrual(agreement, row)

    # Hop three — supersede DRAFT settlements when the tier crossed to PERCENTAGE.
    if tier_before == "MAG_FLOOR" and agreement["rent_tier"] == "PERCENTAGE":
        for settlement in all_rows("settlements"):
            if settlement["agreement_id"] != agreement["id"]:
                continue
            if settlement["status"] != "DRAFT":
                continue
            settlement["status"] = "SUPERSEDED"
            bump(settlement)

    if row["variance_assessment_cents"] > 0:
        if agreement["compliance_status"] in ("COMPLIANT", "DELINQUENT"):
            agreement["compliance_status"] = "COVENANT_BREACH"

    bump(row)
    bump(agreement)
    return resp.ok(ser.report(row))


# --------------------------------------------------------------------------
# CfcRemittance
# --------------------------------------------------------------------------

@bp.route("/rac/cfc-remittances", methods=["POST"])
@endpoint(["ConcessionaireOperator", "FacilityAdmin"])
def create_remittance():
    data = body()
    agreement_id = req_str(data, "agreement_id")
    report_id = req_str(data, "report_id")
    remittance_basis = req_enum(data, "remittance_basis", REMITTANCE_BASES)

    agreement = agreement_or_404(agreement_id)
    report = get("reports", report_id, "ERR_REPORT_NOT_FOUND")

    check_owner(agreement)

    for existing in all_rows("remittances"):
        if existing["report_id"] != report["id"]:
            continue
        if existing["remittance_basis"] != remittance_basis:
            continue
        if existing["status"] != "RECONCILED":
            raise ApiError("ERR_DUPLICATE_REMITTANCE")

    if report["agreement_id"] != agreement["id"]:
        raise ApiError("ERR_REPORT_AGREEMENT_MISMATCH")

    if remittance_basis == "PROVISIONAL":
        if report["status"] not in ("SUBMITTED", "UNDER_AUDIT"):
            raise ApiError("ERR_REMITTANCE_BASIS_MISMATCH")
        billable_days = report["reported_on_airport_transaction_days"]
    else:
        if report["status"] != "ACCEPTED":
            raise ApiError("ERR_REMITTANCE_BASIS_MISMATCH")
        billable_days = report["audited_on_airport_transaction_days"] or 0

    facility = db.facilities[agreement["facility_id"]]
    expected = billable_days * facility["cfc_rate_per_transaction_day_cents"]

    last_day = calc.last_day_of_month(report["period_year"], report["period_month"])
    due_date = calc.iso(
        last_day + datetime.timedelta(days=facility["remittance_grace_days"]))

    row = new_row("remittances", {
        "agreement_id": agreement["id"],
        "report_id": report["id"],
        "remittance_basis": remittance_basis,
        "expected_amount_cents": expected,
        "amount_received_cents": 0,
        "shortfall_cents": expected,
        "due_date": due_date,
        "status": "PENDING",
        "allocated_to_debt_service_cents": 0,
        "allocated_to_om_cents": 0,
        "allocated_to_capital_cents": 0,
        "allocated_to_unallocated_cents": 0,
    })
    return resp.created(ser.remittance(row))


@bp.route("/rac/cfc-remittances/<remittance_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_remittance(remittance_id):
    row = get("remittances", remittance_id, "ERR_REMITTANCE_NOT_FOUND")
    return resp.ok(ser.remittance(row))


@bp.route("/rac/cfc-remittances", methods=["GET"])
@endpoint(ALL_ROLES)
def list_remittances():
    limit, offset = pagination()
    rows = rows_of("remittances",
                   agreement_id=q_str("agreement_id"),
                   report_id=q_str("report_id"),
                   status=q_enum("status", REMITTANCE_STATUSES))
    items, limit, offset, total = paginate(rows, limit, offset, ser.remittance)
    return resp.listing(items, limit, offset, total)


@bp.route("/rac/cfc-remittances/<remittance_id>/receive", methods=["POST"])
@endpoint(["FinanceOfficer"])
def receive_remittance(remittance_id):
    data = body()
    amount = req_int(data, "amount_received_cents", minimum=0)

    row = get("remittances", remittance_id, "ERR_REMITTANCE_NOT_FOUND")
    if row["status"] not in ("PENDING", "DELINQUENT", "RECEIVED"):
        raise ApiError("ERR_INVALID_STATE")

    agreement = db.agreements[row["agreement_id"]]
    facility = db.facilities[agreement["facility_id"]]

    # Hop one — accumulate and recompute the shortfall.
    row["amount_received_cents"] += amount
    row["shortfall_cents"] = max(0, row["expected_amount_cents"] - row["amount_received_cents"])
    if row["amount_received_cents"] >= row["expected_amount_cents"]:
        row["status"] = "RECONCILED"
    else:
        row["status"] = "RECEIVED"

    # Hop two — the trust waterfall over the newly arrived cents only.
    to_ds, to_om, to_capital, to_unallocated = calc.cfc_trust_waterfall(facility, amount)
    facility["trust_debt_service_reserve_cents"] += to_ds
    facility["trust_om_reserve_cents"] += to_om
    facility["trust_capital_fund_cents"] += to_capital
    facility["trust_unallocated_cents"] += to_unallocated
    facility["trust_lifetime_received_cents"] += amount
    row["allocated_to_debt_service_cents"] += to_ds
    row["allocated_to_om_cents"] += to_om
    row["allocated_to_capital_cents"] += to_capital
    row["allocated_to_unallocated_cents"] += to_unallocated

    # Hop three — recompute the covenant posture.
    calc.recompute_bond_coverage(facility)

    # Hop four — offer the refreshed reserve to the auto-funding selector.
    # Hop five — a newly funded obligation releases the facility's waiting
    # capital projects; auto_fund_one performs that release (PRD 3.8).
    auto_fund_one(facility)

    bump(row)
    bump(facility)

    # Compliance may return to COMPLIANT once no delinquency remains.
    if agreement["compliance_status"] == "DELINQUENT":
        remaining = [r for r in all_rows("remittances")
                     if r["agreement_id"] == agreement["id"] and r["status"] == "DELINQUENT"]
        if not remaining:
            agreement["compliance_status"] = "COMPLIANT"
            bump(agreement)

    return resp.ok(ser.remittance(row))
