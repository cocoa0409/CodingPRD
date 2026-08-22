"""Pre-built role headers for every role in the PRD.

`CustomerRep` is the only identity-backed role: for a `CustomerRep` the
`X-User-ID` is the id of the acting `Customer`, so any ownership-scoped call
must be made with `make_customer_rep_headers(customer["id"])`. The other four
roles carry an opaque operator identifier that is never compared to an entity
id, but which the segregation-of-duties rule does compare between roles.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import TEST_DEFAULTS

TEST_USERS = {
    # Opaque roles - the shared constant is the canonical form.
    "regulatory_admin_headers": build_user_headers(
        TEST_DEFAULTS["ADMIN_USER_ID"], "RegulatoryAdmin"
    ),
    "cycle_operator_headers": build_user_headers(
        TEST_DEFAULTS["OPERATOR_USER_ID"], "CycleOperator"
    ),
    "dosimetry_analyst_headers": build_user_headers(
        TEST_DEFAULTS["ANALYST_USER_ID"], "DosimetryAnalyst"
    ),
    "quality_release_officer_headers": build_user_headers(
        TEST_DEFAULTS["OFFICER_USER_ID"], "QualityReleaseOfficer"
    ),
    # Identity-backed role - only safe for calls that are not ownership-scoped.
    "customer_rep_headers": build_user_headers("cust-rep-1", "CustomerRep"),
}


def make_regulatory_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegulatoryAdmin")


def make_customer_rep_headers(customer_id: str) -> dict:
    """Pass the acting Customer's own id: ownership checks compare the
    resource's customer_id against X-User-ID."""
    return build_user_headers(customer_id, "CustomerRep")


def make_cycle_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CycleOperator")


def make_dosimetry_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DosimetryAnalyst")


def make_quality_release_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityReleaseOfficer")
