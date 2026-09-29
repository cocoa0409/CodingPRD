"""
Identity header builders.

Three of the five roles are entity backed: the ``X-User-ID`` a
PooledPlanProvider, an AdoptingEmployer or a ServiceProvider presents is the
primary key of its own row, so every distinct owner gets its own header dict
built from that row's id.  The two oversight roles carry opaque identifiers
that never have to resolve to anything.
"""

from typing import Dict, Optional

from .constants import (
    ROLE_ADOPTING_EMPLOYER,
    ROLE_INDEPENDENT_AUDITOR,
    ROLE_POOLED_PLAN_PROVIDER,
    ROLE_REGULATOR_OPS,
    ROLE_SERVICE_PROVIDER,
)

# Opaque identities: the API never resolves these against a row.
REGULATOR_OPS_USER_ID = "regulator-ops-operator-01"
INDEPENDENT_AUDITOR_USER_ID = "independent-auditor-iqpa-01"

# Syntactically valid UUIDs used where a test needs an id that resolves to
# nothing at all.
UNRESOLVABLE_PROVIDER_ID = "11111111-1111-4111-8111-111111111111"
UNRESOLVABLE_EMPLOYER_ID = "22222222-2222-4222-8222-222222222222"
UNRESOLVABLE_PLAN_PROVIDER_ID = "33333333-3333-4333-8333-333333333333"
UNRESOLVABLE_ELECTION_ID = "44444444-4444-4444-8444-444444444444"
UNRESOLVABLE_BATCH_ID = "55555555-5555-4555-8555-555555555555"
UNRESOLVABLE_DEPOSIT_ID = "66666666-6666-4666-8666-666666666666"
UNRESOLVABLE_FILING_ID = "77777777-7777-4777-8777-777777777777"
UNRESOLVABLE_SERVICE_PROVIDER_ID = "88888888-8888-4888-8888-888888888888"
UNRESOLVABLE_TRANSFER_ID = "99999999-9999-4999-8999-999999999999"
UNRESOLVABLE_PLAN_DOCUMENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UNRESOLVABLE_ALLOCATION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UNRESOLVABLE_TEST_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Build a well-formed identity header pair for an arbitrary id and role."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def regulator_headers() -> Dict[str, str]:
    """Headers for the government-side operator."""
    return make_headers(REGULATOR_OPS_USER_ID, ROLE_REGULATOR_OPS)


def auditor_headers() -> Dict[str, str]:
    """Headers for the independent qualified public accountant."""
    return make_headers(INDEPENDENT_AUDITOR_USER_ID, ROLE_INDEPENDENT_AUDITOR)


def plan_provider_headers(pooled_plan_provider_id: str) -> Dict[str, str]:
    """Headers for one specific pooled plan provider row."""
    return make_headers(pooled_plan_provider_id, ROLE_POOLED_PLAN_PROVIDER)


def employer_headers(adopting_employer_id: str) -> Dict[str, str]:
    """Headers for one specific adopting employer row."""
    return make_headers(adopting_employer_id, ROLE_ADOPTING_EMPLOYER)


def service_provider_headers(service_provider_id: str) -> Dict[str, str]:
    """Headers for one specific engaged service provider row."""
    return make_headers(service_provider_id, ROLE_SERVICE_PROVIDER)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that omit ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that omit ``X-User-Role`` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """Headers whose ``X-User-ID`` is the empty string, not whitespace."""
    return make_headers("", role)


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is the empty string, not whitespace."""
    return make_headers(user_id, "")


def headers_with_unknown_role(
    role: str, user_id: Optional[str] = None
) -> Dict[str, str]:
    """Headers naming a role that is not one of the five declared roles."""
    return make_headers(user_id or UNRESOLVABLE_EMPLOYER_ID, role)


def no_headers() -> Dict[str, str]:
    """A request carrying neither identity header."""
    return {"Content-Type": "application/json"}
