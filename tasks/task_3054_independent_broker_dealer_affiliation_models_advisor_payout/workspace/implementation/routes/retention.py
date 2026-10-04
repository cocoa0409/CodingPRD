"""Transition record and account retention routes."""

import flask

import middleware
from db import account_retentions, transition_records
from response import ok, ok_list
from services import common
from services import retention as retention_service


bp = flask.Blueprint("retention", __name__)


def _owning_advisor(transition):
    from services import advisors as advisor_service
    return advisor_service.get_by_code_or_fail(transition["advisor_code"])


@bp.post("/transitions")
def create_transition():
    role = middleware.require_role("AdvisorOps", "BranchManager")
    data = common.body()
    middleware.require_advisor_owner(role, common.require_field(data, "advisor_code"))
    return ok(retention_service.serialize_transition(retention_service.create(data)), status=201)


@bp.get("/transitions")
def list_transitions():
    middleware.require_role(*middleware.ANY)
    args = flask.request.args
    limit, offset = common.pagination_params()
    rows = [row for row in transition_records.values()
            if (args.get("advisor_code") is None or row["advisor_code"] == args.get("advisor_code"))
            and (args.get("payout_period_id") is None
                 or row["payout_period_id"] == args.get("payout_period_id"))
            and (args.get("status") is None or row["status"] == args.get("status"))]
    page, total = common.page(rows, limit, offset)
    return ok_list([retention_service.serialize_transition(row) for row in page], total, limit, offset)


@bp.get("/transitions/<transition_id>")
def get_transition(transition_id):
    middleware.require_role(*middleware.ANY)
    return ok(retention_service.serialize_transition(
        retention_service.find_transition_or_fail(transition_id)))


@bp.get("/transitions/<transition_id>/retention-rows")
def list_retention_rows(transition_id):
    middleware.require_role("AdvisorOps", "BranchManager", "ComplianceOfficer")
    row = retention_service.find_transition_or_fail(transition_id)
    limit, offset = common.pagination_params()
    rows = retention_service.rows_of(row["id"])
    page, total = common.page(rows, limit, offset)
    return ok_list([retention_service.serialize_retention(item) for item in page], total, limit, offset)


@bp.post("/transitions/<transition_id>/retention/contest")
def contest(transition_id):
    middleware.require_role("BranchManager")
    row = retention_service.find_transition_or_fail(transition_id)
    return ok(retention_service.serialize_retention(retention_service.contest(row, common.body())), status=201)


@bp.post("/transitions/<transition_id>/retention/settle")
def settle(transition_id):
    middleware.require_role("BranchManager")
    row = retention_service.find_transition_or_fail(transition_id)
    return ok(retention_service.serialize_transition(retention_service.settle(row, common.body())))


@bp.post("/transitions/<transition_id>/retention/lose")
def lose(transition_id):
    middleware.require_role("BranchManager")
    row = retention_service.find_transition_or_fail(transition_id)
    return ok(retention_service.serialize_transition(retention_service.lose(row, common.body())))


# ---------------------------------------------------------------------------
# Account retentions
# ---------------------------------------------------------------------------

@bp.get("/account-retentions")
def list_account_retentions():
    middleware.require_role(*middleware.ANY)
    args = flask.request.args
    limit, offset = common.pagination_params()
    rows = [row for row in account_retentions.values()
            if (args.get("transition_record_id") is None
                or row["transition_record_id"] == args.get("transition_record_id"))
            and (args.get("account_id") is None or row["account_id"] == args.get("account_id"))
            and (args.get("status") is None or row["status"] == args.get("status"))]
    page, total = common.page(rows, limit, offset)
    return ok_list([retention_service.serialize_retention(row) for row in page], total, limit, offset)


@bp.get("/account-retentions/<retention_id>")
def get_account_retention(retention_id):
    middleware.require_role(*middleware.ANY)
    return ok(retention_service.serialize_retention(
        retention_service.find_retention_or_fail(retention_id)))


@bp.post("/account-retentions/<retention_id>/state")
def move_retention_state(retention_id):
    middleware.require_role("BranchManager")
    row = retention_service.find_retention_or_fail(retention_id)
    return ok(retention_service.serialize_retention(
        retention_service.move_retention_state(row, common.body())))