"""Declared defaults, round-tripped reads, filtered listings and shape refusals."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# A syntactically valid UUID that no row in this system will ever carry.
_MISSING_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_a_new_title_opens_with_every_counter_at_its_declared_default(api):
    """Registration mints the system fields, not just the echoed input.

    "A newly registered title opens in `localization_state` `PLANNING` with
    `string_lock` false, `release_gate_state` `OPEN`, and `extracted_key_count`,
    `market_plan_count` and `ready_market_count` all initialised to zero."

    "Every resource in this system carries a server-minted `id` that is a UUID
    string with no type prefix, and a `created_at` timestamp."

    "`version` starts at 1 when the row is created and increments by exactly 1 on
    every mutation of that row, including mutations caused by a cascade the client
    did not directly request."

    "A title with zero market plans is therefore `OPEN`."

    Design: Corner/entities/title_create_returns_declared_defaults_and_counters
    """
    response = api.create_title(
        f.title_payload(title_code="NOVA-30", name="Nova Drift 30",
                        source_language="EN",
                        target_release_utc="2026-12-01T00:00:00Z",
                        release_mode="SIMULTANEOUS"),
        users.PRODUCER,
    )

    title = validate_success(response, expected_status=201)

    assert title["title_code"] == "NOVA-30"
    assert title["name"] == "Nova Drift 30"
    assert title["source_language"] == "EN"
    assert title["release_mode"] == "SIMULTANEOUS"
    A.assert_instant_equals(title["target_release_utc"], "2026-12-01T00:00:00Z",
                            "target_release_utc")
    A.assert_new_title(title)
    assert title["localization_state"] == "PLANNING"
    assert title["string_lock"] is False
    assert title["release_gate_state"] == "OPEN"
    assert title["extracted_key_count"] == 0
    assert title["market_plan_count"] == 0
    assert title["ready_market_count"] == 0
    assert title["version"] == 1


def test_reading_a_title_returns_the_counters_its_children_moved(api):
    """The read reports persisted derived counters, not a zeroed stub.

    "`extracted_key_count` is the number of string keys of the title whose
    `status` is either `EXTRACTED` or `LOCKED` — retired keys are excluded."

    "`market_plan_count` is the number of market plans of the title with no status
    filter at all."

    "`ready_market_count` is the number of market plans of the title whose
    `status` is `RELEASE_READY`."

    "All seven roles may call every read endpoint."

    "Otherwise, if the total count is at least 1, the ready count is less than the
    total count, and the number of days to release is fewer than 30, the posture
    is `AT_RISK`."

    One extracted key and one draft market plan move two of the three counters.
    The title is `STAGGERED`, so the simultaneous-release clause cannot fire, and
    the logical clock sits 122 whole days before the 2026-12-01 target, which is
    not fewer than 30, so the posture falls through to `OPEN`.

    Design: Corner/entities/title_get_by_id_round_trips_stored_values
    """
    title = fx.create_title(api, title_code="NOVA-31", name="Nova Drift 31",
                            target_release_utc=C.DEFAULT_TARGET_RELEASE_UTC,
                            release_mode="STAGGERED")
    fx.create_string_key(api, title["id"], **f.MENU_KEY_SPEC)
    fx.create_market_plan(api, title["id"], market_code="JP",
                          scope_tier="TEXT_ONLY", target_rating="TEEN_12",
                          budget_cap_cents=5000000)

    read = validate_success(api.get_title(title["id"], users.VENDOR))

    assert read["id"] == title["id"]
    assert read["title_code"] == "NOVA-31"
    assert read["extracted_key_count"] == 1
    assert read["market_plan_count"] == 1
    assert read["ready_market_count"] == 0
    assert read["localization_state"] == "PLANNING"
    assert read["string_lock"] is False
    assert read["release_gate_state"] == "OPEN"
    assert C.DEFAULT_DAYS_TO_RELEASE == 122
    A.assert_common_fields(read, label="title")
    A.assert_instant_equals(read["created_at"], title["created_at"], "created_at")


def _two_titles_and_three_market_plans(api):
    """DE then JP on the first title, US on the second.

    The market codes are chosen so that creation order and the market-plan
    natural key agree: `DE` precedes `JP` both in time and alphabetically, so the
    expected position of each row is the same whether or not the two plans share
    a `created_at`.
    """
    world = {}
    world["title_a"] = fx.create_title(api, title_code="NOVA-32",
                                       name="Nova Drift 32",
                                       release_mode="STAGGERED")
    world["title_b"] = fx.create_title(api, title_code="NOVA-33",
                                       name="Nova Drift 33",
                                       release_mode="STAGGERED")
    world["plan_de"] = fx.create_market_plan(
        api, world["title_a"]["id"], market_code="DE", scope_tier="SUBTITLED",
        target_rating="MATURE_15", budget_cap_cents=5000000,
    )
    world["plan_jp"] = fx.create_market_plan(
        api, world["title_a"]["id"], market_code="JP", scope_tier="TEXT_ONLY",
        target_rating="TEEN_12", budget_cap_cents=5000000,
    )
    world["plan_us"] = fx.create_market_plan(
        api, world["title_b"]["id"], market_code="US", scope_tier="TEXT_ONLY",
        target_rating="MATURE_17", budget_cap_cents=5000000,
    )
    return world


def test_market_plans_are_listed_created_at_ascending_within_one_title(api):
    """The title filter excludes the sibling title's plan and order is temporal.

    "Every list endpoint returns rows sorted by `created_at` ascending — oldest
    first, newest last."

    "In that case the tie is broken by the entity's declared natural key,
    ascending: a title by `title_code`, a market plan by `market_code`, a string
    key by `key_name`, a translation unit by the `key_name` of the string key it
    points at, a QA pass by `pass_index`, a defect by `summary`, a rating
    submission by `submission_round`, a recording session by `start_utc`, a talent
    contract by `rights_start_utc`, a content edit by `edit_kind`, a booth by
    `booth_code`, and a voice talent by `talent_name`."

    "The `id` field is never a sort key and never a tie-break."

    "Market plans can be listed and filtered by `title_id`, `market_code`,
    `status` and `scope_tier`."

    "List responses carry `limit`, `offset`, `total_count` and `has_more` inside
    `meta`, where `total_count` is the number of rows matching the filters before
    pagination is applied and `has_more` is true when rows remain beyond the
    current page."

    Design: Corner/entities/market_plan_list_filtered_by_title_is_created_at_asc
    """
    world = _two_titles_and_three_market_plans(api)

    rows, meta = validate_paginated(
        api.list_market_plans(users.COMPLIANCE,
                              {"title_id": world["title_a"]["id"]})
    )

    A.assert_pagination_meta(meta, C.DEFAULT_LIMIT, 0, 2, False)
    A.assert_id_order(rows, [world["plan_de"]["id"], world["plan_jp"]["id"]],
                      "market-plan listing")
    A.assert_created_at_ascending(rows, "market_code")
    assert [row["market_code"] for row in rows] == ["DE", "JP"]
    assert world["plan_us"]["id"] not in [row["id"] for row in rows]
    for row in rows:
        assert row["title_id"] == world["title_a"]["id"]
        assert row["status"] == "DRAFT"


def test_the_second_page_of_the_filtered_listing_holds_the_later_plan(api):
    """A one-row window at offset 1 lands on the plan created second.

    "`offset` controls the starting position: it defaults to 0 and its minimum
    accepted value is 0."

    "Filters on a list endpoint are all optional and combine conjunctively."

    "List responses carry `limit`, `offset`, `total_count` and `has_more` inside
    `meta`, where `total_count` is the number of rows matching the filters before
    pagination is applied and `has_more` is true when rows remain beyond the
    current page."

    Both plans are still `DRAFT`, so the extra status filter narrows nothing and
    `total_count` stays 2 while the page carries exactly one row; nothing remains
    beyond it, so `has_more` is false.

    Design: Corner/entities/market_plan_list_filtered_by_title_is_created_at_asc
    """
    world = _two_titles_and_three_market_plans(api)

    rows, meta = validate_paginated(
        api.list_market_plans(users.COMPLIANCE, {
            "title_id": world["title_a"]["id"],
            "status": "DRAFT",
            "limit": 1,
            "offset": 1,
        })
    )

    A.assert_pagination_meta(meta, 1, 1, 2, False)
    A.assert_id_order(rows, [world["plan_jp"]["id"]], "second page")
    assert rows[0]["market_code"] == "JP"


def test_an_unknown_title_uuid_on_the_path_is_the_titles_own_404(api):
    """The 404 is entity-specific even against an empty database.

    "Path identifiers are validated left to right, and the first unresolvable
    identifier decides the error."

    "Each resolves to `ERR_TITLE_NOT_FOUND`, `ERR_MARKET_PLAN_NOT_FOUND`,
    `ERR_STRING_KEY_NOT_FOUND`, `ERR_TRANSLATION_UNIT_NOT_FOUND`,
    `ERR_BOOTH_NOT_FOUND`, `ERR_TALENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, `ERR_QA_PASS_NOT_FOUND`, `ERR_BUG_NOT_FOUND`,
    `ERR_SUBMISSION_NOT_FOUND` and `ERR_CONTENT_EDIT_NOT_FOUND` respectively, all
    HTTP 404."

    "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    "The `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`."

    Design: Corner/entities/get_title_with_unknown_uuid_returns_not_found
    """
    _titles, empty_meta = validate_paginated(api.list_titles(users.PRODUCER))
    assert empty_meta["total_count"] == 0

    response = api.get_title(_MISSING_UUID, users.PRODUCER)

    validate_error(response, E.ERR_TITLE_NOT_FOUND, expected_status=404)
    meta = response.json()["meta"]
    assert set(meta) == {"api_request_id", "api_request_timestamp"}
    assert meta["api_request_id"].startswith("req_")
    A.assert_three_fractional_digits(meta["api_request_timestamp"],
                                     "meta.api_request_timestamp")


def test_omitted_optional_fields_materialise_their_declared_defaults(api):
    """Three optional inputs left out, three declared defaults observed.

    "A **Recording Booth** is registered by a `LocalizationProducer` with a
    `booth_code` of one to twenty-four characters that is unique across all booths,
    a `studio_city` of one to sixty characters naming the city the booth physically
    sits in, and an optional `turnaround_buffer_minutes` between 0 and 240
    inclusive that defaults to 30."

    "A new booth opens with `reserved_minutes_total` at 0."

    "A **Voice Talent** is registered with a `talent_name` of one to eighty
    characters, a `language_code` from `JA`, `DE`, `PT_BR`, `EN` and `KO`, a
    `union_flag` boolean recording whether union scale rules apply (defaulting to
    false), and an optional `max_daily_recording_minutes` between 1 and 720
    inclusive that defaults to 240 and caps the aggregate minutes the talent may be
    booked for on a single UTC calendar date."

    "Reading a talent exposes `reserved_minutes_on_clock_date`, which is that
    aggregate evaluated for the logical clock's current UTC date."

    "An optional `context_note` of one to five hundred characters — or null —
    carries the explanation handed to translators."

    "Every new key starts in `status` `EXTRACTED` and increments the title's
    `extracted_key_count`."

    Design: Corner/entities/booth_and_talent_defaults_applied_when_optional_fields_omitted
    """
    title = fx.create_title(api, title_code="NOVA-35", name="Nova Drift 35",
                            release_mode="STAGGERED")

    booth = validate_success(
        api.create_booth(f.booth_payload("TOK-A", "Tokyo"), users.PRODUCER),
        expected_status=201,
    )
    talent = validate_success(
        api.create_voice_talent(
            f.voice_talent_payload("Miki Sato", "JA", False), users.PRODUCER
        ),
        expected_status=201,
    )
    key = validate_success(
        api.create_string_key(
            f.string_key_payload(title["id"], **f.MENU_KEY_SPEC), users.PRODUCER
        ),
        expected_status=201,
    )

    assert booth["booth_code"] == "TOK-A"
    assert booth["studio_city"] == "Tokyo"
    assert booth["turnaround_buffer_minutes"] == C.DEFAULT_TURNAROUND_BUFFER_MINUTES
    assert booth["turnaround_buffer_minutes"] == 30
    A.assert_whole_minutes(booth["reserved_minutes_total"], 0,
                           "reserved_minutes_total")
    A.assert_fresh_row(booth, "recording_booth")

    assert talent["talent_name"] == "Miki Sato"
    assert talent["language_code"] == "JA"
    assert talent["union_flag"] is False
    assert talent["max_daily_recording_minutes"] == 240
    A.assert_fresh_row(talent, "voice_talent")
    A.assert_whole_minutes(
        fx.read_talent(api, talent["id"])["reserved_minutes_on_clock_date"], 0,
        "reserved_minutes_on_clock_date",
    )

    assert key["key_name"] == "menu.start"
    assert key["ui_surface"] == "MENU"
    assert key["context_note"] is None
    assert key["status"] == "EXTRACTED"
    A.assert_fresh_row(key, "string_key")
    assert fx.read_title(api, title["id"])["extracted_key_count"] == 1
    assert fx.read_booth(api, booth["id"])["turnaround_buffer_minutes"] == 30


# A HUD line whose target-side UI truncates at 80 characters, along the canonical
# MENU key whose limit is 140.
_HUD_KEY_LIMIT_80 = {
    "key_name": "hud.ammo",
    "source_text": "Ammo",
    "source_char_count": 60,
    "ui_surface": "HUD",
    "display_char_limit": 80,
    "tm_match_pct": 80,
}

# Exactly 95 characters of German: 15 over the HUD limit, 45 under the MENU limit.
_NINETY_FIVE_CHARS = ("Munitionsvorrat der aktuellen Waffe wird oben rechts am "
                      "Bildschirmrand nun in Prozent angezeigt")


def _de_market_with_a_tight_and_a_roomy_key(api):
    """A TEXT_ONLY DE market handed to the vendor with two very different limits."""
    return fx.build_market(api, title_code="NOVA-36", name="Nova Drift 36",
                           market_code="DE", scope_tier="TEXT_ONLY",
                           target_rating="MATURE_15", budget_cap_cents=5000000,
                           key_specs=[_HUD_KEY_LIMIT_80, f.MENU_KEY_SPEC],
                           stage=fx.STAGE_IN_LOCALIZATION)


def test_overflow_chars_is_measured_against_the_linked_keys_display_limit(api):
    """One identical translation overflows one key and fits the other.

    "On success the server stores the text and recomputes `target_char_count` as
    the character length of `target_text` — zero when `target_text` is null — and
    recomputes `overflow_chars` as the amount by which `target_char_count` exceeds
    the linked string key's `display_char_limit`, floored at zero."

    "A `TranslationVendor` writes target text into a unit, moving it `PENDING →
    DRAFTED` (or updating a unit that is already `DRAFTED`)."

    "The `qa_status` axis is untouched."

    "`delivered_unit_count` is the number of translation units of this plan whose
    `translation_status` is `DELIVERED`."

    The same 95-character string exceeds the HUD key's 80-character limit by 15
    and falls 45 short of the MENU key's 140, so the floored subtraction gives 15
    and 0 from identical text.

    Design: Corner/entities/translation_unit_overflow_chars_computed_from_display_char_limit
    """
    world = _de_market_with_a_tight_and_a_roomy_key(api)
    assert len(_NINETY_FIVE_CHARS) == 95
    assert world["keys"]["hud.ammo"]["display_char_limit"] == 80
    assert world["keys"]["menu.start"]["display_char_limit"] == 140

    hud = validate_success(
        api.write_translation_unit(
            world["units"]["hud.ammo"]["id"],
            f.translation_text_payload(_NINETY_FIVE_CHARS, 95, 80),
            users.VENDOR,
        )
    )
    menu = validate_success(
        api.write_translation_unit(
            world["units"]["menu.start"]["id"],
            f.translation_text_payload(_NINETY_FIVE_CHARS, 95, 96),
            users.VENDOR,
        )
    )

    assert hud["target_char_count"] == 95
    assert hud["overflow_chars"] == 15
    assert hud["translation_status"] == "DRAFTED"
    assert hud["qa_status"] == "NOT_CHECKED"
    A.assert_version_bumped_by(hud, world["units"]["hud.ammo"], 1,
                               "translation_unit")

    assert menu["target_char_count"] == 95
    assert menu["overflow_chars"] == 0
    assert menu["translation_status"] == "DRAFTED"
    assert menu["qa_status"] == "NOT_CHECKED"

    plan = fx.read_plan(api, world["plan"]["id"])
    assert plan["status"] == "IN_LOCALIZATION"
    assert plan["delivered_unit_count"] == 0
    assert plan["required_unit_count"] == 2


def test_a_client_supplied_target_char_count_is_replaced_by_the_text_length(api):
    """The count is computed from the stored text, not trusted from the body.

    "On success the server stores the text and recomputes `target_char_count` as
    the character length of `target_text` — zero when `target_text` is null — and
    recomputes `overflow_chars` as the amount by which `target_char_count` exceeds
    the linked string key's `display_char_limit`, floored at zero."

    "Writing target text touches only the first axis; flagging a defect touches
    only the second."

    A body claiming 5 characters for a 95-character string would put the unit 75
    characters inside the HUD key's 80-character limit; the recomputed figures are
    95 and an overflow of 15 regardless.

    Design: Corner/entities/translation_unit_overflow_chars_computed_from_display_char_limit
    """
    world = _de_market_with_a_tight_and_a_roomy_key(api)

    written = validate_success(
        api.write_translation_unit(
            world["units"]["hud.ammo"]["id"],
            f.translation_text_payload(_NINETY_FIVE_CHARS, 5, 80),
            users.VENDOR,
        )
    )

    assert written["target_text"] == _NINETY_FIVE_CHARS
    assert written["target_char_count"] == 95
    assert written["overflow_chars"] == 15
    assert written["applied_tm_match_pct"] == 80
    assert written["translation_status"] == "DRAFTED"
    assert written["qa_status"] == "NOT_CHECKED"
    stored = fx.read_unit(api, world["units"]["hud.ammo"]["id"])
    assert stored["target_char_count"] == 95
    assert stored["overflow_chars"] == 15


def test_supplied_system_fields_do_not_displace_a_new_qa_passs_defaults(api):
    """Hostile values for the computed fields change nothing about the row.

    "A new pass opens in `status` `OPEN` with `opened_by_user_id` set to the acting
    `X-User-ID`, `reopen_count` 0, `weighted_defect_points` 0, `defect_density`
    0.0000 and `closed_at_utc` null."

    "The server assigns `pass_index` as one more than the number of pre-existing
    passes with the same `market_plan_id` and `pass_type`, so the first linguistic
    pass over a market is index 1 and its successor is index 2."

    "Clients never supply `id`."

    "`version` starts at 1 when the row is created and increments by exactly 1 on
    every mutation of that row, including mutations caused by a cascade the client
    did not directly request."

    Design: Corner/entities/qa_pass_system_field_input_ignored
    """
    world = fx.build_market(api, title_code="NOVA-37", name="Nova Drift 37",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC],
                            stage=fx.STAGE_IN_LOCALIZATION)

    qa_pass = validate_success(
        api.create_qa_pass(
            f.qa_pass_payload(world["plan"]["id"], "LINGUISTIC", 100,
                              status="CLOSED", pass_index=99,
                              opened_by_user_id="somebody-else",
                              weighted_defect_points=500, defect_density=9.9999,
                              reopen_count=7, version=42),
            users.LQA_OPENER,
        ),
        expected_status=201,
    )

    assert qa_pass["market_plan_id"] == world["plan"]["id"]
    assert qa_pass["pass_type"] == "LINGUISTIC"
    assert qa_pass["inspected_unit_count"] == 100
    assert qa_pass["status"] == "OPEN"
    assert qa_pass["pass_index"] == 1
    assert qa_pass["opened_by_user_id"] == users.LQA_OPENER_USER_ID
    assert qa_pass["reopen_count"] == 0
    assert qa_pass["weighted_defect_points"] == 0
    A.assert_defect_density(qa_pass["defect_density"], 0.0000)
    assert qa_pass["closed_at_utc"] is None
    assert qa_pass["version"] == 1
    A.assert_new_qa_pass(qa_pass, users.LQA_OPENER_USER_ID)
    assert fx.read_qa_pass(api, qa_pass["id"])["pass_index"] == 1


def test_an_undeclared_scope_tier_and_a_mismatched_board_are_both_shape_errors(api):
    """Neither a plausible enum value nor the wrong board survives rung three.

    "**Request shape** — every required field present, every enum value inside its
    declared set, every integer non-negative where declared, every datetime a valid
    RFC 3339 UTC instant, every array actually an array; else `ERR_INVALID_REQUEST`
    (400)."

    "The supplied `rating_board` must equal the board that governs the supplied
    `market_code` per §2.9; a mismatch is `ERR_INVALID_REQUEST`."

    "Each market is governed by exactly one rating board: `JP` by `CERO`, `DE` by
    `USK`, `BR` by `DJCTQ`, `US` by `ESRB`, `AU` by `ACB`, and `KR` by `GRAC`."

    "`market_plan_count` is the number of market plans of the title with no status
    filter at all."

    Design: Corner/entities/market_plan_create_with_invalid_enum_scope_tier_rejected
    """
    title = fx.create_title(api, title_code="NOVA-38", name="Nova Drift 38",
                            release_mode="STAGGERED")
    assert "DUBBED" not in C.SCOPE_TIERS
    assert C.MARKET_BOARD["JP"] == "CERO"

    bad_tier = api.create_market_plan(
        f.market_plan_payload(title["id"], market_code="JP", scope_tier="DUBBED",
                              target_rating="TEEN_12", budget_cap_cents=5000000),
        users.PRODUCER,
    )
    bad_board = api.create_market_plan(
        f.market_plan_payload(title["id"], market_code="JP", rating_board="USK",
                              scope_tier="TEXT_ONLY", target_rating="TEEN_12",
                              budget_cap_cents=5000000),
        users.PRODUCER,
    )

    validate_error(bad_tier, E.ERR_INVALID_REQUEST, expected_status=400)
    validate_error(bad_board, E.ERR_INVALID_REQUEST, expected_status=400)
    assert fx.read_title(api, title["id"])["market_plan_count"] == 0
    _rows, meta = validate_paginated(
        api.list_market_plans(users.PRODUCER, {"title_id": title["id"]})
    )
    assert meta["total_count"] == 0


def _voiced_de_market_with_a_buffered_booth(api, *, title_code, booth_code):
    """A DE FULL_VOICE market in IN_LOCALIZATION with a booth and signed rights."""
    return fx.build_market(api, title_code=title_code,
                           name=f"Nova Drift {title_code[-2:]}",
                           market_code="DE", scope_tier="FULL_VOICE",
                           target_rating="MATURE_15", budget_cap_cents=9000000,
                           key_specs=[f.MENU_KEY_SPEC], booth_code=booth_code,
                           turnaround_buffer_minutes=30,
                           stage=fx.STAGE_IN_LOCALIZATION)


def test_an_inverted_window_is_a_shape_error_and_a_two_date_window_is_not(api):
    """The datetime pair is checked for order first and for containment later.

    "Two domain-specific shape checks live at this rung: on market-plan creation
    the supplied `rating_board` must equal the board that governs the supplied
    `market_code`, and on session booking `end_utc` must be strictly after
    `start_utc`."

    "Then single-date containment: `start_utc` and `end_utc` must fall on the same
    UTC calendar date, else `ERR_SESSION_SPANS_TWO_DATES`."

    "A booth's `reserved_minutes_total` is the sum, over every session on that
    booth whose `status` is `SCHEDULED`, `IN_PROGRESS` or `RECORDED`, of that
    session's `duration_minutes` plus the booth's `turnaround_buffer_minutes`."

    The 22:00-to-01:00 window is well formed and inside the rights window, so it
    travels further down the gauntlet and is refused by a different rule than the
    12:00-to-09:00 one, which never reaches the booth geometry at all.

    Design: Corner/entities/voice_session_with_end_before_start_rejected
    """
    world = _voiced_de_market_with_a_buffered_booth(api, title_code="NOVA-39",
                                                    booth_code="TOK-B")

    inverted = api.create_voice_session(
        f.voice_session_payload(world["plan"]["id"], world["talent"]["id"],
                                world["booth"]["id"], world["contract"]["id"],
                                start_utc="2026-09-10T12:00:00Z",
                                end_utc="2026-09-10T09:00:00Z",
                                planned_line_count=120),
        users.PRODUCER,
    )
    overnight = api.create_voice_session(
        f.voice_session_payload(world["plan"]["id"], world["talent"]["id"],
                                world["booth"]["id"], world["contract"]["id"],
                                start_utc="2026-09-10T22:00:00Z",
                                end_utc="2026-09-11T01:00:00Z",
                                planned_line_count=120),
        users.PRODUCER,
    )

    validate_error(inverted, E.ERR_INVALID_REQUEST, expected_status=400)
    validate_error(overnight, E.ERR_SESSION_SPANS_TWO_DATES, expected_status=422)
    A.assert_whole_minutes(
        fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"], 0,
        "reserved_minutes_total",
    )
    _rows, meta = validate_paginated(
        api.list_voice_sessions(users.PRODUCER,
                                {"market_plan_id": world["plan"]["id"]})
    )
    assert meta["total_count"] == 0


def test_a_string_key_naming_an_unknown_title_writes_no_orphan_row(api):
    """A body foreign key that does not resolve is the parent's own 404.

    "**Body foreign-key existence** — every foreign key in the body resolves, in
    entity field-declaration order, else the matching 404."

    "Foreign keys supplied inside a request body are resolved with the same error
    vocabulary, and they are resolved in the order the fields are declared on the
    target entity."

    "String keys can be listed and filtered by `title_id`, `status` and
    `ui_surface`."

    Design: Corner/entities/string_key_create_with_unknown_title_id_returns_not_found
    """
    response = api.create_string_key(
        f.string_key_payload(_MISSING_UUID, **f.MENU_KEY_SPEC), users.PRODUCER
    )

    validate_error(response, E.ERR_TITLE_NOT_FOUND, expected_status=404)
    _rows, meta = validate_paginated(api.list_string_keys(users.PRODUCER))
    assert meta["total_count"] == 0


def test_a_contract_covering_another_title_is_an_incoherent_booking_pair(api):
    """Both foreign keys resolve, yet the pair does not share an ancestor.

    "**Referential coherence** — two supplied references must share the ancestor
    the domain requires, else `ERR_CROSS_PARENT_MISMATCH` (422)."

    "Specifically: a translation unit's `string_key_id` must belong to the same
    title as its market plan; a session's `talent_contract_id` must reference a
    contract whose `voice_talent_id` equals the supplied `voice_talent_id` and whose
    `title_id` equals the market plan's `title_id`; a defect's
    `translation_unit_id` must belong to the market plan of the QA pass it is filed
    under; and every identifier in a content edit's `affected_string_key_ids` must
    belong to the submission's title."

    "Signature stamps `signed_at_utc` with the logical clock and opens the
    commitment ledger by setting `committed_fee_cents` to `buyout_fee_cents`,
    incrementing the contract's `version` by 1."

    The foreign contract resolves, so the 404 rung is satisfied and the refusal can
    only come from the coherence rung; the ledger it opened at signature keeps its
    500,000-cent buyout because the booking never happened.

    Design: Corner/entities/voice_session_contract_from_other_title_cross_parent_rejected
    """
    world = _voiced_de_market_with_a_buffered_booth(api, title_code="NOVA-40",
                                                    booth_code="TOK-C")
    other_title = fx.create_title(api, title_code="NOVA-41",
                                  name="Nova Drift 41", release_mode="STAGGERED")
    foreign = fx.signed_contract(api, world["talent"]["id"], other_title["id"],
                                 territory_scope=["DE"], media_scope="ALL_MEDIA",
                                 buyout_fee_cents=500000, per_line_rate_cents=250)
    assert foreign["status"] == "SIGNED"
    assert foreign["title_id"] == other_title["id"]
    assert other_title["id"] != world["title"]["id"]

    response = api.create_voice_session(
        f.voice_session_payload(world["plan"]["id"], world["talent"]["id"],
                                world["booth"]["id"], foreign["id"],
                                start_utc="2026-09-10T09:00:00Z",
                                end_utc="2026-09-10T12:00:00Z",
                                planned_line_count=120),
        users.PRODUCER,
    )

    validate_error(response, E.ERR_CROSS_PARENT_MISMATCH, expected_status=422)
    A.assert_whole_minutes(
        fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"], 0,
        "reserved_minutes_total",
    )
    A.assert_money_cents(fx.read_contract(api, foreign["id"])["committed_fee_cents"],
                         500000, "committed_fee_cents")
    _rows, meta = validate_paginated(
        api.list_voice_sessions(users.PRODUCER,
                                {"market_plan_id": world["plan"]["id"]})
    )
    assert meta["total_count"] == 0
