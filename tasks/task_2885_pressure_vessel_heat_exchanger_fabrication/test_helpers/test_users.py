"""Header builders for the two authentication headers of PRD §2.1.

`ShopAdmin` carries an opaque operator identifier that the server never resolves
against a `Personnel` row, so a module-level constant is correct for it. The four
person-backed roles must each carry the `id` of their own registered person, so
every builder for those roles takes that `personnel_id` explicitly: there is no
shared constant that could accidentally make two distinct owners look like one
actor to the segregation-of-duties checks.
"""

from .constants import (
    HEADER_USER_ID,
    HEADER_USER_ROLE,
    ROLE_AUTHORIZED_INSPECTOR,
    ROLE_CODE_TO_ROLE,
    ROLE_DESIGN_ENGINEER,
    ROLE_QC_INSPECTOR,
    ROLE_SHOP_ADMIN,
    ROLE_WELDING_ENGINEER,
)

# §2.1: "When `X-User-Role` is `ShopAdmin`, `X-User-ID` is an opaque operator
# identifier not tied to any persisted entity."
SHOP_ADMIN_OPERATOR_ID = "shop-admin-operator-01"
SECOND_SHOP_ADMIN_OPERATOR_ID = "shop-admin-operator-02"

# A role string that is well formed text but is not one of the five declared.
UNDECLARED_ROLE = "ShopForeman"

_JSON_CONTENT_TYPE = {"Content-Type": "application/json"}


def _headers(user_id, role):
    built = dict(_JSON_CONTENT_TYPE)
    if user_id is not None:
        built[HEADER_USER_ID] = user_id
    if role is not None:
        built[HEADER_USER_ROLE] = role
    return built


def shop_admin_headers(user_id=SHOP_ADMIN_OPERATOR_ID):
    """Headers for the quality-manager capacity of §2.1."""
    return _headers(user_id, ROLE_SHOP_ADMIN)


def make_design_engineer_headers(personnel_id):
    """Headers for a `DesignEngineer` acting as the given `Personnel` row."""
    return _headers(personnel_id, ROLE_DESIGN_ENGINEER)


def make_welding_engineer_headers(personnel_id):
    """Headers for a `WeldingEngineer` acting as the given `Personnel` row."""
    return _headers(personnel_id, ROLE_WELDING_ENGINEER)


def make_qc_inspector_headers(personnel_id):
    """Headers for a `QCInspector` acting as the given `Personnel` row."""
    return _headers(personnel_id, ROLE_QC_INSPECTOR)


def make_authorized_inspector_headers(personnel_id):
    """Headers for an `AuthorizedInspector` acting as the given `Personnel` row."""
    return _headers(personnel_id, ROLE_AUTHORIZED_INSPECTOR)


def make_headers(role, user_id):
    """Headers for an arbitrary declared role and identifier pairing."""
    return _headers(user_id, role)


def headers_for_role_code(role_code, personnel_id):
    """Headers whose declared role is the one matching a person's `role_code`."""
    return _headers(personnel_id, ROLE_CODE_TO_ROLE[role_code])


def headers_for_person(person):
    """Headers for a registered person record, derived from its own `role_code`."""
    return headers_for_role_code(person["role_code"], person["id"])


# --- Malformed-authentication header builders (§2.1, §2.8 step 1) ------------
# Note: a header whose value is meant to be "absent" is omitted entirely, and a
# header whose value is meant to be "blank" is the empty string. Whitespace is
# never used, because a whitespace-only header value is not a blank value.


def headers_missing_user_id(role):
    """Headers that declare a role but carry no `X-User-ID` at all."""
    return _headers(None, role)


def headers_blank_user_id(role):
    """Headers whose `X-User-ID` is present but blank."""
    return _headers("", role)


def headers_missing_role(user_id="anonymous-operator"):
    """Headers that carry an identifier but declare no `X-User-Role`."""
    return _headers(user_id, None)


def headers_blank_role(user_id="anonymous-operator"):
    """Headers whose `X-User-Role` is present but blank."""
    return _headers(user_id, "")


def headers_undeclared_role(user_id="anonymous-operator", role=UNDECLARED_ROLE):
    """Headers declaring a role that is not one of the five exact strings."""
    return _headers(user_id, role)


def headers_no_authentication():
    """Headers carrying neither authentication header."""
    return dict(_JSON_CONTENT_TYPE)
