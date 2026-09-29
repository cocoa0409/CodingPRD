"""Declaration arithmetic: summing at full precision and nesting choice groups.

Both scenarios below only need a brand, a unit and a menu item — a recipe may
be opened and certified for a brand that is not a covered establishment,
because only a `FROZEN` posture blocks recipe-version creation.
"""

from test_helpers.assertions import (
    assert_item_declaration,
    assert_numeric_equals,
    assert_two_decimal_places,
    expected_display_calorie_text,
    validate_unpaginated,
)
from test_helpers.constants import (
    ALLERGEN_MILK,
    ALLERGEN_NONE,
    ALLERGEN_SESAME,
    ALLERGEN_WHEAT,
    CROSS_CONTACT_NONE,
    CROSS_CONTACT_SHARED_FRYER,
    CROSS_CONTACT_SHARED_LINE,
    ITEM_CLASS_STANDARD,
    LABELING_DECLARED,
    ROLE_BASE,
    ROLE_CHOICE,
    SELECTION_EXACTLY_ONE,
    SELECTION_UP_TO_N,
    VARIABLE_COMBINATION_MEAL,
    VARIABLE_NONE,
    VARIABLE_TOPPING_BASED,
)
from test_helpers.factories import component_payload
from test_helpers.fixtures import (
    add_listing,
    certify_recipe_version,
    create_board,
    make_menu_item,
    seed_registry,
)

# Two garnishes of 2.60 calories each: the pair sums to 5.20 and declares as 5,
# while declaring each one first would give 0 plus 0.
PARSLEY = component_payload(
    component_name="Chopped parsley",
    role=ROLE_BASE,
    grams=2,
    calories_per_100g=130,
    sodium_mg_per_100g=60,
    added_sugar_g_per_100g=0,
    allergen_group=ALLERGEN_NONE,
    cross_contact_risk=CROSS_CONTACT_NONE,
)
CHIVES = component_payload(
    component_name="Snipped chives",
    role=ROLE_BASE,
    grams=2,
    calories_per_100g=130,
    sodium_mg_per_100g=60,
    added_sugar_g_per_100g=0,
    allergen_group=ALLERGEN_NONE,
    cross_contact_risk=CROSS_CONTACT_NONE,
)


def test_two_sub_threshold_components_sum_before_the_ladder_is_applied(api):
    """PRD §2.7: "sum first at two-decimal precision, then apply the declaration
    ladder once to the total." "Two components of 2.60 calories each sum to
    5.20 and declare as 5; declaring each component first would give 0 plus 0,
    which is 0."

    Design: Difficulty/combinatorial_formula/base_declaration_sums_at_full_precision_then_rounds_once
    """
    env = seed_registry(api, unit_count=1)
    item = make_menu_item(
        env,
        name="Herb Garnish Plate",
        item_class=ITEM_CLASS_STANDARD,
        variable_type=VARIABLE_NONE,
        first_offered_on="2026-02-01",
    )
    result = certify_recipe_version(
        env, item["id"], [PARSLEY, CHIVES], change_note="Garnish plate specified"
    )
    recipe = result["recipe"]

    assert recipe["component_count"] == 2
    assert_numeric_equals(
        recipe["computed_base_calories"], "5.20", "computed_base_calories"
    )
    assert_two_decimal_places(
        recipe["computed_base_calories"], "computed_base_calories"
    )
    assert recipe["computed_declared_min"] == 5
    assert recipe["computed_declared_max"] == 5

    assert_item_declaration(
        env.read_item(item["id"]),
        declared_calorie_min=5,
        declared_calorie_max=5,
        labeling_status=LABELING_DECLARED,
    )


def test_a_sodium_total_below_five_milligrams_declares_as_zero(api):
    """PRD §2.7: "The sodium ladder has the same three-step shape with different
    breakpoints: a total strictly below 5 milligrams declares as 0".

    Design: Difficulty/combinatorial_formula/base_declaration_sums_at_full_precision_then_rounds_once
    """
    env = seed_registry(api, unit_count=1)
    item = make_menu_item(
        env,
        name="Herb Garnish Plate",
        item_class=ITEM_CLASS_STANDARD,
        variable_type=VARIABLE_NONE,
        first_offered_on="2026-02-01",
    )
    result = certify_recipe_version(
        env, item["id"], [PARSLEY, CHIVES], change_note="Garnish plate specified"
    )

    # 1.20 mg plus 1.20 mg is 2.40 mg raw, which is strictly below 5.
    assert result["recipe"]["computed_sodium_mg"] == 0
    assert env.read_item(item["id"])["declared_sodium_mg"] == 0


# ---------------------------------------------------------------------------
# A topping-based burger and a combination meal
# ---------------------------------------------------------------------------
BURGER_COMPONENTS = [
    component_payload(
        component_name="Beef patty",
        role=ROLE_BASE,
        grams=125,
        calories_per_100g=300,
        sodium_mg_per_100g=240,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_NONE,
        cross_contact_risk=CROSS_CONTACT_NONE,
    ),
    component_payload(
        component_name="Sesame bun",
        role=ROLE_BASE,
        grams=56,
        calories_per_100g=350,
        sodium_mg_per_100g=400,
        added_sugar_g_per_100g=5,
        allergen_group=ALLERGEN_SESAME,
        cross_contact_risk=CROSS_CONTACT_NONE,
    ),
    component_payload(
        component_name="Bacon rashers",
        role=ROLE_CHOICE,
        grams=24,
        calories_per_100g=450,
        sodium_mg_per_100g=1100,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_NONE,
        cross_contact_risk=CROSS_CONTACT_SHARED_LINE,
        choice_group="TOPPINGS",
        selection_mode=SELECTION_UP_TO_N,
        selection_limit=2,
    ),
    component_payload(
        component_name="Cheddar slice",
        role=ROLE_CHOICE,
        grams=25,
        calories_per_100g=400,
        sodium_mg_per_100g=650,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_MILK,
        cross_contact_risk=CROSS_CONTACT_NONE,
        choice_group="TOPPINGS",
        selection_mode=SELECTION_UP_TO_N,
        selection_limit=2,
    ),
    component_payload(
        component_name="Avocado slices",
        role=ROLE_CHOICE,
        grams=60,
        calories_per_100g=80,
        sodium_mg_per_100g=10,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_NONE,
        cross_contact_risk=CROSS_CONTACT_NONE,
        choice_group="TOPPINGS",
        selection_mode=SELECTION_UP_TO_N,
        selection_limit=2,
    ),
]

COMBO_COMPONENTS = [
    component_payload(
        component_name="Chicken nuggets",
        role=ROLE_BASE,
        grams=100,
        calories_per_100g=290,
        sodium_mg_per_100g=470,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_WHEAT,
        cross_contact_risk=CROSS_CONTACT_SHARED_FRYER,
    ),
    component_payload(
        component_name="French fries",
        role=ROLE_CHOICE,
        grams=60,
        calories_per_100g=442,
        sodium_mg_per_100g=300,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_NONE,
        cross_contact_risk=CROSS_CONTACT_SHARED_FRYER,
        choice_group="SIDE",
        selection_mode=SELECTION_EXACTLY_ONE,
    ),
    component_payload(
        component_name="Apple slices",
        role=ROLE_CHOICE,
        grams=80,
        calories_per_100g=39,
        sodium_mg_per_100g=1,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_NONE,
        cross_contact_risk=CROSS_CONTACT_NONE,
        choice_group="SIDE",
        selection_mode=SELECTION_EXACTLY_ONE,
    ),
    component_payload(
        component_name="Cola",
        role=ROLE_CHOICE,
        grams=350,
        calories_per_100g=41,
        sodium_mg_per_100g=3,
        added_sugar_g_per_100g=10,
        allergen_group=ALLERGEN_NONE,
        cross_contact_risk=CROSS_CONTACT_NONE,
        choice_group="DRINK",
        selection_mode=SELECTION_EXACTLY_ONE,
    ),
    component_payload(
        component_name="Whole milk",
        role=ROLE_CHOICE,
        grams=240,
        calories_per_100g=41.30,
        sodium_mg_per_100g=44,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_MILK,
        cross_contact_risk=CROSS_CONTACT_NONE,
        choice_group="DRINK",
        selection_mode=SELECTION_EXACTLY_ONE,
    ),
    component_payload(
        component_name="Bottled water",
        role=ROLE_CHOICE,
        grams=250,
        calories_per_100g=0,
        sodium_mg_per_100g=0,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_NONE,
        cross_contact_risk=CROSS_CONTACT_NONE,
        choice_group="DRINK",
        selection_mode=SELECTION_EXACTLY_ONE,
    ),
]


def test_up_to_n_group_takes_zero_as_its_minimum_and_its_two_largest_as_maximum(api):
    """PRD §3.3: "A group whose `selection_mode` is `UP_TO_N` contributes a
    minimum of 0 — the guest may take nothing — and as its maximum the sum of
    the `selection_limit` largest `component_calories` in the group, or the sum
    of all of its members when the group holds fewer members than
    `selection_limit`."

    Design: Difficulty/combinatorial_formula/variable_range_nested_min_max_over_choice_groups
    """
    env = seed_registry(api, unit_count=1)
    item = make_menu_item(
        env,
        name="Signature Burger",
        item_class=ITEM_CLASS_STANDARD,
        variable_type=VARIABLE_TOPPING_BASED,
        first_offered_on="2026-01-05",
    )
    recipe = certify_recipe_version(
        env, item["id"], BURGER_COMPONENTS, change_note="Burger with three toppings"
    )["recipe"]

    # 375.00 plus 196.00 of base, and the two largest toppings are 108.00 and
    # 100.00, so the raw range runs 571.00 to 779.00.
    assert_numeric_equals(
        recipe["computed_base_calories"], "571.00", "computed_base_calories"
    )
    assert recipe["computed_declared_min"] == 570
    assert recipe["computed_declared_max"] == 780
    assert recipe["computed_sodium_mg"] == 520


def test_exactly_one_groups_each_push_their_cheapest_member_into_the_minimum(api):
    """PRD §3.3: "A group whose `selection_mode` is `EXACTLY_ONE` contributes, as
    its minimum, the smallest `component_calories` among its members, and as
    its maximum, the largest." "The raw minimum is `computed_base_calories`
    plus the sum of every group's minimum; the raw maximum is
    `computed_base_calories` plus the sum of every group's maximum."

    Design: Difficulty/combinatorial_formula/variable_range_nested_min_max_over_choice_groups
    """
    env = seed_registry(api, unit_count=1)
    item = make_menu_item(
        env,
        name="Kids Combo Box",
        item_class=ITEM_CLASS_STANDARD,
        variable_type=VARIABLE_COMBINATION_MEAL,
        first_offered_on="2026-01-05",
    )
    recipe = certify_recipe_version(
        env, item["id"], COMBO_COMPONENTS, change_note="Combination meal specified"
    )["recipe"]

    assert recipe["component_count"] == 6
    assert_numeric_equals(
        recipe["computed_base_calories"], "290.00", "computed_base_calories"
    )
    # Base 290.00 plus 31.20 of apple slices plus 0.00 of water is 321.20 raw;
    # base plus 265.20 of fries plus 143.50 of cola is 698.70 raw.
    assert recipe["computed_declared_min"] == 320
    assert recipe["computed_declared_max"] == 700
    # Sodium comes from the base component alone: 470.00 mg raw.
    assert recipe["computed_sodium_mg"] == 470

    assert_item_declaration(
        env.read_item(item["id"]),
        declared_calorie_min=320,
        declared_calorie_max=700,
        declared_sodium_mg=470,
    )


def test_a_variable_item_prints_its_range_as_hyphenated_display_text(api):
    """PRD §3.3: "`display_calorie_text` on a board line is the item's
    `declared_calorie_min` followed by a space and the word `Cal` when
    `declared_calorie_min` and `declared_calorie_max` are equal, and otherwise
    `declared_calorie_min`, a hyphen, `declared_calorie_max`, a space and
    `Cal`".

    Design: Difficulty/combinatorial_formula/variable_range_nested_min_max_over_choice_groups
    """
    env = seed_registry(api, unit_count=1)
    item = make_menu_item(
        env,
        name="Signature Burger",
        item_class=ITEM_CLASS_STANDARD,
        variable_type=VARIABLE_TOPPING_BASED,
        first_offered_on="2026-01-05",
    )
    certify_recipe_version(
        env, item["id"], BURGER_COMPONENTS, change_note="Burger with three toppings"
    )

    board = create_board(env)
    line = add_listing(env, board.board_id, item["id"])

    assert line["display_calorie_text"] == expected_display_calorie_text(570, 780)
    assert line["declared_min_snapshot"] == 570
    assert line["declared_max_snapshot"] == 780

    reread = validate_unpaginated(
        env.api.get_menu_board(board.board_id, env.officer)
    )
    assert reread["listing_count"] == 1
