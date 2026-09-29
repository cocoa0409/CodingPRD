"""Read paths, the revert endpoint, roster association and the program dashboard."""

from test_helpers import (
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_envelope_meta,
    assert_instant_equals,
    assert_list_meta,
)
from test_helpers.fixtures import CD, HSL, MR, OFFICER_1, PM


def test_01_the_session_read_path_echoes_every_derived_field():
    """GET returns the row the create call derived, and the filter finds it.

    PRD §3.4: "The server derives `scheduled_end` as the start instant advanced
    by the duration"; the session "is created in `SCHEDULED` with
    `recorded_attendance_count` 0 and `void_reason_code` null".

    Design: Corner/endpoints/practice_session_get_reflects_created_row
    """
    world = fx.setup_practice_ready_program()
    session = fx.schedule_session(world["season"]["id"],
                                  world["credential"]["id"],
                                  scheduled_start="2026-09-10T10:00:00Z",
                                  duration_minutes=75, capacity_slots=12)

    response = api_client.get_practice_session(session["id"],
                                               fx.coach_headers_for(world))
    body = response.json()
    assert response.status_code == 200
    assert body["response_type"] == "object"
    assert_envelope_meta(body)
    stored = body["data"]
    assert stored["id"] == session["id"]
    assert stored["season_id"] == world["season"]["id"]
    assert stored["coach_credential_id"] == world["credential"]["id"]
    assert_instant_equals(stored["scheduled_start"], "2026-09-10T10:00:00.000Z",
                          "scheduled_start")
    assert_instant_equals(stored["scheduled_end"], "2026-09-10T11:15:00.000Z",
                          "scheduled_end")
    assert stored["duration_minutes"] == 75
    assert stored["capacity_slots"] == 12
    assert stored["status"] == "SCHEDULED"
    assert stored["recorded_attendance_count"] == 0
    assert stored["void_reason_code"] is None
    assert stored["version"] == 1

    listing = api_client.list_practice_sessions(
        PM, params={"coach_credential_id": world["credential"]["id"],
                    "status": "SCHEDULED", "limit": 50, "offset": 0})
    list_body = listing.json()
    assert listing.status_code == 200
    assert list_body["response_type"] == "array"
    assert_list_meta(list_body["meta"], 50, 0, 1, False)
    assert [row["id"] for row in list_body["data"]] == [session["id"]]


def test_02_redivision_voids_the_divisions_and_returns_the_entries():
    """The only backwards move in the season machine undoes the whole run.

    PRD §3.6: "The revert moves the season `DIVISIONED → PRACTICE_OPEN`, and
    every division of the season still in `DRAFT`, `VALID` or `UNDERSIZED`
    becomes `VOIDED` while keeping its `merged_into_division_id` exactly as it
    was… every entry of the season in `DIVISIONED` returns to `SUBMITTED` with
    `division_id` and `seed_rank` both cleared to null. The season's
    `divisioned_entry_count` therefore becomes 0".

    Design: Corner/endpoints/redivision_reverts_season_and_voids_divisions
    """
    world = fx.setup_divisioned_season(
        [{"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}}],
        [{"athlete_index": 0, "event_code": "100M_DASH", "skill_score": 40.0}],
        season_overrides={"season_name": "Fall 2026 Athletics",
                          "registration_deadline": "2026-09-01",
                          "divisioning_date": "2026-09-05",
                          "competition_date": "2026-09-20"},
        divisioning_clock="2026-09-02T00:00:00Z")
    entry = world["entries"][0]
    assert entry["status"] == "DIVISIONED"
    assert entry["division_id"] is not None
    assert entry["seed_rank"] == 1
    division_id = entry["division_id"]

    reverted = validate_success(
        api_client.redivision_season(world["season"]["id"], {}, CD))
    assert reverted["status"] == "PRACTICE_OPEN"
    assert reverted["divisioned_entry_count"] == 0
    assert reverted["divisioning_run_count"] == 1
    assert reverted["entry_count"] == 1

    after = validate_success(api_client.get_competition_entry(entry["id"], CD))
    assert after["status"] == "SUBMITTED"
    assert after["division_id"] is None
    assert after["seed_rank"] is None

    division = validate_success(api_client.get_division(division_id, CD))
    assert division["status"] == "VOIDED"
    assert division["merged_into_division_id"] is None
    voided = api_client.list_divisions(
        CD, params={"season_id": world["season"]["id"], "status": "VOIDED",
                    "limit": 100})
    assert voided.json()["meta"]["total_count"] == 1


def test_03_a_partner_whose_credential_is_only_initiated_cannot_join():
    """Both rows exist; the association still fails on the credential's state.

    PRD §3.5: "Partner members must hold a credential with `role_class`
    `UNIFIED_PARTNER`, status `CERTIFIED` and an `expires_on` on or after the
    clock date, evaluated at the moment of the append; a partner without one is
    refused with `ERR_PARTNER_CREDENTIAL_INVALID` (422)."

    Design: Corner/endpoints/unified_team_member_add_rejects_uncredentialed_partner
    """
    world = fx.setup_entry_ready_world(
        athlete_specs=[{"athlete": {"legal_name": "Maya Foster",
                                    "birth_date": "2004-03-09",
                                    "sport": "BASKETBALL"}}],
        season_overrides={"sport": "BASKETBALL",
                          "season_name": "Fall 2026 Unified Basketball",
                          "registration_deadline": "2026-09-15",
                          "divisioning_date": "2026-09-25",
                          "competition_date": "2026-10-05"})
    partner = fx.add_volunteer(world["program"]["id"], full_name="Leo Marsh",
                              email="leo@rb.example", date_of_birth="1999-05-20",
                              volunteer_class="UNIFIED_PARTNER")
    credential = fx.open_credential(partner["id"],
                                    role_class="UNIFIED_PARTNER",
                                    officer=OFFICER_1)
    assert credential["status"] == "INITIATED"
    assert credential["expires_on"] is None

    team = fx.create_unified_team(world["season"]["id"],
                                 team_name="Riverbend Rapids")
    with_athlete = fx.add_team_member(team["id"], "ATHLETE",
                                     world["athletes"][0]["id"],
                                     team["version"])
    assert with_athlete["athlete_count"] == 1

    validate_error(api_client.add_unified_team_member(
        team["id"],
        f.add_team_member_payload("PARTNER", partner["id"],
                                  with_athlete["version"]), CD),
        ApiErrorId.ERR_PARTNER_CREDENTIAL_INVALID.value, 422)

    stored = validate_success(api_client.get_unified_team(team["id"], CD))
    assert stored["partner_volunteer_ids"] == []
    assert stored["partner_count"] == 0
    assert stored["athlete_count"] == 1
    assert stored["roster_status"] == "FORMING"
    assert stored["version"] == with_athlete["version"]


def test_04_the_program_read_exposes_every_derived_counter_at_once():
    """One dashboard read, and each counter matches its own formula.

    PRD §2.7: "`expired_credential_ratio` is the expired credential count
    divided by the credential denominator count … and exactly `0.0000` when the
    denominator is zero"; PRD §3.1: "`sweep_epoch` starts at 0 and
    `last_sweep_at` is null until the first compliance checkpoint runs".

    Design: Corner/endpoints/program_get_exposes_all_derived_counters
    """
    world = fx.setup_session_ready_world(
        athlete_specs=[{"athlete": {"legal_name": "Maya Foster",
                                    "birth_date": "2004-03-09"}}],
        season_overrides={"season_name": "Fall 2026 Athletics",
                          "registration_deadline": "2026-09-15",
                          "divisioning_date": "2026-09-20",
                          "competition_date": "2026-10-05"},
        session_overrides={"scheduled_start": "2026-09-10T10:00:00Z",
                           "duration_minutes": 60, "capacity_slots": 10},
        attendance_clock="2026-09-10T10:00:00Z")
    fx.record_attendance(world["session"]["id"], world["athletes"][0]["id"],
                         world["session"]["version"], minutes_present=60)
    contribution = fx.log_contribution(
        world["program"]["id"], donor_name="Cedar Valley Signs",
        contribution_type="IN_KIND_SERVICES", designation="GENERAL",
        stated_value_cents=600_000, received_on="2026-09-01")
    assert contribution["status"] == "RECEIVED"
    assert contribution["recognized_value_cents"] == 480_000

    response = api_client.get_program(world["program"]["id"], PM)
    body = response.json()
    assert response.status_code == 200
    assert body["response_type"] == "object"
    assert_envelope_meta(body)
    program = body["data"]
    assert program["id"] == world["program"]["id"]
    assert program["active_athlete_count"] == 1
    assert program["program_practice_minutes"] == 60
    assert program["certified_coach_count"] == 1
    assert program["credential_denominator_count"] == 1
    assert program["expired_credential_count"] == 0
    assert program["expired_credential_ratio"] == 0.0
    assert program["unresolved_urgent_referral_count"] == 0
    assert program["compliance_posture"] == "OPEN"
    assert program["recognized_support_cents"] == 480_000
    assert program["pledged_support_cents"] == 0
    assert program["family_engagement_credit_cents"] == 0
    assert program["sweep_epoch"] == 0
    assert program["last_sweep_at"] is None


def test_05_only_the_last_urgent_resolution_releases_the_medical_hold():
    """Two urgent referrals, and the hold survives the first resolution.

    PRD §3.8: "When the resolved finding was `URGENT` and the athlete has, after
    this resolution, zero remaining screenings whose `finding_severity` is
    `URGENT` and whose `referral_status` is `REFERRED`, `FOLLOW_UP_LOGGED` or
    `ESCALATED`, the athlete comes off medical hold… `HOLD → CLEARED` when the
    form pointed to by `current_medical_form_id` carries `restrictions` of
    exactly `NONE`."

    Design: Corner/endpoints/resolving_last_urgent_referral_releases_medical_hold
    """
    world = fx.setup_program_with_certified_coach()
    athlete, _form = fx.create_active_athlete(world["program"]["id"])
    fx.set_clock("2026-08-05T00:00:00Z")
    screening_1 = fx.record_screening_finding(
        athlete["id"], event_name="Healthy Athletes Fall Fest",
        discipline="FUNFITNESS", screened_on="2026-08-05",
        finding_severity="URGENT", finding_note="Suspected stress fracture")
    screening_2 = fx.record_screening_finding(
        athlete["id"], event_name="Healthy Athletes Fall Fest",
        discipline="OPENING_EYES", screened_on="2026-08-05",
        finding_severity="URGENT", finding_note="Acute vision loss reported")

    resolved_first = fx.log_followup(
        screening_1["id"], "RESOLVED", headers=HSL,
        note="Orthopaedic clinic confirmed no fracture; cleared in writing.")
    assert resolved_first["referral_status"] == "RESOLVED"

    midway = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert midway["medical_status"] == "HOLD"
    midway_program = fx.get_program(world["program"]["id"])
    assert midway_program["unresolved_urgent_referral_count"] == 1
    assert midway_program["compliance_posture"] == "RESTRICTED"

    resolved_second = validate_success(api_client.log_referral_followup(
        screening_2["id"],
        f.referral_followup_payload(
            "RESOLVED",
            note="Ophthalmology follow-up completed; corrective lenses issued."),
        MR))
    assert resolved_second["referral_status"] == "RESOLVED"

    rows = api_client.list_athlete_health_screenings(
        athlete["id"], PM, params={"limit": 100}).json()["data"]
    stored_first = next(row for row in rows if row["id"] == screening_1["id"])
    assert stored_first["referral_status"] == "RESOLVED"

    after = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert after["medical_status"] == "CLEARED"
    assert after["registration_status"] == "ACTIVE"
    program_after = fx.get_program(world["program"]["id"])
    assert program_after["unresolved_urgent_referral_count"] == 0
    assert program_after["compliance_posture"] == "OPEN"
