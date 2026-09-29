"""Endpoint-level behaviour: amendment, reopen, clock-anchored reads and QA marks."""

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

# A 100-character legal string: at a 96% match its raw contribution is
# 1.00 × 0.10 × 1.50 = 0.15, which rounds half up to 0.2 effort units, and at the
# TEXT_ONLY multiplier that is 0.2 × 4200 × 1.00 = 840 cents.
_LEGAL_KEY_SPEC = {
    "key_name": "legal.eula",
    "source_text": "By continuing you accept the licence.",
    "source_char_count": 100,
    "ui_surface": "LEGAL",
    "display_char_limit": 120,
    "tm_match_pct": 40,
}
_TRANSLATOR_NOTE = "Licence panel copy; keep the legal register formal."
_REVISED_NOTE = "Licence panel copy; the German build needs the formal register."
_EXACT_MATCH_PCT = 96
_LEGAL_EFFORT_UNITS = 0.20
_LEGAL_COST_CENTS = 840


def _legal_key_without_a_context_note(api, title_id):
    """Create the LEGAL key with a null note.

    ``factories.string_key_payload`` always supplies a note for a LEGAL surface,
    so the field is dropped from the payload here to reach the state the lock
    precondition is about.
    """
    payload = f.string_key_payload(title_id, **_LEGAL_KEY_SPEC)
    payload.pop("context_note")
    return validate_success(api.create_string_key(payload, users.PRODUCER),
                            expected_status=201)


def test_amending_the_note_unblocks_the_lock_that_then_freezes_the_key(api):
    """The same PATCH that satisfies the lock is refused once the lock has run.

    "While a key is still `EXTRACTED`, a `LocalizationProducer` may amend it: the
    amendment payload accepts an updated `context_note`, an updated
    `tm_match_pct`, and a boolean `retire` flag."

    "And every `EXTRACTED` key whose `ui_surface` is `LEGAL` must have a non-null
    `context_note` — legal copy is never handed to a translator without context."

    "A failure of either of the latter two conditions is reported as
    `ERR_PREREQUISITE_STATE_NOT_MET`."

    "Amendment is permitted only while the key is `EXTRACTED`; a key that is
    already `LOCKED` or `RETIRED` rejects the change with `ERR_STRING_KEY_LOCKED`."

    "`version` starts at 1 when the row is created and increments by exactly 1 on
    every mutation of that row, including mutations caused by a cascade the client
    did not directly request."

    Design: Corner/endpoints/patch_string_key_edits_context_and_tm_until_the_lock_freezes_it
    """
    title = fx.create_title(api, title_code="NOVA-68", name="Nova Drift 68")
    key = _legal_key_without_a_context_note(api, title["id"])
    assert key["context_note"] is None
    assert key["status"] == "EXTRACTED"
    A.assert_version_is(key, 1, "string_key")

    validate_error(api.lock_strings(title["id"], users.PRODUCER),
                   E.ERR_PREREQUISITE_STATE_NOT_MET, expected_status=409)
    patched = validate_success(
        api.patch_string_key(key["id"],
                             f.patch_string_key_payload(context_note=_TRANSLATOR_NOTE),
                             users.PRODUCER)
    )

    assert patched["context_note"] == _TRANSLATOR_NOTE
    assert patched["status"] == "EXTRACTED"
    A.assert_version_bumped_by(patched, key, 1, "string_key")
    locked_title = validate_success(api.lock_strings(title["id"], users.PRODUCER))
    assert locked_title["localization_state"] == "STRINGS_LOCKED"
    assert locked_title["string_lock"] is True
    assert locked_title["extracted_key_count"] == 1
    frozen = validate_success(api.get_string_key(key["id"], users.PRODUCER))
    assert frozen["status"] == "LOCKED"
    A.assert_version_bumped_by(frozen, patched, 1, "string_key")

    refused = api.patch_string_key(
        key["id"], f.patch_string_key_payload(context_note=_REVISED_NOTE),
        users.PRODUCER,
    )

    validate_error(refused, E.ERR_STRING_KEY_LOCKED, expected_status=409)
    A.assert_unchanged_row(
        validate_success(api.get_string_key(key["id"], users.PRODUCER)), frozen,
        "string_key",
    )


def test_the_amended_match_percentage_is_the_one_scoping_reads(api):
    """Raising `tm_match_pct` before the lock changes the estimate the scope emits.

    "Under the `SCOPE_ESTIMATE` variant — computed at scoping, before any
    translation exists — the input set is every string key of the plan's title
    whose `status` is `EXTRACTED` or `LOCKED`, `RETIRED` keys excluded; the match
    percentage read is the key's own `tm_match_pct`, and `source_char_count` and
    `ui_surface` come from the key."

    "The translation-memory factor is 0.10 when the match percentage is at least
    95 (the exact band), 0.45 when it is at least 75 and less than 95 (the
    high-fuzzy band), 0.75 when it is at least 50 and less than 75 (the low-fuzzy
    band), and 1.00 when it is below 50 (the new-text band)."

    "The surface uplift is 1.50 for `LEGAL`, 1.20 for `SUBTITLE`, 1.10 for `HUD`
    and 1.00 for `MENU`."

    "The text component is `text_effort_units` multiplied by a text rate of 4,200
    cents per effort unit, multiplied by a scope multiplier of 1.00 for
    `TEXT_ONLY`, 1.25 for `SUBTITLED`, 1.80 for `FULL_VOICE` or 2.40 for
    `FULL_CULTURAL`, with that product rounded half up to whole cents."

    Design: Corner/endpoints/patch_string_key_edits_context_and_tm_until_the_lock_freezes_it
    """
    title = fx.create_title(api, title_code="NOVA-69", name="Nova Drift 69")
    key = fx.create_string_key(api, title["id"], **_LEGAL_KEY_SPEC)
    assert key["tm_match_pct"] == 40
    plan = fx.create_market_plan(api, title["id"], market_code="JP",
                                 scope_tier="TEXT_ONLY", target_rating="TEEN_12",
                                 budget_cap_cents=5000000)

    patched = validate_success(
        api.patch_string_key(
            key["id"], f.patch_string_key_payload(tm_match_pct=_EXACT_MATCH_PCT),
            users.PRODUCER,
        )
    )

    assert patched["tm_match_pct"] == _EXACT_MATCH_PCT
    assert patched["context_note"] == f.LEGAL_CONTEXT_NOTE
    fx.lock_strings(api, title["id"])
    scoped = fx.scope_plan(api, plan["id"])
    assert scoped["status"] == "SCOPED"
    assert scoped["text_effort_variant"] == "SCOPE_ESTIMATE"
    A.assert_effort_units(scoped["text_effort_units"], _LEGAL_EFFORT_UNITS)
    A.assert_money_cents(scoped["localization_cost_cents"], _LEGAL_COST_CENTS,
                         "localization_cost_cents")
    A.assert_money_cents(scoped["overage_cents"], 0, "overage_cents")
    assert scoped["required_unit_count"] == 1


def _clean_pass_over_a_market_in_lqa(api):
    """One LINGUISTIC pass with an empty defect ledger, over a plan in `LQA`."""
    world = fx.build_market(api, title_code="NOVA-70", name="Nova Drift 70",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)
    world["qa_pass"] = fx.open_qa_pass(api, world["plan"]["id"], "LINGUISTIC", 40)
    return world


def test_an_open_pass_refuses_a_reopen(api):
    """Reopen is a CLOSED-only transition.

    "A reopen may be requested directly by an `LqaTester`, in which case the pass
    must be `CLOSED` (else `ERR_QA_PASS_NOT_CLOSED`) and the owning market plan
    must be in `IN_LOCALIZATION` or `LQA`."

    "Reopening moves a pass `CLOSED → OPEN` and the cycle is unbounded — a pass
    may go open, closed, open again as many times as the content demands."

    Design: Corner/endpoints/qa_pass_reopen_increments_reopen_count_and_clears_closed_at
    """
    world = _clean_pass_over_a_market_in_lqa(api)
    qa_pass = world["qa_pass"]
    assert qa_pass["status"] == "OPEN"
    assert qa_pass["reopen_count"] == 0

    response = api.reopen_qa_pass(qa_pass["id"], users.LQA_OPENER)

    validate_error(response, E.ERR_QA_PASS_NOT_CLOSED, expected_status=409)
    after = fx.read_qa_pass(api, qa_pass["id"])
    assert after["reopen_count"] == 0
    assert after["closed_at_utc"] is None
    A.assert_unchanged_row(after, qa_pass, "qa_pass")


def test_each_reopen_adds_one_to_the_count_and_clears_the_close_stamp(api):
    """Two close-and-reopen cycles walk `reopen_count` from 0 to 2.

    "On success `status` becomes `CLOSED`, `closed_at_utc` is stamped with the
    logical clock, `weighted_defect_points` and `defect_density` are frozen at the
    values that passed the gate, and the pass's `version` increments by 1."

    "Either way `status` becomes `OPEN`, `reopen_count` increases by 1,
    `closed_at_utc` is cleared to null, and the pass's `version` increments by 1."

    "Reopening moves a pass `CLOSED → OPEN` and the cycle is unbounded — a pass
    may go open, closed, open again as many times as the content demands."

    The pass carries no defects, so the density gate is satisfied on every close
    and `pass_index` never moves: only the reopen ledger changes.

    Design: Corner/endpoints/qa_pass_reopen_increments_reopen_count_and_clears_closed_at
    """
    world = _clean_pass_over_a_market_in_lqa(api)
    qa_pass = world["qa_pass"]

    closed = fx.close_qa_pass(api, qa_pass["id"])
    assert closed["status"] == "CLOSED"
    A.assert_instant_equals(closed["closed_at_utc"], C.CLOCK_STARTUP_UTC,
                            "closed_at_utc")
    assert closed["weighted_defect_points"] == 0
    A.assert_defect_density(closed["defect_density"], 0.0000)
    A.assert_version_bumped_by(closed, qa_pass, 1, "qa_pass")

    reopened = validate_success(api.reopen_qa_pass(closed["id"], users.LQA_OPENER))

    assert reopened["status"] == "OPEN"
    assert reopened["reopen_count"] == 1
    assert reopened["closed_at_utc"] is None
    assert reopened["pass_index"] == qa_pass["pass_index"]
    A.assert_version_bumped_by(reopened, closed, 1, "qa_pass")

    closed_again = fx.close_qa_pass(api, reopened["id"])
    assert closed_again["reopen_count"] == 1
    A.assert_instant_equals(closed_again["closed_at_utc"], C.CLOCK_STARTUP_UTC,
                            "closed_at_utc")
    twice_reopened = validate_success(
        api.reopen_qa_pass(closed["id"], users.LQA_OPENER)
    )

    assert twice_reopened["status"] == "OPEN"
    assert twice_reopened["reopen_count"] == 2
    assert twice_reopened["closed_at_utc"] is None
    A.assert_version_bumped_by(twice_reopened, closed_again, 1, "qa_pass")
    assert fx.read_plan(api, world["plan"]["id"])["status"] == "LQA"


# One two-hour session on 2026-09-10, so the talent's bucket for that UTC date
# holds 120 minutes while every other date holds none, and the booth's total is
# 120 plus its 30-minute buffer.
_SESSION_WINDOW = ("2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")
_SESSION_MINUTES = 120
_BOOTH_MINUTES = 150
_CLOCK_ON_SESSION_DATE = "2026-09-10T08:00:00Z"
_CLOCK_NEXT_DATE = "2026-09-11T00:00:00Z"


def _voiced_market_with_one_september_session(api):
    world = fx.build_market(api, title_code="NOVA-71", name="Nova Drift 71",
                            market_code="JP", scope_tier="FULL_VOICE",
                            target_rating="TEEN_12", budget_cap_cents=9000000,
                            required_voice_line_count=60,
                            key_specs=[f.MENU_KEY_SPEC], booth_code="TOK-H",
                            turnaround_buffer_minutes=C.DEFAULT_TURNAROUND_BUFFER_MINUTES,
                            talent_name="Miki Sato", talent_language_code="JA",
                            max_daily_recording_minutes=240,
                            buyout_fee_cents=400000, per_line_rate_cents=200,
                            territory_scope=["JP"],
                            stage=fx.STAGE_IN_LOCALIZATION)
    world["session"] = fx.book_session(
        api, world["plan"]["id"], world["talent"]["id"], world["booth"]["id"],
        world["contract"]["id"], start_utc=_SESSION_WINDOW[0],
        end_utc=_SESSION_WINDOW[1], planned_line_count=60,
    )
    return world


def test_the_talents_reserved_minutes_follow_the_clocks_utc_date(api):
    """The same session reads as 0, then 120, then 0 as the clock walks past it.

    "Reading a talent exposes `reserved_minutes_on_clock_date`, which is that
    aggregate evaluated for the logical clock's current UTC date."

    "A talent's reserved minutes on a given UTC calendar date is the sum of
    `duration_minutes` over every session for that talent whose `status` is
    `SCHEDULED`, `IN_PROGRESS` or `RECORDED` and whose `start_utc` falls on that
    date; `CANCELLED` sessions are excluded."

    "A booth's `reserved_minutes_total` is the sum, over every session on that
    booth whose `status` is `SCHEDULED`, `IN_PROGRESS` or `RECORDED`, of that
    session's `duration_minutes` plus the booth's `turnaround_buffer_minutes`."

    The booth total is date-blind and stays at 150 throughout, which isolates the
    clock anchoring to the talent read.

    Design: Corner/endpoints/talent_reserved_minutes_read_is_anchored_on_the_logical_clock_date
    """
    world = _voiced_market_with_one_september_session(api)
    booth_id = world["booth"]["id"]
    talent_id = world["talent"]["id"]
    assert world["session"]["duration_minutes"] == _SESSION_MINUTES

    at_startup = validate_success(api.get_voice_talent(talent_id, users.PRODUCER))
    assert at_startup["reserved_minutes_on_clock_date"] == 0
    assert fx.read_booth(api, booth_id)["reserved_minutes_total"] == _BOOTH_MINUTES

    fx.set_clock(api, _CLOCK_ON_SESSION_DATE)
    on_the_date = validate_success(api.get_voice_talent(talent_id, users.PRODUCER))
    assert on_the_date["reserved_minutes_on_clock_date"] == _SESSION_MINUTES
    assert on_the_date["max_daily_recording_minutes"] == 240
    assert fx.read_booth(api, booth_id)["reserved_minutes_total"] == _BOOTH_MINUTES

    fx.set_clock(api, _CLOCK_NEXT_DATE)
    the_day_after = validate_success(api.get_voice_talent(talent_id, users.PRODUCER))
    assert the_day_after["reserved_minutes_on_clock_date"] == 0
    assert fx.read_booth(api, booth_id)["reserved_minutes_total"] == _BOOTH_MINUTES
    A.assert_unchanged_row(the_day_after, at_startup, "voice_talent")


def test_cancelling_the_session_empties_the_bucket_on_its_own_date(api):
    """A cancelled session leaves both aggregates at zero.

    "`CANCELLED` sessions are excluded."

    "`CANCELLED` sessions are excluded from the scan entirely."

    Design: Corner/endpoints/talent_reserved_minutes_read_is_anchored_on_the_logical_clock_date
    """
    world = _voiced_market_with_one_september_session(api)
    fx.set_clock(api, _CLOCK_ON_SESSION_DATE)
    assert fx.read_talent(api, world["talent"]["id"])[
        "reserved_minutes_on_clock_date"] == _SESSION_MINUTES

    cancelled = fx.cancel_session(api, world["session"]["id"])

    assert cancelled["status"] == "CANCELLED"
    assert fx.read_talent(api, world["talent"]["id"])[
        "reserved_minutes_on_clock_date"] == 0
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 0
    _rows, meta = validate_paginated(
        api.list_voice_sessions(users.PRODUCER,
                                {"voice_talent_id": world["talent"]["id"],
                                 "status": "CANCELLED"})
    )
    assert meta["total_count"] == 1


def test_only_a_platform_admin_moves_the_clock_and_the_body_is_the_instant(api):
    """The clock endpoint answers with the instant itself, and only for the admin.

    "A `PlatformAdmin` moves it by supplying a `current_utc` instant; the response
    body for that operation is the inline object `{ current_utc: <datetime> }`
    rather than a domain resource."

    "It is permitted on every endpoint in this specification, and it is the only
    role that may move the server's logical clock."

    A producer's attempt is refused, and the refusal is visible in the talent read
    that would otherwise have reported the September bucket.

    Design: Corner/endpoints/talent_reserved_minutes_read_is_anchored_on_the_logical_clock_date
    """
    world = _voiced_market_with_one_september_session(api)
    talent_id = world["talent"]["id"]

    refused = api.set_clock(_CLOCK_ON_SESSION_DATE, users.PRODUCER)

    validate_error(refused, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    assert fx.read_talent(api, talent_id)["reserved_minutes_on_clock_date"] == 0

    moved = validate_success(api.set_clock(_CLOCK_ON_SESSION_DATE, users.ADMIN))

    assert set(moved.keys()) == {"current_utc"}
    A.assert_instant_equals(moved["current_utc"], _CLOCK_ON_SESSION_DATE,
                            "current_utc")
    assert fx.read_talent(api, talent_id)[
        "reserved_minutes_on_clock_date"] == _SESSION_MINUTES


_MENU_TARGET_TEXT = "ゲーム開始"
_HUD_TARGET_TEXT = "残弾"


def _two_unit_market_with_one_unit_delivered(api):
    """A JP plan in localization: the menu unit DELIVERED, the HUD unit PENDING."""
    world = fx.build_market(api, title_code="NOVA-72", name="Nova Drift 72",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC, f.HUD_KEY_SPEC],
                            stage=fx.STAGE_IN_LOCALIZATION)
    world["menu_unit"] = fx.draft_and_deliver_unit(
        api, world["units"]["menu.start"]["id"], _MENU_TARGET_TEXT, 96
    )
    world["hud_unit"] = world["units"]["hud.ammo"]
    return world


def test_a_unit_that_has_not_been_delivered_refuses_the_qa_mark(api):
    """Neither PENDING nor DRAFTED admits an inspection outcome.

    "This action requires the unit's `translation_status` to be `DELIVERED` — a
    cross-axis guard, reported as `ERR_UNIT_NOT_DELIVERED` when it fails — and it
    may only advance a unit to `PASSED` when the unit's `open_bug_count` is zero
    and its `overflow_chars` is zero."

    "A translation unit carries **two independent state axes** that never move each
    other implicitly."

    The sibling unit of the very same plan is `DELIVERED` and marks `PASSED`
    immediately, so the refusal can only be about the unit's own production axis.

    Design: Corner/endpoints/qa_mark_is_allowed_only_on_a_delivered_unit
    """
    world = _two_unit_market_with_one_unit_delivered(api)
    pending = world["hud_unit"]
    assert pending["translation_status"] == "PENDING"

    while_pending = api.qa_mark_translation_unit(pending["id"],
                                                 f.qa_mark_payload("PASSED"),
                                                 users.LQA_VERIFIER)

    validate_error(while_pending, E.ERR_UNIT_NOT_DELIVERED, expected_status=409)
    A.assert_unchanged_row(fx.read_unit(api, pending["id"]), pending,
                           "translation_unit")

    drafted = fx.write_unit_text(api, pending["id"], _HUD_TARGET_TEXT, 60)
    assert drafted["translation_status"] == "DRAFTED"
    assert drafted["overflow_chars"] == 0
    while_drafted = api.qa_mark_translation_unit(drafted["id"],
                                                 f.qa_mark_payload("PASSED"),
                                                 users.LQA_VERIFIER)

    validate_error(while_drafted, E.ERR_UNIT_NOT_DELIVERED, expected_status=409)
    after = fx.read_unit(api, drafted["id"])
    assert after["qa_status"] == "NOT_CHECKED"
    A.assert_unchanged_row(after, drafted, "translation_unit")
    marked = fx.qa_mark_unit(api, world["menu_unit"]["id"], "PASSED")
    assert marked["qa_status"] == "PASSED"
    assert marked["translation_status"] == "DELIVERED"


def test_delivering_the_unit_opens_the_qa_axis_for_it(api):
    """The refused mark succeeds unchanged once the unit reaches DELIVERED.

    "Delivering a unit moves it `DRAFTED → DELIVERED` and is likewise a
    `TranslationVendor` action; the unit must be in `DRAFTED` (else
    `ERR_UNIT_NOT_DELIVERED`) and its market plan must be in `IN_LOCALIZATION`."

    "A unit may reach `PASSED` from `NOT_CHECKED`, from `LING_FLAGGED` or from
    `FUNC_FLAGGED`, and all three routes carry exactly the same preconditions and
    the same effects: `qa_status` becomes `PASSED` and the unit's `version`
    increments by 1."

    "`delivered_unit_count` is the number of translation units of this plan whose
    `translation_status` is `DELIVERED`."

    Design: Corner/endpoints/qa_mark_is_allowed_only_on_a_delivered_unit
    """
    world = _two_unit_market_with_one_unit_delivered(api)
    hud_id = world["hud_unit"]["id"]
    fx.write_unit_text(api, hud_id, _HUD_TARGET_TEXT, 60)
    validate_error(
        api.qa_mark_translation_unit(hud_id, f.qa_mark_payload("PASSED"),
                                     users.LQA_VERIFIER),
        E.ERR_UNIT_NOT_DELIVERED,
    )

    delivered = fx.deliver_unit(api, hud_id)
    assert delivered["translation_status"] == "DELIVERED"
    marked = validate_success(
        api.qa_mark_translation_unit(hud_id, f.qa_mark_payload("PASSED"),
                                     users.LQA_VERIFIER)
    )

    assert marked["qa_status"] == "PASSED"
    assert marked["translation_status"] == "DELIVERED"
    A.assert_version_bumped_by(marked, delivered, 1, "translation_unit")
    plan = fx.read_plan(api, world["plan"]["id"])
    assert plan["required_unit_count"] == 2
    assert plan["delivered_unit_count"] == 2


# The HUD key renders in 80 characters, and the German HUD line is 95 characters
# long, so the server derives 15 overflow characters for it; the menu line is 130
# characters against a 140-character limit and overflows by nothing.
_AXIS_MENU_KEY = {
    "key_name": "menu.start",
    "source_text": "Start Game",
    "source_char_count": 125,
    "ui_surface": "MENU",
    "display_char_limit": 140,
    "tm_match_pct": 96,
}
_AXIS_HUD_KEY = {
    "key_name": "hud.ammo",
    "source_text": "Ammo",
    "source_char_count": 60,
    "ui_surface": "HUD",
    "display_char_limit": 80,
    "tm_match_pct": 60,
}
_AXIS_MENU_TEXT = ("Spiel starten und die Kampagne fortsetzen " * 4)[:130]
_AXIS_HUD_TEXT = ("Restliche Munition im aktuellen Magazin " * 3)[:95]
_HUD_OVERFLOW_CHARS = 15
_INSPECTED_UNITS = 20
_WEIGHTED_POINTS = 14
_DENSITY = 0.7000


def _two_drafted_units_under_a_functional_pass(api):
    """Both units DRAFTED, and one FUNCTIONAL pass of 20 inspected units open."""
    world = fx.build_market(api, title_code="NOVA-73", name="Nova Drift 73",
                            market_code="DE", scope_tier="TEXT_ONLY",
                            target_rating="MATURE_15", budget_cap_cents=5000000,
                            key_specs=[_AXIS_MENU_KEY, _AXIS_HUD_KEY],
                            stage=fx.STAGE_IN_LOCALIZATION)
    world["menu_unit"] = fx.write_unit_text(api, world["units"]["menu.start"]["id"],
                                            _AXIS_MENU_TEXT, 96)
    world["hud_unit"] = fx.write_unit_text(api, world["units"]["hud.ammo"]["id"],
                                           _AXIS_HUD_TEXT, 60)
    world["qa_pass"] = fx.open_qa_pass(api, world["plan"]["id"], "FUNCTIONAL",
                                       _INSPECTED_UNITS)
    return world


def test_the_derived_axis_of_the_defect_picks_which_unit_flag_moves(api):
    """Two defects on one FUNCTIONAL pass flag their units on opposite axes.

    "Two fields are derived and never supplied: `severity_weight` is the weight of
    the declared `severity`, and `axis` is `LINGUISTIC` when `bug_class` is
    `MISTRANSLATION`, `CULTURAL` or `LEGAL_TEXT`, and `FUNCTIONAL` when it is
    `TEXT_OVERFLOW`, `TRUNCATION` or `FUNCTIONAL_CRASH`."

    "Logging a defect whose derived axis is linguistic drives the unit to
    `LING_FLAGGED`, and it may do so from `NOT_CHECKED`, from `PASSED` or from
    `FUNC_FLAGGED` — linguistic findings dominate the axis."

    "Logging a defect whose derived axis is functional drives the unit to
    `FUNC_FLAGGED`, but only from `NOT_CHECKED` or from `PASSED`; a unit already
    sitting at `LING_FLAGGED` is **not** overwritten by a functional finding."

    "On success the server stores the text and recomputes `target_char_count` as
    the character length of `target_text` — zero when `target_text` is null — and
    recomputes `overflow_chars` as the amount by which `target_char_count` exceeds
    the linked string key's `display_char_limit`, floored at zero."

    "Either flagging recomputes `open_bug_count` and increments the unit's
    `version` by 1."

    The pass is `FUNCTIONAL`, yet the `MISTRANSLATION` filed under it still flags
    its unit linguistically: the axis is read from `bug_class` alone.

    Design: Corner/endpoints/bug_linked_to_a_unit_flips_that_units_qa_axis_by_derived_bug_axis
    """
    world = _two_drafted_units_under_a_functional_pass(api)
    assert world["menu_unit"]["target_char_count"] == 130
    assert world["menu_unit"]["overflow_chars"] == 0
    assert world["hud_unit"]["target_char_count"] == 95
    assert world["hud_unit"]["overflow_chars"] == _HUD_OVERFLOW_CHARS

    linguistic = validate_success(
        api.create_lqa_bug(
            f.lqa_bug_payload(world["qa_pass"]["id"], bug_class="MISTRANSLATION",
                              severity="S2",
                              summary="Formal register lost in the start prompt.",
                              translation_unit_id=world["menu_unit"]["id"]),
            users.LQA_LOGGER,
        ),
        expected_status=201,
    )
    functional = validate_success(
        api.create_lqa_bug(
            f.lqa_bug_payload(world["qa_pass"]["id"], bug_class="TEXT_OVERFLOW",
                              severity="S1",
                              summary="Ammo line runs past the HUD frame.",
                              translation_unit_id=world["hud_unit"]["id"]),
            users.LQA_LOGGER,
        ),
        expected_status=201,
    )

    assert linguistic["axis"] == "LINGUISTIC"
    assert linguistic["severity_weight"] == 4
    assert functional["axis"] == "FUNCTIONAL"
    assert functional["severity_weight"] == 8
    menu_after = fx.read_unit(api, world["menu_unit"]["id"])
    hud_after = fx.read_unit(api, world["hud_unit"]["id"])
    assert menu_after["qa_status"] == "LING_FLAGGED"
    assert hud_after["qa_status"] == "FUNC_FLAGGED"
    assert menu_after["open_bug_count"] == 1
    assert hud_after["open_bug_count"] == 1
    A.assert_version_bumped_by(menu_after, world["menu_unit"], 1,
                               "translation_unit")
    A.assert_version_bumped_by(hud_after, world["hud_unit"], 1, "translation_unit")
    assert menu_after["translation_status"] == "DRAFTED"
    assert hud_after["translation_status"] == "DRAFTED"
    assert hud_after["overflow_chars"] == _HUD_OVERFLOW_CHARS


def test_an_unlinked_crash_weighs_on_the_pass_and_on_no_unit(api):
    """The third defect raises the density while both units keep their flags.

    "The `bug_class` is one of `TEXT_OVERFLOW`, `TRUNCATION`, `MISTRANSLATION`,
    `CULTURAL`, `LEGAL_TEXT` or `FUNCTIONAL_CRASH`, and `translation_unit_id` is
    null when the class is `FUNCTIONAL_CRASH`."

    "A pass's `weighted_defect_points` is the sum of the severity weights of every
    defect filed under that pass whose `status` is `NEW`, `TRIAGED` or
    `FIX_SUBMITTED` — the *open set*."

    "`defect_density` is `weighted_defect_points` divided by the pass's
    `inspected_unit_count`, rounded half up to four decimal places."

    "Severity carries weight: `S1` weighs 8 points, `S2` weighs 4, `S3` weighs 2
    and `S4` weighs 1."

    An `S2`, an `S1` and an `S3` are 4 plus 8 plus 2 weighted points, and over 20
    inspected units that is a density of 0.7000.

    Design: Corner/endpoints/bug_linked_to_a_unit_flips_that_units_qa_axis_by_derived_bug_axis
    """
    world = _two_drafted_units_under_a_functional_pass(api)
    fx.log_bug(api, world["qa_pass"]["id"], bug_class="MISTRANSLATION",
               severity="S2", summary="Formal register lost in the start prompt.",
               translation_unit_id=world["menu_unit"]["id"])
    fx.log_bug(api, world["qa_pass"]["id"], bug_class="TEXT_OVERFLOW",
               severity="S1", summary="Ammo line runs past the HUD frame.",
               translation_unit_id=world["hud_unit"]["id"])
    menu_flagged = fx.read_unit(api, world["menu_unit"]["id"])
    hud_flagged = fx.read_unit(api, world["hud_unit"]["id"])

    crash = validate_success(
        api.create_lqa_bug(
            f.lqa_bug_payload(world["qa_pass"]["id"], bug_class="FUNCTIONAL_CRASH",
                              severity="S3",
                              summary="Hard crash on the German boot screen."),
            users.LQA_LOGGER,
        ),
        expected_status=201,
    )

    assert crash["translation_unit_id"] is None
    assert crash["axis"] == "FUNCTIONAL"
    assert crash["severity_weight"] == 2
    A.assert_unchanged_row(fx.read_unit(api, world["menu_unit"]["id"]), menu_flagged,
                           "translation_unit")
    A.assert_unchanged_row(fx.read_unit(api, world["hud_unit"]["id"]), hud_flagged,
                           "translation_unit")
    assert fx.read_unit(api, world["menu_unit"]["id"])["qa_status"] == "LING_FLAGGED"
    assert fx.read_unit(api, world["hud_unit"]["id"])["qa_status"] == "FUNC_FLAGGED"
    qa_pass = fx.read_qa_pass(api, world["qa_pass"]["id"])
    assert qa_pass["weighted_defect_points"] == _WEIGHTED_POINTS
    A.assert_defect_density(qa_pass["defect_density"], _DENSITY)
    _rows, meta = validate_paginated(
        api.list_lqa_bugs(users.LQA_LOGGER, {"qa_pass_id": world["qa_pass"]["id"]})
    )
    assert meta["total_count"] == 3
