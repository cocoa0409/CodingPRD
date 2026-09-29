"""Derived-quantity arithmetic: posture ratio, practice aggregates, credential
expiry min(), support ledgers, the advancement waterfall and roster spans."""

from test_helpers import (
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_instant_equals
from test_helpers.fixtures import CD, OFFICER_1, PM


def test_01_one_expired_credential_of_five_lands_exactly_on_restricted():
    """The three INITIATED files are in the denominator, so the ratio is 0.2000.

    PRD §2.7: "`credential_denominator_count` is the number of the program's
    credentials whose `status` is any of `INITIATED`, `SCREENING_CLEARED`,
    `TRAINING_COMPLETE`, `READY_TO_CERTIFY`, `CERTIFIED`, `EXPIRED` or
    `RENEWAL_IN_PROGRESS`"; and "one expired credential out of five is a ratio
    of exactly `0.2000` and is therefore `RESTRICTED`".

    Design: Corner/calculations/posture_expired_ratio_at_restricted_boundary
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    _vol1, credential_1 = fx.create_certified_credential(program["id"])

    idle_credentials = []
    for index, (name, email, dob) in enumerate(
            [("Omar Diaz", "omar@rb.example", "1990-02-02"),
             ("Ruth Blake", "ruth@rb.example", "1991-03-03"),
             ("Tom Slater", "tom@rb.example", "1992-04-04")], start=3):
        volunteer = fx.add_volunteer(
            program["id"], full_name=name, email=email, date_of_birth=dob,
            volunteer_class="GENERAL_VOLUNTEER")
        idle_credentials.append(fx.open_credential(
            volunteer["id"], role_class="GENERAL_VOLUNTEER", officer=OFFICER_1))
        assert idle_credentials[-1]["status"] == "INITIATED", index

    fx.set_clock("2027-07-06T00:00:00Z")
    _vol2, credential_2 = fx.create_certified_credential(
        program["id"],
        volunteer_overrides={"full_name": "Priya Nair",
                             "email": "priya@rb.example",
                             "date_of_birth": "1985-06-06",
                             "volunteer_class": "COACH"},
        screening_overrides={"completed_on": "2027-07-01", "result": "CLEAR",
                             "vendor_reference": "BGS-2001"},
        training_overrides={"completed_on": "2027-07-02",
                            "curriculum_code": "PB-CORE-2027"})
    fx.run_sweep(program["id"])

    expired = validate_success(api_client.get_credential(credential_1["id"], PM))
    assert expired["status"] == "EXPIRED"
    assert expired["expires_on"] == "2027-07-05"
    live = validate_success(api_client.get_credential(credential_2["id"], PM))
    assert live["status"] == "CERTIFIED"
    assert live["expires_on"] == "2028-07-01"
    for credential in idle_credentials:
        stored = validate_success(api_client.get_credential(credential["id"], PM))
        assert stored["status"] == "INITIATED"

    after = fx.get_program(program["id"])
    assert after["credential_denominator_count"] == 5
    assert after["expired_credential_count"] == 1
    assert after["expired_credential_ratio"] == 0.2
    assert after["certified_coach_count"] == 1
    assert after["compliance_posture"] == "RESTRICTED"
    assert after["sweep_epoch"] == 1


def test_02_a_not_counted_row_never_enters_the_practice_minimum_aggregate():
    """Two HELD sessions, one qualifying row: counted_sessions is 1, not 2.

    PRD §3.5: "The server gathers this athlete's attendance rows whose `status`
    is `COUNTED` — rows that are `VOIDED` or `NOT_COUNTED` never contribute";
    the athlete is eligible "only when the count is greater than or equal to the
    season's `practice_minimum_sessions` **and** the summed minutes are greater
    than or equal to the season's `practice_minimum_minutes`".

    Design: Corner/calculations/season_practice_eligibility_excludes_not_counted_rows
    """
    world = fx.setup_practice_ready_program(season_overrides={
        "season_name": "Fall 2026 Athletics",
        "practice_minimum_sessions": 2, "practice_minimum_minutes": 60,
        "registration_deadline": "2026-09-15",
        "divisioning_date": "2026-09-20", "competition_date": "2026-10-05"})
    athlete, _form = fx.create_active_athlete(world["program"]["id"])
    session_a = fx.schedule_session(world["season"]["id"],
                                    world["credential"]["id"],
                                    scheduled_start="2026-09-10T10:00:00Z",
                                    duration_minutes=60)
    session_b = fx.schedule_session(world["season"]["id"],
                                    world["credential"]["id"],
                                    scheduled_start="2026-09-10T12:00:00Z",
                                    duration_minutes=60)

    fx.set_clock("2026-09-10T12:00:00Z")
    record_a = fx.record_attendance(session_a["id"], athlete["id"],
                                    session_a["version"], minutes_present=60)
    record_b = fx.record_attendance(session_b["id"], athlete["id"],
                                    session_b["version"], minutes_present=40)
    assert record_a["status"] == "COUNTED"
    assert record_a["required_minutes"] == 45
    assert record_a["counted_minutes"] == 60
    assert record_b["status"] == "NOT_COUNTED"
    assert record_b["required_minutes"] == 45
    assert record_b["counted_minutes"] == 0

    stored_athlete = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert stored_athlete["counted_session_count"] == 1
    assert stored_athlete["cumulative_practice_minutes"] == 60
    assert fx.get_program(world["program"]["id"])["program_practice_minutes"] == 60

    payload = f.create_entry_payload(world["season"]["id"], athlete["id"],
                                     event_code="100M_DASH", skill_score=40.0)
    validate_error(api_client.create_competition_entry(payload, CD),
                   ApiErrorId.ERR_PRACTICE_MINIMUM_NOT_MET.value, 422)
    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["entry_count"] == 0


def test_03_flagged_screening_dominates_a_unified_partners_expiry_min():
    """The certification-plus-365 term beats both 2029-06-30 and 2028-07-04.

    PRD §3.3: the effective expiry is "the earliest of three dates when the
    screening was `FLAGGED`, the third being the certification date plus one
    year, 365 days".

    Design: Corner/calculations/flagged_screening_shortens_credential_expiry
    """
    override_reason = ("Committee reviewed the 2019 non-disqualifying record and "
                       "approved a 12-month provisional term.")
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    volunteer, credential = fx.create_certified_credential(
        program["id"],
        volunteer_overrides={"full_name": "Leo Marsh", "email": "leo@rb.example",
                             "date_of_birth": "1999-05-20",
                             "volunteer_class": "UNIFIED_PARTNER"},
        role_class="UNIFIED_PARTNER",
        screening_overrides={"completed_on": "2026-07-01", "result": "FLAGGED",
                             "vendor_reference": "BGS-3001"},
        training_overrides={"completed_on": "2026-07-05",
                            "curriculum_code": "PB-CORE-2026"},
        certify_overrides={"flag_override_reason": override_reason})

    assert credential["status"] == "CERTIFIED"
    assert credential["screening_expires_on"] == "2029-06-30"
    assert credential["training_expires_on"] == "2028-07-04"
    assert credential["expires_on"] == "2027-08-01"
    assert credential["flag_override_reason"] == override_reason
    assert_instant_equals(credential["certified_at"], "2026-08-01T00:00:00.000Z",
                          "certified_at")

    program_after = fx.get_program(program["id"])
    assert program_after["certified_coach_count"] == 0
    assert program_after["compliance_posture"] == "FROZEN"
    stored_volunteer = validate_success(
        api_client.get_volunteer(volunteer["id"], PM))
    assert stored_volunteer["status"] == "CREDENTIALED"


def _contribution_row(program_id: str, contribution_id: str):
    rows = api_client.list_program_contributions(
        program_id, PM, params={"limit": 100}).json()["data"]
    return next(row for row in rows if row["id"] == contribution_id)


def test_04_fulfilment_moves_the_gift_and_only_then_mints_the_match():
    """The match credit is a RECEIVED-only quantity, minted at fulfilment.

    PRD §3.9: fulfilment "moves it `PLEDGED → RECEIVED` with the date stored.
    The program's `pledged_support_cents` is decremented by the contribution's
    `recognized_value_cents` and its `recognized_support_cents` incremented by
    the same amount"; and "When the designation is `FAMILY_ENGAGEMENT`,
    fulfilment sets the row's `match_credit_cents` to ten percent of its
    recognised value rounded half up to whole cents".

    Design: Corner/calculations/pledge_fulfilment_moves_support_from_pledged_to_recognized
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    contribution = fx.log_contribution(
        program["id"], donor_name="Foster Family",
        contribution_type="CASH_PLEDGE", designation="FAMILY_ENGAGEMENT",
        stated_value_cents=12_345)
    assert contribution["status"] == "PLEDGED"
    assert contribution["recognized_value_cents"] == 12_345
    assert contribution["match_credit_cents"] == 0

    before = fx.get_program(program["id"])
    assert before["pledged_support_cents"] == 12_345
    assert before["recognized_support_cents"] == 0
    assert before["family_engagement_credit_cents"] == 0

    fx.set_clock("2026-08-15T00:00:00Z")
    fulfilled = validate_success(api_client.fulfill_contribution(
        contribution["id"], f.fulfill_contribution_payload(
            received_on="2026-08-15"), PM))
    assert fulfilled["status"] == "RECEIVED"
    assert fulfilled["received_on"] == "2026-08-15"
    assert fulfilled["recognized_value_cents"] == 12_345
    assert fulfilled["match_credit_cents"] == 1_235

    after = fx.get_program(program["id"])
    assert after["pledged_support_cents"] == 0
    assert after["recognized_support_cents"] == 12_345
    assert after["family_engagement_credit_cents"] == 1_235
    assert _contribution_row(program["id"], contribution["id"])[
        "match_credit_cents"] == 1_235


def _locked_bocce_world(season_name, event_code, skill_scores):
    """A single BOCCE division of three entries, locked, clock on games day."""
    athlete_specs = [
        {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09",
                     "sport": "BOCCE"}},
        {"athlete": {"legal_name": "Ivan Petrov", "birth_date": "2003-10-01",
                     "sport": "BOCCE"}},
        {"athlete": {"legal_name": "Grace Lin", "birth_date": "1998-05-20",
                     "sport": "BOCCE"}},
    ]
    entry_specs = [
        {"athlete_index": index, "event_code": event_code,
         "skill_score": score}
        for index, score in enumerate(skill_scores)
    ]
    world = fx.setup_entries_locked_season(
        athlete_specs, entry_specs,
        season_overrides={"sport": "BOCCE", "season_name": season_name,
                          "registration_deadline": "2026-09-01",
                          "divisioning_date": "2026-09-05",
                          "competition_date": "2026-09-20",
                          "entry_slot_budget": 40,
                          "advancement_slots_per_division": 1},
        divisioning_clock="2026-09-02T00:00:00Z")
    assert world["season"]["status"] == "ENTRIES_LOCKED"
    assert len(world["divisions"]) == 1
    fx.set_clock("2026-09-20T00:00:00Z")
    return world


def _post_result(entry_id: str, result_value: float):
    return validate_success(api_client.post_entry_result(
        entry_id, f.post_result_payload(result_value, disqualified=False), CD))


def test_05_the_maxed_winner_keeps_its_placement_but_consumes_no_slot():
    """A 1.2500 ratio is skipped by the waterfall, and the runner-up advances.

    PRD §3.7: "An entry whose `performance_ratio` is **strictly greater than**
    1.20 … its `advancement_status` becomes `INELIGIBLE_MAXING`", and "An entry
    marked `INELIGIBLE_MAXING` is skipped and **consumes no slot**, so a maxed
    winner does not deprive the runner-up of advancement."

    Design: Corner/calculations/maxed_entry_consumes_no_advancement_slot
    """
    world = _locked_bocce_world("Fall 2026 Bocce", "BOCCE_SINGLES",
                                [20.0, 19.0, 18.0])
    entry_1, entry_2, entry_3 = world["entries"]
    _post_result(entry_1["id"], 25.0)
    _post_result(entry_2["id"], 22.0)
    third = _post_result(entry_3["id"], 20.0)
    assert third["performance_ratio"] == 1.1111

    stored = {entry["id"]: entry
              for entry in fx.list_entries_for_season(world["season"]["id"])}
    first = stored[entry_1["id"]]
    assert first["performance_ratio"] == 1.25
    assert first["placement"] == 1
    assert first["advancement_status"] == "INELIGIBLE_MAXING"
    assert first["status"] == "RESULTED"

    second = stored[entry_2["id"]]
    assert second["performance_ratio"] == 1.1579
    assert second["placement"] == 2
    assert second["advancement_status"] == "ADVANCED_STATE"
    assert second["status"] == "ADVANCED"

    last = stored[entry_3["id"]]
    assert last["placement"] == 3
    assert last["advancement_status"] == "NOT_ADVANCED"
    assert last["status"] == "RESULTED"

    advanced = [entry for entry in stored.values() if entry["status"] == "ADVANCED"]
    assert len(advanced) == 1
    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["status"] == "ENTRIES_LOCKED"


def test_06_a_ratio_of_exactly_1_2000_is_not_maxing_and_takes_the_slot():
    """The strict comparison lets 1.2000 advance, revoking the earlier holder.

    PRD §3.7: "The comparison is strict on the four-decimal ratio, so a ratio of
    exactly `1.2000` is not maxing and remains eligible to advance"; and "If a
    sibling's later result pushes an entry's `placement` beyond the season's
    `advancement_slots_per_division`, that entry's `advancement_status` resets to
    `NOT_ADVANCED` and its `status` reverts `ADVANCED → RESULTED`."

    Design: Corner/calculations/performance_ratio_exactly_at_maxing_threshold_advances
    """
    world = _locked_bocce_world("Fall 2026 Bocce Doubles", "BOCCE_RAMP",
                                [13.75, 13.5, 13.0])
    entry_1, entry_2, entry_3 = world["entries"]
    holder = _post_result(entry_2["id"], 14.0)
    assert holder["status"] == "ADVANCED"
    _post_result(entry_3["id"], 13.0)

    first = _post_result(entry_1["id"], 16.5)
    assert first["performance_ratio"] == 1.2
    assert first["advancement_status"] == "ADVANCED_STATE"
    assert first["status"] == "ADVANCED"
    assert first["placement"] == 1

    stored = {entry["id"]: entry
              for entry in fx.list_entries_for_season(world["season"]["id"])}
    second = stored[entry_2["id"]]
    assert second["performance_ratio"] == 1.037
    assert second["placement"] == 2
    assert second["advancement_status"] == "NOT_ADVANCED"
    assert second["status"] == "RESULTED"

    last = stored[entry_3["id"]]
    assert last["performance_ratio"] == 1.0
    assert last["placement"] == 3
    assert last["advancement_status"] == "NOT_ADVANCED"
    assert last["status"] == "RESULTED"

    assert all(entry["advancement_status"] != "INELIGIBLE_MAXING"
               for entry in stored.values())


def test_07_an_age_span_of_exactly_five_years_is_compliant():
    """Ages are taken at the competition_date, and a span of five is compliant.

    PRD §3.5: "`age_span_years` is the difference between the oldest and
    youngest member age across athletes and partners together, where each
    member's age is the whole years elapsed between their birth date … and the
    season's `competition_date` rather than the current clock"; the roster "is
    `COMPLIANT` when the two counts are equal, at least two athletes are on the
    roster, the age span is at most five years (a span of exactly five is
    compliant)".

    Design: Corner/calculations/unified_team_age_span_exactly_five_years_is_compliant
    """
    world = fx.setup_entry_ready_world(
        athlete_specs=[
            {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09",
                         "sport": "BASKETBALL"}},
            {"athlete": {"legal_name": "Noah Reed", "birth_date": "2004-01-15",
                         "sport": "BASKETBALL"}},
        ],
        season_overrides={"sport": "BASKETBALL",
                          "season_name": "Fall 2026 Unified Basketball",
                          "registration_deadline": "2026-09-15",
                          "divisioning_date": "2026-09-25",
                          "competition_date": "2026-10-05",
                          "entry_slot_budget": 40,
                          "advancement_slots_per_division": 2})
    partner_1, _cred_1 = fx.create_certified_partner(
        world["program"]["id"], "Leo Marsh", "leo@rb.example", "1999-05-20",
        screening_overrides={"vendor_reference": "BGS-4001"})
    partner_2, _cred_2 = fx.create_certified_partner(
        world["program"]["id"], "Sara Quinn", "sara@rb.example", "2000-06-10",
        screening_overrides={"vendor_reference": "BGS-4002"})

    team = fx.create_unified_team(world["season"]["id"],
                                 team_name="Riverbend Rapids")
    assert team["roster_status"] == "FORMING"
    assert team["version"] == 1

    after_first = fx.add_team_member(team["id"], "ATHLETE",
                                    world["athletes"][0]["id"], team["version"])
    assert after_first["roster_status"] == "FORMING"
    assert after_first["age_span_years"] == 0

    after_second = fx.add_team_member(team["id"], "PARTNER", partner_1["id"],
                                     after_first["version"])
    assert after_second["roster_status"] == "NON_COMPLIANT"

    after_third = fx.add_team_member(team["id"], "ATHLETE",
                                    world["athletes"][1]["id"],
                                    after_second["version"])
    assert after_third["roster_status"] == "NON_COMPLIANT"

    after_fourth = fx.add_team_member(team["id"], "PARTNER", partner_2["id"],
                                     after_third["version"])
    assert after_fourth["athlete_count"] == 2
    assert after_fourth["partner_count"] == 2
    assert after_fourth["age_span_years"] == 5
    assert after_fourth["roster_status"] == "COMPLIANT"
    assert after_fourth["version"] == 5
    assert after_fourth["athlete_ids"] == [world["athletes"][0]["id"],
                                           world["athletes"][1]["id"]]
    assert after_fourth["partner_volunteer_ids"] == [partner_1["id"],
                                                     partner_2["id"]]
