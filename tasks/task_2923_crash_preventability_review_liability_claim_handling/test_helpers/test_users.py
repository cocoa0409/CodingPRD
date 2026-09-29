"""Pre-built authentication headers for every role the service recognises."""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from test_helpers.constants import (
    OPERATOR_IDS,
    ROLE_AUDITOR,
    ROLE_CLAIMS_ADJUSTER,
    ROLE_CLAIMS_MANAGER,
    ROLE_COMMITTEE_MEMBER,
    ROLE_DISPATCHER,
    ROLE_DRIVER,
    ROLE_SAFETY_ADMIN,
    ROLE_SAFETY_MANAGER,
    UNKNOWN_ROLE,
)

Headers = Dict[str, str]


def make_safety_admin_headers(user_id: Optional[str] = None) -> Headers:
    return build_user_headers(user_id or OPERATOR_IDS["safety_admin"], ROLE_SAFETY_ADMIN)


def make_dispatcher_headers(user_id: Optional[str] = None) -> Headers:
    return build_user_headers(user_id or OPERATOR_IDS["dispatcher"], ROLE_DISPATCHER)


def make_committee_member_headers(user_id: Optional[str] = None) -> Headers:
    return build_user_headers(
        user_id or OPERATOR_IDS["committee_member_one"], ROLE_COMMITTEE_MEMBER
    )


def make_safety_manager_headers(user_id: Optional[str] = None) -> Headers:
    return build_user_headers(
        user_id or OPERATOR_IDS["safety_manager_decider"], ROLE_SAFETY_MANAGER
    )


def make_claims_adjuster_headers(user_id: Optional[str] = None) -> Headers:
    return build_user_headers(user_id or OPERATOR_IDS["claims_adjuster"], ROLE_CLAIMS_ADJUSTER)


def make_claims_manager_headers(user_id: Optional[str] = None) -> Headers:
    return build_user_headers(user_id or OPERATOR_IDS["claims_manager"], ROLE_CLAIMS_MANAGER)


def make_auditor_headers(user_id: Optional[str] = None) -> Headers:
    return build_user_headers(user_id or OPERATOR_IDS["auditor"], ROLE_AUDITOR)


def make_driver_headers(driver_id: str) -> Headers:
    """The Driver role is entity backed: the identifier is a Driver row id."""
    return build_user_headers(driver_id, ROLE_DRIVER)


def make_blank_user_id_headers(role: str = ROLE_SAFETY_ADMIN) -> Headers:
    """Headers whose user identifier is present but empty."""
    return build_user_headers("", role)


def make_blank_role_headers(user_id: Optional[str] = None) -> Headers:
    """Headers whose role is present but empty."""
    return build_user_headers(user_id or OPERATOR_IDS["safety_admin"], "")


def make_unknown_role_headers(user_id: Optional[str] = None) -> Headers:
    """Headers naming a role outside the declared set."""
    return build_user_headers(user_id or OPERATOR_IDS["safety_admin"], UNKNOWN_ROLE)


def make_missing_user_id_headers(role: str = ROLE_SAFETY_ADMIN) -> Headers:
    """Headers with no user identifier at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_missing_role_headers(user_id: Optional[str] = None) -> Headers:
    """Headers with no role at all."""
    return {
        "X-User-ID": user_id or OPERATOR_IDS["safety_admin"],
        "Content-Type": "application/json",
    }


TEST_USERS: Dict[str, Headers] = {
    "safety_admin_headers": make_safety_admin_headers(),
    "dispatcher_headers": make_dispatcher_headers(),
    "committee_member_one_headers": make_committee_member_headers(
        OPERATOR_IDS["committee_member_one"]
    ),
    "committee_member_two_headers": make_committee_member_headers(
        OPERATOR_IDS["committee_member_two"]
    ),
    "committee_member_three_headers": make_committee_member_headers(
        OPERATOR_IDS["committee_member_three"]
    ),
    "safety_manager_headers": make_safety_manager_headers(
        OPERATOR_IDS["safety_manager_decider"]
    ),
    "appeals_manager_headers": make_safety_manager_headers(
        OPERATOR_IDS["safety_manager_appeals"]
    ),
    "claims_adjuster_headers": make_claims_adjuster_headers(),
    "claims_manager_headers": make_claims_manager_headers(),
    "auditor_headers": make_auditor_headers(),
}
