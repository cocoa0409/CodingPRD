"""Pre-built role headers for every role named in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the six roles whose X-User-ID is an opaque
# operator identifier, and for BrandAdmin only on calls that are not
# brand-scope gated.
TEST_USERS = {
    "compliance_admin_headers": build_user_headers("op-compliance-admin-1", "ComplianceAdmin"),
    "brand_admin_headers": build_user_headers("op-brand-admin-1", "BrandAdmin"),
    "labeling_specialist_headers": build_user_headers("op-specialist-1", "LabelingSpecialist"),
    "labeling_specialist_2_headers": build_user_headers("op-specialist-2", "LabelingSpecialist"),
    "labeling_approver_headers": build_user_headers("op-approver-1", "LabelingApprover"),
    "labeling_approver_2_headers": build_user_headers("op-approver-2", "LabelingApprover"),
    "accredited_lab_headers": build_user_headers("op-lab-1", "AccreditedLab"),
    "customs_officer_headers": build_user_headers("op-customs-1", "CustomsOfficer"),
    "auditor_headers": build_user_headers("op-auditor-1", "Auditor"),
}


def make_brand_admin_headers(brand_id: str) -> dict:
    """For BrandAdmin. X-User-ID is the id of the acting Brand row, so every
    brand-scope-gated call must pass the real Brand id here."""
    return build_user_headers(brand_id, "BrandAdmin")


def make_headers(user_id: str, role: str) -> dict:
    return build_user_headers(user_id, role)


def headers_for_role(role: str) -> dict:
    """Shared-constant headers for an arbitrary role name."""
    return build_user_headers(f"op-{role.lower()}-x", role)
