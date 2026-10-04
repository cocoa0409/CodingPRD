"""Pre-built role headers for every role in the PRD (Section 2.1).

Two kinds of entries:

- ``TEST_USERS`` shared constants — safe for opaque roles (any staff role:
  the server never compares their X-User-ID to an entity id) and for tests
  that do not exercise ownership.
- ``make_<role>_headers(user_id)`` builders — the Applicant role is
  entity-backed: its X-User-ID MUST be the target Applicant's server-minted
  ``id`` on every ownership-gated call. Fixtures always build applicant
  headers from the created applicant's id, never from the shared constant.

Segregation of duties needs two DISTINCT LossVerifier user ids on the same
loan (the damage verifier of record vs the milestone decider); use
``fresh_staff_headers`` / ``make_loss_verifier_headers`` with distinct ids.
"""
import itertools

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

_counter = itertools.count(1)


def fresh_user_id(prefix: str) -> str:
    """A per-call unique opaque staff id, e.g. ``lv-dana-3``.

    Opaque staff ids are never compared to entity ids, but segregation tests
    require distinct verifier identities per scenario, so mint fresh ones.
    """
    return f"{prefix}-{next(_counter)}"


# --- Shared constants (opaque roles; non-ownership tests only) --------------
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-0", UserRole.ANONYMOUS.value),
    # Applicant is entity-backed: this shared constant is a fallback ONLY for
    # tests that never touch an ownership-gated resource.
    "applicant_headers": build_user_headers("applicant-0",
                                            UserRole.APPLICANT.value),
    "loan_officer_headers": build_user_headers("officer-0",
                                               UserRole.LOAN_OFFICER.value),
    "loss_verifier_headers": build_user_headers("lv-0",
                                                UserRole.LOSS_VERIFIER.value),
    "loan_approver_headers": build_user_headers("approver-0",
                                                UserRole.LOAN_APPROVER.value),
    "servicing_agent_headers": build_user_headers("servicing-0",
                                                  UserRole.SERVICING_AGENT.value),
    "grant_coordinator_headers": build_user_headers(
        "grants-0", UserRole.GRANT_COORDINATOR.value),
    "system_admin_headers": build_user_headers("admin-0",
                                               UserRole.SYSTEM_ADMIN.value),
}


# --- Per-instance builders -----------------------------------------------------
def make_anonymous_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.ANONYMOUS.value)


def make_applicant_headers(user_id: str) -> dict:
    """Applicant is entity-backed: pass the real Applicant.id as user_id
    whenever the call is ownership-gated (submit, accept, payments, ...)."""
    return build_user_headers(user_id, UserRole.APPLICANT.value)


def make_loan_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.LOAN_OFFICER.value)


def make_loss_verifier_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.LOSS_VERIFIER.value)


def make_loan_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.LOAN_APPROVER.value)


def make_servicing_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.SERVICING_AGENT.value)


def make_grant_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.GRANT_COORDINATOR.value)


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.SYSTEM_ADMIN.value)


def fresh_staff_headers() -> dict:
    """One freshly-minted header set per staff role for a new scenario.

    The two LossVerifier entries are guaranteed distinct so the milestone
    segregation-of-duties rule is satisfiable within one test.
    """
    return {
        "admin_headers": make_system_admin_headers(fresh_user_id("admin")),
        "officer_headers": make_loan_officer_headers(fresh_user_id("officer")),
        "verifier_headers": make_loss_verifier_headers(fresh_user_id("lv-dana")),
        "milestone_verifier_headers": make_loss_verifier_headers(
            fresh_user_id("lv-erin")),
        "approver_headers": make_loan_approver_headers(
            fresh_user_id("approver")),
        "servicing_headers": make_servicing_agent_headers(
            fresh_user_id("servicing")),
        "grant_coordinator_headers": make_grant_coordinator_headers(
            fresh_user_id("grants")),
    }
