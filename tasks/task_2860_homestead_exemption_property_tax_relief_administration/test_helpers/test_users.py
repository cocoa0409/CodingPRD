"""Auth headers for the acting users of each role.

Eight of the nine roles are county operators whose ``X-User-ID`` is an opaque
staff identifier.  The ninth role, Taxpayer, is entity-backed: its ``X-User-ID``
must be the identifier of the TaxpayerAccount row acting, so those headers are
built per taxpayer with :func:`make_taxpayer_headers`.

Two independent operator identities are provided for the roles that appear on
both sides of a duty-separated hand-off, so a test can hand a step to a
colleague without reusing the identity the PRD requires to be distinct.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --- opaque operator identities ------------------------------------------

ADMIN_USER_ID = "admin-01"
ANALYST_USER_ID = "analyst-01"
ANALYST_2_USER_ID = "analyst-02"
CLERK_USER_ID = "clerk-01"
CLERK_2_USER_ID = "clerk-02"
REVIEWER_USER_ID = "reviewer-01"
REVIEWER_2_USER_ID = "reviewer-02"
INVESTIGATOR_USER_ID = "investigator-01"
INVESTIGATOR_2_USER_ID = "investigator-02"
RECOVERY_USER_ID = "recovery-01"
RECOVERY_2_USER_ID = "recovery-02"
HEARING_CLERK_USER_ID = "hclerk-01"
HEARING_OFFICER_USER_ID = "hofficer-01"
HEARING_OFFICER_2_USER_ID = "hofficer-02"

ADMIN = build_user_headers(ADMIN_USER_ID, "ProgramAdministrator")
ANALYST = build_user_headers(ANALYST_USER_ID, "AssessorAnalyst")
ANALYST_2 = build_user_headers(ANALYST_2_USER_ID, "AssessorAnalyst")
CLERK = build_user_headers(CLERK_USER_ID, "IntakeClerk")
CLERK_2 = build_user_headers(CLERK_2_USER_ID, "IntakeClerk")
REVIEWER = build_user_headers(REVIEWER_USER_ID, "ExemptionsReviewer")
REVIEWER_2 = build_user_headers(REVIEWER_2_USER_ID, "ExemptionsReviewer")
INVESTIGATOR = build_user_headers(INVESTIGATOR_USER_ID, "FraudInvestigator")
INVESTIGATOR_2 = build_user_headers(INVESTIGATOR_2_USER_ID, "FraudInvestigator")
RECOVERY = build_user_headers(RECOVERY_USER_ID, "RecoveryOfficer")
RECOVERY_2 = build_user_headers(RECOVERY_2_USER_ID, "RecoveryOfficer")
HEARING_CLERK = build_user_headers(HEARING_CLERK_USER_ID, "HearingClerk")
HEARING_OFFICER = build_user_headers(HEARING_OFFICER_USER_ID, "HearingOfficer")
HEARING_OFFICER_2 = build_user_headers(HEARING_OFFICER_2_USER_ID, "HearingOfficer")

TEST_USERS: Dict[str, Dict[str, str]] = {
    "ProgramAdministrator": ADMIN,
    "AssessorAnalyst": ANALYST,
    "IntakeClerk": CLERK,
    "ExemptionsReviewer": REVIEWER,
    "FraudInvestigator": INVESTIGATOR,
    "RecoveryOfficer": RECOVERY,
    "HearingClerk": HEARING_CLERK,
    "HearingOfficer": HEARING_OFFICER,
}


def make_taxpayer_headers(taxpayer_id: str) -> Dict[str, str]:
    """Headers for the Taxpayer role acting as the given TaxpayerAccount.

    The Taxpayer role is entity-backed, so ``X-User-ID`` carries the account
    identifier itself; ownership checks compare it against the taxpayer_id
    reached from the addressed resource.
    """
    return build_user_headers(taxpayer_id, "Taxpayer")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user id and role string.

    Used where a test needs a specific operator identity or a role string that
    is deliberately not one of the nine declared roles.
    """
    return build_user_headers(user_id, role)


# --- callers the identity gate must turn away ------------------------------

UNREGISTERED_ROLE = make_headers("treasurer-01", "CountyTreasurer")
"""A well-formed pair of headers whose role is not one of the nine declared."""

NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
"""Headers carrying neither ``X-User-ID`` nor ``X-User-Role`` at all."""
