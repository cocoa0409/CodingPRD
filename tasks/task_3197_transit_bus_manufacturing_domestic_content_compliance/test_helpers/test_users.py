"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. For AgencyAdmin (identity backed by the Agency entity)
# the shared constant is a fallback only; ownership-gated calls must use
# make_agency_admin_headers(agency["id"]).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "procurement_officer_headers": build_user_headers("po-1", "ProcurementOfficer"),
    "config_engineer_headers": build_user_headers("ce-1", "ConfigEngineer"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "supplier_rep_headers": build_user_headers("sup-1", "SupplierRep"),
    "auditor_headers": build_user_headers("aud-1", "Auditor"),
    "production_planner_headers": build_user_headers("pp-1", "ProductionPlanner"),
    "agency_inspector_headers": build_user_headers("insp-1", "AgencyInspector"),
    "warranty_admin_headers": build_user_headers("wa-1", "WarrantyAdmin"),
    "agency_admin_headers": build_user_headers("agency-admin-1", "AgencyAdmin"),
}


def make_headers(user_id: str, role: str) -> dict:
    return build_user_headers(user_id, role)


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_procurement_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProcurementOfficer")


def make_config_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ConfigEngineer")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_supplier_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupplierRep")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")


def make_production_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_agency_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AgencyInspector")


def make_warranty_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarrantyAdmin")


def make_agency_admin_headers(user_id: str) -> dict:
    """AgencyAdmin identity is the Agency id. Pass the actual agency id
    whenever the call is ownership-gated (e.g. PATCH /api/agencies/{id})."""
    return build_user_headers(user_id, "AgencyAdmin")
