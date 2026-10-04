"""The book-to-physical shrink charge: provisional at count, final at finalize."""

import pytest

from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, ADMIN, AUDITOR,
    set_clock, setup_store_with_agreement, setup_counted_audit,
    create_shrink_audit, count_shrink_audit, refresh_franchisee, get_success_data,
)


class TestShrinkChargeRecomputedAtFinalize:
    """An amendment between count and finalize moves the charge, not the counts."""

    def test_count_records_the_provisional_charge_at_the_count_time_percentage(self):
        """PRD §3.6: "The provisional charge computed at count time is the
        operator's `shrink_responsibility_pct` — as the covering agreement
        carries it *at the moment of counting* — applied to `shrink_cents` and
        rounded to 2 decimal places".
        PRD §3.6: "its `shrink_cents` is set to the book figure minus the physical
        figure — a negative result meaning the store is in overage rather than
        over-shrunk".

        Design: Difficulty/dual_variant_calc/shrink_charge_recomputed_at_finalize_after_agreement_amendment
        """
        context = setup_store_with_agreement(
            shrink_responsibility_pct=0.40, clock="2026-09-01T12:00:00Z")
        audit = create_shrink_audit(
            context["store"]["id"], "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z",
            10_000_000)
        counted = count_shrink_audit(audit["id"], 9_650_000)

        assert counted["status"] == "COUNTED"
        assert counted["shrink_cents"] == 350_000
        assert counted["shrink_charge_cents"] == pytest.approx(140_000.00, abs=0.01)

    def test_finalize_recharges_the_identical_counts_at_the_finalize_time_percentage(self):
        """PRD §3.6: "On finalization the charge is recomputed one last time using
        the `shrink_responsibility_pct` the agreement carries *at finalize*
        rather than the one it carried at count. This is the second half of the
        dual-variant rule: the same book and physical figures yield a different
        charge when the agreement has been amended between the count and the
        finalization, without any change to `book_inventory_cents`."
        PRD §3.6: "the operator's `open_shrink_charge_cents` is recomputed from
        the finalized charges that have not yet been recovered, followed by
        `audit_adjusted_net_worth_cents` and then `risk_band`, in that order."

        Design: Difficulty/dual_variant_calc/shrink_charge_recomputed_at_finalize_after_agreement_amendment
        """
        context = setup_counted_audit(
            book_inventory_cents=10_000_000,
            physical_inventory_cents=9_650_000,
            shrink_responsibility_pct=0.40,
            clock="2026-09-01T12:00:00Z",
        )
        audit = context["audit"]
        assert audit["shrink_charge_cents"] == pytest.approx(140_000.00, abs=0.01)

        # Amend the percentage after the count, then finalize under the new one.
        validate_success(api_client.amend_agreement(
            context["agreement"]["id"], {"shrink_responsibility_pct": 0.50}, ADMIN), 200)
        finalized = validate_success(
            api_client.finalize_shrink_audit(audit["id"], ADMIN), 200)

        assert finalized["status"] == "FINALIZED"
        # The counts did not move.
        assert finalized["shrink_cents"] == 350_000
        assert finalized["book_inventory_cents"] == 10_000_000
        assert finalized["physical_inventory_cents"] == 9_650_000
        # The charge did.
        assert finalized["shrink_charge_cents"] == pytest.approx(175_000.00, abs=0.01)
        assert finalized["shrink_charge_cents"] != pytest.approx(140_000.00, abs=0.01)

        franchisee = refresh_franchisee(context["franchisee"]["id"])
        assert franchisee["open_shrink_charge_cents"] == pytest.approx(175_000.00, abs=0.01)
        assert franchisee["audit_adjusted_net_worth_cents"] == pytest.approx(
            30_000_000 - 175_000.00, abs=0.01)


class TestShrinkChargeZeroBoundary:
    """A non-positive shrink records a charge of zero rather than a credit."""

    def test_zero_shrink_and_overage_both_charge_nothing_while_a_positive_shrink_charges(self):
        """PRD §3.6: "a non-positive `shrink_cents` records a charge of zero. An
        overage therefore never produces a credit to the operator; it produces a
        zero charge."
        PRD §3.6: "its `shrink_cents` is set to the book figure minus the physical
        figure — a negative result meaning the store is in overage rather than
        over-shrunk".

        Design: Corner/calculations/shrink_overage_zero_charge_boundary_on_a_negative_shrink
        """
        context = setup_store_with_agreement(
            shrink_responsibility_pct=0.60, clock="2026-09-20T00:00:00Z")
        store_id = context["store"]["id"]

        at_boundary = create_shrink_audit(
            store_id, "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", 4_000_000)
        shrink = create_shrink_audit(
            store_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 4_000_000)
        overage = create_shrink_audit(
            store_id, "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", 4_000_000)

        exact = count_shrink_audit(at_boundary["id"], 4_000_000)
        short = count_shrink_audit(shrink["id"], 3_850_000)
        over = count_shrink_audit(overage["id"], 4_100_000)

        # Exactly on the boundary: shrink 0, charge 0.
        assert exact["shrink_cents"] == 0
        assert exact["shrink_charge_cents"] == pytest.approx(0.00, abs=0.01)

        # A real shortfall: charged at the responsibility percentage.
        assert short["shrink_cents"] == 150_000
        assert short["shrink_charge_cents"] == pytest.approx(90_000.00, abs=0.01)

        # An overage: negative shrink, but still a zero charge -- never a credit.
        assert over["shrink_cents"] == -100_000
        assert over["shrink_charge_cents"] == pytest.approx(0.00, abs=0.01)
        assert over["shrink_charge_cents"] != pytest.approx(-60_000.00, abs=0.01)

        for audit in (exact, short, over):
            assert audit["status"] == "COUNTED"

    def test_a_negative_physical_count_is_rejected_as_an_invalid_request(self):
        """PRD §3.6: "The count call supplies `physical_inventory_cents`, which
        must not be negative — a negative figure is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/calculations/shrink_overage_zero_charge_boundary_on_a_negative_shrink
        """
        context = setup_store_with_agreement(clock="2026-09-20T00:00:00Z")
        audit = create_shrink_audit(
            context["store"]["id"], "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z",
            4_000_000)
        response = api_client.count_shrink_audit(
            audit["id"], {"physical_inventory_cents": -1, "recount": False}, AUDITOR)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        unchanged = get_success_data(api_client.get_shrink_audit(audit["id"], ADMIN))
        assert unchanged["status"] == "SCHEDULED"
