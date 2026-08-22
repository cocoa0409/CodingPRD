"""Pre-built role headers for every role in the PRD (§2.1).

The three employer-office roles and the arbitration administrator carry opaque
operator identifiers, so a shared constant is the canonical form for them.
`UnionSteward` and `Grievant` identify an `Employee` through `X-User-ID`, so
every ownership-gated call must build headers from the actual employee id.
"""

from prd_bench_local_runner.testing import build_user_headers

ANALYST_USER_ID = "lr-analyst-01"
SECOND_ANALYST_USER_ID = "lr-analyst-02"
DIRECTOR_USER_ID = "lr-dir-01"
SECOND_DIRECTOR_USER_ID = "lr-dir-02"
NEGOTIATOR_USER_ID = "chief-neg-01"
ADMINISTRATOR_USER_ID = "arb-admin-01"

# Shared constants — the canonical form for the opaque roles, and a safe
# fallback for steward/grievant calls that never touch an ownership check.
TEST_USERS = {
    "analyst_headers": build_user_headers(ANALYST_USER_ID, "LaborRelationsAnalyst"),
    "second_analyst_headers": build_user_headers(
        SECOND_ANALYST_USER_ID, "LaborRelationsAnalyst"
    ),
    "director_headers": build_user_headers(DIRECTOR_USER_ID, "LaborRelationsDirector"),
    "second_director_headers": build_user_headers(
        SECOND_DIRECTOR_USER_ID, "LaborRelationsDirector"
    ),
    "negotiator_headers": build_user_headers(NEGOTIATOR_USER_ID, "ChiefNegotiator"),
    "administrator_headers": build_user_headers(
        ADMINISTRATOR_USER_ID, "ArbitrationAdministrator"
    ),
    "steward_headers": build_user_headers("test-steward-1", "UnionSteward"),
    "grievant_headers": build_user_headers("test-grievant-1", "Grievant"),
}


def make_steward_headers(employee_id: str) -> dict:
    """Headers for a UnionSteward. Pass the acting steward's Employee id."""
    return build_user_headers(employee_id, "UnionSteward")


def make_grievant_headers(employee_id: str) -> dict:
    """Headers for a Grievant. Pass the acting member's Employee id."""
    return build_user_headers(employee_id, "Grievant")


def make_director_headers(user_id: str) -> dict:
    """Headers for a LaborRelationsDirector acting under a specific operator id."""
    return build_user_headers(user_id, "LaborRelationsDirector")


def make_analyst_headers(user_id: str) -> dict:
    """Headers for a LaborRelationsAnalyst acting under a specific operator id."""
    return build_user_headers(user_id, "LaborRelationsAnalyst")


def make_negotiator_headers(user_id: str) -> dict:
    """Headers for a ChiefNegotiator acting under a specific operator id."""
    return build_user_headers(user_id, "ChiefNegotiator")
