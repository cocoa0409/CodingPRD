"""Pre-built role headers for every role in the PRD (§2.1).

Shipper: X-User-ID is an opaque party identifier recorded as shipper_id —
use make_shipper_headers(shipper_id) so the header equals the filing's
shipper_id. CarrierOperator: X-User-ID is the acting Carrier's id — use
make_carrier_operator_headers(carrier_id) after creating the carrier.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import SHIPPER_ADA

# Shared constants — PlatformAdmin and BoardAdjudicator are opaque operator
# identities never compared to any resource id, so these are canonical.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "board_adjudicator_headers": build_user_headers("test-board-1", "BoardAdjudicator"),
    # Fallback shipper identity for tests that do not exercise ownership.
    "shipper_headers": build_user_headers(SHIPPER_ADA, "Shipper"),
}


def make_shipper_headers(shipper_id: str) -> dict:
    """Shipper headers whose X-User-ID equals the given party identifier."""
    return build_user_headers(shipper_id, "Shipper")


def make_carrier_operator_headers(carrier_id: str) -> dict:
    """CarrierOperator headers whose X-User-ID equals the acting Carrier.id.

    Mandatory for ownership-gated calls (merger create/amend, service
    assurance plans, abandonment create, carrier-side evidence, PAYMENT
    reparation events): pass the real carrier's id.
    """
    return build_user_headers(carrier_id, "CarrierOperator")
