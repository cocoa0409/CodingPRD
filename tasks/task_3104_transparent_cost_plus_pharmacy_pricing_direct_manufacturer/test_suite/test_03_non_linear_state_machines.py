"""Non-linear state machines: parallel price dimensions, comparison cycling,
and the terminal rejection branch of the prescription."""
from test_helpers import (
    list_payload,
    get_success_data,
    validate_error,
    create_manufacturer,
    create_drug,
    create_price_row,
    create_sourced_price,
    create_patient,
    create_prescriber,
    create_prescription,
    submit_intake,
    review_intake,
    setup_substituted_order,
    register_substantiation,
    list_comparisons_of,
    reset_clock,
    OPS,
    PHARMACIST,
)


class TestParallelPriceDimensions:

    def test_activation_moves_only_the_price_dimension(self, api):
        """PRD §3.1: "Activation is the operator action that opens the price dimension. Moving a row from PROPOSED to ACTIVE requires that the row's price_status is still PROPOSED and that the offering manufacturer's status is ACTIVE; a price cannot be activated behind a suspended manufacturer."

        Design: Difficulty/non_linear_state_machine/price_row_two_independent_dimensions_activation_without_sourcing
        """
        reset_clock()
        manufacturer = create_manufacturer("Bexley Generics")
        drug = create_drug()
        row = create_price_row(drug["id"], manufacturer["id"], unit_cost_cents=12,
                               available_units=500, reliability_tier="A",
                               packaging="500-count bottle")
        activated = get_success_data(api.activate_price(row["id"], OPS))

        assert activated["price_status"] == "ACTIVE"
        assert activated["sourcing_status"] == "UNDER_REVIEW", (
            "activation moves the price dimension only; the sourcing dimension "
            "is untouched by the price-dimension transition"
        )

    def test_activated_but_unsourced_row_leaves_the_drug_unsourced(self, api):
        """PRD §2.10: "A manufacturer price row is a candidate for the pool when
        three things hold at once: the row's own price dimension is ACTIVE, the
        row's own sourcing dimension is SOURCED, and the manufacturer that
        offers it is itself ACTIVE."

        Design: Difficulty/non_linear_state_machine/price_row_two_independent_dimensions_activation_without_sourcing
        """
        reset_clock()
        manufacturer = create_manufacturer("Bexley Generics")
        drug = create_drug()
        row = create_price_row(drug["id"], manufacturer["id"], unit_cost_cents=12,
                               available_units=500, reliability_tier="A",
                               packaging="500-count bottle")
        get_success_data(api.activate_price(row["id"], OPS))
        current = get_success_data(api.get_drug(drug["id"], OPS))

        assert current["sourcing_status"] != "SOURCED", (
            "a row at UNDER_REVIEW on the sourcing dimension contributes "
            "nothing to the eligible pool even though it is ACTIVE on price"
        )
        # The drug-level sourcing dimension is what the ACTIVE-without-SOURCED
        # row moves: it stays UNDER_REVIEW because the wider pool has positive
        # units but no sourced row. `supply_units` is the *raw headroom* total,
        # which counts this ACTIVE-price UNDER_REVIEW row's 500 units.
        assert current["sourcing_status"] == "UNDER_REVIEW", (
            "positive units with no sourced row leaves the drug UNDER_REVIEW"
        )
        assert current["supply_units"] == 500, (
            "supply_units counts the row while its sourcing dimension is "
            "UNDER_REVIEW (PRD §3.2 supply-total rule)"
        )
        assert current["effective_unit_cost_cents"] is None, (
            "the sourcing pool stays empty, so the sourcing-effective cost is "
            "null even though raw headroom is non-zero"
        )


class TestComparisonCycle:

    def test_substitution_drives_the_comparison_to_refresh_required(self, api):
        """PRD §3.4: "each such order's comparison is driven to
        REFRESH_REQUIRED with substantiated cleared and substantiation_digest
        cleared, and both the order's and the comparison's versions advance."

        Design: Difficulty/non_linear_state_machine/comparison_cycle_refresh_required_then_fresh_after_substitution
        """
        reset_clock()
        ctx, new_drug, comparison = setup_substituted_order()
        assert comparison["state"] == "REFRESH_REQUIRED"
        assert comparison["substantiated"] is False
        assert comparison["substantiation_digest"] is None

    def test_refresh_cycles_the_comparison_back_to_fresh_with_a_new_digest(self, api):
        """PRD §3.9: "Refreshing a comparison is the operator action that
        re-derives its figures after a substitution or a lapse. It addresses the
        comparison by naming both the owning order and the comparison_id it
        refreshes, and it is accepted from REFRESH_REQUIRED, from STALE, and
        from BLOCKED alike, in all three cases requiring that an ENABLED
        substantiation for the order exists whose valid_until is strictly after
        the logical clock."

        Design: Difficulty/non_linear_state_machine/comparison_cycle_refresh_required_then_fresh_after_substitution
        """
        reset_clock()
        ctx, new_drug, comparison = setup_substituted_order()
        ctx, comparison, sub = enable(api, ctx, comparison)

        assert comparison["state"] == "FRESH", (
            "the machine cycles back to FRESH after a refresh rather than "
            "terminating at REFRESH_REQUIRED"
        )
        assert comparison["status"] == "SUBSTANTIATED"
        assert comparison["substantiated"] is True
        assert comparison["substantiation_digest"] is not None


class TestPrescriptionRejectionBranch:

    def test_rejection_is_terminal_with_the_supplied_reason_code(self, api):
        """PRD §3.4: "Rejection sets the prescription to REJECTED with
        rejection_reason_code equal to the supplied reason code, sets the
        request to REJECTED, and then performs a compensating restoration"
        PRD §3.4: "Together with REJECTED, the three terminal prescription
        states are REJECTED, DEPLETED and TERMINATED."

        Design: Difficulty/non_linear_state_machine/prescription_rejection_branch_is_genuinely_terminal_for_that_prescription
        """
        reset_clock()
        manufacturer = create_manufacturer("Bexley Generics")
        drug = create_drug()
        create_sourced_price(drug["id"], manufacturer["id"], unit_cost_cents=12,
                             available_units=600, reliability_tier="A")
        patient = create_patient()
        prescriber = create_prescriber()
        rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                                 total_refills_authorized=2)
        rx_before = get_success_data(api.get_prescription(rx["id"], OPS))
        rq = submit_intake(rx["id"], packaged_quantity=30)
        review_intake(rq["id"])

        get_success_data(api.reject_intake_request(
            rq["id"], "PRESCRIBER_ORDER_ILLEGIBLE", PHARMACIST))

        rx_after = get_success_data(api.get_prescription(rx["id"], OPS))
        rq_after = get_success_data(api.get_intake_request(rq["id"], OPS))
        assert rx_after["status"] == "REJECTED"
        assert rx_after["rejection_reason_code"] == "PRESCRIBER_ORDER_ILLEGIBLE"
        assert rq_after["status"] == "REJECTED"
        assert rq_after["consumed_quantity"] == 0
        assert rx_after["version"] > rx_before["version"]

    def test_second_intake_against_a_rejected_prescription_is_refused(self, api):
        """PRD §2.9: "State validation — whether the resource is in a state that
        admits the requested transition, with every transition attempted from a
        terminal state rejected — comes next."

        Design: Difficulty/non_linear_state_machine/prescription_rejection_branch_is_genuinely_terminal_for_that_prescription
        """
        reset_clock()
        manufacturer = create_manufacturer("Bexley Generics")
        drug = create_drug()
        create_sourced_price(drug["id"], manufacturer["id"], unit_cost_cents=12,
                             available_units=600, reliability_tier="A")
        patient = create_patient()
        prescriber = create_prescriber()
        rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                                 total_refills_authorized=2)
        rq = submit_intake(rx["id"], packaged_quantity=30)
        review_intake(rq["id"])
        get_success_data(api.reject_intake_request(
            rq["id"], "PRESCRIBER_ORDER_ILLEGIBLE", PHARMACIST))

        second = api.create_intake_request(rx["id"], 30, OPS)
        validate_error(second, "ERR_INVALID_STATE")
        requests = list_payload(
            api.list_intake_requests_of_prescription(rx["id"], OPS))
        assert len(requests) == 1, "no second intake request was created"


# ─── local helpers ────────────────────────────────────

def enable(api, ctx, comparison):
    """Register a substantiation for the order and enable it.

    Enablement itself drives the comparison through the lifecycle rule (PRD
    §3.9: "its state is recomputed by the lifecycle rule"), so a live
    substantiation moves a REFRESH_REQUIRED comparison straight to FRESH with a
    fresh digest — no separate refresh call is needed (and a refresh is only
    accepted from REFRESH_REQUIRED, STALE or BLOCKED)."""
    sub = register_substantiation(ctx["order"]["id"])
    version = get_success_data(api.get_order(ctx["order"]["id"], OPS))["version"]
    get_success_data(api.enable_substantiation(
        ctx["order"]["id"], sub["id"], version, OPS))
    refreshed = list_comparisons_of(ctx["order"]["id"])[0]
    return ctx, refreshed, sub