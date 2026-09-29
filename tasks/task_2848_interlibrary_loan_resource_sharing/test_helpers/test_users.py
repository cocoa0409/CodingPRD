"""Header builders for the six roles.

Four roles carry opaque operator identifiers that are never compared against any
row's `id`. The two entity-backed roles must instead present the `id` of the row
they act as: `Patron` presents the acting `Patron` row's `id` and `PartnerAgent`
presents the acting `Partner` row's `id`.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identifiers for the four non-entity-backed roles.
ADMIN_USER_ID = "admin-01"
ILL_STAFF_USER_ID = "ill-staff-01"
ILL_STAFF_ALT_USER_ID = "ill-staff-02"
ACQ_USER_ID = "acq-01"
ACQ_ALT_USER_ID = "acq-02"
ACCOUNTANT_USER_ID = "acct-01"

TEST_USERS = {
    "admin": {"user_id": ADMIN_USER_ID, "role": UserRole.LIBRARY_ADMIN},
    "ill_staff": {"user_id": ILL_STAFF_USER_ID, "role": UserRole.ILL_BORROWING_STAFF},
    "ill_staff_alt": {
        "user_id": ILL_STAFF_ALT_USER_ID,
        "role": UserRole.ILL_BORROWING_STAFF,
    },
    "acquisitions": {
        "user_id": ACQ_USER_ID,
        "role": UserRole.ACQUISITIONS_LIBRARIAN,
    },
    "acquisitions_alt": {
        "user_id": ACQ_ALT_USER_ID,
        "role": UserRole.ACQUISITIONS_LIBRARIAN,
    },
    "accountant": {
        "user_id": ACCOUNTANT_USER_ID,
        "role": UserRole.CONSORTIUM_ACCOUNTANT,
    },
}


def make_headers(user_id: str, role: str) -> dict:
    """Build the `X-User-ID` / `X-User-Role` pair for any role."""
    return build_user_headers(user_id, role)


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.LIBRARY_ADMIN)


def make_ill_staff_headers(user_id: str = ILL_STAFF_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.ILL_BORROWING_STAFF)


def make_acquisitions_headers(user_id: str = ACQ_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.ACQUISITIONS_LIBRARIAN)


def make_accountant_headers(user_id: str = ACCOUNTANT_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.CONSORTIUM_ACCOUNTANT)


def make_patron_headers(patron_id: str) -> dict:
    """`X-User-ID` is the `id` of the acting `Patron` row."""
    return build_user_headers(patron_id, UserRole.PATRON)


def make_partner_agent_headers(partner_id: str) -> dict:
    """`X-User-ID` is the `id` of the acting `Partner` row."""
    return build_user_headers(partner_id, UserRole.PARTNER_AGENT)


def headers_missing_user_id(role: str = UserRole.ILL_BORROWING_STAFF) -> dict:
    """Only the role header, so the `X-User-ID` header is absent."""
    return {"X-User-Role": role}


def headers_missing_role(user_id: str = ILL_STAFF_USER_ID) -> dict:
    """Only the id header, so the `X-User-Role` header is absent."""
    return {"X-User-ID": user_id}


def headers_with_unknown_role(user_id: str = ILL_STAFF_USER_ID) -> dict:
    """A role string that is not one of the six recognized role names."""
    return {"X-User-ID": user_id, "X-User-Role": "Librarian"}


def headers_with_empty_user_id(role: str = UserRole.ILL_BORROWING_STAFF) -> dict:
    return {"X-User-ID": "", "X-User-Role": role}
