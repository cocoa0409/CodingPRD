"""Optimistic concurrency on the two versioned parents, and immediate consistency."""

from test_helpers import (
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_instant_equals
from test_helpers.fixtures import CD, MR, PM


def test_01_the_second_attendance_write_needs_the_re_read_session_version():
    """Only the OCC field differs between the refused call and the accepted one.

    PRD §2.9: "If that value does not equal the session's current `version`, the
    request is rejected with `ERR_STALE_SESSION_VERSION` and HTTP 412; the
    client's picture of the session … is out of date and must be re-read before
    the write is retried" and "Both endpoints increment the parent's `version` by
    one on success, so a client that submits two members with the same observed
    version will have the second rejected."

    Design: Corner/cross_cutting_layers/stale_session_version_rejects_the_second_attendance_write
    """
    world = fx.setup_session_ready_world(
        session_overrides={"scheduled_start": "2026-08-10T10:00:00Z",
                           "duration_minutes": 60, "capacity_slots": 12},
        athlete_specs=[
            {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}},
            {"athlete": {"legal_name": "Ivan Petrov", "birth_date": "2003-10-01"}},
        ],
        attendance_clock="2026-08-10T11:00:00Z")
    session = world["session"]
    version_1 = session["version"]

    first = fx.record_attendance(session["id"], world["athletes"][0]["id"],
                                version_1, minutes_present=60)
    assert first["status"] == "COUNTED"
    version_2 = fx.session_version(session["id"])
    assert version_2 == version_1 + 1

    payload = f.create_attendance_payload(world["athletes"][1]["id"], version_1,
                                          minutes_present=50)
    validate_error(
        api_client.create_attendance_record(session["id"], payload, PM),
        ApiErrorId.ERR_STALE_SESSION_VERSION.value, 412)
    mid = validate_success(api_client.get_practice_session(session["id"], PM))
    assert mid["recorded_attendance_count"] == 1
    assert mid["version"] == version_2

    retry = f.create_attendance_payload(world["athletes"][1]["id"], version_2,
                                        minutes_present=50)
    accepted = validate_success(
        api_client.create_attendance_record(session["id"], retry, PM), 201)
    assert accepted["status"] == "COUNTED"
    assert accepted["required_minutes"] == 45
    assert accepted["counted_minutes"] == 50

    after = validate_success(api_client.get_practice_session(session["id"], PM))
    assert after["recorded_attendance_count"] == 2
    assert after["version"] == version_2 + 1

    second_athlete = validate_success(
        api_client.get_athlete(world["athletes"][1]["id"], PM))
    assert second_athlete["cumulative_practice_minutes"] == 50
    assert second_athlete["counted_session_count"] == 1
    assert fx.get_program(world["program"]["id"])["program_practice_minutes"] == 110


def test_02_the_partner_add_needs_the_re_read_team_version():
    """The roster append is legal; only the stale version rejects it.

    PRD §2.9: "a request that appends a member to a unified team must carry
    `expected_team_version` … and a mismatch against the team's current `version`
    is rejected with `ERR_STALE_TEAM_VERSION` and HTTP 412 — the roster whose
    counts, age span and compliance the writer reasoned about no longer exists";
    PRD §3.5: "A successful append increments the
    team's `version` by one, pushes the id onto `athlete_ids` or
    `partner_volunteer_ids` in insertion order, and re-derives the whole
    composition."

    Design: Corner/cross_cutting_layers/stale_team_version_rejects_the_second_member_add
    """
    world = fx.setup_entry_ready_world(
        athlete_specs=[
            {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}}])
    partner, partner_credential = fx.create_certified_partner(
        world["program"]["id"], "Noel Barr", "noel@rb.example", "2001-07-14",
        screening_overrides={"completed_on": "2026-07-02",
                             "vendor_reference": "BGS-2001"},
        training_overrides={"completed_on": "2026-07-06"})
    assert partner_credential["status"] == "CERTIFIED"

    team = fx.create_unified_team(world["season"]["id"],
                                 team_name="Riverbend Unified Reds")
    version_1 = team["version"]
    assert team["roster_status"] == "FORMING"

    team = fx.add_team_member(team["id"], "ATHLETE",
                             world["athletes"][0]["id"], version_1)
    version_2 = team["version"]
    assert version_2 == version_1 + 1
    assert team["athlete_count"] == 1

    validate_error(api_client.add_unified_team_member(
        team["id"],
        f.add_team_member_payload("PARTNER", partner["id"], version_1), CD),
        ApiErrorId.ERR_STALE_TEAM_VERSION.value, 412)
    mid = validate_success(api_client.get_unified_team(team["id"], CD))
    assert mid["athlete_count"] == 1
    assert mid["partner_count"] == 0
    assert mid["roster_status"] == "FORMING"
    assert mid["version"] == version_2

    accepted = fx.add_team_member(team["id"], "PARTNER", partner["id"], version_2)
    assert accepted["athlete_count"] == 1
    assert accepted["partner_count"] == 1
    assert accepted["version"] == version_2 + 1
    assert accepted["roster_status"] == "NON_COMPLIANT"
    assert accepted["partner_volunteer_ids"] == [partner["id"]]
    assert accepted["athlete_ids"] == [world["athletes"][0]["id"]]


def test_03_the_approval_and_all_its_consequences_are_readable_at_once():
    """No settling step: the review response and the next two reads agree.

    PRD §2.11: "This system is immediately consistent. There is no deferred
    reconciliation queue: when an operation changes something a counter depends
    on, that counter is recomputed inside the same request, and the response body
    already reflects the new value"; PRD §3.2: approval sets
    `registration_expires_on` to
    "whichever comes first" of the form's own expiry and 365 days after the
    approval clock date.

    Design: Corner/consistency_model/approval_cascade_is_visible_in_the_same_response
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    assert fx.get_program(program["id"])["active_athlete_count"] == 0
    athlete = fx.register_athlete(program["id"])
    form = fx.file_medical_form(athlete["id"], exam_date="2026-06-15")

    approved = validate_success(api_client.review_medical_form(
        form["id"], f.review_medical_form_payload(decision="APPROVE"), MR), 200)
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == "reviewer-1"
    assert approved["expires_on"] == "2029-06-14"
    assert_instant_equals(approved["approved_at"], "2026-08-01T00:00:00.000Z",
                          "approved_at")

    stored = validate_success(api_client.get_athlete(athlete["id"], MR))
    assert stored["registration_status"] == "ACTIVE"
    assert stored["medical_status"] == "CLEARED"
    assert stored["current_medical_form_id"] == form["id"]
    assert stored["registration_expires_on"] == "2027-08-01"

    after = fx.get_program(program["id"])
    assert after["active_athlete_count"] == 1


def test_04_the_sweep_response_and_an_immediate_re_read_are_identical():
    """The checkpoint's own body is already the post-sweep truth.

    PRD §3.9 step six: "all of the program's counters, its
    `expired_credential_ratio` and its `compliance_posture` are recomputed from
    the post-sweep world … `sweep_epoch` is incremented by exactly one, and
    `last_sweep_at` is stamped with the logical clock instant. Because step six
    runs last, the posture the checkpoint returns already reflects every expiry,
    lapse and escalation the earlier steps produced."

    Design: Corner/consistency_model/sweep_counters_match_the_sweep_response_on_immediate_reread
    """
    world = fx.setup_program_with_certified_coach()
    athlete, _form = fx.create_active_athlete(world["program"]["id"])
    before = fx.get_program(world["program"]["id"])
    assert before["sweep_epoch"] == 0
    assert before["last_sweep_at"] is None

    fx.set_clock("2026-08-02T00:00:00Z")
    swept = validate_success(api_client.run_compliance_sweep(
        world["program"]["id"], f.compliance_sweep_payload(), PM), 200)
    assert swept["sweep_epoch"] == 1
    assert swept["certified_coach_count"] == 1
    assert swept["credential_denominator_count"] == 1
    assert swept["expired_credential_count"] == 0
    assert swept["expired_credential_ratio"] == 0.0
    assert swept["active_athlete_count"] == 1
    assert swept["compliance_posture"] == "OPEN"
    assert_instant_equals(swept["last_sweep_at"], "2026-08-02T00:00:00.000Z",
                          "last_sweep_at")

    reread = fx.get_program(world["program"]["id"])
    for field in ("sweep_epoch", "certified_coach_count",
                  "credential_denominator_count", "expired_credential_count",
                  "expired_credential_ratio", "active_athlete_count",
                  "compliance_posture"):
        assert reread[field] == swept[field], field
    assert_instant_equals(reread["last_sweep_at"], swept["last_sweep_at"],
                          "last_sweep_at")

    credential = validate_success(
        api_client.get_credential(world["credential"]["id"], PM))
    assert credential["status"] == "CERTIFIED"
    assert credential["expires_on"] == "2027-07-05"
    stored_athlete = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert stored_athlete["registration_status"] == "ACTIVE"
    assert stored_athlete["registration_expires_on"] == "2027-08-01"
