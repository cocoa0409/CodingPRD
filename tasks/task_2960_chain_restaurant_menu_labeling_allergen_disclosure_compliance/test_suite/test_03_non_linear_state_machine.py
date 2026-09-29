"""State fields that walk back into a state they already left.

A recipe cycles DRAFT to ANALYSIS_PENDING and back through an absorbed
rejection, and APPROVED to SUPERSEDED and back through a withdrawal. A menu
board instead carries two independent dimensions on one row, and only one of
them moves at each step.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_brand_counters,
    assert_board_state,
    assert_instant_equals,
    assert_item_declaration,
    validate_unpaginated,
)
from test_helpers.constants import (
    ANALYSIS_CERTIFIED,
    ANALYSIS_REJECTED,
    COMPLIANCE_CURRENT,
    COMPLIANCE_OVERDUE,
    COMPLIANCE_REPRINT_REQUIRED,
    LABELING_DECLARED,
    LISTING_LISTED,
    LISTING_STALE,
    POSTURE_COMPLIANT,
    POSTURE_FROZEN,
    POSTURE_RESTRICTED,
    PUBLICATION_PUBLISHED,
    RECIPE_APPROVED,
    RECIPE_DRAFT,
    RECIPE_WITHDRAWN,
)
from test_helpers.factories import (
    brioche_bun_component,
    chicken_breast_component,
    herb_mayonnaise_component,
    reprint_payload,
    withdraw_certification_payload,
)
from test_helpers.fixtures import (
    add_components,
    build_published_scenario,
    certify_analysis,
    certify_recipe_version,
    make_menu_item,
    open_recipe_version,
    reject_analysis,
    sandwich_components,
    seed_registry,
    set_clock,
    submit_recipe,
)

CLOCK_AFTER_THE_DEADLINE = "2026-09-01T00:00:00Z"
GRACE_DEADLINE = "2026-08-31T00:00:00Z"


# ---------------------------------------------------------------------------
# A second recipe version that absorbs one rejection before it is certified
# ---------------------------------------------------------------------------
def _rejected_second_version(api: ApiClient):
    """v1 is certified at 530 Cal; v2 is submitted without the mayonnaise and
    rejected once, so it sits back in DRAFT."""
    env = seed_registry(api, unit_count=1)
    item = make_menu_item(env)

    r1 = open_recipe_version(env, item["id"], change_note="Initial specification")
    add_components(env, r1["id"], sandwich_components())
    a1 = submit_recipe(env, r1["id"])
    certify_analysis(env, a1["id"])

    r2 = open_recipe_version(
        env, item["id"], change_note="Mayonnaise portion increased to 45 g"
    )
    add_components(
        env, r2["id"], [chicken_breast_component(), brioche_bun_component()]
    )
    a2 = submit_recipe(env, r2["id"])
    reject_analysis(
        env, a2["id"], decision_note="Mayonnaise line item missing from the build"
    )
    return env, item, r1, r2, a2


def _second_version_certified(api: ApiClient):
    """The rejected v2 is completed with 45 g of mayonnaise and certified at 700."""
    env, item, r1, r2, a2 = _rejected_second_version(api)
    add_components(env, r2["id"], [herb_mayonnaise_component(grams=45)])
    a3 = submit_recipe(env, r2["id"])
    certify_analysis(env, a3["id"], decision_note="Revised build certified")
    return env, item, r1, r2, a2, a3


def test_an_absorbed_rejection_returns_the_recipe_to_draft(api):
    """PRD §3.4: "While `revision_round` is below 3, the recipe returns from
    `ANALYSIS_PENDING` to `DRAFT` with `revision_round` incremented by 1 and
    becomes editable again so further components can be added — a genuine
    revision cycle from `DRAFT` to `ANALYSIS_PENDING` and back."

    Design: Difficulty/non_linear_state_machine/recipe_revision_loop_and_supersede_restore_cycle
    """
    env, item, r1, r2, a2 = _rejected_second_version(api)

    reread = env.read_recipe(r2["id"])
    assert reread["status"] == RECIPE_DRAFT
    assert reread["revision_round"] == 1
    assert reread["version_no"] == 2
    assert env.read_analysis(a2["id"])["status"] == ANALYSIS_REJECTED

    # Editable again: the missing component is accepted while the recipe is DRAFT.
    add_components(env, r2["id"], [herb_mayonnaise_component(grams=45)])
    assert env.read_recipe(r2["id"])["component_count"] == 3


def test_withdrawing_the_newer_version_restores_the_superseded_one(api):
    """PRD §3.4: "**Hop 1:** the recipe named by `supersedes_recipe_id` moves from
    `SUPERSEDED` back to `APPROVED`, with its `approved_at` refreshed to the
    logical clock of the restoration." "Because the restored recipe re-enters
    `APPROVED`, the certification cycle from `APPROVED` to `SUPERSEDED` and
    back to `APPROVED` is a real cycle in this system, not a one-way street."

    Design: Difficulty/non_linear_state_machine/recipe_revision_loop_and_supersede_restore_cycle
    """
    env, item, r1, r2, a2, a3 = _second_version_certified(api)

    assert env.read_recipe(r2["id"])["supersedes_recipe_id"] == r1["id"]
    assert env.read_recipe(r1["id"])["supersedes_recipe_id"] is None
    assert env.read_analysis(a3["id"])["status"] == ANALYSIS_CERTIFIED

    withdrawn = validate_unpaginated(
        env.api.withdraw_certification(
            r2["id"],
            withdraw_certification_payload(
                reason="Supplier changed the mayonnaise formulation; reverting to v1"
            ),
            env.submitter,
        )
    )

    assert withdrawn["status"] == RECIPE_WITHDRAWN
    assert env.read_recipe(r1["id"])["status"] == RECIPE_APPROVED
    assert_instant_equals(
        env.read_recipe(r1["id"])["approved_at"],
        "2026-08-01T00:00:00Z",
        "Recipe.approved_at",
    )


def test_the_item_declaration_walks_back_to_the_restored_version(api):
    """PRD §3.4: "**Hop 2**, caused by hop 1: the item's `declared_calorie_min`,
    `declared_calorie_max`, `declared_sodium_mg`, `allergen_groups`,
    `cross_contact_groups` and `approved_recipe_version_no` are rewritten from
    the restored recipe."

    Design: Difficulty/non_linear_state_machine/recipe_revision_loop_and_supersede_restore_cycle
    """
    env, item, r1, r2, a2, a3 = _second_version_certified(api)

    assert_item_declaration(
        env.read_item(item["id"]),
        declared_calorie_max=700,
        approved_recipe_version_no=2,
    )

    get_success_data(
        env.api.withdraw_certification(
            r2["id"],
            withdraw_certification_payload(
                reason="Supplier changed the mayonnaise formulation; reverting to v1"
            ),
            env.submitter,
        )
    )

    assert_item_declaration(
        env.read_item(item["id"]),
        declared_calorie_min=530,
        declared_calorie_max=530,
        declared_sodium_mg=550,
        labeling_status=LABELING_DECLARED,
        approved_recipe_version_no=1,
    )


# ---------------------------------------------------------------------------
# A published board whose printed line has gone stale
# ---------------------------------------------------------------------------
def _published_board_gone_stale(api: ApiClient):
    """A live board whose item is re-certified from 530 Cal to 700 Cal."""
    scenario = build_published_scenario(api)
    certify_recipe_version(
        scenario.env,
        scenario.item_id,
        sandwich_components(mayonnaise_grams=45),
        change_note="Mayonnaise portion increased to 45 g",
    )
    return scenario


def test_a_certification_moves_only_the_compliance_dimension(api):
    """PRD §3.6: "**A board carries two independent state dimensions on one
    row.**" "`calorie_compliance_status` tracks whether the declarations
    printed on the board still match the certified recipes behind them, and
    advances only on recipe-certification cascades, on clock advances, and on
    reprints — never on a publication action."

    Design: Difficulty/non_linear_state_machine/menu_board_two_dimensions_advance_independently
    """
    scenario = _published_board_gone_stale(api)
    env = scenario.env

    board = env.read_board(scenario.board_id)
    assert_board_state(
        board,
        publication_status=PUBLICATION_PUBLISHED,
        calorie_compliance_status=COMPLIANCE_REPRINT_REQUIRED,
        listing_count=1,
        stale_listing_count=1,
        reprint_count=0,
    )
    assert_instant_equals(
        board["reprint_deadline"], GRACE_DEADLINE, "MenuBoard.reprint_deadline"
    )

    line = env.read_listing(scenario.board_id, scenario.board.listing["id"])
    assert line["listing_status"] == LISTING_STALE
    assert_brand_counters(
        env.read_brand(),
        open_reprint_obligation_count=1,
        overdue_board_count=0,
        compliance_posture=POSTURE_RESTRICTED,
    )


def test_the_clock_sweep_carries_the_missed_deadline_to_overdue(api):
    """PRD §3.7: "Every board whose `publication_status` is `PUBLISHED`, whose
    `calorie_compliance_status` is `REPRINT_REQUIRED`, and whose
    `reprint_deadline` is strictly earlier than the new clock instant moves to
    `OVERDUE`, incrementing `Brand.overdue_board_count` by 1 and recomputing
    `compliance_posture` — which carries the brand from `RESTRICTED` to
    `FROZEN`."

    Design: Difficulty/non_linear_state_machine/menu_board_two_dimensions_advance_independently
    """
    scenario = _published_board_gone_stale(api)
    env = scenario.env

    sweep = set_clock(env.api, CLOCK_AFTER_THE_DEADLINE)
    assert sweep["boards_marked_overdue"] == 1

    board = env.read_board(scenario.board_id)
    assert_board_state(
        board,
        publication_status=PUBLICATION_PUBLISHED,
        calorie_compliance_status=COMPLIANCE_OVERDUE,
    )
    assert_brand_counters(
        env.read_brand(),
        overdue_board_count=1,
        compliance_posture=POSTURE_FROZEN,
    )


def test_a_reprint_returns_the_overdue_board_to_current(api):
    """PRD §3.7: "A reprint filed while it was `OVERDUE` returns it to `CURRENT`
    too, and additionally decrements `Brand.overdue_board_count` by 1 before
    the posture is recomputed — which is how a brand walks back from `FROZEN`
    to `RESTRICTED`, or all the way to `COMPLIANT` when nothing else is
    outstanding." "The full compliance cycle is therefore `CURRENT` to
    `REPRINT_REQUIRED` to `OVERDUE` and back to `CURRENT`."

    Design: Difficulty/non_linear_state_machine/menu_board_two_dimensions_advance_independently
    """
    scenario = _published_board_gone_stale(api)
    env = scenario.env
    set_clock(env.api, CLOCK_AFTER_THE_DEADLINE)

    reprinted = validate_unpaginated(
        env.api.reprint_menu_board(
            scenario.board_id,
            reprint_payload(
                reprint_note="New boards installed with the 700 Cal declaration"
            ),
            env.publisher,
        )
    )

    assert_board_state(
        reprinted,
        publication_status=PUBLICATION_PUBLISHED,
        calorie_compliance_status=COMPLIANCE_CURRENT,
        stale_listing_count=0,
        reprint_count=1,
    )
    assert reprinted["reprint_deadline"] is None
    # The display window is untouched by either dimension moving.
    assert_instant_equals(
        reprinted["effective_from"], "2026-08-01T00:00:00Z", "MenuBoard.effective_from"
    )

    line = env.read_listing(scenario.board_id, scenario.board.listing["id"])
    assert line["listing_status"] == LISTING_LISTED
    assert line["declared_max_snapshot"] == 700

    assert_brand_counters(
        env.read_brand(),
        open_reprint_obligation_count=0,
        overdue_board_count=0,
        compliance_posture=POSTURE_COMPLIANT,
    )
