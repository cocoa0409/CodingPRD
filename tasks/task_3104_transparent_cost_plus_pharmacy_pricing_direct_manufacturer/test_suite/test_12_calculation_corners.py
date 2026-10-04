"""Queue B — calculations section (4 non-stub instances)."""
from test_helpers import (
    list_payload,
    get_success_data,
    validate_success,
    create_manufacturer,
    create_drug,
    create_sourced_price,
    create_patient,
    create_prescriber,
    create_prescription,
    submit_intake,
    review_intake,
    accept_intake,
    add_accepted_demand,
    reset_clock,
    OPS,
    PHARMACIST,
)


class TestStockCheckWeightedAverage:

    def test_a_small_high_cost_row_barely_moves_the_weighted_average(self, api):
        """PRD §3.2: "each candidate row's unit_cost_cents multiplied by its
        available_units, summed across the pool, divided by the sum of
        available_units across the pool"

        Design: Corner/calculations/stock_check_overview_variant_is_units_weighted_not_the_cheapest_row
        """
        reset_clock()
        m1 = create_manufacturer("Bexley Generics")
        m2 = create_manufacturer("Cardell Labs")
        drug = create_drug()
        p1 = create_sourced_price(drug["id"], m1["id"], unit_cost_cents=12,
                                  available_units=900, reliability_tier="A",
                                  packaging="900-count bottle")
        p2 = create_sourced_price(drug["id"], m2["id"], unit_cost_cents=20,
                                  available_units=100, reliability_tier="B",
                                  packaging="100-count bottle")

        data = validate_success(api.stock_check(drug["id"], OPS))
        assert data["effective_unit_cost_cents"] == 13, (
            "(12*900 + 20*100) / 1000 = 12.8, rounded half up to 13 — the "
            "cheapest row's 12 cents barely moves the weighted figure"
        )
        assert sorted(data["eligible_price_ids"]) == sorted([p1["id"], p2["id"]])

    def test_the_primary_row_is_the_lowest_unit_cost_holder(self, api):
        """PRD §3.3: "On success the drug's packaging is set from the selected
        primary price row"

        Design: Corner/calculations/stock_check_overview_variant_is_units_weighted_not_the_cheapest_row
        """
        reset_clock()
        m1 = create_manufacturer("Bexley Generics")
        m2 = create_manufacturer("Cardell Labs")
        drug = create_drug()
        create_sourced_price(drug["id"], m1["id"], unit_cost_cents=12,
                             available_units=900, reliability_tier="A",
                             packaging="900-count bottle")
        create_sourced_price(drug["id"], m2["id"], unit_cost_cents=20,
                             available_units=100, reliability_tier="B",
                             packaging="100-count bottle")
        data = validate_success(api.stock_check(drug["id"], OPS))
        assert data["packaging"] == "900-count bottle"


class TestDemandWindowFiltering:

    def test_rejected_requests_leave_the_demand_sum_immediately(self, api):
        """PRD §3.4: "REJECTED requests are excluded from the sum even when they
        fall inside the window"

        Design: Corner/calculations/demand_window_excludes_rejected_requests_and_collapses_to_zero
        """
        reset_clock()
        manufacturer = create_manufacturer()
        drug = create_drug()
        create_sourced_price(drug["id"], manufacturer["id"], unit_cost_cents=12,
                             available_units=500, reliability_tier="C",
                             packaging="500-count bottle")
        patient = create_patient()
        prescriber = create_prescriber()
        rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                                 total_refills_authorized=1)
        rq = submit_intake(rx["id"], packaged_quantity=50)
        review_intake(rq["id"])
        accept_intake(rq["id"])

        before = validate_success(api.supply_summary(drug["id"], OPS))
        assert before["demand_units_30d"] == 50

        rx2 = create_prescription(patient["id"], prescriber["id"], drug["id"],
                                  total_refills_authorized=1)
        rq2 = submit_intake(rx2["id"], packaged_quantity=75)
        review_intake(rq2["id"])
        get_success_data(api.reject_intake_request(rq2["id"], "ILLEGIBLE", PHARMACIST))

        after = validate_success(api.supply_summary(drug["id"], OPS))
        assert after["demand_units_30d"] == 50, (
            "the rejected 75-unit request never enters the window sum"
        )

    def test_supply_summary_surfaces_each_rows_own_sourcing_dimension(self, api):
        """PRD §3.2: "the demand-side supply summary surfaces each price row's
        own sourcing dimension alongside the drug-level value"
        PRD §2.6: "All monetary quantities in this system are integers expressed
        in cents."

        Design: Corner/calculations/demand_window_excludes_rejected_requests_and_collapses_to_zero
        """
        reset_clock()
        manufacturer = create_manufacturer()
        drug = create_drug()
        row = create_sourced_price(drug["id"], manufacturer["id"],
                                   unit_cost_cents=12, available_units=500,
                                   reliability_tier="C", packaging="500-count bottle")
        data = validate_success(api.supply_summary(drug["id"], OPS), 200)
        assert data["supply_units"] == 500
        assert data["sourcing_status"] == "SOURCED"
        rows = data.get("rows") or []
        ids = [r.get("price_id") for r in rows]
        assert row["id"] in ids


class TestRoundingSite:

    def test_the_quotient_is_rounded_once_at_the_final_division(self, api):
        """PRD §2.6: "Where a calculation produces a fractional cent, the
        rounding method is round half up — a value exactly halfway between two
        cents resolves upward — and the rounding is applied only at the specific
        site the calculation names, never at every intermediate operation."

        Design: Corner/calculations/stock_check_rounds_half_up_once_at_the_final_division
        """
        reset_clock()
        m1 = create_manufacturer("Bexley Generics")
        drug = create_drug()
        create_sourced_price(drug["id"], m1["id"], unit_cost_cents=11,
                             available_units=300, reliability_tier="A",
                             packaging="300-count bottle")
        create_sourced_price(drug["id"], m1["id"], unit_cost_cents=17,
                             available_units=200, reliability_tier="B",
                             packaging="200-count bottle")

        data = validate_success(api.stock_check(drug["id"], OPS))
        assert data["effective_unit_cost_cents"] == 13, (
            "(11*300 + 17*200) / 500 = 13.4, rounded half up once to 13"
        )
        assert isinstance(data["effective_unit_cost_cents"], int)

    def test_a_half_cent_resolves_upward(self, api):
        """PRD §2.6: "a value exactly halfway between two cents resolves upward"

        Design: Corner/calculations/stock_check_rounds_half_up_once_at_the_final_division
        """
        reset_clock()
        m1 = create_manufacturer("Bexley Generics")
        drug = create_drug()
        # (10*1 + 11*1)/2 = 10.5, which must resolve upward to 11.
        create_sourced_price(drug["id"], m1["id"], unit_cost_cents=10,
                             available_units=1, reliability_tier="A",
                             packaging="1-count bottle")
        create_sourced_price(drug["id"], m1["id"], unit_cost_cents=11,
                             available_units=1, reliability_tier="A",
                             packaging="1-count bottle")

        data = validate_success(api.stock_check(drug["id"], OPS))
        assert data["effective_unit_cost_cents"] == 11, (
            "the quotient is exactly 10.5, halfway between two cents, and must "
            "resolve upward"
        )


class TestExpansionScoreBands:

    def test_demand_equal_to_supply_scores_one(self, api):
        """PRD §3.3: "When demand_units_30d is greater than or equal to
        supply_units, the score is 1 — supply cannot even meet demand and the
        drug is refused."

        Design: Corner/calculations/expansion_score_bands_and_the_five_band_lower_edge
        """
        reset_clock()
        drug = score_band_drug(api, demand=99, supply=99)
        data = validate_success(api.expansion_score(drug["id"], OPS))
        assert data["demand_units_30d"] == 99
        assert data["supply_units"] == 99
        assert data["expansion_score"] == 1

    def test_demand_below_the_band_lower_edge_scores_zero(self, api):
        """PRD §3.3: "Finally, when supply_units exceeds ten times
        demand_units_30d, the score is 0, which refuses admission: a drug with
        demand that faint relative to supply is not worth formulary space."

        Design: Corner/calculations/expansion_score_bands_and_the_five_band_lower_edge
        """
        reset_clock()
        drug = score_band_drug(api, demand=9, supply=99)
        data = validate_success(api.expansion_score(drug["id"], OPS))
        assert data["demand_units_30d"] == 9
        assert data["supply_units"] == 99
        assert data["expansion_score"] == 0, (
            "99 exceeds ten times 9, so the ratio is too faint to admit"
        )

    def test_the_expansion_score_endpoint_never_changes_the_drug_state(self, api):
        """PRD §3.3: "The expansion score is what makes the supply-versus-demand
        comparison graded rather than binary, and it is evaluated with these exact
        boundaries."
        PRD §3.3: "A Drug begins life as NON_FORMULARY."

        Design: Corner/calculations/expansion_score_bands_and_the_five_band_lower_edge
        """
        reset_clock()
        drug = score_band_drug(api, demand=99, supply=99)
        before = get_success_data(api.get_drug(drug["id"], OPS))
        validate_success(api.expansion_score(drug["id"], OPS))
        after = get_success_data(api.get_drug(drug["id"], OPS))
        assert after["state"] == "NON_FORMULARY"
        assert after["state"] == before["state"]


# ─── local helpers ────────────────────────────────────

def score_band_drug(api, demand, supply):
    """A drug with exactly `demand` units of trailing demand and one sourced row
    of exactly `supply` available units."""
    manufacturer = create_manufacturer()
    drug = create_drug()
    create_sourced_price(drug["id"], manufacturer["id"], unit_cost_cents=12,
                         available_units=supply, reliability_tier="C",
                         packaging=f"{supply}-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    add_accepted_demand(drug["id"], patient["id"], prescriber["id"], demand)
    return drug