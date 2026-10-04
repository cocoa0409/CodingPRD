"""Role headers for the four roles of PRD §2.1.

`Customer`, `Picker`, and `Driver` are entity-backed roles: `X-User-ID` must
be the `id` of a real persisted entity, so ownership-gated calls MUST use the
per-instance builders below with the actual entity id. `SiteOps` is an opaque
operator identifier not tied to any persisted entity, so a shared constant is
canonical for it.
"""

from prd_bench_local_runner.testing import build_user_headers

SITE_OPS_ID = "site-ops-console-1"

TEST_USERS = {
    # Opaque identity — never compared to an entity id (PRD §2.1).
    "site_ops_headers": build_user_headers(SITE_OPS_ID, "SiteOps"),
    # Entity-backed identities — these shared constants are only valid for
    # tests that deliberately exercise a non-existent acting identity, or for
    # calls where the role check never consults ownership.
    "unknown_customer_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000000", "Customer"
    ),
    "unknown_picker_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000000", "Picker"
    ),
    "unknown_driver_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000000", "Driver"
    ),
}


def make_customer_headers(customer_id: str) -> dict:
    """Headers for a `Customer` caller; `customer_id` must be a real `Customer.id`."""
    return build_user_headers(customer_id, "Customer")


def make_picker_headers(picker_id: str) -> dict:
    """Headers for a `Picker` caller; `picker_id` must be a real `Picker.id`."""
    return build_user_headers(picker_id, "Picker")


def make_driver_headers(driver_id: str) -> dict:
    """Headers for a `Driver` caller; `driver_id` must be a real `Driver.id`."""
    return build_user_headers(driver_id, "Driver")


def make_site_ops_headers(operator_id: str = SITE_OPS_ID) -> dict:
    """Headers for a `SiteOps` caller (opaque identifier)."""
    return build_user_headers(operator_id, "SiteOps")


SITE_OPS_HEADERS = TEST_USERS["site_ops_headers"]
