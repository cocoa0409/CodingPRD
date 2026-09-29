"""Two compensating actions, each measured against the ledger it must restore.

Certification withdrawal reverses a certification and has to hand back the
reprint-obligation counters it consumed; penalty rescission reverses an
assessment and has to hand back the two money ledgers it charged. In both
cases the interesting question is not whether the row flips state but whether
the counters land on exactly their pre-cascade values.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_OUTSTANDING_PENALTY, ERR_RECIPE_NOT_APPROVED
from test_helpers.assertions import (
    assert_board_state,
    assert_brand_counters,
    assert_fields_are_none,
    assert_instant_equals,
    assert_item_declaration,
    assert_money_cents,
    expected_display_calorie_text,
    instant_plus_days,
    validate_unpaginated,
)
from test_helpers.constants import (
    ACTION_INFO_REQUESTED,
    ACTION_PENALTY_ASSESSED,
    ACTION_RESPONSE_SUBMITTED,
    ACTION_TYPE_ASSESS_PENALTY,
    ACTION_TYPE_ESCALATE,
    ACTION_TYPE_REQUEST_INFO,
    ACTION_TYPE_RESCIND_PENALTY,
    ALLERGEN_MILK,
    ALLERGEN_WHEAT,
    CITATION_CALORIES_NOT_DECLARED,
    CLOCK_EPOCH_COMPACT,
    COMPLIANCE_CURRENT,
    COMPLIANCE_OVERDUE,
    GRACE_DAYS_NO_EXTRA_REQUIREMENT,
    LABELING_DECLARED,
    LABELING_RELABEL_REQUIRED,
    LISTING_LISTED,
    METHOD_LAB_ANALYSIS,
    PENALTY_BASIS_PER_ESTABLISHMENT,
    POSTURE_COMPLIANT,
    POSTURE_FROZEN,
    PREEMPTION_PREEMPTED,
    PUBLICATION_PUBLISHED,
    RECIPE_APPROVED,
    RECIPE_SUPERSEDED,
    RECIPE_WITHDRAWN,
    RESPONSE_DISPUTED,
    RESPONSE_REPRINT_COMPLETED,
    TIER_ENHANCED,
)
from test_helpers.factories import (
    brioche_bun_component,
    cheddar_slice_component,
    chicken_breast_component,
    enforcement_response_payload,
    garlic_butter_component,
    regulator_action_payload,
    withdraw_certification_payload,
)
from test_helpers.fixtures import (
    BoardBundle,
    Env,
    certify_recipe_version,
    draft_and_publish_packet,
    file_response,
    make_menu_item,
    open_citation,
    published_board,
    regulator_action,
    seed_registry,
    set_clock,
)

# The sandwich of PRD 3.3's worked example, certified twice: 196.00 + 198.00 +
# 136.00 sums to 530.00 raw calories and 548.90 raw sodium, and the spread adds
# 306.00 calories and 265.50 mg for a second declaration of 840 Cal / 810 mg.
SANDWICH_COMPONENTS = [
    chicken_breast_component(),
    brioche_bun_component(),
    cheddar_slice_component(),
]
SANDWICH_WITH_SPREAD_COMPONENTS = SANDWICH_COMPONENTS + [garlic_butter_component()]

RESTORATION_INSTANT = "2026-09-05T00:00:00Z"


# ---------------------------------------------------------------------------
# An overdue board, then the certification behind it is withdrawn
# ---------------------------------------------------------------------------
def _overdue_board_behind_a_second_certification(
    api: ApiClient,
) -> Tuple[Env, Dict[str, Any], Dict[str, Any], Dict[str, Any], BoardBundle]:
    """A live board driven to `OVERDUE` by a 530-to-840 recertification."""
    env = seed_registry(
        api,
        code="OH-STD",
        name="Ohio",
        preemption_mode=PREEMPTION_PREEMPTED,
        unit_label="OH-0001",
        unit_label_prefix="OH-B",
    )
    item = make_menu_item(env)
    first = certify_recipe_version(
        env,
        item["id"],
        SANDWICH_COMPONENTS,
        change_note="Initial specification",
        method=METHOD_LAB_ANALYSIS,
        decision_note="Laboratory panel accepted",
    )["recipe"]
    draft_and_publish_packet(env)
    board = published_board(env, item["id"])
    second = certify_recipe_version(
        env,
        item["id"],
        SANDWICH_WITH_SPREAD_COMPONENTS,
        change_note="Add garlic butter spread",
        method=METHOD_LAB_ANALYSIS,
        decision_note="Spread panel accepted",
    )["recipe"]
    set_clock(api, RESTORATION_INSTANT)
    return env, item, first, second, board


def _withdraw(env: Env, recipe_id: str) -> Dict[str, Any]:
    return validate_unpaginated(
        env.api.withdraw_certification(
            recipe_id,
            withdraw_certification_payload(
                reason="Spread supplier delisted before rollout; revert to the "
                "certified sandwich"
            ),
            env.submitter,
        )
    )


def test_withdrawal_restores_the_superseded_version_and_the_prior_declaration(api):
    """PRD §3.4: "the recipe named by `supersedes_recipe_id` moves from
    `SUPERSEDED` back to `APPROVED`, with its `approved_at` refreshed to the
    logical clock of the restoration." "the item's `declared_calorie_min`,
    `declared_calorie_max`, `declared_sodium_mg`, `allergen_groups`,
    `cross_contact_groups` and `approved_recipe_version_no` are rewritten from
    the restored recipe."

    Design: Difficulty/compensating_invariant/withdraw_certification_restores_the_reprint_obligation_ledger
    """
    env, item, first, second, _board = _overdue_board_behind_a_second_certification(api)

    assert env.read_recipe(first["id"])["status"] == RECIPE_SUPERSEDED
    version_before = env.read_recipe(first["id"])["version"]
    assert env.read_recipe(second["id"])["supersedes_recipe_id"] == first["id"]

    withdrawn = _withdraw(env, second["id"])
    assert withdrawn["status"] == RECIPE_WITHDRAWN

    restored = env.read_recipe(first["id"])
    assert restored["status"] == RECIPE_APPROVED
    assert_instant_equals(
        restored["approved_at"], RESTORATION_INSTANT, "restored recipe approved_at"
    )
    assert restored["version"] > version_before

    assert_item_declaration(
        env.read_item(item["id"]),
        declared_calorie_min=530,
        declared_calorie_max=530,
        declared_sodium_mg=550,
        approved_recipe_version_no=1,
    )
    reread = env.read_item(item["id"])
    assert reread["allergen_groups"] == [ALLERGEN_MILK, ALLERGEN_WHEAT]
    assert reread["cross_contact_groups"] == []


def test_withdrawal_returns_the_stale_line_and_the_overdue_board_to_current(api):
    """PRD §3.4: "every line of the item whose `listing_status` is `STALE`
    returns to `LISTED` with `display_calorie_text`, `declared_min_snapshot` and
    `declared_max_snapshot` rebuilt from the restored declaration, and every
    board whose `stale_listing_count` thereby reaches 0 returns
    `calorie_compliance_status` from `REPRINT_REQUIRED` to `CURRENT`, or from
    `OVERDUE` to `CURRENT`, with `reprint_deadline` cleared to null."

    Design: Difficulty/compensating_invariant/withdraw_certification_restores_the_reprint_obligation_ledger
    """
    env, _item, _first, second, board = _overdue_board_behind_a_second_certification(api)

    overdue = env.read_board(board.board_id)
    assert_board_state(
        overdue,
        publication_status=PUBLICATION_PUBLISHED,
        calorie_compliance_status=COMPLIANCE_OVERDUE,
        stale_listing_count=1,
    )
    assert_instant_equals(
        overdue["reprint_deadline"],
        instant_plus_days(CLOCK_EPOCH_COMPACT, GRACE_DAYS_NO_EXTRA_REQUIREMENT),
        "reprint_deadline",
    )

    _withdraw(env, second["id"])

    line = env.read_listing(board.board_id, board.listing["id"])
    assert line["listing_status"] == LISTING_LISTED
    assert line["declared_min_snapshot"] == 530
    assert line["declared_max_snapshot"] == 530
    assert line["display_calorie_text"] == expected_display_calorie_text(530, 530)

    current = env.read_board(board.board_id)
    assert_board_state(
        current,
        publication_status=PUBLICATION_PUBLISHED,
        calorie_compliance_status=COMPLIANCE_CURRENT,
        stale_listing_count=0,
        reprint_count=0,
    )
    assert_fields_are_none(current, ["reprint_deadline"], "the restored board")
    assert_instant_equals(
        current["effective_from"], CLOCK_EPOCH_COMPACT, "effective_from"
    )


def test_withdrawal_hands_back_both_reprint_counters_exactly(api):
    """PRD §3.4: "`Brand.open_reprint_obligation_count` and
    `Brand.overdue_board_count` are decremented back to exactly their
    pre-certification values, the item's `labeling_status` returns from
    `RELABEL_REQUIRED` to `DECLARED`, and `compliance_posture` is recomputed."
    PRD §3.0: "the reversal restores the affected counters to precisely their
    pre-cascade values, not to a recomputed approximation of them."

    Design: Difficulty/compensating_invariant/withdraw_certification_restores_the_reprint_obligation_ledger
    """
    env, item, _first, second, _board = _overdue_board_behind_a_second_certification(api)

    assert_brand_counters(
        env.read_brand(),
        open_reprint_obligation_count=1,
        overdue_board_count=1,
        compliance_posture=POSTURE_FROZEN,
    )
    assert_item_declaration(
        env.read_item(item["id"]), labeling_status=LABELING_RELABEL_REQUIRED
    )

    _withdraw(env, second["id"])

    assert_brand_counters(
        env.read_brand(),
        open_reprint_obligation_count=0,
        overdue_board_count=0,
        open_enforcement_escalated_count=0,
        compliance_posture=POSTURE_COMPLIANT,
    )
    assert_item_declaration(
        env.read_item(item["id"]), labeling_status=LABELING_DECLARED
    )

    summary = env.read_summary()
    assert summary["open_reprint_obligation_count"] == 0
    assert summary["overdue_board_count"] == 0
    assert summary["compliance_posture"] == POSTURE_COMPLIANT
    assert_money_cents(
        summary["outstanding_penalty_cents_total"],
        0,
        "outstanding_penalty_cents_total",
    )


def test_a_withdrawn_recipe_cannot_be_withdrawn_a_second_time(api):
    """PRD §3.4: "The withdrawn recipe moves from `APPROVED` to `WITHDRAWN`,
    which is terminal". PRD §2.6 rung 14: "The recipe's `status` is `APPROVED`,
    else `ERR_RECIPE_NOT_APPROVED`. Applies to certification withdrawal."

    Design: Difficulty/compensating_invariant/withdraw_certification_restores_the_reprint_obligation_ledger
    """
    env, _item, _first, second, _board = _overdue_board_behind_a_second_certification(api)
    _withdraw(env, second["id"])

    validate_error(
        env.api.withdraw_certification(
            second["id"],
            withdraw_certification_payload(reason="Filed twice by mistake"),
            env.submitter,
        ),
        ERR_RECIPE_NOT_APPROVED,
        409,
    )
    assert env.read_recipe(second["id"])["status"] == RECIPE_WITHDRAWN


# ---------------------------------------------------------------------------
# An escalated citation in an ENHANCED authority, assessed and then rescinded
# ---------------------------------------------------------------------------
def _escalated_file_in_an_enhanced_authority(
    api: ApiClient,
) -> Tuple[Env, Dict[str, Any]]:
    """A citation carried to `ESCALATED`, with both money ledgers still at 0."""
    env = seed_registry(
        api,
        code="NV-ENF",
        name="Nevada",
        preemption_mode=PREEMPTION_PREEMPTED,
        enforcement_tier=TIER_ENHANCED,
        unit_label="NV-0001",
        unit_label_prefix="NV-B",
    )
    item = make_menu_item(env)
    certify_recipe_version(
        env,
        item["id"],
        SANDWICH_COMPONENTS,
        change_note="Initial specification",
        decision_note="Database values verified",
    )
    draft_and_publish_packet(env)

    action = open_citation(env, CITATION_CALORIES_NOT_DECLARED)
    file_response(
        env,
        action["id"],
        RESPONSE_DISPUTED,
        response_note="Declarations were posted on the day of inspection",
    )
    regulator_action(
        env,
        action["id"],
        ACTION_TYPE_REQUEST_INFO,
        action_note="Send dated board photographs",
    )
    file_response(
        env, action["id"], RESPONSE_DISPUTED, response_note="Photographs attached"
    )
    regulator_action(
        env,
        action["id"],
        ACTION_TYPE_ESCALATE,
        action_note="Photographs do not show the required declarations",
    )
    return env, action


def _assess(env: Env, action_id: str) -> Dict[str, Any]:
    return validate_unpaginated(
        env.api.create_regulator_action(
            action_id,
            regulator_action_payload(
                action_type=ACTION_TYPE_ASSESS_PENALTY,
                penalty_basis=PENALTY_BASIS_PER_ESTABLISHMENT,
                action_note="One violation unit, enhanced tier",
            ),
            env.regulator,
        )
    )


def _rescind(env: Env, action_id: str) -> Dict[str, Any]:
    return validate_unpaginated(
        env.api.create_regulator_action(
            action_id,
            regulator_action_payload(
                action_type=ACTION_TYPE_RESCIND_PENALTY,
                action_note="Dated photographs re-examined; penalty withdrawn",
            ),
            env.regulator,
        )
    )


def test_an_assessment_posts_the_whole_total_onto_both_money_ledgers(api):
    """PRD §3.9: "An assessment moves the file to `PENALTY_ASSESSED`, adds
    `penalty_total_cents` to the cited `Establishment.outstanding_penalty_cents`
    and to the citing `Jurisdiction.assessed_penalty_cents_total`, decrements
    `Brand.open_enforcement_escalated_count` by 1, and recomputes
    `compliance_posture`".

    Design: Difficulty/compensating_invariant/rescind_penalty_restores_both_money_ledgers_exactly
    """
    env, action = _escalated_file_in_an_enhanced_authority(api)

    assert_money_cents(
        env.read_establishment()["outstanding_penalty_cents"],
        0,
        "Establishment.outstanding_penalty_cents before assessment",
    )
    assert_money_cents(
        env.read_jurisdiction()["assessed_penalty_cents_total"],
        0,
        "Jurisdiction.assessed_penalty_cents_total before assessment",
    )

    assessed = _assess(env, action["id"])
    assert assessed["status"] == ACTION_PENALTY_ASSESSED
    assert assessed["violation_unit_count"] == 1
    assert_money_cents(assessed["base_penalty_cents"], 75000, "base_penalty_cents")
    assert_money_cents(assessed["admin_fee_cents"], 3750, "admin_fee_cents")
    assert_money_cents(assessed["penalty_total_cents"], 78750, "penalty_total_cents")

    assert_money_cents(
        env.read_establishment()["outstanding_penalty_cents"],
        78750,
        "Establishment.outstanding_penalty_cents",
    )
    assert_money_cents(
        env.read_jurisdiction()["assessed_penalty_cents_total"],
        78750,
        "Jurisdiction.assessed_penalty_cents_total",
    )
    assert_brand_counters(
        env.read_brand(),
        open_enforcement_escalated_count=0,
        compliance_posture=POSTURE_COMPLIANT,
    )


def test_rescission_subtracts_the_total_and_nulls_the_whole_breakdown(api):
    """PRD §3.9: "`RESCIND_PENALTY` is the compensating action" — it subtracts
    the assessed total "from both `Establishment.outstanding_penalty_cents` and
    `Jurisdiction.assessed_penalty_cents_total`, clears `penalty_basis`,
    `violation_unit_count`, `base_penalty_cents` and `admin_fee_cents` back to
    null, resets `penalty_total_cents` to 0, and returns the file to
    `RESPONSE_SUBMITTED`".

    Design: Difficulty/compensating_invariant/rescind_penalty_restores_both_money_ledgers_exactly
    """
    env, action = _escalated_file_in_an_enhanced_authority(api)
    assessed = _assess(env, action["id"])
    assert_money_cents(assessed["penalty_total_cents"], 78750, "penalty_total_cents")

    rescinded = _rescind(env, action["id"])
    assert rescinded["status"] == ACTION_RESPONSE_SUBMITTED
    assert_money_cents(rescinded["penalty_total_cents"], 0, "penalty_total_cents")
    assert_fields_are_none(
        rescinded,
        [
            "penalty_basis",
            "violation_unit_count",
            "base_penalty_cents",
            "admin_fee_cents",
        ],
        "the rescinded file",
    )

    # Each ledger drops by the full 78750, not by base_penalty_cents alone.
    assert_money_cents(
        env.read_establishment()["outstanding_penalty_cents"],
        0,
        "Establishment.outstanding_penalty_cents",
    )
    assert_money_cents(
        env.read_jurisdiction()["assessed_penalty_cents_total"],
        0,
        "Jurisdiction.assessed_penalty_cents_total",
    )
    assert_money_cents(
        env.read_summary()["outstanding_penalty_cents_total"],
        0,
        "outstanding_penalty_cents_total",
    )

    # The compensation is scoped to the money fields.
    settled = env.read_action(action["id"])
    assert settled["info_round_count"] == 1
    assert settled["response_count"] == 2
    assert settled["last_response_type"] == RESPONSE_DISPUTED


def test_the_money_block_on_a_reprint_completed_response_lifts_with_the_penalty(api):
    """PRD §2.6 rung 37: "The cited unit's `outstanding_penalty_cents` is 0, else
    `ERR_OUTSTANDING_PENALTY` (HTTP 402). Applies to a brand response whose
    `response_type` is `REPRINT_COMPLETED`." PRD §3.9: "a chain may not certify a
    reprint as complete for a unit that still owes an assessed penalty, though
    rescinding that penalty clears the block."

    Design: Difficulty/compensating_invariant/rescind_penalty_restores_both_money_ledgers_exactly
    """
    env, action = _escalated_file_in_an_enhanced_authority(api)
    _assess(env, action["id"])

    # A second file on the same unit is the only vantage point from which the
    # money rung can answer: rung 15 would otherwise reject a response filed
    # against the assessed file itself.
    sibling = open_citation(
        env,
        CITATION_CALORIES_NOT_DECLARED,
        inspection_note="Second inspection of the same board",
    )
    file_response(
        env, sibling["id"], RESPONSE_DISPUTED, response_note="Board was corrected"
    )
    regulator_action(
        env,
        sibling["id"],
        ACTION_TYPE_REQUEST_INFO,
        action_note="Confirm the corrected board is in place",
    )

    reprint_response = enforcement_response_payload(
        response_type=RESPONSE_REPRINT_COMPLETED,
        response_note="Corrected board installed",
    )
    validate_error(
        env.api.create_enforcement_response(
            sibling["id"], reprint_response, env.officer
        ),
        ERR_OUTSTANDING_PENALTY,
        402,
    )
    blocked = env.read_action(sibling["id"])
    assert blocked["status"] == ACTION_INFO_REQUESTED
    assert blocked["response_count"] == 1
    assert blocked["last_response_type"] == RESPONSE_DISPUTED

    _rescind(env, action["id"])

    accepted = validate_unpaginated(
        env.api.create_enforcement_response(
            sibling["id"], reprint_response, env.officer
        )
    )
    assert accepted["status"] == ACTION_RESPONSE_SUBMITTED
    assert accepted["last_response_type"] == RESPONSE_REPRINT_COMPLETED
    assert accepted["response_count"] == 2


def test_a_second_penalty_cycle_returns_both_ledgers_to_zero(api):
    """PRD §3.9: "That is the penalty cycle: `RESPONSE_SUBMITTED` to `ESCALATED`
    to `PENALTY_ASSESSED` and back to `RESPONSE_SUBMITTED`". PRD §3.0: "the
    reversal restores the affected counters to precisely their pre-cascade
    values, not to a recomputed approximation of them."

    Design: Difficulty/compensating_invariant/rescind_penalty_restores_both_money_ledgers_exactly
    """
    env, action = _escalated_file_in_an_enhanced_authority(api)
    _assess(env, action["id"])
    _rescind(env, action["id"])

    regulator_action(
        env,
        action["id"],
        ACTION_TYPE_REQUEST_INFO,
        action_note="One further round before escalating again",
    )
    file_response(
        env, action["id"], RESPONSE_DISPUTED, response_note="Position unchanged"
    )
    reescalated = regulator_action(
        env, action["id"], ACTION_TYPE_ESCALATE, action_note="Escalated a second time"
    )
    assert reescalated["info_round_count"] == 2
    assert reescalated["response_count"] == 3

    reassessed = _assess(env, action["id"])
    assert_money_cents(reassessed["penalty_total_cents"], 78750, "second assessment")
    assert_money_cents(
        env.read_establishment()["outstanding_penalty_cents"],
        78750,
        "Establishment.outstanding_penalty_cents after the second assessment",
    )

    _rescind(env, action["id"])
    assert_money_cents(
        env.read_establishment()["outstanding_penalty_cents"],
        0,
        "Establishment.outstanding_penalty_cents after the second rescission",
    )
    assert_money_cents(
        env.read_jurisdiction()["assessed_penalty_cents_total"],
        0,
        "Jurisdiction.assessed_penalty_cents_total after the second rescission",
    )
    assert env.read_action(action["id"])["status"] == ACTION_RESPONSE_SUBMITTED
