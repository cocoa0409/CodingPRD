"""Branch, advisor-link and supervisory-enrollment services."""

from db import (advisor_branch_links, advisors, branches, iso_now, new_id,
                next_created_seq, payout_periods)
from errors import fail
from services import common


def serialize(row):
    """Public projection: every declared field, no internal bookkeeping."""
    return {key: value for key, value in row.items() if not key.startswith("_")}


def find_by_code(branch_code):
    for row in branches.values():
        if row["branch_code"] == branch_code:
            return row
    return None


def find_by_id(branch_id):
    return branches.get(branch_id)


def get_by_code_or_fail(branch_code):
    row = find_by_code(branch_code)
    if row is None:
        fail("ERR_BRANCH_NOT_FOUND")
    return row


def get_by_id_or_fail(branch_id):
    """A branch addressed by a server-minted id.

    An identifier that does not allocate is looked for by code as well, so a
    caller who addressed a branch in business terms still learns the branch is
    missing rather than getting the generic not-found error.
    """
    row = find_by_id(branch_id) or find_by_code(branch_id)
    if row is None:
        fail("ERR_BRANCH_NOT_FOUND")
    return row


def require_unique_code(branch_code):
    if find_by_code(branch_code) is not None:
        fail("ERR_INVALID_REQUEST", "branch_code is already in use.")


def require_unique_transmittal(transmittal_account):
    for row in branches.values():
        if row["transmittal_account"] == transmittal_account:
            fail("ERR_INVALID_REQUEST", "transmittal_account is already in use.")


def create(data):
    branch_code = common.require_field(data, "branch_code")
    name = common.require_field(data, "name")
    transmittal_account = common.require_field(data, "transmittal_account")
    osj_name = common.require_field(data, "osj_name")
    require_unique_code(branch_code)
    require_unique_transmittal(transmittal_account)
    row = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "branch_code": branch_code,
        "name": name,
        "transmittal_account": transmittal_account,
        "osj_name": osj_name,
        "osj_enabled": False,
        "state": "UNSUPERVISED",
        "status": "DRAFT",
        "supervising_advisor_count": 0,
        "current_payout_period_id": None,
    }
    branches[row["id"]] = row
    return row


def update(branch, data):
    if "name" in data and data["name"] is not None:
        branch["name"] = data["name"]
    if "osj_name" in data and data["osj_name"] is not None:
        branch["osj_name"] = data["osj_name"]
    common.touch(branch)
    return branch


def recompute_supervising_count(branch):
    count = 0
    for link in advisor_branch_links.values():
        if link["branch_code"] == branch["branch_code"] and link["is_supervisor"] and link["status"] == "ASSIGNED":
            count += 1
    branch["supervising_advisor_count"] = count
    return count


def has_active_supervision(branch):
    """An ENROLLED supervisor enrollment or an ASSIGNED supervisor link."""
    for enrollment in branch_supervisor_enrollments_of(branch["branch_code"]):
        if enrollment["status"] == "ENROLLED":
            return True
    for link in advisor_branch_links.values():
        if link["branch_code"] == branch["branch_code"] and link["is_supervisor"] \
                and link["status"] == "ASSIGNED":
            return True
    return False


def branch_supervisor_enrollments_of(branch_code):
    from db import branch_supervisor_enrollments
    return [row for row in branch_supervisor_enrollments.values()
            if row["branch_code"] == branch_code]


def open_periods_of(branch_code):
    return [row for row in payout_periods.values()
            if row["branch_code"] == branch_code and row["state"] in ("OPEN", "REOPENED")]


def escalate(branch):
    branch["state"] = "SUPERVISED"
    branch["osj_enabled"] = True
    branch["status"] = "ACTIVE"
    recompute_supervising_count(branch)
    common.touch(branch)


def demote(branch):
    branch["state"] = "UNSUPERVISED"
    branch["osj_enabled"] = False
    branch["status"] = "DRAFT"
    branch["supervising_advisor_count"] = 0
    common.touch(branch)


def refresh_supervision(branch):
    """Re-derive state from the supervisor evidence after a link/enrollment move.

    Two guards, evaluated in the order of PRD 3.7: first the branch must have no
    enrolled supervisor enrollment and no assigned supervisor link left; only
    once it is genuinely at zero supervisors does an open or reopened period
    block the demotion.
    """
    common.touch(branch)
    if has_active_supervision(branch):
        branch["state"] = "SUPERVISED"
        branch["osj_enabled"] = True
        branch["status"] = "ACTIVE"
        recompute_supervising_count(branch)
        return branch
    if open_periods_of(branch["branch_code"]):
        fail("ERR_PERIOD_NOT_CLOSED")
    demote(branch)
    return branch


def is_supervised(branch):
    return branch["state"] == "SUPERVISED"


# ---------------------------------------------------------------------------
# AdvisorBranchLink (parent: Advisor)
# ---------------------------------------------------------------------------

def create_link(data):
    advisor_code = common.require_field(data, "advisor_code")
    branch_code = common.require_field(data, "branch_code")
    advisor = find_advisor_or_fail(advisor_code)
    branch = get_by_code_or_fail(branch_code)
    assignment_type = data.get("assignment_type")
    if assignment_type not in ("PRIMARY", "SECONDARY"):
        fail("ERR_INVALID_REQUEST", "assignment_type must be PRIMARY or SECONDARY.")
    is_supervisor = bool(data.get("is_supervisor", False))
    row = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "advisor_code": advisor_code,
        "branch_code": branch_code,
        "is_supervisor": is_supervisor,
        "assignment_type": assignment_type,
        "status": "ASSIGNED",
    }
    advisor_branch_links[row["id"]] = row
    refresh_supervision(branch)
    _ = advisor
    return row


def find_link_or_fail(link_id):
    row = advisor_branch_links.get(link_id)
    if row is None:
        fail("ERR_NOT_FOUND")
    return row


def move_link_state(link, to_status):
    if to_status not in ("ASSIGNED", "INACTIVE"):
        fail("ERR_INVALID_REQUEST", "to_status must be ASSIGNED or INACTIVE.")
    if link["status"] == to_status:
        fail("ERR_INVALID_STATE")
    link["status"] = to_status
    common.touch(link)
    refresh_supervision(get_by_code_or_fail(link["branch_code"]))
    return link


# ---------------------------------------------------------------------------
# BranchSupervisorEnrollment (parent: Branch)
# ---------------------------------------------------------------------------

def create_enrollment(data):
    branch_code = common.require_field(data, "branch_code")
    advisor_code = common.require_field(data, "advisor_code")
    effective_date = common.require_field(data, "effective_date")
    get_by_code_or_fail(branch_code)
    find_advisor_or_fail(advisor_code)
    row = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "branch_code": branch_code,
        "advisor_code": advisor_code,
        "effective_date": effective_date,
        "status": "REQUESTED",
    }
    from db import branch_supervisor_enrollments
    branch_supervisor_enrollments[row["id"]] = row
    return row


def find_enrollment_or_fail(enrollment_id):
    from db import branch_supervisor_enrollments
    row = branch_supervisor_enrollments.get(enrollment_id)
    if row is None:
        fail("ERR_NOT_FOUND")
    return row


def move_enrollment_state(enrollment, to_status):
    if to_status not in ("REQUESTED", "ENROLLED", "REVOKED"):
        fail("ERR_INVALID_REQUEST", "to_status must be REQUESTED, ENROLLED or REVOKED.")
    branch = get_by_code_or_fail(enrollment["branch_code"])
    if to_status == "ENROLLED":
        if enrollment["status"] != "REQUESTED":
            fail("ERR_INVALID_STATE")
        from db import branch_supervisor_enrollments
        for other in branch_supervisor_enrollments.values():
            if other["id"] != enrollment["id"] and other["branch_code"] == branch["branch_code"] \
                    and other["status"] == "ENROLLED":
                fail("ERR_INVALID_STATE")
        enrollment["status"] = "ENROLLED"
        common.touch(enrollment)
        escalate(branch)
        return enrollment
    if to_status == "REVOKED":
        if enrollment["status"] not in ("REQUESTED", "ENROLLED"):
            fail("ERR_INVALID_STATE")
        enrollment["status"] = "REVOKED"
        common.touch(enrollment)
        refresh_supervision(branch)
        return enrollment
    fail("ERR_INVALID_STATE")


def find_advisor_or_fail(advisor_code):
    from services import advisors as advisor_service
    return advisor_service.get_by_code_or_fail(advisor_code)