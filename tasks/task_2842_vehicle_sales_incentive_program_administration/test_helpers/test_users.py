"""Pre-built role headers for every role the PRD declares."""
from prd_bench_local_runner.testing import build_user_headers

# Operator identifiers. For the four operator roles X-User-ID is opaque and is
# never compared to any entity id, so these constants are the canonical form.
USER_DESIGNER = "u-designer-1"
USER_DESIGNER_2 = "u-designer-2"
USER_CONTROLLER = "u-controller-1"
USER_CONTROLLER_2 = "u-controller-2"
USER_FSM = "u-fsm-1"
USER_FSM_2 = "u-fsm-2"
USER_AUDITOR_1 = "u-auditor-1"
USER_AUDITOR_2 = "u-auditor-2"
USER_AUDITOR_3 = "u-auditor-3"

TEST_USERS = {
    # Opaque operator roles — the shared constant is the canonical form.
    "program_designer_headers": build_user_headers(USER_DESIGNER, "ProgramDesigner"),
    "program_designer_2_headers": build_user_headers(USER_DESIGNER_2, "ProgramDesigner"),
    "incentive_controller_headers": build_user_headers(
        USER_CONTROLLER, "IncentiveController"
    ),
    "incentive_controller_2_headers": build_user_headers(
        USER_CONTROLLER_2, "IncentiveController"
    ),
    "field_sales_manager_headers": build_user_headers(USER_FSM, "FieldSalesManager"),
    "field_sales_manager_2_headers": build_user_headers(USER_FSM_2, "FieldSalesManager"),
    # The validating auditor and the adjudicating auditor must be different
    # principals, so two auditor identities are pre-built.
    "claims_auditor_headers": build_user_headers(USER_AUDITOR_1, "ClaimsAuditor"),
    "claims_auditor_2_headers": build_user_headers(USER_AUDITOR_2, "ClaimsAuditor"),
    "claims_auditor_3_headers": build_user_headers(USER_AUDITOR_3, "ClaimsAuditor"),
    # Dealer identity is entity-backed: this shared constant is a fallback for
    # tests that do NOT depend on the caller owning the subject resource.
    "dealer_headers": build_user_headers("test-dealer-not-a-real-id", "Dealer"),
}


# --- Per-instance builders ---------------------------------------------------


def make_dealer_headers(dealer_id: str) -> dict:
    """Headers for the `Dealer` role, whose X-User-ID is the id of the acting
    Dealer row. Pass the real Dealer id for every ownership-gated call:
    reporting a delivery, submitting a claim, filing a protest."""
    return build_user_headers(dealer_id, "Dealer")


def make_program_designer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramDesigner")


def make_incentive_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IncentiveController")


def make_field_sales_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FieldSalesManager")


def make_claims_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsAuditor")


def make_headers(user_id: str, role: str) -> dict:
    """Free-form builder for role-matrix tests."""
    return build_user_headers(user_id, role)


ALL_ROLE_NAMES = [
    "ProgramDesigner",
    "IncentiveController",
    "FieldSalesManager",
    "ClaimsAuditor",
    "Dealer",
]
