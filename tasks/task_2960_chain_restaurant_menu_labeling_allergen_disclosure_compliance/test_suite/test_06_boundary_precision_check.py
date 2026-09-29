"""Two thresholds examined exactly on their edge.

The first is the reprint tolerance band around an item's previously declared
maximum, reached through a certification. The second is the zero-non-exempt-item
edge of covered-establishment determination, reached through an explicit
coverage determination while the unit branch is satisfied at exactly twenty.
"""

from typing import Any, Dict, Tuple

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_board_state,
    assert_brand_counters,
    assert_item_declaration,
    assert_numeric_equals,
    reprint_tolerance,
    validate_unpaginated,
)
from test_helpers.constants import (
    BASIS_OPERATING_ONLY,
    COMPLIANCE_CURRENT,
    COMPLIANCE_REPRINT_REQUIRED,
    COVERAGE_COVERED,
    COVERAGE_NOT_COVERED,
    COVERED_UNIT_THRESHOLD,
    ITEM_CLASS_DAILY_SPECIAL,
    ITEM_CLASS_STANDARD,
    LABELING_DECLARED,
    LABELING_NOT_REQUIRED,
    LABELING_RELABEL_REQUIRED,
    LISTING_LISTED,
    POSTURE_COMPLIANT,
    POSTURE_EXEMPT,
    POSTURE_RESTRICTED,
    PUBLICATION_PUBLISHED,
    REASON_COVERED_BY_UNIT_COUNT,
    REASON_NO_STANDARD_MENU_ITEMS,
    RECIPE_APPROVED,
    RECIPE_SUPERSEDED,
    VARIABLE_NONE,
)
from test_helpers.factories import (
    coverage_determination_payload,
    dressed_greens_component,
    reprint_payload,
)
from test_helpers.fixtures import (
    BoardBundle,
    Env,
    certify_recipe_version,
    draft_and_publish_packet,
    make_menu_item,
    published_board,
    seed_registry,
)


def _certify_greens(env: Env, menu_item_id: str, grams: int, note: str):
    return certify_recipe_version(
        env,
        menu_item_id,
        [dressed_greens_component(grams=grams)],
        change_note=note,
        decision_note=f"{grams} g portion certified",
    )["recipe"]


def _salad_declared_at_one_hundred(
    api: ApiClient,
) -> Tuple[Env, Dict[str, Any], Dict[str, Any], BoardBundle]:
    """A 50 g salad declaring 100 Cal, printed on one live board."""
    env = seed_registry(api)
    item = make_menu_item(env, name="Side Salad")
    first = _certify_greens(env, item["id"], 50, "Initial 50 g portion")
    draft_and_publish_packet(env)
    board = published_board(env, item["id"])
    return env, item, first, board


def test_a_calorie_change_equal_to_the_tolerance_still_forces_a_reprint(api):
    """PRD §3.4: "the tolerance is the larger of twenty calories and the prior
    maximum multiplied by twenty per cent then rounded half up to a whole
    calorie." "A change equal to the tolerance does require a reprint" — "the
    comparison is at-or-above, not strictly-above."

    Design: Difficulty/boundary_precision_check/reprint_tolerance_band_at_and_below_the_threshold
    """
    env, item, first, board = _salad_declared_at_one_hundred(api)

    assert first["computed_declared_max"] == 100
    assert first["computed_sodium_mg"] == 150
    # A prior maximum of 100 gives max(20, 20) == 20, and 120 - 100 is exactly 20.
    assert reprint_tolerance(100) == 20

    second = _certify_greens(env, item["id"], 60, "Portion raised to 60 g")
    assert_numeric_equals(
        second["computed_base_calories"], "120.00", "computed_base_calories"
    )
    assert second["computed_declared_max"] == 120
    assert second["computed_sodium_mg"] == 180

    assert_item_declaration(
        env.read_item(item["id"]),
        declared_calorie_max=120,
        labeling_status=LABELING_RELABEL_REQUIRED,
    )
    assert_board_state(
        env.read_board(board.board_id),
        publication_status=PUBLICATION_PUBLISHED,
        calorie_compliance_status=COMPLIANCE_REPRINT_REQUIRED,
        stale_listing_count=1,
    )
    assert_brand_counters(
        env.read_brand(),
        open_reprint_obligation_count=1,
        compliance_posture=POSTURE_RESTRICTED,
    )


def test_the_reprint_takes_a_fresh_snapshot_at_the_new_maximum(api):
    """PRD §3.7: "every `STALE` line of the board returns to `LISTED` with
    `declared_min_snapshot`, `declared_max_snapshot` and `display_calorie_text`
    rebuilt from its item's current declaration." "A reprint filed while
    `calorie_compliance_status` was `REPRINT_REQUIRED` returns it to `CURRENT`."
    "`reprint_count` increments by 1, and `stale_listing_count` resets to 0."

    Design: Difficulty/boundary_precision_check/reprint_tolerance_band_at_and_below_the_threshold
    """
    env, item, _first, board = _salad_declared_at_one_hundred(api)
    _certify_greens(env, item["id"], 60, "Portion raised to 60 g")

    validate_unpaginated(
        env.api.reprint_menu_board(
            board.board_id,
            reprint_payload(reprint_note="Reprinted at 120 Cal"),
            env.publisher,
        )
    )

    assert_board_state(
        env.read_board(board.board_id),
        calorie_compliance_status=COMPLIANCE_CURRENT,
        stale_listing_count=0,
        reprint_count=1,
    )
    line = env.read_listing(board.board_id, board.listing["id"])
    assert line["declared_max_snapshot"] == 120
    assert line["listing_status"] == LISTING_LISTED


def test_a_change_below_the_widened_tolerance_leaves_the_board_current(api):
    """PRD §3.4: "an item previously declared at 400 calories has a tolerance of
    80 and survives a move to 470 untouched". PRD §3.4: "a certification that
    shifts the calorie figure of an item nobody has printed yet leaves the item
    in `DECLARED` and creates no reprint obligation anywhere."

    Design: Difficulty/boundary_precision_check/reprint_tolerance_band_at_and_below_the_threshold
    """
    env, item, _first, board = _salad_declared_at_one_hundred(api)
    second = _certify_greens(env, item["id"], 60, "Portion raised to 60 g")
    validate_unpaginated(
        env.api.reprint_menu_board(
            board.board_id,
            reprint_payload(reprint_note="Reprinted at 120 Cal"),
            env.publisher,
        )
    )

    # A prior maximum of 120 widens the band to max(20, 24) == 24, and the move
    # to 110 is a change of 10.
    assert reprint_tolerance(120) == 24
    third = _certify_greens(env, item["id"], 55, "Portion trimmed to 55 g")
    assert_numeric_equals(
        third["computed_base_calories"], "110.00", "computed_base_calories"
    )
    assert third["computed_declared_max"] == 110
    assert third["computed_sodium_mg"] == 170

    assert_item_declaration(
        env.read_item(item["id"]),
        declared_calorie_max=110,
        labeling_status=LABELING_DECLARED,
        approved_recipe_version_no=3,
    )
    assert_board_state(
        env.read_board(board.board_id),
        calorie_compliance_status=COMPLIANCE_CURRENT,
        stale_listing_count=0,
        reprint_count=1,
    )
    assert env.read_listing(board.board_id, board.listing["id"])[
        "listing_status"
    ] == LISTING_LISTED
    assert_brand_counters(
        env.read_brand(),
        open_reprint_obligation_count=0,
        compliance_posture=POSTURE_COMPLIANT,
    )
    assert env.read_recipe(second["id"])["status"] == RECIPE_SUPERSEDED
    assert env.read_recipe(third["id"])["status"] == RECIPE_APPROVED


# ---------------------------------------------------------------------------
# Twenty operating units and not one non-exempt item
# ---------------------------------------------------------------------------
def _twenty_units_and_only_a_daily_special(api: ApiClient) -> Tuple[Env, Dict[str, Any]]:
    env = seed_registry(
        api,
        code="TX-STD",
        name="Texas",
        unit_count=COVERED_UNIT_THRESHOLD,
        unit_label="TX-0001",
        unit_label_prefix="TX-B",
    )
    special = make_menu_item(
        env,
        name="Soup of the Day",
        item_class=ITEM_CLASS_DAILY_SPECIAL,
        variable_type=VARIABLE_NONE,
        first_offered_on="2026-07-01",
    )
    return env, special


def test_a_daily_special_never_joins_the_non_exempt_set(api):
    """PRD §3.2: "`DAILY_SPECIAL`, `CUSTOM_ORDER` and `SELF_SERVICE` items are
    always exempt, whatever the day count." "An item of any other class gets
    `labeling_exempt` true and `labeling_status` `NOT_REQUIRED`."

    Design: Difficulty/boundary_precision_check/zero_non_exempt_item_edge_outranks_unit_threshold
    """
    env, special = _twenty_units_and_only_a_daily_special(api)

    assert_item_declaration(
        env.read_item(special["id"]),
        labeling_exempt=True,
        labeling_status=LABELING_NOT_REQUIRED,
    )


def test_the_zero_item_branch_outranks_a_unit_branch_satisfied_at_twenty(api):
    """PRD §3.1: "If `standard_item_count` is 0, `coverage_status` is
    `NOT_COVERED` and `coverage_reason` is `NO_STANDARD_MENU_ITEMS`. Otherwise,
    if `counted_unit_count` is at least twenty, `coverage_status` is `COVERED`
    and `coverage_reason` is `COVERED_BY_UNIT_COUNT`." "The zero-item branch
    outranks the unit branch".

    Design: Difficulty/boundary_precision_check/zero_non_exempt_item_edge_outranks_unit_threshold
    """
    env, _special = _twenty_units_and_only_a_daily_special(api)

    result = validate_unpaginated(
        env.api.determine_coverage(
            env.brand_id,
            coverage_determination_payload(basis=BASIS_OPERATING_ONLY),
            env.admin,
        )
    )

    assert result["counted_unit_count"] == COVERED_UNIT_THRESHOLD
    assert result["standard_item_count"] == 0
    assert result["coverage_status"] == COVERAGE_NOT_COVERED
    assert result["coverage_reason"] == REASON_NO_STANDARD_MENU_ITEMS

    assert_brand_counters(
        env.read_brand(),
        coverage_status=COVERAGE_NOT_COVERED,
        coverage_reason=REASON_NO_STANDARD_MENU_ITEMS,
        compliance_posture=POSTURE_EXEMPT,
    )


def test_one_standard_item_flips_the_summary_with_no_unit_changing(api):
    """PRD §3.1: "a brand's compliance summary is recomputed from current rows at
    read time rather than served from stored counters. It returns `brand_id`,
    `coverage_status`, `coverage_reason`, `counted_unit_count`,
    `standard_item_count`, `compliance_posture`, `open_reprint_obligation_count`,
    `overdue_board_count`, `open_enforcement_escalated_count`,
    `has_published_disclosure_packet`".

    Design: Difficulty/boundary_precision_check/zero_non_exempt_item_edge_outranks_unit_threshold
    """
    env, _special = _twenty_units_and_only_a_daily_special(api)
    validate_unpaginated(
        env.api.determine_coverage(
            env.brand_id,
            coverage_determination_payload(basis=BASIS_OPERATING_ONLY),
            env.admin,
        )
    )

    standard = make_menu_item(
        env,
        name="Grill Sandwich",
        item_class=ITEM_CLASS_STANDARD,
        variable_type=VARIABLE_NONE,
        first_offered_on="2026-08-01",
    )
    assert env.read_item(standard["id"])["labeling_exempt"] is False

    summary = env.read_summary()
    assert summary["counted_unit_count"] == COVERED_UNIT_THRESHOLD
    assert summary["standard_item_count"] == 1
    assert summary["coverage_status"] == COVERAGE_COVERED
    assert summary["coverage_reason"] == REASON_COVERED_BY_UNIT_COUNT
    assert summary["compliance_posture"] == POSTURE_COMPLIANT
    assert summary["has_published_disclosure_packet"] is False
