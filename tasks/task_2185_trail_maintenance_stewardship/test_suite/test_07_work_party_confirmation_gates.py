"""The confirmation gate, the segment interval rule, completion and cancellation."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_bridge_requisition,
    add_extra_party,
    add_signage_requisition,
    brief_party,
    create_party,
    create_report,
    disposition_report,
    read_agreement,
    read_party,
    read_permit,
    read_report,
    read_shift,
    read_volunteer,
    register_volunteer_on_party,
    setup_briefed_party,
    setup_confirmed_party,
    setup_issued_permit,
    setup_party_with_sawyer,
    setup_started_party,
    triage_report,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _suspended_adoption_with_out_of_window_party():
    """Party scheduled outside the permit window, under an adoption driven to SUSPENDED."""
    world = setup_issued_permit()
    party = create_party(
        world["plan_id"],
        world["seg_id"],
        world["lead_id"],
        world["permit_id"],
        start_at="2026-10-10T09:00:00.000Z",
        end_at="2026-10-10T15:00:00.000Z",
    )
    world["party_id"] = party["id"]
    brief_party(party["id"], world["lead_id"])
    add_bridge_requisition(world)
    add_signage_requisition(world)
    world["shift_saw"] = register_volunteer_on_party(
        party["id"], world["lead_id"], world["saw_id"], role_on_crew="SAWYER"
    )
    return world


def _three_parties_on_one_segment():
    """P1 confirmed 09:00-15:00, P2 queued at 16:00 and P3 queued at 15:59."""
    world = setup_confirmed_party(with_first_aider=True)
    add_extra_party(
        world,
        key="p2",
        start_at="2026-09-05T16:00:00.000Z",
        end_at="2026-09-05T20:00:00.000Z",
    )
    register_volunteer_on_party(
        world["p2_id"], world["lead_id"], world["saw_id"], role_on_crew="SAWYER"
    )
    add_extra_party(
        world,
        key="p3",
        start_at="2026-09-05T15:59:00.000Z",
        end_at="2026-09-05T19:00:00.000Z",
    )
    register_volunteer_on_party(
        world["p3_id"], world["lead_id"], world["aid_id"], role_on_crew="FIRST_AIDER"
    )
    return world


def test_inactive_adoption_outranks_the_permit_window_mismatch_on_confirm(api):
    """PRD 2.7: "The ordering below is the single authority on which one, and it is deliberate: land-manager permission and human-safety checks are evaluated before parent-link checks, which are evaluated before temporal conflicts, which are evaluated before capacity and uniqueness checks, which are evaluated before money."
    PRD 2.7: "Governing adoption is `ACTIVE` (`ERR_ADOPTION_NOT_ACTIVE`, HTTP 409), on work-plan submission, work-plan review, work-party creation, work-party confirmation and permit request."
    PRD 2.7: "Permit window containment (`ERR_PERMIT_WINDOW_MISMATCH`), on work-party confirmation."

    Design: Difficulty/priority_pair_validation_conflict/adoption_not_active_referential_outranks_permit_window_temporal_on_confirm
    """
    world = _suspended_adoption_with_out_of_window_party()

    agreement = read_agreement(world["agreement_id"])
    assert agreement["status"] == "SUSPENDED"
    assert read_party(world["party_id"])["readiness_status"] == "BLOCKED"

    response = api.confirm_work_party(world["party_id"], world["lead_headers"])
    error_data = validate_error(response, ApiErrorId.ERR_ADOPTION_NOT_ACTIVE.value, 409)
    assert error_data["error_id"] != ApiErrorId.ERR_PERMIT_WINDOW_MISMATCH.value


def test_refused_confirmation_leaves_the_party_planned_and_the_roster_intact(api):
    """PRD 3.2: "When a work plan's `budget_posture` becomes `OVER_COMMITTED`, or when the segment's posture becomes `INCIDENT_CLOSED`, the agreement moves `ACTIVE → SUSPENDED` and `suspension_reason` is set to `BUDGET_OVER_COMMIT` or `SEGMENT_INCIDENT` accordingly."
    PRD 2.10: "Parties that stayed `PLANNED` keep their rosters intact."
    PRD 2.7: "Governing adoption is `ACTIVE` (`ERR_ADOPTION_NOT_ACTIVE`, HTTP 409), on work-plan submission, work-plan review, work-party creation, work-party confirmation and permit request."

    Design: Difficulty/priority_pair_validation_conflict/adoption_not_active_referential_outranks_permit_window_temporal_on_confirm
    """
    world = _suspended_adoption_with_out_of_window_party()

    validate_error(
        api.confirm_work_party(world["party_id"], world["lead_headers"]),
        ApiErrorId.ERR_ADOPTION_NOT_ACTIVE.value,
        409,
    )

    assert read_party(world["party_id"])["schedule_status"] == "PLANNED"
    assert read_shift(world["shift_saw"]["id"])["status"] == "REGISTERED"


def test_party_starting_exactly_sixty_minutes_after_the_last_one_is_admitted(api):
    """PRD 3.6: "The party being confirmed conflicts with any other work party on the same `trail_segment_id` whose `schedule_status` is `CONFIRMED` or `IN_PROGRESS` when both of these hold at once: the new party's `start_at` is earlier than the other party's `end_at` advanced by 60 minutes, and the other party's `start_at` is earlier than the new party's `end_at` advanced by 60 minutes."
    PRD 3.6: "A gap of exactly 60 minutes between two parties is therefore permitted."

    Design: Difficulty/resource_temporal_overlap/segment_party_overlap_uses_half_open_intervals_plus_sixty_minute_buffer
    """
    world = _three_parties_on_one_segment()
    assert read_party(world["party_id"])["schedule_status"] == "CONFIRMED"

    confirmed = validate_success(
        api.confirm_work_party(world["p2_id"], world["lead_headers"])
    )
    assert confirmed["schedule_status"] == "CONFIRMED", (
        "16:00 is exactly 60 minutes after the 15:00 end, so the buffer clears"
    )


def test_party_starting_fifty_nine_minutes_after_the_last_one_collides(api):
    """PRD 3.6: "**The segment interval rule** protects the ground itself. Work-party intervals on a segment are half-open, and the resource carries a mandatory 60-minute recovery buffer."
    PRD 3.6: "A conflict is refused with `ERR_SEGMENT_PARTY_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/segment_party_overlap_uses_half_open_intervals_plus_sixty_minute_buffer
    """
    world = _three_parties_on_one_segment()
    validate_success(api.confirm_work_party(world["p2_id"], world["lead_headers"]))

    response = api.confirm_work_party(world["p3_id"], world["lead_headers"])
    validate_error(response, ApiErrorId.ERR_SEGMENT_PARTY_OVERLAP.value, 409)

    stored = read_party(world["p3_id"])
    assert stored["schedule_status"] == "PLANNED"
    assert stored["readiness_status"] == "CLEARED"


def test_confirmation_without_any_first_aid_capable_registrant_is_refused(api):
    """PRD 3.6: "Counting only shifts in `REGISTERED` or `CHECKED_IN` whose volunteer holds `CERT_FIRST_AID` or `CERT_WFA` with a `first_aid_expires_on` on or after the logical clock date, the party's `first_aid_capable_count` must be at least the `registered_count` divided by eight and rounded up to a whole number, and must in any case be at least 1."
    PRD 3.6: "Falling short refuses the confirmation — and equally the start — with `ERR_FIRST_AID_COVERAGE_INSUFFICIENT`."

    Design: Corner/validations/confirm_without_any_first_aid_capable_registrant_is_rejected
    """
    world = setup_briefed_party()
    register_volunteer_on_party(
        world["party_id"], world["lead_id"], world["gen_id"], role_on_crew="CREW_MEMBER"
    )

    party = read_party(world["party_id"])
    assert party["registered_count"] == 1
    assert party["first_aid_capable_count"] == 0

    response = api.confirm_work_party(world["party_id"], world["lead_headers"])
    validate_error(response, ApiErrorId.ERR_FIRST_AID_COVERAGE_INSUFFICIENT.value, 422)
    assert read_party(world["party_id"])["schedule_status"] == "PLANNED"


def test_party_larger_than_the_permit_ceiling_is_refused_at_confirmation(api):
    """PRD 3.6: "A `CrewLeader` requesting it must satisfy, in the ladder order of section 2.7: the segment must not be `SEASONAL_CLOSED` or `INCIDENT_CLOSED`; the work-type restriction under `WET_RESTRICTED` or `HAZARD_RESTRICTED` must be honoured; every registrant must hold every certification in `required_certifications`, and where `work_type` is `CHAINSAW` under an agency with `requires_certified_sawyer` true, the party must still retain at least one non-withdrawn shift whose volunteer holds `CERT_SAWYER_B` or `CERT_SAWYER_C`, failing which the confirmation is refused with `ERR_CERTIFICATION_MISSING`; first-aid cover must be adequate; a briefing must be on record, meaning `readiness_status` is no longer `PENDING`; the governing adoption must be `ACTIVE`; where the agency has `permit_required` true, the party must reference a permit that is `ISSUED` and whose `allowed_work_types` contains the party's `work_type`, failing which the confirmation is refused with `ERR_PERMIT_NOT_ISSUED`; both the UTC date of `start_at` and the UTC date of `end_at` must fall inside the permit's inclusive window, failing which it is refused with `ERR_PERMIT_WINDOW_MISMATCH`; the segment interval rule below must be satisfied; and `max_participants` must be no greater than the referenced permit's `max_party_size`, failing which it is refused with `ERR_PARTY_SIZE_EXCEEDS_PERMIT`."
    PRD 3.6: "Its `roster_capacity` is computed at creation and maintained thereafter as the smaller of `max_participants` and the referenced permit's `max_party_size` when a permit is referenced and that permit is `ISSUED`, and simply `max_participants` otherwise."

    Design: Corner/validations/confirm_with_party_larger_than_the_permit_ceiling_is_rejected
    """
    world = setup_party_with_sawyer(
        permit_overrides={"requested_work_types": ["TREAD_WORK"]},
        issue_overrides={"allowed_work_types": ["TREAD_WORK"], "max_party_size": 5},
    )

    response = api.confirm_work_party(world["party_id"], world["lead_headers"])
    validate_error(response, ApiErrorId.ERR_PARTY_SIZE_EXCEEDS_PERMIT.value, 422)

    party = read_party(world["party_id"])
    assert party["roster_capacity"] == 5
    assert party["schedule_status"] == "PLANNED"


def test_completing_the_party_marks_no_shows_and_consumes_the_permit(api):
    """PRD 3.6: "Completing the party moves it `IN_PROGRESS → COMPLETED`, again requiring the logical clock to be at or after `start_at`, and does three things at once: every shift still in `CHECKED_IN` is checked out at whichever is earlier of the logical clock and the party's `end_at`, with hours credited per shift and the shifts processed in `created_at` ascending order; every shift still sitting in `REGISTERED` moves to `NO_SHOW`; and the referenced permit's `consumed_party_count` rises by 1, with the permit moving to `CONSUMED` when no other referencing party remains in `PLANNED`, `CONFIRMED` or `IN_PROGRESS`."
    PRD 3.7: "Only shifts that reach `CHECKED_OUT` ever receive credited hours; shifts in `REGISTERED`, `WITHDRAWN` and `NO_SHOW` hold `credited_hours` at 0."

    Design: Corner/state_machines/work_party_complete_marks_no_shows_and_consumes_permit
    """
    world = setup_started_party()

    completed = validate_success(
        api.complete_work_party(world["party_id"], world["lead_headers"])
    )
    assert completed["schedule_status"] == "COMPLETED"

    permit = read_permit(world["permit_id"])
    assert permit["consumed_party_count"] == 1
    assert permit["status"] == "CONSUMED"

    shift = read_shift(world["shift_saw_id"])
    assert shift["status"] == "NO_SHOW"
    assert float(shift["credited_hours"]) == 0

    volunteer = read_volunteer(world["saw_id"])
    assert volunteer["active_registration_count"] == 0
    assert float(volunteer["lifetime_credited_hours"]) == 0


def test_cancelling_a_party_withdraws_shifts_and_unschedules_linked_reports(api):
    """PRD 3.6: "Every shift on the party in `REGISTERED` moves to `WITHDRAWN` and each affected volunteer's `active_registration_count` drops by 1, processed in `created_at` ascending order; and every condition report whose `linked_work_party_id` names this party returns from `SCHEDULED` to `TRIAGED` with `linked_work_party_id` cleared."
    PRD 3.6: "Cancellation is available from `PLANNED` and `CONFIRMED` to a `CrewLeader`, and from `SUSPENDED` to a `StewardshipCoordinator`; all three require a non-empty `reason` and all three carry an identical consequence set."

    Design: Corner/state_machines/work_party_cancel_withdraws_shifts_and_unschedules_linked_report
    """
    world = setup_party_with_sawyer()
    report = create_report(
        world["seg_id"],
        world["gen_id"],
        hazard_type="DRAINAGE_FAILURE",
        severity_class="MODERATE",
        description="Plugged culvert at mile 1.2.",
    )
    triaged = triage_report(report["id"], "MEDIUM")
    assert triaged["priority_score"] == 50
    scheduled = disposition_report(
        report["id"], "SCHEDULE", linked_work_party_id=world["party_id"]
    )
    assert scheduled["status"] == "SCHEDULED"

    cancelled = validate_success(
        api.cancel_work_party(
            world["party_id"], {"reason": "Access road washed out."}, world["lead_headers"]
        )
    )
    assert cancelled["schedule_status"] == "CANCELLED"
    assert cancelled["linked_report_count"] == 0

    assert read_shift(world["shift_saw_id"])["status"] == "WITHDRAWN"
    assert read_volunteer(world["saw_id"])["active_registration_count"] == 0

    stored_report = read_report(report["id"])
    assert stored_report["status"] == "TRIAGED"
    assert stored_report["linked_work_party_id"] is None
