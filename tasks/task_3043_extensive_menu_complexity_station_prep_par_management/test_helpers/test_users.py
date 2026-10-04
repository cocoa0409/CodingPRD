"""Caller identities and pre-built role headers.

PRD section 2.1 splits identity in two.  For ``SystemAdmin``, ``MenuAdmin``,
and ``InventoryController`` the ``X-User-ID`` is an opaque operator identifier
that the server never compares against an entity ``id`` — their headers are
constants below.  For ``KitchenManager``, ``PrepCook``, ``LineCook``, and
``PastryChef`` the ``X-User-ID`` IS the ``id`` of the acting Cook; on any call
whose outcome depends on cook identity (attribution of a waste entry,
``requested_by_cook_id`` on a par proposal, the segregation-of-duties
comparison at approval), use the ``make_*_headers`` builders with the real
cook id, never the opaque constants.
"""

from prd_bench_local_runner.testing import build_user_headers

# -- Opaque operator identifiers (PRD section 2.1) ---------------------------

SYSTEM_ADMIN_USER_ID = "sysadmin-1"
MENU_ADMIN_USER_ID = "menu-admin-1"
INVENTORY_CONTROLLER_USER_ID = "ic-dana"

# Bootstrap id used only for the very first Cook row (the kitchen manager who
# then creates the other cooks); after that row exists, KitchenManager calls
# use make_kitchen_manager_headers(cook_id).
BOOTSTRAP_KITCHEN_MANAGER_ID = "bootstrap-kitchen-manager"

TEST_USERS = {
    "system_admin_headers": build_user_headers(
        SYSTEM_ADMIN_USER_ID, "SystemAdmin"),
    "menu_admin_headers": build_user_headers(
        MENU_ADMIN_USER_ID, "MenuAdmin"),
    "inventory_controller_headers": build_user_headers(
        INVENTORY_CONTROLLER_USER_ID, "InventoryController"),
    "bootstrap_kitchen_manager_headers": build_user_headers(
        BOOTSTRAP_KITCHEN_MANAGER_ID, "KitchenManager"),
}


def system_admin_headers():
    """SystemAdmin (opaque identity)."""
    return TEST_USERS["system_admin_headers"]


def menu_admin_headers():
    """MenuAdmin (opaque identity)."""
    return TEST_USERS["menu_admin_headers"]


def inventory_controller_headers():
    """InventoryController (opaque identity)."""
    return TEST_USERS["inventory_controller_headers"]


def bootstrap_kitchen_manager_headers():
    """KitchenManager headers with the bootstrap id — only valid before the
    first Cook row exists."""
    return TEST_USERS["bootstrap_kitchen_manager_headers"]


def make_kitchen_manager_headers(cook_id: str):
    """KitchenManager headers whose X-User-ID is the real Cook.id of the
    manager — mandatory for par approvals and any ownership-gated call."""
    return build_user_headers(cook_id, "KitchenManager")


def make_prep_cook_headers(cook_id: str):
    """PrepCook headers whose X-User-ID is the real Cook.id."""
    return build_user_headers(cook_id, "PrepCook")


def make_line_cook_headers(cook_id: str):
    """LineCook headers whose X-User-ID is the real Cook.id — mandatory for
    par proposals and waste recording, which attribute the cook id."""
    return build_user_headers(cook_id, "LineCook")


def make_pastry_chef_headers(cook_id: str):
    """PastryChef headers whose X-User-ID is the real Cook.id."""
    return build_user_headers(cook_id, "PastryChef")
