"""Field and cross-row validation rules on entries, divisioning and medical forms."""

from test_helpers import (
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.fixtures import CD, PM

_ONE_ATHLETE = [
    {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}},
]

_SEASON = {
    "season_name": "Fall 2026 Athletics",
    "registration_deadline": "2026-09-01",
    "divisioning_date": "2026-09-05",
    "competition_date": "2026-09-20",
    "entry_slot_budget": 40,
}


def _entry_world(**season_overrides):
    """Entry-ready world with one ACTIVE CLEARED athlete and zero minimums."""
    overrides = dict(_SEASON)
    overrides.update(season_overrides)
    world = fx.setup_entry_ready_world(athlete_specs=_ONE_ATHLETE,
                                      season_overrides=overrides)
    world["athlete"] = world["athletes"][0]
    return world


def _submit(world, event_code, skill_score):
    return validate_success(api_client.create_competition_entry(
        f.create_entry_payload(world["season"]["id"], world["athlete"]["id"],
                               event_code=event_code, skill_score=skill_score),
        CD), 201)


def test_01_a_second_live_entry_in_the_same_event_is_refused():
    """The uniqueness key is participant plus season plus event_code.

    PRD §3.5: "The same participant may not hold two live entries in the same
    season for the same `event_code`, where live means anything other than
    `VOIDED` or `DISQUALIFIED`; a second one is refused with
    `ERR_DUPLICATE_ENTRY` (409)."

    Design: Corner/validations/duplicate_live_entry_for_same_event_rejected
    """
    world = _entry_world()
    first = _submit(world, "100M_DASH", 40.0)

    duplicate = f.create_entry_payload(world["season"]["id"],
                                       world["athlete"]["id"],
                                       event_code="100M_DASH", skill_score=41.0)
    validate_error(api_client.create_competition_entry(duplicate, CD),
                   ApiErrorId.ERR_DUPLICATE_ENTRY.value, 409)

    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["entry_count"] == 1
    stored = validate_success(api_client.get_competition_entry(first["id"], CD))
    assert stored["status"] == "SUBMITTED"
    assert stored["skill_score"] == 40.0
    listing = api_client.list_competition_entries(
        CD, params={"season_id": world["season"]["id"], "limit": 100})
    assert listing.json()["meta"]["total_count"] == 1


def test_02_a_second_entry_in_a_different_event_is_accepted():
    """Keying on the event lets one athlete contest several events.

    PRD §3.5: "`age_on_competition_date` is the whole years elapsed between the
    participant's birth date and the season's `competition_date`" and "`age_group`
    is derived: … `AGE_22_29` for 22 through 29"; the entry "is created in
    `SUBMITTED` with `division_id` and `seed_rank` null".

    Design: Corner/validations/second_entry_in_a_different_event_accepted
    """
    world = _entry_world()
    first = _submit(world, "100M_DASH", 40.0)
    second = _submit(world, "200M_DASH", 85.0)

    assert second["status"] == "SUBMITTED"
    assert second["division_id"] is None
    assert second["seed_rank"] is None
    assert second["age_on_competition_date"] == 22
    assert second["age_group"] == "AGE_22_29"

    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["entry_count"] == 2
    assert season["divisioned_entry_count"] == 0
    stored_first = validate_success(
        api_client.get_competition_entry(first["id"], CD))
    assert stored_first["status"] == "SUBMITTED"
    assert stored_first["event_code"] == "100M_DASH"


def test_03_divisioning_run_before_the_registration_deadline_is_refused():
    """The gate is the registration deadline, not the divisioning date.

    PRD §3.6: "The clock date must have reached the season's
    `registration_deadline`, since divisioning a field that can still grow is
    pointless; running it early is refused with `ERR_REGISTRATION_STILL_OPEN`
    (409)."

    Design: Corner/validations/divisioning_before_registration_deadline_rejected
    """
    world = _entry_world(registration_deadline="2026-09-15",
                         divisioning_date="2026-09-20",
                         competition_date="2026-10-05")
    entry = _submit(world, "100M_DASH", 40.0)

    validate_error(api_client.run_divisioning(world["season"]["id"], {}, CD),
                   ApiErrorId.ERR_REGISTRATION_STILL_OPEN.value, 409)

    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["status"] == "PRACTICE_OPEN"
    assert season["divisioning_run_count"] == 0
    assert season["divisioned_entry_count"] == 0
    stored = validate_success(api_client.get_competition_entry(entry["id"], CD))
    assert stored["status"] == "SUBMITTED"
    assert stored["division_id"] is None
    divisions = api_client.list_divisions(
        CD, params={"season_id": world["season"]["id"], "limit": 100})
    assert divisions.json()["meta"]["total_count"] == 0


def test_04_the_third_entry_exhausts_the_seasons_slot_budget():
    """Each entry is individually valid; collectively they hit the budget.

    PRD §3.5: "And the season's live `entry_count` must still be below its
    `entry_slot_budget`, or the entry is refused with
    `ERR_SEASON_ENTRY_BUDGET_EXCEEDED` (409)"; PRD §2.6 places this last, in band
    twelve, "**Business fiscal** — capacity slots and entry budgets".

    Design: Corner/validations/season_entry_budget_exceeded_by_third_entry
    """
    world = _entry_world(entry_slot_budget=2)
    first = _submit(world, "100M_DASH", 40.0)
    second = _submit(world, "200M_DASH", 85.0)

    third = f.create_entry_payload(world["season"]["id"], world["athlete"]["id"],
                                   event_code="400M_DASH", skill_score=190.0)
    validate_error(api_client.create_competition_entry(third, CD),
                   ApiErrorId.ERR_SEASON_ENTRY_BUDGET_EXCEEDED.value, 409)

    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["entry_count"] == 2
    listing = api_client.list_competition_entries(
        CD, params={"season_id": world["season"]["id"], "limit": 100})
    body = listing.json()
    assert body["meta"]["total_count"] == 2
    assert sorted(row["id"] for row in body["data"]) == sorted(
        [first["id"], second["id"]])


def test_05_the_atlantoaxial_attestation_is_required_only_when_flagged():
    """One payload, two athletes, two outcomes decided by down_syndrome_flag.

    PRD §3.2: "A form for a Down-syndrome athlete whose atlantoaxial attestation
    is absent or false is refused with `ERR_ATLANTOAXIAL_SCREEN_MISSING` (422)."

    Design: Corner/validations/atlantoaxial_attestation_required_for_down_syndrome_athlete
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    unflagged = fx.register_athlete(program["id"], legal_name="Maya Foster",
                                    birth_date="2004-03-09",
                                    down_syndrome_flag=False)
    payload = f.create_medical_form_payload(
        exam_date="2026-06-15", attestation_atlantoaxial_screen=False)
    accepted = validate_success(
        api_client.create_medical_form(unflagged["id"], payload, PM), 201)
    assert accepted["status"] == "SUBMITTED"

    flagged = fx.register_athlete(program["id"], legal_name="Noah Reed",
                                  birth_date="2004-01-15",
                                  down_syndrome_flag=True)
    validate_error(api_client.create_medical_form(flagged["id"], payload, PM),
                   ApiErrorId.ERR_ATLANTOAXIAL_SCREEN_MISSING.value, 422)

    stored_accepted = validate_success(
        api_client.get_athlete(unflagged["id"], PM))
    assert stored_accepted["medical_status"] == "PENDING_REVIEW"
    refused_athlete = validate_success(api_client.get_athlete(flagged["id"], PM))
    assert refused_athlete["registration_status"] == "PENDING_MEDICAL"
    assert refused_athlete["medical_status"] == "NONE"
    assert refused_athlete["current_medical_form_id"] is None
    forms = api_client.list_athlete_medical_forms(flagged["id"], PM,
                                                 params={"limit": 100})
    assert forms.json()["meta"]["total_count"] == 0
    assert fx.get_program(program["id"])["active_athlete_count"] == 0
