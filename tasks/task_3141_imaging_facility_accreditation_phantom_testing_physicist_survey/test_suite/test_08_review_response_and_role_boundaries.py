"""Immediate visibility of a deficiency outcome, and separation of duties."""
from test_helpers import (
    TEST_USERS,
    api_client,
    read_facility,
    read_plan,
    read_unit,
    setup_imaging_facility,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWER = TEST_USERS["accreditation_body_headers"]
READER = TEST_USERS["any_headers"]


def _file(scenario, required=10, accepted=8):
    return validate_success(
        api_client.create_clinical_image_submission(
            {
                "unit_id": scenario.unit_id,
                "image_type": "CLINICAL",
                "submitted_at": "2026-09-12T00:00:00Z",
                "reviewer_note_code": "NOTE-1",
                "required_view_count": required,
                "accepted_view_count": accepted,
                "expected_unit_version": read_unit(scenario.unit_id)["version"],
            },
            scenario.admin,
        ),
        201,
    )


# ══════════════════════════════════════════════════════════════════════════
# The deficiency outcome is visible in the responding envelope
# ══════════════════════════════════════════════════════════════════════════

def test_the_review_response_carries_the_deficiency_outcome_immediately(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.3: "When those hold, the submission moves to `DEFICIENCY`, its
    `deficiency_code` is taken from the reviewer's
    `reviewer_deficiency_category`, its `review_outcome_score` is the coverage
    score described above, and both `deficiency_issued_at` and
    `deficiency_deadline_at` are stamped"

    Design: Corner/consistency_model/immediate_model_deficiency_review_is_visible_in_the_same_response
    """
    scenario = setup_imaging_facility()
    submission = _file(scenario)
    reviewed = validate_success(
        api_client.review_clinical_image_submission(
            submission["id"],
            {"review_outcome": "ACCEPT_WITH_DEFICIENCY", "reviewer_deficiency_category": "ARTIFACT"},
            REVIEWER,
        ),
        200,
    )

    assert reviewed["review_status"] == "DEFICIENCY"
    assert reviewed["review_outcome_score"] == 8.0
    assert reviewed["deficiency_code"] == "ARTIFACT"
    assert reviewed["corrective_action_plan_id"] is not None


def test_the_deficiency_deadline_and_its_plan_are_visible_on_the_next_read(api):
    """PRD §3.3: "the deadline is that instant plus `45` days. A corrective
    action plan is opened to answer the deficiency, in `OPEN` status,
    carrying the same `deficiency_code`, naming this submission as its
    `source_submission_id`"
    PRD §3.3: "The unit's `deficiency_open_count` is recomputed."
    PRD §3.3: "And the facility's `payer_participation_status` drops to
    `AT_RISK`."

    Design: Corner/consistency_model/immediate_model_deficiency_review_is_visible_in_the_same_response
    """
    scenario = setup_imaging_facility()
    submission = _file(scenario)
    reviewed = validate_success(
        api_client.review_clinical_image_submission(
            submission["id"],
            {"review_outcome": "ACCEPT_WITH_DEFICIENCY", "reviewer_deficiency_category": "ARTIFACT"},
            REVIEWER,
        ),
        200,
    )
    # submitted_at is 2026-09-12, so the 45-day deadline lands on 2026-10-27.
    assert reviewed["deficiency_deadline_at"] == "2026-10-27T00:00:00Z"

    plan = read_plan(reviewed["corrective_action_plan_id"])
    assert plan["plan_status"] == "OPEN"
    assert plan["deficiency_code"] == "ARTIFACT"
    assert plan["source_submission_id"] == submission["id"]
    assert plan["due_at"] == reviewed["deficiency_deadline_at"]

    assert read_unit(scenario.unit_id)["deficiency_open_count"] == 1
    assert read_facility(scenario.facility_id)["payer_participation_status"] == "AT_RISK"


# ══════════════════════════════════════════════════════════════════════════
# Separation of duties
# ══════════════════════════════════════════════════════════════════════════

def test_a_medical_physicist_principal_cannot_activate_an_accreditation_cycle(api):
    """PRD §2.1: "when the acting role is not listed among the roles
    authorized for the target operation, the request is rejected with
    `ERR_UNAUTHORIZED` at HTTP 403."
    PRD §2.1.1: "The five roles are partitioned so that no single party can
    both produce evidence and pass judgment on it."

    Design: Corner/roles/medical_physicist_may_not_schedule_a_survey_for_another_facilitys_qualification_carrier
    """
    scenario = setup_imaging_facility()
    res = api_client.activate_accreditation_cycle(scenario.cycle_id, {}, scenario.physicist)
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
    error = validate_error(res, "ERR_UNAUTHORIZED")
    assert error["error_id"] != "ERR_INVALID_STATE"
    assert error["error_id"] != "ERR_ALREADY_TERMINAL"

    cycle = validate_success(api_client.get_accreditation_cycle(scenario.cycle_id, READER), 200)
    assert cycle["cycle_status"] == "ACTIVE"
    assert read_facility(scenario.facility_id)["current_cycle_index"] == 1


def test_the_accrediting_body_activating_an_already_active_cycle_is_a_state_error(api):
    """PRD §2.11: "every action endpoint refuses a target that is not in a
    state from which the requested transition is declared, with
    `ERR_INVALID_STATE` at HTTP 409"
    PRD §3.2: "It requires the owning facility to be `ENROLLED`"

    Design: Corner/roles/medical_physicist_may_not_schedule_a_survey_for_another_facilitys_qualification_carrier
    """
    scenario = setup_imaging_facility()
    res = api_client.activate_accreditation_cycle(scenario.cycle_id, {}, REVIEWER)
    assert res.status_code == 409, f"Expected 409, got {res.status_code}: {res.text}"
    validate_error(res, "ERR_INVALID_STATE")


def test_the_accrediting_body_cannot_file_a_clinical_image_submission(api):
    """PRD §2.1.1: "the accrediting body is never permitted to enroll a unit,
    commission, retire or take equipment out of service, file a clinical image
    submission, record or score a phantom test, submit or resubmit a physicist
    survey, stage or submit a dose registry record, respond to a deficiency,
    or purchase registry credit on a facility's behalf."

    Design: Corner/roles/medical_physicist_may_not_schedule_a_survey_for_another_facilitys_qualification_carrier
    """
    scenario = setup_imaging_facility()
    res = api_client.create_clinical_image_submission(
        {
            "unit_id": scenario.unit_id,
            "image_type": "CLINICAL",
            "submitted_at": "2026-09-12T00:00:00Z",
            "reviewer_note_code": "NOTE-1",
            "required_view_count": 10,
            "accepted_view_count": 10,
            "expected_unit_version": read_unit(scenario.unit_id)["version"],
        },
        REVIEWER,
    )
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
    validate_error(res, "ERR_UNAUTHORIZED")

    data, meta = validate_paginated(
        api_client.list_clinical_image_submissions(READER, {"unit_id": scenario.unit_id})
    )
    assert meta["total_count"] == 0
    assert data == []