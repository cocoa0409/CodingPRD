"""Service-score sections: component rounding order, thresholds and tier remapping."""
from decimal import Decimal, ROUND_HALF_UP

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx

SECTION_OPEN = "2026-01-05T00:00:00Z"


def _round2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _conforming_score(cf, ot, gc, rr) -> float:
    return _round2(0.35 * (100 - cf) + 0.30 * ot + 0.25 * gc + 0.10 * (100 - rr))


def _scenario_listed_seller_with_section():
    """Approved seller, one LISTED device, one OPEN section anchored in the past."""
    scenario = fx.setup_listed_device()
    section = fx.open_section(scenario["seller"]["id"], SECTION_OPEN)
    scenario["section"] = section
    return scenario


def _reject_routed_claim(seller_id, listing_id, reason="BATTERY_SWELL"):
    claim = fx.create_claim_under_review(seller_id, listing_id, claim_reason_code=reason)
    validate_success(
        fx.reject_claim(claim["id"]),
    )
    return claim


def _resolve_on_time_repair(seller_id, listing_id, start_iso, reason="TOUCH_FAILURE", carrier="CARRIER_A"):
    """Uphold a REPAIR claim and route it back, leaving the claim RESOLVED on time."""
    claim = fx.create_upheld_claim(seller_id, listing_id, resolution_type="REPAIR",
                                   claim_reason_code=reason)
    validate_success(
        fx.route_claim_return(
            claim["id"], return_carrier=carrier, return_shipment_start=start_iso
        )
    )
    return claim


class TestComponentRoundingOrder:
    def test_score_uses_rounded_components_before_weighting(self, api):
        """PRD §3.7: "Four components follow, each rounded half-up to two decimals *before* it is weighted — this ordering is the only conforming one."
        PRD §3.7: "The service score is then 0.35 times the complement of the claim failure rate, plus 0.30 times the on-time resolution rate, plus 0.25 times the grading compliance rate, plus 0.10 times the complement of the return rate, with the weighted sum rounded half-up to two decimals once more."

        Design: Difficulty/combinatorial_formula/seller_score_component_rounding_order
        """
        # The fourth in-window listing is submitted *before* the section is
        # opened: PRD §3.9 fires the suspension cascade on every open-section
        # recompute, and a submission needs an APPROVED seller, so the whole
        # listing set is built first and the section opened over it.
        scenario = fx.setup_listed_device()
        seller_id = scenario["seller"]["id"]
        listing_id = scenario["listing"]["id"]
        reservation_id = scenario["servicing_reservation_id"]
        fx.create_listing(seller_id, list_price_cents=149000)
        scenario["section"] = fx.open_section(seller_id, SECTION_OPEN)

        _reject_routed_claim(seller_id, listing_id, "BATTERY_SWELL")
        _reject_routed_claim(seller_id, listing_id, "CAMERA_FAILURE")
        _resolve_on_time_repair(seller_id, listing_id, "2026-09-06T00:00:00Z", "TOUCH_FAILURE")
        validate_success(
            fx.remediate_reservation(reservation_id, repair_estimate_cents=18000)
        )
        fx.setup_disclosed_verification(seller_id, listing_id)

        section = fx.read_section(scenario["section"]["id"])
        assert section["claim_failure_rate_pct"] == 66.67
        assert section["on_time_resolution_pct"] == 33.33
        assert section["grading_compliance_pct"] == 0.00
        assert section["return_rate_pct"] == 0.00

        conforming = _conforming_score(66.67, 33.33, 0.00, 0.00)
        assert section["service_score"] == 31.66, (
            f"Expected the rounded-component weighted score 31.66, got {section['service_score']}"
        )
        assert section["service_score"] == conforming
        assert section["service_score"] != 31.67, (
            "weighting the raw unrounded ratios is the non-conforming order and would give 31.67"
        )
        seller = validate_success(
            api.get(f"/v1/sellers/{seller_id}", headers=fx.ADMIN)
        )
        assert seller["performance_tier"] == "SUSPENDED", (
            "a recompute that takes an open section to or below 55.00 suspends the seller"
        )
        assert seller["onboarding_state"] == "SUSPENDED"
        assert section["threshold_breached"] is True

    def test_prd_worked_example_separates_the_two_rounding_orders(self, api):
        """PRD §3.7: "with three claims routed, one rejected, two on time, two shops, one violation, four listings and one return, the conforming order yields a score of 63.34 while the non-conforming order yields 63.33."

        Design: Difficulty/combinatorial_formula/seller_score_component_rounding_order
        """
        # All four in-window listings are submitted before the section opens:
        # PRD §3.9 fires the suspension cascade on every open-section recompute
        # and a submission needs an APPROVED seller, so the listing set is built
        # first and the section opened over it (the window still contains them).
        scenario = fx.setup_listed_device()
        seller_id = scenario["seller"]["id"]
        listing_id = scenario["listing"]["id"]
        reservation_id = scenario["servicing_reservation_id"]
        for price in (149000, 148000, 147000):
            fx.create_listing(seller_id, list_price_cents=price)
        scenario["section"] = fx.open_section(seller_id, SECTION_OPEN)

        _reject_routed_claim(seller_id, listing_id, "BATTERY_SWELL")
        _resolve_on_time_repair(seller_id, listing_id, "2026-09-06T00:00:00Z", "TOUCH_FAILURE")
        validate_success(fx.remediate_reservation(reservation_id, repair_estimate_cents=18000))
        _resolve_on_time_repair(seller_id, listing_id, "2026-09-07T00:00:00Z", "CAMERA_FAILURE", carrier="CARRIER_B")

        fx.setup_disclosed_verification(seller_id, listing_id)
        fx.open_verification(seller_id, listing_id)

        section = fx.read_section(scenario["section"]["id"])
        assert section["claim_failure_rate_pct"] == 33.33
        assert section["on_time_resolution_pct"] == 66.67
        assert section["grading_compliance_pct"] == 50.00
        assert section["return_rate_pct"] == 25.00
        assert section["service_score"] == 63.34, (
            f"Expected the conforming order to yield 63.34, got {section['service_score']}"
        )
        assert section["service_score"] != 63.33, (
            "the non-conforming order that weights raw unrounded ratios yields 63.33"
        )


class TestSuspensionThresholdBoundary:
    def test_score_of_exactly_55_breaches_and_suspends(self, api):
        """PRD §3.7: "`threshold_breached` is true exactly when the score is at or below 55.00, and a breach at or below that figure while the seller is `APPROVED` suspends it (§3.9)."
        PRD §3.9: "When a closed scoring section takes an `APPROVED` seller's score to or below 55.00, the system suspends the seller without any client request: `onboarding_state` becomes `SUSPENDED`, `performance_tier` becomes `SUSPENDED`, `suspension_trigger_count` is incremented by one, and the seller's version advances."

        Design: Difficulty/boundary_precision_check/service_score_exactly_on_suspension_threshold
        """
        scenario = _scenario_listed_seller_with_section()
        seller_id = scenario["seller"]["id"]
        listing_id = scenario["listing"]["id"]
        reservation_id = scenario["servicing_reservation_id"]

        first = fx.create_upheld_claim(seller_id, listing_id, resolution_type="REPAIR")
        validate_success(
            fx.route_claim_return(
                first["id"], return_carrier="CARRIER_A", return_shipment_start="2026-09-06T00:00:00Z"
            )
        )
        validate_success(fx.remediate_reservation(reservation_id, repair_estimate_cents=18000))
        fx.create_claim_under_review(seller_id, listing_id, claim_reason_code="TOUCH_FAILURE")
        fx.create_claim_under_review(seller_id, listing_id, claim_reason_code="CAMERA_FAILURE")
        # Exactly one shop is conducted and it records one violation, so
        # `grading_compliance_pct` is 100 * (1 - 1) / max(1, 1) = 0.00 and the
        # weighted score lands exactly on the 55.00 boundary.
        fx.setup_disclosed_verification(seller_id, listing_id)

        section = fx.read_section(scenario["section"]["id"])
        assert section["claim_failure_rate_pct"] == 0.00
        assert section["on_time_resolution_pct"] == 33.33
        assert section["service_score"] == 55.00, (
            f"Expected the boundary score 55.00, got {section['service_score']}"
        )
        assert section["threshold_breached"] is True, (
            "a score of exactly 55.00 is at the threshold and must breach"
        )

        seller = validate_success(api.get(f"/v1/sellers/{seller_id}", headers=fx.ADMIN))
        assert seller["performance_tier"] == "SUSPENDED"
        assert seller["onboarding_state"] == "SUSPENDED"
        assert seller["suspension_trigger_count"] == 1

    def test_score_above_55_does_not_breach(self, api):
        """PRD §3.7: "`ELITE` at 85.00 or above, `STANDARD` at 70.00 or above, `PROBATION` while the score is strictly above 55.00, and `SUSPENDED` otherwise."
        PRD §3.7: "`threshold_breached` is true exactly when the score is at or below 55.00"

        Design: Difficulty/boundary_precision_check/service_score_exactly_on_suspension_threshold
        """
        scenario = _scenario_listed_seller_with_section()
        seller_id = scenario["seller"]["id"]
        listing_id = scenario["listing"]["id"]
        reservation_id = scenario["servicing_reservation_id"]

        _reject_routed_claim(seller_id, listing_id, "BATTERY_SWELL")
        _resolve_on_time_repair(seller_id, listing_id, "2026-09-06T00:00:00Z", "TOUCH_FAILURE")
        validate_success(fx.remediate_reservation(reservation_id, repair_estimate_cents=18000))
        fx.open_verification(seller_id, listing_id)

        section = fx.read_section(scenario["section"]["id"])
        assert section["claim_failure_rate_pct"] == 50.00
        assert section["on_time_resolution_pct"] == 50.00
        assert section["grading_compliance_pct"] == 100.00
        assert section["service_score"] == 67.50
        assert section["threshold_breached"] is False, (
            "a score strictly above 55.00 is not at the threshold"
        )
        # The seller's own tier is not asserted here: PRD §3.9 suspends an
        # APPROVED seller as soon as *any* component-source change recomputes an
        # open section to or below 55.00, and building the two routed claims
        # above necessarily passes through such an intermediate state (one
        # rejection of one routed claim scores 35.00).  The section's own
        # boundary reading is the assertion this test exists for.