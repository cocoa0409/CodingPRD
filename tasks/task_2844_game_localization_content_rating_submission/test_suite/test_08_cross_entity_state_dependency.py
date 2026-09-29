"""Gates that live on a sibling, on an ancestor and on a descendant row."""

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


def _voiced_market_with_an_unsigned_second_contract(api):
    """A DE FULL_VOICE market handed to the vendor, plus one DRAFT contract.

    The hand-off itself demands a `SIGNED` contract covering `DE`, so Anke's is
    signed; Bruno's is drafted and deliberately left unexecuted.
    """
    world = fx.build_market(api, title_code="NOVA-23", name="Nova Drift 23",
                            market_code="DE", scope_tier="FULL_VOICE",
                            target_rating="MATURE_15", budget_cap_cents=9000000,
                            key_specs=[f.MENU_KEY_SPEC], booth_code="BER-E",
                            turnaround_buffer_minutes=30,
                            stage=fx.STAGE_IN_LOCALIZATION)
    world["bruno"] = fx.create_talent(api, "Bruno Falk", "DE", False)
    world["draft"] = fx.draft_contract(
        api, world["bruno"]["id"], world["title"]["id"], territory_scope=["DE"],
        media_scope="IN_GAME_AND_TRAILER", buyout_fee_cents=500000,
        per_line_rate_cents=250,
    )
    return world


def _bruno_booking(world):
    return f.voice_session_payload(
        world["plan"]["id"], world["bruno"]["id"], world["booth"]["id"],
        world["draft"]["id"], start_utc="2026-09-10T09:00:00Z",
        end_utc="2026-09-10T12:00:00Z", planned_line_count=120,
    )


def test_a_draft_contract_blocks_the_booking_its_ancestors_already_allow(api):
    """The refusal comes from the contract, not from the plan or the booth.

    "First the cross-entity state preconditions: the contract must be `SIGNED`
    (after the lazy expiry evaluation) and the market plan must be
    `IN_LOCALIZATION`, else `ERR_PREREQUISITE_STATE_NOT_MET`."

    "A new contract opens in `status` `DRAFT` with `signed_at_utc` null and
    `committed_fee_cents` 0, and it increments the talent's `version`."

    The plan is already `IN_LOCALIZATION` and the booth is empty, so the only
    unmet condition is the unexecuted contract, and the gate runs before any
    reservation is written.

    Design: Difficulty/cross_entity_state_dependency/voice_session_create_blocked_while_talent_contract_still_draft
    """
    world = _voiced_market_with_an_unsigned_second_contract(api)
    assert world["plan"]["status"] == "IN_LOCALIZATION"
    assert world["draft"]["status"] == "DRAFT"
    assert world["draft"]["signed_at_utc"] is None
    A.assert_money_cents(world["draft"]["committed_fee_cents"], 0,
                         "committed_fee_cents")

    response = api.create_voice_session(_bruno_booking(world), users.PRODUCER)

    validate_error(response, E.ERR_PREREQUISITE_STATE_NOT_MET, expected_status=409)
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 0
    _rows, meta = validate_paginated(
        api.list_voice_sessions(users.PRODUCER,
                                {"recording_booth_id": world["booth"]["id"]})
    )
    assert meta["total_count"] == 0


def test_signing_opens_the_ledger_and_unblocks_the_identical_booking(api):
    """Executing the sibling row is the whole difference.

    "Signature stamps `signed_at_utc` with the logical clock and opens the
    commitment ledger by setting `committed_fee_cents` to `buyout_fee_cents`,
    incrementing the contract's `version` by 1."

    "A successful booking derives `duration_minutes` as the whole minutes between
    `start_utc` and `end_utc`, derives `occupied_end_utc`, opens the session in
    `status` `SCHEDULED` with `recorded_line_count` null and `line_fee_cents` 0,
    and increases the booth's `reserved_minutes_total` by the session's duration
    plus the booth buffer."

    No session is `RECORDED` yet, so the ledger holds the 500,000-cent buyout
    alone, and the three-hour booking plus the thirty-minute buffer is 210
    reserved minutes.

    Design: Difficulty/cross_entity_state_dependency/voice_session_create_blocked_while_talent_contract_still_draft
    """
    world = _voiced_market_with_an_unsigned_second_contract(api)
    validate_error(api.create_voice_session(_bruno_booking(world), users.PRODUCER),
                   E.ERR_PREREQUISITE_STATE_NOT_MET)

    signed = fx.sign_contract(api, world["draft"]["id"], world["bruno"]["id"])

    assert signed["status"] == "SIGNED"
    A.assert_instant_equals(signed["signed_at_utc"], C.CLOCK_STARTUP_UTC,
                            "signed_at_utc")
    A.assert_money_cents(signed["committed_fee_cents"], 500000,
                         "committed_fee_cents")
    A.assert_version_bumped_by(signed, world["draft"], 1, "talent_contract")

    session = validate_success(
        api.create_voice_session(_bruno_booking(world), users.PRODUCER),
        expected_status=201,
    )
    assert session["status"] == "SCHEDULED"
    assert session["duration_minutes"] == 180
    assert session["recorded_line_count"] is None
    A.assert_money_cents(session["line_fee_cents"], 0, "line_fee_cents")
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 210


def _shipped_title_with_a_freshly_scoped_second_market(api):
    """A `SHIPPED` title carrying one extra market plan driven only to `SCOPED`.

    Scoping is legal because the title is no longer `PLANNING`, so the plan's own
    local state precondition is satisfied while its ancestor's is not.
    """
    world = fx.build_release_ready_market(
        api, title_code="NOVA-24", name="Nova Drift 24", market_code="JP",
        target_rating="MATURE_17", budget_cap_cents=5000000,
        key_specs=[f.MENU_KEY_SPEC],
    )
    second = fx.create_market_plan(api, world["title"]["id"], market_code="DE",
                                   scope_tier="TEXT_ONLY",
                                   target_rating="MATURE_17",
                                   budget_cap_cents=5000000)
    world["second_plan"] = fx.scope_plan(api, second["id"])
    return world


def test_start_localization_refuses_while_the_owning_title_is_not_strings_locked(api):
    """The blocking row is the ancestor, and the fan-out never begins.

    "The owning title's `localization_state` must be `STRINGS_LOCKED`, else
    `ERR_PREREQUISITE_STATE_NOT_MET`."

    "`SHIPPED` is terminal for a title."

    "There is no create endpoint for translation units: this cascade is their
    only writer, and listing with a `market_plan_id`, `string_key_id`,
    `translation_status` or `qa_status` filter is the only way to discover them."

    The second market is `SCOPED`, so its own state precondition passes, yet the
    hand-off is refused and the plan owns no translation units afterwards.

    Design: Difficulty/cross_entity_state_dependency/start_localization_blocked_until_title_strings_locked
    """
    world = _shipped_title_with_a_freshly_scoped_second_market(api)
    assert fx.read_title(api, world["title"]["id"])["localization_state"] == "SHIPPED"
    scoped = world["second_plan"]
    assert scoped["status"] == "SCOPED"

    response = api.start_localization(scoped["id"], users.PRODUCER)

    validate_error(response, E.ERR_PREREQUISITE_STATE_NOT_MET, expected_status=409)
    after = fx.read_plan(api, scoped["id"])
    assert after["status"] == "SCOPED"
    A.assert_unchanged_row(after, scoped, "market_plan")
    _units, meta = validate_paginated(
        api.list_translation_units(users.VENDOR, {"market_plan_id": scoped["id"]})
    )
    assert meta["total_count"] == 0


def test_the_hand_off_materialises_the_units_in_string_key_created_at_order(api):
    """With the ancestor frozen the same call runs the downward cascade.

    "The server creates exactly one **Translation Unit** per string key of the
    title whose `status` is `LOCKED`, each opening with `translation_status`
    `PENDING`, `qa_status` `NOT_CHECKED`, `target_text` null, `target_char_count`
    0, `applied_tm_match_pct` null, `overflow_chars` 0 and `open_bug_count` 0."

    "Every list endpoint returns rows sorted by `created_at` ascending — oldest
    first, newest last."

    The relative position of the two units is deliberately not asserted: the
    cascade writes both rows in one request, and §2.3 names that very cascade as
    the case where "two rows can share an identical `created_at`", in which case
    the tie is broken by "the `key_name` of the string key it points at" — a
    tie-break that disagrees with the string-key creation order whenever the two
    orders differ, as they do here.

    "The plan's `required_unit_count` is set to the number of units created and
    `delivered_unit_count` to zero, and the plan's `version` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/start_localization_blocked_until_title_strings_locked
    """
    world = fx.build_market(api, title_code="NOVA-24", name="Nova Drift 24",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC, f.HUD_KEY_SPEC],
                            stage=fx.STAGE_SCOPED)
    title = fx.read_title(api, world["title"]["id"])
    assert title["localization_state"] == "STRINGS_LOCKED"
    assert title["string_lock"] is True
    scoped = world["plan"]

    handed_over = validate_success(
        api.start_localization(scoped["id"], users.PRODUCER)
    )

    assert handed_over["status"] == "IN_LOCALIZATION"
    assert handed_over["required_unit_count"] == 2
    assert handed_over["delivered_unit_count"] == 0
    A.assert_version_bumped_by(handed_over, scoped, 1, "market_plan")
    units, meta = validate_paginated(
        api.list_translation_units(users.VENDOR, {"market_plan_id": scoped["id"]})
    )
    assert meta["total_count"] == 2
    assert sorted(row["string_key_id"] for row in units) == sorted([
        world["keys"]["menu.start"]["id"], world["keys"]["hud.ammo"]["id"],
    ])
    A.assert_created_at_ascending(units)
    for unit in units:
        assert unit["translation_status"] == "PENDING"
        assert unit["qa_status"] == "NOT_CHECKED"
        assert unit["target_text"] is None
        assert unit["target_char_count"] == 0
        assert unit["applied_tm_match_pct"] is None
        assert unit["overflow_chars"] == 0
        assert unit["open_bug_count"] == 0


# 25 + 15 + 20 is 60 base points, which lands in the MATURE_15 band, one step
# stricter than the JP plan's TEEN_12 target.
_STRICT_DISCLOSURE = ["VIOLENCE_REALISTIC", "BLOOD", "SEXUAL_CONTENT"]
_MILD_DISCLOSURE = ["VIOLENCE_STYLIZED"]


def _jp_market_rated_stricter_than_its_target(api):
    """A JP market in LQA whose governing package came back `MATURE_15`."""
    world = fx.build_market(api, title_code="NOVA-25", name="Nova Drift 25",
                            market_code="JP", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)
    world["qa_pass"] = fx.open_and_close_linguistic_pass(api, world["plan"]["id"], 100)
    first = fx.draft_submission(api, world["plan"]["id"], _STRICT_DISCLOSURE, 3,
                                "TEEN_12")
    world["filed"] = fx.submit_submission(api, first["id"])
    world["reviewed"] = fx.begin_review(api, first["id"])
    world["submission"] = fx.record_outcome(api, first["id"], "RATE", "MATURE_15")
    return world


def test_a_governing_rating_stricter_than_the_target_refuses_release_readiness(api):
    """The gate compares a descendant's value against the parent's own field.

    "The governing submission must be in `RATED` and its `assigned_rating` must be
    no stricter than the plan's `target_rating` in the strictness ordering of
    §2.9; a submission that is not `RATED`, or one whose assigned rating is
    stricter than the target, is `ERR_RATING_BAND_MISMATCH`."

    "Rating bands are ordered by strictness from least to most restrictive:
    `ALL_AGES`, then `TEEN_12`, then `MATURE_15`, then `MATURE_17`, then
    `ADULTS_ONLY_18`."

    "To make it concrete: a `CERO` round-one filing made 122 days before release
    has a pre-discount subtotal of 480,000, no expedite fee, a five per cent tier,
    a discount of 24,000, and a fee of 456,000."

    Design: Difficulty/cross_entity_state_dependency/mark_release_ready_blocked_by_governing_submission_rating_band
    """
    world = _jp_market_rated_stricter_than_its_target(api)
    assert world["filed"]["self_assessed_risk_score"] == 60
    A.assert_money_cents(world["filed"]["fee_cents"], 456000, "fee_cents")
    assert world["reviewed"]["board_adjusted_risk_score"] == 60
    assert world["reviewed"]["projected_rating_band"] == "MATURE_15"
    assert world["submission"]["status"] == "RATED"
    assert world["submission"]["assigned_rating"] == "MATURE_15"
    assert A.is_no_stricter_than("MATURE_15", "TEEN_12") is False

    response = api.mark_release_ready(world["plan"]["id"], users.COMPLIANCE)

    validate_error(response, E.ERR_RATING_BAND_MISMATCH, expected_status=422)
    plan = fx.read_plan(api, world["plan"]["id"])
    assert plan["status"] == "LQA"
    assert plan["target_rating"] == "TEEN_12"
    title = fx.read_title(api, world["title"]["id"])
    assert title["ready_market_count"] == 0
    assert title["localization_state"] == "CERT_WINDOW"


def test_a_lower_scoring_round_two_replaces_the_governing_row_and_ships_the_title(api):
    """Filing a milder round is what unblocks the parent.

    "For any market plan, the **governing submission** is the one with the
    greatest `submission_round`, which is unique by construction."

    "The same request then bubbles the title up: when the title has at least one
    market plan and its `ready_market_count` now equals its `market_plan_count`,
    the title moves `CERT_WINDOW → SHIPPED`, its `release_gate_state` is set to
    `CLEARED`, and its `version` increments by 1."

    A round-two `CERO` filing 122 days out has a pre-discount subtotal of 555,000,
    no expedite fee, a five per cent tier keyed on that subtotal and a discount of
    27,750, so the fee is 527,250; `VIOLENCE_STYLIZED` alone is 12 points and
    lands in `ALL_AGES`.

    Design: Difficulty/cross_entity_state_dependency/mark_release_ready_blocked_by_governing_submission_rating_band
    """
    world = _jp_market_rated_stricter_than_its_target(api)
    second = fx.draft_submission(api, world["plan"]["id"], _MILD_DISCLOSURE, 1,
                                 "TEEN_12")
    assert second["submission_round"] == 2
    filed = fx.submit_submission(api, second["id"])
    assert filed["self_assessed_risk_score"] == 12
    A.assert_money_cents(filed["fee_cents"], 527250, "fee_cents")
    reviewed = fx.begin_review(api, second["id"])
    assert reviewed["projected_rating_band"] == "ALL_AGES"
    rated = fx.record_outcome(api, second["id"], "RATE", "ALL_AGES")
    assert rated["assigned_rating"] == "ALL_AGES"
    assert A.is_no_stricter_than("ALL_AGES", "TEEN_12") is True

    released = validate_success(
        api.mark_release_ready(world["plan"]["id"], users.COMPLIANCE)
    )

    assert released["status"] == "RELEASE_READY"
    title = fx.read_title(api, world["title"]["id"])
    assert title["ready_market_count"] == 1
    assert title["market_plan_count"] == 1
    assert title["localization_state"] == "SHIPPED"
    assert title["release_gate_state"] == "CLEARED"


def test_the_greatest_round_governs_even_when_an_earlier_round_is_rated(api):
    """A round-one rating cannot stand in for an unrated round two.

    "Release readiness is judged against that submission and no other."

    "A new submission opens in `status` `DRAFT` with `assigned_rating`,
    `self_assessed_risk_score`, `board_adjusted_risk_score`,
    `projected_rating_band`, `submitted_by_user_id`, `reviewed_by_user_id` and
    `submitted_at_utc` all null, `fee_cents` 0 and `appeal_count` 0, and the
    create increments the market plan's `version`."

    Design: Difficulty/cross_entity_state_dependency/mark_release_ready_blocked_by_governing_submission_rating_band
    """
    world = _jp_market_rated_stricter_than_its_target(api)
    second = fx.draft_submission(api, world["plan"]["id"], _MILD_DISCLOSURE, 1,
                                 "TEEN_12")
    assert second["submission_round"] == 2
    assert second["status"] == "DRAFT"
    assert second["assigned_rating"] is None

    response = api.mark_release_ready(world["plan"]["id"], users.COMPLIANCE)

    validate_error(response, E.ERR_RATING_BAND_MISMATCH, expected_status=422)
    assert fx.read_plan(api, world["plan"]["id"])["status"] == "LQA"
    assert fx.read_submission(api, second["id"])["status"] == "DRAFT"
    assert fx.read_title(api, world["title"]["id"])["ready_market_count"] == 0
