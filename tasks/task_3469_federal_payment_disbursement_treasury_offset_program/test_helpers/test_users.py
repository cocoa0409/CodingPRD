"""Pre-built role headers for every role declared in PRD §2.1.

Seven roles are callable; System is the automation identity and is NEVER a valid
X-User-Role value. CreditorAnalyst is entity-backed: its X-User-ID must equal the
id of the CreditorAgency it acts for, so ownership-gated calls MUST go through
make_creditor_analyst_headers(creditor["id"]) — never the shared constant.

Segregation of duties (PRD §2.1 / §3.6): the RefundOfficer deciding a claim must
differ from the X-User-ID that executed the claimed offset's payment. The shared
defaults deliberately use distinct ids ("op-1" vs "ro-1"); tests that exercise
the violation path build a colliding pair via make_refund_officer_headers("op-1").
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator/officer ids used across fixtures and segregation tests.
SUPERVISOR_USER_ID = "sup-1"
OPERATOR_USER_ID = "op-1"
OPERATOR_2_USER_ID = "op-2"
AGENCY_ANALYST_USER_ID = "paa-1"
STATE_COORDINATOR_USER_ID = "sc-1"
REFUND_OFFICER_USER_ID = "ro-1"
REFUND_OFFICER_2_USER_ID = "ro-2"
AUDITOR_USER_ID = "aud-1"

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "treasury_supervisor_headers": build_user_headers(
        SUPERVISOR_USER_ID, "TreasurySupervisor"
    ),
    "treasury_operator_headers": build_user_headers(
        OPERATOR_USER_ID, "TreasuryOperator"
    ),
    "treasury_operator_2_headers": build_user_headers(
        OPERATOR_2_USER_ID, "TreasuryOperator"
    ),
    "payment_agency_analyst_headers": build_user_headers(
        AGENCY_ANALYST_USER_ID, "PaymentAgencyAnalyst"
    ),
    "state_coordinator_headers": build_user_headers(
        STATE_COORDINATOR_USER_ID, "StateCoordinator"
    ),
    "refund_officer_headers": build_user_headers(
        REFUND_OFFICER_USER_ID, "RefundOfficer"
    ),
    "refund_officer_2_headers": build_user_headers(
        REFUND_OFFICER_2_USER_ID, "RefundOfficer"
    ),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, "Auditor"),
    # Entity-backed role — fallback ONLY for tests that never touch an owned
    # resource (e.g. 400-on-bad-payload before the ownership check can matter).
    # Any debt create/notice/activate call MUST use make_creditor_analyst_headers.
    "creditor_analyst_headers": build_user_headers(
        "creditor-analyst-unbound", "CreditorAnalyst"
    ),
}


# --- Per-instance builders ------------------------------------------------------

def make_creditor_analyst_headers(creditor_agency_id: str) -> dict:
    """CreditorAnalyst is entity-backed (PRD §2.1): X-User-ID must equal the id
    of the CreditorAgency that owns the debt being referred or transitioned."""
    return build_user_headers(creditor_agency_id, "CreditorAnalyst")


def make_treasury_supervisor_headers(user_id: str = SUPERVISOR_USER_ID) -> dict:
    return build_user_headers(user_id, "TreasurySupervisor")


def make_treasury_operator_headers(user_id: str = OPERATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "TreasuryOperator")


def make_payment_agency_analyst_headers(
    user_id: str = AGENCY_ANALYST_USER_ID,
) -> dict:
    return build_user_headers(user_id, "PaymentAgencyAnalyst")


def make_state_coordinator_headers(
    user_id: str = STATE_COORDINATOR_USER_ID,
) -> dict:
    return build_user_headers(user_id, "StateCoordinator")


def make_refund_officer_headers(user_id: str = REFUND_OFFICER_USER_ID) -> dict:
    """Build RefundOfficer headers for an arbitrary user id. Pass the executing
    operator's id (e.g. "op-1") to exercise the segregation-of-duties violation."""
    return build_user_headers(user_id, "RefundOfficer")


def make_auditor_headers(user_id: str = AUDITOR_USER_ID) -> dict:
    return build_user_headers(user_id, "Auditor")
