"""
Writes whose legality is decided by the state of a different row.

A placement depends on the employer partnership's ladder position and on the
participant's licence-relief dimension; an enrollment depends on the
participant's suspension dimension. In each case the refusal is lifted only by
moving the other entity, and the retried call is then expected to land in full.
"""

from test_helpers.api_errors import (
    ERR_LICENSE_RELIEF_REQUIRED,
    ERR_PARTICIPANT_SUSPENDED,
    ERR_PARTNERSHIP_NOT_ACTIVE,
)
from test_helpers.assertions import (
    assert_int_field,
    assert_opening_seat_identity,
    assert_session_seat_identity,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import (
    EMPLOYMENT_OFFERED,
    ENROLLMENT_ENROLLED,
    LICENSE_RELIEF_NONE,
    LICENSE_RELIEF_PETITION_SUBMITTED,
    LICENSE_RELIEF_RELIEF_GRANTED,
    OPENING_OPEN,
    PARTNERSHIP_ACTIVE,
    PARTNERSHIP_ENGAGED,
    POSTURE_OPEN,
    SESSION_SCHEDULED,
    SESSION_TYPE_INTERVIEW_PRACTICE,
    STAGE_POST_RELEASE,
    SUSPENSION_LIFTED,
    SUSPENSION_NONE,
    SUSPENSION_SUSPENDED,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    EMPLOYER_LIAISON,
    PROGRAM_DIRECTOR,
)

LICENSED_OCCUPATION_CODE = "31-1131"


def _opening_under_an_engaged_partnership(api, build):
    """An opening posted by a partnership that has not yet opened for business."""
    grant = build.grant(authorized_cents=5000000, per_participant_cap_cents=60000)
    participant = build.participant_released()
    partnership = build.partnership(wotc_certified=True, excluded_record_categories=[])
    validate_unpaginated(
        api.record_bonding_agreement(
            partnership["id"], f.bonding_agreement_payload(500000, "2026-08-01"), EMPLOYER_LIAISON
        )
    )
    engaged = validate_unpaginated(
        api.set_partnership_status(
            partnership["id"],
            f.partnership_status_payload(PARTNERSHIP_ENGAGED),
            EMPLOYER_LIAISON,
        )
    )
    assert engaged["status"] == PARTNERSHIP_ENGAGED
    opening = build.job_opening(partnership["id"])
    return grant, participant, partnership, opening


def _apply(api, build, participant_id, opening_id, grant_id):
    payload = f.placement_payload(
        participant_id, opening_id, build.opening_version(opening_id), grant_id
    )
    return api.create_placement(payload, CASE_MANAGER)


def test_a_placement_against_an_engaged_partnership_is_refused(api, build):
    """
    An opening may be posted from `ENGAGED`, but placements against it wait for
    the partnership to reach `ACTIVE`.

    PRD section 3.4: "`ENGAGED → ACTIVE` opens the partnership for business, and
    only from `ACTIVE` may placements be created against its openings."

    Design: Difficulty/cross_entity_state_dependency/placement_creation_blocked_until_partnership_reaches_active
    """
    grant, participant, partnership, opening = _opening_under_an_engaged_partnership(
        api, build
    )

    refused = _apply(api, build, participant["id"], opening["id"], grant["id"])
    validate_error(refused, ERR_PARTNERSHIP_NOT_ACTIVE, 409)

    rows, meta = validate_paginated(
        api.list_placements(CASE_MANAGER, f.page_params(job_opening_id=opening["id"]))
    )
    assert meta["total_count"] == 0


def test_activating_the_partnership_unblocks_the_same_placement(api, build):
    """
    Once the partnership reaches `ACTIVE` the identical call is accepted, scored,
    and takes a seat on the opening.

    PRD section 3.6: "Then a job opening whose employer partnership has a `status`
    other than `ACTIVE` is refused with `ERR_PARTNERSHIP_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/placement_creation_blocked_until_partnership_reaches_active
    """
    grant, participant, partnership, opening = _opening_under_an_engaged_partnership(
        api, build
    )
    validate_error(
        _apply(api, build, participant["id"], opening["id"], grant["id"]),
        ERR_PARTNERSHIP_NOT_ACTIVE,
        409,
    )

    activated = validate_unpaginated(
        api.set_partnership_status(
            partnership["id"],
            f.partnership_status_payload(PARTNERSHIP_ACTIVE),
            EMPLOYER_LIAISON,
        )
    )
    assert activated["status"] == PARTNERSHIP_ACTIVE

    placement = validate_unpaginated(
        _apply(api, build, participant["id"], opening["id"], grant["id"]), 201
    )
    assert placement["employment_status"] == EMPLOYMENT_OFFERED
    assert_int_field(placement, "match_score", 75)
    assert placement["match_breakdown"]["access_component"] == 15

    stored_opening = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert_int_field(stored_opening, "offered_count", 1)
    assert_int_field(stored_opening, "remaining_openings", 1)
    assert stored_opening["status"] == OPENING_OPEN
    assert_opening_seat_identity(stored_opening)

    rows, meta = validate_paginated(
        api.list_placements(CASE_MANAGER, f.page_params(job_opening_id=opening["id"]))
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == placement["id"]

    stored_partnership = validate_unpaginated(
        api.get_partnership(partnership["id"], EMPLOYER_LIAISON)
    )
    assert_int_field(stored_partnership, "active_placement_count", 0)


def _licensed_opening_and_unlicensed_participant(api, build):
    """An opening that demands occupational-licence relief the participant lacks."""
    grant = build.grant(authorized_cents=5000000, per_participant_cap_cents=60000)
    participant = build.participant_released()
    partnership = build.partnership_active()
    opening = build.job_opening(
        partnership["id"],
        title="Nursing Assistant",
        occupation_code=LICENSED_OCCUPATION_CODE,
        requires_license=True,
        license_occupation_code=LICENSED_OCCUPATION_CODE,
    )
    assert participant["license_relief_status"] == LICENSE_RELIEF_NONE
    return grant, participant, opening


def test_a_licensed_opening_refuses_a_participant_whose_petition_is_still_pending(
    api, build
):
    """
    A submitted petition is not granted relief, so the refusal survives the first
    licence-relief move.

    PRD section 3.6: "Then licensing: when the opening's `requires_license` is
    true, the placement proceeds only if the participant's `license_relief_status`
    is `RELIEF_GRANTED` **and** the participant's `license_relief_occupation_code`
    equals the opening's `license_occupation_code`; a participant without granted
    relief, or with relief granted for a different occupation code, is refused with
    `ERR_LICENSE_RELIEF_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/licensed_opening_requires_participant_license_relief_granted
    """
    grant, participant, opening = _licensed_opening_and_unlicensed_participant(api, build)

    validate_error(
        _apply(api, build, participant["id"], opening["id"], grant["id"]),
        ERR_LICENSE_RELIEF_REQUIRED,
        409,
    )

    petitioned = validate_unpaginated(
        api.drive_license_relief(
            participant["id"],
            f.license_relief_payload(
                LICENSE_RELIEF_PETITION_SUBMITTED, LICENSED_OCCUPATION_CODE
            ),
            CASE_MANAGER,
        )
    )
    assert petitioned["license_relief_status"] == LICENSE_RELIEF_PETITION_SUBMITTED
    assert petitioned["license_relief_occupation_code"] == LICENSED_OCCUPATION_CODE

    validate_error(
        _apply(api, build, participant["id"], opening["id"], grant["id"]),
        ERR_LICENSE_RELIEF_REQUIRED,
        409,
    )


def test_granted_relief_for_the_matching_occupation_code_unblocks_the_placement(
    api, build
):
    """
    Relief granted for the opening's own occupation code is what the gate wants,
    and the third attempt lands.

    PRD section 3.9: "A `ProgramDirector` closes the petition favourably by driving
    `to_status` to `RELIEF_GRANTED` from `PETITION_SUBMITTED`, which is what makes
    placements on licence-gated openings whose `license_occupation_code` equals the
    participant's stored `license_relief_occupation_code` creatable at last, or
    unfavourably by driving `to_status` to `PETITION_DENIED` from
    `PETITION_SUBMITTED`, which pushes `engagement_posture` to `RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/licensed_opening_requires_participant_license_relief_granted
    """
    grant, participant, opening = _licensed_opening_and_unlicensed_participant(api, build)
    validate_error(
        _apply(api, build, participant["id"], opening["id"], grant["id"]),
        ERR_LICENSE_RELIEF_REQUIRED,
        409,
    )
    validate_unpaginated(
        api.drive_license_relief(
            participant["id"],
            f.license_relief_payload(
                LICENSE_RELIEF_PETITION_SUBMITTED, LICENSED_OCCUPATION_CODE
            ),
            CASE_MANAGER,
        )
    )
    granted = validate_unpaginated(
        api.drive_license_relief(
            participant["id"],
            f.license_relief_payload(LICENSE_RELIEF_RELIEF_GRANTED),
            PROGRAM_DIRECTOR,
        )
    )
    assert granted["license_relief_status"] == LICENSE_RELIEF_RELIEF_GRANTED
    assert granted["license_relief_occupation_code"] == LICENSED_OCCUPATION_CODE
    assert granted["stage"] == STAGE_POST_RELEASE

    placement = validate_unpaginated(
        _apply(api, build, participant["id"], opening["id"], grant["id"]), 201
    )
    assert placement["employment_status"] == EMPLOYMENT_OFFERED
    assert_int_field(placement, "match_score", 75)

    stored_opening = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert_int_field(stored_opening, "offered_count", 1)
    assert_int_field(stored_opening, "remaining_openings", 1)
    assert_opening_seat_identity(stored_opening)

    rows, meta = validate_paginated(
        api.list_placements(CASE_MANAGER, f.page_params(job_opening_id=opening["id"]))
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == placement["id"]


def _suspended_participant_and_a_scheduled_session(api, build):
    """A suspended participant and a session that has not started."""
    participant = build.participant()
    session = build.readiness_session(
        session_type=SESSION_TYPE_INTERVIEW_PRACTICE,
        starts_at="2026-08-03T13:00:00.000Z",
        ends_at="2026-08-03T15:00:00.000Z",
        seat_capacity=3,
    )
    suspended = validate_unpaginated(
        api.set_suspension(
            participant["id"],
            f.suspension_payload(SUSPENSION_SUSPENDED, "Missed two supervision appointments"),
            PROGRAM_DIRECTOR,
        )
    )
    assert suspended["suspension_status"] == SUSPENSION_SUSPENDED
    return participant, session


def test_a_suspended_participant_cannot_take_a_readiness_seat(api, build):
    """
    The suspension gate fires ahead of the seat arithmetic, and the refused
    enrollment consumes nothing.

    PRD section 3.5: "Five gates guard it, and they fire in precedence order: the
    session's own state must be `SCHEDULED`, else `ERR_SESSION_INVALID_STATE`; the
    participant must not have `suspension_status` of `SUSPENDED`, else
    `ERR_PARTICIPANT_SUSPENDED`; the session's `starts_at` must be strictly later
    than the logical clock, so a session whose `starts_at` is at or before the
    current instant is refused with `ERR_SESSION_ALREADY_STARTED`;
    `remaining_seats` must be greater than 0, else `ERR_SESSION_FULL`; and the
    participant must not already hold an enrollment on this same session whose
    `status` is `ENROLLED`, `ATTENDED`, or `NO_SHOW`, else
    `ERR_DUPLICATE_ENROLLMENT`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_blocked_while_participant_suspended
    """
    participant, session = _suspended_participant_and_a_scheduled_session(api, build)

    refused = api.create_enrollment(
        session["id"], f.enrollment_payload(participant["id"], True), CASE_MANAGER
    )
    validate_error(refused, ERR_PARTICIPANT_SUSPENDED, 409)

    stored = validate_unpaginated(api.get_readiness_session(session["id"], CASE_MANAGER))
    assert stored["status"] == SESSION_SCHEDULED
    assert_int_field(stored, "enrolled_count", 0)
    assert_int_field(stored, "remaining_seats", 3)
    assert_session_seat_identity(stored)


def test_lifting_the_suspension_lets_the_same_enrollment_through(api, build):
    """
    Re-enrollment after a lift is a fresh act, and it takes one of the three seats.

    PRD section 3.9: "Driving `to_status` to `LIFTED` requires that
    `suspension_status` is currently `SUSPENDED`; it clears `suspension_reason`
    back to null and recomputes `engagement_posture` to `OPEN` or `RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_blocked_while_participant_suspended
    """
    participant, session = _suspended_participant_and_a_scheduled_session(api, build)
    validate_error(
        api.create_enrollment(
            session["id"], f.enrollment_payload(participant["id"], True), CASE_MANAGER
        ),
        ERR_PARTICIPANT_SUSPENDED,
        409,
    )

    lifted = validate_unpaginated(
        api.set_suspension(
            participant["id"], f.suspension_payload(SUSPENSION_LIFTED), PROGRAM_DIRECTOR
        )
    )
    assert lifted["suspension_status"] == SUSPENSION_NONE
    assert lifted["suspension_reason"] is None
    assert lifted["engagement_posture"] == POSTURE_OPEN

    enrollment = validate_unpaginated(
        api.create_enrollment(
            session["id"], f.enrollment_payload(participant["id"], True), CASE_MANAGER
        ),
        201,
    )
    assert enrollment["status"] == ENROLLMENT_ENROLLED
    assert enrollment["disclosure_script_reviewed"] is True
    assert enrollment["participant_id"] == participant["id"]

    stored = validate_unpaginated(api.get_readiness_session(session["id"], CASE_MANAGER))
    assert_int_field(stored, "enrolled_count", 1)
    assert_int_field(stored, "remaining_seats", 2)
    assert_session_seat_identity(stored)

    rows, meta = validate_paginated(
        api.list_session_enrollments(session["id"], CASE_MANAGER)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == enrollment["id"]
