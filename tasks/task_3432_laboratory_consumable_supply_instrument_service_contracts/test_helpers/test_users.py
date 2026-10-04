"""Caller identities, per PRD section 2.1.

The four operator roles - PlatformAdmin, AccountManager, ServiceDispatcher
and SupplyOps - carry opaque ``X-User-ID`` values the server never compares
against an entity ``id``; their header sets are constants below.

Two roles are entity-backed: for ``LabProcurement`` the ``X-User-ID`` is the
``id`` of the acting Account, and for ``FieldEngineer`` it is the ``id`` of
the acting Engineer.  Their headers can only be built once the backing row
exists, so use ``make_lab_procurement_headers(account["id"])`` and
``make_field_engineer_headers(engineer["id"])``.  The shared constants for
these two roles exist only for tests whose outcome does not depend on the
caller resolving to a real entity (and even those fail authentication on an
empty database - build the entity and use the builder instead).
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ACCOUNT_MANAGER,
    ROLE_FIELD_ENGINEER,
    ROLE_LAB_PROCUREMENT,
    ROLE_PLATFORM_ADMIN,
    ROLE_SERVICE_DISPATCHER,
    ROLE_SUPPLY_OPS,
)

# --- Opaque operator identifiers ----------------------------------------------
ADMIN_USER_ID = "admin-1"
ACCOUNT_MANAGER_USER_ID = "account-manager-1"
ACCOUNT_MANAGER_2_USER_ID = "account-manager-2"
DISPATCHER_USER_ID = "dispatcher-1"
DISPATCHER_2_USER_ID = "dispatcher-2"
SUPPLY_OPS_USER_ID = "supply-ops-1"
SUPPLY_OPS_2_USER_ID = "supply-ops-2"

# --- Ready-made operator header sets -------------------------------------------
ADMIN = build_user_headers(ADMIN_USER_ID, ROLE_PLATFORM_ADMIN)
ACCOUNT_MANAGER = build_user_headers(ACCOUNT_MANAGER_USER_ID, ROLE_ACCOUNT_MANAGER)
ACCOUNT_MANAGER_2 = build_user_headers(ACCOUNT_MANAGER_2_USER_ID, ROLE_ACCOUNT_MANAGER)
DISPATCHER = build_user_headers(DISPATCHER_USER_ID, ROLE_SERVICE_DISPATCHER)
DISPATCHER_2 = build_user_headers(DISPATCHER_2_USER_ID, ROLE_SERVICE_DISPATCHER)
SUPPLY_OPS = build_user_headers(SUPPLY_OPS_USER_ID, ROLE_SUPPLY_OPS)
SUPPLY_OPS_2 = build_user_headers(SUPPLY_OPS_2_USER_ID, ROLE_SUPPLY_OPS)

# Fallback header sets for the entity-backed roles.  NOT ownership-safe: the
# placeholder id resolves to no Account/Engineer row, so any call whose
# authorisation compares X-User-ID against a resource owner rejects them.
# Use the builders below for anything real.
PROCUREMENT_PLACEHOLDER = build_user_headers(
    "test-procurement-placeholder", ROLE_LAB_PROCUREMENT
)
FIELD_ENGINEER_PLACEHOLDER = build_user_headers(
    "test-engineer-placeholder", ROLE_FIELD_ENGINEER
)

TEST_USERS = {
    "platform_admin_headers": ADMIN,
    "account_manager_headers": ACCOUNT_MANAGER,
    "lab_procurement_headers": PROCUREMENT_PLACEHOLDER,
    "service_dispatcher_headers": DISPATCHER,
    "field_engineer_headers": FIELD_ENGINEER_PLACEHOLDER,
    "supply_ops_headers": SUPPLY_OPS,
}


def make_lab_procurement_headers(account_id):
    """Headers for the LabProcurement buyer of the Account with this id.

    Mandatory whenever the call is ownership-gated - order create, submit
    and cancel, service-request create on the account's instruments, reads
    of the account's own resources, and the pull-through projection.
    """
    return build_user_headers(account_id, ROLE_LAB_PROCUREMENT)


def make_field_engineer_headers(engineer_id):
    """Headers for the FieldEngineer whose Engineer row has this id.

    Mandatory on resolve calls: a FieldEngineer may resolve only requests
    whose ``engineer_id`` equals ``X-User-ID``.
    """
    return build_user_headers(engineer_id, ROLE_FIELD_ENGINEER)


def headers_for(role, user_id):
    """Arbitrary role/identity pairing, including deliberate cross-wirings."""
    return build_user_headers(user_id, role)


# --- Malformed authentication header sets (PRD section 2.1) ----------------------
MISSING_USER_ID = {
    "X-User-Role": ROLE_ACCOUNT_MANAGER,
    "Content-Type": "application/json",
}

MISSING_USER_ROLE = {
    "X-User-ID": ACCOUNT_MANAGER_USER_ID,
    "Content-Type": "application/json",
}

EMPTY_USER_ID = {
    "X-User-ID": "",
    "X-User-Role": ROLE_ACCOUNT_MANAGER,
    "Content-Type": "application/json",
}

EMPTY_USER_ROLE = {
    "X-User-ID": ACCOUNT_MANAGER_USER_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}

UNKNOWN_ROLE = {
    "X-User-ID": ACCOUNT_MANAGER_USER_ID,
    "X-User-Role": "LabJanitor",
    "Content-Type": "application/json",
}
