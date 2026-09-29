"""Error reachability: the not-found families, the intake codes and the guard chains."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    APPEALS_OFFICER_HEADERS,
    COMPLAINANT_HEADERS,
    OFFICER_REPRESENTATIVE_HEADERS,
    RECORDS_CUSTODIAN_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    assert_discipline_days,
    assert_eis_run_counters,
    assert_instant,
    assert_officer_ledgers,
    assert_officer_risk,
    assert_two_dp,
    make_supervisor_headers,
)
from test_helpers import factories, fixtures

BASE_CLOCK = "2026-08-01T00:00:00Z"
UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"


def test_every_path_id_family_reports_its_own_not_found_code(api):
    """Eleven routes given the same unknown id answer with eleven different 404 codes.

    PRD: A request naming a complaint that does not exist fails with `ERR_COMPLAINT_NOT_FOUND` (HTTP 404) whatever else is wrong with the body; the same principle yields `ERR_OFFICER_NOT_FOUND`, `ERR_INVESTIGATION_NOT_FOUND`, `ERR_ALLEGATION_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_DISCIPLINE_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_REINSTATEMENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_CHECKIN_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND` and `ERR_ROOM_NOT_FOUND` for their respective resources, each with HTTP 404.
    PRD: A complaints path segment must resolve to a `Complaint` on the single-complaint read, allegation creation, classification, investigation opening, withdrawal and purge; an officers path segment must resolve to an `Officer` on the single-officer read, the activity-event list, the EIS profile read, activity-event creation and the employment-status write; an investigations path segment must resolve to an `Investigation` on the single-investigation read, assignment, tolling, interview-session creation, findings and close; an allegations path segment must resolve to an `Allegation` on the single-allegation read and the disposition write; an interview-sessions path segment must resolve to an `InterviewSession` on the single-session read, hold and postpone; a disciplines path segment must resolve to a `Discipline` on the single-discipline read, impose and appeal filing; an appeals path segment must resolve to an `Appeal` on the single-appeal read, the reinstatement list, hear and decide; a reinstatements path segment must resolve to a `Reinstatement` on finalize; an eis-alerts path segment must resolve to an `EarlyInterventionAlert` on the single-alert read, dismiss and plan creation; an intervention-plans path segment must resolve to an `InterventionPlan` on the single-plan read, the check-in list, activate and close; a check-ins path segment must resolve to a `MonitoringCheckIn` on complete; and a credibility-disclosures path segment must resolve to a `CredibilityDisclosure` on the single-disclosure read and release.
    PRD: Validation proceeds strictly in ascending priority tier; **the first violated rule determines the response, and no later rule is evaluated.**
    Design: Corner/errors/every_path_id_family_reports_its_own_not_found_code
    """
    fixtures.set_clock(api, BASE_CLOCK)
    patrol = fixtures.create_unit(api, intake_enabled=True)
    doyle = fixtures.create_supervisor(api, patrol["id"])
    sup_headers = make_supervisor_headers(doyle["id"])

    validate_error(
        api.get_hearing_room(UNKNOWN_ID, SYSTEM_ADMIN_HEADERS), "ERR_ROOM_NOT_FOUND", 404
    )
    validate_error(
        api.get_allegation(UNKNOWN_ID, RECORDS_CUSTODIAN_HEADERS), "ERR_ALLEGATION_NOT_FOUND", 404
    )
    validate_error(
        api.get_investigation(UNKNOWN_ID, RECORDS_CUSTODIAN_HEADERS),
        "ERR_INVESTIGATION_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_interview_session(UNKNOWN_ID, RECORDS_CUSTODIAN_HEADERS),
        "ERR_SESSION_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_discipline(UNKNOWN_ID, RECORDS_CUSTODIAN_HEADERS), "ERR_DISCIPLINE_NOT_FOUND", 404
    )
    validate_error(
        api.get_appeal(UNKNOWN_ID, RECORDS_CUSTODIAN_HEADERS), "ERR_APPEAL_NOT_FOUND", 404
    )

    # Path existence at tier 3 outranks the fiscal check the payload would satisfy anyway.
    validate_error(
        api.finalize_reinstatement(
            UNKNOWN_ID, factories.reinstatement_finalize_payload(0), APPEALS_OFFICER_HEADERS
        ),
        "ERR_REINSTATEMENT_NOT_FOUND",
        404,
    )
    validate_error(api.get_eis_alert(UNKNOWN_ID, SYSTEM_ADMIN_HEADERS), "ERR_ALERT_NOT_FOUND", 404)
    validate_error(
        api.get_intervention_plan(UNKNOWN_ID, SYSTEM_ADMIN_HEADERS), "ERR_PLAN_NOT_FOUND", 404
    )

    # Path existence also outranks the monitoring-supervisor identity rule at tier 6.
    validate_error(
        api.complete_check_in(
            UNKNOWN_ID,
            factories.check_in_completion_payload(notes="No such check-in."),
            sup_headers,
        ),
        "ERR_CHECKIN_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_credibility_disclosure(UNKNOWN_ID, RECORDS_CUSTODIAN_HEADERS),
        "ERR_DISCLOSURE_NOT_FOUND",
        404,
    )

    _, room_meta = fixtures.rows(api.list_hearing_rooms(SYSTEM_ADMIN_HEADERS))
    assert room_meta["total_count"] == 0
    for listing in (
        api.list_complaints(RECORDS_CUSTODIAN_HEADERS),
        api.list_allegations(RECORDS_CUSTODIAN_HEADERS),
        api.list_investigations(RECORDS_CUSTODIAN_HEADERS),
        api.list_interview_sessions(RECORDS_CUSTODIAN_HEADERS),
        api.list_disciplines(RECORDS_CUSTODIAN_HEADERS),
        api.list_appeals(RECORDS_CUSTODIAN_HEADERS),
        api.list_eis_alerts(RECORDS_CUSTODIAN_HEADERS),
        api.list_intervention_plans(RECORDS_CUSTODIAN_HEADERS),
        api.list_credibility_disclosures(RECORDS_CUSTODIAN_HEADERS),
    ):
        empty, meta = fixtures.rows(listing)
        assert empty == []
        assert meta["total_count"] == 0


def test_intake_routing_and_the_withdrawal_credential_have_their_own_codes(api):
    """No internal-affairs unit blocks intake; then a wrong code and a null code fail apart.

    PRD: If the department has registered no unit at all whose `unit_role` is `INTERNAL_AFFAIRS`, there is nowhere to route and the request is refused with `ERR_NO_INTAKE_UNIT`.
    PRD: The complaint is `CLASS_I` when `alleged_injury` is true, or when at least one member of `reported_allegation_types` is `EXCESSIVE_FORCE`, `UNLAWFUL_SEARCH` or `UNTRUTHFULNESS`.
    PRD: First the credential: when the complaint stores a non-null `intake_reference_code`, the supplied value must equal it, and a mismatch is `ERR_INTAKE_CODE_MISMATCH`.
    PRD: Second the channel: `intake_channel` must be `PUBLIC` or `SUPERVISOR`, and because an anonymous complaint stores no code at all it passes the credential check and is stopped here instead, with `ERR_ANONYMOUS_NOT_WITHDRAWABLE`.
    PRD: An accepted withdrawal always stamps `closed_at` from the logical clock, sets `retention_until` to `closed_at` plus 730 whole days, and sets every allegation still in `PENDING` to `disposition` `WITHDRAWN`.
    Design: Corner/errors/intake_routing_and_the_withdrawal_credential_have_their_own_codes
    """
    fixtures.set_clock(api, BASE_CLOCK)
    patrol = fixtures.create_unit(api, intake_enabled=True)
    doyle = fixtures.create_supervisor(api, patrol["id"])
    sup_headers = make_supervisor_headers(doyle["id"])

    nowhere_to_route = api.create_complaint(
        factories.supervisor_complaint_payload(
            patrol["id"],
            doyle["id"],
            narrative="Reports not filed, but there is nowhere to route the file.",
            incident_datetime="2026-07-15T20:00:00Z",
        ),
        sup_headers,
    )

    validate_error(nowhere_to_route, "ERR_NO_INTAKE_UNIT", 422)
    refused_intake, refused_meta = fixtures.rows(api.list_complaints(sup_headers))
    assert refused_intake == []
    assert refused_meta["total_count"] == 0

    internal_affairs = fixtures.create_internal_affairs_unit(api)
    supervisor_file = get_success_data(
        api.create_complaint(
            factories.supervisor_complaint_payload(
                patrol["id"],
                doyle["id"],
                narrative="Reports not filed on the same shift.",
                incident_datetime="2026-07-15T20:00:00Z",
            ),
            sup_headers,
        )
    )

    assert supervisor_file["classification"] == "CLASS_II"
    assert supervisor_file["status"] == "CLASSIFIED"
    assert supervisor_file["intake_sequence"] == 1
    assert supervisor_file["intake_reference_code"] == "CMP-000001"

    wrong_credential = api.withdraw_complaint(
        supervisor_file["id"],
        factories.withdrawal_payload(
            "CMP-999999", withdrawal_reason="Wrong credential presented."
        ),
        sup_headers,
    )

    validate_error(wrong_credential, "ERR_INTAKE_CODE_MISMATCH", 403)
    untouched = fixtures.read_complaint(api, supervisor_file["id"], sup_headers)
    assert untouched["status"] == "CLASSIFIED"
    assert untouched["closed_at"] is None
    assert untouched["retention_until"] is None

    anonymous_file = get_success_data(
        api.create_complaint(
            factories.anonymous_complaint_payload(
                patrol["id"],
                narrative="Anonymous report of an injury caused by a takedown.",
                incident_datetime="2026-07-18T20:00:00Z",
                alleged_injury=True,
                reported_allegation_types=["EXCESSIVE_FORCE"],
            ),
            COMPLAINANT_HEADERS,
        )
    )

    assert anonymous_file["classification"] == "CLASS_I"
    assert anonymous_file["screening_required"] is False
    assert anonymous_file["status"] == "CLASSIFIED"
    assert anonymous_file["assigned_unit_id"] == internal_affairs["id"]
    assert anonymous_file["intake_sequence"] == 2
    assert anonymous_file["intake_reference_code"] is None

    # The tier-6 credential check passes on a null stored code, so tier 12 refuses instead.
    no_credential_at_all = api.withdraw_complaint(
        anonymous_file["id"],
        factories.withdrawal_payload(
            "CMP-000002", withdrawal_reason="Anonymous author changed their mind."
        ),
        COMPLAINANT_HEADERS,
    )

    validate_error(no_credential_at_all, "ERR_ANONYMOUS_NOT_WITHDRAWABLE", 422)

    withdrawn = get_success_data(
        api.withdraw_complaint(
            supervisor_file["id"],
            factories.withdrawal_payload(
                supervisor_file["intake_reference_code"],
                withdrawal_reason="Correct credential presented.",
            ),
            sup_headers,
        )
    )

    assert withdrawn["status"] == "WITHDRAWN"
    assert_instant(withdrawn["closed_at"], BASE_CLOCK)
    assert_instant(withdrawn["retention_until"], "2028-07-31T00:00:00Z")
    assert fixtures.read_complaint(api, anonymous_file["id"], sup_headers)["status"] == "CLASSIFIED"


def two_allegations_assigned_to_ahn(api):
    """One supervisor-channel file carrying two allegations against Vance, assigned to Ahn."""
    world = fixtures.world_assigned_investigation(
        api,
        allegation_type="NEGLECT_OF_DUTY",
        offense_class="B",
        reported_allegation_types=["NEGLECT_OF_DUTY", "DISCOURTESY"],
        complaint_overrides={
            "narrative": "Two reported failures on one tour of duty.",
            "incident_datetime": "2026-07-20T22:00:00Z",
        },
    )
    second = fixtures.attach_allegation(
        api,
        world,
        world["c_id"],
        allegation_type="DISCOURTESY",
        narrative="Rude language toward the complainant.",
        offense_class="C",
    )
    world.update({"a2_id": second["id"], "allegation_ids": [world["a1_id"], second["id"]]})
    return world


def test_interview_and_findings_guards_fire_one_at_a_time_along_a_single_chain(api):
    """Seven interview-stage codes are provoked in turn along one booking and one findings filing.

    PRD: The requested window must be coherent and in the future: `scheduled_end` must be strictly after `scheduled_start`, and `scheduled_start` must be strictly after the logical clock. Either failure is `ERR_INVALID_SESSION_WINDOW`.
    PRD: An accepted session is created in `SCHEDULED` with `postpone_count` 0 and `held_at` and `interview_summary` both null, records the `investigation_id` of the investigation it belongs to, occupies the officer's buffered window and one unit of the room's concurrent capacity for its scheduled window, and — when it is the first accepted session on a still-`ASSIGNED` investigation — moves that investigation `ASSIGNED → IN_PROGRESS`.
    PRD: Findings may not be filed before the subject officer has actually been heard: `interview_held_count` must be at least 1, and a premature submission is refused with `ERR_NO_INTERVIEW_HELD`.
    PRD: `representation_status` must be `WAIVED` or `REP_PRESENT`; an interview may not be held while representation is still `REP_REQUESTED`, and attempting it is `ERR_REPRESENTATION_NOT_PRESENT`.
    PRD: And the logical clock must be at or after the session's `scheduled_start` — an interview cannot be recorded as held before it was due to begin, and trying is `ERR_INTERVIEW_NOT_STARTED`.
    PRD: The session must still be `SCHEDULED`, otherwise `ERR_SESSION_STATE_INVALID`.
    PRD: The session must be in `SCHEDULED` to begin with, otherwise `ERR_SESSION_STATE_INVALID`, and `postpone_count` must be strictly less than 2 — the department allows two postponements and no more, so a third attempt is `ERR_MAX_POSTPONEMENTS_REACHED`.
    PRD: The `allegation_findings` array must cover the complaint's allegations exactly — one entry for every allegation, with no duplicates and no entries for allegations belonging to some other complaint. Anything else is `ERR_FINDINGS_INCOMPLETE`.
    PRD: An accepted submission stamps `findings_submitted_at`, writes `evidence_weight_for`, `evidence_weight_against` and `policy_compliant` onto every allegation and recomputes each one's `support_pct` and `preponderance_met`, moves the investigation `IN_PROGRESS → PENDING_REVIEW`, and moves the owning complaint `UNDER_INVESTIGATION → ADJUDICATION`.
    Design: Corner/errors/interview_and_findings_guards_fire_one_at_a_time_along_a_single_chain
    """
    world = two_allegations_assigned_to_ahn(api)
    complete_entries = [
        factories.finding_entry(world["a1_id"], 60, 40, False),
        factories.finding_entry(world["a2_id"], 55, 45, False),
    ]

    # Notice would have been 106 hours, so the notice rule cannot be the reported cause.
    reversed_window = api.schedule_interview_session(
        world["i1_id"],
        factories.interview_session_payload(
            world["subj_id"],
            world["room1_id"],
            scheduled_start="2026-08-05T10:00:00Z",
            scheduled_end="2026-08-05T09:00:00Z",
            notice_served_at=BASE_CLOCK,
            representation_status="REP_REQUESTED",
        ),
        world["inv_a_headers"],
    )

    validate_error(reversed_window, "ERR_INVALID_SESSION_WINDOW", 422)
    assert fixtures.read_investigation(api, world["i1_id"], world["cmdr_headers"])["status"] == "ASSIGNED"

    session = fixtures.schedule_session(
        api,
        world,
        world["i1_id"],
        scheduled_start="2026-08-05T09:00:00Z",
        scheduled_end="2026-08-05T10:00:00Z",
        notice_served_at=BASE_CLOCK,
        representation_status="REP_REQUESTED",
    )

    assert session["status"] == "SCHEDULED"
    assert session["investigation_id"] == world["i1_id"]
    assert session["notice_hours"] == 105
    assert session["duration_minutes"] == 60
    assert session["postpone_count"] == 0
    assert session["held_at"] is None
    in_progress = fixtures.read_investigation(api, world["i1_id"], world["cmdr_headers"])
    assert in_progress["status"] == "IN_PROGRESS"
    assert in_progress["interview_held_count"] == 0

    # Coverage is complete and the state gate passes, so only the no-interview rule can refuse.
    premature = api.submit_findings(
        world["i1_id"],
        factories.findings_payload(
            complete_entries, summary="Both allegations covered, but nobody has been interviewed yet."
        ),
        world["inv_a_headers"],
    )

    validate_error(premature, "ERR_NO_INTERVIEW_HELD", 422)

    # Representation at tier 9 outranks the start-time rule at tier 11 though both are violated.
    still_requested = api.hold_interview_session(
        session["id"],
        factories.hold_payload(
            interview_summary="Attempted while representation was still requested."
        ),
        world["inv_a_headers"],
    )

    validate_error(still_requested, "ERR_REPRESENTATION_NOT_PRESENT", 409)

    too_early = api.hold_interview_session(
        session["id"],
        factories.hold_payload(
            interview_summary="Attempted before the scheduled start.",
            representation_status="REP_PRESENT",
        ),
        world["inv_a_headers"],
    )

    validate_error(too_early, "ERR_INTERVIEW_NOT_STARTED", 409)
    unchanged = fixtures.read_session(api, session["id"], world["inv_a_headers"])
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["representation_status"] == "REP_REQUESTED"

    first_move = get_success_data(
        api.postpone_interview_session(
            session["id"],
            factories.postpone_payload(
                "2026-08-07T09:00:00Z",
                "2026-08-07T10:00:00Z",
                BASE_CLOCK,
                postpone_reason="Representative unavailable.",
                hearing_room_id=world["room1_id"],
            ),
            OFFICER_REPRESENTATIVE_HEADERS,
        )
    )

    assert first_move["status"] == "SCHEDULED"
    assert first_move["postpone_count"] == 1
    assert_instant(first_move["scheduled_start"], "2026-08-07T09:00:00Z")

    second_move = get_success_data(
        api.postpone_interview_session(
            session["id"],
            factories.postpone_payload(
                "2026-08-09T09:00:00Z",
                "2026-08-09T10:00:00Z",
                BASE_CLOCK,
                postpone_reason="Second request by the representative.",
                hearing_room_id=world["room1_id"],
            ),
            OFFICER_REPRESENTATIVE_HEADERS,
        )
    )

    assert second_move["status"] == "SCHEDULED"
    assert second_move["postpone_count"] == 2
    assert_instant(second_move["scheduled_start"], "2026-08-09T09:00:00Z")

    third_move = api.postpone_interview_session(
        session["id"],
        factories.postpone_payload(
            "2026-08-11T09:00:00Z",
            "2026-08-11T10:00:00Z",
            BASE_CLOCK,
            postpone_reason="Third request, all interval checks would pass.",
            hearing_room_id=world["room1_id"],
        ),
        OFFICER_REPRESENTATIVE_HEADERS,
    )

    validate_error(third_move, "ERR_MAX_POSTPONEMENTS_REACHED", 409)
    capped = fixtures.read_session(api, session["id"], world["inv_a_headers"])
    assert capped["postpone_count"] == 2
    assert_instant(capped["scheduled_start"], "2026-08-09T09:00:00Z")

    fixtures.set_clock(api, "2026-08-09T09:00:00Z")
    held = fixtures.hold_session(
        api,
        world,
        session["id"],
        interview_summary="Subject interviewed with representation present.",
        representation_status="REP_PRESENT",
    )

    assert held["status"] == "HELD"
    assert_instant(held["held_at"], "2026-08-09T09:00:00Z")
    assert fixtures.read_investigation(api, world["i1_id"], world["cmdr_headers"])["interview_held_count"] == 1

    second_hold = api.hold_interview_session(
        session["id"],
        factories.hold_payload(
            interview_summary="Second attempt on a session that is already HELD.",
            representation_status="REP_PRESENT",
        ),
        world["inv_a_headers"],
    )

    validate_error(second_hold, "ERR_SESSION_STATE_INVALID", 409)
    assert fixtures.read_investigation(api, world["i1_id"], world["cmdr_headers"])["interview_held_count"] == 1

    partial = api.submit_findings(
        world["i1_id"],
        factories.findings_payload(
            [factories.finding_entry(world["a1_id"], 60, 40, False)],
            summary="Only one of the two allegations is covered.",
        ),
        world["inv_a_headers"],
    )

    validate_error(partial, "ERR_FINDINGS_INCOMPLETE", 422)
    unwritten = fixtures.read_allegation(api, world["a1_id"], world["cmdr_headers"])
    assert_two_dp(unwritten["evidence_weight_for"], 0.00, label="evidence_weight_for")
    assert_two_dp(unwritten["support_pct"], 0.00, label="support_pct")

    submitted = fixtures.submit_findings(api, world, world["i1_id"], complete_entries)

    assert submitted["status"] == "PENDING_REVIEW"
    assert_instant(submitted["findings_submitted_at"], "2026-08-09T09:00:00Z")
    first = fixtures.read_allegation(api, world["a1_id"], world["cmdr_headers"])
    second = fixtures.read_allegation(api, world["a2_id"], world["cmdr_headers"])
    assert_two_dp(first["support_pct"], 60.00, label="support_pct")
    assert first["preponderance_met"] is True
    assert_two_dp(second["support_pct"], 55.00, label="support_pct")
    assert second["preponderance_met"] is True
    assert fixtures.read_complaint(api, world["c_id"], world["cmdr_headers"])["status"] == "ADJUDICATION"


def two_allegations_at_adjudication(api):
    """Take the two-allegation file through a held interview and complete findings."""
    world = two_allegations_assigned_to_ahn(api)
    session = fixtures.schedule_session(
        api,
        world,
        world["i1_id"],
        scheduled_start="2026-08-05T09:00:00Z",
        scheduled_end="2026-08-05T10:00:00Z",
        notice_served_at=BASE_CLOCK,
    )
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    fixtures.hold_session(
        api,
        world,
        session["id"],
        interview_summary="Subject interviewed with representation present.",
    )
    fixtures.submit_findings(
        api,
        world,
        world["i1_id"],
        [
            factories.finding_entry(world["a1_id"], 60, 40, False),
            factories.finding_entry(world["a2_id"], 55, 45, False),
        ],
    )
    fixtures.set_clock(api, "2026-08-09T09:00:00Z")
    world.update({"s1_id": session["id"]})
    return world


def test_disposition_and_discipline_guards_each_report_their_own_code(api):
    """Both halves of the unsupported-disposition rule fire, then a late appeal is shut out.

    PRD: - **`PENDING → UNFOUNDED`** requires `evidence_weight_for` to be exactly 0 — the allegation is unfounded precisely when nothing at all supports it — and a request for `UNFOUNDED` with any non-zero supporting weight is refused with `ERR_DISPOSITION_NOT_SUPPORTED`.
    PRD: - **`PENDING → EXONERATED`** requires `policy_compliant` to have been recorded true by the findings; without it the request is refused with `ERR_DISPOSITION_NOT_SUPPORTED`.
    PRD: The owning complaint must be in `ADJUDICATION`, the allegation's `disposition` must still be `PENDING` — a second decision on the same allegation is `ERR_ALLEGATION_ALREADY_DISPOSED` — and segregation of duties is absolute: the acting commander's `X-User-ID` may be neither the investigation's `assigned_investigator_officer_id` nor the allegation's `subject_officer_id`, because the officer who built the case may not decide it and no officer may decide their own case.
    PRD: Third the substance: `sustained_allegation_count` must be 0, and a complaint that already carries a sustained finding is refused with `ERR_SUSTAINED_NOT_WITHDRAWABLE`.
    PRD: The discipline must be `IMPOSED`, otherwise `ERR_DISCIPLINE_STATE_INVALID`, and the logical clock must be at or before `appeal_deadline_at`; the boundary is inclusive, so a filing at exactly the deadline instant is timely, and a filing one instant later is refused with `ERR_APPEAL_WINDOW_CLOSED`.
    Design: Corner/errors/disposition_and_discipline_guards_each_report_their_own_code
    """
    world = two_allegations_at_adjudication(api)

    unfounded = api.dispose_allegation(
        world["a1_id"],
        factories.disposition_payload(
            "UNFOUNDED",
            rationale="Claimed unfounded even though 60 points support the allegation.",
        ),
        world["cmdr_headers"],
    )

    validate_error(unfounded, "ERR_DISPOSITION_NOT_SUPPORTED", 422)

    exonerated = api.dispose_allegation(
        world["a1_id"],
        factories.disposition_payload(
            "EXONERATED",
            rationale="Claimed lawful and proper even though the recorded finding is non-compliant.",
        ),
        world["cmdr_headers"],
    )

    validate_error(exonerated, "ERR_DISPOSITION_NOT_SUPPORTED", 422)

    sustained = fixtures.dispose_allegation(
        api,
        world,
        world["a1_id"],
        "SUSTAINED",
        rationale="Preponderance met at 60.00 percent.",
    )

    assert sustained["disposition"] == "SUSTAINED"
    assert sustained["prior_sustained_count_at_disposition"] == 0
    proposed = fixtures.discipline_for_allegation(api, world, world["a1_id"])
    assert proposed["status"] == "PROPOSED"
    assert proposed["offense_class"] == "B"
    assert_discipline_days(proposed, presumptive_prior_tier=0, presumptive_days=10)

    second_bite = api.dispose_allegation(
        world["a1_id"],
        factories.disposition_payload(
            "NOT_SUSTAINED", rationale="Second bite at an allegation that is already disposed."
        ),
        world["cmdr_headers"],
    )

    validate_error(second_bite, "ERR_ALLEGATION_ALREADY_DISPOSED", 409)
    assert fixtures.read_allegation(api, world["a1_id"], world["cmdr_headers"])["disposition"] == "SUSTAINED"

    # ADJUDICATION is a legal from-state and the code matches, so only the substance rule refuses.
    late_withdrawal = api.withdraw_complaint(
        world["c_id"],
        factories.withdrawal_payload(
            world["complaint"]["intake_reference_code"],
            withdrawal_reason="Reporting supervisor wants the file dropped after the sustained finding.",
        ),
        world["sup_headers"],
    )

    validate_error(late_withdrawal, "ERR_SUSTAINED_NOT_WITHDRAWABLE", 409)
    still_open = fixtures.read_complaint(api, world["c_id"], world["cmdr_headers"])
    assert still_open["status"] == "ADJUDICATION"
    assert still_open["closed_at"] is None
    assert still_open["sustained_allegation_count"] == 1

    early_appeal = api.file_appeal(
        proposed["id"],
        factories.appeal_payload(
            grounds="Filed against a discipline that is still only PROPOSED."
        ),
        OFFICER_REPRESENTATIVE_HEADERS,
    )

    validate_error(early_appeal, "ERR_DISCIPLINE_STATE_INVALID", 409)
    assert fixtures.read_discipline(api, proposed["id"], world["cmdr_headers"])["appeal_deadline_at"] is None

    imposed = get_success_data(
        api.impose_discipline(
            proposed["id"], factories.imposition_payload(), world["cmdr_headers"]
        )
    )

    assert imposed["status"] == "IMPOSED"
    assert_instant(imposed["imposed_at"], "2026-08-09T09:00:00Z")
    assert_instant(imposed["appeal_deadline_at"], "2026-08-24T09:00:00Z")

    fixtures.set_clock(api, "2026-08-24T09:00:01Z")
    too_late = api.file_appeal(
        proposed["id"],
        factories.appeal_payload(
            forum="CIVIL_SERVICE", grounds="Filed one second after the deadline."
        ),
        OFFICER_REPRESENTATIVE_HEADERS,
    )

    validate_error(too_late, "ERR_APPEAL_WINDOW_CLOSED", 422)
    assert fixtures.read_discipline(api, proposed["id"], world["cmdr_headers"])["status"] == "IMPOSED"
    appeals, appeal_meta = fixtures.rows(api.list_appeals(world["cmdr_headers"]))
    assert appeals == []
    assert appeal_meta["total_count"] == 0
    assert fixtures.read_allegation(api, world["a2_id"], world["cmdr_headers"])["disposition"] == "PENDING"


def two_officers_with_imposed_discipline(api):
    """One file sustains a class B allegation against Vance and another against a zero-salary Zane."""
    world = fixtures.seed_reference_data(api)
    zane = fixtures.create_officer(
        api,
        world["patrol_unit_id"],
        badge_number="PN-502",
        full_name="Officer Zane",
        annual_salary_cents=0,
        hire_date="2020-09-01T00:00:00Z",
    )
    complaint = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Two officers failed to file required reports on the same call.",
        incident_datetime="2026-07-20T22:00:00Z",
    )
    first = fixtures.attach_allegation(
        api,
        world,
        complaint["id"],
        subject_officer_id=world["subj_id"],
        allegation_type="NEGLECT_OF_DUTY",
        narrative="Vance filed no report.",
        offense_class="B",
    )
    second = fixtures.attach_allegation(
        api,
        world,
        complaint["id"],
        subject_officer_id=zane["id"],
        allegation_type="NEGLECT_OF_DUTY",
        narrative="Zane filed no report either.",
        offense_class="B",
    )
    investigation = fixtures.open_investigation(api, world, complaint["id"])
    fixtures.assign_investigation(
        api, world, investigation["id"], investigation["version"], world["inv_a_id"]
    )
    session = fixtures.schedule_session(
        api,
        world,
        investigation["id"],
        scheduled_start="2026-08-05T09:00:00Z",
        scheduled_end="2026-08-05T10:00:00Z",
        notice_served_at=BASE_CLOCK,
    )
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    fixtures.hold_session(
        api, world, session["id"], interview_summary="Vance interviewed with representation present."
    )
    fixtures.submit_findings(
        api,
        world,
        investigation["id"],
        [
            factories.finding_entry(first["id"], 70, 30, False),
            factories.finding_entry(second["id"], 70, 30, False),
        ],
    )
    fixtures.set_clock(api, "2026-08-09T09:00:00Z")
    fixtures.dispose_allegation(api, world, first["id"], "SUSTAINED", rationale="Sustained against Vance.")
    fixtures.dispose_allegation(api, world, second["id"], "SUSTAINED", rationale="Sustained against Zane.")
    vance_discipline = fixtures.discipline_for_allegation(api, world, first["id"])
    zane_discipline = fixtures.discipline_for_allegation(api, world, second["id"])
    imposed_v = get_success_data(
        api.impose_discipline(
            vance_discipline["id"], factories.imposition_payload(), world["cmdr_headers"]
        )
    )
    imposed_z = get_success_data(
        api.impose_discipline(
            zane_discipline["id"], factories.imposition_payload(), world["cmdr_headers"]
        )
    )
    world.update(
        {
            "zane_id": zane["id"],
            "c_id": complaint["id"],
            "a1_id": first["id"],
            "a2_id": second["id"],
            "i1_id": investigation["id"],
            "d_v_id": vance_discipline["id"],
            "d_z_id": zane_discipline["id"],
            "d_v": imposed_v,
            "d_z": imposed_z,
        }
    )
    return world


def test_appeal_reinstatement_and_award_guards_are_each_reachable(api):
    """Six post-appeal codes are reached in turn, ending on a zero-salary back-pay award.

    PRD: Filing stamps the appeal's `filed_at` from the logical clock and computes `days_to_file` as the elapsed span from the discipline's `imposed_at` to `filed_at` in whole days with any partial day discarded — an appeal filed at exactly a fifteen-day-old deadline has `days_to_file` 15.
    PRD: The appeal is created in `FILED` with `outcome` `PENDING` and `modified_days` null, recording the `discipline_id` it challenges, and the discipline moves `IMPOSED → APPEALED`.
    PRD: The decision then moves `HEARD → DECIDED` — again `ERR_APPEAL_STATE_INVALID` from any other status — stamping `decided_at`, writing the `outcome`, and driving the corresponding branch on the discipline.
    PRD: No appeal in `FILED` or `HEARD` may exist for any discipline arising from the complaint's allegations, otherwise `ERR_APPEAL_PENDING`.
    PRD: `modified_days` must be present, at least 0, and strictly less than the discipline's `final_days`; a negative value, an absent value, or a value that is not a genuine reduction is refused with `ERR_MODIFIED_DAYS_INVALID`.
    PRD: The reinstatement must still be `PENDING`, otherwise `ERR_REINSTATEMENT_ALREADY_FINALIZED`; `interim_earnings_cents` may not be negative, otherwise `ERR_INVALID_INTERIM_EARNINGS`; and the officer's `annual_salary_cents` must be strictly greater than 0, because a back-pay award cannot be computed from an unknown salary, otherwise `ERR_SALARY_UNKNOWN`.
    PRD: - **`OVERTURNED`.** The discipline moves `APPEALED → OVERTURNED` and `effective_days` is set to 0, and four cascades follow. First, `final_days` is subtracted from the officer's `imposed_suspension_days_total`, restoring exactly the pre-imposition value. Second, when that subtraction brings `imposed_suspension_days_total` to exactly 0, the officer returns `SUSPENDED → ACTIVE` and `suspension_end_date` is cleared; when other imposed discipline still stands the officer remains `SUSPENDED`. Third, because the discipline was overturned, the source allegation moves `SUSTAINED → OVERTURNED_ON_APPEAL`, the owning complaint's `sustained_allegation_count` falls by 1, and any `CredibilityDisclosure` whose `source_allegation_id` is that allegation moves `ACTIVE → EXPUNGED`, after which the officer's `credibility_disclosure_active` is recomputed over the disclosures that remain `ACTIVE`. Fourth, a `Reinstatement` is created in `PENDING` with `reversed_days` equal to the full `final_days`.
    PRD: **Reinstatement and back pay.** A reinstatement records the `appeal_id` of the decision that produced it, stamps `effective_date` from the logical clock at creation, and starts in `PENDING` with `interim_earnings_cents` 0 and `gross_back_pay_cents`, `net_back_pay_cents`, `interest_cents`, `total_award_cents` and `finalized_at` all null. An appeal's reinstatements are listed — the array is always of length 0 or 1 — with an optional `status` filter.
    PRD: Second, the amount owed for a period of a given number of days is the officer's `annual_salary_cents` multiplied by that number of days, divided by 260 working days in the year, rounded half up to a whole cent.
    PRD: Third, `net_back_pay_cents` is `gross_back_pay_cents` less `interim_earnings_cents`, floored at 0.
    PRD: Fourth, the elapsed span from the discipline's `imposed_at` to the finalize-time logical clock is taken in whole days with any partial day discarded, and `interest_cents` is `net_back_pay_cents` multiplied by five percent per annum, multiplied by that day count, divided by 365 days in the year, rounded half up to a whole cent — interest accrues on the net figure after the interim-earnings offset, never on the gross.
    PRD: Fifth, `total_award_cents` is `net_back_pay_cents` plus `interest_cents`.
    Design: Corner/errors/appeal_reinstatement_and_award_guards_are_each_reachable
    """
    world = two_officers_with_imposed_discipline(api)
    assert_discipline_days(world["d_v"], final_prior_tier=0, final_days=10, effective_days=10)
    assert_discipline_days(world["d_z"], final_prior_tier=0, final_days=10, effective_days=10)

    vance_appeal = get_success_data(
        api.file_appeal(
            world["d_v_id"],
            factories.appeal_payload(grounds="Vance appeals through the union."),
            OFFICER_REPRESENTATIVE_HEADERS,
        )
    )
    zane_appeal = get_success_data(
        api.file_appeal(
            world["d_z_id"],
            factories.appeal_payload(
                forum="CIVIL_SERVICE", grounds="Zane appeals to the civil service commission."
            ),
            OFFICER_REPRESENTATIVE_HEADERS,
        )
    )

    for appeal, discipline_id in ((vance_appeal, world["d_v_id"]), (zane_appeal, world["d_z_id"])):
        assert appeal["status"] == "FILED"
        assert appeal["outcome"] == "PENDING"
        assert appeal["modified_days"] is None
        assert appeal["discipline_id"] == discipline_id
        assert appeal["days_to_file"] == 0
        assert fixtures.read_discipline(api, discipline_id, world["cmdr_headers"])["status"] == "APPEALED"

    undecided = api.decide_appeal(
        vance_appeal["id"], factories.appeal_decision_payload("UPHELD"), APPEALS_OFFICER_HEADERS
    )

    validate_error(undecided, "ERR_APPEAL_STATE_INVALID", 409)

    closed = fixtures.close_investigation(api, world, world["i1_id"])

    assert closed["status"] == "CLOSED"
    assert fixtures.read_complaint(api, world["c_id"], world["cmdr_headers"])["status"] == "CLOSED"

    # No disclosure exists, so the credibility hold is silent and the appeal guard answers.
    purge = api.purge_complaint(
        world["c_id"],
        {"purge_reason": "Attempted purge while two appeals are still pending."},
        RECORDS_CUSTODIAN_HEADERS,
    )

    validate_error(purge, "ERR_APPEAL_PENDING", 409)
    assert fixtures.read_complaint(api, world["c_id"], RECORDS_CUSTODIAN_HEADERS)["purged_at"] is None

    heard = fixtures.hear_appeal(api, world, vance_appeal["id"])

    assert heard["status"] == "HEARD"

    not_a_reduction = api.decide_appeal(
        vance_appeal["id"],
        factories.appeal_decision_payload("MODIFIED", modified_days=10),
        APPEALS_OFFICER_HEADERS,
    )

    validate_error(not_a_reduction, "ERR_MODIFIED_DAYS_INVALID", 422)
    stalled = get_success_data(api.get_appeal(vance_appeal["id"], APPEALS_OFFICER_HEADERS))
    assert stalled["status"] == "HEARD"
    assert stalled["outcome"] == "PENDING"

    overturned = fixtures.decide_appeal(api, world, vance_appeal["id"], "OVERTURNED")

    assert overturned["status"] == "DECIDED"
    assert overturned["outcome"] == "OVERTURNED"
    reversed_discipline = fixtures.read_discipline(api, world["d_v_id"], world["cmdr_headers"])
    assert reversed_discipline["status"] == "OVERTURNED"
    assert_discipline_days(reversed_discipline, final_days=10, effective_days=0)
    restored = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(restored, imposed_suspension_days_total=0)
    assert restored["employment_status"] == "ACTIVE"
    assert restored["suspension_end_date"] is None

    reinstatement = fixtures.reinstatement_for_appeal(api, world, vance_appeal["id"])

    assert reinstatement["status"] == "PENDING"
    assert reinstatement["appeal_id"] == vance_appeal["id"]
    assert reinstatement["reversed_days"] == 10
    assert reinstatement["interim_earnings_cents"] == 0
    assert reinstatement["total_award_cents"] is None
    assert reinstatement["finalized_at"] is None

    negative = api.finalize_reinstatement(
        reinstatement["id"], factories.reinstatement_finalize_payload(-1), APPEALS_OFFICER_HEADERS
    )

    validate_error(negative, "ERR_INVALID_INTERIM_EARNINGS", 422)
    unfinalized = fixtures.reinstatement_for_appeal(api, world, vance_appeal["id"])
    assert unfinalized["status"] == "PENDING"
    assert unfinalized["finalized_at"] is None

    finalized = fixtures.finalize_reinstatement(api, world, reinstatement["id"], 0)

    assert finalized["status"] == "FINALIZED"
    assert_instant(finalized["finalized_at"], "2026-08-09T09:00:00Z")
    # One full ten-day period at 9,100,013 cents a year: 350,000.5 rounds half up to 350,001.
    assert finalized["gross_back_pay_cents"] == 350001
    assert finalized["net_back_pay_cents"] == 350001
    assert finalized["net_back_pay_cents"] > 0
    assert finalized["interest_cents"] == 0
    assert finalized["total_award_cents"] == finalized["net_back_pay_cents"] + finalized["interest_cents"]

    replayed = api.finalize_reinstatement(
        reinstatement["id"], factories.reinstatement_finalize_payload(0), APPEALS_OFFICER_HEADERS
    )

    validate_error(replayed, "ERR_REINSTATEMENT_ALREADY_FINALIZED", 409)
    settled = fixtures.reinstatement_for_appeal(api, world, vance_appeal["id"])
    assert settled["total_award_cents"] == finalized["total_award_cents"]

    fixtures.hear_appeal(api, world, zane_appeal["id"])
    fixtures.decide_appeal(api, world, zane_appeal["id"], "OVERTURNED")
    zane_reinstatement = fixtures.reinstatement_for_appeal(api, world, zane_appeal["id"])

    assert zane_reinstatement["reversed_days"] == 10

    unknown_salary = api.finalize_reinstatement(
        zane_reinstatement["id"],
        factories.reinstatement_finalize_payload(0),
        APPEALS_OFFICER_HEADERS,
    )

    validate_error(unknown_salary, "ERR_SALARY_UNKNOWN", 422)
    still_pending = fixtures.reinstatement_for_appeal(api, world, zane_appeal["id"])
    assert still_pending["status"] == "PENDING"
    assert still_pending["total_award_cents"] is None


def test_alert_plan_and_checkin_guards_each_report_their_own_code(api):
    """Four intervention guards, each at its own point of the plan-required to escalated cycle.

    PRD: For each officer who does already have an open alert, it refreshes that alert's `composite_score`, `score_variant`, `alert_level` and `breached_indicators` to the newly computed values and stamps the alert's `run_sequence`.
    PRD: It promotes an alert `OPEN → PLAN_REQUIRED` when the recomputed band reaches `ALERT` or `CRITICAL`, setting `review_due_at` to the promotion instant plus 30 whole days — the same 30-day rule that sets `review_due_at` at creation.
    PRD: The plan is created in `DRAFT` with `completed_checkin_count`, `on_time_checkin_count` and `concern_count` all 0, the alert's `plan_count` rises by 1 and its `version` rises by 1.
    PRD: The alert must be `OPEN` or `PLAN_REQUIRED`, otherwise `ERR_ALERT_STATE_INVALID`, and it must have no intervention plan attached — once a plan exists the alert must be worked through rather than dismissed — so a dismissal against an alert whose `plan_count` is not 0 is refused with `ERR_PLAN_EXISTS`.
    PRD: The plan must be `DRAFT`, otherwise `ERR_PLAN_STATE_INVALID`, and the owning alert must be `PLAN_REQUIRED`. Activation accepts an optional `activation_note`, moves the plan `DRAFT → ACTIVE`, stamps `activated_at` from the logical clock, sets `end_date` to `activated_at` plus `duration_days` whole days, materialises the check-in schedule, and moves the owning alert `PLAN_REQUIRED → PLAN_ACTIVE`.
    PRD: The interval between check-ins is `duration_days` divided by one more than `required_checkin_count`, discarding any remainder.
    PRD: One check-in row is then created for each `sequence_index` from 1 up to and including `required_checkin_count`, with `due_at` equal to `activated_at` plus the interval multiplied by that index, in whole days, carrying the time of day of `activated_at`.
    PRD: The check-in must be `PENDING` and its owning plan must be `ACTIVE`, otherwise `ERR_CHECKIN_NOT_PENDING`, and the acting supervisor must be the plan's monitoring supervisor, otherwise `ERR_NOT_PLAN_SUPERVISOR`.
    PRD: `compliance_score` is one hundred multiplied by `on_time_checkin_count` divided by `required_checkin_count`, less 15 for each concern recorded, floored at 0 and rounded half up to two decimal places.
    PRD: The plan must be `ACTIVE`, otherwise `ERR_PLAN_STATE_INVALID`, and no check-in of the plan may still be `PENDING`, otherwise `ERR_PENDING_CHECKINS`.
    PRD: - The plan moves `ACTIVE → ESCALATED` when `compliance_score` is below 80, **or** when another alert was created for the officer inside that window. A new alert during the monitoring window means the plan did not work even if every check-in was kept, so a perfect compliance score does not rescue it. The owning alert moves `PLAN_ACTIVE → ESCALATED` and keeps counting toward `open_alert_count`; because the alert escalated, the officer's `intervention_escalation_count` rises by 1 and the officer's `eis_alert_level` is raised one band, capped at `CRITICAL`.
    PRD: When an `officer_id` is supplied, that officer must have no alert in `ESCALATED` — an escalated alert must be answered with a replacement plan before a targeted rescore is accepted — and a request that names such an officer is refused with `ERR_ALERT_ALREADY_OPEN`.
    Design: Corner/errors/alert_plan_and_checkin_guards_each_report_their_own_code
    """
    world = fixtures.world_with_promoted_alert(api)
    run = world["run1"]

    assert_eis_run_counters(run, run_sequence=1, alerts_created=0, alerts_promoted=1)
    promoted = world["alert"]
    assert promoted["status"] == "PLAN_REQUIRED"
    assert promoted["alert_level"] == "ALERT"
    assert_two_dp(promoted["composite_score"], 63.75, label="alert.composite_score")
    assert promoted["run_sequence"] == 1
    assert promoted["plan_count"] == 0
    assert_instant(promoted["review_due_at"], "2026-08-31T00:00:00Z")

    plan = get_success_data(
        api.create_intervention_plan(
            world["al_id"],
            factories.intervention_plan_payload(
                world["al_v"],
                world["sup_id"],
                required_checkin_count=2,
                duration_days=30,
                interventions=["RETRAINING", "COUNSELING"],
            ),
            world["sup_headers"],
        )
    )

    assert plan["status"] == "DRAFT"
    assert plan["supervisor_officer_id"] == world["sup_id"]
    assert plan["completed_checkin_count"] == 0
    assert plan["on_time_checkin_count"] == 0
    assert plan["concern_count"] == 0
    assert plan["compliance_score"] is None
    with_plan = fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])
    assert with_plan["plan_count"] == 1
    assert with_plan["version"] == world["al_v"] + 1

    # PLAN_REQUIRED is a legal from-state for dismissal, so only the plan rule can refuse.
    dismissal = api.dismiss_eis_alert(
        world["al_id"],
        {"dismissal_reason": "Attempted dismissal although a draft plan is already attached."},
        world["cmdr_headers"],
    )

    validate_error(dismissal, "ERR_PLAN_EXISTS", 409)
    undismissed = fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])
    assert undismissed["status"] == "PLAN_REQUIRED"
    assert undismissed["dismissal_reason"] is None

    # Doyle is the monitoring supervisor, so the identity rule cannot be the reported cause.
    early_close = api.close_intervention_plan(
        plan["id"],
        {"closing_note": "Attempted close of a plan that has never been activated."},
        world["sup_headers"],
    )

    validate_error(early_close, "ERR_PLAN_STATE_INVALID", 409)

    activated = get_success_data(
        api.activate_intervention_plan(
            plan["id"], {"activation_note": "Monitoring begins."}, world["sup_headers"]
        )
    )

    assert activated["status"] == "ACTIVE"
    assert_instant(activated["activated_at"], BASE_CLOCK)
    assert_instant(activated["end_date"], "2026-08-31T00:00:00Z")
    check_ins, check_in_meta = fixtures.rows(
        api.list_plan_check_ins(plan["id"], world["sup_headers"])
    )
    assert check_in_meta["total_count"] == 2
    assert [row["sequence_index"] for row in check_ins] == [1, 2]
    assert [row["status"] for row in check_ins] == ["PENDING", "PENDING"]
    assert_instant(check_ins[0]["due_at"], "2026-08-11T00:00:00Z")
    assert_instant(check_ins[1]["due_at"], "2026-08-21T00:00:00Z")
    assert fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])["status"] == "PLAN_ACTIVE"

    first = fixtures.complete_check_in(api, world, check_ins[0]["id"], "CONCERN")

    assert first["status"] == "COMPLETED"
    assert first["outcome"] == "CONCERN"
    assert first["on_time"] is True
    counted = fixtures.read_plan(api, plan["id"], world["sup_headers"])
    assert counted["completed_checkin_count"] == 1
    assert counted["on_time_checkin_count"] == 1
    assert counted["concern_count"] == 1

    replay = api.complete_check_in(
        check_ins[0]["id"],
        factories.check_in_completion_payload(notes="Second attempt on a completed check-in."),
        world["sup_headers"],
    )

    validate_error(replay, "ERR_CHECKIN_NOT_PENDING", 409)
    uncounted = fixtures.read_plan(api, plan["id"], world["sup_headers"])
    assert uncounted["completed_checkin_count"] == 1
    assert uncounted["concern_count"] == 1

    fixtures.complete_check_in(api, world, check_ins[1]["id"], "CONCERN")
    closed = get_success_data(
        api.close_intervention_plan(
            plan["id"],
            {"closing_note": "Both check-ins done, both flagged as concerns."},
            world["sup_headers"],
        )
    )

    assert closed["status"] == "ESCALATED"
    assert closed["on_time_checkin_count"] == 2
    assert closed["concern_count"] == 2
    assert_two_dp(closed["compliance_score"], 70.00, label="compliance_score")
    escalated = fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])
    assert escalated["status"] == "ESCALATED"
    subject = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(subject, open_alert_count=1, intervention_escalation_count=1)
    assert_officer_risk(subject, eis_alert_level="CRITICAL")

    targeted = api.run_eis_sweep(
        factories.eis_run_payload(world["subj_id"]), world["cmdr_headers"]
    )

    validate_error(targeted, "ERR_ALERT_ALREADY_OPEN", 409)
    unchanged = fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])
    assert_two_dp(unchanged["composite_score"], 63.75, label="alert.composite_score")
    assert unchanged["status"] == "ESCALATED"


def test_an_expunged_disclosure_can_no_longer_be_released(api):
    """One disclosure released while ACTIVE, expunged by the reversal, then refused.

    PRD: Fifth, when the allegation's `allegation_type` is `UNTRUTHFULNESS`, a `CredibilityDisclosure` is created in `ACTIVE` with `permanent_retention` true and the officer's `credibility_disclosure_active` is set to true.
    PRD: The disclosure must be `ACTIVE`, otherwise `ERR_DISCLOSURE_NOT_ACTIVE` — an expunged or expired record may not be released. Acceptance raises `release_count` by 1 and stamps `last_released_at` from the logical clock.
    PRD: Class `A` — the most severe row — offers 30, 60 and 120 days for tiers 0, 1 and 2.
    PRD: `final_prior_tier` and `final_days` are computed under the final variant, `effective_days` is set to `final_days`, `imposed_at` is stamped from the logical clock, `appeal_deadline_at` is set to `imposed_at` plus 15 whole days, `final_days` is added to the officer's `imposed_suspension_days_total`, and — when `final_days` is at least 1 — an `ACTIVE` officer moves `ACTIVE → SUSPENDED` with `suspension_end_date` set to `effective_date` plus `final_days` days.
    PRD: The discipline moves `APPEALED → OVERTURNED` and `effective_days` is set to 0, and four cascades follow.
    PRD: First, `final_days` is subtracted from the officer's `imposed_suspension_days_total`, restoring exactly the pre-imposition value. Second, when that subtraction brings `imposed_suspension_days_total` to exactly 0, the officer returns `SUSPENDED → ACTIVE` and `suspension_end_date` is cleared; when other imposed discipline still stands the officer remains `SUSPENDED`.
    PRD: Third, because the discipline was overturned, the source allegation moves `SUSTAINED → OVERTURNED_ON_APPEAL`, the owning complaint's `sustained_allegation_count` falls by 1, and any `CredibilityDisclosure` whose `source_allegation_id` is that allegation moves `ACTIVE → EXPUNGED`, after which the officer's `credibility_disclosure_active` is recomputed over the disclosures that remain `ACTIVE`.
    Design: Corner/errors/an_expunged_disclosure_can_no_longer_be_released
    """
    world = fixtures.world_with_sustained_allegation(
        api,
        evidence_weight_for=80,
        evidence_weight_against=20,
        allegation_type="UNTRUTHFULNESS",
        offense_class="A",
        reported_allegation_types=["UNTRUTHFULNESS"],
        complaint_overrides={
            "narrative": "Officer gave a false account in a written report.",
            "incident_datetime": "2026-07-20T22:00:00Z",
        },
    )
    disclosure = fixtures.disclosure_for_allegation(api, world, world["a1_id"])

    assert disclosure["status"] == "ACTIVE"
    assert disclosure["basis"] == "UNTRUTHFULNESS_SUSTAINED"
    assert disclosure["source_allegation_id"] == world["a1_id"]
    assert disclosure["officer_id"] == world["subj_id"]
    assert disclosure["permanent_retention"] is True
    assert disclosure["release_count"] == 0
    assert disclosure["last_released_at"] is None
    flagged = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(flagged, credibility_disclosure_active=True)

    released = get_success_data(
        api.release_credibility_disclosure(
            disclosure["id"],
            {"requesting_party": "County Prosecutor, case 26-CR-1187"},
            RECORDS_CUSTODIAN_HEADERS,
        )
    )

    assert released["status"] == "ACTIVE"
    assert released["release_count"] == 1
    assert_instant(released["last_released_at"], "2026-08-05T09:00:00Z")

    imposed = get_success_data(
        api.impose_discipline(
            world["d1_id"],
            factories.imposition_payload(effective_date="2026-08-10T00:00:00Z"),
            world["cmdr_headers"],
        )
    )

    assert imposed["status"] == "IMPOSED"
    assert imposed["offense_class"] == "A"
    assert_discipline_days(
        imposed,
        presumptive_prior_tier=0,
        presumptive_days=30,
        final_prior_tier=0,
        final_days=30,
        effective_days=30,
    )
    assert_instant(imposed["imposed_at"], "2026-08-05T09:00:00Z")
    suspended = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert suspended["employment_status"] == "SUSPENDED"
    assert_officer_ledgers(suspended, imposed_suspension_days_total=30)
    assert_instant(suspended["suspension_end_date"], "2026-09-09T00:00:00Z")

    appeal = get_success_data(
        api.file_appeal(
            world["d1_id"],
            factories.appeal_payload(
                "ARBITRATION",
                grounds="The arbitrator is asked to reject the untruthfulness finding outright.",
            ),
            world["rep_headers"],
        )
    )

    assert appeal["status"] == "FILED"
    assert appeal["outcome"] == "PENDING"
    assert fixtures.read_discipline(api, world["d1_id"], world["cmdr_headers"])["status"] == "APPEALED"

    heard = fixtures.hear_appeal(api, world, appeal["id"])

    assert heard["status"] == "HEARD"

    decided = fixtures.decide_appeal(api, world, appeal["id"], "OVERTURNED")

    assert decided["status"] == "DECIDED"
    assert decided["outcome"] == "OVERTURNED"
    reversed_discipline = fixtures.read_discipline(api, world["d1_id"], world["cmdr_headers"])
    assert reversed_discipline["status"] == "OVERTURNED"
    assert reversed_discipline["effective_days"] == 0
    allegation = fixtures.read_allegation(api, world["a1_id"], world["cmdr_headers"])
    assert allegation["disposition"] == "OVERTURNED_ON_APPEAL"
    expunged = fixtures.read_disclosure(api, disclosure["id"], RECORDS_CUSTODIAN_HEADERS)
    assert expunged["status"] == "EXPUNGED"
    assert expunged["release_count"] == 1
    cleared = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(
        cleared, credibility_disclosure_active=False, imposed_suspension_days_total=0
    )
    assert cleared["employment_status"] == "ACTIVE"
    assert cleared["suspension_end_date"] is None

    refused = api.release_credibility_disclosure(
        disclosure["id"],
        {"requesting_party": "Defense counsel, case 26-CR-1187"},
        RECORDS_CUSTODIAN_HEADERS,
    )

    validate_error(refused, "ERR_DISCLOSURE_NOT_ACTIVE", 409)
    untouched = fixtures.read_disclosure(api, disclosure["id"], RECORDS_CUSTODIAN_HEADERS)
    assert untouched["status"] == "EXPUNGED"
    assert untouched["release_count"] == 1
    assert_instant(untouched["last_released_at"], "2026-08-05T09:00:00Z")
