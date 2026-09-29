"""Derived fields are correct in the response of the write that changed them.

Nothing in this system is eventually consistent: a write that moves an input
rebuilds every figure that depends on it before it answers, so the body it
returns — and the very next read of any entity the cascade touched — already
carries the new values.
"""

from test_helpers import (
    STOP_STATE_APPROVED,
    assert_cohort_figures,
    assert_credit_hours,
    assert_pct,
    f,
    get_success_data,
    k,
    validate_unpaginated,
)

POSTED_ON = "2026-07-15"


def _agreed_indicator_with_one_participant(build):
    """A state-approved program, one enrolled participant, one agreed indicator.

    The student is enrolled before the indicator is opened and holds no credit,
    so the indicator opens with an empty countable cohort.
    """
    scenario = build.program(
        "15.0000",
        stop_at=STOP_STATE_APPROVED,
        cluster=k.CLUSTER_ADVANCED_MANUFACTURING,
    )
    student = build.enroll(scenario.program_id, "100000001", cohort_year=2026)
    accepted = build.agreed_indicator(
        scenario.program_id,
        k.INDICATOR_4S1_CREDENTIAL,
        40.0,
        reporting_year=2027,
        baseline_pct=40.0,
        cohort_year=2026,
    )
    return scenario, student, accepted


def _post_two_credits(api, student_id, course_id, registrar_headers):
    """Post the two credit hours that carry the student over the threshold."""
    return get_success_data(
        api.post_credit(
            student_id,
            f.credit_posting_payload(course_id, 2.0, POSTED_ON),
            registrar_headers,
        )
    )


def _read_indicator(api, indicator_id, reviewer_headers):
    return validate_unpaginated(api.get_indicator(indicator_id, reviewer_headers), 200)


class TestDerivedFieldsInTheWriteResponse:
    """Every figure a write rebuilds is already published by that write."""

    def test_acceptance_returns_the_negotiated_level_and_its_derived_threshold(
        self, build
    ):
        """PRD §3.8: "Acceptance copies `last_offer_pct` into `negotiated_level_pct` and sets `met_threshold_pct` to that level multiplied by the federal tolerance of 0.90, rounded half-up to two decimal places. In other words, a district hits its target if it achieves at least ninety percent of the level it agreed to." PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/every_derived_field_is_already_correct_in_the_writes_own_response_body
        """
        _scenario, _student, accepted = _agreed_indicator_with_one_participant(build)

        assert accepted["status"] == k.PI_AGREED
        assert_pct(accepted["negotiated_level_pct"], 40.00, "negotiated_level_pct")
        assert_pct(accepted["met_threshold_pct"], 36.00, "met_threshold_pct")

    def test_acceptance_returns_the_cohort_figures_of_an_empty_denominator(self, build):
        """PRD §3.8: "`denominator_count` is the number of students whose program matches the indicator's program, whose `cohort_year` matches the indicator's `cohort_year`, and whose `concentrator_status` is `CONCENTRATOR` or `COMPLETER`; a `PARTICIPANT` counts in neither the numerator nor the denominator." "`small_cohort_flag` is true exactly when `denominator_count` is below the federal minimum cohort size of 5. The raw percentage is null when `denominator_count` is zero" "it publishes the raw percentage as `preliminary_actual_pct` and sets `preliminary_status_projection` to `MET` when the raw percentage is at least `met_threshold_pct`, to `NOT_MET` when it is strictly below, and to `UNDEFINED` whenever either the raw percentage or `met_threshold_pct` is null."

        Design: Corner/consistency_model/every_derived_field_is_already_correct_in_the_writes_own_response_body
        """
        _scenario, _student, accepted = _agreed_indicator_with_one_participant(build)

        assert_cohort_figures(accepted, 0, 0, True)
        assert accepted["preliminary_actual_pct"] is None
        assert accepted["preliminary_status_projection"] == k.PROJECTION_UNDEFINED

    def test_the_credit_posting_returns_the_rebuilt_student_classification(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "First, `cte_credits_earned` is rebuilt as the sum of `credit_delta` across every accepted posting for that student whose target course was in `status` `ACTIVE` at the time of posting, rounded half-up to two decimal places. Second, `verified_qualifying_attainment_count` is rebuilt as the number of that student's attainment records whose `counted_for_indicator` is true. Third, `concentrator_status` is decided by a three-way ladder evaluated top to bottom: the student is a `COMPLETER` when `cte_credits_earned` is at least 2.0 credit hours **and** `exited_on` is non-null **and** `verified_qualifying_attainment_count` is at least 1; failing that, the student is a `CONCENTRATOR` when `cte_credits_earned` alone is at least 2.0 credit hours; failing that, the student is a `PARTICIPANT`." "The credit comparison is inclusive — a balance of exactly 2.0 classifies as at least `CONCENTRATOR`, while 1.99 does not"

        Design: Corner/consistency_model/every_derived_field_is_already_correct_in_the_writes_own_response_body
        """
        scenario, student, _accepted = _agreed_indicator_with_one_participant(build)

        posted = _post_two_credits(
            api, student["id"], scenario.secondary_course_id, registrar_headers
        )
        assert_credit_hours(posted["cte_credits_earned"], 2.00, "cte_credits_earned")
        assert posted["concentrator_status"] == k.CONCENTRATOR_CONCENTRATOR
        assert posted["verified_qualifying_attainment_count"] == 0
        assert posted["exited_on"] is None

    def test_reading_the_student_back_repeats_the_posting_response(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "**Concentrator classification** is recomputed whenever a credit posting, an exit or an attainment lands on a student, and it writes three fields." PRD §1: "**every derived number is recomputed from its inputs rather than accumulated** — the grant ledger, the alignment index, the concentrator classification and the performance actuals are all rebuilt from scratch whenever an input moves"

        Design: Corner/consistency_model/every_derived_field_is_already_correct_in_the_writes_own_response_body
        """
        scenario, student, _accepted = _agreed_indicator_with_one_participant(build)

        posted = _post_two_credits(
            api, student["id"], scenario.secondary_course_id, registrar_headers
        )
        stored = validate_unpaginated(
            api.get_student(student["id"], registrar_headers), 200
        )
        assert_credit_hours(
            stored["cte_credits_earned"],
            posted["cte_credits_earned"],
            "cte_credits_earned",
        )
        assert stored["concentrator_status"] == posted["concentrator_status"]
        assert (
            stored["verified_qualifying_attainment_count"]
            == posted["verified_qualifying_attainment_count"]
        )

    def test_the_posting_has_already_moved_the_cohort_counts_of_the_indicator(
        self, api, build, registrar_headers, reviewer_headers
    ):
        """PRD §3.6: "Every credit posting also propagates into accountability, refreshing `denominator_count`, `small_cohort_flag`, `preliminary_actual_pct` and `preliminary_status_projection` on each performance indicator of the student's program whose `cohort_year` matches, and increments the student's `version`." PRD §3.8: "`denominator_count` is the number of students whose program matches the indicator's program, whose `cohort_year` matches the indicator's `cohort_year`, and whose `concentrator_status` is `CONCENTRATOR` or `COMPLETER`; a `PARTICIPANT` counts in neither the numerator nor the denominator. `numerator_count` is the number of those same students whose `verified_qualifying_attainment_count` is at least 1. `small_cohort_flag` is true exactly when `denominator_count` is below the federal minimum cohort size of 5."

        Design: Corner/consistency_model/every_derived_field_is_already_correct_in_the_writes_own_response_body
        """
        scenario, student, accepted = _agreed_indicator_with_one_participant(build)
        _post_two_credits(
            api, student["id"], scenario.secondary_course_id, registrar_headers
        )

        indicator = _read_indicator(api, accepted["id"], reviewer_headers)
        assert_cohort_figures(indicator, 1, 0, True)

    def test_the_preliminary_variant_publishes_the_raw_percentage_and_projection(
        self, api, build, registrar_headers, reviewer_headers
    ):
        """PRD §3.8: "The raw percentage is null when `denominator_count` is zero; otherwise it is 100 multiplied by `numerator_count`, divided by `denominator_count`, rounded half-up to two decimal places." "The `PRELIMINARY_UNADJUSTED` variant ignores `small_cohort_flag` completely: it publishes the raw percentage as `preliminary_actual_pct` and sets `preliminary_status_projection` to `MET` when the raw percentage is at least `met_threshold_pct`, to `NOT_MET` when it is strictly below, and to `UNDEFINED` whenever either the raw percentage or `met_threshold_pct` is null. This variant is recomputed on every read of the indicator and on every cascade that changes any cohort member's `concentrator_status`, and it never suppresses anything."

        Design: Corner/consistency_model/every_derived_field_is_already_correct_in_the_writes_own_response_body
        """
        scenario, student, accepted = _agreed_indicator_with_one_participant(build)
        _post_two_credits(
            api, student["id"], scenario.secondary_course_id, registrar_headers
        )

        indicator = _read_indicator(api, accepted["id"], reviewer_headers)
        assert_pct(indicator["preliminary_actual_pct"], 0.00, "preliminary_actual_pct")
        assert indicator["preliminary_status_projection"] == k.PROJECTION_NOT_MET
        assert_pct(indicator["met_threshold_pct"], 36.00, "met_threshold_pct")

    def test_the_preliminary_projection_does_not_score_the_indicator(
        self, api, build, registrar_headers, reviewer_headers
    ):
        """PRD §3.8: "The `FINAL_SMALL_COHORT_ADJUSTED` variant is the only one that may persist `actual_pct` or move the indicator's `status`, and it applies the suppression: when `small_cohort_flag` is true, the indicator is scored `NOT_SCORED` and `consecutive_miss_count` is left untouched regardless of how the raw percentage compares to `met_threshold_pct`. Identical student data can therefore show `preliminary_status_projection` of `NOT_MET` while the closed year records `NOT_SCORED`." "The close writes `actual_pct` from the final variant, stores `closed_on`, increments the indicator's `version`"

        Design: Corner/consistency_model/every_derived_field_is_already_correct_in_the_writes_own_response_body
        """
        scenario, student, accepted = _agreed_indicator_with_one_participant(build)
        _post_two_credits(
            api, student["id"], scenario.secondary_course_id, registrar_headers
        )

        indicator = _read_indicator(api, accepted["id"], reviewer_headers)
        assert indicator["status"] == k.PI_AGREED
        assert indicator["actual_pct"] is None
        assert indicator["closed_on"] is None
        assert indicator["consecutive_miss_count"] == 0
