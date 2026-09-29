"""Pre-built role headers for every role the PRD declares.

`CareManager` and `PracticeSupervisor` both carry the acting `CareManager.id`
in `X-User-ID`; `FamilyDecisionMaker` carries the acting `FamilyContact.id`.
Those three roles therefore MUST be built per instance with the real entity id
via the `make_*_headers` builders below whenever the call is ownership-gated.
`BillingAdministrator` and `PracticeAdmin` are opaque operator identities and
the shared constants are their canonical form.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the two opaque roles, and for tests that do not
# exercise ownership at all (bad payloads, unknown ids, role-admission checks).
TEST_USERS: Dict[str, Dict[str, str]] = {
    "care_manager_headers": build_user_headers("test-care-manager-1", "CareManager"),
    "practice_supervisor_headers": build_user_headers(
        "test-supervisor-1", "PracticeSupervisor"
    ),
    "family_decision_maker_headers": build_user_headers(
        "test-family-contact-1", "FamilyDecisionMaker"
    ),
    "billing_administrator_headers": build_user_headers(
        "test-billing-admin-1", "BillingAdministrator"
    ),
    "practice_admin_headers": build_user_headers("test-practice-admin-1", "PracticeAdmin"),
}

PRACTICE_ADMIN = TEST_USERS["practice_admin_headers"]
BILLING_ADMINISTRATOR = TEST_USERS["billing_administrator_headers"]


def make_care_manager_headers(care_manager_id: str) -> Dict[str, str]:
    """Headers for `CareManager`; pass the acting `CareManager.id`."""
    return build_user_headers(care_manager_id, "CareManager")


def make_practice_supervisor_headers(care_manager_id: str) -> Dict[str, str]:
    """Headers for `PracticeSupervisor`; pass the `CareManager.id` of a care
    manager whose `is_supervisor` is true."""
    return build_user_headers(care_manager_id, "PracticeSupervisor")


def make_family_decision_maker_headers(contact_id: str) -> Dict[str, str]:
    """Headers for `FamilyDecisionMaker`; pass the acting `FamilyContact.id`."""
    return build_user_headers(contact_id, "FamilyDecisionMaker")


def make_billing_administrator_headers(
    operator_id: str = "test-billing-admin-1",
) -> Dict[str, str]:
    """Headers for `BillingAdministrator` (an opaque operator identifier)."""
    return build_user_headers(operator_id, "BillingAdministrator")


def make_practice_admin_headers(
    operator_id: str = "test-practice-admin-1",
) -> Dict[str, str]:
    """Headers for `PracticeAdmin` (an opaque operator identifier)."""
    return build_user_headers(operator_id, "PracticeAdmin")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for role-admission tests that need an arbitrary pairing."""
    return build_user_headers(user_id, role)


ALL_ROLE_NAMES = [
    "CareManager",
    "PracticeSupervisor",
    "FamilyDecisionMaker",
    "BillingAdministrator",
    "PracticeAdmin",
]
