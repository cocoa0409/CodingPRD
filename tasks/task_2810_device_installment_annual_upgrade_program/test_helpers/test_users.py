"""Pre-built identity headers for the six roles the program recognises.

`Customer` is the only role whose `X-User-ID` is the id of a persisted record —
"When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting
`Customer` record". Every ownership-gated call by a customer must therefore be
made with :func:`make_customer_headers` carrying that customer's real id. The
other five roles carry opaque operator identifiers that are never compared to an
entity id, so their shared constants below are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers. Two distinct ids exist for the roles that take
# part in a segregation-of-duties comparison.
ASSOCIATE_USER_ID = "u-assoc-1"
ASSOCIATE_USER_ID_2 = "u-assoc-2"
UNDERWRITER_USER_ID = "u-uw-1"
UNDERWRITER_USER_ID_2 = "u-uw-2"
TECHNICIAN_USER_ID = "u-tech-1"
TECHNICIAN_USER_ID_2 = "u-tech-2"
COLLECTIONS_USER_ID = "u-coll-1"
ADMIN_USER_ID = "u-admin-1"
PLACEHOLDER_CUSTOMER_USER_ID = "u-cust-placeholder"

TEST_USERS = {
    # Opaque roles: the shared constant is the canonical identity.
    "associate_headers": build_user_headers(ASSOCIATE_USER_ID, "RetailAssociate"),
    "associate_2_headers": build_user_headers(ASSOCIATE_USER_ID_2, "RetailAssociate"),
    "underwriter_headers": build_user_headers(UNDERWRITER_USER_ID, "CreditUnderwriter"),
    "underwriter_2_headers": build_user_headers(UNDERWRITER_USER_ID_2, "CreditUnderwriter"),
    "technician_headers": build_user_headers(TECHNICIAN_USER_ID, "ServiceTechnician"),
    "technician_2_headers": build_user_headers(TECHNICIAN_USER_ID_2, "ServiceTechnician"),
    "collections_headers": build_user_headers(COLLECTIONS_USER_ID, "CollectionsOfficer"),
    "admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdmin"),
    # Customer is entity_backed: this constant is a fallback for tests that do
    # NOT exercise ownership (a 400 on a malformed payload, a 404 on a missing
    # resource, a 403 on an endpoint the role does not appear on). Any
    # ownership-gated call must use make_customer_headers(customer["id"]).
    "customer_headers": build_user_headers(PLACEHOLDER_CUSTOMER_USER_ID, "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """Identity headers for a `Customer`. Pass the acting Customer record's own
    `id`: ownership checks compare the resource's owning-customer reference to
    `X-User-ID`."""
    return build_user_headers(customer_id, "Customer")


def make_associate_headers(user_id: str = ASSOCIATE_USER_ID) -> dict:
    """Identity headers for a `RetailAssociate` (opaque operator identifier)."""
    return build_user_headers(user_id, "RetailAssociate")


def make_underwriter_headers(user_id: str = UNDERWRITER_USER_ID) -> dict:
    """Identity headers for a `CreditUnderwriter` (opaque operator identifier)."""
    return build_user_headers(user_id, "CreditUnderwriter")


def make_technician_headers(user_id: str = TECHNICIAN_USER_ID) -> dict:
    """Identity headers for a `ServiceTechnician` (opaque operator identifier)."""
    return build_user_headers(user_id, "ServiceTechnician")


def make_collections_headers(user_id: str = COLLECTIONS_USER_ID) -> dict:
    """Identity headers for a `CollectionsOfficer` (opaque operator identifier)."""
    return build_user_headers(user_id, "CollectionsOfficer")


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    """Identity headers for a `ProgramAdmin` (opaque operator identifier)."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_headers_for_role(role: str, user_id: str) -> dict:
    """Identity headers for an arbitrary declared role."""
    return build_user_headers(user_id, role)


ADMIN_HEADERS = TEST_USERS["admin_headers"]
ASSOCIATE_HEADERS = TEST_USERS["associate_headers"]
UNDERWRITER_HEADERS = TEST_USERS["underwriter_headers"]
TECHNICIAN_HEADERS = TEST_USERS["technician_headers"]
TECHNICIAN_2_HEADERS = TEST_USERS["technician_2_headers"]
COLLECTIONS_HEADERS = TEST_USERS["collections_headers"]
