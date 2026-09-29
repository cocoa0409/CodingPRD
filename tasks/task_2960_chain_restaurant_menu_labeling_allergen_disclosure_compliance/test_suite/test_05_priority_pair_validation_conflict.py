"""One publish call that breaks two rules at once, twice over.

Both scenarios below arrange a single `POST /menu-boards/{id}/publish` that
violates two rungs of the refusal ladder simultaneously, and pin down which
rung answers. PRD §2.6: "The first condition that fails ends the request
immediately with that condition's error; no later condition is consulted, and
no partial write is retained."
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_BOARD_NOT_DRAFT, ERR_SUCCINCT_STATEMENT_MISMATCH
from test_helpers.assertions import (
    assert_board_state,
    assert_brand_counters,
    assert_instant_equals,
    assert_item_declaration,
    validate_unpaginated,
)
from test_helpers.constants import (
    BOARD_PRIMARY_MENU_BOARD,
    CLOCK_EPOCH_COMPACT,
    COVERAGE_COVERED,
    LABELING_DECLARATION_PENDING,
    LISTING_LISTED,
    PACKET_PUBLISHED,
    PUBLICATION_DRAFT,
    PUBLICATION_PUBLISHED,
    STATEMENT_FEDERAL_DEFAULT,
    STATEMENT_STATE_EXTENDED,
)
from test_helpers.factories import board_publish_payload
from test_helpers.fixtures import (
    BoardBundle,
    Env,
    PublishedScenario,
    add_listing,
    build_published_scenario,
    certified_sandwich,
    create_board,
    draft_and_publish_packet,
    make_menu_item,
    published_board,
    seed_registry,
)

# The first board holds the closed window, the second the open-ended one that
# starts exactly where the first one ends.
WINDOW_ONE_OPENS = "2026-08-01T00:00:00Z"
WINDOW_ONE_CLOSES = "2026-09-01T00:00:00Z"
WINDOW_TWO_OPENS = "2026-09-01T00:00:00Z"
# Falls inside the second board's open-ended window, so it collides as well.
COLLIDING_INSTANT = "2026-09-15T00:00:00Z"


# ---------------------------------------------------------------------------
# Two live boards of one establishment, adjacent at the exclusive end
# ---------------------------------------------------------------------------
def _two_adjacent_live_windows(
    api: ApiClient,
) -> Tuple[PublishedScenario, BoardBundle]:
    scenario = build_published_scenario(
        api,
        effective_from=WINDOW_ONE_OPENS,
        effective_to=WINDOW_ONE_CLOSES,
        required_succinct_statement_variant=STATEMENT_FEDERAL_DEFAULT,
    )
    second = published_board(
        scenario.env,
        scenario.item_id,
        board_type=BOARD_PRIMARY_MENU_BOARD,
        effective_from=WINDOW_TWO_OPENS,
    )
    return scenario, second


def test_a_window_that_starts_at_another_windows_exclusive_end_is_accepted(api):
    """PRD §3.7: "a window includes its `effective_from` instant and excludes
    its `effective_to` instant, so a window that begins exactly at another
    window's `effective_to` is accepted, with no buffer required between them."

    Design: Difficulty/priority_pair_validation_conflict/board_not_draft_outranks_window_conflict
    """
    scenario, second = _two_adjacent_live_windows(api)

    first = scenario.env.read_board(scenario.board_id)
    assert_board_state(first, publication_status=PUBLICATION_PUBLISHED)
    assert_instant_equals(first["effective_to"], WINDOW_ONE_CLOSES, "B1.effective_to")

    live_second = scenario.env.read_board(second.board_id)
    assert_board_state(live_second, publication_status=PUBLICATION_PUBLISHED)
    assert_instant_equals(
        live_second["effective_from"], WINDOW_TWO_OPENS, "B2.effective_from"
    )
    assert live_second["effective_to"] is None


def test_republishing_a_live_board_reports_the_state_rung_not_the_window_rung(api):
    """PRD §2.6 rung 11: "The board's `publication_status` is `DRAFT`, else
    `ERR_BOARD_NOT_DRAFT`. Applies to listing creation and board publication.
    Re-publishing an already `PUBLISHED` board therefore fails here, before any
    display-window arithmetic is attempted."

    Design: Difficulty/priority_pair_validation_conflict/board_not_draft_outranks_window_conflict
    """
    scenario, _second = _two_adjacent_live_windows(api)

    validate_error(
        scenario.api.publish_menu_board(
            scenario.board_id,
            board_publish_payload(effective_from=COLLIDING_INSTANT),
            scenario.env.publisher,
        ),
        ERR_BOARD_NOT_DRAFT,
        409,
    )


def test_the_refused_republication_leaves_both_display_windows_alone(api):
    """PRD §2.6: "The first condition that fails ends the request immediately
    with that condition's error; no later condition is consulted, and no partial
    write is retained."

    Design: Difficulty/priority_pair_validation_conflict/board_not_draft_outranks_window_conflict
    """
    scenario, second = _two_adjacent_live_windows(api)

    validate_error(
        scenario.api.publish_menu_board(
            scenario.board_id,
            board_publish_payload(effective_from=COLLIDING_INSTANT),
            scenario.env.publisher,
        ),
        ERR_BOARD_NOT_DRAFT,
        409,
    )

    first = scenario.env.read_board(scenario.board_id)
    assert_instant_equals(first["effective_from"], WINDOW_ONE_OPENS, "B1.effective_from")
    assert_instant_equals(first["effective_to"], WINDOW_ONE_CLOSES, "B1.effective_to")
    assert_board_state(first, publication_status=PUBLICATION_PUBLISHED)

    live_second = scenario.env.read_board(second.board_id)
    assert_instant_equals(
        live_second["effective_from"], WINDOW_TWO_OPENS, "B2.effective_from"
    )
    assert live_second["effective_to"] is None
    assert_board_state(live_second, publication_status=PUBLICATION_PUBLISHED)


# ---------------------------------------------------------------------------
# A draft board with the wrong wording that also lists an uncertified item
# ---------------------------------------------------------------------------
def _wrong_wording_over_an_undeclared_line(api: ApiClient) -> Dict[str, Any]:
    """A DRAFT board in a STATE_EXTENDED authority breaking rungs 28 and 30."""
    env = seed_registry(
        api,
        code="MA-EXT",
        name="Massachusetts",
        unit_label="MA-0001",
        unit_label_prefix="MA-B",
        required_succinct_statement_variant=STATEMENT_STATE_EXTENDED,
    )
    certified = certified_sandwich(env)
    # Published while the sandwich was the brand's only non-exempt item, so the
    # stored matrix flag is true; the chowder arrives afterwards.
    packet = draft_and_publish_packet(env)
    pending = make_menu_item(
        env, name="Seasonal Chowder", first_offered_on="2026-07-15"
    )
    board = create_board(env, succinct_statement_variant=STATEMENT_FEDERAL_DEFAULT)
    add_listing(env, board.board_id, certified.item_id)
    pending_line = add_listing(env, board.board_id, pending["id"])
    return {
        "env": env,
        "packet": packet,
        "pending": pending,
        "board": board,
        "pending_line": pending_line,
    }


def _attempt_publication(env: Env, board: BoardBundle):
    return env.api.publish_menu_board(
        board.board_id,
        board_publish_payload(effective_from=CLOCK_EPOCH_COMPACT),
        env.publisher,
    )


def test_the_statement_check_answers_before_any_per_listing_check(api):
    """PRD §2.6 rung 28: "The board's `succinct_statement_variant` matches what
    its jurisdiction requires, or a granted variance covers it, else
    `ERR_SUCCINCT_STATEMENT_MISMATCH`. Applies to board publication, and is
    checked before any per-listing declaration check." PRD §2.6 rung 30: "Every
    listed item either carries a certified calorie declaration or is exempt,
    else `ERR_ITEM_CALORIES_UNDECLARED`. Applies to board publication."

    Design: Difficulty/priority_pair_validation_conflict/succinct_statement_mismatch_outranks_undeclared_item_calories
    """
    world = _wrong_wording_over_an_undeclared_line(api)

    validate_error(
        _attempt_publication(world["env"], world["board"]),
        ERR_SUCCINCT_STATEMENT_MISMATCH,
        409,
    )


def test_the_uncertified_item_still_shows_no_declaration_of_its_own(api):
    """PRD §3.7: "every listed item must either have `labeling_status` of
    `DECLARED` or `RELABEL_REQUIRED` with a non-null `declared_calorie_max`, or
    have `labeling_exempt` true; otherwise `ERR_ITEM_CALORIES_UNDECLARED`."

    Design: Difficulty/priority_pair_validation_conflict/succinct_statement_mismatch_outranks_undeclared_item_calories
    """
    world = _wrong_wording_over_an_undeclared_line(api)
    env = world["env"]

    validate_error(
        _attempt_publication(env, world["board"]),
        ERR_SUCCINCT_STATEMENT_MISMATCH,
        409,
    )

    pending = env.read_item(world["pending"]["id"])
    assert_item_declaration(
        pending,
        labeling_status=LABELING_DECLARATION_PENDING,
        labeling_exempt=False,
    )
    assert pending["declared_calorie_max"] is None
    assert pending["declared_calorie_min"] is None


def test_the_board_stays_draft_with_both_lines_and_no_window(api):
    """PRD §2.6: "The first condition that fails ends the request immediately
    with that condition's error; no later condition is consulted, and no partial
    write is retained."

    Design: Difficulty/priority_pair_validation_conflict/succinct_statement_mismatch_outranks_undeclared_item_calories
    """
    world = _wrong_wording_over_an_undeclared_line(api)
    env = world["env"]

    validate_error(
        _attempt_publication(env, world["board"]),
        ERR_SUCCINCT_STATEMENT_MISMATCH,
        409,
    )

    board = env.read_board(world["board"].board_id)
    assert_board_state(board, publication_status=PUBLICATION_DRAFT, listing_count=2)
    assert board["effective_from"] is None
    assert board["effective_to"] is None

    line = env.read_listing(board["id"], world["pending_line"]["id"])
    assert line["listing_status"] == LISTING_LISTED


def test_the_live_packet_and_the_brand_counters_are_untouched(api):
    """PRD §3.5: "`allergen_matrix_complete` is evaluated later from the stored
    flag, not re-derived. It is computed when the packet is drafted and refreshed
    when the packet is published, and at no other moment."

    Design: Difficulty/priority_pair_validation_conflict/succinct_statement_mismatch_outranks_undeclared_item_calories
    """
    world = _wrong_wording_over_an_undeclared_line(api)
    env = world["env"]

    validate_error(
        _attempt_publication(env, world["board"]),
        ERR_SUCCINCT_STATEMENT_MISMATCH,
        409,
    )

    packet = env.read_packet(world["packet"]["id"])
    assert packet["status"] == PACKET_PUBLISHED
    assert packet["allergen_matrix_complete"] is True

    assert_brand_counters(
        env.read_brand(),
        coverage_status=COVERAGE_COVERED,
        standard_item_count=2,
        has_published_disclosure_packet=True,
    )

    reread = validate_unpaginated(
        env.api.get_menu_board(world["board"].board_id, env.officer)
    )
    assert reread["publication_status"] == PUBLICATION_DRAFT
