"""Authentication headers for each role.

Four of the five roles carry an opaque operator identifier that the server
never resolves against any stored row, so a fixed literal is fine for them.
The shopper role is different: its identifier must be the ``id`` of a real
customer account, so shopper headers are always built at call time from an
account created during setup.
"""

from .types import UserRole

# Opaque operator identifiers.  Two distinct wave planners are provided because
# consolidating and dispatching the same wave must be done by different people.
ADMIN_USER_ID = "admin-user-0001"
WAVE_PLANNER_USER_ID = "wave-planner-0001"
WAVE_PLANNER_2_USER_ID = "wave-planner-0002"
PICK_OPERATOR_USER_ID = "pick-operator-0001"
PICK_OPERATOR_2_USER_ID = "pick-operator-0002"
GRID_ENGINEER_USER_ID = "grid-engineer-0001"

#: A syntactically fine identifier that resolves to no customer account.
UNKNOWN_CUSTOMER_USER_ID = "00000000-0000-4000-8000-000000000999"


def _headers(user_id, role):
    return {"X-User-ID": user_id, "X-User-Role": role}


TEST_USERS = {
    "admin": _headers(ADMIN_USER_ID, UserRole.FULFILLMENT_ADMIN.value),
    "wave_planner": _headers(WAVE_PLANNER_USER_ID, UserRole.WAVE_PLANNER.value),
    "wave_planner_2": _headers(WAVE_PLANNER_2_USER_ID, UserRole.WAVE_PLANNER.value),
    "pick_operator": _headers(PICK_OPERATOR_USER_ID, UserRole.PICK_OPERATOR.value),
    "pick_operator_2": _headers(PICK_OPERATOR_2_USER_ID, UserRole.PICK_OPERATOR.value),
    "grid_engineer": _headers(GRID_ENGINEER_USER_ID, UserRole.GRID_ENGINEER.value),
    "unknown_customer": _headers(
        UNKNOWN_CUSTOMER_USER_ID, UserRole.CUSTOMER.value
    ),
}

ADMIN_HEADERS = TEST_USERS["admin"]
WAVE_PLANNER_HEADERS = TEST_USERS["wave_planner"]
WAVE_PLANNER_2_HEADERS = TEST_USERS["wave_planner_2"]
PICK_OPERATOR_HEADERS = TEST_USERS["pick_operator"]
PICK_OPERATOR_2_HEADERS = TEST_USERS["pick_operator_2"]
GRID_ENGINEER_HEADERS = TEST_USERS["grid_engineer"]
UNKNOWN_CUSTOMER_HEADERS = TEST_USERS["unknown_customer"]


def make_customer_headers(customer_account_id):
    """Headers for a shopper acting as the given customer account."""
    return _headers(str(customer_account_id), UserRole.CUSTOMER.value)


def make_admin_headers(user_id=ADMIN_USER_ID):
    return _headers(str(user_id), UserRole.FULFILLMENT_ADMIN.value)


def make_wave_planner_headers(user_id=WAVE_PLANNER_USER_ID):
    return _headers(str(user_id), UserRole.WAVE_PLANNER.value)


def make_pick_operator_headers(user_id=PICK_OPERATOR_USER_ID):
    return _headers(str(user_id), UserRole.PICK_OPERATOR.value)


def make_grid_engineer_headers(user_id=GRID_ENGINEER_USER_ID):
    return _headers(str(user_id), UserRole.GRID_ENGINEER.value)


def headers_with_role(role_value, user_id=ADMIN_USER_ID):
    """Headers carrying an arbitrary role string, for role-rejection checks."""
    return _headers(str(user_id), role_value)


# ─── Malformed credential variants ───────────────────────────────────────────
# Note the empty strings below are genuinely empty, not whitespace: the PRD
# rejects a header that is "absent or present but empty".

MISSING_USER_ID_HEADERS = {"X-User-Role": UserRole.FULFILLMENT_ADMIN.value}
MISSING_ROLE_HEADERS = {"X-User-ID": ADMIN_USER_ID}
EMPTY_USER_ID_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": UserRole.FULFILLMENT_ADMIN.value,
}
EMPTY_ROLE_HEADERS = {"X-User-ID": ADMIN_USER_ID, "X-User-Role": ""}
NO_HEADERS = {}
UNKNOWN_ROLE_HEADERS = {"X-User-ID": ADMIN_USER_ID, "X-User-Role": "WarehouseKing"}
