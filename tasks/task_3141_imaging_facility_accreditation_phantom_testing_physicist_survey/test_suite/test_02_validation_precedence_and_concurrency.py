"""Validation precedence between rungs, and optimistic-concurrency rejection."""
from test_helpers import (
    TEST_USERS,
    api_client,
    read_facility,
    read_plan,
    read_submission,
    read_survey,
    read_unit,
    setup_imaging_facility,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWER = TEST_USERS["accreditation_body_headers"]
READER = TEST_USERS["any_headers"]


def _file_and_review(scenario, review_outcome, required, accepted, **review_overrides):
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


def _record_phantom(scenario, acquired_at="2026-09-13T00:00:00Z"):
    return validate_success(
        api_client.create_phantom_test(
            {
                "unit_id": scenario.unit_id,
                "phantom_serial_code": "PH-CT-9",
                "acquired_at": acquired_at,
                "duration_minutes": 30,
            },
            scenario.admin,
        ),
        201,
    )


def _score_phantom(scenario, phantom_id, spatial, contrast, artifact, scored_at):
    return api_client.score_phantom_test(
        phantom_id,
        {
            "spatial_resolution_score": spatial,
            "contrast_score": contrast,
            "artifact_score": artifact,
            "scored_at": scored_at,
        },
        scenario.admin,
    )


# ══════════════════════════════════════════════════════════════════════════
# Priority pair: state rules outrank the business-referential rung
# ══════════════════════════════════════════════════════════════════════════

def test_rescoring_a_terminal_phantom_returns_the_state_error(api):
    """PRD §3.4: "A test that has already reached a terminal state cannot be
    scored again and draws `ERR_ALREADY_TERMINAL`, and a test outside the
    `ACQUIRED` state draws `ERR_INVALID_STATE`."
    PRD §2.12: "State rules come next. The system first confirms the target is
    in a state from which the requested transition is declared, raising
    `ERR_INVALID_STATE` otherwise, and confirms it has not already reached a
    terminal state, raising `ERR_ALREADY_TERMINAL`."
    PRD §2.12: "then the referential rules `ERR_CAUSAL_ORDER`,
    `ERR_RESUBMISSION_CHAIN` and `ERR_PHANTOM_UNSCORED`"

    Design: Difficulty/priority_pair_validation_conflict/state_versus_business_referential_on_phantom_scoring
    """
    scenario = setup_imaging_facility()
    # A deficiency is on file, issued at 2026-09-12T00:00:00Z.
    _file_and_review(scenario, "ACCEPT_WITH_DEFICIENCY", 10, 8,
                     reviewer_deficiency_category="ARTIFACT")
    phantom = _record_phantom(scenario)
    scored = validate_success(
        _score_phantom(scenario, phantom["id"], 3, 4, 5, "2026-09-13T01:00:00Z"), 200
    )
    assert scored["result_status"] == "FAIL"

    # The re-score is both terminal-targeted and causally out of order.
    res = _score_phantom(scenario, phantom["id"], 9, 9, 9, "2026-09-11T00:00:00Z")
    assert res.status_code == 409, f"Expected 409, got {res.status_code}: {res.text}"
    error = validate_error(res, "ERR_ALREADY_TERMINAL")
    assert error["error_id"] != "ERR_CAUSAL_ORDER"


def test_a_refused_rescore_leaves_the_phantom_and_its_sub_scores_intact(api):
    """PRD §3.4: "A test that has already reached a terminal state cannot be
    scored again and draws `ERR_ALREADY_TERMINAL`"

    Design: Difficulty/priority_pair_validation_conflict/state_versus_business_referential_on_phantom_scoring
    """
    scenario = setup_imaging_facility()
    phantom = _record_phantom(scenario)
    validate_success(_score_phantom(scenario, phantom["id"], 3, 4, 5, "2026-09-13T01:00:00Z"), 200)

    _score_phantom(scenario, phantom["id"], 9, 9, 9, "2026-09-13T02:00:00Z")

    after = validate_success(api_client.get_phantom_test(phantom["id"], READER), 200)
    assert after["phantom_total_score"] == 4.0
    assert after["result_status"] == "FAIL"
    assert after["spatial_resolution_score"] == 3
    assert after["contrast_score"] == 4
    assert after["artifact_score"] == 5


# ══════════════════════════════════════════════════════════════════════════
# Priority pair: business safety outranks the temporal rung
# ══════════════════════════════════════════════════════════════════════════

def test_resubmitting_with_a_failing_shielding_verdict_is_refused_on_safety(api):
    """PRD §3.5: "Correcting the problem means resubmitting. The physicist
    supplies a fresh `measured_entrance_dose_mgy` and `shielding_verdict`; the
    survey must currently be `CORRECTIVE_REQUIRED`; `shielding_verdict` must
    now be `PASS`"
    PRD §2.12: "Business safety rules form the widest of the later rungs and
    are evaluated together as a group: `ERR_DEADLINE_OVERDUE`,
    `ERR_DEFICIENCY_PENDING`, `ERR_QUALIFICATION_UNVERIFIED`,
    `ERR_SURVEY_SHORTFALL`, `ERR_ROSTER_INELIGIBLE`, `ERR_CE_HOURS_SHORTFALL`
    and `ERR_SHIELDING_FAILED`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_versus_business_temporal_on_survey_resubmission
    """
    scenario = setup_imaging_facility()
    corrective = _corrective_required_by_shielding(scenario)
    assert corrective["survey_status"] == "CORRECTIVE_REQUIRED"

    res = api_client.resubmit_physicist_survey(
        corrective["id"],
        {"measured_entrance_dose_mgy": 2.15, "shielding_verdict": "FAIL"},
        scenario.physicist,
    )
    assert res.status_code == 400, f"Expected 400, got {res.status_code}: {res.text}"
    error = validate_error(res, "ERR_SHIELDING_FAILED")
    assert error["error_id"] != "ERR_SUBMISSION_WINDOW_CLOSED"


def test_a_refused_survey_resubmission_leaves_state_and_balance_untouched(api):
    """PRD §3.5: "the survey does not fail outright but moves instead to
    `CORRECTIVE_REQUIRED`"
    PRD §3.5: "A successful resubmission debits `100000` from the facility's
    `registry_credit_cents`"

    Design: Difficulty/priority_pair_validation_conflict/business_safety_versus_business_temporal_on_survey_resubmission
    """
    scenario = setup_imaging_facility()
    corrective = _corrective_required_by_shielding(scenario)

    api_client.resubmit_physicist_survey(
        corrective["id"],
        {"measured_entrance_dose_mgy": 2.15, "shielding_verdict": "FAIL"},
        scenario.physicist,
    )

    after = read_survey(corrective["id"])
    assert after["survey_status"] == "CORRECTIVE_REQUIRED"
    assert after["rejection_code"] == "SHIELDING_FAILED"
    assert read_facility(scenario.facility_id)["registry_credit_cents"] == 500000


# ══════════════════════════════════════════════════════════════════════════
# Optimistic concurrency — the two version-echo gates
# ══════════════════════════════════════════════════════════════════════════

def test_resubmission_with_a_stale_unit_version_is_rejected(api):
    """PRD §3.3: "Because filing mutates the unit aggregate, it must carry
    `expected_unit_version`, and a mismatch is refused with
    `ERR_STALE_VERSION`."
    PRD §2.10: "Creating a clinical image submission — whether a first
    submission or the resubmission that answers a deficiency — is guarded by
    the unit."

    Design: Corner/concurrency_rules/unit_resubmission_create_with_a_stale_unit_version_returns_412
    """
    scenario = setup_imaging_facility()
    unit = read_unit(scenario.unit_id)
    stale_version = unit["version"]

    submission = validate_success(
        api_client.create_clinical_image_submission(
            {
                "unit_id": scenario.unit_id,
                "image_type": "CLINICAL",
                "submitted_at": "2026-09-12T00:00:00Z",
                "reviewer_note_code": "NOTE-1",
                "required_view_count": 10,
                "accepted_view_count": 8,
                "expected_unit_version": stale_version,
            },
            scenario.admin,
        ),
        201,
    )
    reviewed = validate_success(
        api_client.review_clinical_image_submission(
            submission["id"],
            {"review_outcome": "ACCEPT_WITH_DEFICIENCY", "reviewer_deficiency_category": "POSITIONING"},
            REVIEWER,
        ),
        200,
    )
    plan_id = reviewed["corrective_action_plan_id"]
    version_after_review = read_unit(scenario.unit_id)["version"]
    assert version_after_review > stale_version

    res = api_client.resubmit_clinical_image_submission(
        submission["id"],
        {
            "submitted_at": "2026-09-14T00:00:00Z",
            "reviewer_note_code": "NOTE-2",
            "accepted_view_count": 10,
            "expected_unit_version": stale_version,
        },
        scenario.admin,
    )
    assert res.status_code == 412, f"Expected 412, got {res.status_code}: {res.text}"
    error = validate_error(res, "ERR_STALE_VERSION")
    assert error["error_id"] != "ERR_INVALID_STATE"

    assert read_submission(submission["id"])["review_status"] == "DEFICIENCY"
    assert read_plan(plan_id)["plan_status"] == "OPEN"
    assert read_unit(scenario.unit_id)["version"] == version_after_review


def test_resubmission_with_the_current_unit_version_is_accepted(api):
    """PRD §3.3: "a fresh clinical image submission is created in
    `PENDING_REVIEW` whose `image_type` is `CLINICAL`, whose
    `resubmission_of_submission_id` names the submission being answered, and
    whose `resubmission_round` is exactly one greater than its parent's."

    Design: Corner/concurrency_rules/unit_resubmission_create_with_a_stale_unit_version_returns_412
    """
    scenario = setup_imaging_facility()
    submission, plan = _deficient_submission(scenario)

    fresh = validate_success(
        api_client.resubmit_clinical_image_submission(
            submission["id"],
            {
                "submitted_at": "2026-09-14T00:00:00Z",
                "reviewer_note_code": "NOTE-2",
                "accepted_view_count": 10,
                "expected_unit_version": read_unit(scenario.unit_id)["version"],
            },
            scenario.admin,
        ),
        201,
    )
    assert fresh["review_status"] == "PENDING_REVIEW"
    assert fresh["image_type"] == "CLINICAL"
    assert fresh["resubmission_of_submission_id"] == submission["id"]
    assert fresh["resubmission_round"] == 1
    assert read_submission(submission["id"])["review_status"] == "RESUBMITTED"


def test_facility_registration_with_a_stale_facility_version_is_rejected(api, facility_admin_headers):
    """PRD §2.10: "Whenever a supplied `expected_facility_version` or
    `expected_unit_version` does not equal the persisted `version` of the
    parent entity it names, the write is rejected with `ERR_STALE_VERSION` at
    HTTP 412, protecting the client from overwriting a facility or unit
    aggregate it has not observed."

    Design: Corner/endpoints/facility_register_rejects_a_deliberately_stale_expected_version
    """
    facility = validate_success(
        api.create_facility(
            {"name": "Northgate Imaging Center", "state_code": "CT", "facility_type": "IMAGING_CENTER"},
            facility_admin_headers,
        ),
        201,
    )
    stale_version = facility["version"]

    technician = validate_success(
        api.create_personnel_qualification(
            {
                "facility_id": facility["id"],
                "person_name": "Hana Reyes",
                "personnel_role": "TECHNOLOGIST",
                "credential_number": "TECH-1001",
                "ce_credit_hours": 24.0,
                "required_ce_hours": 24.0,
                "credential_expires_on": "2027-06-30T00:00:00Z",
            },
            REVIEWER,
        ),
        201,
    )
    validate_success(
        api.verify_personnel_qualification(
            technician["id"], {"verified_at": "2026-09-02T00:00:00Z"}, REVIEWER
        ),
        200,
    )

    unit = validate_success(
        api.create_modality_unit(
            {
                "facility_id": facility["id"],
                "modality_code": "CT",
                "unit_label": "CT-1",
                "expected_facility_version": read_facility(facility["id"])["version"],
            },
            facility_admin_headers,
        ),
        201,
    )
    validate_success(
        api.create_equipment(
            {
                "unit_id": unit["id"],
                "manufacturer": "Siemens",
                "model_number": "SOMATOM-X1",
                "serial_number": "SN-CT-0001",
                "modality_code": "CT",
                "installed_on": "2026-08-01T00:00:00Z",
            },
            facility_admin_headers,
        ),
        201,
    )

    # A registry-credit purchase mutates the facility aggregate, so the
    # version captured above is now behind.
    validate_success(
        api.purchase_registry_credit(
            facility["id"],
            {
                "amount_cents": 0,
                "expected_facility_version": read_facility(facility["id"])["version"],
            },
            facility_admin_headers,
        ),
        200,
    )

    res = api.register_facility(facility["id"], {"expected_facility_version": stale_version}, facility_admin_headers)
    assert res.status_code == 412, f"Expected 412, got {res.status_code}: {res.text}"
    validate_error(res, "ERR_STALE_VERSION")

    untouched = read_facility(facility["id"])
    assert untouched["facility_status"] == "PENDING"
    assert untouched["version"] == stale_version + 1
    assert untouched["enrolled_unit_count"] == 0

    # The same call carrying the current version succeeds.
    current = read_facility(facility["id"])["version"]
    registered = validate_success(
        api.register_facility(facility["id"], {"expected_facility_version": current}, facility_admin_headers),
        200,
    )
    assert registered["facility_status"] == "ENROLLED"
    assert registered["enrolled_unit_count"] == 1


# ══════════════════════════════════════════════════════════════════════════
# Auth rungs
# ══════════════════════════════════════════════════════════════════════════

def test_an_unauthorized_role_is_forbidden_rather_than_unauthenticated(api):
    """PRD §2.1: "when the acting role is not listed among the roles
    authorized for the target operation, the request is rejected with
    `ERR_UNAUTHORIZED` at HTTP 403."
    PRD §2.1: "Header presence alone is never sufficient"

    Design: Corner/errors/unauthorized_role_returns_forbidden_on_a_review_call
    """
    scenario = setup_imaging_facility()
    unit = read_unit(scenario.unit_id)
    submission = validate_success(
        api_client.create_clinical_image_submission(
            {
                "unit_id": scenario.unit_id,
                "image_type": "CLINICAL",
                "submitted_at": "2026-09-12T00:00:00Z",
                "reviewer_note_code": "NOTE-1",
                "required_view_count": 10,
                "accepted_view_count": 10,
                "expected_unit_version": unit["version"],
            },
            scenario.admin,
        ),
        201,
    )

    # FacilityAdmin holds a declared role but is not authorized to review.
    res = api_client.review_clinical_image_submission(
        submission["id"], {"review_outcome": "ACCEPT"}, scenario.admin
    )
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
    error = validate_error(res, "ERR_UNAUTHORIZED")
    assert error["error_id"] != "ERR_UNAUTHENTICATED"

    after = read_submission(submission["id"])
    assert after["review_status"] == "PENDING_REVIEW"
    assert after["review_outcome_score"] is None
    assert read_unit(scenario.unit_id)["deficiency_open_count"] == 0


def test_a_request_without_a_role_header_is_unauthenticated(api, any_headers):
    """PRD §2.1: "A request that omits either header, or that supplies a role
    value not among the declared roles, is rejected with `ERR_UNAUTHENTICATED`
    at HTTP 401."

    Design: Corner/errors/unauthenticated_missing_role_header_returns_401_not_403
    """
    res = api_client.create_facility(
        {"name": "No Header Imaging", "state_code": "CT", "facility_type": "HOSPITAL"},
        {"Content-Type": "application/json"},
    )
    assert res.status_code == 401, f"Expected 401, got {res.status_code}: {res.text}"
    error = validate_error(res, "ERR_UNAUTHENTICATED")
    assert error["error_id"] != "ERR_UNAUTHORIZED"
    assert error["error_id"] != "ERR_INVALID_REQUEST"

    data, meta = validate_paginated(api.list_facilities(any_headers))
    assert meta["total_count"] == 0
    assert data == []


def test_a_role_value_outside_the_declared_set_is_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or that supplies a role
    value not among the declared roles, is rejected with `ERR_UNAUTHENTICATED`
    at HTTP 401."

    Design: Corner/errors/unauthenticated_missing_role_header_returns_401_not_403
    """
    res = api_client.create_facility(
        {"name": "Bogus Role Imaging", "state_code": "CT", "facility_type": "HOSPITAL"},
        {"X-User-ID": "someone", "X-User-Role": "NotARole", "Content-Type": "application/json"},
    )
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── local helpers ────────────────────────────────────────────────────────

def _deficient_submission(scenario):
    submission = validate_success(
        api_client.create_clinical_image_submission(
            {
                "unit_id": scenario.unit_id,
                "image_type": "CLINICAL",
                "submitted_at": "2026-09-12T00:00:00Z",
                "reviewer_note_code": "NOTE-1",
                "required_view_count": 10,
                "accepted_view_count": 8,
                "expected_unit_version": read_unit(scenario.unit_id)["version"],
            },
            scenario.admin,
        ),
        201,
    )
    reviewed = validate_success(
        api_client.review_clinical_image_submission(
            submission["id"],
            {"review_outcome": "ACCEPT_WITH_DEFICIENCY", "reviewer_deficiency_category": "POSITIONING"},
            REVIEWER,
        ),
        200,
    )
    return reviewed, read_plan(reviewed["corrective_action_plan_id"])


def _corrective_required_by_shielding(scenario):
    """A POST_REPAIR survey accepted with a failing shielding verdict."""
    survey = validate_success(
        api_client.create_physicist_survey(
            {
                "facility_id": scenario.facility_id,
                "physicist_qualification_id": scenario.physicist_qualification_id,
                "survey_type": "POST_REPAIR",
                "scheduled_at": "2026-09-20T00:00:00Z",
                "reference_entrance_dose_mgy": 2.0,
                "unit_id": scenario.unit_id,
            },
            scenario.physicist,
        ),
        201,
    )
    validate_success(
        api_client.submit_physicist_survey(
            survey["id"],
            {
                "performed_at": "2026-09-20T00:00:00Z",
                "measured_entrance_dose_mgy": 2.15,
                "shielding_verdict": "FAIL",
            },
            scenario.physicist,
        ),
        200,
    )
    return validate_success(
        api_client.accept_physicist_survey(survey["id"], {}, REVIEWER), 200
    )