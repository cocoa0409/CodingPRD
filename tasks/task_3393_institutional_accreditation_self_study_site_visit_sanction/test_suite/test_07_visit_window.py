"""Site visit scheduling: report clock gate, cancel loop, buffered window conflicts."""
from test_helpers import (
    ApiErrorId,
    POST_VISIT_CLOCK_ISO,
    accept_assignment,
    add_evidence_set,
    adjudicate_application,
    assemble_review_team,
    cancel_visit,
    confirm_team,
    create_assurance_argument,
    create_eligibility_application,
    create_institution,
    create_review_cycle,
    create_reviewer,
    file_eligibility_application,
    file_team_report,
    get_review_team,
    get_reviewer,
    lock_argument,
    make_reviewer_headers,
    schedule_visit,
    schedule_visit_payload,
    set_logical_clock,
    setup_visit_scheduled,
    advance_cycle,
    file_report_payload,
    submit_argument,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS


def test_visit_report_before_window_end_rejected(api):
    """PRD section 3.6: "Filing before the logical clock has reached `visit_end_at` is rejected with `ERR_INVALID_STATE`, and only the chair may file, under the same `ERR_REVIEWER_NOT_ASSIGNED` binding."

    Design: Corner/state_machines/visit_report_before_window_end_rejected
    """
    ctx = setup_visit_scheduled()
    team = ctx["team"]
    chair_id = team["chair_reviewer_id"]

    # The logical clock still reads the default 2026-09-01, before the visit end.
    early = api.file_team_report(
        team["id"], file_report_payload(), make_reviewer_headers(chair_id)
    )
    validate_error(early, ApiErrorId.ERR_INVALID_STATE)

    set_logical_clock(POST_VISIT_CLOCK_ISO)
    filed = file_team_report(team["id"], chair_id)
    assert filed["status"] == "REPORT_FILED"


def test_cancel_visit_releases_window_for_reschedule(api):
    """PRD section 3.6: "Staff may cancel a scheduled visit, which returns the team to `CONFIRMED` and releases the window — the cancellation-and-rescheduling loop may repeat."

    Design: Corner/state_machines/cancel_visit_releases_window_and_allows_reschedule
    """
    ctx = setup_visit_scheduled()
    team = ctx["team"]

    cancelled = cancel_visit(team["id"])
    assert cancelled["status"] == "CONFIRMED"
    assert cancelled["visit_start_at"] is None
    assert cancelled["visit_end_at"] is None

    rescheduled = schedule_visit(team["id"], team["chair_reviewer_id"])
    assert rescheduled["status"] == "VISIT_SCHEDULED"
    assert rescheduled["visit_start_at"] is not None


def test_reviewer_window_conflict_includes_travel_buffer(api, staff_headers):
    """PRD section 3.6: "Each visit's effective window is a half-open interval; for an `ON_SITE` modality it runs from one day before the visit's start to one day after its end — a one-day travel buffer on each side — while a `VIRTUAL` visit carries no buffer and its effective window is the visit's own half-open interval."
    PRD section 3.6: "Scheduling also runs a window-conflict check across every accepted member of the team: no accepted member may already hold an effective visit window that intersects the proposed one."
    PRD section 3.6: "A detected conflict is rejected with `ERR_REVIEWER_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/reviewer_window_conflict_with_modality_buffer
    """
    ctx_a = setup_visit_scheduled()
    chair_a = ctx_a["reviewers"]["chair"]
    shared_member = ctx_a["reviewers"]["members"][0]

    institution_b = create_institution(
        legal_name="Second Candidate College", legal_status="PRIVATE_FORPROFIT",
        state_code="MO", fte_enrollment=300, degree_levels_offered=["ASSOCIATE"],
    )
    institution_b_id = institution_b["id"]
    # Screen team A's chair out of institution B's pool; this touches no
    # assignment tied to institution A.
    conflicted = api.update_reviewer(
        chair_a["id"], {"declared_conflict_institution_ids": [institution_b_id]},
        TEST_USERS["staff_headers"],
    )
    validate_success(conflicted)

    application_b = create_eligibility_application(institution_b_id, pathway="ACCELERATED")
    file_eligibility_application(application_b["id"], institution_b_id)
    adjudicate_application(application_b["id"], "APPROVE")
    cycle_b = create_review_cycle(institution_b_id)
    cycle_b = advance_cycle(cycle_b["id"], "advance B to MATERIALS_OPEN")
    argument_b = create_assurance_argument(cycle_b["id"], institution_b_id)
    add_evidence_set(argument_b["id"], institution_b_id)
    submit_argument(argument_b["id"], institution_b_id)
    cycle_b = advance_cycle(cycle_b["id"], "advance B to EVALUATION_ACTIVE")

    chair_b = create_reviewer(
        full_name="Chair Beta",
        specialty_criteria=["CRIT_MISSION", "CRIT_INTEGRITY", "CRIT_TEACHING_QUALITY",
                            "CRIT_TEACHING_EVALUATION", "CRIT_RESOURCES_PLANNING"],
        quality_rating=4.95,
        prior_chair_count=2,
    )
    team_b = assemble_review_team(cycle_b["id"], "VIRTUAL")
    assert team_b["chair_reviewer_id"] == chair_b["id"]

    for reviewer in [chair_b, *ctx_a["reviewers"]["members"]]:
        accept_assignment(team_b["id"], reviewer["id"])
    confirm_team(team_b["id"])
    lock_argument(argument_b["id"])

    # Team A runs ON_SITE 2027-03-10T09:00 -> 2027-03-12T17:00, buffered to
    # [2027-03-09T09:00, 2027-03-13T17:00); the VIRTUAL window below starts
    # inside that buffered tail.
    conflict = api.schedule_visit(
        team_b["id"],
        schedule_visit_payload("2027-03-13T16:00:00Z", "2027-03-13T20:00:00Z"),
        make_reviewer_headers(chair_b["id"]),
    )
    validate_error(conflict, ApiErrorId.ERR_REVIEWER_WINDOW_CONFLICT)

    team_b_after = get_review_team(team_b["id"])
    assert team_b_after["status"] == "CONFIRMED"
    assert team_b_after["visit_start_at"] is None
    assert get_reviewer(shared_member["id"])["current_assignment_count"] == 2
