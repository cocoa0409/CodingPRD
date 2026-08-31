"""Pre-built role headers for every role the API declares."""

from prd_bench_local_runner.testing import build_user_headers

from .constants import QC_TECH_ID, QUALITY_MANAGER_ID

# Shared constants.
#
# Every staff role carries an opaque operator identifier that is never compared
# against any stored row's id, so a shared constant is the canonical form for
# them. The buying account role is different: its identifier IS the account's
# id, so tests must build its headers with make_customer_headers(customer_id).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("pa-001", "PlatformAdmin"),
    "product_manager_headers": build_user_headers("pm-001", "ProductManager"),
    "blend_operator_headers": build_user_headers("bo-001", "BlendOperator"),
    "qc_technician_headers": build_user_headers(QC_TECH_ID, "QCTechnician"),
    "quality_manager_headers": build_user_headers(QUALITY_MANAGER_ID, "QualityManager"),
    "compliance_officer_headers": build_user_headers("co-001", "ComplianceOfficer"),
    "sales_rep_headers": build_user_headers("sr-001", "SalesRep"),
    # Fallback only — never use for an ownership-gated call.
    "customer_headers": build_user_headers("cust-unbound", "Customer"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_product_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductManager")


def make_blend_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BlendOperator")


def make_qc_technician_headers(user_id: str) -> dict:
    """Laboratory analyst headers. The identifier supplied here is stamped onto
    every result recorded through them."""
    return build_user_headers(user_id, "QCTechnician")


def make_quality_manager_headers(user_id: str) -> dict:
    """Disposition authority headers. Supply an identifier that does not appear
    on any of the batch's results unless the test is exercising that refusal."""
    return build_user_headers(user_id, "QualityManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_sales_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_customer_headers(customer_id: str) -> dict:
    """Buying-account headers. The identifier must be the account row's own id,
    because ownership checks compare it directly against a resource's
    customer reference."""
    return build_user_headers(customer_id, "Customer")
