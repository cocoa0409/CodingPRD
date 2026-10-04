"""Pre-built role headers for every role in the PRD.

All six roles carry an opaque ``X-User-ID`` — the PRD declares that no role's
identifier is matched against a persisted entity (there is no User resource).
Two identifiers matter by value, not by entity: the ``LineOperator`` submitting
a verification is captured as ``recorded_by_user_id``, and the ``QualityLead``
approving a calibration is captured as ``approved_by_user_id``; the
segregation-of-duties check compares them. Tests therefore build verifier and
approver headers through ``make_line_operator_headers`` /
``make_quality_lead_headers`` with explicit identifiers.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "shift_manager_headers": build_user_headers("test-shift-manager-1", "ShiftManager"),
    "line_operator_headers": build_user_headers("test-line-operator-1", "LineOperator"),
    "prep_cook_headers": build_user_headers("test-prep-cook-1", "PrepCook"),
    "quality_lead_headers": build_user_headers("test-quality-lead-1", "QualityLead"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}

OPS_ADMIN_HEADERS = TEST_USERS["ops_admin_headers"]
SHIFT_MANAGER_HEADERS = TEST_USERS["shift_manager_headers"]
LINE_OPERATOR_HEADERS = TEST_USERS["line_operator_headers"]
PREP_COOK_HEADERS = TEST_USERS["prep_cook_headers"]
QUALITY_LEAD_HEADERS = TEST_USERS["quality_lead_headers"]
CUSTOMER_HEADERS = TEST_USERS["customer_headers"]


def make_ops_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OpsAdmin")


def make_shift_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ShiftManager")


def make_line_operator_headers(user_id: str) -> dict:
    """Headers for a LineOperator; the id lands on PortionVerification rows."""
    return build_user_headers(user_id, "LineOperator")


def make_prep_cook_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PrepCook")


def make_quality_lead_headers(user_id: str) -> dict:
    """Headers for a QualityLead; the id lands on CalibrationAdjustment rows."""
    return build_user_headers(user_id, "QualityLead")


def make_customer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Customer")
