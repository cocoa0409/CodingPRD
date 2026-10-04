"""Account, revenue-entry and transfer routes."""

import flask

import middleware
from db import accounts, revenue_entries
from response import ok, ok_list
from services import accounts as account_service
from services import advisors as advisor_service
from services import common


bp = flask.Blueprint("accounts", __name__)


@bp.post("/accounts")
def create_account():
    role = middleware.require_role("AdvisorOps", "BranchManager")
    data = common.body()
    middleware.require_advisor_owner(role, common.require_field(data, "advisor_code"))
    return ok(account_service.serialize(account_service.create_account(data)), status=201)


@bp.get("/accounts")
def list_accounts():
    middleware.require_role(*middleware.ANY)
    args = flask.request.args
    limit, offset = common.pagination_params()
    rows = [row for row in accounts.values()
            if (args.get("advisor_code") is None or row["advisor_code"] == args.get("advisor_code"))
            and (args.get("account_type") is None or row["account_type"] == args.get("account_type"))
            and (args.get("status") is None or row["status"] == args.get("status"))]
    page, total = common.page(rows, limit, offset)
    return ok_list([account_service.serialize(row) for row in page], total, limit, offset)


@bp.get("/accounts/<account_id>")
def get_account(account_id):
    middleware.require_role(*middleware.ANY)
    return ok(account_service.serialize(account_service.find_account_or_fail(account_id)))


@bp.get("/accounts/<account_id>/advisory-splits")
def list_account_splits(account_id):
    middleware.require_role("AdvisorOps", "BranchManager", "ComplianceOfficer")
    from db import advisory_revenue_splits
    row = account_service.find_account_or_fail(account_id)
    limit, offset = common.pagination_params()
    rows = [split for split in advisory_revenue_splits.values() if split["account_id"] == row["id"]]
    page, total = common.page(rows, limit, offset)
    return ok_list([account_service.serialize(item) for item in page], total, limit, offset)


@bp.get("/accounts/<account_id>/revenue-entries")
def list_account_entries(account_id):
    middleware.require_role(*middleware.ANY)
    row = account_service.find_account_or_fail(account_id)
    limit, offset = common.pagination_params()
    rows = [entry for entry in revenue_entries.values() if entry["account_id"] == row["id"]]
    page, total = common.page(rows, limit, offset)
    return ok_list([account_service.serialize(item) for item in page], total, limit, offset)


@bp.post("/accounts/<account_id>/transfer/confirm")
def confirm_transfer(account_id):
    middleware.require_role("AdvisorOps", "ComplianceOfficer", "BranchManager")
    row = account_service.find_account_or_fail(account_id)
    return ok(account_service.serialize(account_service.confirm_transfer(row, {})))


# ---------------------------------------------------------------------------
# Revenue entries
# ---------------------------------------------------------------------------

@bp.post("/revenue-entries")
def create_entry():
    role = middleware.require_role("AdvisorOps", "BranchManager")
    data = common.body()
    middleware.require_advisor_owner(role, common.require_field(data, "advisor_code"))
    return ok(account_service.serialize(account_service.create_entry(data)), status=201)


@bp.get("/revenue-entries")
def list_entries():
    middleware.require_role(*middleware.ANY)
    args = flask.request.args
    limit, offset = common.pagination_params()
    rows = [row for row in revenue_entries.values()
            if (args.get("advisor_code") is None or row["advisor_code"] == args.get("advisor_code"))
            and (args.get("account_id") is None or row["account_id"] == args.get("account_id"))
            and (args.get("status") is None or row["status"] == args.get("status"))]
    page, total = common.page(rows, limit, offset)
    return ok_list([account_service.serialize(row) for row in page], total, limit, offset)


@bp.get("/revenue-entries/<entry_id>")
def get_entry(entry_id):
    middleware.require_role(*middleware.ANY)
    return ok(account_service.serialize(account_service.find_entry_or_fail(entry_id)))


@bp.post("/revenue-entries/<entry_id>/release")
def release_entry(entry_id):
    role = middleware.require_role("AdvisorOps", "BranchManager")
    row = account_service.find_entry_or_fail(entry_id)
    middleware.require_advisor_owner(role, row["advisor_code"])
    return ok(account_service.serialize(account_service.release_entry(row, common.body())))