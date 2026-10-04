"""Payout loan and amortization routes."""

import flask

import middleware
from db import loan_amortization_entries, payout_loans
from response import ok, ok_list
from services import common
from services import loans as loan_service


bp = flask.Blueprint("loans", __name__)


@bp.post("/payout-loans")
def create_loan():
    role = middleware.require_role("AdvisorOps", "PlatformAdmin")
    data = common.body()
    middleware.require_advisor_owner(role, common.require_field(data, "advisor_code"))
    return ok(loan_service.serialize(loan_service.create(data)), status=201)


@bp.get("/payout-loans")
def list_loans():
    middleware.require_role("AdvisorOps", "PlatformAdmin", "ComplianceOfficer")
    args = flask.request.args
    limit, offset = common.pagination_params()
    rows = [row for row in payout_loans.values()
            if (args.get("advisor_code") is None or row["advisor_code"] == args.get("advisor_code"))
            and (args.get("status") is None or row["status"] == args.get("status"))]
    page, total = common.page(rows, limit, offset)
    return ok_list([loan_service.serialize(row) for row in page], total, limit, offset)


@bp.get("/payout-loans/<loan_id>")
def get_loan(loan_id):
    middleware.require_role(*middleware.ANY)
    return ok(loan_service.serialize(loan_service.find_loan_or_fail(loan_id)))


@bp.get("/payout-loans/<loan_id>/amortization-entries")
def list_loan_entries(loan_id):
    middleware.require_role("AdvisorOps", "ComplianceOfficer", "PlatformAdmin")
    row = loan_service.find_loan_or_fail(loan_id)
    limit, offset = common.pagination_params()
    rows = loan_service.amortization_entries_of(row["id"])
    page, total = common.page(rows, limit, offset)
    return ok_list([loan_service.serialize(item) for item in page], total, limit, offset)


@bp.get("/payout-loans/<loan_id>/forgiveness-audit")
def forgiveness_audit(loan_id):
    middleware.require_role("AdvisorOps", "ComplianceOfficer", "PlatformAdmin")
    row = loan_service.find_loan_or_fail(loan_id)
    return ok(loan_service.forgiveness_audit(row))


@bp.get("/payout-loans/<loan_id>/amortization-schedule")
def amortization_schedule(loan_id):
    middleware.require_role("AdvisorOps", "ComplianceOfficer", "PlatformAdmin")
    row = loan_service.find_loan_or_fail(loan_id)
    return ok(loan_service.amortization_schedule(row))


@bp.post("/payout-loans/<loan_id>/amortize")
def amortize(loan_id):
    role = middleware.require_role("AdvisorOps", "BranchManager")
    row = loan_service.find_loan_or_fail(loan_id)
    middleware.require_advisor_owner(role, row["advisor_code"])
    return ok(loan_service.serialize(loan_service.amortize(row, common.body())))


@bp.post("/payout-loans/<loan_id>/forgive")
def forgive(loan_id):
    middleware.require_role("AdvisorOps", "PlatformAdmin")
    row = loan_service.find_loan_or_fail(loan_id)
    return ok(loan_service.serialize(loan_service.forgive(row, common.body())))


@bp.get("/loan-amortization-entries")
def list_amortization_entries():
    middleware.require_role("AdvisorOps", "ComplianceOfficer", "PlatformAdmin")
    args = flask.request.args
    limit, offset = common.pagination_params()
    rows = [row for row in loan_amortization_entries.values()
            if (args.get("payout_loan_id") is None or row["payout_loan_id"] == args.get("payout_loan_id"))
            and (args.get("payout_period_id") is None
                 or row["payout_period_id"] == args.get("payout_period_id"))]
    page, total = common.page(rows, limit, offset)
    return ok_list([loan_service.serialize(row) for row in page], total, limit, offset)


@bp.get("/loan-amortization-entries/<entry_id>")
def get_amortization_entry(entry_id):
    middleware.require_role("AdvisorOps", "ComplianceOfficer", "PlatformAdmin")
    row = loan_amortization_entries.get(entry_id)
    if row is None:
        from errors import fail
        fail("ERR_NOT_FOUND")
    return ok(loan_service.serialize(row))