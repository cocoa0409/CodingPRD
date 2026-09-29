"""One entity's state gates a write on another, with the body held constant."""

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN_HEADERS,
    SCHEDULER_HEADERS,
    TRAINER_HEADERS,
    USER_REVIEWER,
    make_producer_headers,
)


# ---------------------------------------------------------------------------
# A playback slot depends on its program having reached APPROVED
# ---------------------------------------------------------------------------
def _submitted_program_awaiting_a_reviewer(client):
    producer = fx.setup_basic_certified_producer(
        client, score=88, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    channel = fx.create_channel(client, call_sign="PATV1")
    program = fx.setup_cleared_program(
        client, producer["id"], title="Neighborhood Notes",
        runtime_seconds=1800, is_live=False, required_crew_roles=[],
    )
    submitted = fx.submit_program(client, program["id"], producer["id"])
    return channel, program, submitted


def test_booking_airtime_is_refused_while_the_program_is_only_submitted(client):
    """A fully valid slot body still fails on the program's review state.

    PRD 3.4: "Its `review_status` must be `APPROVED`, otherwise
    `ERR_PROGRAM_NOT_APPROVED` (409), and this state check runs ahead of every
    window and conflict check on the same request — a slot request that is both
    for an unapproved program and in a full window reports the approval failure."

    PRD 3.4: "A new channel opens with `scheduled_seconds` at 0, `aired_seconds`
    at 0 and `slot_sequence_high` at 0."

    Design: Difficulty/cross_entity_state_dependency/slot_creation_blocked_until_program_reaches_approved
    """
    channel, program, submitted = _submitted_program_awaiting_a_reviewer(client)
    assert submitted["review_status"] == "SUBMITTED"
    assert submitted["clearance_status"] == "CLEARED"

    response = client.create_playback_slot(
        f.playback_slot_payload(channel["id"], program["id"], "2026-08-20T18:00:00Z"),
        SCHEDULER_HEADERS,
    )

    a.error_of(response, e.ERR_PROGRAM_NOT_APPROVED, 409)
    listed = a.data_of(client.list_playback_slots(SCHEDULER_HEADERS, {"channel_id": channel["id"]}))
    assert listed == []
    untouched = fx.read_channel(client, channel["id"])
    a.assert_channel_ledger(untouched, 0, 0)
    assert untouched["slot_sequence_high"] == 0


def test_the_identical_booking_succeeds_once_a_reviewer_approves_the_program(client):
    """Nothing about the slot request changes; only the program's state does.

    PRD 3.3: "`UNDER_REVIEW → APPROVED` clears both `finding_category` and
    `finding_notes` back to null and increments the program's `version` by 1;
    nothing else moves, and the program is now bookable for airtime."

    PRD 3.4: "`occupied_seconds` is the program's `runtime_seconds` plus the
    channel's `inter_program_buffer_seconds`, and it is frozen on the slot at
    creation so that a later change to either input cannot retroactively move the
    schedule."

    PRD 3.4: "Its `booking_type` becomes `SERIES_HOLD` when a `series_id` was
    supplied, in which case that series' `remaining_hold_slots` falls by 1;
    otherwise `booking_type` is `FIRST_COME`."

    Design: Difficulty/cross_entity_state_dependency/slot_creation_blocked_until_program_reaches_approved
    """
    channel, program, _submitted = _submitted_program_awaiting_a_reviewer(client)
    payload = f.playback_slot_payload(channel["id"], program["id"], "2026-08-20T18:00:00Z")
    a.error_of(
        client.create_playback_slot(payload, SCHEDULER_HEADERS),
        e.ERR_PROGRAM_NOT_APPROVED,
        409,
    )

    fx.claim_review(client, program["id"])
    approved = fx.approve_program(client, program["id"])
    assert approved["review_status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == USER_REVIEWER

    slot = a.created_of(client.create_playback_slot(payload, SCHEDULER_HEADERS))

    assert slot["status"] == "SCHEDULED"
    assert slot["booking_type"] == "FIRST_COME"
    assert slot["occupied_seconds"] == 1920
    a.assert_instant_equals(slot["end_at"], "2026-08-20T18:32:00Z", "end_at")
    assert slot["staffing_status"] == "NOT_REQUIRED"
    a.assert_channel_ledger(fx.read_channel(client, channel["id"]), 1920, 0)


# ---------------------------------------------------------------------------
# An enrollment depends on its producer having left APPLICANT
# ---------------------------------------------------------------------------
def _applicant_and_an_open_basic_course(client):
    producer = fx.register_producer(
        client, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    course = fx.publish_course(
        client, tier="BASIC", grants_competency_codes=["STUDIO_FLOOR", "EDIT_SUITE"],
        seat_capacity=12, session_start_at="2026-08-05T17:00:00Z",
        session_end_at="2026-08-05T21:00:00Z",
    )
    return producer, course


def test_enrolling_is_refused_while_the_producer_is_still_an_applicant(client):
    """The seat is not consumed by a refused enrollment.

    PRD 3.1: "Four business rules guard enrollment beyond the ownership check,
    and they are evaluated in this order: the owning producer must be `ACTIVE`,
    otherwise `ERR_PRODUCER_NOT_ACTIVE` (409); the tier prerequisite must be
    satisfied, otherwise `ERR_PREREQUISITE_NOT_MET` (422); a seat must remain,
    otherwise `ERR_COURSE_FULL` (409)"

    PRD 3.1: "A freshly registered producer sits in `APPLICANT` status with
    `residency_verified` false, `certification_level` `NONE`, an empty
    `competency_codes` list, `suspension_points` at 0, `reinstated_count` at 0, a
    null `indemnification_expires_at`, a null `revocation_reason`, and every
    derived money and volunteer counter — `deposit_held_cents`,
    `deposit_forfeited_total_cents`, `volunteer_hours_tenths` and
    `confirmed_crew_commitments` — at 0."

    Design: Difficulty/cross_entity_state_dependency/enrollment_blocked_until_producer_leaves_applicant
    """
    producer, course = _applicant_and_an_open_basic_course(client)
    assert producer["status"] == "APPLICANT"
    assert producer["certification_level"] == "NONE"
    assert producer["residency_verified"] is False

    response = client.create_course_enrollment(
        f.enrollment_payload(producer["id"], course["id"]),
        make_producer_headers(producer["id"]),
    )

    a.error_of(response, e.ERR_PRODUCER_NOT_ACTIVE, 409)
    unchanged = a.data_of(client.get_training_course(course["id"], TRAINER_HEADERS))
    assert unchanged["enrolled_count"] == 0
    assert unchanged["passed_count"] == 0
    listed = a.data_of(
        client.list_course_enrollments(TRAINER_HEADERS, {"producer_id": producer["id"]})
    )
    assert listed == []


def test_the_identical_enrollment_succeeds_once_residency_is_verified(client):
    """Admission alone unblocks the seat, and it grants no competency.

    PRD 3.1: "On success `residency_verified` becomes true,
    `certification_level` is re-derived, and the producer's `version` increments
    by 1. Re-derivation at this point leaves the level at `NONE`, because
    admission is not training: nothing about a residency document grants
    equipment competency."

    PRD 3.1: "A successful enrollment is created in `ENROLLED` status with a null
    `practical_score`, a null `attended_at` and a null `graded_at`, and it raises
    the course's `enrolled_count` by 1."

    Design: Difficulty/cross_entity_state_dependency/enrollment_blocked_until_producer_leaves_applicant
    """
    producer, course = _applicant_and_an_open_basic_course(client)
    payload = f.enrollment_payload(producer["id"], course["id"])
    a.error_of(
        client.create_course_enrollment(payload, make_producer_headers(producer["id"])),
        e.ERR_PRODUCER_NOT_ACTIVE,
        409,
    )

    activated = a.data_of(
        client.verify_residency(
            producer["id"], f.residency_payload(document_reference="UTIL-2026-0001"), ADMIN_HEADERS
        )
    )
    assert activated["status"] == "ACTIVE"
    assert activated["residency_verified"] is True

    enrollment = a.created_of(
        client.create_course_enrollment(payload, make_producer_headers(producer["id"]))
    )

    assert enrollment["status"] == "ENROLLED"
    assert enrollment["producer_id"] == producer["id"]
    assert enrollment["course_id"] == course["id"]
    a.assert_field_absent_or_null(enrollment, "practical_score")
    a.assert_field_absent_or_null(enrollment, "graded_at")
    a.assert_field_absent_or_null(enrollment, "attended_at")

    after = a.data_of(client.get_training_course(course["id"], TRAINER_HEADERS))
    assert after["enrolled_count"] == 1
    assert after["passed_count"] == 0
    assert fx.read_producer(client, producer["id"])["certification_level"] == "NONE"
