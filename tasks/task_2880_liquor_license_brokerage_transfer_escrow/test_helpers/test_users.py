"""Pre-built role headers for every role the platform recognises.

Every request must carry both ``X-User-ID`` and ``X-User-Role``.

Three roles are entity-backed: for ``Broker`` the ``X-User-ID`` is the ``id`` of
the acting ``Brokerage``, for ``Buyer`` it is the ``id`` of the acting
``BuyerProfile``, and for ``Seller`` it is the ``id`` of the acting
``SellerProfile``. Ownership-gated calls MUST therefore use the per-instance
builders below with the real entity ``id``.

The remaining three roles — ``PlatformAdmin``, ``RegulatorAnalyst`` and
``EscrowOfficer`` — are opaque: their ``X-User-ID`` is an operator identifier
that is never compared against any record's ``id``.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque analyst identifiers. The analyst who accepts an application into review
# has their X-User-ID written to accepted_by_analyst_id, and the analyst issuing
# the decision must present a different one.
ANALYST_ONE = "analyst-1"
ANALYST_TWO = "analyst-2"


TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "regulator_analyst_headers": build_user_headers(ANALYST_ONE, "RegulatorAnalyst"),
    "regulator_analyst_two_headers": build_user_headers(ANALYST_TWO, "RegulatorAnalyst"),
    "escrow_officer_headers": build_user_headers("escrow-1", "EscrowOfficer"),
    # Entity-backed roles — fallbacks for tests that do not exercise ownership.
    "broker_headers": build_user_headers("test-brokerage-1", "Broker"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
    "seller_headers": build_user_headers("test-seller-1", "Seller"),
}


def make_broker_headers(brokerage_id: str) -> dict:
    """For the Broker role. Pass the acting Brokerage's ``id``."""
    return build_user_headers(brokerage_id, "Broker")


def make_buyer_headers(buyer_id: str) -> dict:
    """For the Buyer role. Pass the acting BuyerProfile's ``id``."""
    return build_user_headers(buyer_id, "Buyer")


def make_seller_headers(seller_id: str) -> dict:
    """For the Seller role. Pass the acting SellerProfile's ``id``."""
    return build_user_headers(seller_id, "Seller")


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    """For the PlatformAdmin role — an opaque reference-data operator identifier."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_regulator_analyst_headers(analyst_id: str = ANALYST_ONE) -> dict:
    """For the RegulatorAnalyst role — an opaque licensing-authority identifier."""
    return build_user_headers(analyst_id, "RegulatorAnalyst")


def make_escrow_officer_headers(officer_id: str = "escrow-1") -> dict:
    """For the EscrowOfficer role — an opaque escrow-holder identifier."""
    return build_user_headers(officer_id, "EscrowOfficer")


def make_headers(user_id: str, role: str) -> dict:
    """Raw header builder, for tests that need an unrecognised role or an empty
    header value. An empty string is sent as an empty string — never as
    whitespace."""
    return build_user_headers(user_id, role)
