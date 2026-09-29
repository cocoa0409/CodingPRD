"""Refusals read at the rung that produces them.

Each case here drives one operation to the exact point where a single ladder
rung of PRD 2.6 decides the outcome, then reads the aggregate back to prove
that nothing was written on the way out.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_ACTION_STATE_INVALID,
    ERR_ALLERGEN_MATRIX_INCOMPLETE,
    ERR_ALREADY_TERMINAL,
    ERR_BRAND_NOT_COVERED,
    ERR_BRAND_POSTURE_FROZEN,
    ERR_CHOICE_GROUP_INCONSISTENT,
    ERR_CROSS_CONTACT_STATEMENT_REQUIRED,
    ERR_DUPLICATE_LISTING,
    ERR_INFO_ROUND_REQUIRED,
    ERR_INVALID_DATE_RANGE,
    ERR_ITEM_BRAND_MISMATCH,
    ERR_ITEM_NOT_TEMPORARY,
    ERR_NO_STALE_LISTINGS,
    ERR_RECIPE_HAS_NO_BASE_COMPONENT,
    ERR_SODIUM_WARNING_ICON_REQUIRED,
    ERR_VARIANCE_NOT_ALLOWED,
)
from test_helpers.assertions import (
    assert_board_state,
    assert_brand_counters,
    assert_fields_are_none,
    assert_instant_equals,
    assert_item_declaration,
    assert_money_cents,
    assert_numeric_equals,
    expected_display_calorie_text,
    ids_of,
    round_half_up,
    validate_unpaginated,
)
from test_helpers.constants import (
    ACTION_CLOSED_PENALTY,
    ACTION_ESCALATED,
    ACTION_INFO_REQUESTED,
    ACTION_OPEN,
    ACTION_PENALTY_ASSESSED,
    ACTION_RESPONSE_SUBMITTED,
    ACTION_TYPE_ASSESS_PENALTY,
    ACTION_TYPE_CLOSE_COMPLIANT,
    ACTION_TYPE_CLOSE_PENALTY,
    ACTION_TYPE_ESCALATE,
    ACTION_TYPE_REQUEST_INFO,
    ACTION_TYPE_RESCIND_PENALTY,
    ALLERGEN_CRUSTACEAN_SHELLFISH,
    ALLERGEN_NONE,
    ALLERGEN_SOY,
    ALLERGEN_TREE_NUT,
    BASE_VIOLATION_CENTS,
    BOARD_DRIVE_THRU_BOARD,
    BOARD_PRIMARY_MENU_BOARD,
    CHANNEL_IN_STORE_BINDER,
    CHANNEL_QR_HANDOUT,
    CITATION_ALLERGEN_MATRIX_MISSING,
    CITATION_SUCCINCT_STATEMENT_MISSING,
    CITATION_WRITTEN_INFO_UNAVAILABLE,
    CLOCK_EPOCH_COMPACT,
    COMPLIANCE_CURRENT,
    COVERAGE_COVERED,
    COVERAGE_NOT_COVERED,
    CROSS_CONTACT_NONE,
    CROSS_CONTACT_SHARED_EQUIPMENT,
    CROSS_CONTACT_SHARED_FRYER,
    EXTRA_REQUIREMENT_SODIUM_WARNING,
    FEE_RATE_TIER_1,
    FEE_TIER_1_CEILING_CENTS,
    GRACE_DAYS_WITH_EXTRA_REQUIREMENT,
    ITEM_CLASS_DAILY_SPECIAL,
    ITEM_CLASS_TEMPORARY,
    ITEM_CLASS_TEST_MARKET,
    LABELING_NOT_REQUIRED,
    LISTING_LISTED,
    PACKET_DRAFT,
    PACKET_PUBLISHED,
    PENALTY_BASIS_PER_ESTABLISHMENT,
    POSTURE_COMPLIANT,
    POSTURE_FROZEN,
    PREEMPTION_PREEMPTED,
    PREEMPTION_VARIANCE_ALLOWED,
    PUBLICATION_DRAFT,
    PUBLICATION_PUBLISHED,
    REASON_BELOW_UNIT_THRESHOLD,
    REASON_COVERED_BY_UNIT_COUNT,
    RECIPE_DRAFT,
    REQUIREMENT_SUCCINCT_STATEMENT,
    REQUIREMENT_WRITTEN_INFO_FORMAT,
    RESPONSE_DISPUTED,
    ROLE_BASE,
    ROLE_CHOICE,
    SELECTION_EXACTLY_ONE,
    SELECTION_UNLIMITED,
    SELECTION_UP_TO_N,
    STATEMENT_FEDERAL_DEFAULT,
    TIER_FEDERAL_ALIGNED,
    VARIABLE_COMBINATION_MEAL,
    VARIANCE_DECISION_DENIED,
    VARIANCE_DECISION_GRANTED,
    VARIANCE_DECISION_OPEN_REVIEW,
    VARIANCE_DENIED,
    VARIANCE_SUBMITTED,
    VARIANCE_UNDER_REVIEW,
)
from test_helpers.factories import (
    OMIT,
    board_publish_payload,
    component_payload,
    disclosure_packet_payload,
    exemption_review_payload,
    listing_payload,
    menu_board_payload,
    menu_item_payload,
    offer_window_payload,
    recipe_payload,
    regulator_action_payload,
    reprint_payload,
    submit_for_analysis_payload,
    variance_decision_payload,
    variance_request_payload,
)
from test_helpers.fixtures import (
    BoardBundle,
    Env,
    add_listing,
    certified_sandwich,
    certify_recipe_version,
    create_board,
    decide_variance,
    draft_and_publish_packet,
    draft_packet,
    file_response,
    file_variance,
    make_brand,
    make_establishment,
    make_menu_item,
    open_citation,
    open_recipe_version,
    published_board,
    regulator_action,
    seed_registry,
)

SIDE_GROUP = "SIDE"
SODIUM_THRESHOLD_MG = 800
CROSS_CONTACT_WORDING = "Fried items share one fryer with shellfish."


# ---------------------------------------------------------------------------
# Rung 19: one escalated citation freezes every menu and board write
# ---------------------------------------------------------------------------
def _drive_to_escalated(env: Env, action_id: str) -> Dict[str, Any]:
    """OPEN -> RESPONSE_SUBMITTED -> INFO_REQUESTED -> RESPONSE_SUBMITTED -> ESCALATED."""
    file_response(env, action_id, RESPONSE_DISPUTED)
    regulator_action(env, action_id, ACTION_TYPE_REQUEST_INFO)
    file_response(env, action_id, RESPONSE_DISPUTED)
    return regulator_action(env, action_id, ACTION_TYPE_ESCALATE)


def _frozen_brand(api: ApiClient) -> Tuple[Env, str, Dict[str, Any]]:
    """A covered brand carrying one escalated citation, so its posture is FROZEN."""
    env = seed_registry(api, preemption_mode=PREEMPTION_PREEMPTED)
    item = certified_sandwich(env)
    draft_and_publish_packet(env)
    action = open_citation(env, CITATION_ALLERGEN_MATRIX_MISSING)
    escalated = _drive_to_escalated(env, action["id"])
    return env, item.item_id, escalated


def test_one_escalated_citation_freezes_the_brand_and_blocks_a_new_item(api):
    """PRD §3.9: "A successful escalation moves the file to `ESCALATED`,
    increments `Brand.open_enforcement_escalated_count` by 1, and recomputes
    `compliance_posture` to `FROZEN`." PRD §2.6 rung 19: "The owning brand's
    `compliance_posture` is not `FROZEN`, else `ERR_BRAND_POSTURE_FROZEN`.
    Applies to five operations: menu-item creation, recipe-version creation,
    board creation, listing creation and board publication."

    Design: Corner/validations/frozen_posture_blocks_menu_and_board_writes_but_never_reads
    """
    env, _item_id, escalated = _frozen_brand(api)

    assert escalated["status"] == ACTION_ESCALATED
    assert escalated["info_round_count"] == 1
    assert_brand_counters(
        env.read_brand(),
        open_enforcement_escalated_count=1,
        compliance_posture=POSTURE_FROZEN,
    )

    validate_error(
        env.api.create_menu_item(
            menu_item_payload(
                brand_id=env.brand_id,
                name="Late Night Wrap",
                first_offered_on="2026-08-01",
            ),
            env.officer,
        ),
        ERR_BRAND_POSTURE_FROZEN,
        409,
    )

    rows, meta = validate_paginated(
        env.api.list_menu_items(env.officer, params={"brand_id": env.brand_id})
    )
    assert meta["total_count"] == 1, "the blocked item was not created"
    assert len(rows) == 1


def test_a_frozen_brand_can_open_neither_a_board_nor_a_recipe_version(api):
    """PRD §2.9: "`FROZEN` is the gate named in rung 19 of §2.6: a brand that
    has let a board go overdue, or that is carrying an escalated citation,
    cannot add a menu item, open a new recipe version, create a board, add a
    line to a board, or take a board live." The recipe attempt carries the
    item's current version, so PRD §2.6 rung 9 passes and rung 19 is what
    fires.

    Design: Corner/validations/frozen_posture_blocks_menu_and_board_writes_but_never_reads
    """
    env, item_id, _escalated = _frozen_brand(api)

    validate_error(
        env.api.create_menu_board(
            menu_board_payload(
                establishment_id=env.establishment_id,
                board_type=BOARD_PRIMARY_MENU_BOARD,
                succinct_statement_variant=STATEMENT_FEDERAL_DEFAULT,
            ),
            env.publisher,
        ),
        ERR_BRAND_POSTURE_FROZEN,
        409,
    )
    validate_error(
        env.api.create_recipe(
            item_id,
            recipe_payload(
                expected_menu_item_version=env.read_item(item_id)["version"],
                change_note="Blocked while frozen",
            ),
            env.submitter,
        ),
        ERR_BRAND_POSTURE_FROZEN,
        409,
    )

    assert env.read_establishment()["board_count"] == 0


def test_the_freeze_never_reaches_a_read(api):
    """PRD §2.6 rung 4: "Applies to every write; reads are never
    ownership-scoped." Every fetch in PRD §4 is authorized for "All five
    roles", so a unit's publisher may read the frozen brand it hangs off.

    Design: Corner/validations/frozen_posture_blocks_menu_and_board_writes_but_never_reads
    """
    env, item_id, _escalated = _frozen_brand(api)

    brand = validate_unpaginated(env.api.get_brand(env.brand_id, env.publisher))
    assert brand["compliance_posture"] == POSTURE_FROZEN

    item = validate_unpaginated(env.api.get_menu_item(item_id, env.regulator))
    assert item["id"] == item_id


# ---------------------------------------------------------------------------
# Rung 20: packet drafting waits for the twentieth unit
# ---------------------------------------------------------------------------
def _one_unit_short_of_coverage(api: ApiClient) -> Env:
    """Nineteen OPERATING units and one non-exempt item: one unit short."""
    env = seed_registry(api, unit_count=19)
    make_menu_item(env)
    return env


def _binder_only_packet_payload(env: Env) -> Dict[str, Any]:
    return disclosure_packet_payload(
        expected_brand_version=env.brand_version,
        cross_contact_statement="",
        written_info_channels=[CHANNEL_IN_STORE_BINDER],
    )


def test_a_packet_cannot_be_drafted_one_unit_short_of_coverage(api):
    """PRD §3.5: "Drafting is refused with `ERR_BRAND_NOT_COVERED` unless the
    brand's `coverage_status` is `COVERED` — a chain that is not a covered
    establishment has nothing to disclose under this program."

    Design: Corner/validations/packet_creation_waits_for_the_brand_to_become_covered
    """
    env = _one_unit_short_of_coverage(api)
    assert_brand_counters(
        env.read_brand(),
        coverage_status=COVERAGE_NOT_COVERED,
        coverage_reason=REASON_BELOW_UNIT_THRESHOLD,
        counted_unit_count=19,
        standard_item_count=1,
    )

    validate_error(
        env.api.create_disclosure_packet(
            env.brand_id, _binder_only_packet_payload(env), env.officer
        ),
        ERR_BRAND_NOT_COVERED,
        409,
    )

    _rows, meta = validate_paginated(
        env.api.list_brand_disclosure_packets(env.brand_id, env.officer)
    )
    assert meta["total_count"] == 0, "the refused draft left no packet behind"


def test_the_twentieth_unit_unlocks_a_draft_whose_matrix_is_still_empty(api):
    """PRD §3.1: "Otherwise, if `counted_unit_count` is at least twenty,
    `coverage_status` is `COVERED` and `coverage_reason` is
    `COVERED_BY_UNIT_COUNT`." PRD §3.5: "The new packet takes `status` `DRAFT`,
    `published_at` null, and `packet_version` set to 1 for the brand's first
    packet", and "`covered_item_count` is the number of those items that
    actually have a recipe in `APPROVED` — a non-exempt item still waiting on
    certification is in the matrix's population but does not count as covered."

    Design: Corner/validations/packet_creation_waits_for_the_brand_to_become_covered
    """
    env = _one_unit_short_of_coverage(api)
    make_establishment(
        api,
        brand_id=env.brand_id,
        jurisdiction_id=env.jurisdiction_id,
        unit_label="CA-0020",
    )
    assert_brand_counters(
        env.read_brand(),
        coverage_status=COVERAGE_COVERED,
        coverage_reason=REASON_COVERED_BY_UNIT_COUNT,
        counted_unit_count=20,
    )

    packet = validate_unpaginated(
        env.api.create_disclosure_packet(
            env.brand_id, _binder_only_packet_payload(env), env.officer
        ),
        201,
    )
    assert packet["packet_version"] == 1
    assert packet["status"] == PACKET_DRAFT
    assert packet["covered_item_count"] == 0
    assert packet["allergen_matrix_complete"] is False
    assert packet["published_at"] is None


# ---------------------------------------------------------------------------
# Rungs 21 and 22: whose item is it, and is it already printed here
# ---------------------------------------------------------------------------
def _two_brands_and_one_draft_board(api: ApiClient) -> Tuple[Env, str, str, str]:
    """One unit with a DRAFT board, its own item, and a second chain's item."""
    env = seed_registry(api, unit_count=1)
    own = make_menu_item(env)
    other = Env(
        api=api,
        jurisdiction=env.jurisdiction,
        brand=make_brand(
            api,
            legal_name="Silver Spoon Diners Inc",
            doing_business_as="Silver Spoon",
        ),
        establishment=env.establishment,
    )
    foreign = make_menu_item(other, name="Spoon Chowder")
    board = create_board(env)
    return env, board.board_id, own["id"], foreign["id"]


def test_a_new_line_starts_listed_with_the_declaration_it_found(api):
    """PRD §3.6: "On success the line starts at `listing_status` `LISTED` with
    its `menu_board_id` pointing at the board, and `display_calorie_text`,
    `declared_min_snapshot` and `declared_max_snapshot` captured from the item's
    `declared_calorie_min` and `declared_calorie_max` as they stand at that
    moment." The item here has never been certified, so the two snapshots are
    captured from a declaration that is still null.

    Design: Corner/validations/listing_rejects_a_foreign_item_and_a_repeat_of_the_same_pair
    """
    env, board_id, own_item_id, _foreign_item_id = _two_brands_and_one_draft_board(api)

    listing = validate_unpaginated(
        env.api.create_listing(
            board_id, listing_payload(menu_item_id=own_item_id), env.publisher
        ),
        201,
    )
    assert listing["listing_status"] == LISTING_LISTED
    assert listing["menu_board_id"] == board_id
    assert_fields_are_none(
        listing, ["declared_min_snapshot", "declared_max_snapshot"], "Listing"
    )
    assert_board_state(env.read_board(board_id), listing_count=1)


def test_the_same_pair_cannot_be_printed_twice_on_one_board(api):
    """PRD §3.6: "The board-and-item pair must not already be carried by a line
    whose `listing_status` is `LISTED` or `STALE`, else `ERR_DUPLICATE_LISTING`;
    a line that has been `REMOVED` does not block re-listing the same item."

    Design: Corner/validations/listing_rejects_a_foreign_item_and_a_repeat_of_the_same_pair
    """
    env, board_id, own_item_id, _foreign_item_id = _two_brands_and_one_draft_board(api)
    first = add_listing(env, board_id, own_item_id)

    validate_error(
        env.api.create_listing(
            board_id, listing_payload(menu_item_id=own_item_id), env.publisher
        ),
        ERR_DUPLICATE_LISTING,
        409,
    )

    assert_board_state(env.read_board(board_id), listing_count=1)
    rows, meta = validate_paginated(
        env.api.list_menu_board_listings(board_id, env.publisher)
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [first["id"]]


def test_a_board_cannot_print_another_chains_item(api):
    """PRD §3.6: "The item's `brand_id` must equal the `brand_id` of the board's
    establishment, else `ERR_ITEM_BRAND_MISMATCH` — a board cannot print another
    chain's item even when both chains are covered."

    Design: Corner/validations/listing_rejects_a_foreign_item_and_a_repeat_of_the_same_pair
    """
    env, board_id, _own_item_id, foreign_item_id = _two_brands_and_one_draft_board(api)

    validate_error(
        env.api.create_listing(
            board_id, listing_payload(menu_item_id=foreign_item_id), env.publisher
        ),
        ERR_ITEM_BRAND_MISMATCH,
        409,
    )

    assert_board_state(env.read_board(board_id), listing_count=0)
    _rows, meta = validate_paginated(
        env.api.list_menu_board_listings(board_id, env.publisher)
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Rungs 23 and 24: the three choice-group fields, and the missing base
# ---------------------------------------------------------------------------
def _kids_box_draft_recipe(api: ApiClient) -> Tuple[Env, str]:
    """A DRAFT recipe of a COMBINATION_MEAL item, ready to take components."""
    env = seed_registry(api, unit_count=1)
    item = make_menu_item(
        env, name="Kids Box", variable_type=VARIABLE_COMBINATION_MEAL
    )
    recipe = open_recipe_version(env, item["id"])
    return env, recipe["id"]


def _apple_slices(**overrides: Any) -> Dict[str, Any]:
    payload = dict(
        role=ROLE_CHOICE,
        grams=80,
        calories_per_100g=60,
        sodium_mg_per_100g=2,
        added_sugar_g_per_100g=8,
        allergen_group=ALLERGEN_NONE,
        cross_contact_risk=CROSS_CONTACT_NONE,
        choice_group=SIDE_GROUP,
        selection_mode=SELECTION_EXACTLY_ONE,
    )
    payload.update(overrides)
    return component_payload("Apple slices", **payload)


def test_a_choice_component_must_name_both_its_group_and_its_mode(api):
    """PRD §3.3: "a component whose `role` is `CHOICE` must supply a non-null
    `choice_group` and a non-null `selection_mode`", enforced with
    "`ERR_CHOICE_GROUP_INCONSISTENT` (HTTP 400) as the single rejection".

    Design: Corner/validations/choice_group_metadata_and_base_component_requirements
    """
    env, recipe_id = _kids_box_draft_recipe(api)

    validate_error(
        env.api.add_recipe_component(
            recipe_id, _apple_slices(choice_group=OMIT), env.submitter
        ),
        ERR_CHOICE_GROUP_INCONSISTENT,
        400,
    )
    validate_error(
        env.api.add_recipe_component(
            recipe_id, _apple_slices(selection_mode=OMIT), env.submitter
        ),
        ERR_CHOICE_GROUP_INCONSISTENT,
        400,
    )
    assert env.read_recipe(recipe_id)["component_count"] == 0


def test_a_base_component_must_leave_all_three_group_fields_null(api):
    """PRD §3.3: "a component whose `role` is `BASE` must leave all three of
    `choice_group`, `selection_mode` and `selection_limit` null".

    Design: Corner/validations/choice_group_metadata_and_base_component_requirements
    """
    env, recipe_id = _kids_box_draft_recipe(api)

    validate_error(
        env.api.add_recipe_component(
            recipe_id,
            component_payload(
                "Cheeseburger patty",
                role=ROLE_BASE,
                grams=110,
                calories_per_100g=250,
                sodium_mg_per_100g=400,
                choice_group=SIDE_GROUP,
                selection_mode=SELECTION_EXACTLY_ONE,
            ),
            env.submitter,
        ),
        ERR_CHOICE_GROUP_INCONSISTENT,
        400,
    )
    assert env.read_recipe(recipe_id)["component_count"] == 0


def test_up_to_n_demands_a_limit_and_exactly_one_forbids_one(api):
    """PRD §3.3: "`selection_mode` of `UP_TO_N` requires a `selection_limit` of
    at least 1; `selection_mode` of `EXACTLY_ONE` or `UNLIMITED` forbids
    `selection_limit` entirely".

    Design: Corner/validations/choice_group_metadata_and_base_component_requirements
    """
    env, recipe_id = _kids_box_draft_recipe(api)

    validate_error(
        env.api.add_recipe_component(
            recipe_id,
            _apple_slices(selection_mode=SELECTION_UP_TO_N, selection_limit=OMIT),
            env.submitter,
        ),
        ERR_CHOICE_GROUP_INCONSISTENT,
        400,
    )
    validate_error(
        env.api.add_recipe_component(
            recipe_id,
            _apple_slices(selection_mode=SELECTION_EXACTLY_ONE, selection_limit=2),
            env.submitter,
        ),
        ERR_CHOICE_GROUP_INCONSISTENT,
        400,
    )
    assert env.read_recipe(recipe_id)["component_count"] == 0


def test_the_first_member_of_a_group_fixes_the_mode_for_the_next(api):
    """PRD §3.3: "every component sharing one `choice_group` must declare the
    identical `selection_mode` and the identical `selection_limit` as the
    components already stored in that group. That last clause makes the check
    contextual — the same payload is valid against an empty recipe and invalid
    against a recipe whose group already declared a different mode."

    Design: Corner/validations/choice_group_metadata_and_base_component_requirements
    """
    env, recipe_id = _kids_box_draft_recipe(api)

    accepted = validate_unpaginated(
        env.api.add_recipe_component(recipe_id, _apple_slices(), env.submitter), 201
    )
    assert accepted["role"] == ROLE_CHOICE
    assert accepted["choice_group"] == SIDE_GROUP
    assert accepted["selection_mode"] == SELECTION_EXACTLY_ONE
    assert accepted["selection_limit"] is None
    assert_numeric_equals(
        accepted["component_calories"], "48.00", "component_calories"
    )

    validate_error(
        env.api.add_recipe_component(
            recipe_id,
            component_payload(
                "Curly fries",
                role=ROLE_CHOICE,
                grams=90,
                calories_per_100g=320,
                sodium_mg_per_100g=280,
                choice_group=SIDE_GROUP,
                selection_mode=SELECTION_UNLIMITED,
            ),
            env.submitter,
        ),
        ERR_CHOICE_GROUP_INCONSISTENT,
        400,
    )

    recipe = env.read_recipe(recipe_id)
    assert recipe["component_count"] == 1
    assert_numeric_equals(
        recipe["computed_base_calories"], "0", "computed_base_calories"
    )


def test_analysis_submission_refuses_a_recipe_with_no_base_component(api):
    """PRD §3.4: "It must hold at least one component whose `role` is `BASE`, or
    the submission is refused with `ERR_RECIPE_HAS_NO_BASE_COMPONENT` — a recipe
    with no base component has no computable base calorie figure." PRD §3.3:
    "`computed_base_calories` is the sum of `component_calories` over the
    recipe's components whose `role` is `BASE`, held at two decimal places
    rounded half up."

    Design: Corner/validations/choice_group_metadata_and_base_component_requirements
    """
    env, recipe_id = _kids_box_draft_recipe(api)
    validate_unpaginated(
        env.api.add_recipe_component(recipe_id, _apple_slices(), env.submitter), 201
    )

    validate_error(
        env.api.submit_for_analysis(
            recipe_id, submit_for_analysis_payload(), env.submitter
        ),
        ERR_RECIPE_HAS_NO_BASE_COMPONENT,
        409,
    )

    recipe = env.read_recipe(recipe_id)
    assert recipe["status"] == RECIPE_DRAFT
    _rows, meta = validate_paginated(
        env.api.list_recipe_nutrition_analyses(recipe_id, env.submitter)
    )
    assert meta["total_count"] == 0, "a refused submission creates no analysis"


# ---------------------------------------------------------------------------
# Rung 29: the sodium icon exactly at the threshold
# ---------------------------------------------------------------------------
def _bowl_component(name: str, sodium_mg_per_100g: Any) -> Dict[str, Any]:
    """One BASE component that declares 100 Cal and the sodium figure asked for."""
    return component_payload(
        name,
        role=ROLE_BASE,
        grams=100,
        calories_per_100g=100,
        sodium_mg_per_100g=sodium_mg_per_100g,
        allergen_group=ALLERGEN_SOY,
        cross_contact_risk=CROSS_CONTACT_NONE,
    )


def _threshold_authority_with_two_bowls(api: ApiClient) -> Tuple[Env, str, str]:
    """A SODIUM_WARNING authority holding one bowl at 800 mg and one at 790 mg."""
    env = seed_registry(
        api,
        code="CA-SOD",
        preemption_mode=PREEMPTION_PREEMPTED,
        extra_requirement=EXTRA_REQUIREMENT_SODIUM_WARNING,
        enforcement_tier=TIER_FEDERAL_ALIGNED,
        sodium_warning_threshold_mg=SODIUM_THRESHOLD_MG,
        required_succinct_statement_variant=STATEMENT_FEDERAL_DEFAULT,
    )
    on_threshold = make_menu_item(env, name="Salt Bowl")
    certify_recipe_version(
        env, on_threshold["id"], [_bowl_component("Brined rice", 800)]
    )
    below = make_menu_item(env, name="Mild Bowl")
    certify_recipe_version(env, below["id"], [_bowl_component("Steamed rice", 790)])
    draft_and_publish_packet(env)
    return env, on_threshold["id"], below["id"]


def test_the_authority_threshold_and_the_two_declared_sodium_figures(api):
    """PRD §3.1: "`sodium_warning_threshold_mg` is the declared-sodium level at
    or above which a printed line must carry the sodium warning icon", and
    "`reprint_grace_days` is 30 when `extra_requirement` is `NONE` and 14 for
    every other value". PRD §2.7: "a total above 140 milligrams declares as the
    total divided by 10, rounded half up, then multiplied by 10."

    Design: Corner/validations/sodium_icon_required_exactly_at_the_jurisdiction_threshold
    """
    env, on_threshold_id, below_id = _threshold_authority_with_two_bowls(api)

    jurisdiction = env.read_jurisdiction()
    assert jurisdiction["sodium_warning_threshold_mg"] == SODIUM_THRESHOLD_MG
    assert jurisdiction["reprint_grace_days"] == GRACE_DAYS_WITH_EXTRA_REQUIREMENT

    assert env.read_item(on_threshold_id)["declared_sodium_mg"] == 800
    assert env.read_item(below_id)["declared_sodium_mg"] == 790


def test_a_line_exactly_on_the_threshold_must_carry_the_icon(api):
    """PRD §3.7: "every line whose item's `declared_sodium_mg` is at or above
    that authority's `sodium_warning_threshold_mg` must carry
    `sodium_warning_icon` true, else `ERR_SODIUM_WARNING_ICON_REQUIRED`" — and
    the same sentence settles the boundary, because "exactly at the threshold
    the icon" is required rather than optional.

    Design: Corner/validations/sodium_icon_required_exactly_at_the_jurisdiction_threshold
    """
    env, on_threshold_id, below_id = _threshold_authority_with_two_bowls(api)
    board = create_board(env, board_type=BOARD_PRIMARY_MENU_BOARD)
    add_listing(env, board.board_id, on_threshold_id, sodium_warning_icon=False)
    add_listing(env, board.board_id, below_id, sodium_warning_icon=False)

    validate_error(
        env.api.publish_menu_board(
            board.board_id, board_publish_payload(), env.publisher
        ),
        ERR_SODIUM_WARNING_ICON_REQUIRED,
        409,
    )

    assert_board_state(
        env.read_board(board.board_id),
        publication_status=PUBLICATION_DRAFT,
        listing_count=2,
    )


def test_the_line_below_the_threshold_may_go_live_without_the_icon(api):
    """PRD §3.7: the icon check is per line, so a board whose only at-or-above
    line carries the icon satisfies it. PRD §3.3: `display_calorie_text` is
    "the item's `declared_calorie_min` followed by a space and the word `Cal`
    when `declared_calorie_min` and `declared_calorie_max` are equal".

    Design: Corner/validations/sodium_icon_required_exactly_at_the_jurisdiction_threshold
    """
    env, on_threshold_id, below_id = _threshold_authority_with_two_bowls(api)
    board = create_board(env, board_type=BOARD_DRIVE_THRU_BOARD)
    add_listing(env, board.board_id, on_threshold_id, sodium_warning_icon=True)
    add_listing(env, board.board_id, below_id, sodium_warning_icon=False)

    published = validate_unpaginated(
        env.api.publish_menu_board(
            board.board_id, board_publish_payload(), env.publisher
        )
    )
    assert published["publication_status"] == PUBLICATION_PUBLISHED

    rows, meta = validate_paginated(
        env.api.list_menu_board_listings(board.board_id, env.publisher)
    )
    assert meta["total_count"] == 2
    for row in rows:
        assert row["display_calorie_text"] == expected_display_calorie_text(100, 100)


# ---------------------------------------------------------------------------
# Rungs 26 and 27: the matrix is asked about before the statement is
# ---------------------------------------------------------------------------
def _brand_with_one_certified_and_one_bare_item(api: ApiClient) -> Tuple[Env, str]:
    """Two non-exempt items, one certified with a shared-equipment component."""
    env = seed_registry(api)
    slaw = make_menu_item(env, name="Almond Slaw")
    certify_recipe_version(
        env,
        slaw["id"],
        [
            component_payload(
                "Almond dressing",
                role=ROLE_BASE,
                grams=60,
                calories_per_100g=180,
                sodium_mg_per_100g=210,
                allergen_group=ALLERGEN_TREE_NUT,
                cross_contact_risk=CROSS_CONTACT_SHARED_EQUIPMENT,
            )
        ],
    )
    make_menu_item(env, name="Grill Sandwich")
    packet = draft_packet(
        env,
        cross_contact_statement="",
        written_info_channels=[CHANNEL_IN_STORE_BINDER],
    )
    return env, packet["id"]


def test_a_draft_counts_only_the_items_that_are_actually_certified(api):
    """PRD §3.5: "A brand with four non-exempt items and three certifications
    has an incomplete matrix, and so does a brand with no non-exempt items at
    all." And "`cross_contact_statement_required` is true when any component of
    any `APPROVED` recipe of any non-exempt item of the brand has a
    `cross_contact_risk` other than `NONE`."

    Design: Corner/validations/packet_publish_reports_the_incomplete_matrix_before_the_missing_statement
    """
    env, packet_id = _brand_with_one_certified_and_one_bare_item(api)

    packet = env.read_packet(packet_id)
    assert packet["covered_item_count"] == 1
    assert packet["allergen_matrix_complete"] is False
    assert packet["cross_contact_statement_required"] is True
    assert_brand_counters(env.read_brand(), standard_item_count=2)


def test_publication_reports_the_matrix_and_not_the_missing_statement(api):
    """PRD §2.6 rung 26: "The packet's stored `allergen_matrix_complete` is
    true, else `ERR_ALLERGEN_MATRIX_INCOMPLETE`. Applies to packet publication
    and board publication." Rung 27 sits below it: "`cross_contact_statement`
    is non-empty whenever the packet's `cross_contact_statement_required` is
    true, else `ERR_CROSS_CONTACT_STATEMENT_REQUIRED`. Applies to packet
    publication." Both are unmet here, so the higher rung answers.

    Design: Corner/validations/packet_publish_reports_the_incomplete_matrix_before_the_missing_statement
    """
    env, packet_id = _brand_with_one_certified_and_one_bare_item(api)

    validate_error(
        env.api.publish_disclosure_packet(packet_id, env.officer),
        ERR_ALLERGEN_MATRIX_INCOMPLETE,
        409,
    )

    packet = env.read_packet(packet_id)
    assert packet["status"] == PACKET_DRAFT
    assert packet["published_at"] is None
    assert_brand_counters(env.read_brand(), has_published_disclosure_packet=False)


# ---------------------------------------------------------------------------
# Rung 27: the statement the fryer makes mandatory
# ---------------------------------------------------------------------------
def _brand_with_one_shared_fryer_item(api: ApiClient) -> Env:
    """A single non-exempt item, certified, whose component shares a fryer."""
    env = seed_registry(api)
    basket = make_menu_item(env, name="Fried Basket")
    certify_recipe_version(
        env,
        basket["id"],
        [
            component_payload(
                "Beer-battered cod",
                role=ROLE_BASE,
                grams=140,
                calories_per_100g=230,
                sodium_mg_per_100g=310,
                allergen_group=ALLERGEN_CRUSTACEAN_SHELLFISH,
                cross_contact_risk=CROSS_CONTACT_SHARED_FRYER,
            )
        ],
    )
    return env


def test_an_empty_statement_cannot_go_live_once_a_fryer_is_shared(api):
    """PRD §3.5: "It requires `cross_contact_statement` to be non-empty whenever
    `cross_contact_statement_required` is true, else
    `ERR_CROSS_CONTACT_STATEMENT_REQUIRED` — a conditional requirement that
    simply does not apply to a brand whose components are all free of
    shared-equipment exposure." The matrix is complete here, so rung 26 passes
    and rung 27 is what answers.

    Design: Corner/validations/packet_publish_requires_a_cross_contact_statement_once_a_risk_exists
    """
    env = _brand_with_one_shared_fryer_item(api)
    silent = draft_packet(
        env,
        cross_contact_statement="",
        written_info_channels=[CHANNEL_IN_STORE_BINDER],
    )
    assert silent["allergen_matrix_complete"] is True
    assert silent["covered_item_count"] == 1
    assert silent["cross_contact_statement_required"] is True

    validate_error(
        env.api.publish_disclosure_packet(silent["id"], env.officer),
        ERR_CROSS_CONTACT_STATEMENT_REQUIRED,
        409,
    )
    assert env.read_packet(silent["id"])["status"] == PACKET_DRAFT


def test_the_second_draft_carries_the_wording_and_goes_live(api):
    """PRD §3.5: "The new packet takes `status` `DRAFT`, `published_at` null,
    and `packet_version` set to 1 for the brand's first packet or to the brand's
    highest existing `packet_version` plus 1 thereafter." On publication, "the
    packet moves from `DRAFT` to `PUBLISHED`, `published_at` is stamped from the
    logical clock, `Brand.has_published_disclosure_packet` becomes true".

    Design: Corner/validations/packet_publish_requires_a_cross_contact_statement_once_a_risk_exists
    """
    env = _brand_with_one_shared_fryer_item(api)
    silent = draft_packet(
        env,
        cross_contact_statement="",
        written_info_channels=[CHANNEL_IN_STORE_BINDER],
    )
    spoken = draft_packet(
        env,
        cross_contact_statement=CROSS_CONTACT_WORDING,
        written_info_channels=[CHANNEL_IN_STORE_BINDER, CHANNEL_QR_HANDOUT],
    )
    assert spoken["packet_version"] == 2

    published = validate_unpaginated(
        env.api.publish_disclosure_packet(spoken["id"], env.officer)
    )
    assert published["status"] == PACKET_PUBLISHED
    assert_instant_equals(published["published_at"], CLOCK_EPOCH_COMPACT)

    assert env.read_packet(silent["id"])["status"] == PACKET_DRAFT
    assert_brand_counters(env.read_brand(), has_published_disclosure_packet=True)


# ---------------------------------------------------------------------------
# Rung 31: the same date-pair rule on three different endpoints
# ---------------------------------------------------------------------------
def _temporary_item_and_a_review_under_way(api: ApiClient) -> Tuple[Env, str, str]:
    """A TEMPORARY item, plus one variance request already in UNDER_REVIEW."""
    env = seed_registry(
        api,
        code="NY-VAR",
        name="New York",
        preemption_mode=PREEMPTION_VARIANCE_ALLOWED,
        unit_count=1,
    )
    item = make_menu_item(
        env,
        name="Pumpkin Spice Shake",
        item_class=ITEM_CLASS_TEMPORARY,
        first_offered_on="2026-03-01",
    )
    variance = file_variance(
        env,
        REQUIREMENT_WRITTEN_INFO_FORMAT,
        requested_start_date="2026-09-01",
        requested_end_date="2026-09-30",
        justification="Binder reprint pending",
    )
    decide_variance(env, variance["id"], VARIANCE_DECISION_OPEN_REVIEW)
    return env, item["id"], variance["id"]


def test_an_offer_window_that_ends_before_it_starts_is_refused(api):
    """PRD §3.2: "A window whose `start_date` is after its `end_date` is refused
    with `ERR_INVALID_DATE_RANGE`". A single-day window is legitimate, and PRD
    §3.2 counts it as one day: "`cumulative_offered_days` is then the sum, over
    the merged spans, of the number of whole calendar days each covers counting
    both endpoints."

    Design: Corner/validations/date_pairs_are_rejected_on_every_endpoint_that_accepts_one
    """
    env, item_id, _variance_id = _temporary_item_and_a_review_under_way(api)

    validate_error(
        env.api.append_offer_window(
            item_id,
            offer_window_payload(start_date="2026-05-10", end_date="2026-05-01"),
            env.officer,
        ),
        ERR_INVALID_DATE_RANGE,
        400,
    )

    item = validate_unpaginated(
        env.api.append_offer_window(
            item_id,
            offer_window_payload(start_date="2026-05-01", end_date="2026-05-01"),
            env.officer,
        )
    )
    assert item["cumulative_offered_days"] == 1
    assert len(item["offer_windows"]) == 1, "only the accepted window was appended"


def test_a_variance_filing_that_ends_before_it_starts_is_refused(api):
    """PRD §3.8: "The requested end may not precede the requested start, on pain
    of `ERR_INVALID_DATE_RANGE`." PRD §2.6 rung 31: "On every supplied date or
    instant pair the start is not after the end, else `ERR_INVALID_DATE_RANGE`.
    Applies to offer-window append, variance filing, the variance decision, and
    board publication when an end instant is supplied."

    Design: Corner/validations/date_pairs_are_rejected_on_every_endpoint_that_accepts_one
    """
    env, _item_id, _variance_id = _temporary_item_and_a_review_under_way(api)

    validate_error(
        env.api.create_variance_request(
            variance_request_payload(
                brand_id=env.brand_id,
                jurisdiction_id=env.jurisdiction_id,
                requirement_code=REQUIREMENT_SUCCINCT_STATEMENT,
                justification="Signage vendor slipped a quarter",
                requested_start_date="2026-11-30",
                requested_end_date="2026-11-01",
            ),
            env.officer,
        ),
        ERR_INVALID_DATE_RANGE,
        400,
    )

    _rows, meta = validate_paginated(
        env.api.list_brand_variance_requests(env.brand_id, env.officer)
    )
    assert meta["total_count"] == 1, "the refused filing left no request behind"


def test_a_grant_whose_effective_window_is_inverted_is_refused(api):
    """PRD §3.8: "The granted window is written from `effective_start_date` and
    `effective_end_date` in the decision payload, each defaulting to the
    corresponding `requested_start_date` or `requested_end_date` when omitted,
    and the resulting `effective_start_date` may not fall after the resulting
    `effective_end_date`."

    Design: Corner/validations/date_pairs_are_rejected_on_every_endpoint_that_accepts_one
    """
    env, _item_id, variance_id = _temporary_item_and_a_review_under_way(api)

    validate_error(
        env.api.decide_variance_request(
            variance_id,
            variance_decision_payload(
                decision=VARIANCE_DECISION_GRANTED,
                decision_note="Window transcribed backwards",
                effective_start_date="2026-09-30",
                effective_end_date="2026-09-01",
            ),
            env.regulator,
        ),
        ERR_INVALID_DATE_RANGE,
        400,
    )

    variance = env.read_variance(variance_id)
    assert variance["status"] == VARIANCE_UNDER_REVIEW
    assert_fields_are_none(
        variance, ["effective_start_date", "effective_end_date"], "VarianceRequest"
    )


# ---------------------------------------------------------------------------
# Rung 33: a preempted authority may review and deny, but never grant
# ---------------------------------------------------------------------------
def _preempted_authority_with_a_filing(api: ApiClient) -> Tuple[Env, str]:
    """A PREEMPTED authority holding one SUBMITTED variance request."""
    env = seed_registry(
        api,
        code="ID-MIN",
        name="Idaho",
        preemption_mode=PREEMPTION_PREEMPTED,
        unit_count=1,
    )
    variance = validate_unpaginated(
        env.api.create_variance_request(
            variance_request_payload(
                brand_id=env.brand_id,
                jurisdiction_id=env.jurisdiction_id,
                requirement_code=REQUIREMENT_SUCCINCT_STATEMENT,
                justification="Signage vendor delay",
                requested_start_date="2026-09-01",
                requested_end_date="2026-09-30",
            ),
            env.officer,
        ),
        201,
    )
    return env, variance["id"]


def test_a_preempted_authority_may_still_open_the_review(api):
    """PRD §3.8: "A filed request starts at `status` `SUBMITTED` with
    `effective_start_date`, `effective_end_date`, `decision_note` and
    `decided_by_user_id` all null." And "`OPEN_REVIEW` is defined only from
    `SUBMITTED` and moves the request to `UNDER_REVIEW`" — a step PRD §3.8
    grants even to a preempted authority.

    Design: Corner/validations/variance_decisions_are_only_available_in_variance_allowed_jurisdictions
    """
    env, variance_id = _preempted_authority_with_a_filing(api)
    assert env.read_variance(variance_id)["status"] == VARIANCE_SUBMITTED

    opened = validate_unpaginated(
        env.api.decide_variance_request(
            variance_id,
            variance_decision_payload(decision=VARIANCE_DECISION_OPEN_REVIEW),
            env.regulator,
        )
    )
    assert opened["status"] == VARIANCE_UNDER_REVIEW


def test_a_preempted_authority_cannot_grant(api):
    """PRD §3.8: "The authority's `preemption_mode` must be `VARIANCE_ALLOWED`;
    an authority whose `preemption_mode` is `PREEMPTED` may open a review and
    may deny, but a grant from it is refused with `ERR_VARIANCE_NOT_ALLOWED`."

    Design: Corner/validations/variance_decisions_are_only_available_in_variance_allowed_jurisdictions
    """
    env, variance_id = _preempted_authority_with_a_filing(api)
    decide_variance(env, variance_id, VARIANCE_DECISION_OPEN_REVIEW)

    validate_error(
        env.api.decide_variance_request(
            variance_id,
            variance_decision_payload(
                decision=VARIANCE_DECISION_GRANTED,
                decision_note="Relief asked for in a preempted state",
            ),
            env.regulator,
        ),
        ERR_VARIANCE_NOT_ALLOWED,
        409,
    )

    variance = env.read_variance(variance_id)
    assert variance["status"] == VARIANCE_UNDER_REVIEW
    assert_fields_are_none(
        variance, ["effective_start_date", "effective_end_date"], "VarianceRequest"
    )


def test_a_preempted_authority_may_deny(api):
    """PRD §3.8: "Where a denial is issued instead, `decision_note` is recorded
    and both effective dates stay null." The same paragraph allows the denial
    itself, since a preempted authority "may open a review and may deny".

    Design: Corner/validations/variance_decisions_are_only_available_in_variance_allowed_jurisdictions
    """
    env, variance_id = _preempted_authority_with_a_filing(api)
    decide_variance(env, variance_id, VARIANCE_DECISION_OPEN_REVIEW)

    denied = validate_unpaginated(
        env.api.decide_variance_request(
            variance_id,
            variance_decision_payload(
                decision=VARIANCE_DECISION_DENIED,
                decision_note="Federal rule stands in this state",
            ),
            env.regulator,
        )
    )
    assert denied["status"] == VARIANCE_DENIED
    assert denied["decision_note"] == "Federal rule stands in this state"
    assert_fields_are_none(
        env.read_variance(variance_id),
        ["effective_start_date", "effective_end_date"],
        "VarianceRequest",
    )


# ---------------------------------------------------------------------------
# Rung 39: offer windows and exemption reviews are class-restricted
# ---------------------------------------------------------------------------
def _three_classes_of_item(api: ApiClient) -> Tuple[Env, str, str, str]:
    """One STANDARD item, one DAILY_SPECIAL and one TEST_MARKET."""
    env = seed_registry(api, unit_count=1)
    standard = make_menu_item(env, name="Grill Sandwich")
    special = make_menu_item(
        env, name="Soup of the Day", item_class=ITEM_CLASS_DAILY_SPECIAL
    )
    test_market = make_menu_item(
        env, name="Test Market Wrap", item_class=ITEM_CLASS_TEST_MARKET
    )
    return env, standard["id"], special["id"], test_market["id"]


def test_a_standard_item_accepts_neither_a_window_nor_a_review(api):
    """PRD §3.2: "Temporary and test-market items are the only items that carry
    offer windows, and the only items whose exemption can be reviewed." An
    append is refused because "an append against an item whose `item_class` is
    anything other than `TEMPORARY` or `TEST_MARKET` is refused with
    `ERR_ITEM_NOT_TEMPORARY`", and the review "is likewise restricted to
    `TEMPORARY` and `TEST_MARKET` items, on pain of `ERR_ITEM_NOT_TEMPORARY`."

    Design: Corner/validations/offer_windows_and_exemption_reviews_only_apply_to_time_limited_classes
    """
    env, standard_id, _special_id, _test_market_id = _three_classes_of_item(api)

    validate_error(
        env.api.append_offer_window(
            standard_id,
            offer_window_payload(start_date="2026-04-01", end_date="2026-04-20"),
            env.officer,
        ),
        ERR_ITEM_NOT_TEMPORARY,
        409,
    )
    validate_error(
        env.api.review_exemption(
            standard_id, exemption_review_payload(review_year=2026), env.officer
        ),
        ERR_ITEM_NOT_TEMPORARY,
        409,
    )

    item = env.read_item(standard_id)
    assert item["offer_windows"] == []
    assert item["cumulative_offered_days"] == 0
    assert_item_declaration(item, labeling_exempt=False)


def test_an_always_exempt_class_is_still_not_reviewable(api):
    """PRD §3.2: "`DAILY_SPECIAL`, `CUSTOM_ORDER` and `SELF_SERVICE` items are
    always exempt, whatever the day count." Exemption by class is not the same
    as reviewability: the review remains restricted to "`TEMPORARY` and
    `TEST_MARKET` items, on pain of `ERR_ITEM_NOT_TEMPORARY`."

    Design: Corner/validations/offer_windows_and_exemption_reviews_only_apply_to_time_limited_classes
    """
    env, _standard_id, special_id, _test_market_id = _three_classes_of_item(api)

    validate_error(
        env.api.review_exemption(
            special_id, exemption_review_payload(review_year=2026), env.officer
        ),
        ERR_ITEM_NOT_TEMPORARY,
        409,
    )

    assert_item_declaration(env.read_item(special_id), labeling_exempt=True)
    assert_brand_counters(env.read_brand(), standard_item_count=1)


def test_a_test_market_item_accepts_the_window_and_counts_its_days(api):
    """PRD §3.2: "An item of any other class gets `labeling_exempt` true and
    `labeling_status` `NOT_REQUIRED`", and an accepted window is counted as
    "the number of whole calendar days each covers counting both endpoints".

    Design: Corner/validations/offer_windows_and_exemption_reviews_only_apply_to_time_limited_classes
    """
    env, _standard_id, _special_id, test_market_id = _three_classes_of_item(api)

    item = validate_unpaginated(
        env.api.append_offer_window(
            test_market_id,
            offer_window_payload(start_date="2026-04-01", end_date="2026-04-20"),
            env.officer,
        )
    )
    assert item["cumulative_offered_days"] == 20
    assert_item_declaration(
        item, labeling_exempt=True, labeling_status=LABELING_NOT_REQUIRED
    )


# ---------------------------------------------------------------------------
# Rung 35: the information round the escalation waits for
# ---------------------------------------------------------------------------
def _open_citation_against_a_covered_brand(
    api: ApiClient, citation_code: str, enforcement_tier: str = TIER_FEDERAL_ALIGNED
) -> Tuple[Env, str]:
    """A covered brand with a published packet, carrying one OPEN citation."""
    env = seed_registry(
        api,
        preemption_mode=PREEMPTION_PREEMPTED,
        enforcement_tier=enforcement_tier,
    )
    certified_sandwich(env)
    draft_and_publish_packet(env)
    action = open_citation(env, citation_code)
    return env, action["id"]


def test_escalation_straight_from_open_is_a_state_refusal(api):
    """PRD §3.9: "`ESCALATE` is also defined only from `RESPONSE_SUBMITTED`", and
    "Every regulator action requested from a state in which it is undefined is
    refused with `ERR_ACTION_STATE_INVALID`." The file is still as opened, which
    PRD §3.9 describes as "`status` `OPEN` with `info_round_count` and
    `response_count` at 0".

    Design: Corner/validations/escalation_needs_an_information_round_after_the_state_check_passes
    """
    env, action_id = _open_citation_against_a_covered_brand(
        api, CITATION_WRITTEN_INFO_UNAVAILABLE
    )

    validate_error(
        env.api.create_regulator_action(
            action_id,
            regulator_action_payload(action_type=ACTION_TYPE_ESCALATE),
            env.regulator,
        ),
        ERR_ACTION_STATE_INVALID,
        409,
    )

    action = env.read_action(action_id)
    assert action["status"] == ACTION_OPEN
    assert action["info_round_count"] == 0
    assert_brand_counters(env.read_brand(), open_enforcement_escalated_count=0)


def test_one_response_is_not_enough_to_escalate(api):
    """PRD §3.9: "A response is defined only from `OPEN` and from
    `INFO_REQUESTED`, and both land in `RESPONSE_SUBMITTED` with `response_count`
    incremented by 1 and `last_response_type` recorded". The state gate now
    passes, so the next gate answers: "The file's `info_round_count` must be at
    least 1 — a regulator must have asked for information at least once before
    escalating — else `ERR_INFO_ROUND_REQUIRED`."

    Design: Corner/validations/escalation_needs_an_information_round_after_the_state_check_passes
    """
    env, action_id = _open_citation_against_a_covered_brand(
        api, CITATION_WRITTEN_INFO_UNAVAILABLE
    )
    answered = file_response(env, action_id, RESPONSE_DISPUTED)
    assert answered["status"] == ACTION_RESPONSE_SUBMITTED
    assert answered["response_count"] == 1
    assert answered["last_response_type"] == RESPONSE_DISPUTED

    validate_error(
        env.api.create_regulator_action(
            action_id,
            regulator_action_payload(action_type=ACTION_TYPE_ESCALATE),
            env.regulator,
        ),
        ERR_INFO_ROUND_REQUIRED,
        409,
    )

    action = env.read_action(action_id)
    assert action["status"] == ACTION_RESPONSE_SUBMITTED
    assert action["info_round_count"] == 0


def test_an_information_round_and_a_second_response_open_the_escalation(api):
    """PRD §3.9: "`REQUEST_INFO` is defined only from `RESPONSE_SUBMITTED`, moves
    the file to `INFO_REQUESTED` and increments `info_round_count` by 1". Once
    the round is on the file, "A successful escalation moves the file to
    `ESCALATED`, increments `Brand.open_enforcement_escalated_count` by 1, and
    recomputes `compliance_posture` to `FROZEN`."

    Design: Corner/validations/escalation_needs_an_information_round_after_the_state_check_passes
    """
    env, action_id = _open_citation_against_a_covered_brand(
        api, CITATION_WRITTEN_INFO_UNAVAILABLE
    )
    file_response(env, action_id, RESPONSE_DISPUTED)

    asked = regulator_action(env, action_id, ACTION_TYPE_REQUEST_INFO)
    assert asked["status"] == ACTION_INFO_REQUESTED
    assert asked["info_round_count"] == 1

    file_response(env, action_id, RESPONSE_DISPUTED)
    escalated = validate_unpaginated(
        env.api.create_regulator_action(
            action_id,
            regulator_action_payload(action_type=ACTION_TYPE_ESCALATE),
            env.regulator,
        )
    )
    assert escalated["status"] == ACTION_ESCALATED
    assert_brand_counters(
        env.read_brand(),
        compliance_posture=POSTURE_FROZEN,
        open_enforcement_escalated_count=1,
    )


# ---------------------------------------------------------------------------
# Rung 10 and the state gate on the money moves
# ---------------------------------------------------------------------------
def _assess_per_establishment(env: Env, action_id: str) -> Dict[str, Any]:
    return validate_unpaginated(
        env.api.create_regulator_action(
            action_id,
            regulator_action_payload(
                action_type=ACTION_TYPE_ASSESS_PENALTY,
                penalty_basis=PENALTY_BASIS_PER_ESTABLISHMENT,
                action_note="One violation unit for the cited store",
            ),
            env.regulator,
        )
    )


def test_neither_money_move_is_defined_before_the_escalation(api):
    """PRD §3.9: "`ASSESS_PENALTY` is defined only from `ESCALATED`", and the two
    compensating moves are defined from `PENALTY_ASSESSED` alone: "Two moves are
    defined from `PENALTY_ASSESSED`." So the state, not the ledger, is what
    refuses here — "Every regulator action requested from a state in which it is
    undefined is refused with `ERR_ACTION_STATE_INVALID`."

    Design: Corner/validations/enforcement_money_actions_are_gated_by_state_not_by_the_ledger
    """
    env, action_id = _open_citation_against_a_covered_brand(
        api, CITATION_SUCCINCT_STATEMENT_MISSING
    )

    validate_error(
        env.api.create_regulator_action(
            action_id,
            regulator_action_payload(
                action_type=ACTION_TYPE_ASSESS_PENALTY,
                penalty_basis=PENALTY_BASIS_PER_ESTABLISHMENT,
            ),
            env.regulator,
        ),
        ERR_ACTION_STATE_INVALID,
        409,
    )

    file_response(env, action_id, RESPONSE_DISPUTED)
    validate_error(
        env.api.create_regulator_action(
            action_id,
            regulator_action_payload(action_type=ACTION_TYPE_RESCIND_PENALTY),
            env.regulator,
        ),
        ERR_ACTION_STATE_INVALID,
        409,
    )

    action = env.read_action(action_id)
    assert action["status"] == ACTION_RESPONSE_SUBMITTED
    assert_fields_are_none(
        action,
        ["penalty_basis", "violation_unit_count", "base_penalty_cents",
         "admin_fee_cents"],
        "EnforcementAction",
    )
    assert_money_cents(action["penalty_total_cents"], 0, "penalty_total_cents")
    assert_money_cents(
        env.read_establishment()["outstanding_penalty_cents"],
        0,
        "outstanding_penalty_cents",
    )


def test_a_disputed_file_cannot_be_closed_as_compliant(api):
    """PRD §3.9: "`CLOSE_COMPLIANT` is defined only from `RESPONSE_SUBMITTED` and
    additionally demands that `last_response_type` be `REPRINT_COMPLETED` or
    `VARIANCE_CITED`; a file whose most recent response was `DISPUTED` cannot be
    closed as compliant and is refused with `ERR_ACTION_STATE_INVALID`."

    Design: Corner/validations/enforcement_money_actions_are_gated_by_state_not_by_the_ledger
    """
    env, action_id = _open_citation_against_a_covered_brand(
        api, CITATION_SUCCINCT_STATEMENT_MISSING
    )
    file_response(env, action_id, RESPONSE_DISPUTED)

    validate_error(
        env.api.create_regulator_action(
            action_id,
            regulator_action_payload(action_type=ACTION_TYPE_CLOSE_COMPLIANT),
            env.regulator,
        ),
        ERR_ACTION_STATE_INVALID,
        409,
    )

    action = env.read_action(action_id)
    assert action["status"] == ACTION_RESPONSE_SUBMITTED
    assert action["closed_at"] is None


def test_the_escalated_file_takes_one_assessment_and_no_second_one(api):
    """PRD §3.9: "Under `PER_ESTABLISHMENT`, `violation_unit_count` is exactly 1
    regardless of how many boards are out of step." The fee rate is read "five
    per cent when `base_penalty_cents` is at or below one hundred thousand
    cents", and "An assessment moves the file to `PENALTY_ASSESSED`, adds
    `penalty_total_cents` to the cited `Establishment.outstanding_penalty_cents`
    and to the citing `Jurisdiction.assessed_penalty_cents_total`".

    Design: Corner/validations/enforcement_money_actions_are_gated_by_state_not_by_the_ledger
    """
    env, action_id = _open_citation_against_a_covered_brand(
        api, CITATION_SUCCINCT_STATEMENT_MISSING
    )
    _drive_to_escalated(env, action_id)

    assessed = _assess_per_establishment(env, action_id)
    assert assessed["status"] == ACTION_PENALTY_ASSESSED
    assert assessed["violation_unit_count"] == 1
    assert BASE_VIOLATION_CENTS <= FEE_TIER_1_CEILING_CENTS
    expected_fee = round_half_up(BASE_VIOLATION_CENTS * FEE_RATE_TIER_1)
    expected_total = BASE_VIOLATION_CENTS + expected_fee
    assert_money_cents(
        assessed["base_penalty_cents"], BASE_VIOLATION_CENTS, "base_penalty_cents"
    )
    assert_money_cents(assessed["admin_fee_cents"], expected_fee, "admin_fee_cents")
    assert_money_cents(
        assessed["penalty_total_cents"], expected_total, "penalty_total_cents"
    )
    assert_money_cents(
        env.read_establishment()["outstanding_penalty_cents"],
        expected_total,
        "outstanding_penalty_cents",
    )
    assert_money_cents(
        env.read_jurisdiction()["assessed_penalty_cents_total"],
        expected_total,
        "assessed_penalty_cents_total",
    )

    validate_error(
        env.api.create_regulator_action(
            action_id,
            regulator_action_payload(
                action_type=ACTION_TYPE_ASSESS_PENALTY,
                penalty_basis=PENALTY_BASIS_PER_ESTABLISHMENT,
            ),
            env.regulator,
        ),
        ERR_ACTION_STATE_INVALID,
        409,
    )
    assert_money_cents(
        env.read_jurisdiction()["assessed_penalty_cents_total"],
        expected_total,
        "assessed_penalty_cents_total",
    )


def test_a_closed_penalty_file_refuses_the_rescission(api):
    """PRD §3.9: "`CLOSE_PENALTY` instead stamps `closed_at` from the logical
    clock and moves the file to `CLOSED_PENALTY`, which is terminal; the assessed
    money stays on both ledgers". PRD §2.6 rung 10: "`CLOSED_COMPLIANT` and
    `CLOSED_PENALTY` enforcement files, and `PERMANENTLY_CLOSED` units accept no
    further transitions."

    Design: Corner/validations/enforcement_money_actions_are_gated_by_state_not_by_the_ledger
    """
    env, action_id = _open_citation_against_a_covered_brand(
        api, CITATION_SUCCINCT_STATEMENT_MISSING
    )
    _drive_to_escalated(env, action_id)
    assessed = _assess_per_establishment(env, action_id)
    expected_total = assessed["penalty_total_cents"]

    closed = regulator_action(env, action_id, ACTION_TYPE_CLOSE_PENALTY)
    assert closed["status"] == ACTION_CLOSED_PENALTY
    assert_instant_equals(closed["closed_at"], CLOCK_EPOCH_COMPACT)

    validate_error(
        env.api.create_regulator_action(
            action_id,
            regulator_action_payload(action_type=ACTION_TYPE_RESCIND_PENALTY),
            env.regulator,
        ),
        ERR_ALREADY_TERMINAL,
        409,
    )

    assert env.read_action(action_id)["status"] == ACTION_CLOSED_PENALTY
    assert_money_cents(
        env.read_establishment()["outstanding_penalty_cents"],
        expected_total,
        "outstanding_penalty_cents",
    )
    assert_money_cents(
        env.read_jurisdiction()["assessed_penalty_cents_total"],
        expected_total,
        "assessed_penalty_cents_total",
    )


# ---------------------------------------------------------------------------
# Rung 38: a reprint needs something stale to reprint
# ---------------------------------------------------------------------------
def _live_board_and_an_empty_one(api: ApiClient) -> Tuple[Env, BoardBundle, str]:
    """One PUBLISHED board with a fresh line, and one DRAFT board with none."""
    env = seed_registry(api)
    item = certified_sandwich(env)
    draft_and_publish_packet(env)
    live = published_board(env, item.item_id)
    empty = create_board(env, board_type=BOARD_DRIVE_THRU_BOARD)
    return env, live, empty.board_id


def test_a_live_board_with_nothing_stale_cannot_be_reprinted(api):
    """PRD §3.7: a reprint "requires the board's `publication_status` to be
    `PUBLISHED` and its `stale_listing_count` to be at least 1; a reprint on a
    board with nothing stale on it is refused with `ERR_NO_STALE_LISTINGS`, which
    is what stops `reprint_count` from being inflated by empty filings."

    Design: Corner/validations/reprint_is_refused_when_nothing_on_the_board_is_stale
    """
    env, live, _empty_board_id = _live_board_and_an_empty_one(api)

    validate_error(
        env.api.reprint_menu_board(live.board_id, reprint_payload(), env.publisher),
        ERR_NO_STALE_LISTINGS,
        409,
    )

    assert_board_state(
        env.read_board(live.board_id),
        publication_status=PUBLICATION_PUBLISHED,
        calorie_compliance_status=COMPLIANCE_CURRENT,
        listing_count=1,
        stale_listing_count=0,
        reprint_count=0,
    )
    assert_brand_counters(
        env.read_brand(),
        open_reprint_obligation_count=0,
        compliance_posture=POSTURE_COMPLIANT,
    )


def test_an_empty_board_cannot_be_reprinted_either(api):
    """PRD §2.6 rung 38: "The board's `stale_listing_count` is at least 1, else
    `ERR_NO_STALE_LISTINGS`. Applies to board reprint." A board that has never
    carried a line has nothing stale on it, so the same rung answers.

    Design: Corner/validations/reprint_is_refused_when_nothing_on_the_board_is_stale
    """
    env, _live, empty_board_id = _live_board_and_an_empty_one(api)

    validate_error(
        env.api.reprint_menu_board(empty_board_id, reprint_payload(), env.publisher),
        ERR_NO_STALE_LISTINGS,
        409,
    )

    assert_board_state(
        env.read_board(empty_board_id),
        listing_count=0,
        stale_listing_count=0,
        reprint_count=0,
    )
