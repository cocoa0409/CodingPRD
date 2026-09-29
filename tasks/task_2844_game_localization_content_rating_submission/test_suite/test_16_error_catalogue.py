"""Reachability of the error catalogue: one code per entity, per scope, per rung.

Every refusal here is asserted together with the proof that nothing moved: the
target row keeps its status and its `version`, and every derived counter the
operation would have written still carries its old value.
"""

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

# ─── Instance: every_entity_type_has_its_own_reachable_not_found_error ──

# Twelve fabricated identifiers, one per path identifier of §2.4. None of them
# can collide with a server-minted id, and the store is deliberately non-empty
# so each 404 has to come from the id lookup rather than from an empty table.
NOT_FOUND_PROBES = [
    ("title_id", "00000000-0000-4000-8000-00000000ff01",
     E.ERR_TITLE_NOT_FOUND,
     lambda api, oid: api.get_title(oid, users.PRODUCER)),
    ("market_plan_id", "00000000-0000-4000-8000-00000000ff02",
     E.ERR_MARKET_PLAN_NOT_FOUND,
     lambda api, oid: api.get_market_plan(oid, users.PRODUCER)),
    ("string_key_id", "00000000-0000-4000-8000-00000000ff03",
     E.ERR_STRING_KEY_NOT_FOUND,
     lambda api, oid: api.get_string_key(oid, users.PRODUCER)),
    ("translation_unit_id", "00000000-0000-4000-8000-00000000ff04",
     E.ERR_TRANSLATION_UNIT_NOT_FOUND,
     lambda api, oid: api.get_translation_unit(oid, users.VENDOR)),
    ("recording_booth_id", "00000000-0000-4000-8000-00000000ff05",
     E.ERR_BOOTH_NOT_FOUND,
     lambda api, oid: api.get_booth(oid, users.PRODUCER)),
    ("voice_talent_id", "00000000-0000-4000-8000-00000000ff06",
     E.ERR_TALENT_NOT_FOUND,
     lambda api, oid: api.get_voice_talent(oid, users.PRODUCER)),
    ("talent_contract_id", "00000000-0000-4000-8000-00000000ff07",
     E.ERR_CONTRACT_NOT_FOUND,
     lambda api, oid: api.get_talent_contract(oid, users.PRODUCER)),
    ("voice_session_id", "00000000-0000-4000-8000-00000000ff08",
     E.ERR_SESSION_NOT_FOUND,
     lambda api, oid: api.get_voice_session(oid, users.PRODUCER)),
    ("qa_pass_id", "00000000-0000-4000-8000-00000000ff09",
     E.ERR_QA_PASS_NOT_FOUND,
     lambda api, oid: api.get_qa_pass(oid, users.LQA_OPENER)),
    ("lqa_bug_id", "00000000-0000-4000-8000-00000000ff0a",
     E.ERR_BUG_NOT_FOUND,
     lambda api, oid: api.get_lqa_bug(oid, users.LQA_OPENER)),
    ("rating_submission_id", "00000000-0000-4000-8000-00000000ff0b",
     E.ERR_SUBMISSION_NOT_FOUND,
     lambda api, oid: api.get_rating_submission(oid, users.COMPLIANCE)),
    ("content_edit_id", "00000000-0000-4000-8000-00000000ff0c",
     E.ERR_CONTENT_EDIT_NOT_FOUND,
     lambda api, oid: api.get_content_edit(oid, users.COMPLIANCE)),
]

_MISSING_QA_PASS_ID = "00000000-0000-4000-8000-00000000ff09"


def _title_with_one_key(api, title_code, name):
    """One real Title with one real StringKey, so every table probed is reachable."""
    title = fx.create_title(api, title_code=title_code, name=name)
    key = fx.create_string_key(api, title["id"], **f.MENU_KEY_SPEC)
    return {"title": title, "key": key}


def test_each_of_the_twelve_path_identifiers_has_its_own_not_found_code(api):
    """Twelve entities carry twelve distinct 404 codes, not one shared code.

    "The path identifiers used in this API are `title_id`, `market_plan_id`,
    `string_key_id`, `translation_unit_id`, `recording_booth_id`,
    `voice_talent_id`, `talent_contract_id`, `voice_session_id`, `qa_pass_id`,
    `lqa_bug_id`, `rating_submission_id` and `content_edit_id`."

    "Each resolves to `ERR_TITLE_NOT_FOUND`, `ERR_MARKET_PLAN_NOT_FOUND`,
    `ERR_STRING_KEY_NOT_FOUND`, `ERR_TRANSLATION_UNIT_NOT_FOUND`,
    `ERR_BOOTH_NOT_FOUND`, `ERR_TALENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, `ERR_QA_PASS_NOT_FOUND`, `ERR_BUG_NOT_FOUND`,
    `ERR_SUBMISSION_NOT_FOUND` and `ERR_CONTENT_EDIT_NOT_FOUND` respectively,
    all HTTP 404."

    "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/errors/every_entity_type_has_its_own_reachable_not_found_error
    """
    world = _title_with_one_key(api, "NOVA-73", "Nova Drift 73")

    seen = []
    for path_id, missing_id, expected_error, probe in NOT_FOUND_PROBES:
        validate_error(probe(api, missing_id), expected_error, expected_status=404)
        assert E.NOT_FOUND_BY_PATH_ID[path_id] == expected_error
        seen.append(expected_error)

    assert len(set(seen)) == 12, f"Expected twelve distinct 404 codes, got {seen}"

    # The 404s above were id lookups, not a mis-wired route: the real rows read.
    still_there = validate_success(
        api.get_string_key(world["key"]["id"], users.PRODUCER)
    )
    assert still_there["id"] == world["key"]["id"]
    assert still_there["status"] == "EXTRACTED"
    A.assert_unchanged_row(still_there, world["key"], "string_key")
    assert fx.read_title(api, world["title"]["id"])["extracted_key_count"] == 1


def test_a_missing_path_row_is_reported_before_its_state_is_examined(api):
    """An action on a nonexistent pass is a 404, never a state conflict.

    "Path identifiers are validated left to right, and the first unresolvable
    identifier decides the error."

    "When one request violates several rules at once, the server returns the
    error of the highest-precedence rule that is violated and does not evaluate
    any later rule."

    "The pass must be `OPEN`, else `ERR_QA_PASS_NOT_OPEN`."

    Path existence sits at rung 4 and the own-state precondition at rung 11, so
    the id resolves first and the state check is never reached.

    Design: Corner/errors/every_entity_type_has_its_own_reachable_not_found_error
    """
    world = _title_with_one_key(api, "NOVA-73", "Nova Drift 73")

    response = api.close_qa_pass(_MISSING_QA_PASS_ID, users.LQA_CLOSER)

    validate_error(response, E.ERR_QA_PASS_NOT_FOUND, expected_status=404)
    passes, meta = validate_paginated(api.list_qa_passes(users.LQA_OPENER))
    assert meta["total_count"] == 0
    assert passes == []
    assert fx.read_title(api, world["title"]["id"])["market_plan_count"] == 0


# ─── Instance: duplicate_title_code_is_global_while_duplicate_string_key ─
# ─── _is_per_title ──────────────────────────────────────────────────────


def _two_titles_one_owning_the_menu_key(api):
    """NOVA-74A owns menu.start; NOVA-74B is an empty sibling title."""
    title_a = fx.create_title(api, title_code="NOVA-74A", name="Nova Drift 74 A")
    title_b = fx.create_title(api, title_code="NOVA-74B", name="Nova Drift 74 B")
    key_a = fx.create_string_key(api, title_a["id"], **f.MENU_KEY_SPEC)
    # "Every new key starts in `status` `EXTRACTED` and increments the title's
    # `extracted_key_count`" — that increment is a mutation of the title, so its
    # `version` has already moved to 2 by the end of setup. The baseline for
    # "the refused write changed nothing" must therefore be read after setup
    # rather than taken from the creation response.
    title_a = fx.read_title(api, title_a["id"])
    return {"title_a": title_a, "title_b": title_b, "key_a": key_a}


def test_a_reused_title_code_is_refused_across_the_whole_system(api):
    """`title_code` uniqueness is global, even when every other field differs.

    "A title's `title_code` is unique across every title row; a collision is
    `ERR_DUPLICATE_TITLE_CODE`."

    "Four uniqueness rules are enforced at HTTP 409."

    Design: Corner/errors/duplicate_title_code_is_global_while_duplicate_string_key_is_per_title
    """
    world = _two_titles_one_owning_the_menu_key(api)

    response = api.create_title(
        f.title_payload(title_code="NOVA-74A", name="Nova Drift 74 A reprise",
                        source_language="JA",
                        target_release_utc="2027-01-01T00:00:00Z",
                        release_mode="SIMULTANEOUS"),
        users.PRODUCER,
    )

    validate_error(response, E.ERR_DUPLICATE_TITLE_CODE, expected_status=409)
    titles, meta = validate_paginated(api.list_titles(users.PRODUCER))
    assert meta["total_count"] == 2, "A 409 must not create a partial title row"
    assert [row["title_code"] for row in titles] == ["NOVA-74A", "NOVA-74B"]
    after = fx.read_title(api, world["title_a"]["id"])
    assert after["name"] == "Nova Drift 74 A"
    assert after["source_language"] == "EN"
    A.assert_unchanged_row(after, world["title_a"], "title")


def test_a_reused_key_name_is_refused_only_inside_its_own_title(api):
    """`key_name` uniqueness is scoped to the parent title, not global.

    "A string key's `key_name` is unique within its `title_id`; a collision is
    `ERR_DUPLICATE_STRING_KEY`."

    "Every new key starts in `status` `EXTRACTED` and increments the title's
    `extracted_key_count`."

    Design: Corner/errors/duplicate_title_code_is_global_while_duplicate_string_key_is_per_title
    """
    world = _two_titles_one_owning_the_menu_key(api)

    response = api.create_string_key(
        f.string_key_payload(world["title_a"]["id"], key_name="menu.start",
                             source_text="Begin Game", source_char_count=100,
                             ui_surface="MENU", display_char_limit=140,
                             tm_match_pct=90),
        users.PRODUCER,
    )

    validate_error(response, E.ERR_DUPLICATE_STRING_KEY, expected_status=409)
    rows, meta = validate_paginated(
        api.list_string_keys(users.PRODUCER, {"title_id": world["title_a"]["id"]})
    )
    assert meta["total_count"] == 1, "A 409 must not create a partial string key"
    assert rows[0]["source_text"] == "Start Game"
    A.assert_unchanged_row(rows[0], world["key_a"], "string_key")
    assert fx.read_title(api, world["title_a"]["id"])["extracted_key_count"] == 1

    # The same key_name under the sibling title is a different key entirely.
    twin = validate_success(
        api.create_string_key(
            f.string_key_payload(world["title_b"]["id"], **f.MENU_KEY_SPEC),
            users.PRODUCER,
        ),
        expected_status=201,
    )
    assert twin["title_id"] == world["title_b"]["id"]
    assert twin["key_name"] == "menu.start"
    assert twin["status"] == "EXTRACTED"
    assert fx.read_title(api, world["title_b"]["id"])["extracted_key_count"] == 1


# ─── Instance: talent_agent_ownership_and_the_draft_only_signing_window ──


def _two_talents_with_a_draft_contract_each(api):
    """Title NOVA-75 with talents A (JA) and B (KO), one DRAFT contract per talent."""
    title = fx.create_title(api, title_code="NOVA-75", name="Nova Drift 75")
    talent_a = fx.create_talent(api, "Miki Sato", "JA", False, 240)
    talent_b = fx.create_talent(api, "Ji-hoon Park", "KO", True, 180)
    contract_a = fx.draft_contract(
        api, talent_a["id"], title["id"], territory_scope=["JP"],
        media_scope="IN_GAME_AND_TRAILER", buyout_fee_cents=400000,
        per_line_rate_cents=200, rights_start_utc="2026-08-01T00:00:00Z",
        rights_end_utc="2026-12-31T00:00:00Z",
    )
    contract_b = fx.draft_contract(
        api, talent_b["id"], title["id"], territory_scope=["KR"],
        media_scope="IN_GAME_ONLY", buyout_fee_cents=300000,
        per_line_rate_cents=150, rights_start_utc="2026-08-01T00:00:00Z",
        rights_end_utc="2026-12-31T00:00:00Z",
    )
    return {"title": title, "talent_a": talent_a, "talent_b": talent_b,
            "contract_a": contract_a, "contract_b": contract_b}


def test_an_agent_may_not_sign_the_contract_of_another_talent(api):
    """TalentAgent is entity-backed, so the acting id must be the contract's talent.

    "`TalentAgent` is the single exception and is entity-backed."

    "Concretely, a `TalentAgent` may only sign a talent contract whose
    `voice_talent_id` equals its own `X-User-ID`, and may only start or complete a
    recording session whose `voice_talent_id` equals its own `X-User-ID`."

    "A mismatch on any of those three operations is rejected with
    `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

    Design: Corner/errors/talent_agent_ownership_and_the_draft_only_signing_window
    """
    world = _two_talents_with_a_draft_contract_each(api)
    contract_a = world["contract_a"]
    assert contract_a["status"] == "DRAFT"

    response = api.sign_talent_contract(
        contract_a["id"], users.make_talent_agent_headers(world["talent_b"]["id"])
    )

    validate_error(response, E.ERR_OWNERSHIP_VIOLATION, expected_status=403)
    after = fx.read_contract(api, contract_a["id"])
    assert after["status"] == "DRAFT"
    assert after["signed_at_utc"] is None
    A.assert_money_cents(after["committed_fee_cents"], 0, "committed_fee_cents")
    A.assert_unchanged_row(after, contract_a, "talent_contract")


def test_the_second_signature_is_refused_because_draft_is_the_only_source(api):
    """The ownership rung passes, so the own-state rung is what fires.

    "The contract must be in `DRAFT`, else `ERR_CONTRACT_NOT_DRAFT`, and the
    logical clock must be strictly before `rights_end_utc`."

    "Signature stamps `signed_at_utc` with the logical clock and opens the
    commitment ledger by setting `committed_fee_cents` to `buyout_fee_cents`,
    incrementing the contract's `version` by 1."

    Design: Corner/errors/talent_agent_ownership_and_the_draft_only_signing_window
    """
    world = _two_talents_with_a_draft_contract_each(api)
    signed = validate_success(
        api.sign_talent_contract(
            world["contract_a"]["id"],
            users.make_talent_agent_headers(world["talent_a"]["id"]),
        )
    )
    assert signed["status"] == "SIGNED"
    A.assert_instant_equals(signed["signed_at_utc"], C.CLOCK_STARTUP_UTC,
                            "signed_at_utc")
    A.assert_money_cents(signed["committed_fee_cents"], 400000,
                         "committed_fee_cents")
    A.assert_version_bumped_by(signed, world["contract_a"], 1, "talent_contract")

    response = api.sign_talent_contract(
        world["contract_a"]["id"],
        users.make_talent_agent_headers(world["talent_a"]["id"]),
    )

    validate_error(response, E.ERR_CONTRACT_NOT_DRAFT, expected_status=409)
    after = fx.read_contract(api, world["contract_a"]["id"])
    assert after["status"] == "SIGNED"
    A.assert_money_cents(after["committed_fee_cents"], 400000,
                         "committed_fee_cents")
    A.assert_unchanged_row(after, signed, "talent_contract")


def test_terminating_a_draft_contract_raises_the_same_code_from_the_other_side(api):
    """One code covers both "sign requires DRAFT" and "terminate requires SIGNED".

    "Terminating a signed contract moves it `SIGNED → TERMINATED` under a
    `LocalizationProducer`; a contract that is not `SIGNED` is refused with
    `ERR_CONTRACT_NOT_DRAFT`."

    "A new contract opens in `status` `DRAFT` with `signed_at_utc` null and
    `committed_fee_cents` 0, and it increments the talent's `version`."

    Design: Corner/errors/talent_agent_ownership_and_the_draft_only_signing_window
    """
    world = _two_talents_with_a_draft_contract_each(api)
    contract_b = world["contract_b"]

    response = api.terminate_talent_contract(contract_b["id"], users.PRODUCER)

    validate_error(response, E.ERR_CONTRACT_NOT_DRAFT, expected_status=409)
    after = fx.read_contract(api, contract_b["id"])
    assert after["status"] == "DRAFT"
    assert after["signed_at_utc"] is None
    A.assert_money_cents(after["committed_fee_cents"], 0, "committed_fee_cents")
    A.assert_unchanged_row(after, contract_b, "talent_contract")

    # The signed sibling terminates cleanly, which is what makes the refusal above
    # a state rule rather than a missing capability.
    signed = fx.sign_contract(api, world["contract_a"]["id"],
                              world["talent_a"]["id"])
    terminated = validate_success(
        api.terminate_talent_contract(signed["id"], users.PRODUCER)
    )
    assert terminated["status"] == "TERMINATED"
    A.assert_version_bumped_by(terminated, signed, 1, "talent_contract")


# ─── Instance: rights_window_and_single_utc_date_are_two_separate_session ─
# ─── _guards ────────────────────────────────────────────────────────────

# The JP contract's usage rights run 2026-08-01 .. 2026-09-30, and the booth
# carries a zero teardown buffer so the booth geometry never masks the two
# guards under test.
_RIGHTS_END_UTC = "2026-09-30T00:00:00Z"


def _jp_voiced_market_with_a_september_rights_window(api):
    title = fx.create_title(api, title_code="NOVA-76", name="Nova Drift 76")
    keys = {"menu.start": fx.create_string_key(api, title["id"], **f.MENU_KEY_SPEC)}
    plan = fx.create_market_plan(api, title["id"], market_code="JP",
                                 scope_tier="FULL_VOICE", target_rating="TEEN_12",
                                 budget_cap_cents=9000000)
    booth = fx.create_booth(api, "TOK-J", "Tokyo", 0)
    talent = fx.create_talent(api, "Miki Sato", "JA", False, 240)
    contract = fx.signed_contract(
        api, talent["id"], title["id"], territory_scope=["JP"],
        media_scope="IN_GAME_AND_TRAILER", buyout_fee_cents=400000,
        per_line_rate_cents=200, rights_start_utc="2026-08-01T00:00:00Z",
        rights_end_utc=_RIGHTS_END_UTC,
    )
    fx.lock_strings(api, title["id"])
    fx.scope_plan(api, plan["id"])
    plan = fx.start_localization(api, plan["id"])
    return {"title": title, "keys": keys, "plan": plan, "booth": booth,
            "talent": talent, "contract": contract}


def _booking(world, start_utc, end_utc, planned_line_count=60):
    return f.voice_session_payload(
        world["plan"]["id"], world["talent"]["id"], world["booth"]["id"],
        world["contract"]["id"], start_utc=start_utc, end_utc=end_utc,
        planned_line_count=planned_line_count,
    )


def _assert_no_session_was_created(api, world):
    sessions, meta = validate_paginated(
        api.list_voice_sessions(users.PRODUCER,
                                {"market_plan_id": world["plan"]["id"]})
    )
    assert meta["total_count"] == 0
    assert sessions == []
    A.assert_whole_minutes(
        fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"], 0,
        "reserved_minutes_total",
    )
    A.assert_money_cents(
        fx.read_contract(api, world["contract"]["id"])["committed_fee_cents"],
        400000, "committed_fee_cents",
    )


def test_a_booking_reaching_past_the_rights_end_is_refused(api):
    """A window ending after `rights_end_utc` fails even though it is one date.

    "Then the rights window: `rights_start_utc` must be at or before `start_utc`
    and `end_utc` must be at or before `rights_end_utc`, else
    `ERR_CONTRACT_RIGHTS_WINDOW_EXCEEDED`."

    "Then rights coverage: the contract's `territory_scope` must contain the
    market plan's `market_code`, and the contract's `media_scope` must not be
    `IN_GAME_ONLY` when the market plan's `scope_tier` is `FULL_CULTURAL`; either
    failure is `ERR_CONTRACT_TERRITORY_NOT_COVERED`."

    JP is inside the contract's territory scope, so the coverage rung passes and
    the window rung is what refuses the 5 October booking.

    Design: Corner/errors/rights_window_and_single_utc_date_are_two_separate_session_guards
    """
    world = _jp_voiced_market_with_a_september_rights_window(api)
    assert world["contract"]["status"] == "SIGNED"
    A.assert_instant_equals(world["contract"]["rights_end_utc"], _RIGHTS_END_UTC,
                            "rights_end_utc")

    response = api.create_voice_session(
        _booking(world, "2026-10-05T09:00:00Z", "2026-10-05T11:00:00Z"),
        users.PRODUCER,
    )

    validate_error(response, E.ERR_CONTRACT_RIGHTS_WINDOW_EXCEEDED,
                   expected_status=422)
    _assert_no_session_was_created(api, world)


def test_a_booking_crossing_midnight_inside_the_window_is_refused(api):
    """A window fully inside the rights period still fails the single-date rule.

    "Then single-date containment: `start_utc` and `end_utc` must fall on the
    same UTC calendar date, else `ERR_SESSION_SPANS_TWO_DATES`."

    "Because a session is required to start and end on the same UTC date, no
    session ever straddles two date buckets."

    Both endpoints of the 23:00 to 01:00 booking sit inside 2026-08-01 ..
    2026-09-30, so the rights rung is satisfied and the date rung is not.

    Design: Corner/errors/rights_window_and_single_utc_date_are_two_separate_session_guards
    """
    world = _jp_voiced_market_with_a_september_rights_window(api)

    response = api.create_voice_session(
        _booking(world, "2026-09-15T23:00:00Z", "2026-09-16T01:00:00Z"),
        users.PRODUCER,
    )

    validate_error(response, E.ERR_SESSION_SPANS_TWO_DATES, expected_status=422)
    _assert_no_session_was_created(api, world)


def test_the_last_evening_inside_the_window_books_cleanly(api):
    """A 22:00 to 23:59 booking clears both guards at once.

    "A successful booking derives `duration_minutes` as the whole minutes between
    `start_utc` and `end_utc`, derives `occupied_end_utc`, opens the session in
    `status` `SCHEDULED` with `recorded_line_count` null and `line_fee_cents` 0,
    and increases the booth's `reserved_minutes_total` by the session's duration
    plus the booth buffer."

    "That buffer is the mandatory teardown-and-setup gap appended to every
    booking of this booth, and it is always read from the booth row and never
    from the session."

    The booth's buffer is zero, so `occupied_end_utc` equals `end_utc` and the
    119-minute booking reserves exactly 119 minutes.

    Design: Corner/errors/rights_window_and_single_utc_date_are_two_separate_session_guards
    """
    world = _jp_voiced_market_with_a_september_rights_window(api)
    A.assert_whole_minutes(world["booth"]["turnaround_buffer_minutes"], 0,
                           "turnaround_buffer_minutes")

    booked = validate_success(
        api.create_voice_session(
            _booking(world, "2026-09-15T22:00:00Z", "2026-09-15T23:59:00Z"),
            users.PRODUCER,
        ),
        expected_status=201,
    )

    assert booked["status"] == "SCHEDULED"
    A.assert_whole_minutes(booked["duration_minutes"], 119, "duration_minutes")
    A.assert_instant_equals(booked["occupied_end_utc"], "2026-09-15T23:59:00Z",
                            "occupied_end_utc")
    assert booked["recorded_line_count"] is None
    A.assert_money_cents(booked["line_fee_cents"], 0, "line_fee_cents")
    A.assert_whole_minutes(
        fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"], 119,
        "reserved_minutes_total",
    )


# ─── Instance: mandatory_disclosure_gap_is_the_winning_error_on_a_german ──
# ─── _submission ────────────────────────────────────────────────────────

# The German questionnaire must declare GAMBLING_SIM, so this pair of
# descriptors is a complete questionnaire everywhere except DE.
_DE_INCOMPLETE_DISCLOSURE = ["BLOOD", "VIOLENCE_STYLIZED"]
_DE_COMPLETE_DISCLOSURE = ["BLOOD", "VIOLENCE_STYLIZED", "GAMBLING_SIM"]


def _de_market_with_an_incomplete_first_round(api):
    """A USK market at LQA holding a DRAFT package that never names GAMBLING_SIM."""
    world = fx.build_market(api, title_code="NOVA-77", name="Nova Drift 77",
                            market_code="DE", scope_tier="TEXT_ONLY",
                            target_rating="MATURE_15", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)
    world["submission"] = fx.draft_submission(api, world["plan"]["id"],
                                              _DE_INCOMPLETE_DISCLOSURE, 0,
                                              "MATURE_15")
    return world


def test_a_german_package_without_the_gambling_disclosure_cannot_be_filed(api):
    """The disclosure rung is keyed on the market code, not on the rating.

    "Every descriptor that §2.9 makes mandatory for the market's `market_code`
    must appear in `disclosed_content_codes`; a missing one is
    `ERR_MANDATORY_DISCLOSURE_MISSING`."

    "Mandatory disclosures — descriptors a market's questionnaire must declare —
    are: `DE` requires `GAMBLING_SIM`; `KR` requires `LOOTBOX_PAID`."

    The zero footage count would also be refusable, but the footage rung sits
    below the disclosure rung, so the questionnaire gap is what is reported.

    Design: Corner/errors/mandatory_disclosure_gap_is_the_winning_error_on_a_german_submission
    """
    world = _de_market_with_an_incomplete_first_round(api)
    submission = world["submission"]
    assert submission["rating_board"] == "USK"
    assert submission["submission_round"] == 1
    assert submission["footage_asset_count"] == 0

    response = api.submit_rating_submission(submission["id"], users.COMPLIANCE)

    validate_error(response, E.ERR_MANDATORY_DISCLOSURE_MISSING,
                   expected_status=422)
    after = fx.read_submission(api, submission["id"])
    assert after["status"] == "DRAFT"
    assert after["submitted_at_utc"] is None
    assert after["submitted_by_user_id"] is None
    assert after["self_assessed_risk_score"] is None
    A.assert_money_cents(after["fee_cents"], 0, "fee_cents")
    A.assert_unchanged_row(after, submission, "rating_submission")


def test_the_corrected_second_round_supersedes_the_draft_and_is_priced(api):
    """There is no PATCH, so the repair is a new round that carries a surcharge.

    "Creating a submission also supersedes the market's prior non-terminal
    submission into `WITHDRAWN`."

    "Step one computes a pre-discount subtotal as the board's base fee plus
    75,000 cents for each round beyond the first — that is, the base fee plus
    `submission_round` minus one, multiplied by the round surcharge."

    "The `SELF_ASSESSED` variant is the publisher's own questionnaire arithmetic:
    it is the base points alone, clamped to lie between 0 and 100 inclusive, and
    it ignores unresolved legal defects and content edits entirely."

    The USK round-two subtotal is 425,000, no expedite applies 122 days out, the
    tier keyed on 425,000 is five per cent and the discount is 21,250, so the fee
    is 403,750. `BLOOD` 15 plus `VIOLENCE_STYLIZED` 12 plus `GAMBLING_SIM` 18 is
    45 self-assessed points.

    Design: Corner/errors/mandatory_disclosure_gap_is_the_winning_error_on_a_german_submission
    """
    world = _de_market_with_an_incomplete_first_round(api)
    round_two = fx.draft_submission(api, world["plan"]["id"],
                                    _DE_COMPLETE_DISCLOSURE, 2, "MATURE_15")
    assert round_two["submission_round"] == 2
    assert fx.read_submission(api, world["submission"]["id"])["status"] == \
        "WITHDRAWN"

    filed = validate_success(
        api.submit_rating_submission(round_two["id"], users.COMPLIANCE)
    )

    assert filed["status"] == "SUBMITTED"
    A.assert_instant_equals(filed["submitted_at_utc"], C.CLOCK_STARTUP_UTC,
                            "submitted_at_utc")
    assert filed["self_assessed_risk_score"] == 45
    assert A.band_for_score(45) == "MATURE_15"
    A.assert_money_cents(filed["fee_cents"], 403750, "fee_cents")
    assert filed["projected_rating_band"] is None
    assert filed["assigned_rating"] is None
    A.assert_version_bumped_by(filed, round_two, 1, "rating_submission")


# ─── Instance: content_edit_apply_and_withdraw_both_require_the_proposed ──
# ─── _state ─────────────────────────────────────────────────────────────


def _edits_required_market_with_two_proposed_edits(api):
    """A JP package sent back for edits, carrying one text edit and one age gate."""
    world = fx.build_market_with_edits_required(
        api, title_code="NOVA-78", name="Nova Drift 78", market_code="JP",
        scope_tier="TEXT_ONLY", target_rating="ALL_AGES",
        budget_cap_cents=5000000, key_specs=[f.MENU_KEY_SPEC],
        disclosed_content_codes=["VIOLENCE_STYLIZED"], footage_asset_count=0,
    )
    world["edit_1"] = fx.propose_content_edit(
        api, world["submission"]["id"], edit_kind="TEXT_REWRITE",
        rationale="Soften the taunt line flagged by the board.",
        affected_string_key_ids=[world["keys"]["menu.start"]["id"]],
    )
    world["edit_2"] = fx.propose_content_edit(
        api, world["submission"]["id"], edit_kind="AGE_GATE",
        rationale="Add a launch-time age gate for the JP build.",
    )
    world["unit"] = fx.list_units(api, world["plan"]["id"])[0]
    return world


def test_a_withdrawn_edit_can_be_neither_applied_nor_withdrawn_again(api):
    """WITHDRAWN is terminal, and both verbs report the one code.

    "Applying an edit is the deepest cascade in this system, driven by a
    `ComplianceOfficer`, and it runs `PROPOSED → APPLIED`. The edit must be
    `PROPOSED`, else `ERR_CONTENT_EDIT_NOT_PROPOSED`."

    "Withdrawing a proposed edit moves it `PROPOSED → WITHDRAWN` under a
    `ComplianceOfficer` or a `LocalizationProducer`; an edit that is not
    `PROPOSED` refuses with `ERR_CONTENT_EDIT_NOT_PROPOSED`."

    "There is no cascade, because nothing was applied: no translation unit, QA
    pass or market plan changes state."

    Design: Corner/errors/content_edit_apply_and_withdraw_both_require_the_proposed_state
    """
    world = _edits_required_market_with_two_proposed_edits(api)
    assert world["submission"]["status"] == "EDITS_REQUIRED"
    assert world["edit_1"]["status"] == "PROPOSED"
    assert world["edit_1"]["invalidated_unit_count"] == 0
    assert world["edit_1"]["applied_at_utc"] is None

    withdrawn = validate_success(
        api.withdraw_content_edit(world["edit_1"]["id"], users.COMPLIANCE)
    )
    assert withdrawn["status"] == "WITHDRAWN"
    A.assert_version_bumped_by(withdrawn, world["edit_1"], 1, "content_edit")
    assert fx.read_unit(api, world["unit"]["id"])["translation_status"] == \
        "DELIVERED"

    apply_response = api.apply_content_edit(world["edit_1"]["id"], users.COMPLIANCE)

    validate_error(apply_response, E.ERR_CONTENT_EDIT_NOT_PROPOSED,
                   expected_status=409)
    after_apply = fx.read_content_edit(api, world["edit_1"]["id"])
    assert after_apply["status"] == "WITHDRAWN"
    assert after_apply["applied_at_utc"] is None
    assert after_apply["invalidated_unit_count"] == 0
    A.assert_unchanged_row(after_apply, withdrawn, "content_edit")
    # Not one hop of the six-hop cascade ran.
    unit_after = fx.read_unit(api, world["unit"]["id"])
    assert unit_after["translation_status"] == "DELIVERED"
    A.assert_unchanged_row(unit_after, world["unit"], "translation_unit")
    plan_after = fx.read_plan(api, world["plan"]["id"])
    assert plan_after["status"] == "LQA"
    assert plan_after["delivered_unit_count"] == 1
    assert fx.read_title(api, world["title"]["id"])["localization_state"] == \
        "CERT_WINDOW"

    withdraw_again = api.withdraw_content_edit(world["edit_1"]["id"],
                                               users.COMPLIANCE)

    validate_error(withdraw_again, E.ERR_CONTENT_EDIT_NOT_PROPOSED,
                   expected_status=409)
    A.assert_unchanged_row(fx.read_content_edit(api, world["edit_1"]["id"]),
                           withdrawn, "content_edit")


def test_withdrawing_the_submission_withdraws_its_proposed_edits(api):
    """The second edit becomes non-applicable without ever being touched.

    "Withdrawal also withdraws every content edit under that submission whose
    `status` is `PROPOSED`."

    "Withdrawal takes a submission from any of `DRAFT`, `SUBMITTED`,
    `UNDER_REVIEW` or `EDITS_REQUIRED` to `WITHDRAWN`, which is terminal; an
    already-withdrawn submission refuses with `ERR_SUBMISSION_STATE_INVALID`."

    Design: Corner/errors/content_edit_apply_and_withdraw_both_require_the_proposed_state
    """
    world = _edits_required_market_with_two_proposed_edits(api)
    assert world["edit_2"]["status"] == "PROPOSED"

    cascaded = validate_success(
        api.withdraw_rating_submission(world["submission"]["id"], users.COMPLIANCE)
    )

    assert cascaded["status"] == "WITHDRAWN"
    A.assert_version_bumped_by(cascaded, world["submission"], 1,
                               "rating_submission")
    edit_2_after = fx.read_content_edit(api, world["edit_2"]["id"])
    assert edit_2_after["status"] == "WITHDRAWN"
    assert edit_2_after["applied_at_utc"] is None

    response = api.apply_content_edit(world["edit_2"]["id"], users.COMPLIANCE)

    validate_error(response, E.ERR_CONTENT_EDIT_NOT_PROPOSED, expected_status=409)
    A.assert_unchanged_row(fx.read_content_edit(api, world["edit_2"]["id"]),
                           edit_2_after, "content_edit")
    assert fx.read_unit(api, world["unit"]["id"])["translation_status"] == \
        "DELIVERED"
    assert fx.read_plan(api, world["plan"]["id"])["status"] == "LQA"


# ─── Instance: text_overflow_gate_needs_both_the_unit_waiver_and_a_closed ──
# ─── _overflow_bug ──────────────────────────────────────────────────────

# One HUD key whose display budget is 80 characters, delivered at 95, so the
# stored unit carries exactly 15 overflow characters.
_OVERFLOWING_HUD_KEY = {
    "key_name": "hud.ammo",
    "source_text": "Ammo",
    "source_char_count": 60,
    "ui_surface": "HUD",
    "display_char_limit": 80,
    "tm_match_pct": 96,
}
_OVERLONG_HUD_TEXT = "Restliche Munition: " + "9" * 75


def _rated_jp_market_carrying_an_overflowing_unit(api):
    """A RATED JP market whose only unit overruns its HUD budget by 15 characters.

    The S1 overflow finding is logged against a 200-unit sample, which keeps the
    density under the ceiling so the pass can still be closed.
    """
    world = fx.build_market(api, title_code="NOVA-79", name="Nova Drift 79",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="ALL_AGES", budget_cap_cents=5000000,
                            key_specs=[_OVERFLOWING_HUD_KEY],
                            stage=fx.STAGE_IN_LOCALIZATION)
    unit = fx.list_units(api, world["plan"]["id"])[0]
    world["unit"] = fx.draft_and_deliver_unit(api, unit["id"], _OVERLONG_HUD_TEXT, 96)
    world["plan"] = fx.enter_lqa(api, world["plan"]["id"])
    submission = fx.draft_submission(api, world["plan"]["id"],
                                     ["VIOLENCE_STYLIZED"], 0, "ALL_AGES")
    world["submission"] = fx.rate_submission(api, submission["id"], "ALL_AGES")
    world["qa_pass"] = fx.open_qa_pass(api, world["plan"]["id"], "LINGUISTIC", 200)
    world["bug"] = fx.log_bug(api, world["qa_pass"]["id"],
                              translation_unit_id=world["unit"]["id"],
                              bug_class="TEXT_OVERFLOW", severity="S1",
                              summary="Ammo readout overruns the 80-character HUD budget")
    world["qa_pass"] = fx.close_qa_pass(api, world["qa_pass"]["id"])
    # Filing the package bumped the plan's version, so re-read the before-image.
    world["plan"] = fx.read_plan(api, world["plan"]["id"])
    return world


def test_an_overflowing_unit_blocks_release_even_after_its_pass_closes(api):
    """The density gate lets the pass close; the release gate still refuses.

    "No translation unit of the plan may still carry `overflow_chars` greater than
    zero while its `qa_status` is anything other than `PASSED`, and no defect of
    `bug_class` `TEXT_OVERFLOW` or `TRUNCATION` may remain in `NEW`, `TRIAGED` or
    `FIX_SUBMITTED`; either leftover is `ERR_TEXT_OVERFLOW_UNRESOLVED`."

    "Delivery is deliberately permitted while `overflow_chars` is greater than
    zero: overflow is a QA finding, not a delivery gate."

    "Logging a defect whose derived axis is functional drives the unit to
    `FUNC_FLAGGED`, but only from `NOT_CHECKED` or from `PASSED`; a unit already
    sitting at `LING_FLAGGED` is **not** overwritten by a functional finding."

    One S1 finding over 200 inspected units is a density of 0.0400, strictly under
    the ceiling, so the quality gate never treats this defect as blocking.

    Design: Corner/errors/text_overflow_gate_needs_both_the_unit_waiver_and_a_closed_overflow_bug
    """
    world = _rated_jp_market_carrying_an_overflowing_unit(api)
    unit = fx.read_unit(api, world["unit"]["id"])
    assert unit["target_char_count"] == 95
    assert unit["overflow_chars"] == 15
    assert unit["translation_status"] == "DELIVERED"
    assert unit["qa_status"] == "FUNC_FLAGGED"
    assert world["qa_pass"]["status"] == "CLOSED"
    assert world["qa_pass"]["weighted_defect_points"] == 8
    A.assert_defect_density(world["qa_pass"]["defect_density"], 0.0400)
    assert world["submission"]["status"] == "RATED"
    assert world["submission"]["assigned_rating"] == "ALL_AGES"

    response = api.mark_release_ready(world["plan"]["id"], users.COMPLIANCE)

    validate_error(response, E.ERR_TEXT_OVERFLOW_UNRESOLVED, expected_status=422)
    plan_after = fx.read_plan(api, world["plan"]["id"])
    assert plan_after["status"] == "LQA"
    A.assert_unchanged_row(plan_after, world["plan"], "market_plan")
    title_after = fx.read_title(api, world["title"]["id"])
    assert title_after["localization_state"] == "CERT_WINDOW"
    assert title_after["ready_market_count"] == 0
    A.assert_unchanged_row(fx.read_unit(api, world["unit"]["id"]), unit,
                           "translation_unit")


def test_rejecting_the_overflow_defect_alone_does_not_open_the_gate(api):
    """Priority 58 is a conjunction, so clearing one clause is not enough.

    "`REJECT` moves the defect `NEW → REJECTED`. The pass's
    `weighted_defect_points` and `defect_density` are recomputed and drop, because
    the defect leaves the open set."

    "The linked unit's `open_bug_count` is recomputed, but its `qa_status` is
    deliberately **not** reset — it stays flagged until an inspection outcome is
    recorded."

    "No translation unit of the plan may still carry `overflow_chars` greater than
    zero while its `qa_status` is anything other than `PASSED`, and no defect of
    `bug_class` `TEXT_OVERFLOW` or `TRUNCATION` may remain in `NEW`, `TRIAGED` or
    `FIX_SUBMITTED`; either leftover is `ERR_TEXT_OVERFLOW_UNRESOLVED`."

    The defect clause is cleared and the pass closes again at 0.0000, yet the unit
    still carries 15 overflow characters at a `qa_status` other than `PASSED`, so
    the same code is reported.

    Design: Corner/errors/text_overflow_gate_needs_both_the_unit_waiver_and_a_closed_overflow_bug
    """
    world = _rated_jp_market_carrying_an_overflowing_unit(api)
    reopened = validate_success(
        api.reopen_qa_pass(world["qa_pass"]["id"], users.LQA_OPENER)
    )
    assert reopened["status"] == "OPEN"
    assert reopened["reopen_count"] == 1
    rejected = fx.triage_bug(api, world["bug"]["id"], "REJECT")
    assert rejected["status"] == "REJECTED"
    reclosed = fx.close_qa_pass(api, world["qa_pass"]["id"])
    assert reclosed["status"] == "CLOSED"
    assert reclosed["weighted_defect_points"] == 0
    A.assert_defect_density(reclosed["defect_density"], 0.0000)
    still_overflowing = fx.read_unit(api, world["unit"]["id"])
    assert still_overflowing["overflow_chars"] == 15
    assert still_overflowing["open_bug_count"] == 0
    assert still_overflowing["qa_status"] == "FUNC_FLAGGED"

    response = api.mark_release_ready(world["plan"]["id"], users.COMPLIANCE)

    validate_error(response, E.ERR_TEXT_OVERFLOW_UNRESOLVED, expected_status=422)
    assert fx.read_plan(api, world["plan"]["id"])["status"] == "LQA"
    assert fx.read_title(api, world["title"]["id"])["ready_market_count"] == 0
    A.assert_unchanged_row(fx.read_qa_pass(api, world["qa_pass"]["id"]), reclosed,
                           "qa_pass")


def test_closing_a_closed_pass_is_the_mirror_image_of_the_reopen_guard(api):
    """`ERR_QA_PASS_NOT_OPEN` is reachable from a second close, not just a filing.

    "Closing a pass moves it `OPEN → CLOSED` and is subject to three conditions.
    The pass must be `OPEN`, else `ERR_QA_PASS_NOT_OPEN`."

    "A reopen may be requested directly by an `LqaTester`, in which case the pass
    must be `CLOSED` (else `ERR_QA_PASS_NOT_CLOSED`) and the owning market plan
    must be in `IN_LOCALIZATION` or `LQA`."

    The closer is not the opener, so the segregation rung is satisfied and the
    pass's own state is what refuses the request.

    Design: Corner/errors/text_overflow_gate_needs_both_the_unit_waiver_and_a_closed_overflow_bug
    """
    world = _rated_jp_market_carrying_an_overflowing_unit(api)
    closed = world["qa_pass"]
    assert closed["status"] == "CLOSED"
    A.assert_instant_equals(closed["closed_at_utc"], C.CLOCK_STARTUP_UTC,
                            "closed_at_utc")

    response = api.close_qa_pass(closed["id"], users.LQA_CLOSER)

    validate_error(response, E.ERR_QA_PASS_NOT_OPEN, expected_status=409)
    after = fx.read_qa_pass(api, closed["id"])
    assert after["status"] == "CLOSED"
    assert after["reopen_count"] == 0
    A.assert_defect_density(after["defect_density"], 0.0400)
    A.assert_unchanged_row(after, closed, "qa_pass")


# ─── Instance: localization_incomplete_fires_for_missing_units_and_for ────
# ─── _missing_voice_lines ───────────────────────────────────────────────

# The high-fuzzy HUD key: 0.60 raw, a 0.45 memory factor and a 1.10 uplift is
# 0.297, which rounds to 0.3 and joins the menu key's 0.1 for a 0.40 estimate.
_FUZZY_HUD_KEY = {
    "key_name": "hud.ammo",
    "source_text": "Ammo",
    "source_char_count": 60,
    "ui_surface": "HUD",
    "display_char_limit": 80,
    "tm_match_pct": 80,
}
_TWO_KEY_EFFORT_UNITS = 0.40
_JP_TEXT_ONLY_COST_CENTS = 1680
_KR_FULL_VOICE_COST_CENTS = 3024
_KR_VOICE_QUOTA = 40


def _twin_markets_one_short_of_completeness(api):
    """A JP text market missing one delivery and a KR voiced market missing its lines."""
    title = fx.create_title(api, title_code="NOVA-80", name="Nova Drift 80",
                            release_mode="STAGGERED")
    keys = {}
    for spec in (f.MENU_KEY_SPEC, _FUZZY_HUD_KEY):
        key = fx.create_string_key(api, title["id"], **spec)
        keys[key["key_name"]] = key
    jp_plan = fx.create_market_plan(api, title["id"], market_code="JP",
                                    scope_tier="TEXT_ONLY",
                                    target_rating="TEEN_12",
                                    budget_cap_cents=5000000)
    kr_plan = fx.create_market_plan(api, title["id"], market_code="KR",
                                    scope_tier="FULL_VOICE",
                                    target_rating="TEEN_12",
                                    budget_cap_cents=9000000,
                                    required_voice_line_count=_KR_VOICE_QUOTA)
    talent = fx.create_talent(api, "Ji-hoon Park", "KO", True, 240)
    contract = fx.signed_contract(api, talent["id"], title["id"],
                                  territory_scope=["KR"],
                                  media_scope="IN_GAME_AND_TRAILER")
    fx.lock_strings(api, title["id"])
    jp_plan = fx.scope_plan(api, jp_plan["id"])
    kr_plan = fx.scope_plan(api, kr_plan["id"])
    jp_plan = fx.start_localization(api, jp_plan["id"])
    kr_plan = fx.start_localization(api, kr_plan["id"])
    jp_units = fx.units_by_key_name(api, jp_plan["id"], keys)
    kr_units = fx.units_by_key_name(api, kr_plan["id"], keys)
    fx.draft_and_deliver_unit(api, jp_units["menu.start"]["id"], "ゲームを始める", 96)
    fx.draft_and_deliver_unit(api, kr_units["menu.start"]["id"], "게임 시작", 96)
    fx.draft_and_deliver_unit(api, kr_units["hud.ammo"]["id"], "잔탄", 80)
    return {"title": title, "keys": keys,
            "jp_plan": fx.read_plan(api, jp_plan["id"]),
            "kr_plan": fx.read_plan(api, kr_plan["id"]),
            "jp_units": jp_units, "kr_units": kr_units,
            "talent": talent, "contract": contract}


def test_a_market_with_one_undelivered_unit_cannot_open_its_qa_phase(api):
    """The unit-count clause of the completeness gate.

    "Delivery must be complete: `delivered_unit_count` must equal
    `required_unit_count`, and `required_unit_count` must be at least 1."

    "A failure of either completeness condition is `ERR_LOCALIZATION_INCOMPLETE`."

    Both plans scope to 0.40 effort units, which is 1,680 cents of text work for
    the text-only market and 3,024 for the voiced one at its 1.80 multiplier.

    Design: Corner/errors/localization_incomplete_fires_for_missing_units_and_for_missing_voice_lines
    """
    world = _twin_markets_one_short_of_completeness(api)
    jp_plan = world["jp_plan"]
    A.assert_effort_units(jp_plan["text_effort_units"], _TWO_KEY_EFFORT_UNITS)
    A.assert_money_cents(jp_plan["localization_cost_cents"],
                         _JP_TEXT_ONLY_COST_CENTS, "localization_cost_cents")
    A.assert_money_cents(world["kr_plan"]["localization_cost_cents"],
                         _KR_FULL_VOICE_COST_CENTS, "localization_cost_cents")
    assert jp_plan["required_unit_count"] == 2
    assert jp_plan["delivered_unit_count"] == 1

    response = api.enter_lqa(jp_plan["id"], users.PRODUCER)

    validate_error(response, E.ERR_LOCALIZATION_INCOMPLETE, expected_status=422)
    after = fx.read_plan(api, jp_plan["id"])
    assert after["status"] == "IN_LOCALIZATION"
    assert after["delivered_unit_count"] == 1
    assert after["text_effort_variant"] == "SCOPE_ESTIMATE"
    A.assert_unchanged_row(after, jp_plan, "market_plan")
    assert fx.read_title(api, world["title"]["id"])["localization_state"] == \
        "STRINGS_LOCKED"


def test_a_fully_delivered_voiced_market_still_needs_its_recorded_lines(api):
    """The voice-quota clause of the same gate, with every unit already delivered.

    "The voice quota must also be met: `voice_recorded_line_count` must be at
    least `required_voice_line_count` — the check that matters for the voiced
    tiers `FULL_VOICE` and `FULL_CULTURAL`, and one that a text-only or subtitled
    market satisfies trivially because `required_voice_line_count` is left at its
    default of 0."

    "The voice component is the sum, over every recording session of this market
    plan whose `status` is `RECORDED`, of that session's `recorded_line_count`
    multiplied by the `per_line_rate_cents` of the talent contract the session was
    booked against; sessions in `SCHEDULED`, `IN_PROGRESS` or `CANCELLED`
    contribute exactly zero."

    Design: Corner/errors/localization_incomplete_fires_for_missing_units_and_for_missing_voice_lines
    """
    world = _twin_markets_one_short_of_completeness(api)
    kr_plan = world["kr_plan"]
    assert kr_plan["required_unit_count"] == 2
    assert kr_plan["delivered_unit_count"] == 2
    assert kr_plan["required_voice_line_count"] == _KR_VOICE_QUOTA
    assert kr_plan["voice_recorded_line_count"] == 0

    response = api.enter_lqa(kr_plan["id"], users.PRODUCER)

    validate_error(response, E.ERR_LOCALIZATION_INCOMPLETE, expected_status=422)
    after = fx.read_plan(api, kr_plan["id"])
    assert after["status"] == "IN_LOCALIZATION"
    assert after["voice_recorded_line_count"] == 0
    A.assert_money_cents(after["localization_cost_cents"],
                         _KR_FULL_VOICE_COST_CENTS, "localization_cost_cents")
    A.assert_unchanged_row(after, kr_plan, "market_plan")


def test_completing_one_market_does_not_bubble_the_title_up(api):
    """The title waits for every plan, so the JP success leaves it STRINGS_LOCKED.

    "The same request then bubbles the title up: if every market plan of the title
    now sits in `LQA` or `RELEASE_READY` and the title has at least one market
    plan, the title moves `STRINGS_LOCKED → CERT_WINDOW`, its
    `release_gate_state` is recomputed, and its `version` increments by 1."

    "For illustration: a `SIMULTANEOUS` title with two market plans of which one
    is `RELEASE_READY` matches clause 3 and is `AT_RISK`; a `STAGGERED` title with
    the same two plans and 122 days still to run matches no clause before the last
    and is `OPEN`."

    The vendor reused exactly the match percentages extraction predicted, so the
    `DELIVERED_ACTUAL` figure is the same 0.40 the estimate carried.

    Design: Corner/errors/localization_incomplete_fires_for_missing_units_and_for_missing_voice_lines
    """
    world = _twin_markets_one_short_of_completeness(api)
    fx.draft_and_deliver_unit(api, world["jp_units"]["hud.ammo"]["id"], "残弾", 80)

    entered = validate_success(api.enter_lqa(world["jp_plan"]["id"], users.PRODUCER))

    assert entered["status"] == "LQA"
    assert entered["delivered_unit_count"] == 2
    assert entered["text_effort_variant"] == "DELIVERED_ACTUAL"
    A.assert_effort_units(entered["text_effort_units"], _TWO_KEY_EFFORT_UNITS)
    A.assert_money_cents(entered["localization_cost_cents"],
                         _JP_TEXT_ONLY_COST_CENTS, "localization_cost_cents")
    title_after = fx.read_title(api, world["title"]["id"])
    assert title_after["localization_state"] == "STRINGS_LOCKED"
    assert title_after["release_gate_state"] == "OPEN"
    assert title_after["ready_market_count"] == 0
    assert title_after["market_plan_count"] == 2
    assert fx.read_plan(api, world["kr_plan"]["id"])["status"] == "IN_LOCALIZATION"


# ─── Instance: budget_overage_is_the_last_gate_on_the_release_ready_ladder ─

# 0.60 raw at the exact-match factor and the HUD uplift is 0.066, which rounds
# to 0.1 effort units and 420 cents of text work against a 400-cent cap.
_UNDERBUDGETED_HUD_KEY = {
    "key_name": "hud.ammo",
    "source_text": "Ammo",
    "source_char_count": 60,
    "ui_surface": "HUD",
    "display_char_limit": 80,
    "tm_match_pct": 96,
}
_TIGHT_BUDGET_CAP_CENTS = 400
_TIGHT_OVERAGE_CENTS = 20


def test_the_budget_overage_is_the_only_gate_left_on_a_clean_market(api):
    """Every earlier rung is satisfied, so the fiscal rung reports itself.

    "Finally the fiscal gate: the plan's `overage_cents` must be exactly 0, else
    `ERR_BUDGET_OVERAGE`."

    "`localization_cost_cents` is the lesser of that subtotal and
    `budget_cap_cents`, and `overage_cents` is the subtotal minus
    `budget_cap_cents` when that difference is positive and zero otherwise."

    Scoping stores the clamp rather than refusing the request, and no endpoint
    raises a budget cap, so this market is caught only at the very bottom of the
    ladder: the passes are closed, JP restricts nothing, delivery is complete and
    the assigned `ALL_AGES` band matches the target.

    Design: Corner/errors/budget_overage_is_the_last_gate_on_the_release_ready_ladder
    """
    world = fx.build_market(api, title_code="NOVA-81", name="Nova Drift 81",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="ALL_AGES",
                            budget_cap_cents=_TIGHT_BUDGET_CAP_CENTS,
                            key_specs=[_UNDERBUDGETED_HUD_KEY],
                            applied_tm={"hud.ammo": 96}, stage=fx.STAGE_LQA)
    plan = fx.read_plan(api, world["plan"]["id"])
    A.assert_effort_units(plan["text_effort_units"], 0.10)
    assert plan["text_effort_variant"] == "DELIVERED_ACTUAL"
    A.assert_money_cents(plan["localization_cost_cents"],
                         _TIGHT_BUDGET_CAP_CENTS, "localization_cost_cents")
    A.assert_money_cents(plan["overage_cents"], _TIGHT_OVERAGE_CENTS,
                         "overage_cents")
    submission = fx.draft_submission(api, plan["id"], ["VIOLENCE_STYLIZED"], 0,
                                     "ALL_AGES")
    rated = fx.rate_submission(api, submission["id"], "ALL_AGES")
    assert rated["status"] == "RATED"
    assert rated["assigned_rating"] == "ALL_AGES"
    qa_pass = fx.open_and_close_linguistic_pass(api, plan["id"], 40)
    assert qa_pass["status"] == "CLOSED"
    A.assert_defect_density(qa_pass["defect_density"], 0.0000)
    unit = fx.read_unit(api, fx.list_units(api, plan["id"])[0]["id"])
    assert unit["overflow_chars"] == 0
    plan = fx.read_plan(api, plan["id"])

    response = api.mark_release_ready(plan["id"], users.COMPLIANCE)

    validate_error(response, E.ERR_BUDGET_OVERAGE, expected_status=422)
    after = fx.read_plan(api, plan["id"])
    assert after["status"] == "LQA"
    A.assert_money_cents(after["overage_cents"], _TIGHT_OVERAGE_CENTS,
                         "overage_cents")
    A.assert_unchanged_row(after, plan, "market_plan")
    title_after = fx.read_title(api, world["title"]["id"])
    assert title_after["localization_state"] == "CERT_WINDOW"
    assert title_after["ready_market_count"] == 0
