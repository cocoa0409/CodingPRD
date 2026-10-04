"""Modeled approval odds, the pre-qualification decision and its eligibility gates."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.factories import create_consent_payload, create_targeting_criterion_payload
from test_helpers.fixtures import (
    LENDER_OPS,
    REFEREE,
    create_active_catalog_item,
    create_active_lender,
    create_active_program,
    create_active_score_tier,
    create_decision,
    create_monitored_consumer,
    qualify_decision,
    reset_clock,
    setup_catalog_scenario,
)


def _probe(api, email, bureau_pin, balance_cents, score=660, dti_pct=35.0,
           limit_cents=1_200_000):
    return create_monitored_consumer(
        score=score, balance_cents=balance_cents, limit_cents=limit_cents,
        email=email, bureau_pin=bureau_pin, dti_pct=dti_pct, api=api,
    )[0]


def _program_with(api, criteria):
    """ACTIVE score tier + catalog item + lender + program carrying `criteria`."""
    reset_clock(api=api)
    create_active_score_tier(api=api)
    item = create_active_catalog_item(api=api)
    lender = create_active_lender(api=api)
    program = create_active_program(lender_id=lender["id"], item_id=item["id"], api=api)
    for criterion in criteria:
        validate_success(
            api.create_targeting_criterion(
                program["id"], create_targeting_criterion_payload(**criterion), LENDER_OPS
            ),
            201,
        )
    return program


def test_odds_utilization_penalty_branch_and_clamp(api):
    """PRD §3.5: "Then, if the pinned snapshot's overall credit utilization exceeds
    30.0 percent (`ODDS_UTILIZATION_FREE_PCT`), the value is increased by 0.05
    (`ODDS_UTILIZATION_PENALTY_PER_10PCT`) for each complete group of 10 percentage
    points by which it exceeds that free allowance."
    PRD §3.5: "Finally the value is capped at a maximum of 0.99 (`ODDS_MAX`) and
    floored at a minimum of 0.01 (`ODDS_MIN`), and the floored result is rounded half
    up to 2 decimal places to become `modeled_odds_pct`."

    Design: Difficulty/combinatorial_formula/odds_weighted_penalty_branch_and_clamp
    """
    program = _program_with(api, [
        {"criterion_field": "SCORE", "operator": "GTE", "criterion_value": "640",
         "is_hard_requirement": True},
        {"criterion_field": "DTI_PCT", "operator": "LTE", "criterion_value": "40",
         "is_hard_requirement": False},
    ])

    at_forty = _probe(api, "maya@example.com", "4821", 480_000)     # util 40.00
    at_thirty = _probe(api, "rae@example.com", "7712", 360_000)     # util 30.00
    far_above = _probe(api, "sam@example.com", "3390", 2_400_000)   # util 200.00

    assert create_decision(at_forty["id"], program["id"], api=api)["modeled_odds_pct"] == 0.85
    assert create_decision(at_thirty["id"], program["id"], api=api)["modeled_odds_pct"] == 0.80
    assert create_decision(far_above["id"], program["id"], api=api)["modeled_odds_pct"] == 0.99


def test_odds_soft_match_fraction_scales_the_penalty(api):
    """PRD §3.5: "When there is at least one soft criterion, the value is further
    reduced by 0.06 (`ODDS_SOFT_MATCH_BONUS`) multiplied by the fraction of soft
    criteria that matched."
    PRD §3.5: "The running value is reduced by 0.04 (`ODDS_HARD_MATCH_BONUS`) for each
    hard criterion that matched."

    Design: Difficulty/combinatorial_formula/odds_weighted_penalty_branch_and_clamp
    """
    program = _program_with(api, [
        {"criterion_field": "SCORE", "operator": "GTE", "criterion_value": "640",
         "is_hard_requirement": True},
        {"criterion_field": "DTI_PCT", "operator": "LTE", "criterion_value": "30",
         "is_hard_requirement": False},
    ])

    soft_misses = _probe(api, "miss@example.com", "3400", 240_000, dti_pct=35.0)
    soft_matches = _probe(api, "match@example.com", "3401", 240_000, dti_pct=25.0)

    # One hard criterion matches; the soft fraction is 0/1 and 1/1 respectively.
    assert create_decision(
        soft_misses["id"], program["id"], api=api
    )["modeled_odds_pct"] == 0.86
    assert create_decision(
        soft_matches["id"], program["id"], api=api
    )["modeled_odds_pct"] == 0.80


def test_odds_utilization_boundary_exactly_at_thirty_percent(api):
    """PRD §3.5: "Then, if the pinned snapshot's overall credit utilization exceeds
    30.0 percent (`ODDS_UTILIZATION_FREE_PCT`), the value is increased by 0.05
    (`ODDS_UTILIZATION_PENALTY_PER_10PCT`) for each complete group of 10 percentage
    points by which it exceeds that free allowance."

    Design: Difficulty/boundary_precision_check/utilization_penalty_boundary_exactly_at_thirty_percent
    """
    program = _program_with(api, [
        {"criterion_field": "SCORE", "operator": "GTE", "criterion_value": "640",
         "is_hard_requirement": True},
    ])

    just_below = _probe(api, "below@example.com", "1029", 359_880)   # util 29.99
    exactly = _probe(api, "exact@example.com", "2201", 360_000)      # util 30.00
    one_group = _probe(api, "group@example.com", "2202", 480_000)    # util 40.00

    below_odds = create_decision(just_below["id"], program["id"], api=api)["modeled_odds_pct"]
    exact_odds = create_decision(exactly["id"], program["id"], api=api)["modeled_odds_pct"]
    group_odds = create_decision(one_group["id"], program["id"], api=api)["modeled_odds_pct"]

    assert just_below["utilization_pct"] == 29.99
    assert exactly["utilization_pct"] == 30.00
    assert one_group["utilization_pct"] == 40.00
    # The free allowance is inclusive: neither 29.99 nor exactly 30.00 is penalized.
    assert below_odds == exact_odds == 0.86
    # One complete group of ten points above the allowance adds the 0.05 penalty.
    assert group_odds == 0.91


def test_odds_penalty_is_added_once_per_matched_hard_criterion(api):
    """PRD §3.5: "The walk counts how many hard criteria matched, how many hard
    criteria failed, how many soft criteria matched, and how many soft criteria there
    were in total."
    PRD §3.5: "The running value is reduced by 0.04 (`ODDS_HARD_MATCH_BONUS`) for each
    hard criterion that matched."

    Design: Difficulty/boundary_precision_check/utilization_penalty_boundary_exactly_at_thirty_percent
    """
    program = _program_with(api, [
        {"criterion_field": "SCORE", "operator": "GTE", "criterion_value": "640",
         "is_hard_requirement": True},
        {"criterion_field": "UTILIZATION_PCT", "operator": "LTE", "criterion_value": "50",
         "is_hard_requirement": True},
    ])

    consumer = _probe(api, "twoc@example.com", "2203", 360_000)  # util exactly 30.00
    decision = create_decision(consumer["id"], program["id"], api=api)

    # 0.90 - 0.04 (SCORE) - 0.04 (UTILIZATION_PCT) = 0.82, with no utilization penalty.
    assert decision["modeled_odds_pct"] == 0.82
    assert decision["decision_status"] == "ELIGIBLE"
    assert decision["reason"] == "NOT_PREQUALIFIED"


def test_ineligible_decision_cannot_be_qualified(api):
    """PRD §3.5: "If any hard criterion failed, the calculation yields nothing and
    `modeled_odds_pct` is null, the decision lands in `INELIGIBLE`, and
    `disqualifying_criteria` is populated with one entry per failed hard criterion".
    PRD §3.5: "An operations `Referee` promotes an eligible decision to `PREQUALIFIED`
    through a qualifying action, which requires the decision to be `ELIGIBLE`".

    Design: Corner/state_machines/qualifying_an_ineligible_decision_is_rejected
    """
    program = _program_with(api, [
        {"criterion_field": "SCORE", "operator": "GTE", "criterion_value": "640",
         "is_hard_requirement": True},
    ])
    consumer = _probe(api, "low@example.com", "7777", 100_000, score=500)
    decision = create_decision(consumer["id"], program["id"], api=api)

    assert decision["decision_status"] == "INELIGIBLE"
    assert decision["modeled_odds_pct"] is None
    assert decision["reason"] == "HARD_CRITERIA_FAILED"
    assert len(decision["disqualifying_criteria"]) == 1
    assert decision["disqualifying_criteria"][0]["criterion_field"] == "SCORE"

    validate_error(
        api.qualify_decision(decision["id"], REFEREE),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409,
    )


def test_qualifying_a_decision_makes_the_consent_route_reachable(api, as_consumer):
    """PRD §3.5: "An operations `Referee` promotes an eligible decision to
    `PREQUALIFIED` through a qualifying action, which requires the decision to be
    `ELIGIBLE`".
    PRD §3.6: "The decision must be `PREQUALIFIED` before consent can be recorded;
    consenting to anything else is rejected with `ERR_CONSENT_DECISION_NOT_PREQUALIFIED`."

    Design: Corner/endpoints/qualifying_a_decision_kicks_off_the_consent_chain
    """
    ctx = setup_catalog_scenario(api=api)
    consumer = _probe(api, "qual@example.com", "2580", 300_000, score=700, dti_pct=25.0)
    decision = create_decision(consumer["id"], ctx["program"]["id"], api=api)
    assert decision["decision_status"] == "ELIGIBLE"

    updated = qualify_decision(decision["id"], api=api)
    assert updated["decision_status"] == "PREQUALIFIED"
    assert updated["modeled_odds_settled"] is False

    version = validate_success(
        api.get_consumer(consumer["id"], as_consumer(consumer["id"])), 200
    )["version"]
    validate_success(
        api.complete_consent(
            consumer["id"], decision["id"], create_consent_payload(version),
            as_consumer(consumer["id"]),
        ),
        201,
    )