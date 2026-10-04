"""Compensating invariants: cancellation conserves money, disablement
conserves the servable comparison."""
from test_helpers import (
    get_success_data,
    validate_error,
    validate_success,
    create_order_payload,
    create_sourced_price,
    setup_full_stack,
    setup_order_with_comparison,
    register_substantiation,
    pay_order,
    fulfill_order,
    list_comparisons_of,
    reset_clock,
    OPS,

)


class TestCancellationConservesThePriceDecomposition:

    def test_all_five_price_components_are_identical_across_the_cancellation(self, api):
        """PRD §3.8: "In all three cases the order moves to CANCELED, and the
        referenced intake request's consumed_quantity is restored by the smaller
        of the order's quantity and the request's packaged_quantity — the exact
        mirror of what fulfilment drew down."

        Design: Difficulty/compensating_invariant/order_cancellation_conserves_the_patient_price_decomposition
        """
        reset_clock()
        ctx = blended_paid_order(api)
        before = get_success_data(api.get_order(ctx["order"]["id"], OPS))

        get_success_data(api.cancel_order(ctx["order"]["id"], "PATIENT_REQUEST", OPS))

        after = get_success_data(api.get_order(ctx["order"]["id"], OPS))
        assert after["status"] == "CANCELED"
        for field in ("acquisition_cost_cents", "markup_cents", "pharmacy_fee_cents",
                      "shipping_fee_cents", "patient_price_cents"):
            assert after[field] == before[field], (
                f"{field} must be unchanged by the cancellation"
            )

    def test_cancellation_restores_the_consumed_capacity_exactly(self, api):
        """PRD §3.8: "Cancellation is where the system's compensating invariants
        are pinned. The first is that a cancellation restores the intake
        request's consumed quantity exactly — the same quantity fulfilment
        consumed, computed by the same smaller-of rule — so that repeated
        create-and-cancel cycles cannot drift a request's capacity away from its
        true value."

        Design: Difficulty/compensating_invariant/order_cancellation_conserves_the_patient_price_decomposition
        """
        reset_clock()
        ctx = blended_paid_order(api)
        before = get_success_data(api.get_intake_request(ctx["request"]["id"], OPS))
        before_drug = get_success_data(api.get_drug(ctx["drug"]["id"], OPS))
        assert before["consumed_quantity"] == 60

        get_success_data(api.cancel_order(ctx["order"]["id"], "PATIENT_REQUEST", OPS))

        after = get_success_data(api.get_intake_request(ctx["request"]["id"], OPS))
        assert after["consumed_quantity"] == 0, (
            "the cancel gives back exactly the 60 units fulfilment drew down"
        )
        after_drug = get_success_data(api.get_drug(ctx["drug"]["id"], OPS))
        assert after_drug["supply_units"] >= before_drug["supply_units"], (
            "restoring the reservation cannot reduce the drug's supply headroom"
        )
        assert (after["packaged_quantity"] - after["consumed_quantity"]) == (
            after["packaged_quantity"]
        ), ("the restored capacity is the request's full packaged quantity, so "
            "repeated create-and-cancel cycles cannot drift it away from its "
            "true value")


class TestDisablementConservesTheServableComparison:

    def test_enablement_makes_the_comparison_message_servable(self, api):
        """PRD §3.9: "On success the order's comparison becomes substantiated
        and carries a fresh digest, its state is recomputed by the lifecycle
        rule, and both the substantiation's and the comparison's versions
        advance, along with the order's version."

        Design: Difficulty/compensating_invariant/substantive_record_disablement_conserves_the_servable_comparison_count
        """
        reset_clock()
        ctx, comparison = setup_order_with_comparison(quantity=60)
        sub = register_substantiation(ctx["order"]["id"])
        version = get_success_data(api.get_order(ctx["order"]["id"], OPS))["version"]
        get_success_data(api.enable_substantiation(
            ctx["order"]["id"], sub["id"], version, OPS))

        data = validate_success(api.get_order_comparison(ctx["order"]["id"], OPS))
        assert data["status"] == "SUBSTANTIATED"
        assert data["substantiated"] is True
        assert data["substantiation_digest"] is not None

    def test_disablement_withholds_the_message_again_and_clears_the_digest(self, api):
        """PRD §2.11: "Serving a comparison message to a patient is refused with
        ERR_COMPARISON_UNSUBSTANTIATED and HTTP 422 when the comparison is
        unsubstantiated or blocked."
        PRD §3.9: "when no other enabled and unexpired substantiation remains,
        the comparison's substantiated flag and its digest are cleared."

        Design: Difficulty/compensating_invariant/substantive_record_disablement_conserves_the_servable_comparison_count
        """
        reset_clock()
        ctx, comparison = setup_order_with_comparison(quantity=60)
        sub = register_substantiation(ctx["order"]["id"])
        version = get_success_data(api.get_order(ctx["order"]["id"], OPS))["version"]
        get_success_data(api.enable_substantiation(
            ctx["order"]["id"], sub["id"], version, OPS))

        disabled = get_success_data(
            api.disable_substantiation(ctx["order"]["id"], sub["id"], OPS))
        assert disabled["status"] == "DISABLED"

        response = api.get_order_comparison(ctx["order"]["id"], OPS)
        validate_error(response, "ERR_COMPARISON_UNSUBSTANTIATED")
        after = list_comparisons_of(ctx["order"]["id"])[0]
        assert after["substantiation_digest"] is None, (
            "the digest returns to its pre-enablement value"
        )


# ─── local helpers ────────────────────────────────────

def blended_paid_order(api):
    """A PAID order of quantity 60 whose source row can cover only part of the
    quantity, so the fallback blends: acquisition 15, markup 2, fee 800,
    shipping 500 and patient price 1317. The request's consumed quantity is 60
    after fulfilment."""
    ctx = setup_full_stack(
        drug_rows=[{"unit_cost_cents": 16, "available_units": 400,
                    "reliability_tier": "C", "packaging": "400-count bottle"}],
        formulary=True, quantity=60, packaged_quantity=100,
        create_order_now=False,
    )
    short_source = create_sourced_price(
        ctx["drug"]["id"], ctx["manufacturer"]["id"],
        unit_cost_cents=12, available_units=20, reliability_tier="C",
        packaging="20-count bottle",
    )
    fallback = ctx["prices"][0]
    payload = create_order_payload(
        ctx["prescription"]["id"], ctx["request"]["id"], ctx["pharmacy"]["id"],
        short_source["id"], quantity=60, sub_source_price_id=fallback["id"],
    )
    order = get_success_data(api.create_order(payload, OPS))
    paid = pay_order(order["id"])
    # The blended pool straddles a 20-unit row and a 400-unit row, so the
    # drug's ship_interval_days is 35 and the interval gate must clear first.
    reset_clock("2026-11-01T00:00:00Z")
    fulfill_order(paid["id"])   # draws the request's consumed quantity down
    ctx["order"] = get_success_data(api.get_order(order["id"], OPS))
    return ctx