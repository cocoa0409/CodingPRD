"""Pre-built role headers for every role in the PRD (§2.1).

Six of the seven roles carry an opaque identity, so a shared constant is the
canonical form for them. `Participant` is entity-backed: its `X-User-ID` is the
`id` of the acting `Qualifier` row, so ownership-gated calls MUST go through
`make_participant_headers(qualifier_id)`.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import USER_IDS

TEST_USERS: Dict[str, Dict[str, str]] = {
    # opaque roles — the shared constant is the canonical form
    "program_director_headers": build_user_headers(
        USER_IDS["PROGRAM_DIRECTOR"], "ProgramDirector"
    ),
    "sourcing_manager_headers": build_user_headers(
        USER_IDS["SOURCING_MANAGER"], "SourcingManager"
    ),
    "sourcing_manager_alt_headers": build_user_headers(
        USER_IDS["SOURCING_MANAGER_ALT"], "SourcingManager"
    ),
    "contract_approver_headers": build_user_headers(
        USER_IDS["CONTRACT_APPROVER"], "ContractApprover"
    ),
    "contract_approver_alt_headers": build_user_headers(
        USER_IDS["CONTRACT_APPROVER_ALT"], "ContractApprover"
    ),
    "sales_ops_analyst_headers": build_user_headers(
        USER_IDS["SALES_OPS_ANALYST"], "SalesOpsAnalyst"
    ),
    "travel_desk_headers": build_user_headers(USER_IDS["TRAVEL_DESK"], "TravelDesk"),
    "tax_officer_headers": build_user_headers(
        USER_IDS["TAX_OFFICER"], "TaxComplianceOfficer"
    ),
    "tax_officer_alt_headers": build_user_headers(
        USER_IDS["TAX_OFFICER_ALT"], "TaxComplianceOfficer"
    ),
    # entity_backed role — fallback for tests that never exercise ownership
    "participant_headers": build_user_headers("participant-not-an-owner", "Participant"),
}


def make_program_director_headers(user_id: str) -> Dict[str, str]:
    """ProgramDirector acting under a specific opaque operator id."""
    return build_user_headers(user_id, "ProgramDirector")


def make_sourcing_manager_headers(user_id: str) -> Dict[str, str]:
    """SourcingManager acting under a specific opaque operator id.

    Used by the duty-separation scenarios of PRD §2.9, where the proposing
    identity is compared against the executing identity.
    """
    return build_user_headers(user_id, "SourcingManager")


def make_contract_approver_headers(user_id: str) -> Dict[str, str]:
    """ContractApprover acting under a specific opaque operator id."""
    return build_user_headers(user_id, "ContractApprover")


def make_sales_ops_analyst_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "SalesOpsAnalyst")


def make_travel_desk_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "TravelDesk")


def make_tax_officer_headers(user_id: str) -> Dict[str, str]:
    """TaxComplianceOfficer acting under a specific opaque operator id.

    The filing identity is the comparand for the void self-review rule.
    """
    return build_user_headers(user_id, "TaxComplianceOfficer")


def make_participant_headers(qualifier_id: str) -> Dict[str, str]:
    """For Participant (entity-backed on Qualifier).

    Pass the acting Qualifier's `id` whenever the call is ownership-gated —
    every Participant write and single-row read is.
    """
    return build_user_headers(qualifier_id, "Participant")


ROLE_HEADER_BUILDERS = {
    "ProgramDirector": make_program_director_headers,
    "SourcingManager": make_sourcing_manager_headers,
    "ContractApprover": make_contract_approver_headers,
    "SalesOpsAnalyst": make_sales_ops_analyst_headers,
    "TravelDesk": make_travel_desk_headers,
    "TaxComplianceOfficer": make_tax_officer_headers,
    "Participant": make_participant_headers,
}


def headers_for_role(role: str, user_id: str = "generic-operator-1") -> Dict[str, str]:
    """Build headers for an arbitrary role name (used by RBAC matrix tests)."""
    return build_user_headers(user_id, role)
