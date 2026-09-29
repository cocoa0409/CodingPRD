"""Four-hop cascades reached from two different triggers.

A certification walks recipe to item to line to board to brand. A permanent
closure walks unit to board to line to item to brand, and unwinds most of what
the certification did without rolling the declaration itself backwards.
"""

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_board_state,
    assert_brand_counters,
    assert_instant_equals,
    assert_item_declaration,
    validate_unpaginated,
)
from test_helpers.constants import (
    COMPLIANCE_REPRINT_REQUIRED,
    COVERAGE_NOT_COVERED,
    LABELING_DECLARED,
    LABELING_RELABEL_REQUIRED,
    LISTING_REMOVED,
    LISTING_STALE,
    PACKET_PUBLISHED,
    POSTURE_EXEMPT,
    POSTURE_RESTRICTED,
    PUBLICATION_PUBLISHED,
    PUBLICATION_WITHDRAWN,
    REASON_BELOW_UNIT_THRESHOLD,
    RECIPE_APPROVED,
    RECIPE_SUPERSEDED,
    UNIT_PERMANENTLY_CLOSED,
)
from test_helpers.factories import status_change_payload
from test_helpers.fixtures import (
    add_components,
    build_published_scenario,
    certify_analysis,
    certify_recipe_version,
    open_recipe_version,
    sandwich_components,
    submit_recipe,
)

CLOCK_EPOCH_INSTANT = "2026-08-01T00:00:00Z"
GRACE_DEADLINE = "2026-08-31T00:00:00Z"


# ---------------------------------------------------------------------------
# A live board, and a second recipe version waiting on its certification
# ---------------------------------------------------------------------------
def _pending_second_version(api: ApiClient):
    scenario = build_published_scenario(api)
    env = scenario.env
    r2 = open_recipe_version(
        env, scenario.item_id, change_note="Mayonnaise portion increased to 45 g"
    )
    add_components(env, r2["id"], sandwich_components(mayonnaise_grams=45))
    a2 = submit_recipe(env, r2["id"])
    return scenario, scenario.item.recipes[-1], r2, a2


def test_the_certification_supersedes_the_prior_version_and_rewrites_the_item(api):
    """PRD §3.4: "**Hop 1:** the menu item's previously `APPROVED` recipe, if there
    was one, moves from `APPROVED` to `SUPERSEDED`, and the newly certified
    recipe's `supersedes_recipe_id` is set to that row's `id`". "**Hop 2**,
    caused by hop 1: the item's `declared_calorie_min`, `declared_calorie_max`,
    `declared_sodium_mg`, `allergen_groups`, `cross_contact_groups` and
    `approved_recipe_version_no` are all rewritten from the newly approved
    recipe".

    Design: Difficulty/transitive_cascade/certification_cascade_recipe_to_item_to_board_to_brand
    """
    scenario, r1, r2, a2 = _pending_second_version(api)
    env = scenario.env

    certify_analysis(env, a2["id"], decision_note="Revised portion certified")

    approved = env.read_recipe(r2["id"])
    assert approved["status"] == RECIPE_APPROVED
    assert_instant_equals(
        approved["approved_at"], CLOCK_EPOCH_INSTANT, "Recipe.approved_at"
    )
    assert approved["computed_declared_max"] == 700
    assert approved["supersedes_recipe_id"] == r1["id"]
    assert env.read_recipe(r1["id"])["status"] == RECIPE_SUPERSEDED

    assert_item_declaration(
        env.read_item(scenario.item_id),
        declared_calorie_max=700,
        declared_sodium_mg=700,
        labeling_status=LABELING_RELABEL_REQUIRED,
        approved_recipe_version_no=2,
    )


def test_the_relabelled_item_stales_its_line_and_starts_the_reprint_clock(api):
    """PRD §3.4: "**Hop 3**, caused by hop 2 landing in `RELABEL_REQUIRED`: every
    line of the item whose `listing_status` is `LISTED` becomes `STALE`, and
    every board holding such a line whose `publication_status` is `PUBLISHED`
    moves `calorie_compliance_status` from `CURRENT` to `REPRINT_REQUIRED` with
    `reprint_deadline` set to the logical clock plus that board's authority's
    `reprint_grace_days` days."

    Design: Difficulty/transitive_cascade/certification_cascade_recipe_to_item_to_board_to_brand
    """
    scenario, r1, r2, a2 = _pending_second_version(api)
    env = scenario.env

    certify_analysis(env, a2["id"], decision_note="Revised portion certified")

    line = env.read_listing(scenario.board_id, scenario.board.listing["id"])
    assert line["listing_status"] == LISTING_STALE

    board = env.read_board(scenario.board_id)
    assert_board_state(
        board,
        publication_status=PUBLICATION_PUBLISHED,
        calorie_compliance_status=COMPLIANCE_REPRINT_REQUIRED,
        stale_listing_count=1,
    )
    assert_instant_equals(
        board["reprint_deadline"], GRACE_DEADLINE, "MenuBoard.reprint_deadline"
    )


def test_the_new_obligation_carries_the_brand_from_compliant_to_restricted(api):
    """PRD §3.4: "**Hop 4**, caused by hop 3: `Brand.open_reprint_obligation_count`
    rises by one for each newly `REPRINT_REQUIRED` board,
    `MenuBoard.stale_listing_count` is recomputed on each, and
    `compliance_posture` is recomputed — typically carrying the brand from
    `COMPLIANT` to `RESTRICTED`."

    Design: Difficulty/transitive_cascade/certification_cascade_recipe_to_item_to_board_to_brand
    """
    scenario, r1, r2, a2 = _pending_second_version(api)
    env = scenario.env

    certify_analysis(env, a2["id"], decision_note="Revised portion certified")

    assert_brand_counters(
        env.read_brand(),
        open_reprint_obligation_count=1,
        overdue_board_count=0,
        compliance_posture=POSTURE_RESTRICTED,
    )
    # The allergen sets did not change, so the published packet stays fresh.
    assert env.read_packet(scenario.packet_id)["status"] == PACKET_PUBLISHED


# ---------------------------------------------------------------------------
# The same estate, closed out of the register for good
# ---------------------------------------------------------------------------
def _estate_with_a_stale_live_board(api: ApiClient):
    """The end state of the certification cascade: 20 units, one PUBLISHED board
    in REPRINT_REQUIRED with a STALE line, the item at RELABEL_REQUIRED."""
    scenario = build_published_scenario(api)
    certify_recipe_version(
        scenario.env,
        scenario.item_id,
        sandwich_components(mayonnaise_grams=45),
        change_note="Mayonnaise portion increased to 45 g",
    )
    return scenario


def _close_the_unit(scenario):
    return validate_unpaginated(
        scenario.api.change_establishment_status(
            scenario.env.establishment_id,
            status_change_payload(
                new_unit_status=UNIT_PERMANENTLY_CLOSED,
                effective_note="Lease terminated; unit closed for good",
            ),
            scenario.env.officer,
        )
    )


def test_permanent_closure_withdraws_the_board_and_removes_its_lines(api):
    """PRD §3.1: "**Hop 1:** every board of the unit whose `publication_status` is
    `DRAFT` or `PUBLISHED` moves to `WITHDRAWN`, processed in `created_at`
    ascending order. **Hop 2**, caused by hop 1: each withdrawn board sets its
    lines whose `listing_status` is `LISTED` or `STALE` to `REMOVED`, and where
    the board left `PUBLISHED` with `calorie_compliance_status` of
    `REPRINT_REQUIRED` or `OVERDUE`, `Brand.open_reprint_obligation_count`
    drops by 1 for that board".

    Design: Difficulty/transitive_cascade/permanent_closure_cascade_unit_to_board_to_item_to_brand
    """
    scenario = _estate_with_a_stale_live_board(api)
    env = scenario.env

    closed = _close_the_unit(scenario)
    assert closed["unit_status"] == UNIT_PERMANENTLY_CLOSED

    board = env.read_board(scenario.board_id)
    assert board["publication_status"] == PUBLICATION_WITHDRAWN
    # The second dimension is not rewritten by the withdrawal.
    assert board["calorie_compliance_status"] == COMPLIANCE_REPRINT_REQUIRED

    line = env.read_listing(scenario.board_id, scenario.board.listing["id"])
    assert line["listing_status"] == LISTING_REMOVED
    assert_brand_counters(env.read_brand(), open_reprint_obligation_count=0)


def test_the_item_returns_to_declared_without_rolling_its_figures_back(api):
    """PRD §3.1: "**Hop 3**, caused by hop 2: every menu item that no longer has
    any `STALE` line anywhere returns from `labeling_status`
    `RELABEL_REQUIRED` to `DECLARED`."

    Design: Difficulty/transitive_cascade/permanent_closure_cascade_unit_to_board_to_item_to_brand
    """
    scenario = _estate_with_a_stale_live_board(api)
    env = scenario.env
    assert (
        env.read_item(scenario.item_id)["labeling_status"] == LABELING_RELABEL_REQUIRED
    )

    _close_the_unit(scenario)

    assert_item_declaration(
        env.read_item(scenario.item_id),
        declared_calorie_max=700,
        labeling_status=LABELING_DECLARED,
    )


def test_the_recount_drops_the_brand_below_the_unit_threshold(api):
    """PRD §3.1: "**Hop 4**, caused by hops 1 through 3:
    `Brand.counted_unit_count` is recomputed, the coverage determination
    re-runs on the `OPERATING_ONLY` basis, and `compliance_posture` is
    recomputed. `Establishment.board_count` ends at 0."

    Design: Difficulty/transitive_cascade/permanent_closure_cascade_unit_to_board_to_item_to_brand
    """
    scenario = _estate_with_a_stale_live_board(api)
    env = scenario.env

    _close_the_unit(scenario)

    assert_brand_counters(
        env.read_brand(),
        coverage_status=COVERAGE_NOT_COVERED,
        coverage_reason=REASON_BELOW_UNIT_THRESHOLD,
        counted_unit_count=19,
        compliance_posture=POSTURE_EXEMPT,
    )
    assert env.read_establishment()["board_count"] == 0
