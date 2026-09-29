"""Entity contracts: envelopes, declared defaults, identity and existence codes."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_athlete,
    assert_common_fields,
    assert_contribution,
    assert_envelope_meta,
    assert_instant_equals,
    assert_list_meta,
    assert_program,
)
from test_helpers.fixtures import CD, PM


def test_01_program_creation_returns_the_full_object_envelope():
    """Every declared program field is present, at its declared default.

    PRD §3.1: "The new program is born `FROZEN`… Every derived quantity starts
    at zero — `certified_coach_count`, `credential_denominator_count`,
    `expired_credential_count`, `unresolved_urgent_referral_count`,
    `active_athlete_count`, `program_practice_minutes`,
    `recognized_support_cents`, `pledged_support_cents` and
    `family_engagement_credit_cents` — while `expired_credential_ratio` starts
    at exactly `0.0000`, `sweep_epoch` starts at 0 and `last_sweep_at` is null
    until the first compliance checkpoint runs."

    Design: Corner/entities/program_create_returns_full_response_envelope
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    response = api_client.create_program(
        f.create_program_payload(name="Riverbend Special Olympics",
                                 region_code="OH"), PM)
    assert response.status_code == 201
    body = response.json()
    assert_envelope_meta(body)
    assert body["response_type"] == "object"

    program = body["data"]
    assert_program(program)
    assert program["name"] == "Riverbend Special Olympics"
    assert program["region_code"] == "OH"
    assert program["compliance_posture"] == "FROZEN"
    assert program["certified_coach_count"] == 0
    assert program["credential_denominator_count"] == 0
    assert program["expired_credential_count"] == 0
    assert program["expired_credential_ratio"] == 0.0
    assert program["unresolved_urgent_referral_count"] == 0
    assert program["active_athlete_count"] == 0
    assert program["program_practice_minutes"] == 0
    assert program["recognized_support_cents"] == 0
    assert program["pledged_support_cents"] == 0
    assert program["family_engagement_credit_cents"] == 0
    assert program["sweep_epoch"] == 0
    assert program["last_sweep_at"] is None
    assert program["version"] == 1
    assert_instant_equals(program["updated_at"], program["created_at"],
                          "updated_at")


def test_02_reading_a_fresh_athlete_echoes_the_stored_registration_row():
    """Both dimensions sit at their initial values with no form on file.

    PRD §3.1: "`registration_status` starts at `PENDING_MEDICAL`… `medical_status`
    starts at `NONE`… `registration_expires_on` is null while registration is
    `PENDING_MEDICAL`, `current_medical_form_id` is null until a form is
    approved, `cumulative_practice_minutes` and `counted_session_count` both
    start at 0, and `withdrawal_reason_code` is null unless the athlete has been
    withdrawn"; "Because `active_athlete_count` counts only athletes in `ACTIVE`
    registration, registering an athlete does not move it".

    Design: Corner/entities/athlete_get_returns_stored_registration_row
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    created = fx.register_athlete(program["id"])

    body = api_client.get_athlete(created["id"], PM).json()
    assert_envelope_meta(body)
    athlete = body["data"]
    assert_athlete(athlete)
    assert athlete["id"] == created["id"]
    assert athlete["program_id"] == program["id"]
    assert athlete["legal_name"] == "Maya Foster"
    assert athlete["birth_date"] == "2004-03-09"
    assert athlete["sport"] == "ATHLETICS"
    assert athlete["down_syndrome_flag"] is False
    assert athlete["registration_status"] == "PENDING_MEDICAL"
    assert athlete["medical_status"] == "NONE"
    assert athlete["registration_expires_on"] is None
    assert athlete["current_medical_form_id"] is None
    assert athlete["cumulative_practice_minutes"] == 0
    assert athlete["counted_session_count"] == 0
    assert athlete["withdrawal_reason_code"] is None
    assert athlete["version"] == 1
    assert fx.get_program(program["id"])["active_athlete_count"] == 0


def test_03_athlete_listing_pages_the_filtered_collection():
    """total_count counts the whole collection while data carries one page.

    PRD §2.3: "List responses set `response_type` to `"array"` and place the page
    of rows in `data`… `limit` and `offset` echo the effective values used for
    the page, `total_count` reports how many rows matched the filter across the
    whole collection rather than just the returned page, and `has_more` is true
    exactly when rows remain beyond the current page."

    Design: Corner/entities/program_athletes_list_pagination_envelope
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    ids = [
        fx.register_athlete(program["id"], legal_name="Maya Foster",
                            birth_date="2004-03-09")["id"],
        fx.register_athlete(program["id"], legal_name="Ivan Petrov",
                            birth_date="2003-10-01")["id"],
        fx.register_athlete(program["id"], legal_name="Grace Lin",
                            birth_date="1998-05-20", sport="BOCCE")["id"],
    ]

    first = api_client.list_program_athletes(
        program["id"], PM, params={"limit": 2, "offset": 0})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["response_type"] == "array"
    assert len(first_body["data"]) == 2
    assert_list_meta(first_body["meta"], limit=2, offset=0, total_count=3,
                     has_more=True)

    second = api_client.list_program_athletes(
        program["id"], PM, params={"limit": 2, "offset": 2}).json()
    assert len(second["data"]) == 1
    assert_list_meta(second["meta"], limit=2, offset=2, total_count=3,
                     has_more=False)

    seen = [row["id"] for row in first_body["data"]] + \
        [row["id"] for row in second["data"]]
    assert sorted(seen) == sorted(ids)
    assert len(set(seen)) == 3


def test_04_an_unknown_athlete_id_returns_the_entity_specific_404():
    """The code names the entity that failed to resolve.

    PRD §2.6: "The unresolved identifier decides the code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_ATHLETE_NOT_FOUND`… each HTTP 404"; PRD §2.2: "The `error_id` is a
    unique, machine-readable string that identifies the specific error" and "The
    `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/athlete_get_unknown_id_returns_athlete_not_found
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    response = api_client.get_athlete(NON_EXISTENT_UUID, PM)
    body = response.json()
    assert body["response_type"] == "error"
    error = validate_error(response, ApiErrorId.ERR_ATHLETE_NOT_FOUND.value, 404)
    assert isinstance(error["message"], str) and error["message"]

    listing = api_client.list_program_athletes(program["id"], PM)
    assert listing.json()["meta"]["total_count"] == 0


def test_05_volunteer_hours_are_conditionally_required_by_type():
    """A stated value cannot stand in for the hours the type demands.

    PRD §3.9: "`volunteer_hours` is required when and only when the type is
    `VOLUNTEER_HOURS`, and must be omitted otherwise; a volunteer-hours
    contribution whose hours are absent or not greater than zero is refused with
    `ERR_VOLUNTEER_HOURS_REQUIRED` (HTTP 400)."

    Design: Corner/entities/contribution_volunteer_hours_required_when_type_volunteer_hours
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    payload = f.create_contribution_payload(
        donor_name="Harbor Physio Group", contribution_type="VOLUNTEER_HOURS",
        designation="GENERAL", stated_value_cents=250_000)
    validate_error(api_client.create_contribution(program["id"], payload, PM),
                   ApiErrorId.ERR_VOLUNTEER_HOURS_REQUIRED.value, 400)

    listing = api_client.list_program_contributions(program["id"], PM)
    assert listing.json()["meta"]["total_count"] == 0
    after = fx.get_program(program["id"])
    assert after["pledged_support_cents"] == 0
    assert after["recognized_support_cents"] == 0


def test_06_a_cash_pledge_without_received_on_starts_pledged_with_no_match():
    """A promised family-engagement gift earns no credit until it is banked.

    PRD §3.9: "a `CASH_PLEDGE` starts `PLEDGED` because the money has been
    promised but not banked, and every other type starts `RECEIVED`… 
    `pledged_support_cents` is the sum of `recognized_value_cents` over the
    program's `PLEDGED` contributions"; and a match credit accrues only to a
    contribution "whose `status` is `RECEIVED`", "every other contribution's
    `match_credit_cents` is 0".

    Design: Corner/entities/contribution_create_defaults_pledged_with_zero_match
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    response = api_client.create_contribution(
        program["id"],
        f.create_contribution_payload(donor_name="Cedar Valley Rotary",
                                      contribution_type="CASH_PLEDGE",
                                      designation="FAMILY_ENGAGEMENT",
                                      stated_value_cents=250_000), PM)
    contribution = validate_success(response, 201)
    assert_contribution(contribution)
    assert contribution["status"] == "PLEDGED"
    assert contribution["received_on"] is None
    assert contribution["void_reason_code"] is None
    assert contribution["match_credit_cents"] == 0
    assert contribution["recognized_value_cents"] == 250_000

    after = fx.get_program(program["id"])
    assert after["pledged_support_cents"] == 250_000
    assert after["recognized_support_cents"] == 0
    assert after["family_engagement_credit_cents"] == 0


def test_07_volunteer_hours_recognition_ignores_the_stated_value():
    """12.5 hours at the standard rate recognises 41850 cents, not 999999.

    PRD §3.9: "`VOLUNTEER_HOURS` ignores `stated_value_cents` entirely and
    recognises the donated hours multiplied by a standard rate of 3,348 cents per
    hour — $33.48 — rounded half up to whole cents."

    Design: Corner/entities/volunteer_hours_contribution_ignores_stated_value
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    contribution = fx.log_contribution(
        program["id"], donor_name="Harbor Physio Group",
        contribution_type="VOLUNTEER_HOURS", designation="GENERAL",
        stated_value_cents=999_999, volunteer_hours=12.5,
        received_on="2026-08-01")
    assert contribution["recognized_value_cents"] == 41_850
    assert contribution["volunteer_hours"] == 12.5
    assert contribution["status"] == "RECEIVED"
    assert contribution["received_on"] == "2026-08-01"

    after = fx.get_program(program["id"])
    assert after["recognized_support_cents"] == 41_850
    assert after["pledged_support_cents"] == 0
    assert after["family_engagement_credit_cents"] == 0


def test_08_system_fields_are_minted_and_a_cascade_lifts_the_version():
    """Filing a form mutates the athlete row exactly once.

    PRD §2.4: "Every resource this API mints carries an `id` that is a
    server-generated UUID with no type prefix… Every mutation of a row — whether
    an operator called an endpoint that targets it directly, or a cascade from a
    sibling entity reached in… — refreshes that row's `updated_at` to the logical
    clock instant of the request and increments its `version` by exactly one."

    Design: Corner/entities/athlete_system_fields_minted_and_version_increments
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    athlete = fx.register_athlete(program["id"])
    assert athlete["version"] == 1

    form = fx.file_medical_form(athlete["id"], exam_date="2026-06-15")
    assert_common_fields(form, expected_version=1)
    assert len(form["id"]) == 36
    assert form["status"] == "SUBMITTED"
    assert form["revision_count"] == 0
    assert form["athlete_id"] == athlete["id"]

    after = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert after["version"] == 2
    assert_instant_equals(after["created_at"], athlete["created_at"], "created_at")
    assert after["id"] == athlete["id"]
    assert after["medical_status"] == "PENDING_REVIEW"
    # PRD §3.1: "`current_medical_form_id` is null until a form is approved" —
    # filing leaves the form in SUBMITTED, so the pointer is still null here.
    assert after["current_medical_form_id"] is None
    assert after["registration_status"] == "PENDING_MEDICAL"


def test_09_the_schema_band_rejects_a_bad_enum_and_an_out_of_range_number():
    """Both shape failures earn the same generic 400 and write nothing.

    PRD §2.6: "**Request schema** — the body parses, required inputs are present,
    enum-typed inputs name declared members, and numeric inputs fall inside their
    declared ranges. Failure yields `ERR_INVALID_REQUEST` (400)".

    Design: Corner/entities/entity_type_constraints_reject_bad_enum_and_out_of_range_number
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    validate_error(
        api_client.create_athlete(
            program["id"], f.create_athlete_payload(sport="CURLING"), PM),
        ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    validate_error(
        api_client.create_contribution(
            program["id"],
            f.create_contribution_payload(stated_value_cents=200_000_000), PM),
        ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    assert api_client.list_program_athletes(
        program["id"], PM).json()["meta"]["total_count"] == 0
    assert api_client.list_program_contributions(
        program["id"], PM).json()["meta"]["total_count"] == 0


def test_10_the_path_parent_is_resolved_before_the_body_is_validated():
    """A bad program id outranks the invalid sport in the same body.

    PRD §2.6: existence sits in band 3, where "every identifier in the URL path
    is resolved first, strictly left to right, and only then are foreign keys
    carried in the request body resolved", while the request-schema band is
    band 4.

    Design: Corner/entities/athlete_create_under_unknown_program_returns_program_not_found
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    error = validate_error(
        api_client.create_athlete(
            NON_EXISTENT_UUID, f.create_athlete_payload(sport="CURLING"), PM),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND.value, 404)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
    assert api_client.list_program_athletes(
        program["id"], PM).json()["meta"]["total_count"] == 0


def test_11_an_unknown_participant_resolves_to_the_polymorphic_404():
    """The participant reference is probed only in the collection it names.

    PRD §3.5: "the server resolves it against the athlete collection when
    `participant_type` is `ATHLETE` and against the unified-team collection when
    it is `UNIFIED_TEAM`, never probing the other collection… A reference that
    fails either test is refused with `ERR_PARTICIPANT_NOT_FOUND` (404)."

    Design: Corner/entities/entry_create_with_unknown_participant_returns_participant_not_found
    """
    world = fx.setup_practice_ready_program(
        season_overrides={"practice_minimum_sessions": 0,
                          "practice_minimum_minutes": 0})
    payload = f.create_entry_payload(world["season"]["id"], NON_EXISTENT_UUID,
                                     event_code="100M_DASH", skill_score=40.0)
    validate_error(api_client.create_competition_entry(payload, CD),
                   ApiErrorId.ERR_PARTICIPANT_NOT_FOUND.value, 404)

    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["entry_count"] == 0
    assert season["status"] == "PRACTICE_OPEN"
    listing = api_client.list_competition_entries(
        CD, params={"season_id": world["season"]["id"]})
    assert listing.json()["meta"]["total_count"] == 0
