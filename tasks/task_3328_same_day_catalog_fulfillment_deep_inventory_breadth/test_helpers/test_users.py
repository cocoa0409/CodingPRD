"""Pre-built role headers for every role declared in the PRD.

Only ``CustomerAccount`` is entity-backed: its ``X-User-ID`` must be the ``id`` of
a persisted account whenever the call is ownership-gated. The other four roles
carry opaque operator identifiers.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "catalog_curator_headers": build_user_headers("test-curator-ada", "CatalogCurator"),
    "warehouse_picker_headers": build_user_headers("wp-dana", "WarehousePicker"),
    "dc_manager_headers": build_user_headers("dcm-mo", "DCManager"),
}

CURATOR_USER_ID = "test-curator-ada"
PICKER_USER_ID = "wp-dana"
DC_MANAGER_USER_ID = "dcm-mo"
PLATFORM_ADMIN_USER_ID = "test-platform-admin-1"


def make_customer_account_headers(user_id: str) -> dict:
    """For CustomerAccount (entity_backed:CustomerAccount).

    Pass the actual CustomerAccount.id as user_id whenever the call is
    ownership-gated (order create/release/allocate/cancel, return creation).
    """
    return build_user_headers(user_id, "CustomerAccount")


# Convenience alias matching the plural/role naming used by the fixtures.
make_account_headers = make_customer_account_headers