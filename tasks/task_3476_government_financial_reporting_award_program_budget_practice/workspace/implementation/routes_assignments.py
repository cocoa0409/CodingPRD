"""Blind review assignments and findings (PRD 3.5).

Selector: ELIGIBLE, employer != submitting government, submitting government
not conflicted, open_assignment_count < 5, and no assignment for this
submission in ANY appeal round (any status excludes). Ranking: open ASC,
completed DESC, trained_at ASC, created_at ASC. Empty pool ->
ERR_NO_ELIGIBLE_REVIEWER. At most 3 active (OFFERED/ACCEPTED/SUBMITTED)
assignments per appeal round -> ERR_REVIEW_QUORUM_FULL.
"""

from clock import clock
from domain import (
    REQUIRED_FINDINGS_PER_ROUND,
    active_assignments_in_round,
    finding_weighted_score,
    findings_for_round,
    next_alias_seq,
    select_reviewer,
    weights_by_code,
)
from envelope import ok
from errors import api_error
from auth import authenticate, authorize
from listing import list_response
from serialize import review_assignment, review_finding
from store import store, new_id, touch
from validate import (
    SEVERITIES,
    get_body,
    opt_list,
    pagination,
    query_filter,
    req_list,
    req_str,
    score_decimal,
)


def _now():
    return clock.now_iso()


def create_assignment():
    uid, role = authenticate()
    body = get_body()
    submission_id = req_str(body, "submission_id")
    authorize(role, ["AwardsDirector"])
    s = store.report_submissions.get(submission_id)
    if s is None:
        raise api_error("ERR_SUBMISSION_NOT_FOUND", "report submission not found")
    # state gate (6)
    if s["status"] not in ("SUBMITTED", "APPEALED", "UNDER_REVIEW"):
        raise api_error(
            "ERR_SUBMISSION_STATE_INVALID",
            "assignments require a SUBMITTED, APPEALED or UNDER_REVIEW submission",
        )
    # selector (priority 7) runs before the quorum structural check (10)
    reviewer = select_reviewer(s)
    if reviewer is None:
        raise api_error("ERR_NO_ELIGIBLE_REVIEWER", "no eligible reviewer survives the blind filter")
    if active_assignments_in_round(s) >= REQUIRED_FINDINGS_PER_ROUND:
        raise api_error("ERR_REVIEW_QUORUM_FULL", "the round already seats three active assignments")
    now = _now()
    a = {
        "id": new_id(),
        "submission_id": s["id"],
        "reviewer_id": reviewer["id"],
        "reviewer_alias": "R%d-%d" % (s["appeal_round"], next_alias_seq(s)),
        "appeal_round": s["appeal_round"],
        "status": "OFFERED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.review_assignments[a["id"]] = a
    # reviewer.open_assignment_count is derived; the mutation still bumps the
    # reviewer's version (PRD 2.5 cascade rule)
    touch(reviewer, now)
    # the round's first assignment flips the submission into UNDER_REVIEW (and
    # only the first bumps the submission's version, PRD 3.5)
    if s["status"] in ("SUBMITTED", "APPEALED"):
        s["status"] = "UNDER_REVIEW"
        touch(s, now)
    return ok(review_assignment(a), 201)


def accept_assignment(assignment_id):
    uid, role = authenticate()
    get_body()
    authorize(role, ["Reviewer"])
    a = store.review_assignments.get(assignment_id)
    if a is None:
        raise api_error("ERR_ASSIGNMENT_NOT_FOUND", "review assignment not found")
    if a["reviewer_id"] != uid:
        raise api_error("ERR_NOT_RESOURCE_OWNER", "only the assigned reviewer may accept")
    if a["status"] != "OFFERED":
        raise api_error("ERR_ASSIGNMENT_STATE_INVALID", "accept requires status OFFERED")
    reviewer = store.reviewer_profiles[a["reviewer_id"]]
    if reviewer["status"] != "ELIGIBLE":
        raise api_error("ERR_REVIEWER_NOT_ELIGIBLE", "reviewer is not ELIGIBLE")
    now = _now()
    a["status"] = "ACCEPTED"
    touch(a, now)
    return ok(review_assignment(a))


def decline_assignment(assignment_id):
    uid, role = authenticate()
    get_body()
    authorize(role, ["Reviewer"])
    a = store.review_assignments.get(assignment_id)
    if a is None:
        raise api_error("ERR_ASSIGNMENT_NOT_FOUND", "review assignment not found")
    if a["reviewer_id"] != uid:
        raise api_error("ERR_NOT_RESOURCE_OWNER", "only the assigned reviewer may decline")
    if a["status"] != "OFFERED":
        raise api_error("ERR_ASSIGNMENT_STATE_INVALID", "decline requires status OFFERED")
    now = _now()
    a["status"] = "DECLINED"
    touch(a, now)
    # open_assignment_count declines / declined_assignment_count rises (both
    # derived); the reviewer record is mutated by the cascade, so bump it
    reviewer = store.reviewer_profiles[a["reviewer_id"]]
    touch(reviewer, now)
    return ok(review_assignment(a))


def _parse_criterion_scores(body):
    entries = req_list(body, "criterion_scores")
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise api_error("ERR_VALIDATION", "each criterion score must be an object")
        code = entry.get("criterion_code")
        if not isinstance(code, str) or not code:
            raise api_error("ERR_VALIDATION", "criterion_code must be a string")
        score = score_decimal(entry.get("score"))
        out.append({"criterion_code": code, "_score_decimal": score})
    return out


def _parse_comments(body):
    raw = opt_list(body, "comments")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise api_error("ERR_VALIDATION", "each comment must be an object")
        code = entry.get("criterion_code")
        if not isinstance(code, str) or not code:
            raise api_error("ERR_VALIDATION", "comment criterion_code must be a string")
        severity = entry.get("severity")
        if severity not in SEVERITIES:
            raise api_error("ERR_VALIDATION", "comment severity must be MAJOR or MINOR")
        text = entry.get("text")
        if not isinstance(text, str):
            raise api_error("ERR_VALIDATION", "comment text must be a string")
        out.append({"criterion_code": code, "severity": severity, "text": text})
    return out


def submit_finding(assignment_id):
    uid, role = authenticate()
    body = get_body()
    criterion_scores = _parse_criterion_scores(body)
    comments = _parse_comments(body)
    authorize(role, ["Reviewer"])
    a = store.review_assignments.get(assignment_id)
    if a is None:
        raise api_error("ERR_ASSIGNMENT_NOT_FOUND", "review assignment not found")
    if a["reviewer_id"] != uid:
        raise api_error("ERR_NOT_RESOURCE_OWNER", "only the assigned reviewer may file a finding")
    if a["status"] != "ACCEPTED":
        raise api_error("ERR_ASSIGNMENT_STATE_INVALID", "finding requires status ACCEPTED")
    reviewer = store.reviewer_profiles[a["reviewer_id"]]
    if reviewer["status"] != "ELIGIBLE":
        raise api_error("ERR_REVIEWER_NOT_ELIGIBLE", "reviewer is not ELIGIBLE")
    # structural (10): scores must cover exactly the pinned checklist's criteria
    s = store.report_submissions[a["submission_id"]]
    checklist = store.checklist_versions[s["pinned_checklist_version_id"]]
    weights = weights_by_code(checklist)
    seen = set()
    for entry in criterion_scores:
        if entry["criterion_code"] not in weights:
            raise api_error(
                "ERR_UNKNOWN_CRITERION",
                "criterion %s is absent from the pinned checklist" % entry["criterion_code"],
            )
        seen.add(entry["criterion_code"])
    missing = [code for code in weights if code not in seen]
    if missing:
        raise api_error(
            "ERR_CRITERION_SET_INCOMPLETE",
            "pinned checklist criteria left unscored: %s" % ", ".join(missing),
        )
    now = _now()
    f = {
        "id": new_id(),
        "assignment_id": a["id"],
        "appeal_round": a["appeal_round"],
        "criterion_scores": criterion_scores,
        "comments": comments,
        "weighted_score": finding_weighted_score(criterion_scores, checklist),
        "major_deficiency_count": sum(1 for c in comments if c["severity"] == "MAJOR"),
        "created_at": now,
        "_seq": store.next_seq(),
    }
    store.review_findings[f["id"]] = f
    # cascade link 1: assignment -> SUBMITTED; reviewer counters move (derived)
    a["status"] = "SUBMITTED"
    touch(a, now)
    touch(reviewer, now)
    # cascade link 2: submission provisional_score / major_deficiency_total are
    # recomputed on read; the record still bumps
    touch(s, now)
    # cascade link 3: third current-round finding -> DECISION_READY
    if len(findings_for_round(s["id"], s["appeal_round"])) == REQUIRED_FINDINGS_PER_ROUND:
        s["status"] = "DECISION_READY"
        cycle = store.award_cycles[s["cycle_id"]]
        cycle["decision_ready_count"] += 1
        touch(cycle, now)
    return ok(review_finding(f), 201)


def get_assignment(assignment_id):
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "AwardsDirector", "Reviewer", "GovernmentContact"])
    a = store.review_assignments.get(assignment_id)
    if a is None:
        raise api_error("ERR_ASSIGNMENT_NOT_FOUND", "review assignment not found")
    return ok(review_assignment(a, caller_role=role))


def list_assignments():
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "AwardsDirector", "Reviewer", "GovernmentContact"])
    limit, offset = pagination()
    rows = list(store.review_assignments.values())
    submission_id = query_filter("submission_id")
    if submission_id is not None:
        rows = [a for a in rows if a["submission_id"] == submission_id]
    reviewer_id = query_filter("reviewer_id")
    if reviewer_id is not None:
        rows = [a for a in rows if a["reviewer_id"] == reviewer_id]
    status = query_filter("status")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    appeal_round = query_filter("appeal_round")
    if appeal_round is not None:
        rows = [a for a in rows if str(a["appeal_round"]) == appeal_round]
    return list_response(
        rows, lambda a: review_assignment(a, caller_role=role), limit, offset
    )


def get_finding(finding_id):
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "AwardsDirector", "Reviewer", "GovernmentContact"])
    f = store.review_findings.get(finding_id)
    if f is None:
        raise api_error("ERR_FINDING_NOT_FOUND", "review finding not found")
    return ok(review_finding(f))


def list_findings():
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "AwardsDirector", "Reviewer", "GovernmentContact"])
    limit, offset = pagination()
    rows = list(store.review_findings.values())
    assignment_id = query_filter("assignment_id")
    if assignment_id is not None:
        rows = [f for f in rows if f["assignment_id"] == assignment_id]
    return list_response(rows, review_finding, limit, offset)


def register(app):
    app.add_url_rule("/gfoa/review-assignments", "create_assignment", create_assignment, methods=["POST"])
    app.add_url_rule("/gfoa/review-assignments", "list_assignments", list_assignments, methods=["GET"])
    app.add_url_rule("/gfoa/review-assignments/<assignment_id>", "get_assignment", get_assignment, methods=["GET"])
    app.add_url_rule("/gfoa/review-assignments/<assignment_id>/accept", "accept_assignment", accept_assignment, methods=["POST"])
    app.add_url_rule("/gfoa/review-assignments/<assignment_id>/decline", "decline_assignment", decline_assignment, methods=["POST"])
    app.add_url_rule("/gfoa/review-assignments/<assignment_id>/finding", "submit_finding", submit_finding, methods=["POST"])
    app.add_url_rule("/gfoa/review-findings/<finding_id>", "get_finding", get_finding, methods=["GET"])
    app.add_url_rule("/gfoa/review-findings", "list_findings", list_findings, methods=["GET"])
