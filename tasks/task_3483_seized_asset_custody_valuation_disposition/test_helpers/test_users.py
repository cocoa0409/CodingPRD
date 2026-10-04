"""Pre-built role headers for every role the PRD declares (§2.1).

Every role's X-User-ID is opaque — it is not the id of any persisted entity,
and the server never compares it against a resource's own id. Two comparisons
do pin the identifier:

- a Claimant may file or appeal a third-party interest only when X-User-ID
  equals that interest's petitioner_ref — use ``make_claimant_headers(ref)``;
- the two segregation-of-duties pairs compare caller ids across a hand-off:
  an interlocutory sale request's adjudicator must differ from its
  requested_by_user_id, and a distribution's approver must differ from its
  created_by_user_id — use the second-identity constants for the approver side.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Canonical operator identifiers (stamped into the PRD's audit fields).
CASE_AGENT_USER_ID = "ca-blake"
COURT_OFFICIAL_USER_ID = "co-reyes"
SECOND_COURT_OFFICIAL_USER_ID = "co-lane"
ASSET_CUSTODIAN_USER_ID = "ac-dana"
APPRAISER_USER_ID = "ap-jo"
ASSET_MANAGER_USER_ID = "am-priya"
AUCTION_COORDINATOR_USER_ID = "aco-ruiz"
FUND_ADMINISTRATOR_USER_ID = "fa-mora"
SECOND_FUND_ADMINISTRATOR_USER_ID = "fa-lenovo"
CLAIMANT_USER_ID = "cl-orma"
SECOND_CLAIMANT_USER_ID = "cl-other"
SYSTEM_OPERATOR_USER_ID = "so-ada"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "case_agent_headers": build_user_headers(CASE_AGENT_USER_ID, "CaseAgent"),
    "court_official_headers": build_user_headers(
        COURT_OFFICIAL_USER_ID, "CourtOfficial"
    ),
    "second_court_official_headers": build_user_headers(
        SECOND_COURT_OFFICIAL_USER_ID, "CourtOfficial"
    ),
    "asset_custodian_headers": build_user_headers(
        ASSET_CUSTODIAN_USER_ID, "AssetCustodian"
    ),
    "appraiser_headers": build_user_headers(APPRAISER_USER_ID, "Appraiser"),
    "asset_manager_headers": build_user_headers(
        ASSET_MANAGER_USER_ID, "AssetManager"
    ),
    "auction_coordinator_headers": build_user_headers(
        AUCTION_COORDINATOR_USER_ID, "AuctionCoordinator"
    ),
    "fund_administrator_headers": build_user_headers(
        FUND_ADMINISTRATOR_USER_ID, "FundAdministrator"
    ),
    "second_fund_administrator_headers": build_user_headers(
        SECOND_FUND_ADMINISTRATOR_USER_ID, "FundAdministrator"
    ),
    # Shared Claimant headers: usable only where the call is not pinned to a
    # petitioner_ref (unauthenticated / forbidden / not-found probes). For
    # filing or appealing, use make_claimant_headers(petitioner_ref).
    "claimant_headers": build_user_headers(CLAIMANT_USER_ID, "Claimant"),
    "second_claimant_headers": build_user_headers(
        SECOND_CLAIMANT_USER_ID, "Claimant"
    ),
    "system_operator_headers": build_user_headers(
        SYSTEM_OPERATOR_USER_ID, "SystemOperator"
    ),
}


def make_case_agent_headers(user_id: str = CASE_AGENT_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "CaseAgent")


def make_court_official_headers(
    user_id: str = COURT_OFFICIAL_USER_ID,
) -> Dict[str, str]:
    """Pass the ISR requester's / distribution creator's user id here when a
    test needs the same-person segregation-of-duties probe."""
    return build_user_headers(user_id, "CourtOfficial")


def make_asset_custodian_headers(
    user_id: str = ASSET_CUSTODIAN_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "AssetCustodian")


def make_appraiser_headers(user_id: str = APPRAISER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "Appraiser")


def make_asset_manager_headers(
    user_id: str = ASSET_MANAGER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "AssetManager")


def make_auction_coordinator_headers(
    user_id: str = AUCTION_COORDINATOR_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "AuctionCoordinator")


def make_fund_administrator_headers(
    user_id: str = FUND_ADMINISTRATOR_USER_ID,
) -> Dict[str, str]:
    """Pass SECOND_FUND_ADMINISTRATOR_USER_ID (or vice versa) when the test
    crosses the distribution approve/rescind segregation-of-duties barrier."""
    return build_user_headers(user_id, "FundAdministrator")


def make_claimant_headers(petitioner_ref: str) -> Dict[str, str]:
    """For Claimant calls pinned to a third-party interest: the X-User-ID must
    equal that interest's petitioner_ref (PRD §2.1, §3.5)."""
    return build_user_headers(petitioner_ref, "Claimant")


def make_system_operator_headers(
    user_id: str = SYSTEM_OPERATOR_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "SystemOperator")


__all__ = [
    "CASE_AGENT_USER_ID",
    "COURT_OFFICIAL_USER_ID",
    "SECOND_COURT_OFFICIAL_USER_ID",
    "ASSET_CUSTODIAN_USER_ID",
    "APPRAISER_USER_ID",
    "ASSET_MANAGER_USER_ID",
    "AUCTION_COORDINATOR_USER_ID",
    "FUND_ADMINISTRATOR_USER_ID",
    "SECOND_FUND_ADMINISTRATOR_USER_ID",
    "CLAIMANT_USER_ID",
    "SECOND_CLAIMANT_USER_ID",
    "SYSTEM_OPERATOR_USER_ID",
    "TEST_USERS",
    "make_case_agent_headers",
    "make_court_official_headers",
    "make_asset_custodian_headers",
    "make_appraiser_headers",
    "make_asset_manager_headers",
    "make_auction_coordinator_headers",
    "make_fund_administrator_headers",
    "make_claimant_headers",
    "make_system_operator_headers",
]
