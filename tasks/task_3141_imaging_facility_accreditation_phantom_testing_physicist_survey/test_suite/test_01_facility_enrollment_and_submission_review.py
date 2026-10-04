"""Facility enrollment, the clinical review outcome rule, and phantom scoring."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_clinical_image_submission,
    assert_facility,
    assert_phantom_test,
    read_facility,
    read_unit,
    setup_imaging_facility,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWER = TEST_USERS["accreditation_body_headers"]


def _file_and_review(scenario, review_outcome, required, accepted, **review_overrides):
    """File a clinical image set, then review it as the accrediting body."""
    unit = read_unit(scenario.unit_id)
    submission = validate_success(
        api_client.create_clinical_image_submission(
            {
                "unit_id": scenario.unit_id,
                "image_type": "CLINICAL",
                "submitted_at": "2026-09-12T00:00:00Z",
                "reviewer_note_code": "NOTE-1",
                "required_view_count": required,
                "accepted_view_count": accepted,
                "expected_unit_version": unit["version"],
            },
            scenario.admin,
        ),
        201,
    )
    return validate_success(
        api_client.review_clinical_image_submission(
            submission["id"],
            {"review_outcome": review_outcome, **review_overrides},
            REVIEWER,
        ),
        200,
    )


def _score_phantom(scenario, spatial, contrast, artifact):
    phantom = validate_success(
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
    return validate_success(
        api_client.score_phantom_test(
            phantom["id"],
            {
                "spatial_resolution_score": spatial,
                "contrast_score": contrast,
                "artifact_score": artifact,
                "scored_at": "2026-09-13T01:00:00Z",
            },
            scenario.admin,
        ),
        200,
    )


# ══════════════════════════════════════════════════════════════════════════
# The clinical review outcome rule — reviewer-reported vs coverage-derived
# ══════════════════════════════════════════════════════════════════════════

def test_reviewer_reported_fail_short_circuits_coverage(api):
    """PRD §3.3: "The reviewer-reported variant fires only when the request
    supplies `review_outcome` as `FAIL`, and it forces the `FAIL` triple
    regardless of how good coverage is; it is only reachable when
    `accepted_view_count` is `0`."
    PRD §3.3: "The submission moves to `FAILED` with `deficiency_code`
    `IMAGE_QUALITY`, an `review_outcome_score` of `0.0`, `deficiency_issued_at`
    set to the submission's `submitted_at` and `deficiency_deadline_at` set to
    that instant plus `45` days."

    Design: Difficulty/dual_variant_calc/clinical_review_outcome_reviewer_variant_vs_coverage_variant
    """
    scenario = setup_imaging_facility()
    submission = _file_and_review(scenario, "FAIL", required=10, accepted=8)
    assert submission["review_status"] == "FAILED"
    assert submission["review_outcome_score"] == 0.0
    assert submission["deficiency_code"] == "IMAGE_QUALITY"
    assert submission["resubmission_round"] == 0
    assert submission["corrective_action_plan_id"] is not None
    assert_clinical_image_submission(submission)


def test_coverage_derived_variant_yields_deficiency_at_the_same_view_count(api):
    """PRD §3.3: "Otherwise, if coverage is below `1.0` but not below `0.80`,
    the outcome is `ACCEPT_WITH_DEFICIENCY`, the `deficiency_code` comes from
    the `reviewer_deficiency_category` the reviewer supplied, and the score is
    coverage multiplied by ten."

    Design: Difficulty/dual_variant_calc/clinical_review_outcome_reviewer_variant_vs_coverage_variant
    """
    scenario = setup_imaging_facility()
    submission = _file_and_review(
        scenario, "ACCEPT_WITH_DEFICIENCY", required=10, accepted=8,
        reviewer_deficiency_category="POSITIONING",
    )
    assert submission["review_status"] == "DEFICIENCY"
    assert submission["review_outcome_score"] == 8.0
    assert submission["deficiency_code"] == "POSITIONING"
    # The two rows carried the identical accepted view count of 8 of 10.
    assert submission["accepted_view_count"] == 8
    assert submission["required_view_count"] == 10


def test_review_branch_selection_across_fail_and_accept(api):
    """PRD §3.3: "If the reviewer explicitly reported a `review_outcome` of
    `FAIL`, the outcome is `FAIL` with `deficiency_code` `IMAGE_QUALITY` and a
    `review_outcome_score` of `0.0`."
    PRD §3.3: "Otherwise — coverage of exactly `1.0` or greater — the outcome
    is `ACCEPT` with `NONE` and the ceiling score of `10.0`."

    Design: Difficulty/combinatorial_formula/clinical_review_outcome_three_input_branch_selection
    """
    scenario = setup_imaging_facility()
    failed = _file_and_review(scenario, "FAIL", required=10, accepted=8)
    accepted = _file_and_review(scenario, "ACCEPT", required=10, accepted=10)
    assert failed["review_status"] == "FAILED"
    assert failed["review_outcome_score"] == 0.0
    assert failed["deficiency_code"] == "IMAGE_QUALITY"
    assert accepted["review_status"] == "ACCEPTED"
    assert accepted["review_outcome_score"] == 10.0
    assert accepted["deficiency_code"] == "NONE"
    assert accepted["corrective_action_plan_id"] is None


def test_phantom_composite_score_is_the_mean_of_the_three_sub_scores(api):
    """PRD §3.4: "It sums the spatial resolution, contrast and artifact
    sub-scores and divides that total by three — the arithmetic mean of the
    three sub-scores — and stores the result as `phantom_total_score` at 2
    decimal places rounded half up."
    PRD §3.4: "a test whose `phantom_total_score` reaches or exceeds `7.0`
    moves to `SCORED`, while one whose rounded total falls below `7.0` moves
    to `FAIL`."

    Design: Difficulty/combinatorial_formula/clinical_review_outcome_three_input_branch_selection
    """
    scenario = setup_imaging_facility()
    phantom = _score_phantom(scenario, 3, 4, 5)
    assert phantom["phantom_total_score"] == 4.0
    assert phantom["result_status"] == "FAIL"
    assert_phantom_test(phantom)

    unit = read_unit(scenario.unit_id)
    assert unit["last_phantom_score"] == 4.0
    assert unit["phantom_failure_count"] == 1
    assert unit["phantom_attempt_count"] == 1


def test_facility_creation_returns_declared_inputs_and_server_defaults(api, facility_admin_headers):
    """PRD §3.1: "It comes into existence in `PENDING` status with
    `accreditation_currency` `PROVISIONAL` and `payer_participation_status`
    `AT_RISK` — a new facility has proven nothing yet."
    PRD §3.1: "Its derived counters all start at zero: `registry_credit_cents`,
    `enrolled_unit_count`, `deferred_unit_count`, `current_cycle_index`,
    `rejected_survey_count`, and its `roster_disposition` is `CLEAR` because no
    one has been credentialed yet."

    Design: Corner/entities/facility_creation_returns_only_declared_input_and_defaults
    """
    created = validate_success(
        api.create_facility(
            {"name": "Lakeside MRI", "state_code": "MN", "facility_type": "HOSPITAL"},
            facility_admin_headers,
        ),
        201,
    )
    assert created["name"] == "Lakeside MRI"
    assert created["state_code"] == "MN"
    assert created["facility_type"] == "HOSPITAL"
    assert created["facility_status"] == "PENDING"
    assert created["accreditation_currency"] == "PROVISIONAL"
    assert created["payer_participation_status"] == "AT_RISK"
    assert created["registry_credit_cents"] == 0
    assert created["enrolled_unit_count"] == 0
    assert created["deferred_unit_count"] == 0
    assert created["rejected_survey_count"] == 0
    assert created["roster_disposition"] == "CLEAR"
    assert created["version"] == 1
    assert_facility(created)


def test_facility_read_of_an_unknown_identifier_is_a_dedicated_not_found(api, any_headers):
    """PRD §2.11: "the identifiers are resolved left to right, and the request
    fails at the first one that does not resolve, with the not-found error
    dedicated to that identifier's type."

    Design: Corner/entities/facility_read_of_an_unknown_id_returns_not_found
    """
    error = validate_error(
        api.get_facility(NON_EXISTENT_UUID, any_headers), "ERR_FACILITY_NOT_FOUND"
    )
    assert isinstance(error["message"], str) and error["message"].strip()
    data, meta = validate_paginated(api.list_facilities(any_headers))
    assert meta["total_count"] == 0
    assert data == []


def test_modality_unit_creation_requires_the_facility_reference_to_resolve(api, facility_admin_headers):
    """PRD §2.11: "a modality unit, physicist survey, personnel qualification
    or accreditation cycle that names a facility which does not exist fails
    with `ERR_FACILITY_NOT_FOUND`"

    Design: Corner/entities/modality_unit_create_requires_the_facility_foreign_key_to_resolve
    """
    facility = validate_success(
        api.create_facility(
            {"name": "Northgate Imaging Center", "state_code": "CT", "facility_type": "IMAGING_CENTER"},
            facility_admin_headers,
        ),
        201,
    )
    version_before = facility["version"]
    res = api.create_modality_unit(
        {
            "facility_id": NON_EXISTENT_UUID,
            "modality_code": "CT",
            "unit_label": "CT-1",
            "expected_facility_version": version_before,
        },
        facility_admin_headers,
    )
    validate_error(res, "ERR_FACILITY_NOT_FOUND")

    data, meta = validate_paginated(
        api.list_modality_units(facility_admin_headers, {"facility_id": facility["id"]})
    )
    assert meta["total_count"] == 0
    refreshed = read_facility(facility["id"])
    assert refreshed["facility_status"] == "PENDING"
    assert refreshed["enrolled_unit_count"] == 0
    assert refreshed["version"] == version_before