"""Difficulty tests (queue A): referral pending-count compensating invariant
(routing +1 / TTL expiry -1 nets to zero)."""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    create_certified_shop, create_referral,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
DEALER = TEST_USERS["dealer_headers"]


def test_referral_pending_count_roundtrip_zero_drift(api):
    """PRD §3.8: "If neither happens, the clock sweep expires the referral at
    72 hours past routed_at, moving it ROUTED → EXPIRED and decrementing the
    counter as the exact compensation of the routing increment." PRD §3.8:
    "A successful route ... increments that shop's pending_referral_count."

    Design: Difficulty/compensating_invariant/referral_pending_count_roundtrip_zero_drift
    """
    shop, _cycle = create_certified_shop(
        legal_name="Counter Body", state_code="ID", zip_code="83701",
        latitude=43.61, longitude=-116.2)
    ref1 = create_referral(DEALER, consumer_zip="83701", source_type="DEALER",
                           source_reference="DLR-1", vin="1HGCV1F34LA000013")
    ref2 = create_referral(DEALER, consumer_zip="83701", source_type="DEALER",
                           source_reference="DLR-1", vin="1HGCV1F34LA000014")
    assert ref1["status"] == "ROUTED" and ref2["status"] == "ROUTED"

    mid = validate_success(api.get_shop(shop["id"], ADMIN))
    assert mid["pending_referral_count"] == 2

    get_success_data(api.set_clock("2026-09-04T02:00:01Z", ADMIN))
    for ref in (ref1, ref2):
        assert validate_success(api.get_referral(ref["id"], ADMIN))["status"] == "EXPIRED"
    final = validate_success(api.get_shop(shop["id"], ADMIN))
    assert final["pending_referral_count"] == 0


def test_referral_pending_count_accept_decrements(api):
    """PRD §3.8: "acceptance moves the referral ROUTED → ACCEPTED and
    decrements the shop's pending_referral_count."

    Design: Difficulty/compensating_invariant/referral_pending_count_roundtrip_zero_drift
    """
    shop, _cycle = create_certified_shop(
        TEST_USERS["auditor2_headers"],
        legal_name="Counter Body 2", state_code="ID", zip_code="83702",
        latitude=43.61, longitude=-116.2)
    ref = create_referral(DEALER, consumer_zip="83702", source_type="DEALER",
                          source_reference="DLR-2", vin="1HGCV1F34LA000051")
    assert ref["status"] == "ROUTED"
    from test_helpers import sm
    mid = validate_success(api.get_shop(shop["id"], ADMIN))
    assert mid["pending_referral_count"] == 1
    accepted = validate_success(api.accept_referral(ref["id"], sm(shop["id"])))
    assert accepted["status"] == "ACCEPTED"
    final = validate_success(api.get_shop(shop["id"], ADMIN))
    assert final["pending_referral_count"] == 0
