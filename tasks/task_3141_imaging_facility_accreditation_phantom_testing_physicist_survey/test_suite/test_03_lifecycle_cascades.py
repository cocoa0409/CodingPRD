"""State-machine transitions and the multi-hop cascades they trigger."""
from test_helpers import (
    TEST_USERS,
    api_client,
    read_facility,
    read_plan,
    read_submission,
    read_unit,
    setup_imaging_facility,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWER = TEST_USERS["accreditation_body_headers"]
READER = TEST_USERS["any_headers"]


# ══════════════════════════════════════════════════════════════════════════
# Facility suspension cascade: facility -> unit -> equipment / phantom
# ══════════════════════════════════════════════════════════════════════════

def test_suspension_cascades_through_the_unit_to_equipment_and_phantom(api):
    """PRD §3.1: "Suspension moves `facility_status` to `SUSPENDED` and
    `accreditation_currency` to `SUSPENDED`, revokes payer participation by
    setting `payer_participation_status` to `REVOKED`, and defers every
    enrolled unit."
    PRD §3.1: "Each deferred unit in turn pushes its equipment `OUT_OF_SERVICE`
    and voids any phantom acquisition that was still `ACQUIRED`"
    PRD §3.1: "every phantom test of that unit still in `ACQUIRED` status is
    voided, and the unit's `phantom_attempt_count` is recomputed so the voided
    tests drop out"

    Design: Difficulty/transitive_cascade/renewal_rejection_hop_accreditation_hop_unit_hop_equipment_and_phantoms
    """
    scenario = setup_imaging_facility()
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
    validate_success(
        api_client.suspend_facility(
            scenario.facility_id,
            {"expected_facility_version": read_facility(scenario.facility_id)["version"]},
            REVIEWER,
        ),
        200,
    )

    facility = read_facility(scenario.facility_id)
    assert facility["facility_status"] == "SUSPENDED"
    assert facility["accreditation_currency"] == "SUSPENDED"
    assert facility["payer_participation_status"] == "REVOKED"

    unit = read_unit(scenario.unit_id)
    assert unit["unit_status"] == "DEFERRED"

    equipment = validate_success(api_client.get_equipment(scenario.equipment_id, READER), 200)
    assert equipment["equipment_status"] == "OUT_OF_SERVICE"

    voided = validate_success(api_client.get_phantom_test(phantom["id"], READER), 200)
    assert voided["result_status"] == "VOIDED"
    assert voided["phantom_total_score"] is None

    assert facility["enrolled_unit_count"] == 0
    assert facility["deferred_unit_count"] == 1


def test_suspension_leaves_an_accepted_survey_undisturbed(api):
    """PRD §3.1: "Each deferred unit in turn pushes its equipment `OUT_OF_SERVICE`
    and voids any phantom acquisition that was still `ACQUIRED`; the facility's
    `enrolled_unit_count` and `deferred_unit_count` are recomputed afterwards."

    Design: Difficulty/transitive_cascade/renewal_rejection_hop_accreditation_hop_unit_hop_equipment_and_phantoms
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
    survey = validate_success(api_client.get_physicist_survey(scenario.survey_id, READER), 200)
    assert survey["survey_status"] == "ACCEPTED"


def test_suspending_defers_every_enrolled_unit_and_recomputes_the_counters(api):
    """PRD §3.1: "It requires only that at least one unit of the facility be in
    `ENROLLED` or `DEFERRED` status, and it must carry
    `expected_facility_version`."
    PRD §3.1: "Each deferred unit pushes its equipment `OUT_OF_SERVICE`,
    expires every corrective action plan of its facility, and causes the
    facility's two unit counters to be recomputed."

    Design: Corner/state_machines/modality_unit_becomes_deferred_when_its_facility_is_suspended_and_never_returns_to_enrolled_directly
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

    facility = read_facility(scenario.facility_id)
    assert facility["facility_status"] == "SUSPENDED"
    assert facility["enrolled_unit_count"] == 0
    assert facility["deferred_unit_count"] == 1

    unit = read_unit(scenario.unit_id)
    assert unit["unit_status"] == "DEFERRED"
    assert unit["deficiency_open_count"] == 0
    assert unit["phantom_attempt_count"] == 0

    equipment = validate_success(api_client.get_equipment(scenario.equipment_id, READER), 200)
    assert equipment["equipment_status"] == "OUT_OF_SERVICE"


# ══════════════════════════════════════════════════════════════════════════
# The deficiency hop chain: review -> plan -> unit count -> payer posture
# ══════════════════════════════════════════════════════════════════════════

def test_a_deficiency_cascades_four_hops_to_restore_payer_participation(api):
    """PRD §3.3: "The unit's `deficiency_open_count` is recomputed, and if it
    falls to zero while every other unit of the facility is also at zero, the
    facility's `payer_participation_status` is restored to `ACTIVE`."
    PRD §3.3: "And the facility's `payer_participation_status` drops to
    `AT_RISK`."
    PRD §3.7: "A successful submission moves the plan to `SUBMITTED`"

    Design: Difficulty/transitive_cascade/deficiency_hop_plan_hop_unit_count_hop_payer_hop
    """
    scenario = setup_imaging_facility()
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
    plan_id = reviewed["corrective_action_plan_id"]

    # hop 1
    assert reviewed["review_status"] == "DEFICIENCY"
    assert read_facility(scenario.facility_id)["payer_participation_status"] == "AT_RISK"

    # The plan must be answerable before it can be submitted, so give the unit
    # phantom evidence scored after the deficiency was issued.
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
    # `validate_success` already returns the envelope's `data` payload (here an
    # array), so index it directly rather than reading a further `["data"]` key.
    phantom_rows, phantom_meta = validate_paginated(
        api_client.list_phantom_tests(READER, {"unit_id": scenario.unit_id})
    )
    assert phantom_meta["total_count"] == 1
    phantom_id = phantom_rows[0]["id"]
    validate_success(
        api_client.score_phantom_test(
            phantom_id,
            {
                "spatial_resolution_score": 9,
                "contrast_score": 9,
                "artifact_score": 9,
                "scored_at": "2026-09-13T01:00:00Z",
            },
            scenario.admin,
        ),
        200,
    )

    # hop 2 — the plan becomes SUBMITTED (set by the submit call, not the review)
    submitted = validate_success(
        api_client.submit_corrective_action_plan(plan_id, {}, scenario.admin), 200
    )
    assert submitted["plan_status"] == "SUBMITTED"

    # hop 3 — the unit's open deficiency count is still 1
    assert read_unit(scenario.unit_id)["deficiency_open_count"] == 1

    # hop 4 — the answering resubmission accepted clears the count and the posture
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
    validate_success(
        api_client.review_clinical_image_submission(fresh["id"], {"review_outcome": "ACCEPT"}, REVIEWER),
        200,
    )

    assert read_unit(scenario.unit_id)["deficiency_open_count"] == 0
    assert read_facility(scenario.facility_id)["payer_participation_status"] == "ACTIVE"


def test_the_answering_resubmission_advances_the_chain_one_round(api):
    """PRD §3.3: "whose `resubmission_round` is exactly one greater than its
    parent's. The parent moves to the terminal `RESUBMITTED`."

    Design: Difficulty/transitive_cascade/deficiency_hop_plan_hop_unit_count_hop_payer_hop
    """
    scenario = setup_imaging_facility()
    fresh, parent = _resubmit_a_deficiency(scenario)
    assert fresh["resubmission_round"] == 1
    assert fresh["resubmission_of_submission_id"] == parent["id"]
    assert fresh["review_status"] == "PENDING_REVIEW"
    assert read_submission(parent["id"])["review_status"] == "RESUBMITTED"


# ══════════════════════════════════════════════════════════════════════════
# Unit enrollment gated by the parent facility's state
# ══════════════════════════════════════════════════════════════════════════

def test_enrolling_a_unit_into_a_suspended_facility_is_refused(api):
    """PRD §2.12: "Only then are the contextual guards evaluated:
    `ERR_UNIT_DEFERRED` when the owning unit is not `ENROLLED`"
    PRD §3.1: "A facility that has no units, that has deferred a unit, or that
    has taken an item out of service is not ready."

    Design: Difficulty/cross_entity_state_dependency/unit_enrollment_gated_by_facility_status_after_renewal_rejection
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

    res = api_client.create_modality_unit(
        {
            "facility_id": scenario.facility_id,
            "modality_code": "MRI",
            "unit_label": "MR-2",
            "expected_facility_version": read_facility(scenario.facility_id)["version"],
        },
        scenario.admin,
    )
    assert res.status_code == 409, f"Expected 409, got {res.status_code}: {res.text}"
    error = validate_error(res, "ERR_UNIT_DEFERRED")
    assert error["error_id"] != "ERR_ACCREDITATION_LAPSED"

    data, meta = validate_paginated(
        api_client.list_modality_units(READER, {"facility_id": scenario.facility_id})
    )
    assert meta["total_count"] == 1
    assert data[0]["unit_status"] == "DEFERRED"
    assert all(row["modality_code"] != "MRI" for row in data)


def test_a_refused_unit_enrollment_leaves_the_facility_counters_alone(api):
    """PRD §3.1: "Enrolling also recomputes the owning facility's
    `enrolled_unit_count`, so the facility's roll-up always reflects the units
    it actually holds."
    PRD §3.1: "A new unit begins in `ENROLLED` status"

    Design: Difficulty/cross_entity_state_dependency/unit_enrollment_gated_by_facility_status_after_renewal_rejection
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
    api_client.create_modality_unit(
        {
            "facility_id": scenario.facility_id,
            "modality_code": "MRI",
            "unit_label": "MR-2",
            "expected_facility_version": read_facility(scenario.facility_id)["version"],
        },
        scenario.admin,
    )

    facility = read_facility(scenario.facility_id)
    assert facility["facility_status"] == "SUSPENDED"
    assert facility["deferred_unit_count"] == 1
    assert facility["enrolled_unit_count"] == 0


# ══════════════════════════════════════════════════════════════════════════
# Corrective action plan: the cyclic machine reopens from a rejection
# ══════════════════════════════════════════════════════════════════════════

def test_rejecting_a_plan_response_reopens_it_and_grows_the_attempt_counter(api):
    """PRD §3.7: "Rejection increments `resubmission_attempts` by one, extends
    `due_at` by `30` days, and extends `resubmission_deadline_at` by `30` days,
    giving the facility a fresh month to answer properly."
    PRD §3.7: "Note that the plan returns to `OPEN` status once rejected,
    which is what allows it to be submitted again."

    Design: Difficulty/non_linear_state_machine/corrective_action_plan_reopen_cycle_via_targeted_review
    """
    scenario = setup_imaging_facility()
    reviewed, plan = _deficient_with_plan(scenario)
    validate_success(api_client.submit_corrective_action_plan(plan["id"], {}, scenario.admin), 200)

    rejected = validate_success(
        api_client.reject_corrective_action_plan(plan["id"], {}, REVIEWER), 200
    )
    assert rejected["plan_status"] == "OPEN"
    assert rejected["resubmission_attempts"] == 1
    # The plan is created at 2026-10-27 (submitted_at 2026-09-12 + the PRD's
    # 45-day deficiency deadline), with `due_at` and `resubmission_deadline_at`
    # both inherited from it. Submitting the response applies the stated one-day
    # grace to `due_at` only -> 2026-10-28, leaving `resubmission_deadline_at` at
    # 2026-10-27. Rejection then extends each of them by the stated 30 days:
    # `due_at` 2026-10-28 -> 2026-11-27 and `resubmission_deadline_at`
    # 2026-10-27 -> 2026-11-26.
    assert rejected["due_at"] == "2026-11-27T00:00:00Z"
    assert rejected["resubmission_deadline_at"] == "2026-11-26T00:00:00Z"


def test_a_reopened_plan_keeps_the_source_submission_and_unit_count(api):
    """PRD §3.7: "It opens in `OPEN` status with `due_at` and
    `resubmission_deadline_at` inherited from the creating submission's
    `deficiency_deadline_at`, `resubmission_attempts` at `0`"
    PRD §3.3: "The resubmission chain is bounded."

    Design: Difficulty/non_linear_state_machine/corrective_action_plan_reopen_cycle_via_targeted_review
    """
    scenario = setup_imaging_facility()
    reviewed, plan = _deficient_with_plan(scenario)
    validate_success(api_client.submit_corrective_action_plan(plan["id"], {}, scenario.admin), 200)
    api_client.reject_corrective_action_plan(plan["id"], {}, REVIEWER)

    assert read_unit(scenario.unit_id)["deficiency_open_count"] == 1
    assert read_submission(reviewed["id"])["review_status"] == "DEFICIENCY"
    reopened = read_plan(plan["id"])
    assert reopened["plan_status"] == "OPEN"
    assert reopened["source_submission_id"] == reviewed["id"]


# ══════════════════════════════════════════════════════════════════════════
# Other state-machine corners
# ══════════════════════════════════════════════════════════════════════════

def test_registering_an_already_enrolled_facility_is_refused(api):
    """PRD §3.1: "Registration is the act that turns a pending facility into
    an enrolled one, and it is deliberately hard."
    PRD §2.11: "every action endpoint refuses a target that is not in a state
    from which the requested transition is declared, with `ERR_INVALID_STATE`
    at HTTP 409"

    Design: Corner/state_machines/facility_register_from_already_enrolled_returns_invalid_state
    """
    scenario = setup_imaging_facility()
    before = read_facility(scenario.facility_id)
    assert before["facility_status"] == "ENROLLED"

    res = api_client.register_facility(
        scenario.facility_id, {"expected_facility_version": before["version"]}, scenario.admin
    )
    assert res.status_code == 409, f"Expected 409, got {res.status_code}: {res.text}"
    error = validate_error(res, "ERR_INVALID_STATE")
    assert error["error_id"] != "ERR_STALE_VERSION"

    after = read_facility(scenario.facility_id)
    assert after["facility_status"] == "ENROLLED"
    assert after["payer_participation_status"] == before["payer_participation_status"]
    assert after["enrolled_unit_count"] == 1
    assert after["deferred_unit_count"] == 0


def test_returning_equipment_to_service_requires_an_accepted_survey_of_its_unit(api):
    """PRD §3.1: "Returning an out-of-service item to service is gated on
    evidence that the problem was investigated: the owning unit must already
    have at least one physicist survey in `ACCEPTED` status whose `unit_id`
    equals that unit."

    Design: Corner/state_machines/equipment_return_to_service_is_gated_on_an_accepted_survey_of_the_unit
    """
    scenario = setup_imaging_facility()

    # A second unit with no accepted survey, and an item commissioned there.
    second_unit = validate_success(
        api_client.create_modality_unit(
            {
                "facility_id": scenario.facility_id,
                "modality_code": "MRI",
                "unit_label": "MR-2",
                "expected_facility_version": read_facility(scenario.facility_id)["version"],
            },
            scenario.admin,
        ),
        201,
    )
    second_equipment = validate_success(
        api_client.create_equipment(
            {
                "unit_id": second_unit["id"],
                "manufacturer": "GE",
                "model_number": "REV-A",
                "serial_number": "SN-MR-0002",
                "modality_code": "MRI",
                "installed_on": "2026-08-02T00:00:00Z",
            },
            scenario.admin,
        ),
        201,
    )
    validate_success(
        api_client.take_equipment_out_of_service(
            second_equipment["id"],
            {"expected_unit_version": read_unit(second_unit["id"])["version"]},
            scenario.admin,
        ),
        200,
    )

    res = api_client.return_equipment_to_service(
        second_equipment["id"],
        {"expected_unit_version": read_unit(second_unit["id"])["version"]},
        scenario.admin,
    )
    assert res.status_code == 409, f"Expected 409, got {res.status_code}: {res.text}"
    validate_error(res, "ERR_INVALID_STATE")

    unchanged = validate_success(api_client.get_equipment(second_equipment["id"], READER), 200)
    assert unchanged["equipment_status"] == "OUT_OF_SERVICE"
    assert unchanged["performance_verdict"] == "PENDING"

    # The unit that does have an accepted survey keeps its own item ACTIVE.
    first = validate_success(api_client.get_equipment(scenario.equipment_id, READER), 200)
    assert first["equipment_status"] == "ACTIVE"


# ─── local helpers ────────────────────────────────────────────────────────

def _deficient_with_plan(scenario, category="POSITIONING"):
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
            {"review_outcome": "ACCEPT_WITH_DEFICIENCY", "reviewer_deficiency_category": category},
            REVIEWER,
        ),
        200,
    )
    return reviewed, read_plan(reviewed["corrective_action_plan_id"])


def _resubmit_a_deficiency(scenario):
    """File -> deficiency-review -> resubmit. Returns (fresh, parent) submissions."""
    reviewed, _ = _deficient_with_plan(scenario)
    fresh = validate_success(
        api_client.resubmit_clinical_image_submission(
            reviewed["id"],
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
    return fresh, reviewed