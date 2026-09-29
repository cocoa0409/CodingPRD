"""Pre-built role headers for every role the PRD declares.

The PRD authenticates with X-User-ID and X-User-Role. Two roles resolve their
X-User-ID against a stored row — AgencyOfficer against Agency.id and Bidder
against Bidder.id — so any call those roles make must carry the real row id.
The remaining five roles are opaque: their X-User-ID is a free-form operator
identifier the server merely stamps onto audit fields.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Operator identifiers stamped into the PRD's audit fields.
ADMIN_USER_ID = "admin-01"
ASSESSOR_USER_ID = "assessor-01"
OFFICER_USER_ID = "officer-01"
TECHNICIAN_USER_ID = "tech-01"
FINANCE_USER_ID = "finance-01"

# Second identities for the segregation-of-duties barriers.
SECOND_ASSESSOR_USER_ID = "assessor-02"
SECOND_OFFICER_USER_ID = "officer-02"
SECOND_TECHNICIAN_USER_ID = "tech-02"
SECOND_FINANCE_USER_ID = "finance-02"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — the shared constant is the canonical form.
    "program_admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdmin"),
    "surplus_assessor_headers": build_user_headers(ASSESSOR_USER_ID, "SurplusAssessor"),
    "disposal_officer_headers": build_user_headers(OFFICER_USER_ID, "DisposalOfficer"),
    "clearance_technician_headers": build_user_headers(
        TECHNICIAN_USER_ID, "ClearanceTechnician"
    ),
    "finance_controller_headers": build_user_headers(
        FINANCE_USER_ID, "FinanceController"
    ),
    # Entity-resolved roles — shared constants are usable only where the call is
    # not ownership-gated (unauthenticated / unauthorized / not-found probes).
    "agency_officer_headers": build_user_headers("no-such-agency", "AgencyOfficer"),
    "bidder_headers": build_user_headers("no-such-bidder", "Bidder"),
    # Second operator identities for the two segregation-of-duties barriers.
    "second_surplus_assessor_headers": build_user_headers(
        SECOND_ASSESSOR_USER_ID, "SurplusAssessor"
    ),
    "second_disposal_officer_headers": build_user_headers(
        SECOND_OFFICER_USER_ID, "DisposalOfficer"
    ),
    "second_clearance_technician_headers": build_user_headers(
        SECOND_TECHNICIAN_USER_ID, "ClearanceTechnician"
    ),
    "second_finance_controller_headers": build_user_headers(
        SECOND_FINANCE_USER_ID, "FinanceController"
    ),
}


def make_agency_officer_headers(agency_id: str) -> Dict[str, str]:
    """For AgencyOfficer, whose X-User-ID must resolve to an Agency row. Pass the
    id of the organization on whose behalf the call is made."""
    return build_user_headers(agency_id, "AgencyOfficer")


def make_bidder_headers(bidder_id: str) -> Dict[str, str]:
    """For Bidder, whose X-User-ID must resolve to a Bidder row. Pass the id of
    the bidder placing the bid, lodging the deposit or paying the invoice."""
    return build_user_headers(bidder_id, "Bidder")


def make_program_admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "ProgramAdmin")


def make_surplus_assessor_headers(user_id: str = ASSESSOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "SurplusAssessor")


def make_disposal_officer_headers(user_id: str = OFFICER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "DisposalOfficer")


def make_clearance_technician_headers(
    user_id: str = TECHNICIAN_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "ClearanceTechnician")


def make_finance_controller_headers(user_id: str = FINANCE_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "FinanceController")
