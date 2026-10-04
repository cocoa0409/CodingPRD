"""Release cycles, preliminary-result reviews, corrections and publication."""

import pytest

from test_helpers import (
    CLOCK_2026_06_01,
    CLOCK_2026_06_02,
    CLOCK_2026_06_29_LATE,
    CLOCK_2026_06_30,
    CLOCK_2026_07_01,
    CLOCK_2026_07_10,
    CLOCK_2026_07_14_LATE,
    CLOCK_2026_07_15,
    SIX_DOCUMENT_CODES,
    TEST_USERS,
    api_client,
    create_correction_payload,
    create_methodology_version_payload,
    create_survey_payload,
    file_correction,
    get_review_for,
    make_respondent_headers,
    open_review_cycle,
    open_review_cycle_with_review,
    publish_methodology,
    register_hospital,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import BASELINE_MEASURE_DEFINITIONS

ADMIN = TEST_USERS["rating_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ENGINE = TEST_USERS["engine_headers"]
READER = TEST_USERS["reader_headers"]


class TestCycleEntryGuards:

    def test_open_review_on_a_cycle_with_no_grades_is_refused(self):
        """PRD §3.7: "It requires the cycle to hold at least one grade, or it is
        refused with `ERR_CYCLE_HAS_NO_GRADES`"

        Design: Corner/state_machines/open_review_on_cycle_with_no_grades_returns_cycle_has_no_grades
        """
        version = publish_methodology(BASELINE_MEASURE_DEFINITIONS, label="Baseline Methodology")
        cycle = validate_success(api_client.create_release_cycle({
            "label": "Baseline Grades",
            "methodology_version_id": version["id"],
            "preliminary_release_date": "2026-06-01T00:00:00Z",
            "correction_window_ends_at": "2026-06-30T00:00:00Z",
            "publication_date": "2026-07-15T00:00:00Z",
        }, ADMIN), 201)

        refused = api_client.open_review(cycle["id"], ENGINE)
        validate_error(refused, "ERR_CYCLE_HAS_NO_GRADES", 409)
        reread = validate_success(api_client.get_release_cycle(cycle["id"], READER))
        assert reread["grade_count"] == 0
        assert reread["state"] == "DRAFT"
        grades, _meta = validate_paginated(
            api_client.list_release_cycle_grades(cycle["id"], READER))
        assert grades == []
        reviews, _meta = validate_paginated(
            api_client.list_reviews(READER, {"release_cycle_id": cycle["id"]}))
        assert reviews == [], "no review is synthesised for an empty cycle"


class TestCorrectionFiling:

    def test_correction_codes_must_subset_the_challenged_set(self):
        """PRD §3.7: "The `corrected_measure_codes` must be a subset of the
        parent review's `challenged_measure_codes`, which were declared when the
        review was opened; a correction naming a measure the review never
        challenged is refused with `ERR_CORRECTION_MEASURE_NOT_CHALLENGED`."

        Design: Corner/validations/correction_codes_must_subset_the_challenged_set
        """
        ctx = open_review_cycle_with_review(
            challenged_measure_codes=["o1"], measure_codes=["o1", "o2"])
        review = _read_review(ctx)
        assert review["challenged_measure_codes"] == ["o1"]

        refused = api_client.create_correction(
            ctx.hospital["id"], ctx.review["id"],
            create_correction_payload(["o2"]),
            make_respondent_headers(ctx.hospital["id"]))
        validate_error(refused, "ERR_CORRECTION_MEASURE_NOT_CHALLENGED", 409)
        rows, _meta = validate_paginated(api_client.list_corrections(
            READER, {"hospital_review_id": ctx.review["id"]}))
        assert rows == []

        filed = api_client.create_correction(
            ctx.hospital["id"], ctx.review["id"],
            create_correction_payload(["o1"]),
            make_respondent_headers(ctx.hospital["id"]))
        created = validate_success(filed, 201)
        assert created["status"] == "PENDING"

    def test_referential_tier_is_answered_before_the_temporal_tier(self):
        """PRD §3.7: "The `corrected_measure_codes` must be a subset of the
        parent review's `challenged_measure_codes`, which were declared when the
        review was opened; a correction naming a measure the review never
        challenged is refused with `ERR_CORRECTION_MEASURE_NOT_CHALLENGED`."
        PRD §3.7: "the logical-clock instant must be strictly before the cycle's
        `correction_window_ends_at`, or the filing is refused with
        `ERR_CORRECTION_WINDOW_CLOSED`"

        Design: Corner/validations/priority_ordering_prefers_referential_over_temporal_on_corrections
        """
        ctx = open_review_cycle_with_review(
            challenged_measure_codes=["o1"], measure_codes=["o1", "o2"])
        set_clock(CLOCK_2026_07_01)

        first = api_client.create_correction(
            ctx.hospital["id"], ctx.review["id"],
            create_correction_payload(["o2"]),
            make_respondent_headers(ctx.hospital["id"]))
        error_data = validate_error(first, "ERR_CORRECTION_MEASURE_NOT_CHALLENGED", 409)
        assert error_data["error_id"] != "ERR_CORRECTION_WINDOW_CLOSED"

        second = api_client.create_correction(
            ctx.hospital["id"], ctx.review["id"],
            create_correction_payload(["o1"]),
            make_respondent_headers(ctx.hospital["id"]))
        validate_error(second, "ERR_CORRECTION_WINDOW_CLOSED", 409)

        rows, _meta = validate_paginated(api_client.list_corrections(
            READER, {"hospital_review_id": ctx.review["id"]}))
        assert rows == []


class TestCorrectionWindow:

    def test_a_decision_at_the_exact_window_end_is_refused(self):
        """PRD §2.9: "Because the publish comparison accepts the instant exactly
        equal to `publication_date` while the correction-window comparisons
        exclude their boundary instants, a publish attempted at exactly
        `publication_date` succeeds and a correction filed at exactly
        `correction_window_ends_at` fails."
        PRD §3.7: "An acceptance requires the parent cycle to be `OPEN_REVIEW`,
        the clock to be strictly before the window's end, and the request to be
        `PENDING`"

        Design: Corner/state_machines/correction_window_closed_exact_boundary_between_accept_and_expire
        """
        ctx = open_review_cycle_with_review(challenged_measure_codes=["o1"])
        correction = file_correction(ctx.hospital["id"], ctx.review["id"], ["o1"])

        set_clock(CLOCK_2026_06_30)
        refused = api_client.decide_correction(
            ctx.hospital["id"], ctx.review["id"], correction["id"],
            {"decision": "ACCEPT"}, ENGINE)
        validate_error(refused, "ERR_CORRECTION_WINDOW_CLOSED", 409)

        rows, _meta = validate_paginated(api_client.list_corrections(
            READER, {"hospital_review_id": ctx.review["id"]}))
        assert rows and rows[0]["delta_points"] == pytest.approx(0.0)
        assert rows[0]["status"] == "PENDING"


class TestCorrectionDecision:

    def test_accepting_a_correction_moves_the_grade_to_corrected(self):
        """PRD §3.7: "An accepted correction moves to `ACCEPTED` and re-derives
        the grade: the grade's `composite_score` becomes the preliminary score
        plus every accepted correction's `delta_points`, rounded once to two
        decimal places, and its `letter_grade` is reassigned through the
        downgrade-on-cap variant."

        Design: Difficulty/non_linear_state_machine/release_cycle_compound_with_corrected_to_scored_cycle
        """
        ctx = open_review_cycle_with_review(challenged_measure_codes=["o1"])
        set_clock(CLOCK_2026_06_29_LATE)
        correction = file_correction(ctx.hospital["id"], ctx.review["id"], ["o1"])
        accepted = validate_success(api_client.decide_correction(
            ctx.hospital["id"], ctx.review["id"], correction["id"],
            {"decision": "ACCEPT"}, ENGINE))
        assert accepted["status"] == "ACCEPTED"

        grade = validate_success(api_client.get_grade(ctx.grade["id"], READER))
        assert grade["status"] == "CORRECTED"
        review = _read_review(ctx)
        assert review["status"] == "CORRECTION_REQUESTED"

    def test_cycle_state_advances_through_correction_closed_without_a_caller(self):
        """PRD §3.7: "When the logical clock advances strictly past
        `correction_window_ends_at`, a cycle in `OPEN_REVIEW` moves to
        `CORRECTION_CLOSED`"
        PRD §3.7: "From `CORRECTION_CLOSED` the cycle advances to `EMBARGOED`
        once every review in it is `ACCEPTED` or `CORRECTION_REQUESTED`"

        Design: Difficulty/non_linear_state_machine/release_cycle_compound_with_corrected_to_scored_cycle
        """
        ctx = open_review_cycle_with_review(challenged_measure_codes=["o1"])
        set_clock(CLOCK_2026_06_29_LATE)
        correction = file_correction(ctx.hospital["id"], ctx.review["id"], ["o1"])
        validate_success(api_client.decide_correction(
            ctx.hospital["id"], ctx.review["id"], correction["id"],
            {"decision": "ACCEPT"}, ENGINE))

        before = validate_success(api_client.get_release_cycle(ctx.cycle["id"], READER))
        assert before["state"] == "OPEN_REVIEW"

        set_clock(CLOCK_2026_07_01)
        after = validate_success(api_client.get_release_cycle(ctx.cycle["id"], READER))
        assert after["state"] == "EMBARGOED", (
            "the cycle moves through CORRECTION_CLOSED to EMBARGOED with no caller action")


class TestReviewAcceptance:

    def test_accept_closes_the_review_and_a_stale_reuse_is_refused(self):
        """PRD §3.7: "Acceptance moves the review from `PENDING` to `ACCEPTED`
        and stamps `accepted_at` with the current logical-clock instant; it must
        carry `expected_hospital_version` matching the hospital's current
        `version`, or it is refused with `ERR_STALE_VERSION`"

        Design: Corner/endpoints/action_endpoint_accept_preliminary_result_closes_the_review
        """
        ctx = open_review_cycle()
        first = validate_success(api_client.accept_preliminary_result(
            ctx.hospital["id"], ctx.review["id"],
            {"expected_hospital_version": ctx.hospital_version},
            make_respondent_headers(ctx.hospital["id"])))
        assert first["status"] == "ACCEPTED"
        assert first["accepted_at"]

        hospital_now = validate_success(api_client.get_hospital(ctx.hospital["id"], READER))
        assert hospital_now["version"] > ctx.hospital_version

        stale = api_client.accept_preliminary_result(
            ctx.hospital["id"], ctx.review["id"],
            {"expected_hospital_version": ctx.hospital_version},
            make_respondent_headers(ctx.hospital["id"]))
        validate_error(stale, "ERR_STALE_VERSION", 412)

        review = _read_review(ctx)
        assert review["status"] == "ACCEPTED"
        assert review["preliminary_composite_score"] == pytest.approx(
            ctx.review["preliminary_composite_score"])


class TestPublicationEmbargo:

    def test_publish_one_second_early_is_refused_and_the_exact_instant_succeeds(self):
        """PRD §2.9: "a publish attempted at exactly `publication_date` succeeds"
        PRD §3.7: "only when the logical-clock instant is at or after the
        cycle's `publication_date` — an attempt before that instant is refused
        with `ERR_EMBARGO_ACTIVE`"

        Design: Corner/state_machines/publish_before_publication_date_returns_embargo_active
        """
        ctx = open_review_cycle()
        validate_success(api_client.accept_preliminary_result(
            ctx.hospital["id"], ctx.review["id"],
            {"expected_hospital_version": ctx.hospital_version},
            make_respondent_headers(ctx.hospital["id"])))

        set_clock(CLOCK_2026_07_14_LATE)
        refused = api_client.publish_release_cycle(ctx.cycle["id"], ENGINE)
        validate_error(refused, "ERR_EMBARGO_ACTIVE", 409)
        early = validate_success(api_client.get_release_cycle(ctx.cycle["id"], READER))
        assert early["state"] == "EMBARGOED"
        assert early["embargo_lifted"] is False

        set_clock(CLOCK_2026_07_15)
        published = validate_success(api_client.publish_release_cycle(ctx.cycle["id"], ENGINE))
        assert published["state"] == "PUBLISHED"
        assert published["embargo_lifted"] is True

    def test_embargo_and_window_verdicts_are_distinguishable_on_the_same_cycle(self):
        """PRD §2.11: "the embargo is lifted only when the cycle publishes at or
        after its `publication_date`"
        PRD §3.7: "the logical-clock instant must be strictly before the cycle's
        `correction_window_ends_at`, or the filing is refused with
        `ERR_CORRECTION_WINDOW_CLOSED`"

        Design: Corner/errors/embargo_active_error_is_triggerable_and_distinct_from_window_closed
        """
        ctx = open_review_cycle_with_review(challenged_measure_codes=["o1"])
        correction = file_correction(ctx.hospital["id"], ctx.review["id"], ["o1"])
        set_clock(CLOCK_2026_07_10)

        embargo = api_client.publish_release_cycle(ctx.cycle["id"], ENGINE)
        err_embargo = validate_error(embargo, "ERR_EMBARGO_ACTIVE", 409)["error_id"]

        window = api_client.decide_correction(
            ctx.hospital["id"], ctx.review["id"], correction["id"],
            {"decision": "ACCEPT"}, ENGINE)
        err_window = validate_error(window, "ERR_CORRECTION_WINDOW_CLOSED", 409)["error_id"]

        assert err_embargo != err_window
        cycle = validate_success(api_client.get_release_cycle(ctx.cycle["id"], READER))
        assert cycle["state"] == "OPEN_REVIEW"
        assert cycle["embargo_lifted"] is False


class TestVersionPinning:

    def test_an_applied_pin_does_not_move_an_existing_survey_off_its_version(self):
        """PRD §3.1: "Reviewing that change posts a `decision`: an apply decision
        moves the change to `APPLIED`, creates the new pin and flips the prior
        `is_current`"
        PRD §3.2: "the methodology version that will govern the submission is
        captured at that moment from the hospital's
        `active_methodology_version_id`"

        Design: Corner/cross_cutting_complexity_layers/frozen_measure_definition_pin_keeps_a_survey_on_its_original_version
        """
        from test_helpers import create_survey_payload as _payload
        from test_helpers import (open_survey, pin_methodology, record_measure,
                                  review_pending_change, raise_pending_change)

        version_b0 = publish_methodology(BASELINE_MEASURE_DEFINITIONS,
                                         label="Baseline Methodology")
        version_mg = publish_methodology(
            [
                {"measure_code": "o1", "domain": "PATIENT_SAFETY", "scale_factor": 1.0,
                 "weight": 0.50, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
                 "higher_is_better": True, "derivation_rule": "NONE"},
                {"measure_code": "o2", "domain": "CPOE", "scale_factor": 1.0,
                 "weight": 0.30, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
                 "higher_is_better": True, "derivation_rule": "NONE"},
                {"measure_code": "o3", "domain": "STAFFING", "scale_factor": 1.0,
                 "weight": 0.20, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
                 "higher_is_better": True, "derivation_rule": "NONE"},
                {"measure_code": "o4", "domain": "INFECTION_PREVENTION", "scale_factor": 1.0,
                 "weight": 0.10, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
                 "higher_is_better": True, "derivation_rule": "NONE"},
                {"measure_code": "o5", "domain": "SURGICAL_VOLUME", "scale_factor": 1.0,
                 "weight": 0.10, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
                 "higher_is_better": True, "derivation_rule": "NONE"},
            ],
            label="Measure-Grade Methodology")

        hospital = register_hospital()
        pin_methodology(hospital["id"], version_b0["id"])
        survey = open_survey(hospital["id"])
        record_measure(hospital["id"], survey["id"], "o1", 70.0)

        change = raise_pending_change(hospital["id"], version_mg["id"])
        applied = review_pending_change(change["id"], "APPLY")
        assert applied["comparability_index"] == pytest.approx(1.0000)
        assert applied["status"] == "APPLIED"

        survey_now = validate_success(api_client.get_survey(survey["id"], READER))
        assert survey_now["methodology_version_id"] == version_b0["id"]

        hospital_now = validate_success(api_client.get_hospital(hospital["id"], READER))
        assert hospital_now["active_methodology_version_id"] == version_mg["id"]

        request = validate_success(api_client.create_reanalysis_request(
            hospital["id"],
            {"survey_id": survey["id"], "subset_selector": [{"measure_code": "o1"}],
             "supporting_documents": [
                 {"document_code": code, "issued_on": "2026-05-01T00:00:00Z"}
                 for code in SIX_DOCUMENT_CODES]},
            make_respondent_headers(hospital["id"])), 201)
        validate_success(api_client.decide_reanalysis_request(
            hospital["id"], request["id"], {"decision": "START_REVIEW"}, ANALYST))
        reread = validate_success(api_client.get_reanalysis_request(request["id"], READER))
        assert reread["reference_stale"] is True


def _read_review(ctx):
    """Read a hospital's review by id through its own collection."""
    response = api_client.list_hospital_reviews(ctx.hospital["id"], READER)
    assert response.status_code == 200
    for row in response.json()["data"]:
        if row["id"] == ctx.review["id"]:
            return row
    raise AssertionError("the review was not found in the hospital's review list")