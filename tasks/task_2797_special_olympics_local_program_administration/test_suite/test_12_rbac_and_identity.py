"""Authentication, role authorisation and the two identity-backed 403s."""

from test_helpers import (
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    CD,
    HSL,
    MR,
    OFFICER_1,
    OFFICER_2,
    OFFICER_3,
    OFFICER_5,
    PM,
)
from test_helpers.test_users import make_coach_headers


def _role_matrix_world(season_overrides=None):
    """One program carrying work for all six roles at once."""
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    volunteer = fx.add_volunteer(program["id"])
    credential = fx.open_credential(volunteer["id"], officer=OFFICER_1)
    fx.record_screening(credential["id"], officer=OFFICER_1,
                        completed_on="2026-07-01", result="CLEAR",
                        vendor_reference="BGS-1001")
    credential = fx.record_training(credential["id"], officer=OFFICER_2,
                                    completed_on="2026-07-05",
                                    curriculum_code="PB-CORE-2026")
    assert credential["status"] == "READY_TO_CERTIFY"
    athlete = fx.register_athlete(program["id"])
    form = fx.file_medical_form(athlete["id"], exam_date="2026-06-15")
    assert form["status"] == "SUBMITTED"
    overrides = {"practice_minimum_sessions": 0, "practice_minimum_minutes": 0,
                 "registration_deadline": "2026-09-15",
                 "divisioning_date": "2026-09-18",
                 "competition_date": "2026-10-05"}
    overrides.update(season_overrides or {})
    season = fx.create_season(program["id"], **overrides)
    return {"program": program, "volunteer": volunteer,
            "credential": credential, "athlete": athlete, "form": form,
            "season": season}


def test_01_all_six_roles_exercise_their_own_operations_in_one_chain():
    """Six authorised roles, six successes, each at its declared status code.

    PRD §2.1: "A `ProgramManager` is the local program administrator … A
    `CredentialingOfficer` opens credentialing files, records background
    screening and protective-behaviours training, and certifies credentials. A
    `MedicalReviewer` is the clinician who approves or rejects athlete medical
    forms … A `Coach` is a certified coach who runs practices. A
    `CompetitionDirector` owns the competition pipeline end to end … A
    `HealthScreeningLead` runs the Healthy Athletes screening tent."

    Design: Corner/rbac/each_role_exercises_one_of_its_own_operations
    """
    world = _role_matrix_world()

    certified = validate_success(api_client.certify_credential(
        world["credential"]["id"], f.certify_credential_payload(), OFFICER_3), 200)
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == "officer-3"

    reviewed = validate_success(api_client.review_medical_form(
        world["form"]["id"], f.review_medical_form_payload(decision="APPROVE"),
        MR), 200)
    assert reviewed["status"] == "APPROVED"
    assert reviewed["reviewed_by_user_id"] == "reviewer-1"
    athlete = validate_success(api_client.get_athlete(world["athlete"]["id"], PM))
    assert athlete["registration_status"] == "ACTIVE"

    screening = validate_success(api_client.create_health_screening(
        f.create_health_screening_payload(
            world["athlete"]["id"], event_name="Riverbend Fall Games Healthy Athletes",
            discipline="FUNFITNESS", screened_on="2026-07-30",
            finding_severity="ROUTINE"), HSL), 201)
    assert screening["referral_status"] == "NOT_REQUIRED"

    opened = validate_success(
        api_client.open_season_practice(world["season"]["id"], {}, CD), 200)
    assert opened["status"] == "PRACTICE_OPEN"

    coach = make_coach_headers(world["volunteer"]["id"])
    session = validate_success(api_client.create_practice_session(
        f.create_practice_session_payload(
            world["season"]["id"], world["credential"]["id"],
            scheduled_start="2026-08-12T10:00:00Z", duration_minutes=60,
            capacity_slots=12), coach), 201)
    assert session["status"] == "SCHEDULED"

    entry = validate_success(api_client.create_competition_entry(
        f.create_entry_payload(world["season"]["id"], world["athlete"]["id"],
                               skill_score=40.0), CD), 201)
    assert entry["status"] == "SUBMITTED"

    contribution = validate_success(api_client.create_contribution(
        world["program"]["id"],
        f.create_contribution_payload(contribution_type="CASH_RECEIPT",
                                      designation="GENERAL",
                                      stated_value_cents=100_000,
                                      received_on="2026-08-01"), PM), 201)
    assert contribution["status"] == "RECEIVED"
    assert contribution["recognized_value_cents"] == 100_000
    assert fx.get_program(world["program"]["id"])["recognized_support_cents"] == \
        100_000


def test_02_the_wrong_role_is_403_on_four_otherwise_valid_requests():
    """The role check at priority 2 fires before any state or existence check.

    PRD §2.1: "Once authentication succeeds, the acting role must appear in the
    authorised-role list of the endpoint being called, as tabulated in §4; if it
    does not, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)";
    PRD §2.6 orders "**Role authorisation**" second, above existence and state.

    Design: Corner/rbac/forbidden_role_denied_on_four_exclusive_operations
    """
    world = _role_matrix_world()
    # PRD §3.4: opening the practice window "requires the program to hold at
    # least one live certified coach credential", so a second coach is certified
    # here while world["credential"] stays READY_TO_CERTIFY for the 403 probe.
    fx.setup_program_with_second_coach(world)
    validate_success(api_client.open_season_practice(world["season"]["id"], {}, CD))
    coach = make_coach_headers(world["volunteer"]["id"])

    forbidden = [
        api_client.certify_credential(world["credential"]["id"],
                                      f.certify_credential_payload(), coach),
        api_client.review_medical_form(
            world["form"]["id"],
            f.review_medical_form_payload(decision="APPROVE"), PM),
        api_client.create_competition_entry(
            f.create_entry_payload(world["season"]["id"], world["athlete"]["id"],
                                   skill_score=40.0), OFFICER_1),
        api_client.create_health_screening(
            f.create_health_screening_payload(
                world["athlete"]["id"],
                event_name="Riverbend Fall Games Healthy Athletes",
                discipline="FUNFITNESS", screened_on="2026-07-30",
                finding_severity="ROUTINE"), CD),
    ]
    for response in forbidden:
        error = validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
        assert response.json()["response_type"] == "error"
        assert isinstance(error["message"], str) and error["message"]

    credential = validate_success(
        api_client.get_credential(world["credential"]["id"], OFFICER_1))
    assert credential["status"] == "READY_TO_CERTIFY"
    assert credential["expires_on"] is None
    forms = api_client.list_athlete_medical_forms(world["athlete"]["id"], PM,
                                                 params={"limit": 100}).json()
    assert forms["data"][0]["status"] == "SUBMITTED"
    assert forms["data"][0]["reviewed_by_user_id"] is None
    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["entry_count"] == 0
    screenings = api_client.list_athlete_health_screenings(
        world["athlete"]["id"], PM, params={"limit": 100})
    assert screenings.json()["meta"]["total_count"] == 0

    accepted = validate_success(api_client.certify_credential(
        world["credential"]["id"], f.certify_credential_payload(), OFFICER_3), 200)
    assert accepted["status"] == "CERTIFIED"


_NO_ROLE_HEADERS = {"X-User-ID": "manager-1", "Content-Type": "application/json"}
_UNDECLARED_ROLE_HEADERS = {"X-User-ID": "manager-1", "X-User-Role": "Treasurer",
                            "Content-Type": "application/json"}
_NO_USER_HEADERS = {"X-User-Role": "ProgramManager",
                    "Content-Type": "application/json"}


def test_03_authentication_is_evaluated_before_anything_else():
    """A missing role, an undeclared role and a missing user id are all 401.

    PRD §2.1: "If `X-User-Role` is absent, or carries a value that is not one of
    the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401); the same code and status are returned when `X-User-ID` is absent
    on any state-changing request. Authentication is evaluated before anything
    else about the request is considered."

    Design: Corner/rbac/unauthenticated_outranks_every_later_check
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    athlete = fx.register_athlete(program["id"])

    payload = f.create_medical_form_payload(exam_date="2026-06-15")
    created = validate_success(
        api_client.create_medical_form(athlete["id"], payload, PM), 201)
    assert created["status"] == "SUBMITTED"

    for headers in (_NO_ROLE_HEADERS, _UNDECLARED_ROLE_HEADERS, _NO_USER_HEADERS):
        error = validate_error(
            api_client.create_medical_form(athlete["id"], payload, headers),
            ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        assert isinstance(error["message"], str) and error["message"]

    validate_error(api_client.review_medical_form(
        "88888888-8888-4888-8888-888888888888",
        f.review_medical_form_payload(), _NO_ROLE_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    forms = api_client.list_athlete_medical_forms(athlete["id"], PM,
                                                 params={"limit": 100}).json()
    assert forms["meta"]["total_count"] == 1
    assert forms["data"][0]["id"] == created["id"]


def test_04_three_distinct_officers_are_required_across_the_three_steps():
    """The rule is enforced on the branch endpoints too, not only at certify.

    PRD §2.8: "the user who records a credential's background screening may not
    also record that credential's protective-behaviours training… the user who
    certifies a credential may not be the user who recorded its screening…the
    certifying user may not be the user who recorded its training", and "the
    rule is enforced on all three of those endpoints rather than only at
    certification time — an attempt to record the second branch under the same
    user who recorded the first is refused where it is made."

    Design: Corner/rbac/segregation_of_duties_across_the_three_credential_steps
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()

    volunteer_a = fx.add_volunteer(program["id"])
    credential_a = fx.open_credential(volunteer_a["id"], officer=OFFICER_1)
    fx.record_screening(credential_a["id"], officer=OFFICER_1,
                        completed_on="2026-07-01", result="CLEAR",
                        vendor_reference="BGS-1001")
    fx.record_training(credential_a["id"], officer=OFFICER_2,
                       completed_on="2026-07-05",
                       curriculum_code="PB-CORE-2026")

    volunteer_b = fx.add_volunteer(program["id"], full_name="Ken Obi",
                                  email="ken@rb.example",
                                  date_of_birth="1986-09-09",
                                  volunteer_class="COACH")
    credential_b = fx.open_credential(volunteer_b["id"], officer=OFFICER_5)
    screened_b = fx.record_screening(credential_b["id"], officer=OFFICER_5,
                                     completed_on="2026-07-02", result="CLEAR",
                                     vendor_reference="BGS-3001")
    assert screened_b["status"] == "SCREENING_CLEARED"

    validate_error(api_client.certify_credential(
        credential_a["id"], f.certify_credential_payload(), OFFICER_1),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    validate_error(api_client.certify_credential(
        credential_a["id"], f.certify_credential_payload(), OFFICER_2),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    validate_error(api_client.record_credential_training(
        credential_b["id"],
        f.record_training_payload(completed_on="2026-07-06",
                                 curriculum_code="PB-CORE-2026"), OFFICER_5),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    stored_a = validate_success(
        api_client.get_credential(credential_a["id"], OFFICER_1))
    assert stored_a["status"] == "READY_TO_CERTIFY"
    assert stored_a["certified_by_user_id"] is None
    assert stored_a["certified_at"] is None
    assert stored_a["expires_on"] is None

    stored_b = validate_success(
        api_client.get_credential(credential_b["id"], OFFICER_1))
    assert stored_b["status"] == "SCREENING_CLEARED"
    assert stored_b["training_completed_on"] is None
    assert stored_b["training_recorded_by_user_id"] is None

    after = fx.get_program(program["id"])
    assert after["certified_coach_count"] == 0
    assert after["compliance_posture"] == "FROZEN"


def test_05_a_coach_may_only_act_under_a_credential_they_hold():
    """Identity is checked against the credential, not merely against the role.

    PRD §2.1: "when a coach schedules a practice session, cancels one, or
    records attendance at one, the credential named by that session's
    `coach_credential_id` must belong to the volunteer whose `id` equals
    `X-User-ID`, and that credential must itself be a `CERTIFIED` `COACH`
    credential; when it is not, the request is rejected with
    `ERR_NOT_CREDENTIAL_OWNER` (HTTP 403)."

    Design: Corner/rbac/coach_may_only_act_under_a_credential_they_hold
    """
    world = fx.setup_practice_ready_program()
    second = fx.setup_program_with_second_coach(
        world, screening_overrides={"vendor_reference": "BGS-3001"})
    athlete, _form = fx.create_active_athlete(world["program"]["id"])
    coach_a = make_coach_headers(world["volunteer"]["id"])
    coach_b = make_coach_headers(second["volunteer"]["id"])

    session = validate_success(api_client.create_practice_session(
        f.create_practice_session_payload(
            world["season"]["id"], world["credential"]["id"],
            scheduled_start="2026-09-10T10:00:00Z", duration_minutes=60,
            capacity_slots=12), coach_a), 201)
    session_version = session["version"]
    fx.set_clock("2026-09-10T11:00:00Z")

    validate_error(api_client.create_practice_session(
        f.create_practice_session_payload(
            world["season"]["id"], world["credential"]["id"],
            scheduled_start="2026-09-20T10:00:00Z", duration_minutes=60,
            capacity_slots=12), coach_b),
        ApiErrorId.ERR_NOT_CREDENTIAL_OWNER.value, 403)
    listing = api_client.list_practice_sessions(
        PM, params={"season_id": world["season"]["id"], "limit": 100})
    assert listing.json()["meta"]["total_count"] == 1

    attendance = f.create_attendance_payload(athlete["id"], session_version,
                                             minutes_present=60)
    validate_error(
        api_client.create_attendance_record(session["id"], attendance, coach_b),
        ApiErrorId.ERR_NOT_CREDENTIAL_OWNER.value, 403)

    stored = validate_success(api_client.get_practice_session(session["id"], PM))
    assert stored["status"] == "SCHEDULED"
    assert stored["recorded_attendance_count"] == 0
    assert stored["version"] == session_version

    record = validate_success(
        api_client.create_attendance_record(session["id"], attendance, coach_a), 201)
    assert record["status"] == "COUNTED"
    after = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert after["cumulative_practice_minutes"] == 60
    assert after["counted_session_count"] == 1
