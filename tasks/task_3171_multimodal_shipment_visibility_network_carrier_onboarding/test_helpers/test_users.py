"""Caller identities for the six declared roles.

Every request carries an ``X-User-ID`` and an ``X-User-Role`` header. Three
roles are entity-backed: the acting user's identifier is matched against the
foreign key of the resource being touched, so a CarrierRep must present a real
carrier's ``id``, a ShipperRep a real shipper's ``id`` and a ConsigneeRep a
real consignee's ``id``. Those three therefore get per-instance builders that
take the identifier the test just created. The other three roles are opaque
operator identifiers never compared to any stored row, so a stable constant
identifier is enough.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_CARRIER_REP,
    ROLE_CONSIGNEE_REP,
    ROLE_CUSTOMER_SERVICE,
    ROLE_NETWORK_OPS,
    ROLE_PLATFORM_ADMIN,
    ROLE_SHIPPER_REP,
)

# Stable opaque identifiers for the roles that are not matched against a row.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": build_user_headers("11111111-1111-4111-8111-111111111111", ROLE_PLATFORM_ADMIN),
    "network_ops": build_user_headers("22222222-2222-4222-8222-222222222222", ROLE_NETWORK_OPS),
    "customer_service": build_user_headers("33333333-3333-4333-8333-333333333333", ROLE_CUSTOMER_SERVICE),
    # Fallbacks for entity-backed roles, safe ONLY where ownership is not checked.
    "carrier_rep": build_user_headers("44444444-4444-4444-8444-444444444444", ROLE_CARRIER_REP),
    "shipper_rep": build_user_headers("55555555-5555-4555-8555-555555555555", ROLE_SHIPPER_REP),
    "consignee_rep": build_user_headers("66666666-6666-4666-8666-666666666666", ROLE_CONSIGNEE_REP),
}

PLATFORM_ADMIN_HEADERS = TEST_USERS["platform_admin"]
NETWORK_OPS_HEADERS = TEST_USERS["network_ops"]
CUSTOMER_SERVICE_HEADERS = TEST_USERS["customer_service"]


def make_carrier_rep_headers(carrier_id: str) -> Dict[str, str]:
    """Headers for a CarrierRep acting for the given carrier.

    Ownership-gated carrier calls (submit-credentials, heartbeats, event
    ingest, appointment booking and completion) must pass the actual
    carrier's ``id`` here.
    """
    return build_user_headers(carrier_id, ROLE_CARRIER_REP)


def make_shipper_rep_headers(shipper_id: str) -> Dict[str, str]:
    """Headers for a ShipperRep acting for the given shipper.

    Ownership-gated shipper calls (consignee, purchase order, shipment and
    grant creation, cancel, link confirm/reject) must pass the actual
    shipper's ``id`` here.
    """
    return build_user_headers(shipper_id, ROLE_SHIPPER_REP)


def make_consignee_rep_headers(consignee_id: str) -> Dict[str, str]:
    """Headers for a ConsigneeRep acting for the given consignee."""
    return build_user_headers(consignee_id, ROLE_CONSIGNEE_REP)
