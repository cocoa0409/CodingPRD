"""The three declared boundary-precision checks, each pinned on its own edge."""

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_error_envelope, assert_unpaginated_list
from test_helpers.fixtures import (
    add_funding_assurance,
    read_action,
    read_plan,
    record_field_survey,
    run_effect_determination,
    setup_action_with_absent_determinations,
    setup_opinion_for_population,
    setup_plan_with_permittee_responsible_commitment,
    setup_second_action,
)


class TestJeopardyFractionFourDecimalThreshold:
    """The jeopardy screen is decided on the rounded four-decimal fraction."""

    def test_a_fraction_rounding_to_0_0494_is_no_jeopardy(self, api):
        """A population of 81 lands just below the inclusive threshold.

        PRD: "`jeopardy_fraction` is `authorized_take_units` divided by the primary
        species' `recovery_unit_population`, rounded half up to four decimal places."
        PRD: "Below the threshold, `rpa_required` is false and `conclusion` is
        `NO_JEOPARDY`."

        Design: Difficulty/boundary_precision_check/jeopardy_fraction_four_decimal_threshold_boundary
        """
        scenario = setup_opinion_for_population(81)
        opinion = scenario["opinion"]

        assert opinion["authorized_take_units"] == 4.00
        assert opinion["jeopardy_fraction"] == 0.0494
        assert opinion["conclusion"] == "NO_JEOPARDY"
        assert opinion["rpa_required"] is False
        assert opinion["reinitiation_trigger_units"] == 3.60

    def test_a_fraction_of_exactly_0_0500_is_jeopardy(self, api):
        """A population of 80 puts the fraction exactly on the threshold.

        PRD: "When that rounded fraction is at or above 0.0500 - five hundredths, the
        threshold being inclusive, so a fraction rounding to exactly 0.0500 **is** a
        jeopardy result - `rpa_required` is set to true, and `conclusion` becomes
        `JEOPARDY_WITH_RPA` when an `rpa_description` was supplied and `JEOPARDY` when
        none was."
        PRD: "All three conclusions are persistable; issuance never fails on the
        jeopardy screen."

        Design: Difficulty/boundary_precision_check/jeopardy_fraction_four_decimal_threshold_boundary
        """
        scenario = setup_opinion_for_population(80)
        opinion = scenario["opinion"]

        assert opinion["authorized_take_units"] == 4.00
        assert opinion["jeopardy_fraction"] == 0.0500
        assert opinion["conclusion"] == "JEOPARDY"
        assert opinion["rpa_required"] is True
        assert opinion["rpa_description"] is None
        assert opinion["reinitiation_trigger_units"] == 3.60
        assert read_action(scenario["action"]["id"])["status"] == "CONSULTATION_CONCLUDED"

    def test_a_fraction_well_below_the_threshold_is_no_jeopardy(self, api):
        """A population of 100 divides the same take to a clean 0.0400.

        PRD: "Below the threshold, `rpa_required` is false and `conclusion` is
        `NO_JEOPARDY`."
        PRD: "Finally, `reinitiation_trigger_units` is `authorized_take_units`
        multiplied by ninety percent, rounded half up to two decimal places"

        Design: Difficulty/boundary_precision_check/jeopardy_fraction_four_decimal_threshold_boundary
        """
        scenario = setup_opinion_for_population(100)
        opinion = scenario["opinion"]

        assert opinion["authorized_take_units"] == 4.00
        assert opinion["jeopardy_fraction"] == 0.0400
        assert opinion["conclusion"] == "NO_JEOPARDY"
        assert opinion["rpa_required"] is False
        assert opinion["reinitiation_trigger_units"] == 3.60


class TestFundingHalfBoundaryOnIntegerCents:
    """The funding status is decided on cents while the ratio only reports."""

    def test_one_cent_short_of_half_is_unfunded_while_the_ratio_reads_0_5000(self, api):
        """701,399 of 1,402,800 cents displays 0.5000 and still says UNFUNDED.

        PRD: "The funding decision is made on **exact integer cents**."
        PRD: "One cent short of exactly half is `UNFUNDED` even though `funded_ratio`
        still displays 0.5000."

        Design: Difficulty/boundary_precision_check/funding_half_boundary_decided_on_integer_cents_not_on_ratio
        """
        scenario = setup_plan_with_permittee_responsible_commitment(10.00)
        commitment = scenario["commitments"][0]
        plan = scenario["plan"]

        assert commitment["base_fee_cents"] == 2_100_000
        assert commitment["endowment_contribution_cents"] == 1_252_500
        assert plan["endowment_base_cents"] == 1_252_500
        assert plan["endowment_required_cents"] == 1_402_800

        add_funding_assurance(plan["id"], scenario["proponent"], 701_399)
        plan = read_plan(plan["id"])

        assert plan["endowment_secured_cents"] == 701_399
        assert plan["funded_ratio"] == 0.5000
        assert plan["funding_status"] == "UNFUNDED"
        assert plan["plan_status"] == "DRAFT"

    def test_exactly_half_is_partially_assured_at_the_same_displayed_ratio(self, api):
        """The next cent flips the status without moving the reported ratio.

        PRD: "`funding_status` becomes `FULLY_ASSURED` when `endowment_secured_cents` is
        at least `endowment_required_cents`; otherwise it becomes `PARTIALLY_ASSURED`
        when twice `endowment_secured_cents` is at least `endowment_required_cents`;
        otherwise it stays `UNFUNDED`."

        Design: Difficulty/boundary_precision_check/funding_half_boundary_decided_on_integer_cents_not_on_ratio
        """
        scenario = setup_plan_with_permittee_responsible_commitment(10.00)
        plan = scenario["plan"]
        proponent = scenario["proponent"]

        add_funding_assurance(plan["id"], proponent, 701_399)
        add_funding_assurance(plan["id"], proponent, 1)
        plan = read_plan(plan["id"])

        assert plan["endowment_secured_cents"] == 701_400
        assert plan["funded_ratio"] == 0.5000
        assert plan["funding_status"] == "PARTIALLY_ASSURED"
        assert plan["plan_status"] == "DRAFT"

    def test_reaching_the_requirement_exactly_is_fully_assured(self, api):
        """Secured equal to required is inclusive on the FULLY_ASSURED side.

        PRD: "Each accepted contribution **adds** `contribution_cents` to
        `endowment_secured_cents`, which is the running sum of every accepted
        funding-assurance contribution plus every changed-circumstance response
        contribution, and then re-derives the funding dimension."
        PRD: "A single sufficient contribution can therefore carry the plan `UNFUNDED -
        FULLY_ASSURED` in one hop, or `UNFUNDED - PARTIALLY_ASSURED` and later
        `PARTIALLY_ASSURED - FULLY_ASSURED`."

        Design: Difficulty/boundary_precision_check/funding_half_boundary_decided_on_integer_cents_not_on_ratio
        """
        scenario = setup_plan_with_permittee_responsible_commitment(10.00)
        plan = scenario["plan"]
        proponent = scenario["proponent"]

        add_funding_assurance(plan["id"], proponent, 701_400)
        add_funding_assurance(plan["id"], proponent, 701_400)
        plan = read_plan(plan["id"])

        assert plan["endowment_secured_cents"] == 1_402_800
        assert plan["funded_ratio"] == 1.0000
        assert plan["funding_status"] == "FULLY_ASSURED"
        assert plan["plan_status"] == "DRAFT"

    def test_over_funding_is_accepted_and_changes_nothing(self, api):
        """A contribution beyond the requirement neither errors nor moves the status.

        PRD: "`funding_status` becomes `FULLY_ASSURED` when `endowment_secured_cents` is
        at least `endowment_required_cents`"
        PRD: "Otherwise `funded_ratio` is `endowment_secured_cents` divided by
        `endowment_required_cents`, rounded half up to four decimal places, and it is
        **reporting only**."

        Design: Difficulty/boundary_precision_check/funding_half_boundary_decided_on_integer_cents_not_on_ratio
        """
        scenario = setup_plan_with_permittee_responsible_commitment(10.00)
        plan = scenario["plan"]
        proponent = scenario["proponent"]

        add_funding_assurance(plan["id"], proponent, 1_402_800)
        add_funding_assurance(plan["id"], proponent, 1)
        plan = read_plan(plan["id"])

        assert plan["endowment_secured_cents"] == 1_402_801
        assert plan["endowment_required_cents"] == 1_402_800
        assert plan["funded_ratio"] == 1.0000
        assert plan["funding_status"] == "FULLY_ASSURED"
        assert plan["plan_status"] == "DRAFT"


class TestEmptyCandidateSetIsNoEffect:
    """Zero candidates is a clean determination; zero rows is an error."""

    def test_absent_rows_are_derived_and_then_excluded(self, api):
        """A negative in-season survey is ABSENT and a negative query PRESUMED_ABSENT.

        PRD: "`NOT_DETECTED` yields `ABSENT` only when `survey_in_season` is true; when
        the survey was conducted outside the species' detectability season,
        `NOT_DETECTED` yields `PRESUMED_PRESENT` instead, because failing to find an
        animal when it cannot be detected is not evidence that it is not there."
        PRD: "A `DATABASE_QUERY` can never produce a confirmed status: `DETECTED` yields
        `PRESUMED_PRESENT`, `NOT_DETECTED` yields `PRESUMED_ABSENT`, and `INCONCLUSIVE`
        yields `PRESUMED_PRESENT`."

        Design: Difficulty/boundary_precision_check/empty_candidate_set_is_no_effect_not_an_error
        """
        scenario = setup_action_with_absent_determinations()

        survey = scenario["absent_field_survey"]
        assert survey["presence_status"] == "ABSENT"
        assert survey["survey_in_season"] is True
        assert survey["habitat_overlap_acres"] == 12.50

        query = scenario["absent_query"]
        assert query["presence_status"] == "PRESUMED_ABSENT"
        assert query["survey_in_season"] is False
        assert query["habitat_overlap_acres"] == 7.25

    def test_an_all_absent_action_clears_at_zero_acres(self, api):
        """The 12.50 and 7.25 acres are not summed and no clock ever starts.

        PRD: "An action with determinations that are all absent has an **empty**
        candidate set, which is a legitimate outcome rather than an error:
        `total_overlap_acres` and `overlap_pct` are both written as 0.00 and the
        determination is `NO_EFFECT`."
        PRD: "On `NO_EFFECT`, the action moves `SCREENING - CLEARED_NO_EFFECT`,
        `effect_determination` is written as `NO_EFFECT`, `total_overlap_acres` and
        `overlap_pct` are written, and **no consultation row is created at all** -
        `active_consultation_id` stays null and no statutory clock ever starts."

        Design: Difficulty/boundary_precision_check/empty_candidate_set_is_no_effect_not_an_error
        """
        scenario = setup_action_with_absent_determinations()

        action = run_effect_determination(scenario["action"], scenario["proponent"])

        assert action["effect_determination"] == "NO_EFFECT"
        assert action["total_overlap_acres"] == 0.00
        assert action["overlap_pct"] == 0.00
        assert action["status"] == "CLEARED_NO_EFFECT"
        assert action["active_consultation_id"] is None

        consultations = assert_unpaginated_list(
            api.list_action_consultations(action["id"], scenario["proponent_headers"])
        )
        assert consultations == []

    def test_zero_rows_is_an_error_rather_than_a_clean_determination(self, api):
        """An action with no determinations at all cannot be analysed.

        PRD: "If the action has **zero** presence determinations of any kind, the
        analysis cannot proceed and the request is rejected with
        `ERR_NO_PRESENCE_DETERMINATIONS` (HTTP 422)."
        PRD: "The distinction between zero rows (an error) and zero candidates (a clean
        determination) is deliberate."

        Design: Difficulty/boundary_precision_check/empty_candidate_set_is_no_effect_not_an_error
        """
        scenario = setup_action_with_absent_determinations()
        bare_action = setup_second_action(scenario)

        response = api.run_effect_determination(
            bare_action["id"], scenario["proponent_headers"]
        )

        assert_error_envelope(
            response, ApiErrorId.ERR_NO_PRESENCE_DETERMINATIONS, 422
        )
        assert read_action(bare_action["id"])["status"] == "SCREENING"

    def test_an_out_of_season_negative_survey_stays_a_candidate(self, api):
        """The same NOT_DETECTED row outside the season counts against the action.

        PRD: "The analysis works from the action's **candidate set**: those presence
        determinations of this action whose `presence_status` is `PRESENT` or
        `PRESUMED_PRESENT`."
        PRD: "In every remaining case the determination is `LAA`."

        Design: Difficulty/boundary_precision_check/empty_candidate_set_is_no_effect_not_an_error
        """
        scenario = setup_action_with_absent_determinations()
        third_action = setup_second_action(scenario, action_name="Sunrise Park Phase III")

        determination = record_field_survey(
            third_action,
            scenario["proponent"],
            scenario["species"]["id"],
            detection_result="NOT_DETECTED",
            habitat_overlap_acres=12.50,
            survey_window_start="2026-01-10",
            survey_window_end="2026-01-14",
        )
        assert determination["survey_in_season"] is False
        assert determination["presence_status"] == "PRESUMED_PRESENT"

        action = run_effect_determination(third_action, scenario["proponent"])
        assert action["total_overlap_acres"] == 12.50
        assert action["overlap_pct"] == 6.25
        assert action["effect_determination"] == "LAA"
        assert action["status"] == "FORMAL_CONSULTATION"

    def test_the_cleared_action_refuses_a_second_analysis(self, api):
        """CLEARED_NO_EFFECT is terminal, so the analysis cannot be re-run.

        PRD: "This operation takes **no body fields at all** - every input it needs is
        already persisted - and it is available only while the action's `status` is
        `SCREENING`, so a second determination on the same action is
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
        PRD: "`CLEARED_NO_EFFECT` is terminal; nothing further happens to that action."

        Design: Difficulty/boundary_precision_check/empty_candidate_set_is_no_effect_not_an_error
        """
        scenario = setup_action_with_absent_determinations()
        action = run_effect_determination(scenario["action"], scenario["proponent"])
        assert action["status"] == "CLEARED_NO_EFFECT"

        response = api.run_effect_determination(
            action["id"], scenario["proponent_headers"]
        )

        assert_error_envelope(
            response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409
        )
        after = read_action(action["id"])
        assert after["status"] == "CLEARED_NO_EFFECT"
        assert after["active_consultation_id"] is None
