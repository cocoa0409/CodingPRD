"""Three co-violated pairs and which rung of the ladder wins each."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# KR's questionnaire must declare LOOTBOX_PAID, so this disclosure is incomplete
# for a KR market while still being the non-empty array the shape rule demands.
KR_INCOMPLETE_DISCLOSURE = ["VIOLENCE_STYLIZED"]


def _kr_market_with_a_withdrawn_submission(api):
    world = fx.build_market(api, title_code="NOVA-17", name="Nova Drift 17",
                            market_code="KR", scope_tier="TEXT_ONLY",
                            target_rating="TEEN_12", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC], stage=fx.STAGE_LQA)
    submission = fx.draft_submission(api, world["plan"]["id"],
                                     KR_INCOMPLETE_DISCLOSURE, 0, "TEEN_12")
    world["submission"] = validate_success(
        api.withdraw_rating_submission(submission["id"], users.COMPLIANCE)
    )
    return world


def test_the_submission_state_conflict_outranks_the_disclosure_gap(api):
    """Filing a withdrawn package reports the state, not the questionnaire.

    "The submission must be in `DRAFT`, else `ERR_SUBMISSION_STATE_INVALID`, and
    the owning market plan must be in `LQA`, else
    `ERR_PREREQUISITE_STATE_NOT_MET`."

    "Every descriptor that §2.9 makes mandatory for the market's `market_code`
    must appear in `disclosed_content_codes`; a missing one is
    `ERR_MANDATORY_DISCLOSURE_MISSING`."

    "Mandatory disclosures — descriptors a market's questionnaire must declare —
    are: `DE` requires `GAMBLING_SIM`; `KR` requires `LOOTBOX_PAID`."

    The withdrawn KR package violates both rules at once, and the state rung
    wins.

    Design: Difficulty/priority_pair_validation_conflict/submission_state_conflict_beats_mandatory_disclosure_gap
    """
    world = _kr_market_with_a_withdrawn_submission(api)
    withdrawn = world["submission"]
    assert withdrawn["status"] == "WITHDRAWN"

    response = api.submit_rating_submission(withdrawn["id"], users.COMPLIANCE)

    validate_error(response, E.ERR_SUBMISSION_STATE_INVALID, expected_status=409)
    after = fx.read_submission(api, withdrawn["id"])
    assert after["status"] == "WITHDRAWN"
    assert after["submitted_at_utc"] is None
    assert after["submitted_by_user_id"] is None
    A.assert_unchanged_row(after, withdrawn, "rating_submission")


def test_the_disclosure_gap_is_reachable_once_the_state_is_valid(api):
    """The losing rung reports itself as soon as the state rung is satisfied.

    "Every descriptor that §2.9 makes mandatory for the market's `market_code`
    must appear in `disclosed_content_codes`; a missing one is
    `ERR_MANDATORY_DISCLOSURE_MISSING`."

    "A new submission opens in `status` `DRAFT` with `assigned_rating`,
    `self_assessed_risk_score`, `board_adjusted_risk_score`,
    `projected_rating_band`, `submitted_by_user_id`, `reviewed_by_user_id` and
    `submitted_at_utc` all null, `fee_cents` 0 and `appeal_count` 0, and the
    create increments the market plan's `version`."

    Design: Difficulty/priority_pair_validation_conflict/submission_state_conflict_beats_mandatory_disclosure_gap
    """
    world = _kr_market_with_a_withdrawn_submission(api)
    round_two = fx.draft_submission(api, world["plan"]["id"],
                                    KR_INCOMPLETE_DISCLOSURE, 0, "TEEN_12")
    assert round_two["submission_round"] == 2
    assert round_two["status"] == "DRAFT"

    response = api.submit_rating_submission(round_two["id"], users.COMPLIANCE)

    validate_error(response, E.ERR_MANDATORY_DISCLOSURE_MISSING, expected_status=422)
    after = fx.read_submission(api, round_two["id"])
    assert after["status"] == "DRAFT"
    A.assert_money_cents(after["fee_cents"], 0, "fee_cents")
    assert after["submitted_at_utc"] is None
    assert after["self_assessed_risk_score"] is None


def _voiced_market_with_an_occupied_booth(api):
    world = fx.build_market(api, title_code="NOVA-18", name="Nova Drift 18",
                            market_code="DE", scope_tier="FULL_VOICE",
                            target_rating="MATURE_15", budget_cap_cents=5000000,
                            key_specs=[f.MENU_KEY_SPEC], booth_code="BER-C",
                            stage=fx.STAGE_IN_LOCALIZATION)
    world["session"] = fx.book_session(api, world["plan"]["id"],
                                       world["talent"]["id"], world["booth"]["id"],
                                       world["contract"]["id"],
                                       start_utc="2026-09-10T09:00:00Z",
                                       end_utc="2026-09-10T12:00:00Z",
                                       planned_line_count=120)
    world["bruno"] = fx.add_talent_with_contract(
        api, world, talent_name="Bruno Falk", territory_scope=["US"],
        media_scope="ALL_MEDIA", buyout_fee_cents=400000, per_line_rate_cents=200,
    )
    return world


def test_the_rights_coverage_gap_outranks_the_booth_window_conflict(api):
    """A contract that does not license the market fails before the calendar.

    "Then rights coverage: the contract's `territory_scope` must contain the
    market plan's `market_code`, and the contract's `media_scope` must not be
    `IN_GAME_ONLY` when the market plan's `scope_tier` is `FULL_CULTURAL`; either
    failure is `ERR_CONTRACT_TERRITORY_NOT_COVERED`."

    "Then booth geometry, then talent capacity."

    The US-only contract is booked into a window that also collides with the
    occupied interval of the 09:00-12:00 session, and the rights rung wins.

    Design: Difficulty/priority_pair_validation_conflict/contract_territory_gap_beats_booth_window_conflict
    """
    world = _voiced_market_with_an_occupied_booth(api)

    response = api.create_voice_session(
        f.voice_session_payload(
            world["plan"]["id"], world["bruno"]["talent"]["id"],
            world["booth"]["id"], world["bruno"]["contract"]["id"],
            start_utc="2026-09-10T12:00:00Z", end_utc="2026-09-10T13:00:00Z",
            planned_line_count=40,
        ),
        users.PRODUCER,
    )

    validate_error(response, E.ERR_CONTRACT_TERRITORY_NOT_COVERED,
                   expected_status=422)
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 210


def test_the_booth_window_conflict_is_reachable_once_the_rights_cover(api):
    """With a DE contract the same window reaches the calendar rung.

    "A new booking is rejected with `ERR_BOOTH_WINDOW_CONFLICT` when there
    exists any other session on the same booth whose `status` is `SCHEDULED`,
    `IN_PROGRESS` or `RECORDED` and whose own half-open occupied interval
    intersects the new one."

    "Consider a booth with a thirty-minute buffer holding a session from 09:00 to
    12:00: its occupied interval runs from 09:00 up to but not including 12:30, so
    a second session starting at 12:30 is accepted and one starting at 12:29 is
    not."

    Design: Difficulty/priority_pair_validation_conflict/contract_territory_gap_beats_booth_window_conflict
    """
    world = _voiced_market_with_an_occupied_booth(api)

    response = api.create_voice_session(
        f.voice_session_payload(
            world["plan"]["id"], world["talent"]["id"], world["booth"]["id"],
            world["contract"]["id"], start_utc="2026-09-10T12:00:00Z",
            end_utc="2026-09-10T13:00:00Z", planned_line_count=40,
        ),
        users.PRODUCER,
    )

    validate_error(response, E.ERR_BOOTH_WINDOW_CONFLICT, expected_status=409)
    assert fx.read_booth(api, world["booth"]["id"])["reserved_minutes_total"] == 210
    sessions, meta = validate_paginated(
        api.list_voice_sessions(users.PRODUCER,
                                {"recording_booth_id": world["booth"]["id"]})
    )
    assert meta["total_count"] == 1
    assert sessions[0]["id"] == world["session"]["id"]


# One LEGAL key of 125 source characters is 1.9 effort units, which at the
# FULL_CULTURAL multiplier is a 19,152-cent text component; the cultural
# surcharge floor of 1,500,000 cents takes the subtotal to 1,519,152 against a
# 100,000-cent cap.
_OVERRUNNING_LEGAL_KEY = {
    "key_name": "legal.eula",
    "source_text": "End User Licence Agreement",
    "source_char_count": 125,
    "ui_surface": "LEGAL",
    "display_char_limit": 140,
    "tm_match_pct": 40,
}
_OVERSPENT_COST_CENTS = 100000
_OVERSPENT_OVERAGE_CENTS = 1419152


def _twin_markets_over_budget(api):
    """AU and US twins of one over-budget title, both awaiting release sign-off."""
    title = fx.create_title(api, title_code="NOVA-19", name="Nova Drift 19",
                            release_mode="STAGGERED")
    keys = {"legal.eula": fx.create_string_key(api, title["id"],
                                               **_OVERRUNNING_LEGAL_KEY)}
    plans = {}
    for market_code in ("AU", "US"):
        plans[market_code] = fx.create_market_plan(
            api, title["id"], market_code=market_code, scope_tier="FULL_CULTURAL",
            target_rating="MATURE_17", budget_cap_cents=_OVERSPENT_COST_CENTS,
        )
    talent = fx.create_talent(api, "Marta Vieira", "EN")
    contract = fx.signed_contract(api, talent["id"], title["id"],
                                  territory_scope=["AU", "US"],
                                  media_scope="ALL_MEDIA")
    fx.lock_strings(api, title["id"])
    submissions = {}
    for market_code in ("AU", "US"):
        plan = plans[market_code]
        fx.scope_plan(api, plan["id"])
        fx.start_localization(api, plan["id"])
        fx.deliver_all_units(api, plan["id"], keys)
        plans[market_code] = fx.enter_lqa(api, plan["id"])
        submission = fx.draft_submission(
            api, plan["id"], ["DRUG_REFERENCE", "VIOLENCE_STYLIZED"], 2,
            "MATURE_17",
        )
        submissions[market_code] = fx.rate_submission(api, submission["id"],
                                                      "TEEN_12")
        fx.open_and_close_linguistic_pass(api, plan["id"])
    return {"title": title, "keys": keys, "plans": plans,
            "submissions": submissions, "talent": talent, "contract": contract}


def test_the_content_restriction_outranks_the_budget_overage(api):
    """A restricted descriptor is reported ahead of the fiscal gate.

    "Then, in order: every descriptor that §2.9 makes restricted for the plan's
    `market_code` must have left the governing submission's effective disclosure
    set — and a restricted descriptor leaves that set only by being named in the
    `removed_content_codes` of an `APPLIED` content edit of that submission —
    else `ERR_CONTENT_RESTRICTION_UNRESOLVED`."

    "Restricted descriptors — descriptors that may not remain in a market's
    effective disclosure set at release — are: `DE` restricts `BLOOD`; `AU`
    restricts `DRUG_REFERENCE`; `KR` restricts `GAMBLING_SIM`."

    The AU market both discloses `DRUG_REFERENCE` and runs 1,419,152 cents over
    its cap, and the compliance rung wins.

    Design: Difficulty/priority_pair_validation_conflict/content_restriction_beats_budget_overage_on_release_ready
    """
    world = _twin_markets_over_budget(api)
    au_plan = fx.read_plan(api, world["plans"]["AU"]["id"])
    A.assert_money_cents(au_plan["localization_cost_cents"], _OVERSPENT_COST_CENTS,
                         "localization_cost_cents")
    A.assert_money_cents(au_plan["overage_cents"], _OVERSPENT_OVERAGE_CENTS,
                         "overage_cents")

    response = api.mark_release_ready(au_plan["id"], users.COMPLIANCE)

    validate_error(response, E.ERR_CONTENT_RESTRICTION_UNRESOLVED,
                   expected_status=422)
    assert fx.read_plan(api, au_plan["id"])["status"] == "LQA"
    assert fx.read_title(api, world["title"]["id"])["localization_state"] == \
        "CERT_WINDOW"


def test_the_budget_gate_is_reachable_where_nothing_is_restricted(api):
    """The US twin restricts nothing, so the same package reaches the fiscal rung.

    "Finally the fiscal gate: the plan's `overage_cents` must be exactly 0, else
    `ERR_BUDGET_OVERAGE`."

    "The markets `JP`, `BR` and `US` restrict nothing."

    Design: Difficulty/priority_pair_validation_conflict/content_restriction_beats_budget_overage_on_release_ready
    """
    world = _twin_markets_over_budget(api)
    us_plan = fx.read_plan(api, world["plans"]["US"]["id"])
    A.assert_money_cents(us_plan["localization_cost_cents"], _OVERSPENT_COST_CENTS,
                         "localization_cost_cents")
    A.assert_money_cents(us_plan["overage_cents"], _OVERSPENT_OVERAGE_CENTS,
                         "overage_cents")
    assert world["submissions"]["US"]["assigned_rating"] == "TEEN_12"

    response = api.mark_release_ready(us_plan["id"], users.COMPLIANCE)

    validate_error(response, E.ERR_BUDGET_OVERAGE, expected_status=422)
    assert fx.read_plan(api, us_plan["id"])["status"] == "LQA"
    assert fx.read_title(api, world["title"]["id"])["ready_market_count"] == 0
