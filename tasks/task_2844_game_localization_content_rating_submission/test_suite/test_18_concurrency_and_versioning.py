"""The two optimistic-concurrency guards and the version counter they read.

Both guarded creates are destructive — one withdraws the market's live submission,
the other terminates the talent's signed contract — so each is exercised twice
from the same stale view: refused, then accepted after the view is refreshed.
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


def _jp_market_in_lqa(api, title_code, name):
    """A JP TEXT_ONLY market in `LQA`, which is where submissions may be filed."""
    return fx.build_market(api, title_code=title_code, name=name, market_code="JP",
                           scope_tier="TEXT_ONLY", target_rating="TEEN_12",
                           budget_cap_cents=5000000,
                           key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)


def test_a_second_filing_reusing_the_first_views_plan_version_is_refused(api):
    """The literal that worked once is stale the moment the create bumps the plan.

    "Filing a new rating submission requires the non-optional field
    `expected_market_plan_version`, carrying the client's last observed `version`
    of the target `MarketPlan`."

    "If that value does not equal the market plan's current `version`, the create
    is rejected with `ERR_STALE_MARKET_PLAN_VERSION` (HTTP 412)."

    "A successful create increments the market plan's `version`."

    "The server assigns `submission_round` as one more than the number of
    pre-existing submissions for that `market_plan_id`, so the first filing is
    round 1."

    Both requests are otherwise impeccable — right role, right shape, plan in
    `LQA` — so only the concurrency rung can answer the second one.

    Design: Corner/cross_cutting_complexity_layers/stale_market_plan_version_is_refused_before_the_round_is_superseded
    """
    world = _jp_market_in_lqa(api, "NOVA-86", "Nova Drift 86")
    plan_as_first_seen = fx.read_plan(api, world["plan"]["id"])
    stale_version = plan_as_first_seen["version"]

    first = validate_success(
        api.create_rating_submission(
            f.rating_submission_payload(world["plan"]["id"], stale_version,
                                        ["VIOLENCE_STYLIZED"], 0, "TEEN_12"),
            users.COMPLIANCE,
        ),
        expected_status=201,
    )
    assert first["submission_round"] == 1
    assert first["status"] == "DRAFT"
    A.assert_version_bumped_by(fx.read_plan(api, world["plan"]["id"]),
                               plan_as_first_seen, 1, "market_plan")

    validate_error(
        api.create_rating_submission(
            f.rating_submission_payload(world["plan"]["id"], stale_version,
                                        ["BLOOD"], 1, "TEEN_12"),
            users.COMPLIANCE,
        ),
        E.ERR_STALE_MARKET_PLAN_VERSION, expected_status=412,
    )

    rows, meta = validate_paginated(
        api.list_rating_submissions(users.COMPLIANCE,
                                    {"market_plan_id": world["plan"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["submission_round"] == 1
    assert rows[0]["status"] == "DRAFT"
    survivor = fx.read_submission(api, first["id"])
    A.assert_unchanged_row(survivor, first, "rating_submission")


def test_the_refreshed_plan_version_lets_round_two_supersede_round_one(api):
    """With a current view the destructive create runs and withdraws the old round.

    "Creating a submission also supersedes the market's prior non-terminal
    submission into `WITHDRAWN`."

    "The guard exists because a new submission supersedes the market's prior
    non-terminal submission — driving it to `WITHDRAWN` — and re-bases
    `submission_round`; a filing built on a stale view of the market would
    silently discard an outcome the client never saw."

    "A submission that came back `EDITS_REQUIRED` is never re-filed: the next
    round is a brand-new submission whose creation supersedes the old one into
    `WITHDRAWN`."

    Design: Corner/cross_cutting_complexity_layers/stale_market_plan_version_is_refused_before_the_round_is_superseded
    """
    world = _jp_market_in_lqa(api, "NOVA-86B", "Nova Drift 86 B")
    plan_as_first_seen = fx.read_plan(api, world["plan"]["id"])
    stale_version = plan_as_first_seen["version"]
    first = fx.draft_submission(api, world["plan"]["id"], ["VIOLENCE_STYLIZED"], 0,
                                "TEEN_12",
                                expected_market_plan_version=stale_version)
    validate_error(
        api.create_rating_submission(
            f.rating_submission_payload(world["plan"]["id"], stale_version,
                                        ["BLOOD"], 1, "TEEN_12"),
            users.COMPLIANCE,
        ),
        E.ERR_STALE_MARKET_PLAN_VERSION, expected_status=412,
    )

    refreshed = fx.read_plan(api, world["plan"]["id"])
    assert refreshed["version"] == stale_version + 1

    second = validate_success(
        api.create_rating_submission(
            f.rating_submission_payload(world["plan"]["id"], refreshed["version"],
                                        ["BLOOD"], 1, "TEEN_12"),
            users.COMPLIANCE,
        ),
        expected_status=201,
    )
    assert second["submission_round"] == 2
    assert second["status"] == "DRAFT"

    superseded = fx.read_submission(api, first["id"])
    assert superseded["status"] == "WITHDRAWN"
    A.assert_version_bumped_by(superseded, first, 1, "rating_submission")
    A.assert_version_bumped_by(fx.read_plan(api, world["plan"]["id"]), refreshed, 1,
                               "market_plan")
    rows, meta = validate_paginated(
        api.list_rating_submissions(users.COMPLIANCE,
                                    {"market_plan_id": world["plan"]["id"]})
    )
    assert meta["total_count"] == 2
    assert [row["submission_round"] for row in rows] == [1, 2]


def _title_and_one_talent(api, title_code, name):
    """A title plus a freshly registered JA talent, both at version 1."""
    title = fx.create_title(api, title_code=title_code, name=name)
    talent = fx.create_talent(api, "Miki Sato", "JA", False, 240)
    A.assert_fresh_row(talent, "voice_talent")
    return title, talent


def _contract_payload(talent_id, title_id, expected_version, **overrides):
    fields = {
        "territory_scope": ["JP"],
        "media_scope": "IN_GAME_AND_TRAILER",
        "buyout_fee_cents": 400000,
        "per_line_rate_cents": 200,
    }
    fields.update(overrides)
    return f.talent_contract_payload(talent_id, title_id, expected_version,
                                     **fields)


def test_a_replacement_contract_built_on_the_pre_create_talent_view_is_refused(api):
    """The talent's version moves when the child is created, not when it is signed.

    "Creating a talent contract requires the non-optional field
    `expected_voice_talent_version`, carrying the client's last observed `version`
    of the target `VoiceTalent`."

    "If that value does not equal the talent's current `version`, the create is
    rejected with `ERR_STALE_TALENT_VERSION` (HTTP 412)."

    "A new contract opens in `status` `DRAFT` with `signed_at_utc` null and
    `committed_fee_cents` 0, and it increments the talent's `version`."

    "Signature stamps `signed_at_utc` with the logical clock and opens the
    commitment ledger by setting `committed_fee_cents` to `buyout_fee_cents`,
    incrementing the contract's `version` by 1."

    The signature bumps the contract alone, so the view captured before the first
    create is exactly one behind — and this guard reports a different error id from
    the market-plan guard.

    Design: Corner/cross_cutting_complexity_layers/stale_talent_version_is_refused_before_the_prior_contract_is_terminated
    """
    title, talent = _title_and_one_talent(api, "NOVA-87", "Nova Drift 87")
    stale_version = talent["version"]

    first = validate_success(
        api.create_talent_contract(
            _contract_payload(talent["id"], title["id"], stale_version),
            users.PRODUCER,
        ),
        expected_status=201,
    )
    assert first["status"] == "DRAFT"
    assert first["signed_at_utc"] is None
    A.assert_money_cents(first["committed_fee_cents"], 0, "committed_fee_cents")
    talent_after_create = fx.read_talent(api, talent["id"])
    A.assert_version_bumped_by(talent_after_create, talent, 1, "voice_talent")

    signed = validate_success(api.sign_talent_contract(
        first["id"], users.make_talent_agent_headers(talent["id"])
    ))
    assert signed["status"] == "SIGNED"
    A.assert_instant_equals(signed["signed_at_utc"], C.CLOCK_STARTUP_UTC,
                            "signed_at_utc")
    A.assert_money_cents(signed["committed_fee_cents"], 400000,
                         "committed_fee_cents")
    A.assert_version_bumped_by(signed, first, 1, "talent_contract")
    A.assert_unchanged_row(fx.read_talent(api, talent["id"]), talent_after_create,
                           "voice_talent")

    validate_error(
        api.create_talent_contract(
            _contract_payload(talent["id"], title["id"], stale_version,
                              territory_scope=["JP", "KR"],
                              buyout_fee_cents=500000, per_line_rate_cents=250),
            users.PRODUCER,
        ),
        E.ERR_STALE_TALENT_VERSION, expected_status=412,
    )

    survivor = fx.read_contract(api, first["id"])
    assert survivor["status"] == "SIGNED"
    A.assert_unchanged_row(survivor, signed, "talent_contract")
    A.assert_unchanged_row(fx.read_talent(api, talent["id"]), talent_after_create,
                           "voice_talent")
    _rows, meta = validate_paginated(
        api.list_talent_contracts(users.PRODUCER, {"voice_talent_id": talent["id"]})
    )
    assert meta["total_count"] == 1


def test_the_refreshed_talent_version_lets_the_replacement_terminate_the_old_one(api):
    """A current view is the licence to supersede the signed rights.

    "A contract also terminates without anyone asking: when a new contract is
    created for the same `voice_talent_id` and `title_id` pair, any existing
    `SIGNED` contract for that pair is superseded to `TERMINATED` with its
    `version` incremented."

    "That legitimate supersede is exactly why contract creation carries an
    optimistic-concurrency guard."

    "The guard exists because a new contract for the same talent-and-title
    combination supersedes the prior `SIGNED` contract by terminating it; a create
    built on a stale view of the talent would terminate rights the client never
    observed."

    Design: Corner/cross_cutting_complexity_layers/stale_talent_version_is_refused_before_the_prior_contract_is_terminated
    """
    title, talent = _title_and_one_talent(api, "NOVA-87B", "Nova Drift 87 B")
    stale_version = talent["version"]
    first = validate_success(
        api.create_talent_contract(
            _contract_payload(talent["id"], title["id"], stale_version),
            users.PRODUCER,
        ),
        expected_status=201,
    )
    signed = fx.sign_contract(api, first["id"], talent["id"])
    validate_error(
        api.create_talent_contract(
            _contract_payload(talent["id"], title["id"], stale_version),
            users.PRODUCER,
        ),
        E.ERR_STALE_TALENT_VERSION, expected_status=412,
    )

    refreshed = fx.read_talent(api, talent["id"])
    assert refreshed["version"] == stale_version + 1

    second = validate_success(
        api.create_talent_contract(
            _contract_payload(talent["id"], title["id"], refreshed["version"],
                              territory_scope=["JP", "KR"],
                              buyout_fee_cents=500000, per_line_rate_cents=250),
            users.PRODUCER,
        ),
        expected_status=201,
    )
    assert second["status"] == "DRAFT"
    A.assert_money_cents(second["committed_fee_cents"], 0, "committed_fee_cents")

    superseded = fx.read_contract(api, first["id"])
    assert superseded["status"] == "TERMINATED"
    A.assert_version_bumped_by(superseded, signed, 1, "talent_contract")
    A.assert_version_bumped_by(fx.read_talent(api, talent["id"]), refreshed, 1,
                               "voice_talent")
    rows, meta = validate_paginated(
        api.list_talent_contracts(users.PRODUCER, {"voice_talent_id": talent["id"]})
    )
    assert meta["total_count"] == 2
    assert [row["status"] for row in rows] == ["TERMINATED", "DRAFT"]


def _locked_title_with_an_unscoped_plan(api):
    """A frozen string set and a JP plan still sitting in `DRAFT`.

    The baseline plan version is read after the lock, so every later assertion is
    a delta against a value the server itself reported.
    """
    title = fx.create_title(api, title_code="NOVA-88", name="Nova Drift 88")
    key = fx.create_string_key(api, title["id"], **f.MENU_KEY_SPEC)
    plan = fx.create_market_plan(api, title["id"], market_code="JP",
                                 scope_tier="TEXT_ONLY", target_rating="TEEN_12",
                                 budget_cap_cents=5000000)
    A.assert_fresh_row(plan, "market_plan")
    title = fx.lock_strings(api, title["id"])
    return {"title": title, "key": key, "plan": plan}


def test_a_read_never_moves_a_version_while_each_accepted_transition_moves_it_once(api):
    """Two GETs, two accepted transitions and one refused repeat, counted exactly.

    "`version` starts at 1 when the row is created and increments by exactly 1 on
    every mutation of that row, including mutations caused by a cascade the client
    did not directly request."

    "The plan must be in `SCOPED`, else `ERR_MARKET_PLAN_STATE_INVALID`."

    "Second, `updated_at` is refreshed on every row whose `version` was bumped,
    cascade-driven or not."

    The second hand-off attempt is refused by the plan's own state rung, and the
    refusal must leave the counter exactly where the accepted hand-off left it.

    Design: Corner/cross_cutting_complexity_layers/version_increments_once_per_successful_write_and_never_on_a_read_or_a_refusal
    """
    world = _locked_title_with_an_unscoped_plan(api)
    plan_id = world["plan"]["id"]
    baseline = fx.read_plan(api, plan_id)

    A.assert_unchanged_row(fx.read_plan(api, plan_id), baseline, "market_plan")
    A.assert_unchanged_row(validate_success(api.get_market_plan(plan_id,
                                                               users.VENDOR)),
                           baseline, "market_plan")

    scoped = validate_success(api.scope_market_plan(plan_id, users.PRODUCER))
    assert scoped["status"] == "SCOPED"
    A.assert_version_bumped_by(scoped, baseline, 1, "market_plan")

    started = validate_success(api.start_localization(plan_id, users.PRODUCER))
    assert started["status"] == "IN_LOCALIZATION"
    A.assert_version_bumped_by(started, scoped, 1, "market_plan")

    validate_error(api.start_localization(plan_id, users.PRODUCER),
                   E.ERR_MARKET_PLAN_STATE_INVALID, expected_status=409)

    after_refusal = fx.read_plan(api, plan_id)
    assert after_refusal["status"] == "IN_LOCALIZATION"
    A.assert_unchanged_row(after_refusal, started, "market_plan")


def test_the_text_write_bumps_only_the_unit_while_delivery_bumps_its_parent_too(api):
    """One request, two rows: the counter says which writes reach the parent.

    "The `qa_status` axis is untouched. The unit's `version` increments by 1."

    "Delivery records `applied_tm_match_pct` and recomputes the market plan's
    `delivered_unit_count`, incrementing both the unit's and the market plan's
    `version` by 1."

    "On success the plan's `text_effort_units` is recomputed under the
    `DELIVERED_ACTUAL` variant with `text_effort_variant` set accordingly,
    `localization_cost_cents` and `overage_cents` are recomputed from the new
    effort figure, and the plan's `version` increments by 1."

    "First, a single request routinely bumps the `version` of several rows:
    completing a recording session, for example, increments the session's own
    `version`, the governing talent contract's `version` and the market plan's
    `version`."

    The plan's version after entry to QA is the only value the concurrency guard
    of §2.6 accepts, which is asserted by filing one submission with the value one
    below it and one with the value itself.

    Design: Corner/cross_cutting_complexity_layers/version_increments_once_per_successful_write_and_never_on_a_read_or_a_refusal
    """
    world = fx.build_market(api, title_code="NOVA-88B", name="Nova Drift 88 B",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC],
                            stage=fx.STAGE_IN_LOCALIZATION)
    plan_id = world["plan"]["id"]
    unit = world["units"]["menu.start"]
    A.assert_fresh_row(unit, "translation_unit")
    plan_before_write = fx.read_plan(api, plan_id)

    drafted = validate_success(api.write_translation_unit(
        unit["id"], f.translation_text_payload("ゲームを始める", 7, 96), users.VENDOR
    ))
    assert drafted["translation_status"] == "DRAFTED"
    A.assert_version_bumped_by(drafted, unit, 1, "translation_unit")
    A.assert_unchanged_row(fx.read_plan(api, plan_id), plan_before_write,
                           "market_plan")

    delivered = validate_success(
        api.deliver_translation_unit(unit["id"], users.VENDOR)
    )
    assert delivered["translation_status"] == "DELIVERED"
    A.assert_version_bumped_by(delivered, drafted, 1, "translation_unit")
    plan_after_deliver = fx.read_plan(api, plan_id)
    assert plan_after_deliver["delivered_unit_count"] == 1
    A.assert_version_bumped_by(plan_after_deliver, plan_before_write, 1,
                               "market_plan")

    in_lqa = validate_success(api.enter_lqa(plan_id, users.PRODUCER))
    assert in_lqa["status"] == "LQA"
    assert in_lqa["text_effort_variant"] == "DELIVERED_ACTUAL"
    A.assert_version_bumped_by(in_lqa, plan_after_deliver, 1, "market_plan")

    validate_error(
        api.create_rating_submission(
            f.rating_submission_payload(plan_id, in_lqa["version"] - 1,
                                        ["VIOLENCE_STYLIZED"], 1, "TEEN_12"),
            users.COMPLIANCE,
        ),
        E.ERR_STALE_MARKET_PLAN_VERSION, expected_status=412,
    )
    accepted = validate_success(
        api.create_rating_submission(
            f.rating_submission_payload(plan_id, in_lqa["version"],
                                        ["VIOLENCE_STYLIZED"], 1, "TEEN_12"),
            users.COMPLIANCE,
        ),
        expected_status=201,
    )
    assert accepted["submission_round"] == 1


def test_no_refused_write_consumes_a_version_on_any_row_it_names(api):
    """Rungs 1, 2 and 11 all leave the unit and its parent byte-for-byte identical.

    "If either header is absent, or if `X-User-Role` is not exactly one of the
    seven role names below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    "The unit's owning market plan must be in `IN_LOCALIZATION`; a unit that has
    already reached `DELIVERED` refuses further text writes with
    `ERR_UNIT_NOT_DELIVERED`."

    "This action requires the unit's `translation_status` to be `DELIVERED` — a
    cross-axis guard, reported as `ERR_UNIT_NOT_DELIVERED` when it fails — and it
    may only advance a unit to `PASSED` when the unit's `open_bug_count` is zero
    and its `overflow_chars` is zero."

    "`version` starts at 1 when the row is created and increments by exactly 1 on
    every mutation of that row, including mutations caused by a cascade the client
    did not directly request."

    Design: Corner/cross_cutting_complexity_layers/version_increments_once_per_successful_write_and_never_on_a_read_or_a_refusal
    """
    world = fx.build_market(api, title_code="NOVA-88C", name="Nova Drift 88 C",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC],
                            stage=fx.STAGE_DELIVERED)
    plan_id = world["plan"]["id"]
    unit = fx.read_unit(api, world["units"]["menu.start"]["id"])
    assert unit["translation_status"] == "DELIVERED"
    plan_before = fx.read_plan(api, plan_id)

    validate_error(
        api.write_translation_unit(
            unit["id"], f.translation_text_payload("ゲーム開始", 5, 96), users.VENDOR
        ),
        E.ERR_UNIT_NOT_DELIVERED, expected_status=409,
    )
    validate_error(
        api.qa_mark_translation_unit(unit["id"], f.qa_mark_payload("PASSED"),
                                     users.VENDOR),
        E.ERR_ROLE_NOT_PERMITTED, expected_status=403,
    )
    validate_error(
        api.deliver_translation_unit(unit["id"], users.HEADERS_UNKNOWN_ROLE),
        E.ERR_UNAUTHENTICATED, expected_status=401,
    )
    validate_error(api.enter_lqa(plan_id, users.VENDOR),
                   E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    A.assert_unchanged_row(fx.read_unit(api, unit["id"]), unit, "translation_unit")
    A.assert_unchanged_row(fx.read_plan(api, plan_id), plan_before, "market_plan")
    assert fx.read_unit(api, unit["id"])["qa_status"] == "NOT_CHECKED"
