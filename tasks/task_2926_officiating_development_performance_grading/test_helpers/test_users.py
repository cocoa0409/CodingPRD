"""Caller identities for every departmental role the PRD declares.

`X-User-ID` is an opaque operator identifier for seven of the eight roles, so a
shared constant is the canonical form for those. For the `Official` role
`X-User-ID` is the id of the acting Official row, so ownership-gated calls must
use `make_official_headers(official["id"])`.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Named operator identifiers. The grading supervisor who authors a grade and the
# supervisor who adjudicates the appeal against it must be different people.
DIRECTOR_USER_ID = "dir-1"
SCHEDULER_USER_ID = "sched-1"
GRADER_USER_ID = "sup-grader-1"
APPEAL_REVIEWER_USER_ID = "sup-review-2"
EVALUATOR_USER_ID = "eval-1"
EVALUATOR_2_USER_ID = "eval-2"
EVALUATOR_3_USER_ID = "eval-3"
REPLAY_OFFICIAL_USER_ID = "replay-1"
TRAINING_COORDINATOR_USER_ID = "train-1"
COMMUNICATIONS_USER_ID = "comms-1"

# A placeholder Official identity, safe only for calls whose outcome does not
# depend on the caller owning the subject resource.
PLACEHOLDER_OFFICIAL_USER_ID = "test-official-1"

UNDECLARED_ROLE = "LeagueIntern"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "director_headers": build_user_headers(DIRECTOR_USER_ID, "OfficiatingDirector"),
    "scheduler_headers": build_user_headers(SCHEDULER_USER_ID, "CrewScheduler"),
    "grader_headers": build_user_headers(GRADER_USER_ID, "GradingSupervisor"),
    "appeal_reviewer_headers": build_user_headers(
        APPEAL_REVIEWER_USER_ID, "GradingSupervisor"
    ),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "official_headers": build_user_headers(PLACEHOLDER_OFFICIAL_USER_ID, "Official"),
    "field_evaluator_headers": build_user_headers(EVALUATOR_USER_ID, "FieldEvaluator"),
    "field_evaluator_2_headers": build_user_headers(
        EVALUATOR_2_USER_ID, "FieldEvaluator"
    ),
    "field_evaluator_3_headers": build_user_headers(
        EVALUATOR_3_USER_ID, "FieldEvaluator"
    ),
    "replay_official_headers": build_user_headers(
        REPLAY_OFFICIAL_USER_ID, "ReplayOfficial"
    ),
    "training_coordinator_headers": build_user_headers(
        TRAINING_COORDINATOR_USER_ID, "TrainingCoordinator"
    ),
    "communications_headers": build_user_headers(
        COMMUNICATIONS_USER_ID, "CommunicationsOfficer"
    ),
}

# One reader identity per declared role, keyed by the role name.
READER_HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    "OfficiatingDirector": TEST_USERS["director_headers"],
    "CrewScheduler": TEST_USERS["scheduler_headers"],
    "GradingSupervisor": TEST_USERS["grader_headers"],
    "Official": TEST_USERS["official_headers"],
    "FieldEvaluator": TEST_USERS["field_evaluator_headers"],
    "ReplayOfficial": TEST_USERS["replay_official_headers"],
    "TrainingCoordinator": TEST_USERS["training_coordinator_headers"],
    "CommunicationsOfficer": TEST_USERS["communications_headers"],
}


def make_official_headers(official_id: str) -> Dict[str, str]:
    """For the `Official` role, whose `X-User-ID` is the id of the acting Official
    row. Pass the actual official's `id` on any ownership-gated call."""
    return build_user_headers(official_id, "Official")


def make_grading_supervisor_headers(user_id: str) -> Dict[str, str]:
    """A `GradingSupervisor` identity under a caller-chosen operator identifier,
    for exercising the segregation-of-duties rule."""
    return build_user_headers(user_id, "GradingSupervisor")


def make_field_evaluator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "FieldEvaluator")


def make_role_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identity/role pair, including undeclared role names."""
    return build_user_headers(user_id, role)


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """Both headers present, but `X-User-ID` carries the empty string."""
    return build_user_headers("", role)


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    """Both headers present, but `X-User-Role` carries the empty string."""
    return build_user_headers(user_id, "")


def headers_without_user_id(role: str) -> Dict[str, str]:
    """`X-User-ID` absent entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """`X-User-Role` absent entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
