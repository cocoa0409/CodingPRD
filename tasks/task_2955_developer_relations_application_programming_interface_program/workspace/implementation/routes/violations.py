"""Violation cases: opening, investigation, adjudication and appeal."""
from flask import Blueprint

from constants import (
    CASE_OUTCOMES,
    CASE_STATES,
    ROLE_DEVELOPER,
    ROLE_PLATFORM_ADMIN,
    ROLE_TRUST_SAFETY,
    SEVERITIES_LMH,
    VIOLATION_CATEGORIES,
)
from db import new_id, store
from errors import ApiError
from middleware import (
    acting_user,
    endpoint,
    lookup,
    require_not_revoked,
    require_owner,
)
from response import (
    array_response,
    enum_filter,
    object_response,
    pagination,
    string_filter,
)
from serializers import violation_case_out
from services import enforcement
from validation import body

bp = Blueprint("violations", __name__)


def _case(case_id):
    return lookup(store.violation_cases, case_id, "ERR_VIOLATION_CASE_NOT_FOUND")


def _check_evidence(developer_id, window_ids):
    for window_id in window_ids:
        if window_id not in store.usage_windows:
            raise ApiError(
                "ERR_USAGE_WINDOW_NOT_FOUND",
                "Cited usage window %s does not exist." % window_id,
            )
    if not enforcement.evidence_windows_attributable(developer_id, window_ids):
        raise ApiError(
            "ERR_EVIDENCE_NOT_ATTRIBUTABLE",
            "Every cited usage window must belong to an entitlement of this developer.",
        )


def _developer_snapshot(developer):
    return (
        developer["violation_points"],
        developer["standing"],
        developer["directory_state"],
    )


@bp.post("/violation-cases")
@endpoint([ROLE_TRUST_SAFETY])
def open_case():
    payload = body()
    developer_id = payload.string("developer_id", min_len=1)
    assignment_id = payload.string("quota_assignment_id", required=False)
    category = payload.string("category", choices=VIOLATION_CATEGORIES)
    severity = payload.string("severity", choices=SEVERITIES_LMH)
    summary = payload.string("summary", min_len=10, max_len=500)
    evidence = payload.string_array("evidence_window_ids", required=False, max_items=100)

    developer = lookup(store.developers, developer_id, "ERR_DEVELOPER_NOT_FOUND")
    if assignment_id is not None:
        lookup(
            store.quota_assignments, assignment_id, "ERR_QUOTA_ASSIGNMENT_NOT_FOUND"
        )
    if evidence:
        _check_evidence(developer["id"], evidence)

    case = {
        "id": new_id(),
        "developer_id": developer["id"],
        "quota_assignment_id": assignment_id,
        "category": category,
        "severity": severity,
        "summary": summary,
        "evidence_window_ids": list(evidence) if evidence is not None else [],
        "state": "OPENED",
        "penalty_points": enforcement.penalty_points_for(category, severity),
        "points_applied": 0,
        "opened_by_user_id": acting_user(),
        "investigator_user_id": None,
        "adjudicator_user_id": None,
        "remediation_deadline": None,
        "appeal_deadline": None,
        "outcome": None,
        "appeal_reason": None,
        "appeal_count": 0,
        "decision_note": None,
    }
    store.stamp_new(case)
    store.violation_cases[case["id"]] = case
    return object_response(violation_case_out(case), 201)


@bp.get("/violation-cases/<case_id>")
@endpoint([ROLE_DEVELOPER, ROLE_TRUST_SAFETY, ROLE_PLATFORM_ADMIN])
def read_case(case_id):
    case = _case(case_id)
    require_owner(case["developer_id"])
    return object_response(violation_case_out(case))


@bp.get("/violation-cases")
@endpoint([ROLE_DEVELOPER, ROLE_TRUST_SAFETY, ROLE_PLATFORM_ADMIN])
def list_cases():
    limit, offset = pagination()
    developer_id = string_filter("developer_id")
    assignment_id = string_filter("quota_assignment_id")
    state = enum_filter("state", CASE_STATES)

    records = store.ordered(store.violation_cases)
    if developer_id is not None:
        records = [r for r in records if r["developer_id"] == developer_id]
    if assignment_id is not None:
        records = [r for r in records if r["quota_assignment_id"] == assignment_id]
    if state is not None:
        records = [r for r in records if r["state"] == state]

    total = len(records)
    page = records[offset : offset + limit]
    return array_response([violation_case_out(r) for r in page], total, limit, offset)


@bp.post("/violation-cases/<case_id>/investigate")
@endpoint([ROLE_TRUST_SAFETY])
def investigate_case(case_id):
    payload = body()
    evidence = payload.string_array("evidence_window_ids", required=False, max_items=100)

    case = _case(case_id)

    if case["state"] != "OPENED":
        raise ApiError(
            "ERR_CASE_STATE_INVALID",
            "Only an OPENED case may be investigated; state is %s." % case["state"],
        )

    if evidence:
        _check_evidence(case["developer_id"], evidence)
        cited = list(case["evidence_window_ids"] or [])
        for window_id in evidence:
            if window_id not in cited:
                cited.append(window_id)
        case["evidence_window_ids"] = cited

    case["state"] = "INVESTIGATING"
    case["investigator_user_id"] = acting_user()
    case["remediation_deadline"] = enforcement.remediation_deadline(case["severity"])
    store.touch(case)

    developer = store.developers[case["developer_id"]]
    if developer["standing"] == "GOOD_STANDING":
        developer["standing"] = "UNDER_REVIEW"
        store.touch(developer)

    return object_response(violation_case_out(case))


@bp.post("/violation-cases/<case_id>/adjudicate")
@endpoint([ROLE_PLATFORM_ADMIN])
def adjudicate_case(case_id):
    payload = body()
    outcome = payload.string("outcome", choices=CASE_OUTCOMES)
    note = payload.string("decision_note", min_len=1)

    case = _case(case_id)

    if case["state"] not in ("INVESTIGATING", "APPEALED"):
        raise ApiError(
            "ERR_CASE_STATE_INVALID",
            "Only an INVESTIGATING or APPEALED case may be adjudicated; state is %s."
            % case["state"],
        )

    if (
        case["investigator_user_id"] is not None
        and case["investigator_user_id"] == acting_user()
    ):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The adjudicating operator may not be the recorded investigator.",
        )

    developer = store.developers[case["developer_id"]]
    before = _developer_snapshot(developer)
    origin = case["state"]

    case["adjudicator_user_id"] = acting_user()
    case["outcome"] = outcome
    case["decision_note"] = note
    case["penalty_points"] = enforcement.penalty_points_for(
        case["category"], case["severity"]
    )

    if outcome == "UPHELD":
        case["state"] = "UPHELD"
        if origin == "INVESTIGATING":
            enforcement.apply_upheld(case, developer)
        # an appealed case upheld again keeps the points and the deadline
    else:
        case["state"] = "DISMISSED"
        enforcement.apply_dismissed(case, developer)

    store.touch(case)
    if _developer_snapshot(developer) != before:
        store.touch(developer)

    return object_response(violation_case_out(case))


@bp.post("/violation-cases/<case_id>/appeal")
@endpoint([ROLE_DEVELOPER])
def appeal_case(case_id):
    payload = body()
    reason = payload.string("appeal_reason", min_len=1)

    case = _case(case_id)
    require_owner(case["developer_id"])

    if case["state"] != "UPHELD":
        raise ApiError(
            "ERR_CASE_STATE_INVALID",
            "Only an UPHELD case may be appealed; state is %s." % case["state"],
        )

    require_not_revoked()

    if case["appeal_deadline"] is None or store.now() > case["appeal_deadline"]:
        raise ApiError(
            "ERR_APPEAL_WINDOW_CLOSED",
            "The appeal window for this case has closed.",
        )
    if case["appeal_count"] != 0:
        raise ApiError(
            "ERR_APPEAL_ALREADY_FILED",
            "An appeal has already been filed against this case.",
        )

    case["state"] = "APPEALED"
    case["appeal_reason"] = reason
    case["appeal_count"] = 1
    store.touch(case)
    return object_response(violation_case_out(case))
