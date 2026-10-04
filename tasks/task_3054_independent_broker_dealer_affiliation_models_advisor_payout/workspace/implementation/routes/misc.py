"""Clock, branch, supervisor-enrollment and advisor-link routes."""

import flask

import middleware
from db import branches, clock_value, set_clock
from errors import ApiError, fail
from response import ok, ok_list
from services import branches as branch_service
from services import common


bp = flask.Blueprint("misc", __name__)


# ---------------------------------------------------------------------------
# POST /_clock/set_current_utc  (PlatformAdmin)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_current_utc():
    middleware.require_role("PlatformAdmin")
    data = common.body()
    current_utc = common.require_field(data, "current_utc")
    set_clock(str(current_utc))
    return ok({"current_utc": clock_value()})


# ---------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------

@bp.post("/branches")
def create_branch():
    middleware.require_role("PlatformAdmin")
    row = branch_service.create(common.body())
    return ok(branch_service.serialize(row), status=201)


@bp.get("/branches")
def list_branches():
    middleware.require_role("PlatformAdmin", "BranchManager", "ComplianceOfficer")
    limit, offset = common.pagination_params()
    status = flask.request.args.get("status")
    rows = [row for row in branches.values() if status is None or row["status"] == status]
    page, total = common.page(rows, limit, offset)
    return ok_list([branch_service.serialize(row) for row in page], total, limit, offset)


@bp.get("/branches/<branch_id>")
def get_branch(branch_id):
    middleware.require_role(*middleware.ANY)
    row = branch_service.get_by_id_or_fail(branch_id)
    return ok(branch_service.serialize(row))


@bp.patch("/branches/<branch_id>")
def patch_branch(branch_id):
    middleware.require_role("PlatformAdmin")
    data = common.body()
    row = branch_service.get_by_id_or_fail(branch_id)
    common.required_version(data, "expected_branch_version")
    common.check_occ(row, "expected_branch_version", data.get("expected_branch_version"))
    return ok(branch_service.serialize(branch_service.update(row, data)))


@bp.get("/branches/<branch_id>/advisor-links")
def list_branch_links(branch_id):
    middleware.require_role(*middleware.ANY)
    from db import advisor_branch_links
    row = branch_service.get_by_id_or_fail(branch_id)
    limit, offset = common.pagination_params()
    rows = [link for link in advisor_branch_links.values() if link["branch_code"] == row["branch_code"]]
    page, total = common.page(rows, limit, offset)
    return ok_list([branch_service.serialize(item) for item in page], total, limit, offset)


@bp.get("/branches/<branch_id>/payout-periods")
def list_branch_periods(branch_id):
    middleware.require_role(*middleware.ANY)
    from db import payout_periods
    row = branch_service.get_by_id_or_fail(branch_id)
    limit, offset = common.pagination_params()
    rows = [period for period in payout_periods.values() if period["branch_code"] == row["branch_code"]]
    page, total = common.page(rows, limit, offset)
    return ok_list([branch_service.serialize(item) for item in page], total, limit, offset)


@bp.get("/branches/<branch_id>/supervisor-enrollments")
def list_branch_enrollments(branch_id):
    middleware.require_role("PlatformAdmin", "BranchManager", "ComplianceOfficer")
    row = branch_service.get_by_id_or_fail(branch_id)
    limit, offset = common.pagination_params()
    rows = branch_service.branch_supervisor_enrollments_of(row["branch_code"])
    page, total = common.page(rows, limit, offset)
    return ok_list([branch_service.serialize(item) for item in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Supervisory enrollments
# ---------------------------------------------------------------------------

@bp.post("/branch-supervisor-enrollments")
def create_enrollment():
    middleware.require_role("PlatformAdmin", "BranchManager")
    row = branch_service.create_enrollment(common.body())
    return ok(branch_service.serialize(row), status=201)


@bp.post("/branch-supervisor-enrollments/<enrollment_id>/state")
def move_enrollment_state(enrollment_id):
    middleware.require_role("PlatformAdmin", "BranchManager")
    data = common.body()
    row = branch_service.find_enrollment_or_fail(enrollment_id)
    branch = branch_service.get_by_code_or_fail(row["branch_code"])
    common.required_version(data, "expected_branch_version")
    common.check_occ(branch, "expected_branch_version", data.get("expected_branch_version"))
    updated = branch_service.move_enrollment_state(row, common.require_field(data, "to_status"))
    return ok(branch_service.serialize(updated))


# ---------------------------------------------------------------------------
# Advisor links
# ---------------------------------------------------------------------------

@bp.get("/advisor-links")
def list_links():
    middleware.require_role(*middleware.ANY)
    from db import advisor_branch_links
    limit, offset = common.pagination_params()
    args = flask.request.args
    rows = [row for row in advisor_branch_links.values()
            if (args.get("advisor_code") is None or row["advisor_code"] == args.get("advisor_code"))
            and (args.get("branch_code") is None or row["branch_code"] == args.get("branch_code"))
            and (args.get("status") is None or row["status"] == args.get("status"))]
    page, total = common.page(rows, limit, offset)
    return ok_list([branch_service.serialize(row) for row in page], total, limit, offset)


@bp.get("/advisor-links/<link_id>")
def get_link(link_id):
    middleware.require_role(*middleware.ANY)
    return ok(branch_service.serialize(branch_service.find_link_or_fail(link_id)))


@bp.post("/advisor-links")
def create_link():
    role = middleware.require_role("AdvisorOps", "BranchManager", "PlatformAdmin")
    data = common.body()
    advisor_code = common.require_field(data, "advisor_code")
    middleware.require_advisor_owner(role, advisor_code)
    row = branch_service.create_link(data)
    return ok(branch_service.serialize(row), status=201)


@bp.post("/advisor-links/<link_id>/state")
def move_link_state(link_id):
    role = middleware.require_role("AdvisorOps", "BranchManager", "PlatformAdmin")
    data = common.body()
    row = branch_service.find_link_or_fail(link_id)
    middleware.require_advisor_owner(role, row["advisor_code"])
    branch = branch_service.get_by_code_or_fail(row["branch_code"])
    common.required_version(data, "expected_branch_version")
    common.check_occ(branch, "expected_branch_version", data.get("expected_branch_version"))
    updated = branch_service.move_link_state(row, common.require_field(data, "to_status"))
    return ok(branch_service.serialize(updated))