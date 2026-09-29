"""Money and calendar arithmetic: endowments, take ceilings, dates and penalties.

Every test here translates one `calculations` instance from the corner design
index: the mechanism factors behind the endowment, the primary-species tie-break
that decides the take budget, the take-unit switch on density, the 45-day report
due date, the 180-day compliance decay boundary, the changed-circumstance
waterfall, penalty accumulation across categories, and the global permit ordinal
with its leap-day term clamp.
"""

from prd_bench_local_runner.testing import get_success_data
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_bank_ledger_identity,
    assert_error_envelope,
    assert_response_cost_identity,
    assert_unpaginated_list,
)
from test_helpers.factories import (
    circumstance_response_payload,
    habitat_conservation_plan_payload,
)
from test_helpers.fixtures import (
    add_commitment,
    adjudicate_report,
    build_scenario,
    decide_plan,
    file_monitoring_report,
    fully_fund_plan,
    issue_biological_opinion,
    issue_permit,
    read_bank,
    read_permit,
    read_plan,
    read_proponent,
    record_field_survey,
    register_species,
    report_circumstance,
    respond_to_circumstance,
    run_effect_determination,
    set_clock,
    setup_second_action,
    setup_take_exceedance,
    submit_biological_assessment,
    submit_plan,
)


class TestEndowmentMechanismFactors:
    """The mechanism factor, not the unit count, separates two identical rows."""

    def test_two_ten_unit_commitments_endow_differently_and_the_reserve_reads_the_base(
        self, api
    ):
        """Same units, three mechanisms, three endowment contributions.

        PRD: "Each contributing commitment's own `endowment_contribution_cents` is
        its `units` multiplied by the annual stewardship cost of 4,175 cents per
        unit per year - forty-one dollars and seventy-five cents - multiplied by a
        capitalization horizon of 30 years, multiplied by a mechanism factor of 0.60
        for `CONSERVATION_BANK_CREDIT`, 0.85 for `IN_LIEU_FEE`, or 1.00 for
        `PERMITTEE_RESPONSIBLE`, with the result rounded half up to whole cents."

        PRD: "`endowment_base_cents` is then the sum of those **per-commitment
        rounded** contributions - round each, then add, never add the raw products
        and round once. `changed_circumstance_reserve_cents` is twelve percent of
        that already-rounded base, rounded half up to whole cents.
        `endowment_required_cents` is `endowment_base_cents` plus
        `changed_circumstance_reserve_cents`."

        Ten permittee-responsible units endow 1,252,500 cents while ten in-lieu-fee
        units endow 1,064,625, so the base is 2,317,125, the twelve percent reserve
        is 278,055 and the requirement is 2,595,180. A third ten-unit commitment
        bought from a conservation bank would endow only 751,500.

        Design: Corner/calculations/endowment_mechanism_factors_and_reserve_on_the_rounded_base
        """
        scenario = build_scenario("plan")
        plan_id = scenario["plan"]["id"]

        permittee = add_commitment(
            plan_id, scenario["proponent"], {"mechanism": "PERMITTEE_RESPONSIBLE", "units": 10.00}
        )
        in_lieu = add_commitment(
            plan_id, scenario["proponent"], {"mechanism": "IN_LIEU_FEE", "units": 10.00}
        )
        plan = read_plan(plan_id, scenario["proponent_headers"])

        assert permittee["endowment_contribution_cents"] == 1_252_500
        assert in_lieu["endowment_contribution_cents"] == 1_064_625
        assert plan["endowment_base_cents"] == 2_317_125
        assert plan["changed_circumstance_reserve_cents"] == 278_055
        assert plan["endowment_required_cents"] == 2_595_180
        assert plan["reserve_remaining_cents"] == 278_055
        assert plan["reserve_drawn_cents"] == 0
        assert plan["endowment_secured_cents"] == 0
        assert plan["funding_status"] == "UNFUNDED"
        assert plan["funded_ratio"] == 0.0000

        bank_credit = add_commitment(
            plan_id,
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": 10.00,
                "conservation_bank_id": scenario["bank"]["id"],
            },
        )

        assert bank_credit["endowment_contribution_cents"] == 751_500


class TestPrimarySpeciesTieBreak:
    """Equal listing rank hands the opinion to the rarer species."""

    def test_the_smaller_recovery_population_wins_the_tie_and_owns_the_exposure(self, api):
        """Two ENDANGERED species tie, and the 1,200-population one takes the opinion.

        PRD: "Within that pool the species with the **highest** listing rank wins;
        ties are broken first by the **smallest** `recovery_unit_population` and then
        by the **earliest** species `created_at`."

        PRD: "`exposed_acres` is then the sum of `habitat_overlap_acres` over only
        those candidate rows that reference the primary species - rows about other
        species contribute nothing to the exposure figure."

        PRD: "`jeopardy_fraction` is `authorized_take_units` divided by the primary
        species' `recovery_unit_population`, rounded half up to four decimal places."

        The action carries 10.00 acres for the 4,000-population species and 12.50 for
        the 1,200-population one, so the exposure is 12.50 rather than the 22.50 total,
        the take is 5.00 individuals and the fraction is 0.0042.

        Design: Corner/calculations/primary_species_tie_break_uses_the_smallest_recovery_population
        """
        scenario = build_scenario(
            "action", include_unit=False, include_threatened=False, include_bank=False
        )
        frog = register_species(
            scientific_name="Rana muscosa",
            common_name="Mountain yellow-legged frog",
            recovery_unit_population=1200,
        )
        record_field_survey(
            scenario["action"],
            scenario["proponent"],
            scenario["species"]["id"],
            habitat_overlap_acres=10.00,
        )
        record_field_survey(
            scenario["action"], scenario["proponent"], frog["id"], habitat_overlap_acres=12.50
        )
        action = run_effect_determination(scenario["action"], scenario["proponent"])
        consultation_id = action["active_consultation_id"]
        submit_biological_assessment(consultation_id, scenario["proponent"])

        opinion = issue_biological_opinion(consultation_id)

        assert opinion["primary_species_scientific_name"] == "Rana muscosa"
        assert opinion["primary_species_listing_status"] == "ENDANGERED"
        assert opinion["exposed_acres"] == 12.50
        assert opinion["take_unit"] == "INDIVIDUALS"
        assert opinion["authorized_take_units"] == 5.00
        assert opinion["jeopardy_fraction"] == 0.0042
        assert opinion["conclusion"] == "NO_JEOPARDY"
        assert opinion["rpa_required"] is False
        assert opinion["rpa_description"] is None
        assert opinion["reinitiation_trigger_units"] == 4.50
        assert opinion["issued_late"] is False


class TestTakeUnitDensityApplication:
    """The take unit alone decides whether the density is a multiplier or noise."""

    def test_an_acres_species_ignores_the_density_that_a_nests_species_applies(self, api):
        """The same 12.50 exposed acres become 12.50 acres of take or 1.50 nests.

        PRD: "When `take_unit` is `INDIVIDUALS` or `NESTS`, the raw take is
        `exposed_acres` multiplied by the primary species' `take_density_per_acre`;
        when `take_unit` is `ACRES` the acreage **is** the take and
        `take_density_per_acre` is ignored entirely."

        PRD: "`reinitiation_trigger_units` is `authorized_take_units` multiplied by
        ninety percent, rounded half up to two decimal places"

        The `ACRES` species still carries a density of 0.40, so applying it would
        report 5.00 instead of 12.50; the `NESTS` species at 0.12 reports 1.50.

        Design: Corner/calculations/take_unit_decides_whether_density_is_applied
        """
        scenario = build_scenario(
            "action",
            include_unit=False,
            include_threatened=False,
            include_bank=False,
            species_overrides={"take_authorization_unit": "ACRES"},
        )
        plover = register_species(
            scientific_name="Charadrius nivosus",
            common_name="Western snowy plover",
            take_authorization_unit="NESTS",
            take_density_per_acre=0.12,
            recovery_unit_population=21000,
        )
        record_field_survey(
            scenario["action"],
            scenario["proponent"],
            scenario["species"]["id"],
            habitat_overlap_acres=12.50,
        )
        second_action = setup_second_action(scenario)
        record_field_survey(
            second_action, scenario["proponent"], plover["id"], habitat_overlap_acres=12.50
        )

        acres_action = run_effect_determination(scenario["action"], scenario["proponent"])
        nests_action = run_effect_determination(second_action, scenario["proponent"])
        submit_biological_assessment(acres_action["active_consultation_id"], scenario["proponent"])
        submit_biological_assessment(nests_action["active_consultation_id"], scenario["proponent"])
        acres_opinion = issue_biological_opinion(acres_action["active_consultation_id"])
        nests_opinion = issue_biological_opinion(nests_action["active_consultation_id"])

        assert acres_opinion["take_unit"] == "ACRES"
        assert acres_opinion["authorized_take_units"] == 12.50
        assert acres_opinion["jeopardy_fraction"] == 0.0031
        assert acres_opinion["conclusion"] == "NO_JEOPARDY"
        assert acres_opinion["reinitiation_trigger_units"] == 11.25
        assert nests_opinion["take_unit"] == "NESTS"
        assert nests_opinion["authorized_take_units"] == 1.50
        assert nests_opinion["jeopardy_fraction"] == 0.0001
        assert nests_opinion["reinitiation_trigger_units"] == 1.35
        assert acres_opinion["exposed_acres"] == 12.50
        assert nests_opinion["exposed_acres"] == 12.50


class TestReportDueDateAndLatenessBoundary:
    """Forty-five calendar days, a strict comparison, and adjacent periods."""

    def test_one_report_lands_on_its_due_date_and_the_next_period_abuts_it(self, api):
        """Two back-to-back periods split on lateness without colliding.

        PRD: "`due_at` is `period_end` advanced by 45 calendar days, and it is a
        date-only value. `is_late` is true when the UTC calendar date of
        `submitted_at` is **strictly later** than `due_at`, so a report filed on the
        due date itself is on time."

        PRD: "there is no buffer, and exact adjacency is explicitly allowed, so a
        period beginning precisely on another period's `period_end` coexists with it."

        The first period closes 2027-04-01 and is filed on its 2027-05-16 due date;
        the second opens exactly there, closes 2027-07-01 and is filed on 2027-08-16,
        one day past its 2027-08-15 due date. Two takes of 0.50 leave the permit at
        1.00 consumed, still short of its 3.60 trigger.

        Design: Corner/calculations/report_due_date_and_lateness_boundary
        """
        scenario = build_scenario("permit")
        permit_id = scenario["permit"]["id"]

        set_clock("2027-05-16T00:00:00Z")
        first = file_monitoring_report(
            permit_id,
            scenario["proponent"],
            period_start="2027-01-01",
            period_end="2027-04-01",
            take_units_reported=0.50,
            mitigation_units_verified=59.72,
        )
        set_clock("2027-08-16T00:00:00Z")
        second = file_monitoring_report(
            permit_id,
            scenario["proponent"],
            period_start="2027-04-01",
            period_end="2027-07-01",
            take_units_reported=0.50,
            mitigation_units_verified=59.72,
        )

        assert first["due_at"] == "2027-05-16"
        assert first["is_late"] is False
        assert second["due_at"] == "2027-08-15"
        assert second["is_late"] is True

        permit = read_permit(permit_id, scenario["proponent_headers"])

        assert permit["take_consumed_units"] == 1.00
        assert permit["take_remaining_units"] == 3.00
        assert permit["status"] == "ACTIVE"

        rows = assert_unpaginated_list(
            api_client.list_permit_monitoring_reports(permit_id, scenario["proponent_headers"])
        )

        assert [row["id"] for row in rows] == [first["id"], second["id"]]
        assert [row["status"] for row in rows] == ["SUBMITTED", "SUBMITTED"]


class TestComplianceDecayBoundary:
    """One hundred eighty whole days keeps the whole weight; day 181 halves it."""

    def test_the_halving_step_waits_for_the_one_hundred_eighty_first_day(self, api):
        """The same rejected report scores 89.00 one day and 94.50 the next.

        PRD: "A monitoring report that reached `REJECTED` contributes a weight of 11,
        dated at the report's `adjudicated_at`."

        PRD: "An event older than 180 whole days carries **half** its weight; an event
        exactly 180 whole days old carries its **full** weight, because the comparison
        is strictly greater than."

        PRD: "the same proponent row can return different values at two different
        clock positions with no intervening write of any kind"

        PRD: "the permit's `take_consumed_units` decreases by that report's
        `take_units_reported` and `take_remaining_units` is restored by the same
        amount"

        The rejection lands 2027-05-20, so 2027-11-16 is exactly 180 days later and
        both reads select the same windowed variant - only the decay step moves.

        Design: Corner/calculations/compliance_decay_halving_boundary_at_exactly_180_days
        """
        scenario = build_scenario("permit")
        proponent_id = scenario["proponent"]["id"]

        set_clock("2027-05-16T00:00:00Z")
        report = file_monitoring_report(
            scenario["permit"]["id"],
            scenario["proponent"],
            period_start="2027-01-01",
            period_end="2027-04-01",
            take_units_reported=0.50,
            mitigation_units_verified=59.72,
        )
        assert report["is_late"] is False
        set_clock("2027-05-20T00:00:00Z")
        adjudicate_report(
            report["id"], "REJECT", note="Survey effort insufficient for the reported period."
        )

        set_clock("2027-11-16T00:00:00Z")
        at_boundary = read_proponent(proponent_id)
        set_clock("2027-11-17T00:00:00Z")
        past_boundary = read_proponent(proponent_id)

        assert at_boundary["compliance_standing_score"] == 89.00
        assert at_boundary["compliance_variant_applied"] == "ROLLING_12_MONTH"
        assert past_boundary["compliance_standing_score"] == 94.50
        assert past_boundary["compliance_variant_applied"] == "ROLLING_12_MONTH"

        permit = read_permit(scenario["permit"]["id"], scenario["proponent_headers"])

        assert permit["take_consumed_units"] == 0.00
        assert permit["take_remaining_units"] == 4.00
        assert permit["status"] == "ACTIVE"


class TestChangedCircumstanceWaterfall:
    """The reserve is the first bucket and drains to exactly zero."""

    def test_a_seven_hundred_thousand_cent_cost_drains_the_reserve_then_bills_the_rest(
        self, api
    ):
        """A 538,555-cent reserve absorbs what it can and the permittee owes 161,445.

        PRD: "The first bucket is the plan's reserve: `reserve_draw_cents` is the
        **lesser** of `response_cost_cents` and the plan's `reserve_remaining_cents` as
        it stands at that moment."

        PRD: "Regardless of how the two buckets split, `permittee_borne_cents` is the
        **whole** `response_cost_cents`, `agency_borne_cents` is 0, and
        `assurances_invoked` is false - a changed circumstance is entirely the
        permittee's cost, the reserve being merely the permittee's own pre-funded
        money."

        PRD: "`contributed_cents` must be at least the event's
        `required_additional_cents`; anything less is
        `ERR_RESERVE_CONTRIBUTION_INSUFFICIENT` (HTTP 422)."

        PRD: "An accepted response moves the event `RESPONSE_REQUIRED - RESPONDED`,
        records `contributed_cents` and `response_note`, **adds** `contributed_cents`
        to the plan's `endowment_secured_cents`, and re-derives the plan's
        `funded_ratio` and `funding_status`"

        One cent short is refused; 161,445 closes the event, carries the endowment to
        5,187,959 against an unchanged requirement of 5,026,514, and pushes the
        reported ratio above one at 1.0321.

        Design: Corner/calculations/changed_circumstance_waterfall_drains_the_reserve_before_the_permittee
        """
        scenario = build_scenario("permit")
        plan_id = scenario["plan"]["id"]
        headers = scenario["proponent_headers"]

        event = report_circumstance(plan_id, scenario["proponent"], response_cost_cents=700_000)

        assert event["status"] == "RESPONSE_REQUIRED"
        assert event["reserve_draw_cents"] == 538_555
        assert event["required_additional_cents"] == 161_445
        assert event["permittee_borne_cents"] == 700_000
        assert event["agency_borne_cents"] == 0
        assert event["assurances_invoked"] is False
        assert_response_cost_identity(event)

        short = api_client.respond_to_circumstance_event(
            event["id"], circumstance_response_payload(161_444), headers
        )
        assert_error_envelope(short, ApiErrorId.ERR_RESERVE_CONTRIBUTION_INSUFFICIENT, 422)
        still_open = assert_unpaginated_list(
            api_client.list_plan_changed_circumstance_events(plan_id, headers)
        )

        assert [row["status"] for row in still_open] == ["RESPONSE_REQUIRED"]

        responded = respond_to_circumstance(event["id"], scenario["proponent"], 161_445)

        assert responded["status"] == "RESPONDED"
        assert responded["contributed_cents"] == 161_445

        plan = read_plan(plan_id, headers)

        assert plan["reserve_drawn_cents"] == 538_555
        assert plan["reserve_remaining_cents"] == 0
        assert plan["endowment_secured_cents"] == 5_187_959
        assert plan["endowment_required_cents"] == 5_026_514
        assert plan["funded_ratio"] == 1.0321
        assert plan["funding_status"] == "FULLY_ASSURED"


class TestCompliancePenaltyCategories:
    """Two penalty families sum on one read and one of them clears on response."""

    def test_a_reinitiation_and_an_open_circumstance_cost_twenty_seven_points(self, api):
        """18 plus 9 scores 73.00, and answering the circumstance restores 9.

        PRD: "Each of the proponent's consultations currently sitting in
        `REINITIATION_REQUIRED` contributes a weight of 18, dated at that
        consultation's `reinitiation_triggered_at`. Each changed-circumstance event on
        the proponent's plans currently sitting in `RESPONSE_REQUIRED` contributes a
        weight of 9, dated at that event's `reported_at`."

        PRD: "Reports that are `SUBMITTED` but not yet adjudicated contribute nothing,
        and an accepted report that was on time contributes nothing."

        PRD: "The unresponded-circumstance penalty that had been weighing on the
        proponent's compliance standing disappears from the next read of its
        `compliance_standing_score`."

        A 4.00-unit report at 2027-04-15 fires the take-exceedance cascade and a
        700,000-cent changed circumstance lands in `RESPONSE_REQUIRED` on the same
        day, so both events are nought days old and neither decays.

        Design: Corner/calculations/compliance_penalties_accumulate_across_categories_and_clear_on_response
        """
        scenario = setup_take_exceedance(
            report_clock="2027-04-15T00:00:00Z", take_units=4.00
        )
        proponent_id = scenario["proponent"]["id"]

        assert scenario["consultation"]["status"] == "REINITIATION_REQUIRED"
        assert scenario["report"]["status"] == "SUBMITTED"

        event = report_circumstance(
            scenario["plan"]["id"], scenario["proponent"], response_cost_cents=700_000
        )

        assert event["status"] == "RESPONSE_REQUIRED"
        assert event["required_additional_cents"] == 161_445

        before = read_proponent(proponent_id)

        assert before["compliance_standing_score"] == 73.00
        assert before["compliance_variant_applied"] == "ROLLING_12_MONTH"
        assert before["open_reinitiation_count"] == 1

        respond_to_circumstance(event["id"], scenario["proponent"], 161_445)
        after = read_proponent(proponent_id)

        assert after["compliance_standing_score"] == 82.00
        assert after["open_reinitiation_count"] == 1


class TestPermitOrdinalAndTermClamp:
    """The ordinal counts the whole permit table and the term clamps 29 February."""

    def test_a_second_plan_takes_the_global_ordinal_and_the_leap_day_clamps(self, api):
        """The proponent's second permit is ITP-000002 and its term ends 2029-02-28.

        PRD: "`permit_number` is the literal prefix `ITP-` followed by a six-digit
        zero-padded ordinal equal to one more than the number of incidental take
        permits created before this one, counting the whole global permit table
        ordered by `created_at` ascending - never by `id`."

        PRD: "`term_end` is `term_start` with its year advanced by the plan's
        `permit_term_years`, keeping the same month and day; when the resulting month
        and day do not exist - a term starting on 29 February whose target year is not
        a leap year - it clamps to 28 February of that year, and the clamp is
        normative rather than incidental."

        PRD: "`take_consumed_units` starts at 0.00, `take_remaining_units` starts equal
        to `authorized_take_units`, and `suspension_count` starts at 0."

        A second 200.00-acre action carrying 15.00 overlapping acres reaches an opinion
        for 6.00 individuals, and its plan endows 3,787,560 cents on one 45.00-unit
        bank commitment. The first permit keeps its own number and its own 4.00-unit
        ledger, and the bank has now transferred 104.72 credits across the two plans.

        Design: Corner/calculations/permit_ordinal_counts_globally_and_the_term_clamps_the_leap_day
        """
        scenario = build_scenario("permit")
        headers = scenario["proponent_headers"]

        second_action = setup_second_action(scenario)
        record_field_survey(
            second_action,
            scenario["proponent"],
            scenario["species"]["id"],
            habitat_overlap_acres=15.00,
        )
        second_action = run_effect_determination(second_action, scenario["proponent"])
        second_consultation_id = second_action["active_consultation_id"]
        submit_biological_assessment(second_consultation_id, scenario["proponent"])
        second_opinion = issue_biological_opinion(second_consultation_id)

        assert second_opinion["authorized_take_units"] == 6.00

        second_plan = get_success_data(
            api_client.create_habitat_conservation_plan(
                second_action["id"],
                habitat_conservation_plan_payload(
                    plan_name="Sunrise Park Phase II HCP", permit_term_years=1
                ),
                headers,
            ),
            201,
        )
        add_commitment(
            second_plan["id"],
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": 45.00,
                "conservation_bank_id": scenario["bank"]["id"],
            },
        )
        second_plan = read_plan(second_plan["id"], headers)

        assert second_plan["endowment_required_cents"] == 3_787_560

        fully_fund_plan(second_plan["id"], scenario["proponent"])
        second_plan = submit_plan(second_plan["id"], scenario["proponent"])

        assert second_plan["final_mitigation_units"] == 45.00

        decide_plan(second_plan["id"], "APPROVE")

        second_permit = issue_permit(
            second_plan["id"],
            term_start="2028-02-29",
            implementing_agreement_reference="IA-2028-0002",
        )

        assert second_permit["permit_number"] == "ITP-000002"
        assert second_permit["term_end"] == "2029-02-28"
        assert second_permit["authorized_take_units"] == 6.00
        assert second_permit["take_unit"] == "INDIVIDUALS"
        assert second_permit["reinitiation_trigger_units"] == 5.40
        assert second_permit["take_consumed_units"] == 0.00
        assert second_permit["take_remaining_units"] == 6.00
        assert second_permit["suspension_count"] == 0

        first_permit = read_permit(scenario["permit"]["id"], headers)

        assert first_permit["permit_number"] == "ITP-000001"
        assert first_permit["authorized_take_units"] == 4.00

        bank = read_bank(scenario["bank"]["id"])

        assert bank["credits_transferred"] == 104.72
        assert bank["credits_available"] == 395.28
        assert_bank_ledger_identity(bank)
