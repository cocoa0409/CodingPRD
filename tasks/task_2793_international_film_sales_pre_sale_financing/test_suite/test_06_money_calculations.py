"""Money and derived-figure arithmetic of the Film Sales Presale API.

Every expected figure below is a literal pre-computed against the PRD prose that
the docstring quotes, never re-derived in the test body, so that a rounding order
different from the one the PRD pins is detected rather than reproduced.
"""

import pytest

from test_helpers import (
    CLOCK_DEFAULT,
    HEAD_OF_SALES_CLOSER,
    accepted_contract,
    add_milestone_schedule,
    approve_facility,
    assert_account_counters,
    assert_allocations,
    assert_buyer_exposure,
    assert_contract_axes,
    assert_created,
    assert_facility_figures,
    assert_instant,
    assert_list_response,
    assert_money,
    assert_money_precision,
    assert_object_response,
    assert_tier,
    assert_valuation_prices,
    bond_facility,
    buyer_amendment_payload,
    comparable_payload,
    contract_payload,
    distribute_payload,
    executed_contract,
    executed_contract_environment,
    find_by,
    get_success_data,
    make_buyer_headers,
    make_collection_agent_headers,
    make_comparables,
    make_delivery_manager_headers,
    make_facility,
    make_film,
    make_fr_territory,
    make_head_of_sales_headers,
    make_lender_headers,
    make_platform_admin_headers,
    make_sales_agent_headers,
    make_territory,
    make_tiers,
    milestone_by_label,
    package_payload,
    pin_clock,
    post_receipt,
    read_account,
    read_agreement,
    read_buyer,
    read_contract,
    read_facility,
    read_milestones,
    read_tiers,
    slate_with_published_valuation,
    validate_error,
    valuation_payload,
)


# --------------------------------------------------------------------------
# Local helpers.  Nothing here belongs in the shared package: these are the
# two non-money numeric comparisons this module needs.
# --------------------------------------------------------------------------
def _assert_ratio(actual, expected, field):
    """A multiplier or ratio field equals `expected` exactly."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{field}: expected a JSON number, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=1e-9), (
        f"{field}: expected {expected}, got {actual}"
    )


def _assert_not_money(actual, forbidden, field):
    """The field is at least a cent away from a figure a wrong order would give."""
    assert abs(float(actual) - float(forbidden)) > 0.005, (
        f"{field}: {actual} matches the forbidden figure {forbidden}"
    )


class TestTerritoryValuationArithmetic:
    def test_cast_adjusted_estimate_on_a_three_comparable_odd_sample(self, api):
        """A three-row sample takes the middle fee and the 1.40 cast band drives ask and floor.

        PRD: "When the sample size is odd, the median is the fee of the single middle row of that sorted sequence."

        PRD: "The **cast tier multiplier** is a step function of the film's `principal_cast_score`, with each band inclusive on its lower bound: a score of 85 or above yields 1.40; a score from 70 up to but not including 85 yields 1.20; a score from 50 up to but not including 70 yields 1.00; and a score below 50 yields 0.80."

        PRD: "Under `CAST_ADJUSTED` — the packaging view used to argue the ask to buyers — `cast_multiplier` takes the value the cast tier function returns for the film's `principal_cast_score`, and `estimate_usd` is the comparable median multiplied by the territory's `base_value_index` and then by that cast multiplier, rounded half-up to two decimal places."

        PRD: "`ask_price_usd` is the estimate multiplied by an ask premium of 1.25, rounded half-up to two decimal places — the opening number the sales agent carries into negotiation."

        PRD: "`floor_price_usd` is the estimate multiplied by a floor discount of 0.70, rounded half-up to two decimal places — the minimum guarantee floor that will be enforced when a contract for this territory is countersigned."

        Design: Corner/calculations/cast_adjusted_estimate_from_a_three_comp_odd_sample
        """
        pin_clock(api, CLOCK_DEFAULT)
        film = make_film(api, principal_cast_score=88)
        territory = make_territory(api, base_value_index=1.20)
        make_comparables(
            api,
            territory["id"],
            fees=(800000.00, 1000000.00, 1200000.00),
            years=(2022, 2023, 2021),
        )

        created = assert_created(
            api.create_valuation(
                valuation_payload(film["id"], territory["id"], "CAST_ADJUSTED"),
                make_sales_agent_headers(),
            )
        )

        assert created["comp_sample_size"] == 3, (
            f"expected comp_sample_size 3, got {created['comp_sample_size']}"
        )
        assert_money(created["comp_median_usd"], 1000000.00, "comp_median_usd")
        _assert_ratio(created["cast_multiplier"], 1.40, "cast_multiplier")
        assert_valuation_prices(created, 1680000.00, 2100000.00, 1176000.00)
        assert created["status"] == "DRAFT", (
            f"expected a DRAFT valuation, got {created['status']}"
        )
        assert created["published_by_user_id"] is None, (
            "a new valuation carries a null published_by_user_id"
        )
        assert created["published_at"] is None, "a new valuation carries a null published_at"

    def test_even_sample_median_rounds_half_up_and_carries_the_cent_onward(self, api):
        """A four-row sample averages the middle pair half-up and that cent survives to ask and floor.

        PRD: "When it is even, the median is the average of the two middle rows' fees — their sum divided by two — rounded half-up to two decimal places."

        PRD: "Under `COMPARABLE_WEIGHTED` — the pure market view the agency uses to argue a territory's floor to financiers — `cast_multiplier` is forced to exactly 1.00, the film's `principal_cast_score` is ignored entirely, and `estimate_usd` is the comparable median multiplied by the territory's `base_value_index`, rounded half-up to two decimal places."

        PRD: "`ask_price_usd` is the estimate multiplied by an ask premium of 1.25, rounded half-up to two decimal places — the opening number the sales agent carries into negotiation."

        PRD: "`floor_price_usd` is the estimate multiplied by a floor discount of 0.70, rounded half-up to two decimal places — the minimum guarantee floor that will be enforced when a contract for this territory is countersigned."

        Design: Corner/calculations/even_sample_median_rounds_half_up_and_propagates_to_ask_and_floor
        """
        pin_clock(api, CLOCK_DEFAULT)
        film = make_film(api, principal_cast_score=88)
        territory = make_territory(api, base_value_index=1.20)
        make_comparables(
            api,
            territory["id"],
            fees=(800000.00, 900000.01, 1000000.00, 1200000.00),
            years=(2022, 2023, 2023, 2021),
        )

        created = assert_created(
            api.create_valuation(
                valuation_payload(film["id"], territory["id"], "COMPARABLE_WEIGHTED"),
                make_sales_agent_headers(),
            )
        )

        assert created["comp_sample_size"] == 4, (
            f"expected comp_sample_size 4, got {created['comp_sample_size']}"
        )
        assert_money(created["comp_median_usd"], 950000.01, "comp_median_usd")
        _assert_not_money(created["comp_median_usd"], 950000.00, "comp_median_usd")
        assert_money_precision(created["comp_median_usd"], "comp_median_usd")
        assert_valuation_prices(created, 1140000.01, 1425000.01, 798000.01)

    def test_comparable_eligibility_excludes_unverified_off_genre_stale_and_foreign_rows(
        self, api
    ):
        """Four dominating comparables are each excluded for a different reason.

        PRD: "Unverified comparables, comparables from another genre, and comparables from another territory are excluded even when they are the only datapoints available at all."

        PRD: "When a `SalesAgent` or `HeadOfSales` values one territory for one film, supplying just three inputs — the `film_id`, the `territory_id` and the `method` — the service assembles the eligible comparable set by taking every comparable title whose `territory_id` equals the territory being valued, whose `genre` equals the film's `genre`, whose `verified` flag is true, and whose `release_year` is at or after the calendar year of the logical present instant minus seven."

        PRD: "The seven-year lookback means that at the default clock reading of 1 August 2026 a comparable released in 2019 is eligible and one released in 2018 is not."

        PRD: "Under `CAST_ADJUSTED` — the packaging view used to argue the ask to buyers — `cast_multiplier` takes the value the cast tier function returns for the film's `principal_cast_score`, and `estimate_usd` is the comparable median multiplied by the territory's `base_value_index` and then by that cast multiplier, rounded half-up to two decimal places."

        Design: Corner/calculations/comparable_eligibility_excludes_unverified_off_genre_stale_and_foreign_comps
        """
        pin_clock(api, CLOCK_DEFAULT)
        film = make_film(api, genre="ACTION", principal_cast_score=88)
        territory = make_territory(api, base_value_index=1.20)
        make_comparables(
            api,
            territory["id"],
            fees=(800000.00, 1000000.00, 1200000.00),
            years=(2022, 2023, 2021),
        )
        # Each of these four would dominate the median if it leaked into the sample.
        for overrides in (
            {"name": "Comp Unverified", "genre": "ACTION", "verified": False},
            {"name": "Comp Drama", "genre": "DRAMA", "verified": True},
        ):
            get_success_data(
                api.create_comparable_title(
                    territory["id"],
                    comparable_payload(5000000.00, 2024, **overrides),
                    make_platform_admin_headers(),
                )
            )
        get_success_data(
            api.create_comparable_title(
                territory["id"],
                comparable_payload(
                    5000000.00, 2018, name="Comp Stale", genre="ACTION", verified=True
                ),
                make_platform_admin_headers(),
            )
        )
        foreign_territory = make_fr_territory(api)
        get_success_data(
            api.create_comparable_title(
                foreign_territory["id"],
                comparable_payload(
                    5000000.00, 2024, name="Comp Foreign", genre="ACTION", verified=True
                ),
                make_platform_admin_headers(),
            )
        )

        created = assert_created(
            api.create_valuation(
                valuation_payload(film["id"], territory["id"], "CAST_ADJUSTED"),
                make_sales_agent_headers(),
            )
        )

        assert created["comp_sample_size"] == 3, (
            "the unverified, off-genre, out-of-lookback and foreign rows are all excluded: "
            f"expected comp_sample_size 3, got {created['comp_sample_size']}"
        )
        assert_money(created["comp_median_usd"], 1000000.00, "comp_median_usd")
        assert_money(created["estimate_usd"], 1680000.00, "estimate_usd")

    def test_comparable_weighted_method_freezes_the_cast_multiplier_at_one(self, api):
        """The method field alone selects the variant and both rows freeze their own multiplier.

        PRD: "Under `COMPARABLE_WEIGHTED` — the pure market view the agency uses to argue a territory's floor to financiers — `cast_multiplier` is forced to exactly 1.00, the film's `principal_cast_score` is ignored entirely, and `estimate_usd` is the comparable median multiplied by the territory's `base_value_index`, rounded half-up to two decimal places."

        PRD: "Under `CAST_ADJUSTED` — the packaging view used to argue the ask to buyers — `cast_multiplier` takes the value the cast tier function returns for the film's `principal_cast_score`, and `estimate_usd` is the comparable median multiplied by the territory's `base_value_index` and then by that cast multiplier, rounded half-up to two decimal places."

        PRD: "`floor_price_usd` is the estimate multiplied by a floor discount of 0.70, rounded half-up to two decimal places — the minimum guarantee floor that will be enforced when a contract for this territory is countersigned."

        PRD: "A valuation never re-samples its comparables: if the comparable set changes, the agency creates a new valuation."

        Design: Corner/calculations/comparable_weighted_variant_forces_the_cast_multiplier_to_one
        """
        pin_clock(api, CLOCK_DEFAULT)
        film = make_film(api, principal_cast_score=88)
        territory = make_territory(api, base_value_index=1.20)
        make_comparables(
            api,
            territory["id"],
            fees=(800000.00, 1000000.00, 1200000.00),
            years=(2022, 2023, 2021),
        )

        weighted = assert_created(
            api.create_valuation(
                valuation_payload(film["id"], territory["id"], "COMPARABLE_WEIGHTED"),
                make_sales_agent_headers(),
            )
        )
        cast_adjusted = assert_created(
            api.create_valuation(
                valuation_payload(film["id"], territory["id"], "CAST_ADJUSTED"),
                make_sales_agent_headers(),
            )
        )

        _assert_ratio(weighted["cast_multiplier"], 1.00, "cast_multiplier")
        assert_money(weighted["estimate_usd"], 1200000.00, "estimate_usd")
        assert_money(weighted["floor_price_usd"], 840000.00, "floor_price_usd")
        _assert_ratio(cast_adjusted["cast_multiplier"], 1.40, "cast_multiplier")
        assert_money(cast_adjusted["estimate_usd"], 1680000.00, "estimate_usd")
        for row in (weighted, cast_adjusted):
            assert_money(row["comp_median_usd"], 1000000.00, "comp_median_usd")
            assert row["comp_sample_size"] == 3, (
                f"expected comp_sample_size 3, got {row['comp_sample_size']}"
            )


class TestCreditGateAndLenderArithmetic:
    def test_net_execution_headroom_multiplies_the_limit_rather_than_the_exposure(self, api):
        """Execution is measured against 1.50 times the buyer's limit, so 1333333.34 clears 2000000.00.

        PRD: "Sixth, the net credit gate: the buyer's net unpaid exposure plus this contract's `unpaid_amount_usd` must not exceed the buyer's `exposure_limit_usd` multiplied by a net execution headroom of 1.50, that product rounded half-up to two decimal places, else `ERR_BUYER_NET_EXPOSURE_EXCEEDED`; landing exactly on the headroom passes."

        Design: Corner/calculations/net_execution_headroom_constant_gates_execution_at_one_point_five_times_the_limit
        """
        env = accepted_contract(api, minimum_guarantee_usd=2000000.00)
        contract_id = env["contract"]["id"]
        buyer_id = env["buyer"]["id"]

        # The gross gate passed at offer time against the raw 3000000.00 limit; the
        # limit is only now trimmed so that the execution-time ceiling binds.
        get_success_data(
            api.patch_buyer(
                buyer_id,
                buyer_amendment_payload(exposure_limit_usd=1000000.00),
                make_platform_admin_headers(),
            )
        )

        validate_error(
            api.execute_contract(
                contract_id, make_head_of_sales_headers(HEAD_OF_SALES_CLOSER)
            ),
            "ERR_BUYER_NET_EXPOSURE_EXCEEDED",
            422,
        )
        blocked = read_contract(api, contract_id)
        assert_contract_axes(blocked, negotiation="ACCEPTED")
        assert blocked["license_start_date"] is None, (
            "a rejected countersigning must not stamp license_start_date"
        )

        get_success_data(
            api.patch_buyer(
                buyer_id,
                buyer_amendment_payload(exposure_limit_usd=1333333.34),
                make_platform_admin_headers(),
            )
        )
        executed = assert_object_response(
            api.execute_contract(
                contract_id, make_head_of_sales_headers(HEAD_OF_SALES_CLOSER)
            ),
            200,
        )

        assert_contract_axes(executed, negotiation="EXECUTED")
        assert_instant(executed["license_start_date"], CLOCK_DEFAULT, "license_start_date")
        assert_buyer_exposure(read_buyer(api, buyer_id), gross=2000000.00, net=2000000.00)

    def test_discounted_collateral_drops_the_already_received_milestone(self, api):
        """A milestone booked before the facility exists leaves the discount base at 1100000.00.

        PRD: "Within an eligible contract, only milestones whose `status` is `SCHEDULED` or `INVOICED` count; `RECEIVED` and `WRITTEN_OFF` milestones drop out, since the first has already been paid and the second never will be."

        PRD: "The tenor is the **latest** `due_date` among those unpaid milestones — not the earliest, and not a weighted average."

        PRD: "The discount factor is one minus the product of the facility's `discount_rate_pct` and the days to payment divided by 365, that whole expression rounded half-up to 6 decimal places."

        PRD: "The contract's value is then the rounded unpaid sum multiplied by the facility's `advance_rate_pct` and by the discount factor, rounded half-up to two decimal places."

        PRD: "Then, if `completion_bond_required` is true and `completion_bond_posted` is still false, halve that figure — the unbonded haircut is exactly 0.50 — and round to two decimal places."

        Design: Corner/calculations/discounted_advance_input_set_drops_the_received_milestone_from_the_base
        """
        env = executed_contract_environment(api)
        signature = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")
        assert_money(signature["amount_usd"], 900000.00, "ON_SIGNATURE amount_usd")
        post_receipt(api, signature, "2026-08-05T00:00:00Z")

        facility = assert_created(
            api.create_banking_facility(
                env["film"]["id"],
                {
                    "lender_name": "Cine Lend Bank",
                    "discount_rate_pct": 0.08,
                    "advance_rate_pct": 0.80,
                    "facility_cap_usd": 1000000.00,
                },
                make_lender_headers(),
            )
        )

        assert_facility_figures(
            facility, collateral=739007.28, advance=369503.64, status="PROPOSED"
        )
        _assert_not_money(
            facility["eligible_collateral_usd"], 1343649.60, "eligible_collateral_usd"
        )
        assert_money_precision(facility["eligible_collateral_usd"], "eligible_collateral_usd")
        assert_money_precision(facility["advance_amount_usd"], "advance_amount_usd")

        received = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")
        assert received["status"] == "RECEIVED", (
            f"the booked milestone must be RECEIVED, got {received['status']}"
        )
        for label, amount in (
            ("ON_DELIVERY", 400000.00),
            ("ON_RELEASE", 200000.00),
            ("ON_TERM_END", 500000.00),
        ):
            row = milestone_by_label(read_milestones(api, env["contract"]["id"]), label)
            assert row["status"] in ("SCHEDULED", "INVOICED"), (
                f"{label} must still be discountable, got {row['status']}"
            )
            assert_money(row["amount_usd"], amount, f"{label} amount_usd")

    def test_posting_the_bond_lifts_the_advance_to_the_cap_not_to_half_the_collateral(
        self, api
    ):
        """The unbonded haircut applies after the cap, so the bond lifts 500000.00 to 1000000.00.

        PRD: "First take the lesser of the facility's `facility_cap_usd` and its `eligible_collateral_usd`. Then, if `completion_bond_required` is true and `completion_bond_posted` is still false, halve that figure — the unbonded haircut is exactly 0.50 — and round to two decimal places."

        PRD: "It sets `completion_bond_posted` to true, writes both supplied fields, and recomputes `advance_amount_usd` without the unbonded haircut — typically doubling it."

        PRD: "The contract's value is then the rounded unpaid sum multiplied by the facility's `advance_rate_pct` and by the discount factor, rounded half-up to two decimal places."

        Design: Corner/calculations/posting_the_completion_bond_removes_the_haircut_and_the_facility_cap_binds
        """
        env = executed_contract(api)
        facility = make_facility(
            api,
            env["film"]["id"],
            discount_rate_pct=0.08,
            advance_rate_pct=0.80,
            facility_cap_usd=1000000.00,
            completion_bond_required=True,
        )
        approved = approve_facility(api, facility["id"])

        assert_facility_figures(
            approved, collateral=1343649.60, advance=500000.00, status="APPROVED"
        )
        assert approved["completion_bond_posted"] is False, (
            "the bond has not been posted yet"
        )

        bonded = bond_facility(
            api, facility["id"], bond_provider="Guarantor Global", bond_amount_usd=24000000.00
        )

        assert bonded["completion_bond_posted"] is True, (
            "posting the bond sets completion_bond_posted true"
        )
        assert_money(bonded["advance_amount_usd"], 1000000.00, "advance_amount_usd")
        _assert_not_money(bonded["advance_amount_usd"], 671824.80, "advance_amount_usd")
        assert_facility_figures(
            bonded, collateral=1343649.60, drawn=0.00, status="APPROVED"
        )
        assert_facility_figures(
            read_facility(api, env["film"]["id"], facility["id"]),
            collateral=1343649.60,
            advance=1000000.00,
        )


class TestExecutionDatesAndDeliveryThresholds:
    def test_license_end_date_clamps_to_the_last_day_of_a_shorter_target_month(self, api):
        """An 18-month term countersigned on 31 August clamps to the leap day 29 February 2028.

        PRD: "`license_start_date` is stamped with the logical present instant, and `license_end_date` is that instant plus `license_term_months` calendar months, using the same same-day-of-month rule with clamping to a shorter target month's last day."

        PRD: "`holdback_release_date` is computed as the picture's `theatrical_release_date` — as it stands at execution time, not as it stood when the offer was made — plus `holdback_days` whole days."

        PRD: "The contract's `unpaid_amount_usd` is computed as the sum of `amount_usd` across its `SCHEDULED` and `INVOICED` payment milestones, and `received_amount_usd` as the sum of `received_amount_usd` across its `RECEIVED` milestones."

        Design: Corner/calculations/license_end_date_clamps_to_the_last_day_of_a_shorter_target_month
        """
        env = slate_with_published_valuation(api)
        buyer_version = read_buyer(api, env["buyer"]["id"])["version"]
        contract = get_success_data(
            api.create_contract(
                contract_payload(
                    env["film"]["id"],
                    env["buyer"]["id"],
                    env["territory"]["id"],
                    buyer_version,
                    minimum_guarantee_usd=2000000.00,
                    license_term_months=18,
                    holdback_days=45,
                ),
                make_sales_agent_headers(),
            )
        )
        add_milestone_schedule(
            api,
            contract["id"],
            schedule=(
                ("ON_SIGNATURE", 0.45, "2026-09-01T00:00:00Z", 900000.00),
                ("ON_DELIVERY", 0.20, "2027-06-15T00:00:00Z", 400000.00),
                ("ON_RELEASE", 0.10, "2027-07-15T00:00:00Z", 200000.00),
                ("ON_TERM_END", 0.25, "2028-02-29T00:00:00Z", 500000.00),
            ),
        )
        get_success_data(
            api.accept_contract(contract["id"], make_buyer_headers(env["buyer"]["id"]))
        )
        pin_clock(api, "2026-08-31T00:00:00Z")

        executed = assert_object_response(
            api.execute_contract(
                contract["id"], make_head_of_sales_headers(HEAD_OF_SALES_CLOSER)
            ),
            200,
        )

        assert_instant(
            executed["license_start_date"], "2026-08-31T00:00:00Z", "license_start_date"
        )
        assert_instant(
            executed["license_end_date"], "2028-02-29T00:00:00Z", "license_end_date"
        )
        assert_instant(
            executed["holdback_release_date"],
            "2027-05-30T00:00:00Z",
            "holdback_release_date",
        )
        assert_contract_axes(executed, negotiation="EXECUTED")
        assert_money(executed["unpaid_amount_usd"], 2000000.00, "unpaid_amount_usd")

    def test_deliverable_thresholds_are_two_independent_inclusive_floors(self, api):
        """Thirteen technical items fail, five legal items fail, and exactly 14 with 6 passes.

        PRD: "Exactly 14 technical and exactly 6 legal items is complete; one fewer of either is not, and the submission is rejected with `ERR_DELIVERABLES_INCOMPLETE`."

        PRD: "`technical_items_count` — masters, music-and-effects tracks, subtitle files, quality-control reports and the rest — must be at least 14."

        PRD: "`legal_items_count` — chain of title, errors-and-omissions insurance, music cue sheets and the rest — must be at least 6."

        PRD: "Its `revision_round` is 1 when no prior package exists for this contract, and otherwise one more than the `revision_round` of the contract's latest package, selected as the last row by `created_at` ascending."

        Design: Corner/calculations/deliverable_thresholds_pass_at_exactly_fourteen_and_six_and_fail_one_short
        """
        env = executed_contract(api)
        contract_id = env["contract"]["id"]
        pin_clock(api, "2027-06-14T00:00:00Z")

        validate_error(
            api.create_deliverable_package(
                contract_id, package_payload(13, 6), make_delivery_manager_headers()
            ),
            "ERR_DELIVERABLES_INCOMPLETE",
            422,
        )
        validate_error(
            api.create_deliverable_package(
                contract_id, package_payload(14, 5), make_delivery_manager_headers()
            ),
            "ERR_DELIVERABLES_INCOMPLETE",
            422,
        )
        assert_contract_axes(read_contract(api, contract_id), delivery="PENDING")

        package = assert_created(
            api.create_deliverable_package(
                contract_id, package_payload(14, 6), make_delivery_manager_headers()
            )
        )

        assert package["revision_round"] == 1, (
            f"expected revision_round 1, got {package['revision_round']}"
        )
        assert package["status"] == "SUBMITTED", (
            f"expected status SUBMITTED, got {package['status']}"
        )
        assert package["qc_result"] == "PENDING", (
            f"expected qc_result PENDING, got {package['qc_result']}"
        )
        assert_list_response(
            api.list_deliverable_packages(
                contract_id, make_delivery_manager_headers(), {"limit": 100}
            ),
            expected_total=1,
            expected_rows=1,
        )
        assert_contract_axes(read_contract(api, contract_id), delivery="SUBMITTED")


class TestWaterfallResidual:
    def test_fully_capped_waterfall_leaves_the_unallocated_cash_in_the_account(self, api):
        """With every tier capped there is no sweep destination, so 755000.00 stays behind.

        PRD: "If no uncapped `ACTIVE` tier exists at all, the cash simply stays in the account."

        PRD: "First compute the tier's target as the current remaining figure multiplied by the tier's `pct_of_available`, **rounded half-up to two decimal places immediately**."

        PRD: "If the tier has a `cap_usd`, compute its remaining room as `cap_usd` less `recouped_usd`, rounded to two decimal places, and reduce the target to the lesser of the two."

        PRD: "`residual_usd` is `amount_in_usd` less `amount_allocated_usd`, rounded to two decimal places — cash that stayed behind because no uncapped `ACTIVE` tier could absorb it."

        PRD: "When the prior total is below one million dollars, the rate is the agreement's `commission_pct` unchanged."

        PRD: "Step three: the commission this receipt accrues is the posted `amount_usd` multiplied by that single rate, rounded half-up to two decimal places."

        Design: Corner/calculations/fully_capped_waterfall_leaves_the_unallocated_cash_in_the_account
        """
        env = executed_contract_environment(api)
        account_id = env["account"]["id"]
        signature = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")
        assert_money(signature["amount_usd"], 900000.00, "ON_SIGNATURE amount_usd")
        post_receipt(api, signature, "2026-08-05T00:00:00Z")
        fee_tier, equity_tier = make_tiers(
            api,
            account_id,
            (
                (1, "COLLECTION_FEE", 0.05, 50000.00),
                (2, "EQUITY_RECOUPMENT", 1.00, 100000.00),
            ),
        )

        run = assert_created(
            api.distribute(
                account_id,
                distribute_payload(900000.00),
                make_collection_agent_headers(),
            )
        )

        assert run["run_index"] == 1, f"expected run_index 1, got {run['run_index']}"
        assert_money(run["amount_in_usd"], 900000.00, "amount_in_usd")
        assert_money(run["amount_allocated_usd"], 145000.00, "amount_allocated_usd")
        assert_money(run["residual_usd"], 755000.00, "residual_usd")
        assert_allocations(run, [45000.00, 100000.00], tier_count=2)

        tiers = read_tiers(api, account_id)
        assert_tier(
            find_by(tiers, id=fee_tier["id"]), recouped=45000.00, cap=50000.00, status="ACTIVE"
        )
        assert_tier(
            find_by(tiers, id=equity_tier["id"]),
            recouped=100000.00,
            cap=100000.00,
            status="SATISFIED",
        )
        assert_account_counters(
            read_account(api, account_id),
            receipts=900000.00,
            distributed=145000.00,
            balance=755000.00,
            run_count=1,
        )
        agreement = read_agreement(api, env["film"]["id"], env["agreement"]["id"])
        assert_money(
            agreement["commission_earned_usd"], 90000.00, "commission_earned_usd"
        )
