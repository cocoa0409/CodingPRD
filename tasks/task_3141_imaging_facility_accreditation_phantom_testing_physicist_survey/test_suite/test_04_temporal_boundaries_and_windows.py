"""Boundary precision on the review and deviation rules, and window conflicts."""
from test_helpers import (
    TEST_USERS,
    api_client,
    read_facility,
    read_survey,
    read_unit,
    setup_imaging_facility,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

REVIEWER = TEST_USERS["accreditation_body_headers"]
READER = TEST_USERS["any_headers"]


def _file(scenario, required, accepted, **overrides):
    return api_client.create_clinical_image_submission(
        {
            "unit_id": scenario.unit_id,
            "image_type": "CLINICAL",
            "submitted_at": "2026-09-12T00:00:00Z",
            "reviewer_note_code": "NOTE-1",
            "required_view_count": required,
            "accepted_view_count": accepted,
            "expected_unit_version": read_unit(scenario.unit_id)["version"],
            **overrides,
        },
        scenario.admin,
    )


def _schedule_survey(scenario, scheduled_at):
    return api_client.create_physicist_survey(
        {
            "facility_id": scenario.facility_id,
            "physicist_qualification_id": scenario.physicist_qualification_id,
            "survey_type": "POST_REPAIR",
            "scheduled_at": scheduled_at,
            "reference_entrance_dose_mgy": 2.0,
            "unit_id": scenario.unit_id,
        },
        scenario.physicist,
    )


# ══════════════════════════════════════════════════════════════════════════
# Coverage boundary: strict `<` at 0.80, and exactly 1.00
# ══════════════════════════════════════════════════════════════════════════

def test_coverage_of_exactly_zero_point_eight_zero_is_not_below_the_fail_threshold(api):
    """PRD §3.3: "Otherwise, if coverage is below `0.80`, the outcome is
    likewise `FAIL` with `IMAGE_QUALITY` and a score of `0.0`."
    PRD §3.3: "Otherwise, if coverage is below `1.0` but not below `0.80`,
    the outcome is `ACCEPT_WITH_DEFICIENCY`"

    Design: Difficulty/boundary_precision_check/review_coverage_exact_0_80_and_exact_1_00
    """
    scenario = setup_imaging_facility()
    submission = validate_success(_file(scenario, required=10, accepted=8), 201)

    reviewed = validate_success(
        api_client.review_clinical_image_submission(
            submission["id"],
            {"review_outcome": "ACCEPT_WITH_DEFICIENCY", "reviewer_deficiency_category": "DOSE"},
            REVIEWER,
        ),
        200,
    )
    # 8 of 10 is coverage 0.80, which is not below the threshold, so this is a
    # deficiency rather than a failure.
    assert reviewed["review_status"] == "DEFICIENCY"
    assert reviewed["review_outcome_score"] == 8.0


def test_coverage_of_zero_point_one_zero_reaches_the_terminal_failed_outcome(api):
    """PRD §3.3: "A review returning `FAIL` is the harshest outcome"
    PRD §3.3: "A `FAILED` submission answers through exactly the same action
    and under exactly the same three preconditions, exchanging `DEFICIENCY`
    for `FAILED` in the first of them."

    Design: Difficulty/boundary_precision_check/review_coverage_exact_0_80_and_exact_1_00
    """
    scenario = setup_imaging_facility()
    submission = validate_success(_file(scenario, required=10, accepted=7), 201)
    reviewed = validate_success(
        api_client.review_clinical_image_submission(submission["id"], {"review_outcome": "FAIL"}, REVIEWER),
        200,
    )
    assert reviewed["review_status"] == "FAILED"
    assert reviewed["review_outcome_score"] == 0.0
    assert reviewed["deficiency_code"] == "IMAGE_QUALITY"


def test_full_coverage_of_exactly_one_point_zero_reaches_accepted(api):
    """PRD §3.3: "Otherwise — coverage of exactly `1.0` or greater — the
    outcome is `ACCEPT` with `NONE` and the ceiling score of `10.0`."

    Design: Difficulty/boundary_precision_check/review_coverage_exact_0_80_and_exact_1_00
    """
    scenario = setup_imaging_facility()
    submission = validate_success(_file(scenario, required=10, accepted=10), 201)
    reviewed = validate_success(
        api_client.review_clinical_image_submission(submission["id"], {"review_outcome": "ACCEPT"}, REVIEWER),
        200,
    )
    assert reviewed["review_status"] == "ACCEPTED"
    assert reviewed["review_outcome_score"] == 10.0
    assert reviewed["deficiency_code"] == "NONE"


# ══════════════════════════════════════════════════════════════════════════
# Deviation bands: inclusive at 5.0 and at 10.0, exceeded above 10.0
# ══════════════════════════════════════════════════════════════════════════

def test_deviation_of_seven_point_five_lands_in_the_partial_credit_band(api):
    """PRD §3.5: "The rule then classifies the survey's dose weight, a value
    used by consequential decisions, by the magnitude of the deviation: when
    the absolute deviation is at most `5.0` percent the dose weight is `1.0`;
    otherwise, when the absolute deviation is at most `10.0` percent, the
    weight is `0.5`; otherwise the weight is `0.0`."
    PRD §3.5: "It computes the deviation as the measured entrance dose minus
    the reference entrance dose, divided by the reference entrance dose,
    multiplied by one hundred — a signed percentage."

    Design: Difficulty/dual_variant_calc/survey_dose_deviation_banded_weight_vs_mean_of_bands
    """
    scenario = setup_imaging_facility()
    survey = validate_success(_schedule_survey(scenario, "2026-09-20T00:00:00Z"), 201)
    submitted = validate_success(
        api_client.submit_physicist_survey(
            survey["id"],
            {
                "performed_at": "2026-09-20T00:00:00Z",
                "measured_entrance_dose_mgy": 2.15,
                "shielding_verdict": "PASS",
            },
            scenario.physicist,
        ),
        200,
    )
    # (2.15 - 2.0) / 2.0 * 100 = 7.5 %
    assert submitted["dose_deviation_pct"] == 7.5
    assert submitted["survey_status"] == "SUBMITTED"
    assert submitted["rejection_code"] == "NONE"


def test_deviation_of_exactly_five_point_zero_keeps_full_credit(api):
    """PRD §3.5: "when the absolute deviation is at most `5.0` percent the
    dose weight is `1.0`"
    PRD §2.9: "Survey dose deviation percentages are likewise reported with 2
    decimal places rounded half up, and band membership is judged against the
    rounded value."
    PRD §3.5: "Band membership is judged against the rounded deviation, which
    is why `5.0` exactly earns full credit and `10.0` exactly earns half
    credit."

    Design: Difficulty/boundary_precision_check/survey_dose_deviation_exact_5_and_exact_10_and_empty_formula_result
    """
    scenario = setup_imaging_facility()
    survey = validate_success(_schedule_survey(scenario, "2026-09-20T00:00:00Z"), 201)
    submitted = validate_success(
        api_client.submit_physicist_survey(
            survey["id"],
            {
                "performed_at": "2026-09-20T00:00:00Z",
                "measured_entrance_dose_mgy": 2.1,
                "shielding_verdict": "PASS",
            },
            scenario.physicist,
        ),
        200,
    )
    # (2.1 - 2.0) / 2.0 * 100 = 5.0 % — the inclusive full-credit edge.
    assert submitted["dose_deviation_pct"] == 5.0
    assert submitted["survey_status"] == "SUBMITTED"


def test_deviation_of_exactly_ten_point_zero_keeps_the_partial_credit_band(api):
    """PRD §3.5: "otherwise, when the absolute deviation is at most `10.0`
    percent, the weight is `0.5`"
    PRD §3.5: "`10.0` exactly earns half credit"

    Design: Difficulty/boundary_precision_check/survey_dose_deviation_exact_5_and_exact_10_and_empty_formula_result
    """
    scenario = setup_imaging_facility()
    survey = validate_success(_schedule_survey(scenario, "2026-09-20T00:00:00Z"), 201)
    submitted = validate_success(
        api_client.submit_physicist_survey(
            survey["id"],
            {
                "performed_at": "2026-09-20T00:00:00Z",
                "measured_entrance_dose_mgy": 2.2,
                "shielding_verdict": "PASS",
            },
            scenario.physicist,
        ),
        200,
    )
    # (2.2 - 2.0) / 2.0 * 100 = 10.0 % — exactly on the limit, still allowed.
    assert submitted["dose_deviation_pct"] == 10.0
    assert submitted["survey_status"] == "SUBMITTED"


def test_deviation_beyond_ten_point_zero_is_refused_on_resubmission(api):
    """PRD §3.5: "the recomputed absolute deviation must be at most `10.0`
    percent"
    PRD §3.5: "When either shielding fails or the absolute deviation exceeds
    `10.0` percent, the survey does not fail outright but moves instead to
    `CORRECTIVE_REQUIRED`"

    Design: Difficulty/boundary_precision_check/survey_dose_deviation_exact_5_and_exact_10_and_empty_formula_result
    """
    scenario = setup_imaging_facility()
    survey = validate_success(_schedule_survey(scenario, "2026-09-20T00:00:00Z"), 201)
    validate_success(
        api_client.submit_physicist_survey(
            survey["id"],
            {
                "performed_at": "2026-09-20T00:00:00Z",
                "measured_entrance_dose_mgy": 2.4,
                "shielding_verdict": "PASS",
            },
            scenario.physicist,
        ),
        200,
    )
    corrective = validate_success(
        api_client.accept_physicist_survey(survey["id"], {}, REVIEWER), 200
    )
    assert corrective["survey_status"] == "CORRECTIVE_REQUIRED"

    res = api_client.resubmit_physicist_survey(
        survey["id"],
        {"measured_entrance_dose_mgy": 1.79, "shielding_verdict": "PASS"},
        scenario.physicist,
    )
    assert res.status_code == 400, f"Expected 400, got {res.status_code}: {res.text}"
    validate_error_is_one_of(res, ["ERR_SHIELDING_FAILED", "ERR_INVALID_REQUEST"])
    assert read_survey(survey["id"])["survey_status"] == "CORRECTIVE_REQUIRED"


# ══════════════════════════════════════════════════════════════════════════
# Phantom acquisition window: half-open on the right, adjacency allowed
# ══════════════════════════════════════════════════════════════════════════

def test_a_phantom_window_overlapping_a_live_one_is_refused(api):
    """PRD §3.4: "The new window, running from `acquired_at` up to but not
    including `acquired_at` plus `duration_minutes`, must be disjoint from
    every other phantom test of the same unit that is still in `ACQUIRED`
    status."
    PRD §3.4: "An overlap is refused with `ERR_PHANTOM_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/phantom_acquisition_half_open_windows_with_touching_allowed
    """
    scenario = setup_imaging_facility()
    validate_success(
        api_client.create_phantom_test(
            {
                "unit_id": scenario.unit_id,
                "phantom_serial_code": "PH-CT-9",
                "acquired_at": "2026-09-13T00:00:00Z",
                "duration_minutes": 30,
            },
            scenario.admin,
        ),
        201,
    )

    res = api_client.create_phantom_test(
        {
            "unit_id": scenario.unit_id,
            "phantom_serial_code": "PH-CT-10",
            "acquired_at": "2026-09-13T00:29:00Z",
            "duration_minutes": 30,
        },
        scenario.admin,
    )
    assert res.status_code == 400, f"Expected 400, got {res.status_code}: {res.text}"
    validate_error(res, "ERR_PHANTOM_SCHEDULE_CONFLICT")


def test_a_phantom_window_that_merely_touches_the_previous_one_is_accepted(api):
    """PRD §3.4: "Two windows that merely touch — where one begins at the
    exact instant another ends — are permitted, so the boundary convention is
    half-open on the right."

    Design: Difficulty/resource_temporal_overlap/phantom_acquisition_half_open_windows_with_touching_allowed
    """
    scenario = setup_imaging_facility()
    validate_success(
        api_client.create_phantom_test(
            {
                "unit_id": scenario.unit_id,
                "phantom_serial_code": "PH-CT-9",
                "acquired_at": "2026-09-13T00:00:00Z",
                "duration_minutes": 30,
            },
            scenario.admin,
        ),
        201,
    )
    adjacent = validate_success(
        api_client.create_phantom_test(
            {
                "unit_id": scenario.unit_id,
                "phantom_serial_code": "PH-CT-11",
                "acquired_at": "2026-09-13T00:30:00Z",
                "duration_minutes": 30,
            },
            scenario.admin,
        ),
        201,
    )
    assert adjacent["acquired_at"] == "2026-09-13T00:30:00Z"
    assert adjacent["result_status"] == "ACQUIRED"
    assert adjacent["phantom_total_score"] is None

    data, meta = validate_paginated(
        api_client.list_phantom_tests(READER, {"unit_id": scenario.unit_id, "result_status": "ACQUIRED"})
    )
    assert meta["total_count"] == 2
    assert len(data) == 2


# ══════════════════════════════════════════════════════════════════════════
# Survey window: one whole day per survey, adjacency rejected
# ══════════════════════════════════════════════════════════════════════════

def test_a_survey_scheduled_inside_an_existing_survey_day_is_refused(api):
    """PRD §3.5: "The new survey's window runs from its `performed_at` for one day,
    and it must be disjoint from every other physicist survey of the same
    facility that is not `REJECTED`"
    PRD §3.5: "A survey that overlaps a live one, or that predates one already
    on file, is refused with `ERR_SURVEY_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/physicist_survey_one_day_windows_require_strict_separation
    """
    scenario = setup_imaging_facility()
    # The accepted baseline survey was performed on 2026-09-10.
    res = _schedule_survey(scenario, "2026-09-10T12:00:00Z")
    assert res.status_code == 400, f"Expected 400, got {res.status_code}: {res.text}"
    validate_error(res, "ERR_SURVEY_WINDOW_CONFLICT")


def test_a_survey_on_a_clean_day_is_scheduled_normally(api):
    """PRD §3.5: "A scheduled survey begins in `SCHEDULED` status with
    `rejection_code` `NONE`, and its `performed_at`,
    `measured_entrance_dose_mgy`, `shielding_verdict` and `dose_deviation_pct`
    stay null until the survey is actually performed."

    Design: Difficulty/resource_temporal_overlap/physicist_survey_one_day_windows_require_strict_separation
    """
    scenario = setup_imaging_facility()
    scheduled = validate_success(_schedule_survey(scenario, "2026-09-11T00:00:00Z"), 201)
    assert scheduled["scheduled_at"] == "2026-09-11T00:00:00Z"
    assert scheduled["performed_at"] is None
    assert scheduled["survey_status"] == "SCHEDULED"
    assert scheduled["rejection_code"] == "NONE"

    data, meta = validate_paginated(
        api_client.list_physicist_surveys(READER, {"facility_id": scenario.facility_id})
    )
    assert meta["total_count"] == 2
    assert len(data) == 2


# ══════════════════════════════════════════════════════════════════════════
# Cross-entity state guard outranks the unit's own deadline
# ══════════════════════════════════════════════════════════════════════════

def test_filing_against_a_deferred_unit_is_refused_on_the_state_guard(api):
    """PRD §3.3: "Filing a submission is refused when the owning facility's
    `accreditation_currency` is `LAPSED` or `SUSPENDED`, with
    `ERR_ACCREDITATION_LAPSED`; when the owning unit is not `ENROLLED`, with
    `ERR_UNIT_DEFERRED`; and when the unit's `clinical_deadline_at` has
    already passed, with `ERR_SUBMISSION_WINDOW_CLOSED`."
    PRD §2.12: "Only then are the contextual guards evaluated:
    `ERR_UNIT_DEFERRED` when the owning unit is not `ENROLLED`"

    Design: Corner/validations/unit_deferred_rejects_new_image_submission_at_priority_four
    """
    scenario = setup_imaging_facility()
    validate_success(
        api_client.suspend_facility(
            scenario.facility_id,
            {"expected_facility_version": read_facility(scenario.facility_id)["version"]},
            REVIEWER,
        ),
        200,
    )
    assert read_unit(scenario.unit_id)["unit_status"] == "DEFERRED"

    res = _file(scenario, required=10, accepted=10)
    assert res.status_code == 409, f"Expected 409, got {res.status_code}: {res.text}"
    error = validate_error(res, "ERR_UNIT_DEFERRED")
    assert error["error_id"] != "ERR_SUBMISSION_WINDOW_CLOSED"

    data, meta = validate_paginated(
        api_client.list_clinical_image_submissions(READER, {"unit_id": scenario.unit_id})
    )
    assert meta["total_count"] == 0
    assert data == []
    assert read_unit(scenario.unit_id)["unit_status"] == "DEFERRED"
    assert read_facility(scenario.facility_id)["accreditation_currency"] == "SUSPENDED"