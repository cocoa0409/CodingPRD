"""Advisor routes: CRUD, lifecycle, payout lines, bulk import."""

import flask

import middleware
from db import advisors
from errors import fail
from response import ok, ok_list
from services import advisors as advisor_service
from services import common, lifecycle
from services import payout_periods as period_service


bp = flask.Blueprint("advisors", __name__)


@bp.post("/advisors")
def create_advisor():
    role = middleware.require_role("PlatformAdmin", "AdvisorOps")
    data = common.body()
    # The acting advisor does not exist yet, so the entity-backed identity
    # cannot name the row being created; only its presence is required.
    middleware.require_advisor_owner(role, common.require_field(data, "advisor_code"))
    return ok(advisor_service.serialize(advisor_service.create(data)), status=201)


@bp.get("/advisors")
def list_advisors():
    middleware.require_role(*middleware.ANY)
    args = flask.request.args
    limit, offset = common.pagination_params()
    rows = [row for row in advisors.values()
            if (args.get("primary_branch_code") is None
                or row["primary_branch_code"] == args.get("primary_branch_code"))
            and (args.get("status") is None or row["status"] == args.get("status"))
            and (args.get("affiliation_model") is None
                 or row["affiliation_model"] == args.get("affiliation_model"))]
    page, total = common.page(rows, limit, offset)
    return ok_list([advisor_service.serialize(row) for row in page], total, limit, offset)


@bp.get("/advisors/<advisor_id>")
def get_advisor(advisor_id):
    middleware.require_role(*middleware.ANY)
    return ok(advisor_service.serialize(advisor_service.get_by_id_or_fail(advisor_id)))


@bp.patch("/advisors/<advisor_id>")
def patch_advisor(advisor_id):
    role = middleware.require_role("AdvisorOps", "PlatformAdmin")
    data = common.body()
    row = advisor_service.get_by_id_or_fail(advisor_id)
    middleware.require_advisor_owner(role, row["advisor_code"])
    common.required_version(data, "expected_advisor_version")
    common.check_occ(row, "expected_advisor_version", data.get("expected_advisor_version"))
    return ok(advisor_service.serialize(advisor_service.update(row, data)))


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@bp.post("/advisors/<advisor_id>/enrollment")
def enrollment(advisor_id):
    role = middleware.require_role("AdvisorOps")
    row = advisor_service.get_by_id_or_fail(advisor_id)
    middleware.require_advisor_owner(role, row["advisor_code"])
    return ok(advisor_service.serialize(lifecycle.enrollment(row, common.body())))


@bp.post("/advisors/<advisor_id>/affiliation")
def affiliation(advisor_id):
    role = middleware.require_role("AdvisorOps")
    row = advisor_service.get_by_id_or_fail(advisor_id)
    middleware.require_advisor_owner(role, row["advisor_code"])
    return ok(advisor_service.serialize(lifecycle.affiliation(row, common.body())))


@bp.post("/advisors/<advisor_id>/state")
def move_state(advisor_id):
    middleware.require_role("ComplianceOfficer")
    row = advisor_service.get_by_id_or_fail(advisor_id)
    return ok(advisor_service.serialize(lifecycle.move_state(row, common.body())))


@bp.post("/advisors/<advisor_id>/departure")
def departure(advisor_id):
    role = middleware.require_role("AdvisorOps")
    row = advisor_service.get_by_id_or_fail(advisor_id)
    middleware.require_advisor_owner(role, row["advisor_code"])
    return ok(advisor_service.serialize(lifecycle.departure(row, common.body())))


@bp.post("/advisors/<advisor_id>/departure/reinstate")
def departure_reinstate(advisor_id):
    role = middleware.require_role("AdvisorOps")
    row = advisor_service.get_by_id_or_fail(advisor_id)
    middleware.require_advisor_owner(role, row["advisor_code"])
    return ok(advisor_service.serialize(lifecycle.departure_reinstate(row, common.body())))


@bp.post("/advisors/<advisor_id>/departure/settle")
def departure_settle(advisor_id):
    middleware.require_role("ComplianceOfficer")
    row = advisor_service.get_by_id_or_fail(advisor_id)
    return ok(advisor_service.serialize(lifecycle.departure_settle(row, common.body())))


@bp.post("/advisors/<advisor_id>/book-transfer")
def book_transfer(advisor_id):
    role = middleware.require_role("AdvisorOps")
    row = advisor_service.get_by_id_or_fail(advisor_id)
    middleware.require_advisor_owner(role, row["advisor_code"])
    moved = lifecycle.book_transfer(row, common.body())
    return ok([advisor_service.serialize(item) for item in moved], response_type="array")


@bp.post("/advisors/<advisor_id>/crd-change")
def crd_change(advisor_id):
    middleware.require_role("PlatformAdmin", "ComplianceOfficer")
    row = advisor_service.get_by_id_or_fail(advisor_id)
    data = common.body()
    common.required_version(data, "expected_advisor_version")
    common.check_occ(row, "expected_advisor_version", data.get("expected_advisor_version"))
    return ok(advisor_service.serialize(advisor_service.crd_change(row, data)))


@bp.post("/advisors/bulk-import")
def bulk_import():
    role = middleware.require_role("PlatformAdmin", "AdvisorOps")
    if role == "AdvisorOps":
        middleware.require_advisor_owner(role, None)
    return ok(advisor_service.bulk_import(common.body()))


# ---------------------------------------------------------------------------
# Payout lines
# ---------------------------------------------------------------------------

@bp.post("/advisors/<advisor_id>/payout-lines")
def create_line(advisor_id):
    role = middleware.require_role("AdvisorOps", "BranchManager")
    row = advisor_service.get_by_id_or_fail(advisor_id)
    middleware.require_advisor_owner(role, row["advisor_code"])
    return ok(period_service.serialize(period_service.create_line(row, common.body())), status=201)


@bp.get("/advisor-payout-lines")
def list_lines():
    middleware.require_role("AdvisorOps", "BranchManager", "ComplianceOfficer", "PlatformAdmin")
    from db import advisor_payout_lines
    args = flask.request.args
    limit, offset = common.pagination_params()
    rows = [row for row in advisor_payout_lines.values()
            if (args.get("payout_period_id") is None
                or row["payout_period_id"] == args.get("payout_period_id"))
            and (args.get("advisor_code") is None or row["advisor_code"] == args.get("advisor_code"))
            and (args.get("status") is None or row["status"] == args.get("status"))]
    page, total = common.page(rows, limit, offset)
    return ok_list([period_service.serialize(row) for row in page], total, limit, offset)


@bp.get("/advisor-payout-lines/<line_id>")
def get_line(line_id):
    middleware.require_role("AdvisorOps", "BranchManager", "ComplianceOfficer", "PlatformAdmin")
    return ok(period_service.serialize(period_service.find_line_or_fail(line_id)))


@bp.post("/advisor-payout-lines/<line_id>/settlement")
def settle_line(line_id):
    middleware.require_role("BranchManager", "AdvisorOps")
    row = period_service.find_line_or_fail(line_id)
    advisor = advisor_service.get_by_code_or_fail(row["advisor_code"])
    return ok(period_service.serialize(period_service.settle_line(advisor, row, common.body())))