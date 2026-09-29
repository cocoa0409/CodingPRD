"""Pre-built role headers for every role the PRD recognises (§2.1).

Five of the six roles carry an opaque identity, so a shared constant is the
canonical form for them.  ``BrokerRepresentative`` is entity-backed: its
``X-User-ID`` is the ``id`` of the acting counterparty row, so ownership-gated
calls MUST use :func:`make_broker_representative_headers` with a real
counterparty ``id``.
"""
from prd_bench_local_runner.testing import build_user_headers

# Distinct operator identifiers, so a preparer and a blesser never collide
# under the duty-segregation comparisons of PRD §2.9.
USER_IDS = {
    "admin": "op_admin",
    "desk": "op_desk",
    "compliance": "op_comp",
    "treasury": "op_alm",
    "examiner": "op_exam",
    # Second identifiers of the same capacity, for tests that need a distinct
    # acting operator in the same role.
    "admin_alt": "op_admin_2",
    "desk_alt": "op_desk_2",
    "compliance_alt": "op_comp_2",
    "treasury_alt": "op_alm_2",
    "examiner_alt": "op_exam_2",
}

TEST_USERS = {
    "system_admin_headers": build_user_headers(USER_IDS["admin"], "SystemAdmin"),
    "system_admin_alt_headers": build_user_headers(USER_IDS["admin_alt"], "SystemAdmin"),
    "funding_desk_headers": build_user_headers(USER_IDS["desk"], "FundingDeskOfficer"),
    "funding_desk_alt_headers": build_user_headers(
        USER_IDS["desk_alt"], "FundingDeskOfficer"
    ),
    "compliance_headers": build_user_headers(USER_IDS["compliance"], "ComplianceReviewer"),
    "compliance_alt_headers": build_user_headers(
        USER_IDS["compliance_alt"], "ComplianceReviewer"
    ),
    "treasury_headers": build_user_headers(USER_IDS["treasury"], "TreasuryController"),
    "treasury_alt_headers": build_user_headers(
        USER_IDS["treasury_alt"], "TreasuryController"
    ),
    "examiner_headers": build_user_headers(USER_IDS["examiner"], "Examiner"),
    "examiner_alt_headers": build_user_headers(USER_IDS["examiner_alt"], "Examiner"),
    # Fallback only: never use for an ownership-gated BrokerRepresentative call.
    "broker_rep_headers": build_user_headers("op_broker_rep", "BrokerRepresentative"),
}

ADMIN = TEST_USERS["system_admin_headers"]
DESK = TEST_USERS["funding_desk_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
TREASURY = TEST_USERS["treasury_headers"]
EXAMINER = TEST_USERS["examiner_headers"]


def make_system_admin_headers(user_id: str) -> dict:
    """SystemAdmin acting under an explicit operator identifier."""
    return build_user_headers(user_id, "SystemAdmin")


def make_funding_desk_headers(user_id: str) -> dict:
    """FundingDeskOfficer acting under an explicit operator identifier."""
    return build_user_headers(user_id, "FundingDeskOfficer")


def make_compliance_headers(user_id: str) -> dict:
    """ComplianceReviewer acting under an explicit operator identifier."""
    return build_user_headers(user_id, "ComplianceReviewer")


def make_treasury_headers(user_id: str) -> dict:
    """TreasuryController acting under an explicit operator identifier."""
    return build_user_headers(user_id, "TreasuryController")


def make_examiner_headers(user_id: str) -> dict:
    """Examiner acting under an explicit operator identifier."""
    return build_user_headers(user_id, "Examiner")


def make_broker_representative_headers(broker_id: str) -> dict:
    """BrokerRepresentative headers: X-User-ID is the acting counterparty's id."""
    return build_user_headers(broker_id, "BrokerRepresentative")
