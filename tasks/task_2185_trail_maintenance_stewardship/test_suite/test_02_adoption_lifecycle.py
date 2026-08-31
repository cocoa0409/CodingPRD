"""Adopting a segment: the draft/review/activate walk, its revision loop and its end."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_adoption_agreement,
    create_agreement,
    read_agreement,
    read_land_manager,
    read_segment,
    setup_active_adoption,
    setup_confirmed_party,
    setup_registry,
    submit_agreement,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _return_once(api, agreement_id, reason):
    return validate_success(
        api.review_adoption_agreement(
            agreement_id, {"decision": "RETURN", "reason": reason}, COORD
        )
    )


def test_return_and_resubmit_cycle_advances_revision_round_each_round(api):
    """PRD 3.2: "Returning the agreement moves it `SUBMITTED → RETURNED`, requires the `reason` to be a non-empty string, increments `revision_round` by 1 and records the acting `X-User-ID` as `reviewed_by_user_id`."
    PRD 3.2: "The crew leader may then resubmit, moving `RETURNED → SUBMITTED`, which re-checks that the segment is still `UNADOPTED`."

    Design: Difficulty/non_linear_state_machine/adoption_agreement_return_resubmit_cycle_hits_revision_limit
    """
    world = setup_registry()
    agreement = create_agreement(world["seg_id"], world["lead_id"])
    submit_agreement(agreement["id"], world["lead_id"])

    first = _return_once(api, agreement["id"], "Add a drainage inventory.")
    assert first["revision_round"] == 1
    assert first["status"] == "RETURNED"
    submit_agreement(agreement["id"], world["lead_id"])

    second = _return_once(api, agreement["id"], "Missing sawyer roster.")
    assert second["revision_round"] == 2
    submit_agreement(agreement["id"], world["lead_id"])

    third = _return_once(api, agreement["id"], "Term dates overlap the closure.")
    assert third["revision_round"] == 3

    third_resubmit = submit_agreement(agreement["id"], world["lead_id"])
    assert third_resubmit["status"] == "SUBMITTED", (
        "resubmission is permitted while revision_round is at most 3"
    )
    assert_adoption_agreement(third_resubmit)


def test_submission_at_revision_round_four_is_refused_by_the_revision_ceiling(api):
    """PRD 3.2: "That cycle — `SUBMITTED → RETURNED → SUBMITTED` — is bounded: resubmission is permitted only while `revision_round` is at most 3, so the fourth submit, attempted when `revision_round` has already reached 4, is refused with `ERR_REVISION_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/adoption_agreement_return_resubmit_cycle_hits_revision_limit
    """
    world = setup_registry()
    agreement = create_agreement(world["seg_id"], world["lead_id"])
    submit_agreement(agreement["id"], world["lead_id"])
    for reason in (
        "Add a drainage inventory.",
        "Missing sawyer roster.",
        "Term dates overlap the closure.",
    ):
        _return_once(api, agreement["id"], reason)
        submit_agreement(agreement["id"], world["lead_id"])
    fourth = _return_once(api, agreement["id"], "Still incomplete.")
    assert fourth["revision_round"] == 4

    response = api.submit_adoption_agreement(agreement["id"], world["lead_headers"])
    validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED.value, 422)

    stored = read_agreement(agreement["id"])
    assert stored["status"] == "RETURNED"
    assert stored["revision_round"] == 4


def test_new_agreement_starts_in_draft_and_cannot_be_activated_directly(api):
    """PRD 3.2: "The agreement is created in `DRAFT` with `revision_round` at 0 and `pinned_policy_version`, `reviewed_by_user_id`, `activated_at` and `suspension_reason` all null."
    PRD 3.2: "Activation is the land manager's countersignature and moves the agreement `APPROVED → ACTIVE`."
    PRD 2.7: "State legality — the target resource currently sits in a state from which the requested transition is declared, terminal states included, otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/adoption_agreement_starts_in_draft_and_cannot_be_activated_directly
    """
    world = setup_registry()
    agreement = create_agreement(world["seg_id"], world["lead_id"])
    assert agreement["status"] == "DRAFT"
    assert agreement["revision_round"] == 0
    assert agreement["pinned_policy_version"] is None

    response = api.activate_adoption_agreement(agreement["id"], world["lm_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    assert read_agreement(agreement["id"])["status"] == "DRAFT"
    assert read_segment(world["seg_id"])["adoption_status"] == "UNADOPTED"


def test_second_agreement_on_an_adopted_segment_is_refused_at_submission(api):
    """PRD 3.2: "The segment must not be sitting in `INCIDENT_CLOSED`, and its `adoption_status` must be `UNADOPTED` — an attempt to adopt a segment where another agreement already holds `ACTIVE` or `SUSPENDED` is refused with `ERR_SEGMENT_ALREADY_ADOPTED`."
    PRD 3.2: "Activation snapshots the agency's `policy_version` onto the agreement as `pinned_policy_version`, stamps `activated_at` with the logical clock, flips the segment's `adoption_status` to `ADOPTED`, and increments the agency's `adopted_segment_count` by 1."

    Design: Corner/validations/second_adoption_on_an_already_adopted_segment_is_rejected
    """
    world = setup_active_adoption()
    assert read_segment(world["seg_id"])["adoption_status"] == "ADOPTED"

    rival = create_agreement(world["seg_id"], world["lead_id"])
    response = api.submit_adoption_agreement(rival["id"], world["lead_headers"])
    validate_error(response, ApiErrorId.ERR_SEGMENT_ALREADY_ADOPTED.value, 409)

    assert read_agreement(rival["id"])["status"] == "DRAFT"
    assert read_land_manager(world["lm_id"])["adopted_segment_count"] == 1


def test_termination_cascade_is_visible_immediately_after_the_triggering_call(api):
    """PRD 3.2: "The agreement lands in `TERMINATED`, which is terminal."
    PRD 3.2: "The segment's `adoption_status` returns to `UNADOPTED` and the agency's `adopted_segment_count` drops by 1."
    PRD 3.2: "Every work plan under the agreement whose status is `APPROVED` moves to `CLOSED`."
    PRD 3.2: "And every work party under the agreement's plans whose `schedule_status` is `PLANNED`, `CONFIRMED` or `SUSPENDED` moves to `CANCELLED`, processed in `created_at` ascending order."

    Design: Corner/consistency_model/cascade_results_are_visible_in_the_triggering_response
    """
    world = setup_confirmed_party()
    assert world["party"]["schedule_status"] == "CONFIRMED"

    terminated = validate_success(
        api.terminate_adoption_agreement(
            world["agreement_id"],
            {"reason": "Segment transferred to another agency."},
            COORD,
        )
    )
    assert terminated["status"] == "TERMINATED", (
        "the terminate response body itself must already show TERMINATED"
    )

    assert validate_success(api.get_work_plan(world["plan_id"], COORD))["status"] == "CLOSED"
    party = validate_success(api.get_work_party(world["party_id"], COORD))
    assert party["schedule_status"] == "CANCELLED"
    segment = validate_success(api.get_trail_segment(world["seg_id"], COORD))
    assert segment["adoption_status"] == "UNADOPTED"
    assert read_land_manager(world["lm_id"])["adopted_segment_count"] == 0
