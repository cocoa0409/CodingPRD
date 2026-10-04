"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. For SupplierOperator (entity-backed by DataSupplier) and
# ManufacturerClient (entity-backed by ManufacturerClient) the shared constant
# is a fallback only; ownership-gated calls must use the make_*_headers
# builders with the actual entity id.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "data_acquisition_manager_headers": build_user_headers(
        "test-data-acquisition-manager-1", "DataAcquisitionManager"
    ),
    "privacy_officer_headers": build_user_headers("test-privacy-officer-1", "PrivacyOfficer"),
    "supplier_operator_headers": build_user_headers("test-supplier-operator-1", "SupplierOperator"),
    "manufacturer_client_headers": build_user_headers(
        "test-manufacturer-client-1", "ManufacturerClient"
    ),
}


def make_supplier_operator_headers(supplier_id: str) -> dict:
    """For SupplierOperator (entity-backed by DataSupplier): X-User-ID must equal
    the acting supplier's id whenever the call is ownership-gated (batch submit
    and reprocess)."""
    return build_user_headers(supplier_id, "SupplierOperator")


def make_manufacturer_client_headers(client_id: str) -> dict:
    """For ManufacturerClient (entity-backed by ManufacturerClient): X-User-ID
    must equal the acting client's id whenever the call is ownership-gated
    (own-record reads and audit requests)."""
    return build_user_headers(client_id, "ManufacturerClient")
