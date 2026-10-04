"""Pre-built role headers for every role named in PRD §2.1.

``Learner`` is the only entity-backed role: ``X-User-ID`` must be the ``id`` of a
real ``Learner`` row, so ownership-gated calls use ``make_learner_headers`` with
the entity's own id.  The other three roles are opaque operator identifiers and
their shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles, and for learner calls that do not
# exercise ownership.  ``learner_headers`` is a fallback only; see the builder.
TEST_USERS = {
    "learner_headers": build_user_headers("test-learner-1", "Learner"),
    "proctor_headers": build_user_headers("proctor-1", "CertificationProctor"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
}


def make_learner_headers(learner_id: str) -> dict:
    """Headers for the Learner role, acting as the learner with this id.

    Pass the actual ``Learner.id`` whenever the call is ownership-gated — a
    practice attempt, a review, a streak repair, a placement read or write, a
    subscription write, or an exam action.
    """
    return build_user_headers(learner_id, "Learner")


def make_proctor_headers(operator_id: str = "proctor-1") -> dict:
    """Headers for the CertificationProctor role (opaque operator id)."""
    return build_user_headers(operator_id, "CertificationProctor")


def make_admin_headers(operator_id: str = "test-admin-1") -> dict:
    """Headers for the PlatformAdmin role (opaque operator id)."""
    return build_user_headers(operator_id, "PlatformAdmin")