"""Pre-built identity headers for every role the API recognises.

Two of the five roles are backed by a persisted entity, and for those the
``X-User-ID`` must be the entity's own ``id``:

* ``StoreManager`` — ``X-User-ID`` is the acting ``Store``'s ``id``.
* ``Driver``       — ``X-User-ID`` is the acting ``Driver``'s ``id``.

The remaining three roles (``Dispatcher``, ``ComplianceOfficer``,
``CustomerCareAgent``) carry an opaque operator identifier that the server never
compares to any entity's ``id``, so a shared constant is the canonical form.

Use ``make_manager_headers(store["id"])`` / ``make_driver_headers(driver["id"])``
for every ownership-gated call. The shared ``TEST_USERS`` manager and driver
entries exist only for tests that deliberately exercise a *foreign* identity, or
for store registration, where there is no target resource to scope against.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers.
DISPATCHER_USER_ID = "dispatcher-1"
COMPLIANCE_OFFICER_USER_ID = "officer-1"
SECOND_COMPLIANCE_OFFICER_USER_ID = "officer-2"
CUSTOMER_CARE_USER_ID = "care-agent-1"

# Accepted on store registration only, where any non-empty caller identity works.
BOOTSTRAP_MANAGER_USER_ID = "boot"

TEST_USERS = {
    # entity_backed:Store — a bootstrap identity, valid for registration and for
    # tests that want a manager who owns nothing.
    "store_manager_headers": build_user_headers(BOOTSTRAP_MANAGER_USER_ID, "StoreManager"),
    # entity_backed:Driver — a driver identity that owns nothing.
    "driver_headers": build_user_headers("driver-not-a-real-id", "Driver"),
    # opaque roles.
    "dispatcher_headers": build_user_headers(DISPATCHER_USER_ID, "Dispatcher"),
    "compliance_officer_headers": build_user_headers(COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"),
    "customer_care_headers": build_user_headers(CUSTOMER_CARE_USER_ID, "CustomerCareAgent"),
}

DISPATCHER_HEADERS = TEST_USERS["dispatcher_headers"]
COMPLIANCE_HEADERS = TEST_USERS["compliance_officer_headers"]
CARE_HEADERS = TEST_USERS["customer_care_headers"]
SECOND_COMPLIANCE_HEADERS = build_user_headers(SECOND_COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer")
BOOTSTRAP_MANAGER_HEADERS = TEST_USERS["store_manager_headers"]


def make_manager_headers(store_id: str) -> dict:
    """Headers for a StoreManager acting as the owner of ``store_id``."""
    return build_user_headers(store_id, "StoreManager")


def make_driver_headers(driver_id: str) -> dict:
    """Headers for a Driver acting as ``driver_id``."""
    return build_user_headers(driver_id, "Driver")


def make_dispatcher_headers(user_id: str = DISPATCHER_USER_ID) -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_compliance_headers(user_id: str = COMPLIANCE_OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_care_headers(user_id: str = CUSTOMER_CARE_USER_ID) -> dict:
    return build_user_headers(user_id, "CustomerCareAgent")


def headers_for(role: str, user_id: str) -> dict:
    """Generic builder — useful for parametrized role tests."""
    return build_user_headers(user_id, role)
