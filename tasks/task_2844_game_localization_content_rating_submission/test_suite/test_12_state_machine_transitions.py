"""Declared initial states, refused edges, terminal lockdown and bubble-up.

Five machines open in five different states and none of them may be nudged
forward by the creation call itself; the edges that are absent from a state are
refused at the own-state rung of the ladder before any later rule is read; the
two terminal market-plan statuses accept nothing further; and the title's
compound state is derived from the whole sibling population rather than from the
child that happened to move.
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


def test_every_creation_endpoint_opens_its_row_in_the_declared_initial_state(api):
    """Four machines, four different initial states, and no creation skips ahead.

    "A newly registered title opens in `localization_state` `PLANNING` with
    `string_lock` false, `release_gate_state` `OPEN`, and `extracted_key_count`,
    `market_plan_count` and `ready_market_count` all initialised to zero."

    "Every new key starts in `status` `EXTRACTED` and increments the title's
    `extracted_key_count`."

    "A new market plan opens in `status` `DRAFT` with `blocked_reason` null,
    `text_effort_units` 0, `text_effort_variant` null, `localization_cost_cents`
    0 and `overage_cents` 0, and it increments the title's `market_plan_count`."

    "A new contract opens in `status` `DRAFT` with `signed_at_utc` null and
    `committed_fee_cents` 0, and it increments the talent's `version`."

    "Freezing the string set is the title's first real transition, `PLANNING →
    STRINGS_LOCKED`, and only a `LocalizationProducer` may drive it."

    The title holds an `EXTRACTED` key and a market plan yet stays in `PLANNING`,
    the plan carries a `scope_tier` yet stays in `DRAFT`, and the contract names a
    buyout fee yet its ledger is still empty: every one of those values only takes
    effect at the transition that reads it.

    Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
    """
    title = validate_success(
        api.create_title(
            f.title_payload(title_code="NOVA-42", name="Nova Drift 42",
                            source_language="EN",
                            target_release_utc="2026-12-01T00:00:00Z",
                            release_mode="STAGGERED"),
            users.PRODUCER,
        ),
        expected_status=201,
    )
    A.assert_new_title(title)

    talent = validate_success(
        api.create_voice_talent(
            f.voice_talent_payload("Miki Sato", "JA", False), users.PRODUCER
        ),
        expected_status=201,
    )
    A.assert_fresh_row(talent, "voice_talent")

    key = validate_success(
        api.create_string_key(
            f.string_key_payload(title["id"], **f.MENU_KEY_SPEC), users.PRODUCER
        ),
        expected_status=201,
    )
    assert key["status"] == "EXTRACTED"
    A.assert_fresh_row(key, "string_key")

    plan = validate_success(
        api.create_market_plan(
            f.market_plan_payload(title["id"], market_code="JP",
                                  scope_tier="TEXT_ONLY", target_rating="TEEN_12",
                                  budget_cap_cents=5000000,
                                  required_voice_line_count=0),
            users.PRODUCER,
        ),
        expected_status=201,
    )
    A.assert_new_market_plan(plan)
    assert plan["scope_tier"] == "TEXT_ONLY"
    assert plan["cultural_adaptation_required"] is False

    contract = validate_success(
        api.create_talent_contract(
            f.talent_contract_payload(
                talent["id"], title["id"], talent["version"],
                territory_scope=["JP"], media_scope="IN_GAME_ONLY",
                buyout_fee_cents=500000, per_line_rate_cents=250,
                rights_start_utc="2026-08-01T00:00:00Z",
                rights_end_utc="2026-12-31T00:00:00Z",
            ),
            users.PRODUCER,
        ),
        expected_status=201,
    )
    assert contract["status"] == "DRAFT"
    assert contract["signed_at_utc"] is None
    A.assert_money_cents(contract["committed_fee_cents"], 0, "committed_fee_cents")
    A.assert_money_cents(contract["buyout_fee_cents"], 500000, "buyout_fee_cents")
    A.assert_version_bumped_by(fx.read_talent(api, talent["id"]), talent, 1,
                               "voice_talent")

    after = fx.read_title(api, title["id"])
    assert after["localization_state"] == "PLANNING"
    assert after["string_lock"] is False
    assert after["release_gate_state"] == "OPEN"
    assert after["extracted_key_count"] == 1
    assert after["market_plan_count"] == 1
    assert after["ready_market_count"] == 0
    assert fx.read_plan(api, plan["id"])["status"] == "DRAFT"


def test_lock_strings_called_twice_is_refused_and_the_cascade_runs_once(api):
    """The freeze is not idempotent and the refusal re-runs nothing.

    "The title must currently be in `PLANNING`; a title in any other
    `localization_state` is rejected with `ERR_TITLE_STRINGS_ALREADY_LOCKED`."

    "On success, the title's `localization_state` becomes `STRINGS_LOCKED`,
    `string_lock` becomes true (which is the derived signal that source-string
    edits are now blocked, and which is true for every `localization_state` other
    than `PLANNING`), every `EXTRACTED` key of the title cascades to `LOCKED`, and
    `required_unit_count` is recomputed for every market plan of the title."

    "The title's `version` increments by 1."

    "Its `version` increments by 1 and its `updated_at` refreshes, exactly as if
    the client had written it directly."

    The key was created at version 1 and the cascade is the single mutation that
    reaches it, so it sits at version 2 and stays there across the refusal.

    Design: Corner/state_machines/lock_strings_called_twice_is_rejected
    """
    title = fx.create_title(api, title_code="NOVA-43", name="Nova Drift 43")
    key = fx.create_string_key(api, title["id"], **f.MENU_KEY_SPEC)
    before = fx.read_title(api, title["id"])

    locked = validate_success(api.lock_strings(title["id"], users.PRODUCER),
                              expected_status=200)

    assert locked["localization_state"] == "STRINGS_LOCKED"
    assert locked["string_lock"] is True
    A.assert_version_bumped_by(locked, before, 1, "title")
    cascaded = validate_success(api.get_string_key(key["id"], users.PRODUCER))
    assert cascaded["status"] == "LOCKED"
    A.assert_version_bumped_by(cascaded, key, 1, "string_key")

    refused = api.lock_strings(title["id"], users.PRODUCER)

    validate_error(refused, E.ERR_TITLE_STRINGS_ALREADY_LOCKED, expected_status=409)
    after = fx.read_title(api, title["id"])
    assert after["localization_state"] == "STRINGS_LOCKED"
    A.assert_unchanged_row(after, locked, "title")
    still_locked = validate_success(api.get_string_key(key["id"], users.PRODUCER))
    A.assert_unchanged_row(still_locked, cascaded, "string_key")


def test_enter_lqa_and_start_localization_are_refused_from_a_draft_plan(api):
    """`DRAFT` has two outgoing edges and neither of these is one of them.

    "The plan must be in `IN_LOCALIZATION`, else `ERR_MARKET_PLAN_STATE_INVALID`."

    "The plan must be in `SCOPED`, else `ERR_MARKET_PLAN_STATE_INVALID`."

    "When one request violates several rules at once, the server returns the error
    of the highest-precedence rule that is violated and does not evaluate any
    later rule."

    "A failure of either completeness condition is `ERR_LOCALIZATION_INCOMPLETE`."

    "There is no create endpoint for translation units: this cascade is their only
    writer, and listing with a `market_plan_id`, `string_key_id`,
    `translation_status` or `qa_status` filter is the only way to discover them."

    The plan owns no units at all, so the completeness rule at the domain rung
    would have failed too; the own-state rung outranks it, so the reported error
    is the status error and the fan-out never runs.

    Design: Corner/state_machines/enter_lqa_from_a_draft_market_plan_is_rejected
    """
    world = fx.build_market(api, title_code="NOVA-44", name="Nova Drift 44",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC],
                            stage=fx.STAGE_STRINGS_LOCKED)
    assert fx.read_title(api, world["title"]["id"])["localization_state"] == (
        "STRINGS_LOCKED"
    )
    draft = fx.read_plan(api, world["plan"]["id"])
    assert draft["status"] == "DRAFT"

    validate_error(api.enter_lqa(draft["id"], users.PRODUCER),
                   E.ERR_MARKET_PLAN_STATE_INVALID, expected_status=409)
    validate_error(api.start_localization(draft["id"], users.PRODUCER),
                   E.ERR_MARKET_PLAN_STATE_INVALID, expected_status=409)

    after = fx.read_plan(api, draft["id"])
    assert after["status"] == "DRAFT"
    A.assert_effort_units(after["text_effort_units"], 0.00)
    assert after["text_effort_variant"] is None
    A.assert_unchanged_row(after, draft, "market_plan")
    _units, meta = validate_paginated(
        api.list_translation_units(users.VENDOR, {"market_plan_id": draft["id"]})
    )
    assert meta["total_count"] == 0


def _scoped_jp_market(api):
    """A locked title whose single JP plan sits in `SCOPED`."""
    return fx.build_market(api, title_code="NOVA-45", name="Nova Drift 45",
                           market_code="JP", scope_tier="TEXT_ONLY",
                           target_rating="TEEN_12", budget_cap_cents=5000000,
                           key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_SCOPED)


def test_blocking_a_scoped_market_drives_the_title_gate_to_blocked(api):
    """The block records its reason and the first gate clause wins outright.

    "A `ComplianceOfficer` may block a market from `SCOPED`, `IN_LOCALIZATION` or
    `LQA`, supplying a `blocked_reason` of `LEGAL_RESTRICTION`,
    `RATING_TOO_STRICT` or `CERT_DEADLINE_MISSED`."

    "All three permitted source states behave identically: `status` becomes
    `BLOCKED` and `blocked_reason` records the supplied reason (it remains null for
    any plan that is not `BLOCKED`); every recording session of that plan whose
    `status` is `SCHEDULED` is conditionally cancelled, releasing its booth and
    talent minutes, while sessions already `RECORDED` or `CANCELLED` are left
    untouched; the title's `release_gate_state` is set to `BLOCKED`; and the plan's
    `version` increments by 1."

    "If the blocked count is at least 1, the posture is `BLOCKED`."

    The block moves the plan and the title's gate posture only: the title's
    compound `localization_state` still reflects a frozen string set.

    Design: Corner/state_machines/blocked_market_plan_refuses_every_further_transition
    """
    world = _scoped_jp_market(api)
    scoped = world["plan"]
    assert scoped["status"] == "SCOPED"
    assert scoped["blocked_reason"] is None
    assert fx.read_title(api, world["title"]["id"])["release_gate_state"] == "OPEN"

    blocked = validate_success(
        api.block_market_plan(scoped["id"], f.block_payload("LEGAL_RESTRICTION"),
                              users.COMPLIANCE),
        expected_status=200,
    )

    assert blocked["status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "LEGAL_RESTRICTION"
    A.assert_version_bumped_by(blocked, scoped, 1, "market_plan")
    title = fx.read_title(api, world["title"]["id"])
    assert title["release_gate_state"] == "BLOCKED"
    assert title["localization_state"] == "STRINGS_LOCKED"
    assert title["ready_market_count"] == 0


def test_a_blocked_market_plan_refuses_every_further_transition(api):
    """`BLOCKED` is terminal, so the three forward edges and a re-block all fail.

    "A plan in `DRAFT`, `RELEASE_READY` or already `BLOCKED` refuses with
    `ERR_MARKET_PLAN_STATE_INVALID`."

    "`BLOCKED` and `RELEASE_READY` are the two terminal statuses for a market
    plan."

    "The plan must be in `LQA`, else `ERR_MARKET_PLAN_STATE_INVALID`."

    "Every QA pass of the plan must be `CLOSED`, and at least one pass with
    `pass_type` `LINGUISTIC` must exist; the title's `release_gate_state` must not
    be `BLOCKED`."

    "When one request violates several rules at once, the server returns the error
    of the highest-precedence rule that is violated and does not evaluate any
    later rule."

    Release readiness also demands that the title's gate posture is not `BLOCKED`,
    which is a cross-entity precondition one rung lower, so the plan's own status
    is what the server reports; and the refused re-block leaves the first recorded
    reason in place.

    Design: Corner/state_machines/blocked_market_plan_refuses_every_further_transition
    """
    world = _scoped_jp_market(api)
    blocked = validate_success(
        api.block_market_plan(world["plan"]["id"],
                              f.block_payload("LEGAL_RESTRICTION"), users.COMPLIANCE)
    )
    assert blocked["status"] == "BLOCKED"

    validate_error(api.start_localization(blocked["id"], users.PRODUCER),
                   E.ERR_MARKET_PLAN_STATE_INVALID, expected_status=409)
    validate_error(api.enter_lqa(blocked["id"], users.PRODUCER),
                   E.ERR_MARKET_PLAN_STATE_INVALID, expected_status=409)
    validate_error(api.mark_release_ready(blocked["id"], users.COMPLIANCE),
                   E.ERR_MARKET_PLAN_STATE_INVALID, expected_status=409)
    validate_error(
        api.block_market_plan(blocked["id"], f.block_payload("RATING_TOO_STRICT"),
                              users.COMPLIANCE),
        E.ERR_MARKET_PLAN_STATE_INVALID, expected_status=409,
    )

    after = fx.read_plan(api, blocked["id"])
    assert after["status"] == "BLOCKED"
    assert after["blocked_reason"] == "LEGAL_RESTRICTION"
    A.assert_unchanged_row(after, blocked, "market_plan")
    _units, meta = validate_paginated(
        api.list_translation_units(users.VENDOR, {"market_plan_id": blocked["id"]})
    )
    assert meta["total_count"] == 0
    assert fx.read_title(api, world["title"]["id"])["release_gate_state"] == "BLOCKED"


def _voiced_jp_market_with_one_recorded_and_one_scheduled_session(api):
    """A `FULL_VOICE` JP market carrying two sessions on 2026-09-10.

    The first runs 09:00-11:00 and is driven all the way to `RECORDED` with 100
    lines; the second runs 13:00-14:30 and is left `SCHEDULED`. Both sit on booth
    TOK-D with its thirty-minute buffer and on the same talent and contract, so
    only their own status separates them.
    """
    world = fx.build_market(api, title_code="NOVA-46", name="Nova Drift 46",
                            market_code="JP", scope_tier="FULL_VOICE",
                            target_rating="TEEN_12", budget_cap_cents=9000000,
                            required_voice_line_count=100,
                            key_specs=[f.MENU_KEY_SPEC], booth_code="TOK-D",
                            turnaround_buffer_minutes=30, talent_name="Miki Sato",
                            talent_language_code="JA", buyout_fee_cents=500000,
                            per_line_rate_cents=250,
                            media_scope="IN_GAME_AND_TRAILER",
                            stage=fx.STAGE_IN_LOCALIZATION)
    booked = fx.book_session(api, world["plan"]["id"], world["talent"]["id"],
                             world["booth"]["id"], world["contract"]["id"],
                             start_utc="2026-09-10T09:00:00Z",
                             end_utc="2026-09-10T11:00:00Z", planned_line_count=100)
    world["recorded"] = fx.record_session_at_its_start(api, booked,
                                                      world["talent"]["id"], 100)
    world["scheduled"] = fx.book_session(
        api, world["plan"]["id"], world["talent"]["id"], world["booth"]["id"],
        world["contract"]["id"], start_utc="2026-09-10T13:00:00Z",
        end_utc="2026-09-10T14:30:00Z", planned_line_count=40,
    )
    return world


def test_a_market_block_cancels_only_the_scheduled_recording_session(api):
    """The cascade is conditional on the child's own status.

    "All three permitted source states behave identically: `status` becomes
    `BLOCKED` and `blocked_reason` records the supplied reason (it remains null for
    any plan that is not `BLOCKED`); every recording session of that plan whose
    `status` is `SCHEDULED` is conditionally cancelled, releasing its booth and
    talent minutes, while sessions already `RECORDED` or `CANCELLED` are left
    untouched; the title's `release_gate_state` is set to `BLOCKED`; and the plan's
    `version` increments by 1."

    "A booth's `reserved_minutes_total` is the sum, over every session on that
    booth whose `status` is `SCHEDULED`, `IN_PROGRESS` or `RECORDED`, of that
    session's `duration_minutes` plus the booth's `turnaround_buffer_minutes`."

    "A talent's reserved minutes on a given UTC calendar date is the sum of
    `duration_minutes` over every session for that talent whose `status` is
    `SCHEDULED`, `IN_PROGRESS` or `RECORDED` and whose `start_utc` falls on that
    date; `CANCELLED` sessions are excluded."

    "Cancelling a session that was only `SCHEDULED` — whether by direct request or
    as a cascade from a market block or a contract termination — sets `status` to
    `CANCELLED`, recomputes the booth's `reserved_minutes_total` and the talent's
    reserved minutes for the clock date, leaves `committed_fee_cents` unchanged
    because a scheduled session contributed no line fee, and increments the
    session's `version` by 1."

    "A contract's `committed_fee_cents` is its `buyout_fee_cents` plus the sum, over
    every recording session booked against this contract whose `status` is
    `RECORDED`, of that session's `recorded_line_count` multiplied by the
    contract's `per_line_rate_cents`."

    "A market plan's `voice_recorded_line_count` is the sum of
    `recorded_line_count` over its sessions whose `status` is `RECORDED`."

    Before the block the booth holds 120 + 30 for the recorded session and 90 + 30
    for the scheduled one, which is 270 minutes, and the talent holds 120 + 90 =
    210 minutes on 2026-09-10. Cancelling only the scheduled child leaves 150 booth
    minutes and 120 talent minutes, while the ledger stays at the 500,000-cent
    buyout plus 100 lines at 250 cents, which is 525,000.

    Design: Corner/state_machines/market_plan_block_cancels_only_scheduled_voice_sessions
    """
    world = _voiced_jp_market_with_one_recorded_and_one_scheduled_session(api)
    assert world["recorded"]["status"] == "RECORDED"
    assert world["scheduled"]["status"] == "SCHEDULED"
    A.assert_whole_minutes(fx.read_booth(api, world["booth"]["id"])[
        "reserved_minutes_total"], 270, "reserved_minutes_total")
    A.assert_whole_minutes(fx.read_talent(api, world["talent"]["id"])[
        "reserved_minutes_on_clock_date"], 210, "reserved_minutes_on_clock_date")

    blocked = validate_success(
        api.block_market_plan(world["plan"]["id"],
                              f.block_payload("CERT_DEADLINE_MISSED"),
                              users.COMPLIANCE),
        expected_status=200,
    )

    assert blocked["status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "CERT_DEADLINE_MISSED"
    swept = fx.read_session(api, world["scheduled"]["id"])
    assert swept["status"] == "CANCELLED"
    A.assert_version_bumped_by(swept, world["scheduled"], 1, "voice_session")
    spared = fx.read_session(api, world["recorded"]["id"])
    assert spared["status"] == "RECORDED"
    assert spared["recorded_line_count"] == 100
    A.assert_unchanged_row(spared, world["recorded"], "voice_session")
    A.assert_whole_minutes(fx.read_booth(api, world["booth"]["id"])[
        "reserved_minutes_total"], 150, "reserved_minutes_total")
    A.assert_whole_minutes(fx.read_talent(api, world["talent"]["id"])[
        "reserved_minutes_on_clock_date"], 120, "reserved_minutes_on_clock_date")
    A.assert_money_cents(
        fx.read_contract(api, world["contract"]["id"])["committed_fee_cents"],
        525000, "committed_fee_cents",
    )
    assert blocked["voice_recorded_line_count"] == 100
    assert fx.read_title(api, world["title"]["id"])["release_gate_state"] == "BLOCKED"


def _title_with_two_delivered_text_markets(api):
    """One title, one `MENU` key, and JP plus DE both delivered but not yet in QA.

    Both plans hold a single unit delivered at an applied match of 96, so each one
    contributes 125 / 100 x 0.10 x 1.00 = 0.125, which rounds to 0.1 per row and
    to 0.10 in total.
    """
    world = fx.build_market(api, title_code="NOVA-47", name="Nova Drift 47",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_DELIVERED)
    second = fx.create_market_plan(api, world["title"]["id"], market_code="DE",
                                   scope_tier="TEXT_ONLY",
                                   target_rating="MATURE_15",
                                   budget_cap_cents=5000000)
    fx.scope_plan(api, second["id"])
    world["second_plan"] = fx.start_localization(api, second["id"])
    fx.deliver_all_units(api, second["id"], world["keys"])
    return world


def test_the_title_enters_cert_window_only_when_the_second_plan_reaches_lqa(api):
    """The bubble-up is all-or-nothing over the sibling set.

    "The same request then bubbles the title up: if every market plan of the title
    now sits in `LQA` or `RELEASE_READY` and the title has at least one market
    plan, the title moves `STRINGS_LOCKED → CERT_WINDOW`, its `release_gate_state`
    is recomputed, and its `version` increments by 1."

    "On success the plan's `text_effort_units` is recomputed under the
    `DELIVERED_ACTUAL` variant with `text_effort_variant` set accordingly,
    `localization_cost_cents` and `overage_cents` are recomputed from the new
    effort figure, and the plan's `version` increments by 1."

    "The text component is `text_effort_units` multiplied by a text rate of 4,200
    cents per effort unit, multiplied by a scope multiplier of 1.00 for
    `TEXT_ONLY`, 1.25 for `SUBTITLED`, 1.80 for `FULL_VOICE` or 2.40 for
    `FULL_CULTURAL`, with that product rounded half up to whole cents."

    "`ready_market_count` is the number of market plans of the title whose `status`
    is `RELEASE_READY`."

    "Otherwise, if the total count is at least 1, the ready count is less than the
    total count, and the number of days to release is fewer than 30, the posture is
    `AT_RISK`."

    "Otherwise the posture is `OPEN`."

    Each plan settles at 0.10 effort units, so its text component is 0.10 x 4,200 x
    1.00 = 420 cents against a 5,000,000-cent cap and no overage. The title is
    `STAGGERED` with no ready market and 122 days to run, so the gate chain falls
    through to its last clause throughout.

    Design: Corner/state_machines/title_enters_cert_window_only_after_every_plan_reaches_lqa
    """
    world = _title_with_two_delivered_text_markets(api)
    assert fx.read_title(api, world["title"]["id"])["market_plan_count"] == 2

    first = validate_success(api.enter_lqa(world["plan"]["id"], users.PRODUCER),
                             expected_status=200)

    assert first["status"] == "LQA"
    A.assert_effort_units(first["text_effort_units"], 0.10)
    assert first["text_effort_variant"] == "DELIVERED_ACTUAL"
    A.assert_money_cents(first["localization_cost_cents"], 420,
                         "localization_cost_cents")
    A.assert_money_cents(first["overage_cents"], 0, "overage_cents")
    midway = fx.read_title(api, world["title"]["id"])
    assert midway["localization_state"] == "STRINGS_LOCKED"
    assert midway["release_gate_state"] == "OPEN"
    assert fx.read_plan(api, world["second_plan"]["id"])["status"] == (
        "IN_LOCALIZATION"
    )

    second = validate_success(
        api.enter_lqa(world["second_plan"]["id"], users.PRODUCER),
        expected_status=200,
    )

    assert second["status"] == "LQA"
    A.assert_effort_units(second["text_effort_units"], 0.10)
    assert second["text_effort_variant"] == "DELIVERED_ACTUAL"
    A.assert_money_cents(second["localization_cost_cents"], 420,
                         "localization_cost_cents")
    final = fx.read_title(api, world["title"]["id"])
    assert final["localization_state"] == "CERT_WINDOW"
    assert final["release_gate_state"] == "OPEN"
    assert final["ready_market_count"] == 0
    A.assert_version_bumped_by(final, midway, 1, "title")


def test_the_only_market_reaching_release_ready_ships_the_whole_title(api):
    """Every gate passes at once and the whole side-effect chain fires.

    "On success the plan's `status` becomes `RELEASE_READY`, the title's
    `ready_market_count` and `release_gate_state` are recomputed, and the plan's
    `version` increments by 1."

    "The same request then bubbles the title up: when the title has at least one
    market plan and its `ready_market_count` now equals its `market_plan_count`,
    the title moves `CERT_WINDOW → SHIPPED`, its `release_gate_state` is set to
    `CLEARED`, and its `version` increments by 1."

    "To make it concrete: a `CERO` round-one filing made 122 days before release
    has a pre-discount subtotal of 480,000, no expedite fee, a five per cent tier,
    a discount of 24,000, and a fee of 456,000."

    "The `SELF_ASSESSED` variant is the publisher's own questionnaire arithmetic:
    it is the base points alone, clamped to lie between 0 and 100 inclusive, and it
    ignores unresolved legal defects and content edits entirely."

    "The governing submission must be in `RATED` and its `assigned_rating` must be
    no stricter than the plan's `target_rating` in the strictness ordering of §2.9;
    a submission that is not `RATED`, or one whose assigned rating is stricter than
    the target, is `ERR_RATING_BAND_MISMATCH`."

    "On success `status` becomes `CLOSED`, `closed_at_utc` is stamped with the
    logical clock, `weighted_defect_points` and `defect_density` are frozen at the
    values that passed the gate, and the pass's `version` increments by 1."

    "Finally the fiscal gate: the plan's `overage_cents` must be exactly 0, else
    `ERR_BUDGET_OVERAGE`."

    `VIOLENCE_STYLIZED` 12 plus `BLOOD` 15 plus `LANGUAGE_STRONG` 10 is 37 base
    points, which lands in `TEEN_12`; with no unresolved legal defect and no edit
    the board arithmetic reads the same 37. None of the three descriptors is
    footage-mandatory, so a zero footage count is enough, `JP` restricts nothing,
    and the assigned band equals the target, so the band comparison passes on
    equality.

    Design: Corner/state_machines/single_market_title_ships_when_its_only_plan_reaches_release_ready
    """
    world = fx.build_market(api, title_code="NOVA-48", name="Nova Drift 48",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)
    assert fx.read_title(api, world["title"]["id"])["localization_state"] == (
        "CERT_WINDOW"
    )
    qa_pass = fx.open_qa_pass(api, world["plan"]["id"], "LINGUISTIC", 100)
    closed = fx.close_qa_pass(api, qa_pass["id"])
    assert closed["status"] == "CLOSED"
    assert closed["weighted_defect_points"] == 0
    A.assert_defect_density(closed["defect_density"], 0.0000)
    A.assert_instant_equals(closed["closed_at_utc"], C.CLOCK_STARTUP_UTC,
                            "closed_at_utc")

    submission = fx.draft_submission(
        api, world["plan"]["id"],
        ["VIOLENCE_STYLIZED", "BLOOD", "LANGUAGE_STRONG"], 0, "TEEN_12",
    )
    assert submission["submission_round"] == 1
    filed = fx.submit_submission(api, submission["id"])
    assert filed["self_assessed_risk_score"] == 37
    A.assert_money_cents(filed["fee_cents"], 456000, "fee_cents")
    reviewed = fx.begin_review(api, submission["id"])
    assert reviewed["board_adjusted_risk_score"] == 37
    assert reviewed["projected_rating_band"] == "TEEN_12"
    rated = fx.record_outcome(api, submission["id"], "RATE", "TEEN_12")
    assert rated["status"] == "RATED"
    assert rated["assigned_rating"] == "TEEN_12"
    assert A.is_no_stricter_than("TEEN_12", "TEEN_12") is True
    before = fx.read_plan(api, world["plan"]["id"])
    A.assert_money_cents(before["overage_cents"], 0, "overage_cents")
    A.assert_money_cents(before["localization_cost_cents"], 420,
                         "localization_cost_cents")

    released = validate_success(
        api.mark_release_ready(world["plan"]["id"], users.COMPLIANCE),
        expected_status=200,
    )

    assert released["status"] == "RELEASE_READY"
    A.assert_version_bumped_by(released, before, 1, "market_plan")
    title = fx.read_title(api, world["title"]["id"])
    assert title["ready_market_count"] == 1
    assert title["market_plan_count"] == 1
    assert title["localization_state"] == "SHIPPED"
    assert title["release_gate_state"] == "CLEARED"


def test_a_replacement_contract_supersedes_only_the_same_talent_and_title_pair(api):
    """The supersede edge is driven by a sibling creation, keyed on the pair.

    "A contract also terminates without anyone asking: when a new contract is
    created for the same `voice_talent_id` and `title_id` pair, any existing
    `SIGNED` contract for that pair is superseded to `TERMINATED` with its
    `version` incremented."

    "A new contract opens in `status` `DRAFT` with `signed_at_utc` null and
    `committed_fee_cents` 0, and it increments the talent's `version`."

    "The buyout term is present from the moment the contract is `SIGNED` and is
    never reversed."

    "Creating a talent contract requires the non-optional field
    `expected_voice_talent_version`, carrying the client's last observed `version`
    of the target `VoiceTalent`."

    A contract for the second title leaves the incumbent alone; only the second
    contract on the first title terminates it. The talent is created at version 1
    and each of the three creates is one mutation of that row, so it ends at
    version 4, while the terminated incumbent keeps the 500,000-cent buyout it
    committed at signature.

    Design: Corner/state_machines/creating_a_replacement_contract_supersedes_the_previous_signed_one
    """
    talent = fx.create_talent(api, "Miki Sato", "JA", False)
    title_a = fx.create_title(api, title_code="NOVA-49", name="Nova Drift 49")
    title_b = fx.create_title(api, title_code="NOVA-50", name="Nova Drift 50")
    incumbent = fx.draft_contract(api, talent["id"], title_a["id"],
                                  territory_scope=["JP"], media_scope="IN_GAME_ONLY",
                                  buyout_fee_cents=500000, per_line_rate_cents=250)
    signed = fx.sign_contract(api, incumbent["id"], talent["id"])
    assert signed["status"] == "SIGNED"
    A.assert_money_cents(signed["committed_fee_cents"], 500000,
                         "committed_fee_cents")

    other_title = fx.draft_contract(api, talent["id"], title_b["id"],
                                    territory_scope=["JP"], media_scope="ALL_MEDIA",
                                    buyout_fee_cents=600000,
                                    per_line_rate_cents=300)

    assert other_title["status"] == "DRAFT"
    A.assert_money_cents(other_title["committed_fee_cents"], 0,
                         "committed_fee_cents")
    untouched = fx.read_contract(api, incumbent["id"])
    assert untouched["status"] == "SIGNED"
    A.assert_unchanged_row(untouched, signed, "talent_contract")

    replacement = fx.draft_contract(api, talent["id"], title_a["id"],
                                    territory_scope=["JP", "KR"],
                                    media_scope="ALL_MEDIA",
                                    buyout_fee_cents=700000,
                                    per_line_rate_cents=320)

    assert replacement["status"] == "DRAFT"
    assert replacement["signed_at_utc"] is None
    A.assert_money_cents(replacement["committed_fee_cents"], 0,
                         "committed_fee_cents")
    superseded = fx.read_contract(api, incumbent["id"])
    assert superseded["status"] == "TERMINATED"
    A.assert_version_bumped_by(superseded, signed, 1, "talent_contract")
    A.assert_money_cents(superseded["committed_fee_cents"], 500000,
                         "committed_fee_cents")
    assert fx.read_contract(api, other_title["id"])["status"] == "DRAFT"
    A.assert_version_bumped_by(fx.read_talent(api, talent["id"]), talent, 3,
                               "voice_talent")
