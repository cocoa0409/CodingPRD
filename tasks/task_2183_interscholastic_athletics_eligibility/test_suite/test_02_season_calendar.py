"""The association calendar: opening a season, moving it, and reading it back."""
from test_helpers import (
    ApiErrorId,
    assert_sport_season,
    create_sport_season_payload,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def test_season_creation_rejects_a_sport_outside_the_declared_set(api, admin_headers):
    """PRD §3.1: "An `AssociationAdmin` opens one by declaring the `sport` it
    contests — one of `FOOTBALL`, `BASKETBALL`, `TRACK`, or `SOCCER` — the
    `classification` band it serves, which is one of `C1A`, `C2A`, `C3A`, `C4A`, or
    `C5A`, the `school_year` label it belongs to (for example `2026-2027`), and the
    `sport_tier` that fixes its fee and stipend economics, one of `TIER_A`,
    `TIER_B`, or `TIER_C`."
    PRD §2.6: "Required body fields present, enum values drawn from their declared
    sets, numbers inside their declared ranges, ISO 8601 fields parseable, and
    `ends_at` strictly after `starts_at` — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/season_creation_with_an_unknown_sport_enum_returns_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z")

    response = api.create_sport_season(
        create_sport_season_payload(sport="LACROSSE"), admin_headers
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_new_season_stands_at_planned_and_a_new_case_at_intake_with_an_assessed_fee(
    api, admin_headers
):
    """PRD §3.1: "A newly opened season stands at `PLANNED`, with
    `scheduled_contest_count`, `seeded_school_count`, and `unseeded_school_count`
    all initialised to 0."
    PRD §3.1: "A `contest_limit` of at least 1 caps how many games any one school
    may hold in the season, and an optional `required_officials`, which must be at
    least 1 and defaults to 2, sets the officiating quorum a game must reach."
    PRD §3.3: "A new case begins at `INTAKE` on its eligibility axis, with
    `ineligibility_reason`, `gpa_variant_applied`, `effective_gpa`,
    `provisional_revoked_at`, and `activated_at` all null, and with `appeal_count`
    and `evaluation_count` both 0."
    PRD §3.3: "The starting figure is the season's tier base: 12345 cents for
    `TIER_A`, 8975 cents for `TIER_B`, and 6499 cents for `TIER_C`."

    Design: Corner/state_machines/season_is_created_in_planned_and_case_is_created_in_intake_with_assessed_fee
    """
    school = fx.create_school(name="North High", fee_cap_cents=20000)
    student = fx.create_student(school["id"], full_name="Nia Frost",
                                birth_date="2009-05-14", grade_level=10)

    season = validate_success(
        api.create_sport_season(create_sport_season_payload(), admin_headers), 201
    )
    case = fx.create_case(school["id"], student["id"], season["id"])

    assert_sport_season(season)
    assert season["status"] == "PLANNED"
    assert season["scheduled_contest_count"] == 0
    assert season["seeded_school_count"] == 0
    assert season["unseeded_school_count"] == 0
    assert season["required_officials"] == 2, "required_officials defaults to 2"
    assert case["status"] == "INTAKE"
    assert case["fee_status"] == "ASSESSED"
    assert case["fee_amount_cents"] == 12345
    assert case["fee_outstanding_cents"] == 12345
    assert case["ineligibility_reason"] is None


def test_season_cannot_open_practice_before_its_practice_start_date(api, admin_headers):
    """PRD §3.1: "From `PLANNED` the season may move to `PRACTICE_OPEN`, but only
    once the logical clock's UTC date has reached or passed `practice_start_date`."
    PRD §3.1: "Any requested move that is not one of the transitions just described
    — including a premature move whose date floor has not yet been reached on the
    logical clock — is refused with `ERR_INVALID_STATE`."
    PRD §2.5: "At startup the logical clock stands at exactly
    `2026-08-01T00:00:00Z`, and it holds that instant until an administrator moves
    it."

    Design: Corner/state_machines/season_advance_before_practice_start_date_is_rejected
    """
    # The clock is left at its startup instant: 2026-08-01, four days early.
    season = fx.create_season(practice_start_date="2026-08-05")

    response = api.advance_sport_season(
        season["id"], {"to_status": "PRACTICE_OPEN"}, admin_headers
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = fx.read_season(season["id"])
    assert after["status"] == "PLANNED"
    assert after["version"] == 1, "a refused move must not increment the season's version"


def test_season_read_exposes_the_bracket_counters_and_the_concurrency_version(
    api, admin_headers
):
    """PRD §3.7: "A newly scheduled contest opens at `SCHEDULED` with
    `accepted_official_count` 0, `home_score` and `away_score` null,
    `forfeiting_school_id` null, `hold_reason` null, and `result_recorded_at` null;
    the season's `scheduled_contest_count` increments by 1 and its `version`
    increments by 1."
    PRD §3.1: "A newly opened season stands at `PLANNED`, with
    `scheduled_contest_count`, `seeded_school_count`, and `unseeded_school_count`
    all initialised to 0."

    Design: Corner/endpoints/season_read_exposes_the_derived_bracket_counters
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-02T09:00:00Z",
        home_overrides={"name": "Alpha High"},
        away_overrides={"name": "Beta High", "region_code": "R-SOUTH"},
        open_season=False,
    )
    fx.create_contest(
        ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
        "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z",
        headers=admin_headers, travel_miles=20,
    )

    season = validate_success(
        api.get_sport_season(ctx["season"]["id"], admin_headers), 200
    )

    assert season["scheduled_contest_count"] == 1
    assert season["seeded_school_count"] == 0
    assert season["unseeded_school_count"] == 0
    assert season["version"] == 2, "the contest create advanced the season from version 1 to 2"
    assert season["status"] == "PLANNED"


def test_bracket_of_two_schools_cannot_open_the_playoffs(api, admin_headers):
    """PRD §3.1: "From `SEEDING_LOCKED` the season may open its bracket by moving
    to `PLAYOFFS`, and that move requires the drawn bracket to hold at least four
    schools: a `seeded_school_count` below 4 is rejected with
    `ERR_BRACKET_TOO_SMALL`."

    Design: Corner/errors/opening_a_bracket_with_only_two_seeded_schools_returns_bracket_too_small
    """
    drawn = fx.setup_seeded_season(
        schools=[
            {"name": "Larch High", "classification": "C1A", "region_code": "R-EAST"},
            {"name": "Maple High", "classification": "C1A", "region_code": "R-EAST"},
        ],
        contests=[(0, 1, "2026-09-12T18:00:00Z", "2026-09-12T20:00:00Z", 1)],
        season_overrides={"sport": "BASKETBALL", "classification": "C1A",
                          "sport_tier": "TIER_C"},
    )
    assert drawn["season"]["seeded_school_count"] == 2

    response = api.advance_sport_season(
        drawn["season"]["id"], {"to_status": "PLAYOFFS"}, admin_headers
    )

    validate_error(response, ApiErrorId.ERR_BRACKET_TOO_SMALL.value, 409)
    after = fx.read_season(drawn["season"]["id"])
    assert after["status"] == "SEEDING_LOCKED"
    assert after["seeded_school_count"] == 2
