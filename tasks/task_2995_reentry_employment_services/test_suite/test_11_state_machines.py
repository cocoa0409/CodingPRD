"""
Transition legality, the cascades a legal transition drags behind it, and the
refusals an undeclared pair earns.

Each dimension is exercised where it is interesting: at its birth, along a legal
walk, at a terminal wall, at a round limit, and at the point where one row's
transition reconciles rows two levels below it.
"""

from test_helpers.api_errors import (
    ERR_PARTICIPANT_INVALID_STATE,
    ERR_PETITION_ROUNDS_EXHAUSTED,
    ERR_SUPPORT_REQUEST_INVALID_STATE,
)
from test_helpers.assertions import (
    assert_all_null,
    assert_common_fields,
    assert_int_field,
    assert_money_cents,
    assert_one_decimal_place,
    assert_opening_seat_identity,
    assert_session_seat_identity,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import (
    CASE_PENDING_CONTACT,
    CATEGORY_ID_FEE,
    COMPLIANCE_COMPLIANT,
    DOC_BIRTH_CERTIFICATE,
    DOC_SSN_CARD,
    DOC_STATE_ID,
    DOC_WORK_HISTORY,
    EMPLOYMENT_DECLINED,
    EMPLOYMENT_OFFERED,
    ENROLLMENT_ATTENDED,
    ENROLLMENT_NO_SHOW,
    ENROLLMENT_WITHDRAWN,
    EXIT_DISENGAGED,
    FUNDING_POSTURE_OPEN,
    LICENSE_RELIEF_INFO_REQUESTED,
    LICENSE_RELIEF_PETITION_SUBMITTED,
    OFFER_RESPONSE_DECLINED,
    OPENING_CLOSED,
    OPENING_FILLED,
    OPENING_OPEN,
    PARTNERSHIP_ACTIVE,
    PARTNERSHIP_ENGAGED,
    PARTNERSHIP_TERMINATED,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    RECORD_DRUG_OFFENSE,
    RECORD_DUI,
    RELEASE_PLAN_APPROVED,
    RELEASE_PLAN_DRAFT,
    REQUEST_DISBURSED,
    REQUEST_SUBMITTED,
    SESSION_HELD,
    SESSION_TYPE_DISCLOSURE_COACHING,
    SESSION_TYPE_INTERVIEW_PRACTICE,
    SHIFT_SCHEDULED,
    STAGE_EXITED,
    STAGE_POST_RELEASE,
    STAGE_PRE_RELEASE,
    STAGE_RELEASE_READY,
    SUPERVISION_PAROLE,
    SUSPENSION_NONE,
    SUSPENSION_SUSPENDED,
    WORK_AUTH_APPROVED,
    WORK_AUTH_NOT_REQUESTED,
    WORK_AUTH_SUSPENDED,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    EMPLOYER_LIAISON,
    FUNDER_ANALYST,
    PROGRAM_DIRECTOR,
    SUPERVISION_OFFICER,
    SUPERVISION_OFFICER_ID,
    participant_headers,
)

FOUR_VERIFIED_TYPES = [DOC_STATE_ID, DOC_SSN_CARD, DOC_BIRTH_CERTIFICATE, DOC_WORK_HISTORY]
SUSPENSION_REASON = "Missed two supervision appointments"


def test_a_new_supervision_case_is_born_in_both_dimensions_at_once(api, build):
    """
    The case's own lifecycle and its work-authorisation dimension each start at
    their own initial value, with no window stored and no decision counted.

    PRD section 3.3: "A new case is born with `status` of `PENDING_CONTACT`,
    `work_authorization_status` of `NOT_REQUESTED`, `authorization_change_count` of
    0, and both `approved_window_start_minute` and `approved_window_end_minute`
    null."

    Design: Corner/state_machines/supervision_case_starts_pending_contact_with_authorization_not_requested
    """
    participant = build.participant()

    case = validate_unpaginated(
        api.create_supervision_case(
            f.supervision_case_payload(participant["id"], SUPERVISION_OFFICER_ID),
            SUPERVISION_OFFICER,
        ),
        201,
    )
    assert case["status"] == CASE_PENDING_CONTACT
    assert case["work_authorization_status"] == WORK_AUTH_NOT_REQUESTED
    assert_all_null(
        case, ["approved_window_start_minute", "approved_window_end_minute"]
    )
    assert_int_field(case, "authorization_change_count", 0)
    assert case["officer_user_id"] == SUPERVISION_OFFICER_ID
    assert case["participant_id"] == participant["id"]
    assert case["supervision_type"] == SUPERVISION_PAROLE
    assert_common_fields(case, 1)


def test_a_partnership_walks_prospect_to_engaged_to_active_one_hop_at_a_time(
    api, build
):
    """
    Both hops are mutations, so the row's `version` reaches exactly three: one for
    the create and one for each accepted transition.

    PRD section 3.4: "Partnership development walks a short ladder driven by
    `to_status`. `PROSPECT → ENGAGED` records first substantive contact. `ENGAGED →
    ACTIVE` opens the partnership for business, and only from `ACTIVE` may placements
    be created against its openings."

    Design: Corner/state_machines/partnership_walks_prospect_to_engaged_to_active
    """
    partnership = build.partnership(wotc_certified=True, excluded_record_categories=[])

    engaged = validate_unpaginated(
        api.set_partnership_status(
            partnership["id"],
            f.partnership_status_payload(PARTNERSHIP_ENGAGED),
            EMPLOYER_LIAISON,
        )
    )
    assert engaged["status"] == PARTNERSHIP_ENGAGED
    assert_common_fields(engaged, 2)
    assert_int_field(engaged, "active_placement_count", 0)

    active = validate_unpaginated(
        api.set_partnership_status(
            partnership["id"],
            f.partnership_status_payload(PARTNERSHIP_ACTIVE),
            EMPLOYER_LIAISON,
        )
    )
    assert active["status"] == PARTNERSHIP_ACTIVE
    assert_common_fields(active, 3)
    assert_int_field(active, "active_placement_count", 0)

    rows, meta = validate_paginated(
        api.list_partnerships(
            EMPLOYER_LIAISON, f.page_params(status=PARTNERSHIP_ACTIVE)
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == partnership["id"]


def test_release_is_refused_while_the_plan_is_still_a_draft(api, build):
    """
    Documentation at the inclusive boundary and a recorded barrier score are not
    enough on their own: without an approved plan the participant never reached
    `RELEASE_READY`, so the release write has no legal source state.

    PRD section 3.2: "The transition additionally requires that `stage` is
    `RELEASE_READY` and `suspension_status` is `NONE`; a suspended participant, or
    one still in `PRE_RELEASE`, is refused with `ERR_PARTICIPANT_INVALID_STATE`."

    Design: Corner/state_machines/release_without_an_approved_plan_is_rejected
    """
    participant = build.participant_assessed()
    build.verify_documents(participant["id"], FOUR_VERIFIED_TYPES)
    drafted = build.release_plan_draft(participant["id"])
    assert drafted["release_plan_status"] == RELEASE_PLAN_DRAFT

    refused = api.record_release(
        participant["id"], f.release_payload("2026-08-01"), CASE_MANAGER
    )
    validate_error(refused, ERR_PARTICIPANT_INVALID_STATE, 409)

    stored = validate_unpaginated(api.get_participant(participant["id"], CASE_MANAGER))
    assert stored["stage"] == STAGE_PRE_RELEASE
    assert stored["release_plan_status"] == RELEASE_PLAN_DRAFT
    assert stored["actual_release_date"] is None

    summary = validate_unpaginated(
        api.get_readiness_summary(participant["id"], CASE_MANAGER)
    )
    assert_one_decimal_place(summary, "doc_completeness_pct", 80.0)
    assert summary["readiness_met"] is False
    assert summary["release_plan_status"] == RELEASE_PLAN_DRAFT


def test_terminating_a_partnership_closes_its_openings_and_declines_their_offers(
    api, build
):
    """
    One transition on the parent reconciles two levels below it: the opening closes
    and its unanswered offer is declined, and the declined seat comes back to the
    counters even though the opening itself is shut.

    PRD section 3.4: "Every job opening of the partnership whose `status` is `OPEN`
    or `FILLED` moves to `CLOSED`. Because those openings closed, every placement on
    them whose `employment_status` is `OFFERED` moves to `DECLINED`, which decrements
    that opening's `offered_count` and raises its `remaining_openings`."

    Design: Corner/state_machines/partnership_termination_closes_openings_and_declines_offers
    """
    grant = build.grant(authorized_cents=30000, per_participant_cap_cents=60000)
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"], openings_count=2)
    participant = build.participant_released()
    build.case_authorized(participant["id"])
    placement = build.placement_offered(participant["id"], opening["id"], grant["id"])
    assert placement["employment_status"] == EMPLOYMENT_OFFERED

    terminated = validate_unpaginated(
        api.set_partnership_status(
            partnership["id"],
            f.partnership_status_payload(PARTNERSHIP_TERMINATED),
            EMPLOYER_LIAISON,
        )
    )
    assert terminated["status"] == PARTNERSHIP_TERMINATED
    assert_int_field(terminated, "active_placement_count", 0)

    closed = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert closed["status"] == OPENING_CLOSED
    assert_int_field(closed, "offered_count", 0)
    assert_int_field(closed, "filled_count", 0)
    assert_int_field(closed, "remaining_openings", 2)
    assert_opening_seat_identity(closed)

    declined = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert declined["employment_status"] == EMPLOYMENT_DECLINED

    stored_participant = validate_unpaginated(
        api.get_participant(participant["id"], CASE_MANAGER)
    )
    assert stored_participant["stage"] == STAGE_POST_RELEASE


def test_settling_a_still_submitted_request_is_an_undeclared_pair(api, build):
    """
    Settlement is only reachable from `APPROVED` or `DEFERRED`, so a disbursement
    driven straight off `SUBMITTED` is refused and no money moves.

    PRD section 3.8: "`APPROVED → DISBURSED` pays the money out:
    `settled_by_user_id` and `settlement_note` are recorded, `committed_cents` falls
    by `total_charge_cents` and `disbursed_cents` rises by the same amount, so
    `available_cents` and `funding_posture` are unchanged in value by this move."

    PRD section 2.8: "A request that names a target state is legal only when the pair
    formed by the entity's current value in that dimension and the requested target is
    a declared transition of that dimension's graph."

    Design: Corner/state_machines/settling_a_submitted_support_request_returns_invalid_state
    """
    grant = build.grant(authorized_cents=100000, per_participant_cap_cents=60000)
    participant = build.participant_zero_barrier_draft(
        record_categories=[RECORD_DRUG_OFFENSE]
    )
    request = build.support_request(
        participant["id"],
        grant["id"],
        [f.line_item("State ID replacement fee", 8000)],
        category=CATEGORY_ID_FEE,
        justification="State ID required before employment",
    )
    assert request["status"] == REQUEST_SUBMITTED

    refused = api.settle_support_request(
        request["id"], f.settle_payload(REQUEST_DISBURSED), PROGRAM_DIRECTOR
    )
    validate_error(refused, ERR_SUPPORT_REQUEST_INVALID_STATE, 409)

    stored = validate_unpaginated(api.get_support_request(request["id"], CASE_MANAGER))
    assert stored["status"] == REQUEST_SUBMITTED
    assert stored["settled_by_user_id"] is None
    assert_common_fields(stored, 1)

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 0)
    assert_money_cents(ledger, "disbursed_cents", 0)
    assert_money_cents(ledger, "available_cents", 100000)
    assert_int_field(ledger, "open_request_count", 1)


def test_an_exited_participant_cannot_be_suspended(api, build):
    """
    The terminal stage freezes the suspension dimension too, even though suspension
    itself is still sitting at its own initial value.

    PRD section 3.9: "Attempting to suspend an exited participant is refused with
    `ERR_PARTICIPANT_INVALID_STATE`, and so is any suspension or lift that is not one
    of the two declared edges."

    PRD section 3.9: "Exit from any of the four permitted stages runs an identical
    cascade: `stage` becomes `EXITED`, `exit_reason` and `exit_date` are recorded, and
    `engagement_posture` becomes `FROZEN`"

    Design: Corner/state_machines/an_exited_participant_cannot_be_suspended
    """
    participant = build.participant()
    exited = validate_unpaginated(
        api.exit_participant(
            participant["id"],
            f.exit_payload(EXIT_DISENGAGED, "2026-08-01"),
            PROGRAM_DIRECTOR,
        )
    )
    assert exited["stage"] == STAGE_EXITED

    refused = api.set_suspension(
        participant["id"],
        f.suspension_payload(SUSPENSION_SUSPENDED, SUSPENSION_REASON),
        PROGRAM_DIRECTOR,
    )
    validate_error(refused, ERR_PARTICIPANT_INVALID_STATE, 409)

    stored = validate_unpaginated(api.get_participant(participant["id"], CASE_MANAGER))
    assert stored["stage"] == STAGE_EXITED
    assert stored["suspension_status"] == SUSPENSION_NONE
    assert stored["suspension_reason"] is None
    assert stored["engagement_posture"] == POSTURE_FROZEN
    assert stored["exit_reason"] == EXIT_DISENGAGED


def test_approving_an_already_approved_plan_is_refused_and_bumps_nothing(api, build):
    """
    A second approval is not a harmless repeat: with the plan already `APPROVED`
    there is nothing to approve, and the revision counter must not move.

    PRD section 3.2: "Approval is only meaningful against a plan that exists and is
    not already approved: when `release_plan_status` is `NONE` or already `APPROVED`,
    approval is refused with `ERR_PARTICIPANT_INVALID_STATE`."

    Design: Corner/state_machines/approving_an_already_approved_release_plan_returns_invalid_state
    """
    participant = build.participant_assessed()
    build.verify_documents(participant["id"], FOUR_VERIFIED_TYPES)
    approved = build.release_plan_approved(participant["id"])
    assert approved["release_plan_status"] == RELEASE_PLAN_APPROVED
    assert approved["stage"] == STAGE_RELEASE_READY

    refused = api.approve_release_plan(participant["id"], PROGRAM_DIRECTOR)
    validate_error(refused, ERR_PARTICIPANT_INVALID_STATE, 409)

    stored = validate_unpaginated(api.get_participant(participant["id"], CASE_MANAGER))
    assert stored["release_plan_status"] == RELEASE_PLAN_APPROVED
    assert_int_field(stored, "release_plan_revision", 1)
    assert stored["stage"] == STAGE_RELEASE_READY

    summary = validate_unpaginated(
        api.get_readiness_summary(participant["id"], CASE_MANAGER)
    )
    assert summary["readiness_met"] is True


def test_a_third_petition_refiling_exhausts_the_rounds(api, build):
    """
    Only the cycle edge back out of `INFO_REQUESTED` counts a round, so the first
    submission is round zero and the third refiling is the one that fails, leaving
    the dimension parked where it was with the stored occupation code intact.

    PRD section 3.9: "The cycle edge returns `INFO_REQUESTED → PETITION_SUBMITTED`,
    requires that `petition_rounds_used` is strictly below two, and increments
    `petition_rounds_used` by exactly one — so the third re-submission is refused with
    `ERR_PETITION_ROUNDS_EXHAUSTED`."

    Design: Corner/state_machines/petition_refiling_beyond_two_rounds_is_rejected
    """
    participant = build.participant()
    validate_unpaginated(
        api.drive_license_relief(
            participant["id"],
            f.license_relief_payload(LICENSE_RELIEF_PETITION_SUBMITTED, "53-7062"),
            CASE_MANAGER,
        )
    )
    for _round in range(2):
        validate_unpaginated(
            api.drive_license_relief(
                participant["id"],
                f.license_relief_payload(LICENSE_RELIEF_INFO_REQUESTED),
                CASE_MANAGER,
            )
        )
        validate_unpaginated(
            api.drive_license_relief(
                participant["id"],
                f.license_relief_payload(LICENSE_RELIEF_PETITION_SUBMITTED),
                CASE_MANAGER,
            )
        )
    parked = validate_unpaginated(
        api.drive_license_relief(
            participant["id"],
            f.license_relief_payload(LICENSE_RELIEF_INFO_REQUESTED),
            CASE_MANAGER,
        )
    )
    assert_int_field(parked, "petition_rounds_used", 2)

    refused = api.drive_license_relief(
        participant["id"],
        f.license_relief_payload(LICENSE_RELIEF_PETITION_SUBMITTED),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_PETITION_ROUNDS_EXHAUSTED, 409)

    stored = validate_unpaginated(api.get_participant(participant["id"], CASE_MANAGER))
    assert stored["license_relief_status"] == LICENSE_RELIEF_INFO_REQUESTED
    assert_int_field(stored, "petition_rounds_used", 2)
    assert stored["license_relief_occupation_code"] == "53-7062"
    assert stored["engagement_posture"] == POSTURE_OPEN


def test_holding_a_session_converts_only_the_still_enrolled_rows(api, build, clock):
    """
    The attendance sweep is conditional on each child's own state: the row already
    marked attended is left alone, the two still enrolled become no-shows, and the
    seat counters do not move at all because a no-show keeps its seat.

    PRD section 3.5: "Holding a session sweeps attendance: every enrollment on it
    still in `ENROLLED` moves to `NO_SHOW`, while `enrolled_count` and
    `remaining_seats` do not move at all, because a no-show enrollment still occupies
    the seat it consumed."

    Design: Corner/state_machines/holding_a_session_converts_only_enrolled_rows_to_no_show
    """
    first_participant = build.participant()
    second_participant = build.participant(
        full_name="Dana Whitfield", record_categories=[RECORD_DRUG_OFFENSE]
    )
    third_participant = build.participant(
        full_name="Alvin Peters", record_categories=[RECORD_DUI]
    )
    session = build.readiness_session(
        session_type=SESSION_TYPE_DISCLOSURE_COACHING,
        coach_user_id="coach-1",
        starts_at="2026-08-05T13:00:00.000Z",
        ends_at="2026-08-05T15:00:00.000Z",
        seat_capacity=3,
    )
    attended = build.enrollment(session["id"], first_participant["id"], True)
    second = build.enrollment(session["id"], second_participant["id"], False)
    third = build.enrollment(session["id"], third_participant["id"], False)

    clock.set("2026-08-05T14:00:00.000Z")
    validate_unpaginated(
        api.set_enrollment_status(
            attended["id"], f.enrollment_status_payload(ENROLLMENT_ATTENDED), CASE_MANAGER
        )
    )
    clock.set("2026-08-05T15:00:00.000Z")

    held = validate_unpaginated(
        api.set_session_status(
            session["id"], f.session_status_payload(SESSION_HELD), CASE_MANAGER
        )
    )
    assert held["status"] == SESSION_HELD
    assert_int_field(held, "enrolled_count", 3)
    assert_int_field(held, "remaining_seats", 0)
    assert_session_seat_identity(held)

    assert (
        validate_unpaginated(api.get_enrollment(attended["id"], CASE_MANAGER))["status"]
        == ENROLLMENT_ATTENDED
    )
    for enrollment in (second, third):
        assert (
            validate_unpaginated(api.get_enrollment(enrollment["id"], CASE_MANAGER))[
                "status"
            ]
            == ENROLLMENT_NO_SHOW
        )

    rows, meta = validate_paginated(
        api.list_session_enrollments(
            session["id"], CASE_MANAGER, f.page_params(status=ENROLLMENT_NO_SHOW)
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {second["id"], third["id"]}


def test_suspension_withdraws_only_the_enrolled_seat_on_the_scheduled_session(
    api, build, clock
):
    """
    The withdrawal cascade is doubly conditional — on the enrollment being still
    enrolled and on its session being still scheduled — so one session loses its seat
    while the attended row on the session already under way keeps its own.

    PRD section 3.9: "Driving `to_status` to `SUSPENDED` requires that the
    participant's `stage` is not `EXITED` and that `suspension_status` is currently
    `NONE`; it records the supplied `suspension_reason`, forces `engagement_posture` to
    `FROZEN`, and withdraws the participant from readiness training — every enrollment
    of this participant whose `status` is `ENROLLED` and whose session's `status` is
    `SCHEDULED` moves to `WITHDRAWN`, decrementing that session's `enrolled_count` and
    incrementing its `remaining_seats`."

    Design: Corner/state_machines/suspension_withdraws_only_the_still_enrolled_scheduled_seats
    """
    participant = build.participant()
    later_session = build.readiness_session(
        session_type=SESSION_TYPE_INTERVIEW_PRACTICE,
        coach_user_id="coach-1",
        starts_at="2026-08-06T13:00:00.000Z",
        ends_at="2026-08-06T15:00:00.000Z",
        seat_capacity=3,
    )
    earlier_session = build.readiness_session(
        session_type=SESSION_TYPE_DISCLOSURE_COACHING,
        coach_user_id="coach-1",
        starts_at="2026-08-05T13:00:00.000Z",
        ends_at="2026-08-05T15:00:00.000Z",
        seat_capacity=2,
    )
    later_enrollment = build.enrollment(later_session["id"], participant["id"], False)
    earlier_enrollment = build.enrollment(earlier_session["id"], participant["id"], True)

    clock.set("2026-08-05T14:00:00.000Z")
    validate_unpaginated(
        api.set_enrollment_status(
            earlier_enrollment["id"],
            f.enrollment_status_payload(ENROLLMENT_ATTENDED),
            CASE_MANAGER,
        )
    )

    suspended = validate_unpaginated(
        api.set_suspension(
            participant["id"],
            f.suspension_payload(SUSPENSION_SUSPENDED, SUSPENSION_REASON),
            PROGRAM_DIRECTOR,
        )
    )
    assert suspended["suspension_status"] == SUSPENSION_SUSPENDED
    assert suspended["suspension_reason"] == SUSPENSION_REASON
    assert suspended["engagement_posture"] == POSTURE_FROZEN

    assert (
        validate_unpaginated(api.get_enrollment(later_enrollment["id"], CASE_MANAGER))[
            "status"
        ]
        == ENROLLMENT_WITHDRAWN
    )
    assert (
        validate_unpaginated(api.get_enrollment(earlier_enrollment["id"], CASE_MANAGER))[
            "status"
        ]
        == ENROLLMENT_ATTENDED
    )

    emptied = validate_unpaginated(
        api.get_readiness_session(later_session["id"], CASE_MANAGER)
    )
    assert_int_field(emptied, "enrolled_count", 0)
    assert_int_field(emptied, "remaining_seats", 3)
    assert_session_seat_identity(emptied)

    kept = validate_unpaginated(
        api.get_readiness_session(earlier_session["id"], CASE_MANAGER)
    )
    assert_int_field(kept, "enrolled_count", 1)
    assert_int_field(kept, "remaining_seats", 1)
    assert_session_seat_identity(kept)


def test_restoring_authorisation_returns_the_conflicted_shifts_and_the_money(
    api, build
):
    """
    The restoration is the exact mirror of the suspension: both future shifts return
    to `SCHEDULED` with no conflict reason, the placement's projection climbs back to
    the full 11,100 cents, the ledger re-commits it, and the decision counter keeps
    counting rather than resetting.

    PRD section 3.3: "When authorisation moves `SUSPENDED → APPROVED`, every work
    shift that is currently `CONFLICTED`, whose `conflict_reason` is
    `WORK_AUTHORIZATION_SUSPENDED`, whose `starts_at` is later than the logical clock,
    and which belongs to an active placement of this participant returns to
    `SCHEDULED` with `conflict_reason` cleared to null — but only if that shift's
    minute-of-day span still lies inside the newly stored window."

    PRD section 3.3: "Every accepted decision increments `authorization_change_count`
    by exactly one, including a denial."

    Eight hours and four hours at 1850 cents an hour sit wholly inside the
    fifty-percent tier, which is 7,400 plus 3,700 cents.

    Design: Corner/state_machines/restoring_work_authorization_returns_conflicted_shifts_to_scheduled
    """
    grant = build.grant(authorized_cents=30000, per_participant_cap_cents=60000)
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"], openings_count=2)
    participant = build.participant_released()
    case = build.case_authorized(participant["id"], 480, 1020)
    placement = build.placement_active(participant["id"], opening["id"], grant["id"])
    first_shift = build.work_shift(
        placement["id"], "2026-08-03T09:00:00.000Z", "2026-08-03T17:00:00.000Z"
    )
    second_shift = build.work_shift(
        placement["id"], "2026-08-04T09:00:00.000Z", "2026-08-04T13:00:00.000Z"
    )
    assert first_shift["scheduled_hours"] == 8.0
    assert second_shift["scheduled_hours"] == 4.0
    validate_unpaginated(
        api.decide_work_authorization(
            case["id"],
            f.work_authorization_payload(WORK_AUTH_SUSPENDED),
            SUPERVISION_OFFICER,
        )
    )

    restored = validate_unpaginated(
        api.decide_work_authorization(
            case["id"],
            f.work_authorization_payload(WORK_AUTH_APPROVED, 480, 1020),
            SUPERVISION_OFFICER,
        )
    )
    assert restored["work_authorization_status"] == WORK_AUTH_APPROVED
    assert_int_field(restored, "approved_window_start_minute", 480)
    assert_int_field(restored, "approved_window_end_minute", 1020)
    assert_int_field(restored, "authorization_change_count", 3)

    for shift in (first_shift, second_shift):
        stored_shift = validate_unpaginated(api.get_work_shift(shift["id"], CASE_MANAGER))
        assert stored_shift["status"] == SHIFT_SCHEDULED
        assert stored_shift["conflict_reason"] is None

    stored_placement = validate_unpaginated(
        api.get_placement(placement["id"], CASE_MANAGER)
    )
    assert stored_placement["schedule_compliance"] == COMPLIANCE_COMPLIANT
    assert_money_cents(stored_placement, "projected_subsidy_cents", 11100)
    assert_money_cents(stored_placement, "actual_subsidy_cents", 0)

    stored_participant = validate_unpaginated(
        api.get_participant(participant["id"], CASE_MANAGER)
    )
    assert stored_participant["engagement_posture"] == POSTURE_OPEN

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 11100)
    assert_money_cents(ledger, "available_cents", 18900)
    assert ledger["funding_posture"] == FUNDING_POSTURE_OPEN


def test_an_opening_flips_to_filled_and_back_as_its_only_seat_is_taken_and_freed(
    api, build
):
    """
    The opening's own status is derived from its children in both directions: one
    outstanding offer on a one-seat posting fills it, the decline reopens it, and the
    freed seat is provably usable because a second placement is accepted on it.

    PRD section 3.4: "After any placement write that changes `offered_count` or
    `filled_count`, the server re-evaluates the opening: `OPEN → FILLED` when
    `remaining_openings` reaches 0, and `FILLED → OPEN` when `remaining_openings`
    becomes greater than 0 again because a placement left `OFFERED` or `ACTIVE` through
    a decline, a separation, or a termination cascade."

    PRD section 3.6: "Declining moves `employment_status` from `OFFERED` to
    `DECLINED`, which decrements the opening's `offered_count` and raises
    `remaining_openings`, possibly flipping the opening `FILLED → OPEN`."

    Design: Corner/state_machines/job_opening_flips_to_filled_when_seats_run_out_and_back_on_decline
    """
    grant = build.grant(authorized_cents=30000, per_participant_cap_cents=60000)
    partnership = build.partnership_active(max_concurrent_placements=2)
    opening = build.job_opening(partnership["id"], openings_count=1)
    first_participant = build.participant_released()
    second_participant = build.participant_released(
        full_name="Dana Whitfield", record_categories=[RECORD_DRUG_OFFENSE]
    )
    first = build.placement_offered(
        first_participant["id"], opening["id"], grant["id"]
    )

    filled = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert filled["status"] == OPENING_FILLED
    assert_int_field(filled, "remaining_openings", 0)

    declined = validate_unpaginated(
        api.respond_to_offer(
            first["id"],
            f.offer_response_payload(OFFER_RESPONSE_DECLINED),
            participant_headers(first_participant["id"]),
        )
    )
    assert declined["employment_status"] == EMPLOYMENT_DECLINED

    reopened = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert reopened["status"] == OPENING_OPEN
    assert_int_field(reopened, "offered_count", 0)
    assert_int_field(reopened, "filled_count", 0)
    assert_int_field(reopened, "remaining_openings", 1)
    assert_opening_seat_identity(reopened)

    second = validate_unpaginated(
        api.create_placement(
            f.placement_payload(
                second_participant["id"],
                opening["id"],
                build.opening_version(opening["id"]),
                grant["id"],
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert second["employment_status"] == EMPLOYMENT_OFFERED

    refilled = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert refilled["status"] == OPENING_FILLED
    assert_int_field(refilled, "offered_count", 1)
    assert_int_field(refilled, "remaining_openings", 0)
    assert_opening_seat_identity(refilled)

    rows, meta = validate_paginated(
        api.list_placements(CASE_MANAGER, f.page_params(job_opening_id=opening["id"]))
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
