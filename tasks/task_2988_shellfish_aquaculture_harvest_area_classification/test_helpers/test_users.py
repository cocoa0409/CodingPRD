"""Pre-built identity headers for every role the PRD defines (PRD §2.1).

`ShellfishControlAuthority`, `SitingReviewer` and `FarmOperator` carry opaque
identifiers that the server never compares to any record's `id`; the shared
constants below are therefore the canonical form for those three. Lease-scoped
ownership is an equality test against the `operator_user_id` recorded when the
lease was drafted, so a test that needs a *second, non-owning* operator must
use `make_farm_operator_headers()` with a different identifier.

`HatcheryOperator` and `SeafoodDealer` are backed by persisted records: their
`X-User-ID` must be the acting `Hatchery`'s / `Dealer`'s own `id`. Always build
those headers with `make_hatchery_operator_headers(hatchery["id"])` /
`make_seafood_dealer_headers(dealer["id"])`.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Canonical opaque identifiers used across the suite.
AUTHORITY_USER_ID = "authority-user-1"
REVIEWER_USER_ID = "siting-reviewer-1"
REVIEWER_B_USER_ID = "siting-reviewer-2"
OPERATOR_USER_ID = "farm-operator-1"
OPERATOR_B_USER_ID = "farm-operator-2"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "authority_headers": build_user_headers(
        AUTHORITY_USER_ID, UserRole.SHELLFISH_CONTROL_AUTHORITY.value
    ),
    "reviewer_headers": build_user_headers(
        REVIEWER_USER_ID, UserRole.SITING_REVIEWER.value
    ),
    "reviewer_b_headers": build_user_headers(
        REVIEWER_B_USER_ID, UserRole.SITING_REVIEWER.value
    ),
    "operator_headers": build_user_headers(
        OPERATOR_USER_ID, UserRole.FARM_OPERATOR.value
    ),
    "operator_b_headers": build_user_headers(
        OPERATOR_B_USER_ID, UserRole.FARM_OPERATOR.value
    ),
    # Record-backed roles — these shared constants are only safe for tests that
    # do not exercise ownership (missing-resource 404s, bad-payload 400s and
    # role-authorisation 403s). Use the per-instance builders otherwise.
    "hatchery_operator_headers": build_user_headers(
        "hatchery-operator-placeholder", UserRole.HATCHERY_OPERATOR.value
    ),
    "seafood_dealer_headers": build_user_headers(
        "seafood-dealer-placeholder", UserRole.SEAFOOD_DEALER.value
    ),
}


def make_authority_headers(user_id: str) -> dict:
    """Headers for `ShellfishControlAuthority` with an explicit opaque identifier."""
    return build_user_headers(user_id, UserRole.SHELLFISH_CONTROL_AUTHORITY.value)


def make_siting_reviewer_headers(user_id: str) -> dict:
    """Headers for `SitingReviewer`. The identifier is what segregation of duties
    compares against the sibling leg's recorded reviewer identity."""
    return build_user_headers(user_id, UserRole.SITING_REVIEWER.value)


def make_farm_operator_headers(user_id: str) -> dict:
    """Headers for `FarmOperator`. The identifier must equal the
    `operator_user_id` of the lease every lease-scoped write hangs from."""
    return build_user_headers(user_id, UserRole.FARM_OPERATOR.value)


def make_hatchery_operator_headers(hatchery_id: str) -> dict:
    """Headers for `HatcheryOperator`. Pass the acting `Hatchery`'s own `id`."""
    return build_user_headers(hatchery_id, UserRole.HATCHERY_OPERATOR.value)


def make_seafood_dealer_headers(dealer_id: str) -> dict:
    """Headers for `SeafoodDealer`. Pass the acting `Dealer`'s own `id`."""
    return build_user_headers(dealer_id, UserRole.SEAFOOD_DEALER.value)


def headers_for_role(role: str, user_id: str = "some-user-1") -> dict:
    """Headers for an arbitrary role value — including values that are not
    recognised role names at all, for role-authorisation tests."""
    return build_user_headers(user_id, role)


ALL_ROLE_VALUES = [r.value for r in UserRole]
