# routes/reassignments.py — backlog-driven administrative reassignment of
# non-detained cases out of backlog-critical courts (PRD §3.7).
import uuid

from flask import Blueprint

import db
from auth import get_auth, require_role
from computed import (serialize_reassignment, court_pending_count,
                      court_backlog_critical)
from constants import (ROLE_COURT_ADMINISTRATOR, CASE_FILED, CASE_COMPLETED,
                       CUSTODY_DETAINED, REASSIGN_REASON)
from envelope import success, list_response
from errors import ApiError
from inputs import (get_body, req_str, req_version, fk, pagination_params,
                    filter_param, sorted_page)
from scheduling import cancel_scheduled_hearings_of_case

bp = Blueprint("reassignments", __name__)


def _select_destination(case):
    """calculations.reassignment_target_selector: every court other than the
    current one whose pending_case_count is strictly below its
    annual_completion_goal; ranked by load_ratio ASC with EXACT rational
    comparison (pending*other.goal vs other.pending*goal), tie-break
    created_at ASC. Empty pool -> ERR_NO_ELIGIBLE_COURT."""
    candidates = []
    for c in db.courts.values():
        if c["id"] == case["court_id"]:
            continue
        pending = court_pending_count(c["id"])
        if pending < c["annual_completion_goal"]:
            candidates.append((pending, c["annual_completion_goal"],
                               c["created_at"], c["_seq"], c))
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_COURT",
                       "Every other court is at or above its completion goal")

    from functools import cmp_to_key

    def cmp(a, b):
        pa, ga, _, sa, _ = a
        pb, gb, _, sb, _ = b
        lhs = pa * gb
        rhs = pb * ga
        if lhs != rhs:
            return -1 if lhs < rhs else 1
        if sa != sb:
            return -1 if sa < sb else 1
        return 0

    candidates.sort(key=cmp_to_key(cmp))
    return candidates[0][4]


@bp.post("/case-reassignments")
def create_reassignment():
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    body = get_body()
    # ---- tier 3: body FKs in declared input order (case_id) ----
    case_id = fk(body, "case_id")
    case = db.cases.get(case_id) if case_id is not None else None
    if case_id is not None and case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Case id does not exist")
    if case is not None:
        # ---- tier 5: case terminality ----
        if case["status"] == CASE_COMPLETED:
            raise ApiError("ERR_CASE_ALREADY_TERMINAL",
                           "Case has reached COMPLETED")
        # ---- tier 9: detained cases stay with the detaining court; the
        # source court must be backlog-critical at execution time ----
        if case["custody_status"] == CUSTODY_DETAINED:
            raise ApiError("ERR_DETAINED_NOT_REASSIGNABLE",
                           "Detained cases may not be reassigned")
        source = db.courts[case["court_id"]]
        if not court_backlog_critical(source):
            raise ApiError("ERR_COURT_NOT_BACKLOG_CRITICAL",
                           "The case's current court is not backlog-critical")
    # ---- tier 10: shape, then the destination selector (semantic) ----
    case_id = req_str(body, "case_id")
    case = db.cases.get(case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Case id does not exist")
    expected_version = req_version(body, "expected_case_version")
    destination = _select_destination(case)
    # ---- tier 11: OCC, immediately before commit ----
    if expected_version != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION",
                       "expected_case_version does not equal the case's "
                       "current version")
    # ---- commit: immutable ledger record + the venue-motion-style reset ----
    record = {
        "id": str(uuid.uuid4()),
        "case_id": case["id"],
        "from_court_id": case["court_id"],
        "to_court_id": destination["id"],
        "reason": REASSIGN_REASON,
        "executed_at": db.get_clock(),
    }
    db.stamp_new(record)
    db.reassignments[record["id"]] = record
    case["court_id"] = destination["id"]
    case["assigned_judge_id"] = None
    case["status"] = CASE_FILED
    cancel_scheduled_hearings_of_case(case["id"])
    db.touch(case)  # increments Case.version by 1
    # both courts' pending counts and backlog flags recompute live (PRD §2.9)
    return success(serialize_reassignment(record), response_type="object",
                   status=201)


@bp.get("/case-reassignments")
def list_reassignments():
    get_auth()  # all roles
    limit, offset = pagination_params()
    records = list(db.reassignments.values())
    for name in ("case_id", "from_court_id", "to_court_id"):
        v = filter_param(name)
        if v is not None:
            records = [r for r in records if r.get(name) == v]
    page, total = sorted_page(records, limit, offset)
    return list_response([serialize_reassignment(r) for r in page], total,
                         limit, offset)


@bp.get("/case-reassignments/<reassignmentId>")
def get_reassignment(reassignmentId):
    get_auth()  # all roles
    record = db.reassignments.get(reassignmentId)
    if record is None:
        # generic 404 for CaseReassignment references (PRD §2.6 tier 3)
        raise ApiError("ERR_NOT_FOUND", "CaseReassignment id does not exist")
    return success(serialize_reassignment(record), response_type="object",
                   status=200)
