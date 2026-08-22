"""Pre-built role headers for every operating role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. The five operator roles carry an opaque X-User-ID that is
# never compared to any entity id, so a fixed identifier is always safe for them.
# The PayerLiaison constant is only safe for calls that do not reach a payer
# ownership check (for example a 401/403/404 probe).
TEST_USERS = {
    "credit_analyst_headers": build_user_headers("ca-analyst-1", "CreditAnalyst"),
    "refund_approver_headers": build_user_headers("appr-1", "RefundApprover"),
    "disbursement_officer_headers": build_user_headers("disb-1", "DisbursementOfficer"),
    "compliance_officer_headers": build_user_headers("comp-1", "ComplianceOfficer"),
    "system_admin_headers": build_user_headers("sysadmin-1", "SystemAdmin"),
    "payer_liaison_headers": build_user_headers("payer-liaison-1", "PayerLiaison"),
}


def make_payer_liaison_headers(payer_id: str) -> dict:
    """Headers for a PayerLiaison acting for the payer whose id is `payer_id`.

    A PayerLiaison's X-User-ID is the id of the acting Payer row, so every
    ownership-gated take-back call MUST use this builder with the real payer id.
    """
    return build_user_headers(payer_id, "PayerLiaison")


def make_credit_analyst_headers(user_id: str) -> dict:
    """Headers for a named CreditAnalyst operator (segregation-of-duties tests)."""
    return build_user_headers(user_id, "CreditAnalyst")


def make_refund_approver_headers(user_id: str) -> dict:
    """Headers for a named RefundApprover operator (duplicate-approver tests)."""
    return build_user_headers(user_id, "RefundApprover")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_disbursement_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DisbursementOfficer")


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")
