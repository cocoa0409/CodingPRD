"""Formulas that combine several inputs under a pinned evaluation order.

Covers the endowment's per-row-then-sum rounding, the in-lieu-fee administrative
tier that is selected from the base fee and never revisited, and the three-input
effect-determination ladder.
"""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers.assertions import assert_same_instant
from test_helpers.fixtures import (
    add_commitment,
    build_scenario,
    read_bank,
    read_consultation,
    read_plan,
    record_field_survey,
    open_project_action,
    run_effect_determination,
)


def _plan_with_bank_commitment(units):
    """A DRAFT plan carrying exactly one conservation-bank commitment."""
    scenario = build_scenario("plan")
    scenario["c1"] = add_commitment(
        scenario["plan"]["id"],
        scenario["proponent"],
        {
            "mechanism": "CONSERVATION_BANK_CREDIT",
            "units": units,
            "conservation_bank_id": scenario["bank"]["id"],
        },
    )
    scenario["plan"] = read_plan(scenario["plan"]["id"], scenario["proponent_headers"])
    return scenario


class TestEndowmentRoundingOrder:
    """Round each commitment to cents first, then sum, then take the reserve."""

    def test_each_commitment_contribution_is_rounded_before_the_plan_sums_them(self, api):
        """Two contributions ending in half a cent sum to an odd total.

        PRD: "Each contributing commitment's own `endowment_contribution_cents` is
        its `units` multiplied by the annual stewardship cost of 4,175 cents per unit
        per year ... multiplied by a capitalization horizon of 30 years, multiplied by
        a mechanism factor of 0.60 for `CONSERVATION_BANK_CREDIT` ... with the result
        rounded half up to whole cents."

        PRD: "`endowment_base_cents` is then the sum of those **per-commitment
        rounded** contributions - round each, then add, never add the raw products and
        round once."

        45.01 units raise 3,382,501.5 raw and store 3,382,502; 14.71 units raise
        1,105,456.5 raw and store 1,105,457; the base is therefore 4,487,959 and not
        the 4,487,958 that summing the two raw products would yield.

        Design: Difficulty/combinatorial_formula/endowment_rounds_per_commitment_then_sums_reserve_on_rounded_base
        """
        scenario = _plan_with_bank_commitment(45.01)
        c2 = add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": 14.71,
                "conservation_bank_id": scenario["bank"]["id"],
            },
        )

        assert scenario["c1"]["endowment_contribution_cents"] == 3_382_502
        assert c2["endowment_contribution_cents"] == 1_105_457
        plan = read_plan(scenario["plan"]["id"], scenario["proponent_headers"])
        assert plan["endowment_base_cents"] == 4_487_959
        assert plan["endowment_base_cents"] != 4_487_958

    def test_changed_circumstance_reserve_is_taken_from_the_rounded_base(self, api):
        """The reserve percentage never sees the raw sum.

        PRD: "`changed_circumstance_reserve_cents` is twelve percent of that
        already-rounded base, rounded half up to whole cents.
        `endowment_required_cents` is `endowment_base_cents` plus
        `changed_circumstance_reserve_cents`. And `reserve_remaining_cents` is
        `changed_circumstance_reserve_cents` minus `reserve_drawn_cents`, floored at
        0 - the reserve can be drained to exactly zero but never below."

        12% of 4,487,959 is 538,555.08, which rounds to 538,555, and the required
        total is 5,026,514.

        Design: Difficulty/combinatorial_formula/endowment_rounds_per_commitment_then_sums_reserve_on_rounded_base
        """
        scenario = _plan_with_bank_commitment(45.01)
        add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": 14.71,
                "conservation_bank_id": scenario["bank"]["id"],
            },
        )

        plan = read_plan(scenario["plan"]["id"], scenario["proponent_headers"])
        assert plan["changed_circumstance_reserve_cents"] == 538_555
        assert plan["endowment_required_cents"] == 5_026_514
        assert plan["reserve_remaining_cents"] == 538_555
        assert plan["reserve_drawn_cents"] == 0
        assert plan["secured_mitigation_units"] == 59.72
        assert plan["funding_status"] == "UNFUNDED"
        assert plan["endowment_secured_cents"] == 0

    def test_reserve_is_recomputed_from_the_rounded_base_on_every_commitment(self, api):
        """After a single commitment the reserve already tracks the rounded base.

        PRD: "The plan's `endowment_base_cents`,
        `changed_circumstance_reserve_cents`, `endowment_required_cents`,
        `reserve_remaining_cents`, and `secured_mitigation_units` are all recomputed"
        on every accepted commitment, and the endowment requirement "is recomputed
        from scratch whenever the commitment set changes."

        With only the 45.01-unit commitment booked the base is 3,382,502 and 12% of
        it is 405,900.24, which rounds to 405,900.

        Design: Difficulty/combinatorial_formula/endowment_rounds_per_commitment_then_sums_reserve_on_rounded_base
        """
        scenario = _plan_with_bank_commitment(45.01)

        plan = scenario["plan"]
        assert plan["endowment_base_cents"] == 3_382_502
        assert plan["changed_circumstance_reserve_cents"] == 405_900
        assert plan["endowment_required_cents"] == 3_788_402

    def test_bank_credit_commitment_carries_a_zero_administrative_tier(self, api):
        """The tier table is gated on the mechanism, not on the amount.

        PRD: "the tier table is **mechanism-gated rather than amount-gated**: it
        applies to `IN_LIEU_FEE` commitments only. ... For every other mechanism,
        `admin_fee_pct_applied` is 0.000 - a bank-credit commitment whose
        `base_fee_cents` happens to land inside an in-lieu-fee band still carries
        0.000. The field is stored with exactly three decimal places."

        PRD: "Step three computes `admin_fee_cents` as `base_fee_cents` multiplied by
        `admin_fee_pct_applied` ... It is therefore 0 for every mechanism other than
        `IN_LIEU_FEE`. Step four sets `total_cost_cents` to `base_fee_cents` plus
        `admin_fee_cents`".

        A bank commitment of 14.71 credits at 250,000 cents each prices at
        3,677,500 and pays no administrative fee even though that base would land in
        a populated in-lieu-fee tier.

        Design: Difficulty/combinatorial_formula/endowment_rounds_per_commitment_then_sums_reserve_on_rounded_base
        """
        scenario = _plan_with_bank_commitment(45.01)

        c2 = add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": 14.71,
                "conservation_bank_id": scenario["bank"]["id"],
            },
        )

        assert c2["base_fee_cents"] == 3_677_500
        assert c2["admin_fee_pct_applied"] == 0.000
        assert c2["admin_fee_cents"] == 0
        assert c2["total_cost_cents"] == 3_677_500


class TestInLieuFeeTierPinning:
    """The administrative tier is chosen from the base fee, once."""

    def test_tier_is_selected_from_the_base_fee_and_never_from_the_total(self, api):
        """A base under the first strict bound pays 0.150 even though the total is not.

        PRD: "the order is normative because the formula reads as though it were
        circular - the administrative fee depends on the total, and the total depends
        on the fee. It is not circular, because the tier is selected from the **base**
        and never re-selected from the total."

        PRD: "`admin_fee_pct_applied` is 0.150 when `base_fee_cents` is below
        5,000,000 cents ... 0.115 when `base_fee_cents` is below 20,000,000 cents ...
        but not below the first bound".

        27.00 in-lieu units price at 4,927,500, which is below the first bound, so the
        fee is 739,125 and the total 5,666,625 - not the 5,579,162 a re-selection from
        that total would produce, nor the 5,494,163 tier two applied to the base
        would produce.

        Design: Difficulty/combinatorial_formula/in_lieu_fee_tier_pinned_to_base_never_reselected_from_total
        """
        scenario = build_scenario("plan")

        commitment = add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {"mechanism": "IN_LIEU_FEE", "units": 27.00},
        )

        assert commitment["base_fee_cents"] == 4_927_500
        assert commitment["admin_fee_pct_applied"] == 0.150
        assert commitment["admin_fee_cents"] == 739_125
        assert commitment["total_cost_cents"] == 5_666_625
        assert commitment["total_cost_cents"] != 5_579_162
        assert commitment["total_cost_cents"] != 5_494_163

    def test_in_lieu_fee_commitment_names_no_bank_and_moves_no_credits(self, api):
        """The bank ledger is untouched by a non-bank mechanism.

        PRD: "That last field is strictly mechanism-gated: it is **required** when
        `mechanism` is `CONSERVATION_BANK_CREDIT` and must be omitted or null for
        every other mechanism."

        PRD: "Every accepted commitment is created in `status` `RESERVED`. For a
        `CONSERVATION_BANK_CREDIT` commitment, the bank's `credits_available`
        decreases by `units` and its `credits_reserved` increases by the same `units`".

        Design: Difficulty/combinatorial_formula/in_lieu_fee_tier_pinned_to_base_never_reselected_from_total
        """
        scenario = build_scenario("plan")

        commitment = add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {"mechanism": "IN_LIEU_FEE", "units": 27.00},
        )

        assert commitment.get("conservation_bank_id") is None
        assert commitment["status"] == "RESERVED"
        bank = read_bank(scenario["bank"]["id"])
        assert bank["credits_available"] == 500.00
        assert bank["credits_reserved"] == 0.00
        assert bank["credits_transferred"] == 0.00

    def test_in_lieu_fee_endowment_uses_its_own_mechanism_factor(self, api):
        """The 0.85 factor drives both the commitment and the plan aggregates.

        PRD: "multiplied by a mechanism factor of 0.60 for
        `CONSERVATION_BANK_CREDIT`, 0.85 for `IN_LIEU_FEE`, or 1.00 for
        `PERMITTEE_RESPONSIBLE`, with the result rounded half up to whole cents."

        27.00 x 4,175 x 30 x 0.85 is 2,874,487.5 and stores 2,874,488; twelve percent
        of that is 344,938.56 and stores 344,939, for a requirement of 3,219,427.

        Design: Difficulty/combinatorial_formula/in_lieu_fee_tier_pinned_to_base_never_reselected_from_total
        """
        scenario = build_scenario("plan")

        commitment = add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {"mechanism": "IN_LIEU_FEE", "units": 27.00},
        )

        assert commitment["endowment_contribution_cents"] == 2_874_488
        plan = read_plan(scenario["plan"]["id"], scenario["proponent_headers"])
        assert plan["endowment_base_cents"] == 2_874_488
        assert plan["changed_circumstance_reserve_cents"] == 344_939
        assert plan["endowment_required_cents"] == 3_219_427


class TestEffectDeterminationLadder:
    """The same overlap percentage resolves two ways depending on listing rank."""

    def _two_mirror_actions(self):
        """Two actions of one proponent, identical but for the species surveyed."""
        scenario = build_scenario("action")
        record_field_survey(
            scenario["action"],
            scenario["proponent"],
            scenario["threatened_species"]["id"],
        )
        scenario["action_a"] = run_effect_determination(
            scenario["action"], scenario["proponent"]
        )
        action_b = open_project_action(
            scenario["proponent"], action_name="Sunrise Park Phase II"
        )
        record_field_survey(action_b, scenario["proponent"], scenario["species"]["id"])
        scenario["action_b"] = run_effect_determination(action_b, scenario["proponent"])
        return scenario

    def test_equal_overlap_percentage_resolves_differently_by_listing_rank(self, api):
        """Ten acres of a two-hundred-acre footprint is NLAA or LAA by rank alone.

        PRD: "Otherwise, if `overlap_pct` is at most 5.00, there **is** a confirmed
        presence, and the maximum listing rank is exactly 2 - a `THREATENED` species -
        the determination is `NLAA`. In every remaining case the determination is
        `LAA`. ... The practical shape of the rule is that a confirmed `ENDANGERED`
        presence goes to `LAA` at any positive overlap, while a confirmed `THREATENED`
        presence stays `NLAA` all the way up to and including five percent."

        Both actions report `total_overlap_acres` 10.00 and `overlap_pct` 5.00, yet the
        threatened action clears at NLAA while the endangered action falls through to
        LAA and opens a formal consultation.

        Design: Difficulty/combinatorial_formula/effect_determination_three_input_ladder_rank_beats_equal_percentage
        """
        scenario = self._two_mirror_actions()
        action_a, action_b = scenario["action_a"], scenario["action_b"]

        assert action_a["total_overlap_acres"] == 10.00
        assert action_a["overlap_pct"] == 5.00
        assert action_a["effect_determination"] == "NLAA"
        assert action_b["total_overlap_acres"] == 10.00
        assert action_b["overlap_pct"] == 5.00
        assert action_b["effect_determination"] == "LAA"
        assert action_b["status"] == "FORMAL_CONSULTATION"
        assert action_b["active_consultation_id"] is not None

    def test_the_two_consultations_differ_in_type_statutory_days_and_deadline(self, api):
        """One fork opens sixty informal days, the other a hundred and thirty-five.

        PRD: "On `NLAA`, the action moves `SCREENING - INFORMAL_CONSULTATION` ... and
        exactly one consultation is created with `consultation_type` `INFORMAL`,
        `status` `DRAFT_BA`, `clock_started_at` at the current logical clock,
        `statutory_days` of 60, and `tolled_days` of 0 ... On `LAA` ... exactly one
        consultation is created with `consultation_type` `FORMAL` ... `statutory_days`
        of 135, and `tolled_days` of 0".

        PRD: "`deadline_at` is `clock_started_at` advanced by a number of days equal to
        `statutory_days` plus `tolled_days`".

        Design: Difficulty/combinatorial_formula/effect_determination_three_input_ladder_rank_beats_equal_percentage
        """
        scenario = self._two_mirror_actions()

        consultation_a = read_consultation(scenario["action_a"]["active_consultation_id"])
        consultation_b = read_consultation(scenario["action_b"]["active_consultation_id"])

        assert consultation_a["consultation_type"] == "INFORMAL"
        assert consultation_a["statutory_days"] == 60
        assert_same_instant(consultation_a["deadline_at"], "2026-11-30T00:00:00Z")
        assert consultation_b["consultation_type"] == "FORMAL"
        assert consultation_b["statutory_days"] == 135
        assert_same_instant(consultation_b["deadline_at"], "2027-02-13T00:00:00Z")

    def test_the_endangered_action_carries_exactly_one_in_season_present_row(self, api):
        """The ladder read a single candidate row, detected and in season.

        PRD: "A `FIELD_SURVEY` can: `DETECTED` yields `PRESENT`".

        PRD: "`survey_in_season` is computed from the calendar month of
        `survey_window_start` and the calendar month of `survey_window_end`, tested
        against the species' detectability season, and it is true only when **both**
        months fall inside that season."

        Design: Difficulty/combinatorial_formula/effect_determination_three_input_ladder_rank_beats_equal_percentage
        """
        scenario = self._two_mirror_actions()

        response = api.list_presence_determinations(
            scenario["proponent_headers"],
            params={"project_action_id": scenario["action_b"]["id"]},
        )
        rows, _meta = validate_paginated(response)

        assert len(rows) == 1
        assert rows[0]["presence_status"] == "PRESENT"
        assert rows[0]["survey_in_season"] is True
