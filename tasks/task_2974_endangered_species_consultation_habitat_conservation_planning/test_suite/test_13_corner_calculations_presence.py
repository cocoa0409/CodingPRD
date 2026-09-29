"""Presence, seasonality, and the effect-determination ladder.

Every test translates one `calculations` instance of the corner design index:
the method-first presumption table, the seasonality branch on a negative field
survey, the wrap-aware season predicate, the two low-rank rungs of the effect
ladder, the candidate-set filter, and the rounding that precedes the threshold
comparison.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_error_envelope,
    assert_presence_determination,
    assert_unpaginated_list,
)
from test_helpers.factories import (
    database_query_payload,
    habitat_conservation_plan_payload,
)
from test_helpers.fixtures import (
    add_commitment,
    build_scenario,
    designate_critical_habitat_unit,
    issue_biological_opinion,
    read_bank,
    read_consultation,
    record_database_query,
    record_field_survey,
    register_threatened_species,
    run_effect_determination,
    setup_second_action,
    submit_biological_assessment,
    submit_plan,
)


class TestDatabaseQueryPresumptions:
    """A desk query can never produce a confirmed status."""

    def test_all_three_detection_results_map_to_presumptions(self, api):
        """DETECTED and INCONCLUSIVE collapse onto the same presumption.

        PRD: "A `DATABASE_QUERY` can never produce a confirmed status: `DETECTED`
        yields `PRESUMED_PRESENT`, `NOT_DETECTED` yields `PRESUMED_ABSENT`, and
        `INCONCLUSIVE` yields `PRESUMED_PRESENT`."

        PRD: "For a `DATABASE_QUERY` determination, `survey_in_season` is always
        false."

        PRD: "When `method` is `DATABASE_QUERY`, both must be omitted or supplied as
        null - a desk query has no field window."

        PRD: "Any violation of either half of that rule is
        `ERR_SURVEY_WINDOW_INVALID` (HTTP 422), whether the failure is a missing
        window on a survey, an inverted window on a survey, or a window supplied
        non-null alongside a database query."

        Design: Corner/calculations/database_query_maps_all_three_detection_results_to_presumptions
        """
        scenario = build_scenario(
            "action", include_unit=False, include_threatened=False, include_bank=False
        )
        species_id = scenario["species"]["id"]

        rows = [
            record_database_query(
                scenario["action"],
                scenario["proponent"],
                species_id,
                detection_result=result,
                habitat_overlap_acres=acres,
            )
            for result, acres in (
                ("DETECTED", 3.00),
                ("NOT_DETECTED", 4.00),
                ("INCONCLUSIVE", 5.00),
            )
        ]

        assert [row["presence_status"] for row in rows] == [
            "PRESUMED_PRESENT",
            "PRESUMED_ABSENT",
            "PRESUMED_PRESENT",
        ]
        for row in rows:
            assert_presence_determination(row)
            assert row["survey_in_season"] is False
            assert row["survey_window_start"] is None
            assert row["survey_window_end"] is None
        assert_error_envelope(
            api.create_presence_determination(
                scenario["action"]["id"],
                database_query_payload(species_id, survey_window_start="2026-05-04"),
                scenario["proponent_headers"],
            ),
            ApiErrorId.ERR_SURVEY_WINDOW_INVALID,
            422,
        )


class TestNegativeSurveySeasonality:
    """A negative field survey splits on the seasonality flag."""

    def test_an_out_of_season_negative_keeps_the_species_in_play(self, api):
        """The same negative observation lands in two different statuses.

        PRD: "The consequential branch is a negative field survey. `NOT_DETECTED`
        yields `ABSENT` only when `survey_in_season` is true; when the survey was
        conducted outside the species' detectability season, `NOT_DETECTED` yields
        `PRESUMED_PRESENT` instead, because failing to find an animal when it cannot
        be detected is not evidence that it is not there."

        PRD: "Rows in `PRESUMED_ABSENT` and rows in `ABSENT` are excluded, and they
        are excluded from both the acreage sum and the listing-rank maximum."

        PRD: "In every remaining case the determination is `LAA`."

        The species is detectable from April through July, so the May window is in
        season and drops out of the candidate set while the identical September
        survey keeps its 12.00 acres - 6.00 percent of the footprint - in play.

        Design: Corner/calculations/negative_field_survey_out_of_season_is_not_evidence_of_absence
        """
        scenario = build_scenario(
            "action", include_unit=False, include_threatened=False, include_bank=False
        )

        in_season = record_field_survey(
            scenario["action"],
            scenario["proponent"],
            scenario["species"]["id"],
            detection_result="NOT_DETECTED",
            habitat_overlap_acres=12.00,
            survey_window_start="2026-05-04",
            survey_window_end="2026-05-08",
        )
        off_season = record_field_survey(
            scenario["action"],
            scenario["proponent"],
            scenario["species"]["id"],
            detection_result="NOT_DETECTED",
            habitat_overlap_acres=12.00,
            survey_window_start="2026-09-04",
            survey_window_end="2026-09-08",
        )

        assert in_season["survey_in_season"] is True
        assert in_season["presence_status"] == "ABSENT"
        assert off_season["survey_in_season"] is False
        assert off_season["presence_status"] == "PRESUMED_PRESENT"
        action = run_effect_determination(scenario["action"], scenario["proponent"])
        assert action["total_overlap_acres"] == 12.00
        assert action["overlap_pct"] == 6.00
        assert action["effect_determination"] == "LAA"


class TestWrapAroundSeason:
    """A November-to-February season contains January and excludes June."""

    def test_the_season_predicate_switches_when_the_season_wraps(self, api):
        """Both window endpoints must sit inside the wrapped season.

        PRD: "The season test is wrap-aware: when `survey_season_start_month` is less
        than or equal to `survey_season_end_month`, a month is in season when it is at
        or after the start month and at or before the end month; when the start month
        is greater than the end month, the season wraps the year boundary and a month
        is in season when it is at or after the start month **or** at or before the
        end month."

        PRD: "it is true only when **both** months fall inside that season"

        PRD: "The start month may be **greater** than the end month, and that is not
        an error - it expresses a season that wraps the year boundary, such as a
        season running from November through February."

        PRD: "A `FIELD_SURVEY` can: `DETECTED` yields `PRESENT`"

        Design: Corner/calculations/wrap_around_detectability_season_membership
        """
        scenario = build_scenario(
            "action", include_unit=False, include_threatened=False, include_bank=False
        )
        plover = register_threatened_species(
            survey_season_start_month=11, survey_season_end_month=2
        )

        january = record_field_survey(
            scenario["action"],
            scenario["proponent"],
            plover["id"],
            detection_result="NOT_DETECTED",
            habitat_overlap_acres=6.00,
            survey_window_start="2027-01-10",
            survey_window_end="2027-01-14",
        )
        june = record_field_survey(
            scenario["action"],
            scenario["proponent"],
            plover["id"],
            detection_result="NOT_DETECTED",
            habitat_overlap_acres=6.00,
            survey_window_start="2026-06-10",
            survey_window_end="2026-06-14",
        )
        straddling = record_field_survey(
            scenario["action"],
            scenario["proponent"],
            plover["id"],
            detection_result="NOT_DETECTED",
            habitat_overlap_acres=6.00,
            survey_window_start="2026-10-30",
            survey_window_end="2026-11-02",
        )

        assert january["survey_in_season"] is True
        assert january["presence_status"] == "ABSENT"
        assert june["survey_in_season"] is False
        assert june["presence_status"] == "PRESUMED_PRESENT"
        assert straddling["survey_in_season"] is False
        assert straddling["presence_status"] == "PRESUMED_PRESENT"
        detected = record_field_survey(
            scenario["action"],
            scenario["proponent"],
            plover["id"],
            detection_result="DETECTED",
            habitat_overlap_acres=6.00,
            survey_window_start="2026-06-20",
            survey_window_end="2026-06-24",
        )
        assert detected["survey_in_season"] is False
        assert detected["presence_status"] == "PRESENT"


class TestLowRankLadderRungs:
    """The first two rungs of the ladder are decided by the rank alone."""

    def test_a_candidate_only_set_stops_at_nlaa_and_clears_only_at_zero(self, api):
        """Rank 0 can never reach LAA, however large the overlap.

        PRD: "If the maximum listing rank is at most 1 - that is, the most serious
        species in the candidate set is only `PROPOSED` or `CANDIDATE` - and
        `overlap_pct` is at most 0.00, the determination is `NO_EFFECT`. Otherwise, if
        the maximum listing rank is at most 1, the determination is `NLAA`."

        PRD: "`CANDIDATE` is rank 0, `PROPOSED` is rank 1, `THREATENED` is rank 2, and
        `ENDANGERED` is rank 3."

        PRD: "exactly one consultation is created with `consultation_type` `INFORMAL`,
        `status` `DRAFT_BA`, `clock_started_at` at the current logical clock,
        `statutory_days` of 60"

        The 4.00-acre candidate row gives 2.00 percent and stops at NLAA, while the
        0.00-acre row on a non-empty candidate set clears the action outright - the
        two thresholds are 5.00 and 0.00 and they are not the same number.

        Design: Corner/calculations/low_listing_rank_candidates_stop_at_nlaa
        """
        scenario = build_scenario(
            "action",
            species_overrides={"listing_status": "CANDIDATE"},
            include_unit=False,
            include_threatened=False,
            include_bank=False,
        )
        action_two = setup_second_action(scenario)
        record_database_query(
            scenario["action"],
            scenario["proponent"],
            scenario["species"]["id"],
            habitat_overlap_acres=4.00,
        )
        record_database_query(
            action_two,
            scenario["proponent"],
            scenario["species"]["id"],
            habitat_overlap_acres=0.00,
        )

        first = run_effect_determination(scenario["action"], scenario["proponent"])
        second = run_effect_determination(action_two, scenario["proponent"])

        assert first["effect_determination"] == "NLAA"
        assert first["overlap_pct"] == 2.00
        assert first["total_overlap_acres"] == 4.00
        assert first["status"] == "INFORMAL_CONSULTATION"
        consultation = read_consultation(first["active_consultation_id"])
        assert consultation["consultation_type"] == "INFORMAL"
        assert consultation["statutory_days"] == 60
        assert second["effect_determination"] == "NO_EFFECT"
        assert second["overlap_pct"] == 0.00
        assert second["status"] == "CLEARED_NO_EFFECT"
        assert (
            assert_unpaginated_list(
                api.list_action_consultations(
                    action_two["id"], scenario["proponent_headers"]
                )
            )
            == []
        )
        assert (
            len(
                assert_unpaginated_list(
                    api.list_action_consultations(
                        scenario["action"]["id"], scenario["proponent_headers"]
                    )
                )
            )
            == 1
        )


class TestCandidateSetFiltering:
    """The excluded row is the largest and the highest ranked one."""

    def test_an_absent_row_leaves_the_sum_and_the_rank_max_untouched(self, api):
        """A hundred absent acres of an endangered species drop out entirely.

        PRD: "The analysis works from the action's **candidate set**: those presence
        determinations of this action whose `presence_status` is `PRESENT` or
        `PRESUMED_PRESENT`."

        PRD: "`overlap_pct` is that total divided by the action's `footprint_acres`,
        multiplied by 100, and rounded half up to two decimal places."

        PRD: "Otherwise, if `overlap_pct` is at most 5.00 and there is no confirmed
        presence, the determination is `NLAA`."

        Only the 7.35 threatened acres survive the filter, so the total is 7.35 rather
        than 107.35 and 3.675 percent rounds to 3.68.

        Design: Corner/calculations/absent_rows_are_excluded_from_the_overlap_sum_and_the_rank_max
        """
        scenario = build_scenario("action", include_unit=False, include_bank=False)
        absent = record_field_survey(
            scenario["action"],
            scenario["proponent"],
            scenario["species"]["id"],
            detection_result="NOT_DETECTED",
            habitat_overlap_acres=100.00,
        )
        presumed = record_database_query(
            scenario["action"],
            scenario["proponent"],
            scenario["threatened_species"]["id"],
            habitat_overlap_acres=7.35,
        )
        assert absent["presence_status"] == "ABSENT"
        assert presumed["presence_status"] == "PRESUMED_PRESENT"

        action = run_effect_determination(scenario["action"], scenario["proponent"])

        assert action["total_overlap_acres"] == 7.35
        assert action["overlap_pct"] == 3.68
        assert action["effect_determination"] == "NLAA"
        assert action["status"] == "INFORMAL_CONSULTATION"
        consultation = read_consultation(action["active_consultation_id"])
        assert consultation["consultation_type"] == "INFORMAL"
        assert consultation["statutory_days"] == 60


class TestOverlapRoundingBeforeComparison:
    """One hundredth of an acre changes the consultation type.

    The threshold is applied to the rounded percentage, never to the quotient.
    """

    def test_the_threshold_reads_the_rounded_percentage(self, api):
        """10.01 acres is LAA where 10.00 acres is NLAA.

        PRD: "All threshold comparisons are made against the **rounded** two-decimal
        `overlap_pct`, never against the raw quotient, and the boundary is inclusive
        on the less-severe side: an `overlap_pct` of exactly 5.00 is `NLAA`, while
        5.01 is `LAA`."

        PRD: "exactly one consultation is created with `consultation_type` `FORMAL`,
        `status` `DRAFT_BA`, `clock_started_at` at the current logical clock,
        `statutory_days` of 135"

        Design: Corner/calculations/overlap_percentage_is_rounded_before_the_threshold_comparison
        """
        scenario = build_scenario(
            "action",
            species_overrides={"listing_status": "THREATENED"},
            include_unit=False,
            include_threatened=False,
            include_bank=False,
        )
        action_two = setup_second_action(scenario)
        record_field_survey(
            scenario["action"],
            scenario["proponent"],
            scenario["species"]["id"],
            habitat_overlap_acres=10.01,
        )
        record_field_survey(
            action_two,
            scenario["proponent"],
            scenario["species"]["id"],
            habitat_overlap_acres=10.00,
        )

        first = run_effect_determination(scenario["action"], scenario["proponent"])
        second = run_effect_determination(action_two, scenario["proponent"])

        assert first["overlap_pct"] == 5.01
        assert first["effect_determination"] == "LAA"
        assert first["status"] == "FORMAL_CONSULTATION"
        assert read_consultation(first["active_consultation_id"])["statutory_days"] == 135
        assert second["overlap_pct"] == 5.00
        assert second["effect_determination"] == "NLAA"
        assert second["status"] == "INFORMAL_CONSULTATION"
        assert read_consultation(second["active_consultation_id"])["statutory_days"] == 60


class TestCriticalHabitatUplift:
    """The 1.5 uplift is gated on the designation status, not on citing a unit."""

    def test_only_a_final_designation_earns_the_uplift(self, api):
        """Two identical acreages contribute 45.00 and 30.00 units.

        PRD: "Each row also carries a **critical-habitat uplift** of 1.5 when the row
        cites a `critical_habitat_unit_id` whose unit has `designation_status` `FINAL`,
        and an uplift of 1.0 in every other case - including a row citing a merely
        `PROPOSED` unit and a row citing no unit at all."

        PRD: "for each candidate row it multiplies that row's own
        `habitat_overlap_acres` by that row's own listing ratio and by that row's own
        uplift, **rounds that product half up to two decimal places**, and only then
        sums the rounded per-row figures."

        PRD: "It ignores the critical-habitat uplift entirely and it ignores each row's
        own acreage, which is what makes it computable from the plan alone."

        PRD: "Submission recomputes `final_mitigation_units` with the FINAL variant,
        writes `mitigation_delta_units`, and recomputes `secured_mitigation_units` as
        the sum of `units` over the plan's `RESERVED` and `SECURED` commitments,
        rounded half up to two decimal places."

        The FINAL-unit row raises 10.00 x 3.0 x 1.5 = 45.00 and the PROPOSED-unit row
        10.00 x 3.0 x 1.0 = 30.00, so the final requirement is 75.00 against a
        preliminary 60.00 - a delta of 15.00 rather than the 30.00 an ungated uplift
        would report.

        Design: Corner/calculations/critical_habitat_uplift_applies_only_to_final_designations
        """
        scenario = build_scenario(
            "action", include_threatened=False, include_bank=False
        )
        proposed_unit = designate_critical_habitat_unit(
            scenario["species"]["id"], unit_code="CHU-2", designation_status="PROPOSED"
        )
        record_field_survey(
            scenario["action"],
            scenario["proponent"],
            scenario["species"]["id"],
            critical_habitat_unit_id=scenario["unit"]["id"],
        )
        record_field_survey(
            scenario["action"],
            scenario["proponent"],
            scenario["species"]["id"],
            critical_habitat_unit_id=proposed_unit["id"],
        )
        action = run_effect_determination(scenario["action"], scenario["proponent"])
        assert action["total_overlap_acres"] == 20.00
        assert action["overlap_pct"] == 10.00
        assert action["effect_determination"] == "LAA"
        submit_biological_assessment(
            action["active_consultation_id"], scenario["proponent"]
        )
        issue_biological_opinion(action["active_consultation_id"])
        plan = get_success_data(
            api.create_habitat_conservation_plan(
                action["id"],
                habitat_conservation_plan_payload(),
                scenario["proponent_headers"],
            ),
            201,
        )
        assert plan["preliminary_mitigation_units"] == 60.00
        add_commitment(
            plan["id"],
            scenario["proponent"],
            {"mechanism": "PERMITTEE_RESPONSIBLE", "units": 75.00},
        )

        submitted = submit_plan(plan["id"], scenario["proponent"])

        assert submitted["final_mitigation_units"] == 75.00
        assert submitted["mitigation_delta_units"] == 15.00
        assert submitted["preliminary_mitigation_units"] == 60.00
        assert submitted["secured_mitigation_units"] == 75.00
        assert submitted["plan_status"] == "SUBMITTED"


class TestInLieuFeeTierBoundary:
    """The strict tier bound makes the total non-monotonic in the units.

    Buying one hundredth of a unit more mitigation costs 172,918 cents less.
    """

    def test_one_hundredth_of_a_unit_crosses_the_tier_and_lowers_the_total(self, api):
        """The tier is selected with a strict comparison on the rounded base.

        PRD: "An `IN_LIEU_FEE` commitment multiplies its `units` by the standard
        in-lieu base rate of 182,500 cents per unit"

        PRD: "For an in-lieu-fee commitment, `admin_fee_pct_applied` is 0.150 when
        `base_fee_cents` is below 5,000,000 cents (fifty thousand dollars), 0.115 when
        `base_fee_cents` is below 20,000,000 cents (two hundred thousand dollars) but
        not below the first bound, and 0.080 otherwise. Both upper bounds are
        **strict**, so a `base_fee_cents` of exactly 5,000,000 falls in the middle
        band"

        PRD: "Step three computes `admin_fee_cents` as `base_fee_cents` multiplied by
        `admin_fee_pct_applied`, rounded half up to whole cents - computed from the
        **rounded** base, not from the raw product of step one."

        PRD: "Step four sets `total_cost_cents` to `base_fee_cents` plus
        `admin_fee_cents`, and the tier is not revisited."

        27.39 units price at 4,998,675 and pay 749,801 of the 749,801.25 due, for
        5,748,476; 27.40 units price at 5,000,500 and pay 575,058 of the 575,057.5
        due, for 5,575,558.

        Design: Corner/calculations/in_lieu_fee_tier_boundary_makes_the_total_non_monotonic
        """
        scenario = build_scenario("plan")

        first = add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {"mechanism": "IN_LIEU_FEE", "units": 27.39},
        )
        second = add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {"mechanism": "IN_LIEU_FEE", "units": 27.40},
        )

        assert first["base_fee_cents"] == 4_998_675
        assert first["admin_fee_pct_applied"] == 0.150
        assert first["admin_fee_cents"] == 749_801
        assert first["total_cost_cents"] == 5_748_476
        assert second["base_fee_cents"] == 5_000_500
        assert second["admin_fee_pct_applied"] == 0.115
        assert second["admin_fee_cents"] == 575_058
        assert second["total_cost_cents"] == 5_575_558
        assert second["total_cost_cents"] < first["total_cost_cents"]
        assert first.get("conservation_bank_id") is None
        assert second.get("conservation_bank_id") is None
        assert read_bank(scenario["bank"]["id"])["credits_reserved"] == 0.00
