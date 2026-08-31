"""The individual-counselling waitlist: queue priority, assignment preconditions,
closure and the deactivation cascade."""

import pytest

from test_helpers import (
    IC,
    PD,
    ApiErrorId,
    UNUSED_UUIDS,
    api_client,
    assign_counseling_referral,
    create_assessed_participant,
    create_counseling_referral,
    create_counselor,
    create_participant,
    counselor_version,
    deactivate_counselor,
    make_counselor_headers,
    make_participant_headers,
    read_counseling_referral,
    read_counselor,
    read_outreach_plan,
    read_participant,
    set_clock,
    setup_assigned_counseling_case,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_caseload_cap_refuses_the_second_case_on_a_generous_minute_budget():
    """PRD 3.5: "Four preconditions guard it. The named provider must be in status
    `ACTIVE`, otherwise `ERR_COUNSELOR_NOT_ACTIVE`. The referral's
    `required_specialty` must appear in the provider's `specialties`, otherwise
    `ERR_SPECIALTY_MISMATCH`. Taking the case must not push `active_caseload` above
    `caseload_cap` — that is, the current caseload plus one must remain at or below
    the cap — otherwise `ERR_COUNSELOR_CASELOAD_EXCEEDED`. And the minute budget
    must hold: the provider's `committed_minutes` plus this referral's
    `requested_minutes_per_week` must not exceed `weekly_capacity_minutes`,
    otherwise `ERR_COUNSELOR_CAPACITY_EXCEEDED`. That last comparison is strictly
    greater-than, so landing exactly on the weekly budget is legal."

    Design: Corner/validations/counselor_caseload_cap_is_enforced_before_the_minute_budget
    """
    set_clock()
    counselor = create_counselor(full_name="Dr Wren Adisa", license_type="LCSW",
                                 specialties=["SUDDEN_DEATH"], caseload_cap=1,
                                 weekly_capacity_minutes=600)
    first_participant = create_participant(loss_type="SUDDEN_DEATH")
    second_participant = create_participant(loss_type="SUDDEN_DEATH")
    first = create_counseling_referral(first_participant["id"],
                                       requested_minutes_per_week=60)
    second = create_counseling_referral(second_participant["id"],
                                        requested_minutes_per_week=60)
    assign_counseling_referral(first["id"], counselor["id"], counselor["version"])

    error = validate_error(
        api_client.assign_counseling_referral(
            second["id"],
            {"counselor_id": counselor["id"],
             "expected_counselor_version": counselor_version(counselor["id"])}, IC),
        ApiErrorId.ERR_COUNSELOR_CASELOAD_EXCEEDED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_COUNSELOR_CAPACITY_EXCEEDED.value

    refreshed = read_counselor(counselor["id"])
    assert refreshed["active_caseload"] == 1
    assert refreshed["committed_minutes"] == 60
    assert read_counseling_referral(second["id"])["status"] == "WAITLISTED"


def test_assigning_to_a_provider_without_the_required_specialty_is_refused():
    """PRD 3.5: "Four preconditions guard it. The named provider must be in status
    `ACTIVE`, otherwise `ERR_COUNSELOR_NOT_ACTIVE`. The referral's
    `required_specialty` must appear in the provider's `specialties`, otherwise
    `ERR_SPECIALTY_MISMATCH`."
    PRD 3.5: "The urgency band contributes a flat weight: 10 points for `ROUTINE`,
    25 points for `PRIORITY`, 45 points for `URGENT`. Clinical need contributes the
    participant's `composite_need_index` multiplied by 0.35, capped so that this
    component never exceeds 35 points — meaning a composite of one hundred and a
    composite of ninety-nine both contribute the full 35."

    Design: Corner/validations/assign_to_a_counselor_lacking_the_required_specialty_returns_specialty_mismatch
    """
    set_clock()
    counselor = create_counselor(full_name="Dr Perin Case", license_type="CHAPLAIN",
                                 specialties=["PERINATAL"], caseload_cap=5,
                                 weekly_capacity_minutes=600)
    participant = create_participant(loss_type="SUDDEN_DEATH")
    referral = create_counseling_referral(
        participant["id"], requested_minutes_per_week=60, urgency="ROUTINE",
        required_specialty="SUDDEN_DEATH")
    assert referral["queue_priority"] == pytest.approx(10.00, abs=0.001), (
        f"Expected a ROUTINE band alone to score 10.00, got {referral['queue_priority']}")

    validate_error(
        api_client.assign_counseling_referral(
            referral["id"],
            {"counselor_id": counselor["id"],
             "expected_counselor_version": counselor["version"]}, IC),
        ApiErrorId.ERR_SPECIALTY_MISMATCH.value, 422)

    refreshed = read_counselor(counselor["id"])
    assert refreshed["active_caseload"] == 0
    assert refreshed["committed_minutes"] == 0
    assert refreshed["version"] == 1
    assert read_counseling_referral(referral["id"])["status"] == "WAITLISTED"


def test_closing_an_unknown_counselling_referral_is_not_found():
    """PRD 2.8: "Each entity has its own dedicated code — `ERR_REFERRAL_NOT_FOUND`,
    `ERR_PARTICIPANT_NOT_FOUND`, `ERR_SPACE_NOT_FOUND`, `ERR_COHORT_NOT_FOUND`,
    `ERR_ENROLLMENT_NOT_FOUND`, `ERR_COUNSELOR_NOT_FOUND`,
    `ERR_COUNSELING_REFERRAL_NOT_FOUND`"

    Design: Corner/errors/counseling_referral_close_with_unknown_id_returns_counseling_referral_not_found
    """
    set_clock()
    validate_error(
        api_client.close_counseling_referral(
            UNUSED_UUIDS["counseling_referral"], {"close_reason": "COMPLETED"}, IC),
        ApiErrorId.ERR_COUNSELING_REFERRAL_NOT_FOUND.value, 404)


def test_assigning_to_an_unknown_counselor_is_not_found_before_the_version_check():
    """PRD 2.5: "Every entity identifier named inside the request body resolves to
    an existing record — otherwise the corresponding not-found error (404). This
    rung guards enrollment creation, counselling-referral creation,
    counselling-referral assignment, companion-match creation, cohort creation,
    remembrance-event creation, invitation creation, funding-allocation creation
    and grant-report creation."

    Design: Corner/errors/counseling_referral_assign_with_unknown_counselor_returns_counselor_not_found
    """
    set_clock()
    real_counselor = create_counselor(full_name="Dr Real", license_type="LCSW",
                                      specialties=["SUDDEN_DEATH"])
    participant = create_participant(loss_type="SUDDEN_DEATH")
    referral = create_counseling_referral(participant["id"])

    validate_error(
        api_client.assign_counseling_referral(
            referral["id"],
            {"counselor_id": UNUSED_UUIDS["counselor"],
             "expected_counselor_version": real_counselor["version"]}, IC),
        ApiErrorId.ERR_COUNSELOR_NOT_FOUND.value, 404)
    assert read_counseling_referral(referral["id"])["status"] == "WAITLISTED"


def test_assigning_to_a_deactivated_counselor_is_refused():
    """PRD 3.5: "A `ProgramDirector` deactivates them, moving the provider
    `ACTIVE → INACTIVE` and zeroing both `active_caseload` and
    `committed_minutes`."
    PRD 3.5: "Four preconditions guard it. The named provider must be in status
    `ACTIVE`, otherwise `ERR_COUNSELOR_NOT_ACTIVE`."

    Design: Corner/errors/counselor_not_active_error_on_assign_to_deactivated_counselor
    """
    set_clock()
    counselor = create_counselor(full_name="Dr Gone", license_type="LPC",
                                 specialties=["SUDDEN_DEATH"])
    deactivated = deactivate_counselor(counselor["id"])
    assert deactivated["status"] == "INACTIVE"

    participant = create_participant(loss_type="SUDDEN_DEATH")
    referral = create_counseling_referral(participant["id"])

    validate_error(
        api_client.assign_counseling_referral(
            referral["id"],
            {"counselor_id": counselor["id"],
             "expected_counselor_version": deactivated["version"]}, IC),
        ApiErrorId.ERR_COUNSELOR_NOT_ACTIVE.value, 409)

    refreshed = read_counseling_referral(referral["id"])
    assert refreshed["status"] == "WAITLISTED"
    assert refreshed["counselor_id"] is None


def test_a_counselor_may_not_close_another_counselors_case():
    """PRD 2.1: "When `X-User-Role` is `Counselor`, `X-User-ID` is the `id` of the
    acting `Counselor`, and ownership checks compare it against the `counselor_id`
    of the counselling referral being acted on."
    PRD 3.5: "Available from `ASSIGNED` to either an `IntakeCoordinator` or the
    assigned `Counselor` themselves, closure moves the referral to `CLOSED`,
    records a `close_reason` of `COMPLETED`, `PARTICIPANT_WITHDRAWN`,
    `COUNSELOR_UNAVAILABLE` or `DECLINED`, decreases the provider's
    `active_caseload` by one and their `committed_minutes` by that referral's
    `requested_minutes_per_week`, and increments the provider's `version`."

    Design: Corner/rbac/counselor_cannot_close_a_referral_assigned_to_another_counselor
    """
    set_clock()
    counselor_a = create_counselor(full_name="Dr A Marin", license_type="LCSW",
                                   specialties=["SUDDEN_DEATH"])
    counselor_b = create_counselor(full_name="Dr B Okafor", license_type="LPC",
                                   specialties=["SUDDEN_DEATH"])
    participant = create_participant(loss_type="SUDDEN_DEATH")
    referral = create_counseling_referral(participant["id"],
                                          requested_minutes_per_week=60)
    assign_counseling_referral(referral["id"], counselor_a["id"],
                               counselor_a["version"])

    validate_error(
        api_client.close_counseling_referral(
            referral["id"], {"close_reason": "COMPLETED"},
            make_counselor_headers(counselor_b["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    closed = validate_success(
        api_client.close_counseling_referral(
            referral["id"], {"close_reason": "COMPLETED"},
            make_counselor_headers(counselor_a["id"])))
    assert closed["status"] == "CLOSED"
    assert closed["close_reason"] == "COMPLETED"

    refreshed_a = read_counselor(counselor_a["id"])
    assert refreshed_a["active_caseload"] == 0
    assert refreshed_a["committed_minutes"] == 0
    assert read_counselor(counselor_b["id"])["active_caseload"] == 0


def _setup_counselor_at_the_minute_boundary():
    """One ACTIVE provider with a 120-minute weekly budget and three waitlisted
    referrals asking for 60, 60 and 1 minutes."""
    set_clock()
    counselor = create_counselor(full_name="Dr Wren Adisa",
                                 license_type="PSYCHOLOGIST",
                                 specialties=["SUDDEN_DEATH"], caseload_cap=5,
                                 weekly_capacity_minutes=120)
    referrals = []
    for minutes, name in ((60, "Sol Amara"), (60, "Uma Boro"), (1, "Wynn Cerra")):
        participant = create_participant(loss_type="SUDDEN_DEATH",
                                         contact_name=name)
        referrals.append(create_counseling_referral(
            participant["id"], requested_minutes_per_week=minutes,
            urgency="ROUTINE", required_specialty="SUDDEN_DEATH"))
    return counselor, referrals


def test_committed_minutes_may_land_exactly_on_the_weekly_budget():
    """PRD 3.5: "Four preconditions guard it. The named provider must be in status
    `ACTIVE`, otherwise `ERR_COUNSELOR_NOT_ACTIVE`. The referral's
    `required_specialty` must appear in the provider's `specialties`, otherwise
    `ERR_SPECIALTY_MISMATCH`. Taking the case must not push `active_caseload` above
    `caseload_cap` — that is, the current caseload plus one must remain at or below
    the cap — otherwise `ERR_COUNSELOR_CASELOAD_EXCEEDED`. And the minute budget
    must hold: the provider's `committed_minutes` plus this referral's
    `requested_minutes_per_week` must not exceed `weekly_capacity_minutes`,
    otherwise `ERR_COUNSELOR_CAPACITY_EXCEEDED`. That last comparison is strictly
    greater-than, so landing exactly on the weekly budget is legal."
    PRD 3.5: "`committed_minutes` is therefore simply the sum of
    `requested_minutes_per_week` over that provider's referrals in status
    `ASSIGNED`; referrals in `WAITLISTED`, `CLOSED` or `CANCELLED` contribute
    nothing."

    Design: Difficulty/resource_temporal_overlap/counselor_weekly_minutes_aggregate_capacity_admits_exact_equality
    """
    counselor, referrals = _setup_counselor_at_the_minute_boundary()

    assign_counseling_referral(referrals[0]["id"], counselor["id"],
                               counselor["version"])
    after_first = read_counselor(counselor["id"])
    assert after_first["committed_minutes"] == 60

    second = validate_success(
        api_client.assign_counseling_referral(
            referrals[1]["id"],
            {"counselor_id": counselor["id"],
             "expected_counselor_version": after_first["version"]}, IC))
    assert second["status"] == "ASSIGNED"

    after_second = read_counselor(counselor["id"])
    assert after_second["committed_minutes"] == 120, (
        "landing exactly on weekly_capacity_minutes must be admitted")
    assert after_second["active_caseload"] == 2


def test_one_minute_beyond_the_weekly_budget_is_refused():
    """PRD 3.5: "And the minute budget must hold: the provider's
    `committed_minutes` plus this referral's `requested_minutes_per_week` must not
    exceed `weekly_capacity_minutes`, otherwise `ERR_COUNSELOR_CAPACITY_EXCEEDED`.
    That last comparison is strictly greater-than, so landing exactly on the weekly
    budget is legal."
    PRD 3.5: "The minute budget is aggregate capacity, not a calendar."

    Design: Difficulty/resource_temporal_overlap/counselor_weekly_minutes_aggregate_capacity_admits_exact_equality
    """
    counselor, referrals = _setup_counselor_at_the_minute_boundary()
    assign_counseling_referral(referrals[0]["id"], counselor["id"],
                               counselor["version"])
    assign_counseling_referral(referrals[1]["id"], counselor["id"])

    validate_error(
        api_client.assign_counseling_referral(
            referrals[2]["id"],
            {"counselor_id": counselor["id"],
             "expected_counselor_version": counselor_version(counselor["id"])}, IC),
        ApiErrorId.ERR_COUNSELOR_CAPACITY_EXCEEDED.value, 409)

    refreshed = read_counselor(counselor["id"])
    assert refreshed["committed_minutes"] == 120
    assert refreshed["active_caseload"] == 2
    third = read_counseling_referral(referrals[2]["id"])
    assert third["status"] == "WAITLISTED"
    assert third["counselor_id"] is None


def _setup_second_reentry():
    """A participant tiered MODERATE whose counselling referral has already fallen
    back to the waitlist once and is now assigned to a second provider."""
    set_clock()
    counselor_x = create_counselor(full_name="Dr X Marin", license_type="LCSW",
                                   specialties=["SUDDEN_DEATH"], caseload_cap=5,
                                   weekly_capacity_minutes=600)
    counselor_y = create_counselor(full_name="Dr Y Okafor", license_type="LPC",
                                   specialties=["SUDDEN_DEATH"], caseload_cap=5,
                                   weekly_capacity_minutes=600)
    participant = create_assessed_participant(
        loss_type="SUDDEN_DEATH", date_of_death="2026-06-10",
        relationship_to_deceased="PARENT", grief_severity=20, isolation_index=8,
        functional_impairment=8)
    assert participant["risk_tier"] == "MODERATE"

    referral = create_counseling_referral(
        participant["id"], requested_minutes_per_week=60, urgency="PRIORITY",
        required_specialty="SUDDEN_DEATH")
    assign_counseling_referral(referral["id"], counselor_x["id"],
                               counselor_x["version"])
    deactivate_counselor(counselor_x["id"])
    assign_counseling_referral(referral["id"], counselor_y["id"],
                               counselor_y["version"])
    return counselor_y, participant, referral


def test_deactivation_returns_the_caseload_to_the_waitlist_and_rescores_the_queue():
    """PRD 3.5: "A `ProgramDirector` deactivates them, moving the provider
    `ACTIVE → INACTIVE` and zeroing both `active_caseload` and
    `committed_minutes`. Every referral that provider held in `ASSIGNED` falls back
    `ASSIGNED → WAITLISTED`, with `counselor_id` and `assigned_at` cleared and
    `waitlisted_at` reset to the current logical clock so the referral takes its
    place in the queue afresh. Each such fall-back increments that participant's
    `waitlist_reentry_count` by one and recomputes the referral's `queue_priority`
    — which is where the re-entry bonus earned above begins to bite."
    PRD 3.5: "Re-entry contributes 5 points for each time this participant's
    counselling has fallen back to the waitlist, taken from
    `waitlist_reentry_count`, capped at 10 points."

    Design: Difficulty/transitive_cascade/counselor_deactivation_chain_requeue_reentry_tier_outreach_channel
    """
    counselor_y, participant, referral = _setup_second_reentry()

    validate_success(api_client.deactivate_counselor(counselor_y["id"], PD))

    refreshed_counselor = read_counselor(counselor_y["id"])
    assert refreshed_counselor["status"] == "INACTIVE"
    assert refreshed_counselor["active_caseload"] == 0
    assert refreshed_counselor["committed_minutes"] == 0

    refreshed_referral = read_counseling_referral(referral["id"])
    assert refreshed_referral["status"] == "WAITLISTED"
    assert refreshed_referral["counselor_id"] is None
    assert refreshed_referral["queue_priority"] == pytest.approx(50.75, abs=0.001), (
        f"Expected 25 + 15.75 + 10 = 50.75, got {refreshed_referral['queue_priority']}")
    assert read_participant(participant["id"])["waitlist_reentry_count"] == 2


def test_a_second_waitlist_reentry_escalates_the_tier_cadence_and_outreach_channel():
    """PRD 3.5: "And once a participant's `waitlist_reentry_count` has reached two
    or more, the programme treats repeated disruption as a clinical risk in its own
    right: that participant's `risk_tier` is escalated by exactly one level, `LOW`
    becoming `MODERATE` and `MODERATE` becoming `HIGH`, with a tier already at
    `HIGH` left unchanged. The escalated tier then recomputes
    `outreach_cadence_days` on the same 90 / 60 / 30 scale, and when the escalated
    tier is `HIGH`, every one of that participant's anniversary touchpoints in
    `SCHEDULED` or `DUE` has its `channel` switched to `PHONE` and its `escalated`
    flag set to true."

    Design: Difficulty/transitive_cascade/counselor_deactivation_chain_requeue_reentry_tier_outreach_channel
    """
    counselor_y, participant, referral = _setup_second_reentry()

    validate_success(api_client.deactivate_counselor(counselor_y["id"], PD))

    refreshed = read_participant(participant["id"])
    assert refreshed["waitlist_reentry_count"] == 2
    assert refreshed["risk_tier"] == "HIGH", (
        "a second re-entry escalates MODERATE by exactly one level")
    assert refreshed["composite_need_index"] == pytest.approx(45.00, abs=0.001), (
        "the escalation moves the tier, never the composite")
    assert refreshed["outreach_cadence_days"] == 30

    plan = read_outreach_plan(participant["id"])
    assert len(plan) == 4
    for row in plan:
        assert row["status"] == "SCHEDULED"
        assert row["channel"] == "PHONE"
        assert row["escalated"] is True


def _setup_participant_on_outreach_hold():
    """An ASSESSED participant tiered MODERATE whose outreach dimension is held."""
    set_clock()
    participant = create_assessed_participant(
        source_type="SELF", decedent_name="Gita Halloran",
        date_of_death="2026-06-10", relationship_to_deceased="PARENT",
        loss_type="SUDDEN_DEATH", contact_name="Ines Halloran",
        contact_email="ines.h@example.org", grief_severity=20, isolation_index=8,
        functional_impairment=8)
    return participant


def test_placing_outreach_on_hold_leaves_the_service_dimension_untouched():
    """PRD 3.8: "Either an `IntakeCoordinator` or the `Participant` themselves may
    place the outreach dimension on hold by supplying `hold` as true, moving
    `outreach_status` `SCHEDULED → ON_HOLD`; the participant's existing touchpoints
    are left exactly as they are, but the sweep skips over that participant
    entirely while the hold stands, so nothing ripens and nothing lapses. Supplying
    `hold` as false lifts it, moving `outreach_status` `ON_HOLD → SCHEDULED` and
    letting the sweep resume advancing that participant's rows. Placing a hold
    requires the participant's `service_status` not to be `WITHDRAWN`; the hold
    toggle never touches `service_status`."

    Design: Difficulty/non_linear_state_machine/participant_service_and_outreach_dimensions_advance_independently
    """
    participant = _setup_participant_on_outreach_hold()

    held = validate_success(
        api_client.set_outreach_hold(
            participant["id"], True, make_participant_headers(participant["id"])))
    assert held["service_status"] == "ASSESSED", (
        "the hold toggle must not move the clinical dimension")
    assert held["outreach_status"] == "ON_HOLD"

    lifted = validate_success(
        api_client.set_outreach_hold(
            participant["id"], False, make_participant_headers(participant["id"])))
    assert lifted["outreach_status"] == "SCHEDULED"
    assert lifted["service_status"] == "ASSESSED"


def test_a_counselling_referral_advances_the_service_dimension_while_outreach_stays_held():
    """PRD 3.8: "`service_status` is the clinical dimension — `INTAKE`, `ASSESSED`,
    `ACTIVE`, `MAINTENANCE`, `DISCHARGED`, `WITHDRAWN` — and it advances through
    assessment, enrolment, cohort completion and discharge as described in §3.2 and
    §3.4. `outreach_status` is the follow-up dimension — `SCHEDULED`, `ON_HOLD`,
    `LAPSED`, `CLOSED` — and it evolves under entirely different triggers. Neither
    dimension gates the other, with a single exception: when `service_status`
    reaches the terminal `WITHDRAWN`, `outreach_status` is forced to `CLOSED` in
    the same write."
    PRD 3.5: "The referral is created in status `WAITLISTED` with HTTP 201, its
    `waitlisted_at` stamped from the logical clock, its `counselor_id`,
    `assigned_at` and `close_reason` all null, and its `queue_priority` computed
    immediately. Creating a counselling referral also advances the participant's
    `service_status` from `ASSESSED` to `ACTIVE`, exactly as a first group
    placement does."

    Design: Difficulty/non_linear_state_machine/participant_service_and_outreach_dimensions_advance_independently
    """
    participant = _setup_participant_on_outreach_hold()
    validate_success(
        api_client.set_outreach_hold(
            participant["id"], True, make_participant_headers(participant["id"])))

    referral = validate_success(
        api_client.create_counseling_referral(
            {"participant_id": participant["id"],
             "requested_minutes_per_week": 60, "urgency": "PRIORITY",
             "required_specialty": "SUDDEN_DEATH"}, IC), 201)
    assert referral["status"] == "WAITLISTED"
    assert referral["queue_priority"] == pytest.approx(40.75, abs=0.001), (
        f"Expected 25 + 15.75 = 40.75, got {referral['queue_priority']}")

    refreshed = read_participant(participant["id"])
    assert refreshed["service_status"] == "ACTIVE"
    assert refreshed["outreach_status"] == "ON_HOLD", (
        "the outreach hold must survive an advance on the clinical dimension")
    assert refreshed["composite_need_index"] == pytest.approx(45.00, abs=0.001)
    assert refreshed["risk_tier"] == "MODERATE"
    assert refreshed["outreach_cadence_days"] == 60
