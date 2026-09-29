"""Arithmetic read at its boundaries: unit counts, ladders, days and money.

Every case here pins a computed figure rather than a transition: the twentieth
unit, the exclusive zero ceilings of the two declaration ladders, the merge that
turns adjacent offer windows into one span, the matrix aggregate, and the fee
tier that a four-board assessment reaches in an enhanced authority.
"""

from typing import Any, Dict, List, Tuple

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_brand_counters,
    assert_instant_equals,
    assert_item_declaration,
    instant_plus_days,
    assert_money_cents,
    assert_numeric_equals,
    assert_ordered_by,
    validate_unpaginated,
)
from test_helpers.constants import (
    ACTION_PENALTY_ASSESSED,
    ACTION_TYPE_ASSESS_PENALTY,
    ACTION_TYPE_ESCALATE,
    ACTION_TYPE_REQUEST_INFO,
    ALLERGEN_EGG,
    ALLERGEN_MILK,
    ALLERGEN_NONE,
    ALLERGEN_TREE_NUT,
    ALLERGEN_WHEAT,
    BASE_VIOLATION_CENTS,
    BASIS_OPERATING_ONLY,
    BOARD_DRIVE_THRU_BOARD,
    BOARD_PRIMARY_MENU_BOARD,
    BOARD_PRINTED_MENU,
    BOARD_THIRD_PARTY_DELIVERY,
    CHANNEL_IN_STORE_BINDER,
    CHANNEL_WEBSITE,
    CITATION_CALORIES_NOT_DECLARED,
    CLOCK_EPOCH_COMPACT,
    COMPLIANCE_REPRINT_REQUIRED,
    COVERAGE_COVERED,
    COVERAGE_NOT_COVERED,
    COVERED_UNIT_THRESHOLD,
    CROSS_CONTACT_NONE,
    CROSS_CONTACT_SHARED_EQUIPMENT,
    CROSS_CONTACT_SHARED_FRYER,
    CROSS_CONTACT_SHARED_LINE,
    DECISION_CERTIFY,
    ENHANCED_MULTIPLIER,
    EXEMPTION_DAY_LIMIT,
    FEE_RATE_TIER_2,
    FEE_RATE_TIER_3,
    FEE_TIER_2_CEILING_CENTS,
    GRACE_DAYS_NO_EXTRA_REQUIREMENT,
    ITEM_CLASS_TEMPORARY,
    LABELING_DECLARATION_PENDING,
    LABELING_NOT_REQUIRED,
    PACKET_DRAFT,
    PENALTY_BASIS_PER_BOARD,
    POSTURE_COMPLIANT,
    POSTURE_EXEMPT,
    PREEMPTION_PREEMPTED,
    PUBLICATION_PUBLISHED,
    REASON_BELOW_UNIT_THRESHOLD,
    REASON_COVERED_BY_UNIT_COUNT,
    REASON_NO_STANDARD_MENU_ITEMS,
    RESPONSE_DISPUTED,
    TIER_ENHANCED,
    TIER_FEDERAL_ALIGNED,
    UNIT_OPERATING,
    UNIT_PERMANENTLY_CLOSED,
    UNIT_PLANNED,
)
from test_helpers.factories import (
    analysis_decision_payload,
    component_payload,
    coverage_determination_payload,
    exemption_review_payload,
    menu_item_payload,
    offer_window_payload,
    regulator_action_payload,
    status_change_payload,
)
from test_helpers.fixtures import (
    Env,
    add_components,
    add_listing,
    certify_recipe_version,
    create_board,
    draft_packet,
    draft_and_publish_packet,
    file_response,
    make_brand,
    make_establishment,
    make_jurisdiction,
    make_menu_item,
    open_citation,
    open_recipe_version,
    publish_board,
    register_unit_batch,
    regulator_action,
    seed_registry,
    set_clock,
    submit_recipe,
)
from test_helpers.test_users import make_brand_officer_headers


def _read_brand(api: ApiClient, brand_id: str, officer: Dict[str, str]) -> Dict[str, Any]:
    return validate_unpaginated(api.get_brand(brand_id, officer))


# ---------------------------------------------------------------------------
# The twenty-unit threshold walked one registration at a time
# ---------------------------------------------------------------------------
def _eighteen_units_and_one_standard_item(
    api: ApiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, str], Dict[str, Any]]:
    """One brand, one non-exempt item, eighteen operating brand-name units."""
    set_clock(api)
    authority = make_jurisdiction(
        api, code="ID-MIN", name="Idaho", preemption_mode=PREEMPTION_PREEMPTED
    )
    brand = make_brand(api)
    officer = make_brand_officer_headers(brand["id"])
    validate_success(
        api.create_menu_item(menu_item_payload(brand_id=brand["id"]), officer), 201
    )
    batch = register_unit_batch(
        api,
        brand_id=brand["id"],
        jurisdiction_id=authority["id"],
        unit_count=18,
        unit_label_prefix="ID-B",
    )
    return authority, brand, officer, batch


def test_the_nineteenth_operating_unit_still_falls_below_the_threshold(api):
    """PRD §3.1: "The response summarises the batch rather than echoing every
    row: `brand_id`, `created_count`, the `unit_status` the batch was created
    in, `first_created_establishment_id`, and the brand's resulting
    `brand_coverage_status` and `brand_counted_unit_count`." "Otherwise
    `coverage_status` is `NOT_COVERED` and `coverage_reason` is
    `BELOW_UNIT_THRESHOLD`."

    Design: Corner/calculations/unit_count_threshold_boundary_at_nineteen_twenty_and_twenty_one
    """
    authority, brand, officer, batch = _eighteen_units_and_one_standard_item(api)

    assert batch["created_count"] == 18
    assert batch["brand_counted_unit_count"] == 18
    assert batch["brand_coverage_status"] == COVERAGE_NOT_COVERED

    make_establishment(
        api,
        brand_id=brand["id"],
        jurisdiction_id=authority["id"],
        unit_label="ID-0019",
    )

    assert_brand_counters(
        _read_brand(api, brand["id"], officer),
        coverage_status=COVERAGE_NOT_COVERED,
        coverage_reason=REASON_BELOW_UNIT_THRESHOLD,
        counted_unit_count=19,
        standard_item_count=1,
        compliance_posture=POSTURE_EXEMPT,
    )


def test_the_twentieth_registration_covers_the_brand_and_the_next_only_counts(api):
    """PRD §3.1: "Otherwise, if `counted_unit_count` is at least twenty,
    `coverage_status` is `COVERED` and `coverage_reason` is
    `COVERED_BY_UNIT_COUNT`." "Registering a single unit re-runs the coverage
    determination on the `OPERATING_ONLY` basis and increments the brand's
    `version` once." PRD §2.9: "`COMPLIANT` — when `coverage_status` is
    `COVERED`."

    Design: Corner/calculations/unit_count_threshold_boundary_at_nineteen_twenty_and_twenty_one
    """
    authority, brand, officer, _batch = _eighteen_units_and_one_standard_item(api)
    for label in ("ID-0019", "ID-0020"):
        make_establishment(
            api,
            brand_id=brand["id"],
            jurisdiction_id=authority["id"],
            unit_label=label,
        )

    assert_brand_counters(
        _read_brand(api, brand["id"], officer),
        coverage_status=COVERAGE_COVERED,
        coverage_reason=REASON_COVERED_BY_UNIT_COUNT,
        counted_unit_count=COVERED_UNIT_THRESHOLD,
        standard_item_count=1,
        compliance_posture=POSTURE_COMPLIANT,
    )

    make_establishment(
        api,
        brand_id=brand["id"],
        jurisdiction_id=authority["id"],
        unit_label="ID-0021",
    )
    assert_brand_counters(
        _read_brand(api, brand["id"], officer),
        coverage_status=COVERAGE_COVERED,
        coverage_reason=REASON_COVERED_BY_UNIT_COUNT,
        counted_unit_count=COVERED_UNIT_THRESHOLD + 1,
        standard_item_count=1,
        compliance_posture=POSTURE_COMPLIANT,
    )


# ---------------------------------------------------------------------------
# Twenty-two rows on file, nineteen of them countable
# ---------------------------------------------------------------------------
def _twenty_one_rows_with_two_uncountable(
    api: ApiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    """Nineteen countable units, one `PLANNED` unit and one franchise unit."""
    set_clock(api)
    authority = make_jurisdiction(
        api, code="ID-MIN", name="Idaho", preemption_mode=PREEMPTION_PREEMPTED
    )
    brand = make_brand(api)
    officer = make_brand_officer_headers(brand["id"])
    validate_success(
        api.create_menu_item(menu_item_payload(brand_id=brand["id"]), officer), 201
    )
    register_unit_batch(
        api,
        brand_id=brand["id"],
        jurisdiction_id=authority["id"],
        unit_count=19,
        unit_label_prefix="ID-B",
    )
    make_establishment(
        api,
        brand_id=brand["id"],
        jurisdiction_id=authority["id"],
        unit_label="ID-PLAN",
        unit_status=UNIT_PLANNED,
    )
    make_establishment(
        api,
        brand_id=brand["id"],
        jurisdiction_id=authority["id"],
        unit_label="ID-FRAN",
        operates_under_brand_name=False,
    )
    return authority, brand, officer


def _and_then_one_unit_closes_for_good(
    api: ApiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, str], Dict[str, Any]]:
    authority, brand, officer = _twenty_one_rows_with_two_uncountable(api)
    closing = make_establishment(
        api,
        brand_id=brand["id"],
        jurisdiction_id=authority["id"],
        unit_label="ID-CLSD",
    )
    validate_unpaginated(
        api.change_establishment_status(
            closing["id"],
            status_change_payload(
                UNIT_PERMANENTLY_CLOSED, effective_note="Lease ended"
            ),
            officer,
        )
    )
    return authority, brand, officer, closing


def test_a_planned_unit_and_a_franchise_unit_never_enter_the_count(api):
    """PRD §3.1: "Under the `OPERATING_ONLY` basis, `counted_unit_count` is the
    number of the brand's units whose `unit_status` is `OPERATING` and whose
    `operates_under_brand_name` is true." "a unit for which it is false never
    counts toward the federal unit threshold under any counting basis."

    Design: Corner/calculations/coverage_counting_excludes_planned_closed_and_non_brand_name_units
    """
    authority, brand, officer = _twenty_one_rows_with_two_uncountable(api)

    assert_brand_counters(
        _read_brand(api, brand["id"], officer),
        coverage_status=COVERAGE_NOT_COVERED,
        coverage_reason=REASON_BELOW_UNIT_THRESHOLD,
        counted_unit_count=19,
        standard_item_count=1,
    )

    make_establishment(
        api,
        brand_id=brand["id"],
        jurisdiction_id=authority["id"],
        unit_label="ID-CLSD",
    )
    assert_brand_counters(
        _read_brand(api, brand["id"], officer),
        coverage_status=COVERAGE_COVERED,
        coverage_reason=REASON_COVERED_BY_UNIT_COUNT,
        counted_unit_count=COVERED_UNIT_THRESHOLD,
    )


def test_a_permanent_closure_takes_the_count_back_below_twenty(api):
    """PRD §3.1: "Units in `PLANNED` or `PERMANENTLY_CLOSED`, and units whose
    `operates_under_brand_name` is false, are excluded under both bases." "An
    explicit determination overwrites the brand's stored `coverage_status`,
    `coverage_reason`, `counted_unit_count` and `standard_item_count` with the
    chosen basis's result, increments the brand's `version`, and reports
    `brand_id`, the `basis` used, `counted_unit_count`, `standard_item_count`,
    `coverage_status`, `coverage_reason` and a `persisted` flag."

    Design: Corner/calculations/coverage_counting_excludes_planned_closed_and_non_brand_name_units
    """
    _authority, brand, officer, _closing = _and_then_one_unit_closes_for_good(api)

    assert_brand_counters(
        _read_brand(api, brand["id"], officer),
        coverage_status=COVERAGE_NOT_COVERED,
        coverage_reason=REASON_BELOW_UNIT_THRESHOLD,
        counted_unit_count=19,
    )

    determination = validate_unpaginated(
        api.determine_coverage(
            brand["id"],
            coverage_determination_payload(basis=BASIS_OPERATING_ONLY),
            officer,
        )
    )
    assert determination["brand_id"] == brand["id"]
    assert determination["basis"] == BASIS_OPERATING_ONLY
    assert determination["counted_unit_count"] == 19
    assert determination["standard_item_count"] == 1
    assert determination["coverage_status"] == COVERAGE_NOT_COVERED
    assert determination["coverage_reason"] == REASON_BELOW_UNIT_THRESHOLD
    assert determination["persisted"] is True


def test_the_three_excluded_units_are_still_rows_on_the_register(api):
    """PRD §3.1: "Units in `PLANNED` or `PERMANENTLY_CLOSED`, and units whose
    `operates_under_brand_name` is false, are excluded under both bases."

    Design: Corner/calculations/coverage_counting_excludes_planned_closed_and_non_brand_name_units
    """
    _authority, brand, officer, _closing = _and_then_one_unit_closes_for_good(api)

    _rows, meta = validate_paginated(
        api.list_establishments(officer, params={"brand_id": brand["id"], "limit": 100})
    )
    assert meta["total_count"] == 22

    _operating, operating_meta = validate_paginated(
        api.list_establishments(
            officer,
            params={
                "brand_id": brand["id"],
                "unit_status": UNIT_OPERATING,
                "limit": 100,
            },
        )
    )
    assert operating_meta["total_count"] == COVERED_UNIT_THRESHOLD


# ---------------------------------------------------------------------------
# Both declaration ladders, band by band
# ---------------------------------------------------------------------------
def _one_brand_and_no_boards(api: ApiClient) -> Env:
    """A brand whose only interesting property is its declaration arithmetic."""
    return seed_registry(
        api,
        code="ID-MIN",
        name="Idaho",
        preemption_mode=PREEMPTION_PREEMPTED,
        unit_count=1,
        unit_label="ID-0001",
    )


def _hundred_gram_component(
    component_name: str,
    calories_per_100g: Any,
    sodium_mg_per_100g: Any,
    added_sugar_g_per_100g: Any = 0,
    allergen_group: str = ALLERGEN_NONE,
) -> Dict[str, Any]:
    return component_payload(
        component_name,
        grams=100,
        calories_per_100g=calories_per_100g,
        sodium_mg_per_100g=sodium_mg_per_100g,
        added_sugar_g_per_100g=added_sugar_g_per_100g,
        allergen_group=allergen_group,
        cross_contact_risk=CROSS_CONTACT_NONE,
    )


def _certified_single_component_item(
    env: Env,
    name: str,
    component_name: str,
    calories_per_100g: Any,
    sodium_mg_per_100g: Any,
    added_sugar_g_per_100g: Any = 0,
    allergen_group: str = ALLERGEN_NONE,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    item = make_menu_item(env, name=name)
    certified = certify_recipe_version(
        env,
        item["id"],
        [
            _hundred_gram_component(
                component_name,
                calories_per_100g,
                sodium_mg_per_100g,
                added_sugar_g_per_100g=added_sugar_g_per_100g,
                allergen_group=allergen_group,
            )
        ],
        decision_note="Values verified",
    )
    return item, certified


def test_a_total_below_five_declares_as_zero_on_both_ladders(api):
    """PRD §2.7: "a total strictly below 5 calories declares as 0". "a total
    strictly below 5 milligrams declares as 0".

    Design: Corner/calculations/calorie_and_sodium_declaration_bands_at_both_rounding_ceilings
    """
    env = _one_brand_and_no_boards(api)
    item, certified = _certified_single_component_item(
        env, "Item A Broth", "Clear broth", 4.9, 4.9
    )

    recipe = certified["recipe"]
    assert_numeric_equals(
        recipe["computed_base_calories"], "4.90", "computed_base_calories"
    )
    assert recipe["computed_declared_min"] == 0
    assert recipe["computed_declared_max"] == 0
    assert recipe["computed_sodium_mg"] == 0

    assert_item_declaration(
        env.read_item(item["id"]),
        declared_calorie_min=0,
        declared_calorie_max=0,
        declared_sodium_mg=0,
    )


def test_both_nearest_five_ceilings_include_their_own_endpoint(api):
    """PRD §2.7: "a total from 5 up to and including 50 calories declares as the
    total divided by 5, rounded half up to a whole number, then multiplied by
    5". "a total from 5 up to and including 140 milligrams declares as the total
    divided by 5, rounded half up, then multiplied by 5".

    Design: Corner/calculations/calorie_and_sodium_declaration_bands_at_both_rounding_ceilings
    """
    env = _one_brand_and_no_boards(api)
    item, certified = _certified_single_component_item(
        env, "Item B Side Salad", "Dressed greens", 45, 140
    )

    recipe = certified["recipe"]
    assert_numeric_equals(
        recipe["computed_base_calories"], "45.00", "computed_base_calories"
    )
    assert recipe["computed_declared_max"] == 45
    assert recipe["computed_sodium_mg"] == 140

    assert_item_declaration(
        env.read_item(item["id"]),
        declared_calorie_max=45,
        declared_sodium_mg=140,
    )


def test_above_the_ceilings_the_nearest_ten_band_rounds_its_tie_upwards(api):
    """PRD §2.7: "a total above 50 calories declares as the total divided by 10,
    rounded half up to a whole number, then multiplied by 10". "a total above
    140 milligrams declares as the total divided by 10, rounded half up, then
    multiplied by 10".

    Design: Corner/calculations/calorie_and_sodium_declaration_bands_at_both_rounding_ceilings
    """
    env = _one_brand_and_no_boards(api)
    item = make_menu_item(env, name="Item C Slaw Cup")
    recipe = open_recipe_version(env, item["id"])
    components = add_components(
        env,
        recipe["id"],
        [
            _hundred_gram_component(
                "Creamy slaw", 55, 145,
                added_sugar_g_per_100g=2,
                allergen_group=ALLERGEN_EGG,
            )
        ],
    )
    analysis = submit_recipe(env, recipe["id"])

    decided = validate_unpaginated(
        env.api.decide_analysis(
            analysis["id"],
            analysis_decision_payload(
                decision=DECISION_CERTIFY, decision_note="Values verified"
            ),
            env.certifier,
        )
    )
    assert decided["declared_calorie_min"] == 60
    assert decided["declared_calorie_max"] == 60
    assert decided["declared_sodium_mg"] == 150

    stored = env.read_recipe(recipe["id"])
    assert_numeric_equals(
        stored["computed_base_calories"], "55.00", "computed_base_calories"
    )
    assert stored["computed_declared_max"] == 60
    assert stored["computed_sodium_mg"] == 150

    assert_numeric_equals(
        components[0]["component_calories"], "55.00", "component_calories"
    )
    assert_numeric_equals(
        components[0]["component_sodium_mg"], "145.00", "component_sodium_mg"
    )


# ---------------------------------------------------------------------------
# Offer windows: what merges, what stays apart, and where sixty days bite
# ---------------------------------------------------------------------------
DECEMBER_2025 = ("2025-12-01", "2025-12-31")
JANUARY_RUN = ("2026-01-01", "2026-01-30")
ADJACENT_RUN = ("2026-01-31", "2026-02-14")
DISJOINT_RUN = ("2026-03-01", "2026-03-14")
ONE_MORE_DAY = ("2026-04-01", "2026-04-01")


def _append_window(env: Env, menu_item_id: str, window: Tuple[str, str]) -> Dict[str, Any]:
    return validate_unpaginated(
        env.api.append_offer_window(
            menu_item_id,
            offer_window_payload(start_date=window[0], end_date=window[1]),
            env.officer,
        )
    )


def _review_year(env: Env, menu_item_id: str, review_year: int) -> Dict[str, Any]:
    return validate_unpaginated(
        env.api.review_exemption(
            menu_item_id,
            exemption_review_payload(review_year=review_year),
            env.officer,
        )
    )


def _temporary_item_with_four_windows(api: ApiClient) -> Tuple[Env, Dict[str, Any]]:
    """Twenty operating units and one temporary item carrying four windows."""
    env = seed_registry(
        api,
        code="ID-MIN",
        name="Idaho",
        preemption_mode=PREEMPTION_PREEMPTED,
        unit_count=COVERED_UNIT_THRESHOLD,
        unit_label="ID-0001",
        unit_label_prefix="ID-B",
    )
    item = make_menu_item(
        env,
        name="Pumpkin Spice Shake",
        item_class=ITEM_CLASS_TEMPORARY,
        first_offered_on="2025-12-01",
    )
    for window in (DECEMBER_2025, JANUARY_RUN, ADJACENT_RUN, DISJOINT_RUN):
        _append_window(env, item["id"], window)
    return env, item


def test_adjacent_windows_merge_while_a_two_day_gap_stays_disjoint(api):
    """PRD §3.2: "The adjacency rule is exact — a window that starts on the very
    next day after the previous span ends merges into it, while a window that
    leaves a two-day gap starts a fresh span." "`cumulative_offered_days` is then
    the sum, over the merged spans, of the number of whole calendar days each
    covers counting both endpoints."

    Design: Corner/calculations/temporary_item_offer_windows_merge_then_cross_the_sixty_day_limit
    """
    env, item = _temporary_item_with_four_windows(api)

    # 2026-01-01..2026-01-30 and 2026-01-31..2026-02-14 merge into a 45-day
    # span; 2026-03-01 leaves a two-day gap and adds its own 14 days.
    reviewed = _review_year(env, item["id"], 2026)
    assert reviewed["cumulative_offered_days"] == 59
    assert reviewed["labeling_exempt"] is True
    assert reviewed["labeling_status"] == LABELING_NOT_REQUIRED

    assert_brand_counters(
        env.read_brand(),
        coverage_status=COVERAGE_NOT_COVERED,
        coverage_reason=REASON_NO_STANDARD_MENU_ITEMS,
        standard_item_count=0,
    )


def test_the_sixtieth_offered_day_ends_the_exemption(api):
    """PRD §3.2: "such an item is exempt while `cumulative_offered_days` is
    strictly below sixty days for the reviewed year, and loses its exemption the
    moment the merged total reaches sixty. Sixty days on the nose is not
    exempt." "A flip to false sets it to `DECLARATION_PENDING` when the item has
    no `APPROVED` recipe".

    Design: Corner/calculations/temporary_item_offer_windows_merge_then_cross_the_sixty_day_limit
    """
    env, item = _temporary_item_with_four_windows(api)
    _append_window(env, item["id"], ONE_MORE_DAY)

    reviewed = _review_year(env, item["id"], 2026)
    assert reviewed["cumulative_offered_days"] == EXEMPTION_DAY_LIMIT
    assert reviewed["labeling_exempt"] is False
    assert reviewed["labeling_status"] == LABELING_DECLARATION_PENDING

    assert_brand_counters(
        env.read_brand(),
        coverage_status=COVERAGE_COVERED,
        coverage_reason=REASON_COVERED_BY_UNIT_COUNT,
        counted_unit_count=COVERED_UNIT_THRESHOLD,
        standard_item_count=1,
    )


def test_a_review_of_the_earlier_year_sees_only_that_years_windows(api):
    """PRD §3.2: "The review considers only the entries of `offer_windows` whose
    `start_date` falls in the reviewed year, sorted by `start_date` ascending
    and, where two share a start, by `end_date` ascending." "Entries are never
    removed and never edited."

    Design: Corner/calculations/temporary_item_offer_windows_merge_then_cross_the_sixty_day_limit
    """
    env, item = _temporary_item_with_four_windows(api)
    _append_window(env, item["id"], ONE_MORE_DAY)
    _review_year(env, item["id"], 2026)

    reviewed = _review_year(env, item["id"], 2025)
    assert reviewed["cumulative_offered_days"] == 31
    assert reviewed["labeling_exempt"] is True
    assert reviewed["labeling_status"] == LABELING_NOT_REQUIRED
    assert len(reviewed["offer_windows"]) == 5

    assert_brand_counters(
        env.read_brand(),
        coverage_status=COVERAGE_NOT_COVERED,
        coverage_reason=REASON_NO_STANDARD_MENU_ITEMS,
        standard_item_count=0,
    )


# ---------------------------------------------------------------------------
# The allergen matrix as an aggregate over the brand's covered items
# ---------------------------------------------------------------------------
GRILL_SANDWICH_COMPONENTS: List[Dict[str, Any]] = [
    component_payload(
        "Grilled chicken breast", grams=140, calories_per_100g=140,
        sodium_mg_per_100g=240, added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_NONE,
        cross_contact_risk=CROSS_CONTACT_SHARED_FRYER,
    ),
    component_payload(
        "Brioche bun", grams=60, calories_per_100g=330, sodium_mg_per_100g=148,
        added_sugar_g_per_100g=4, allergen_group=ALLERGEN_WHEAT,
        cross_contact_risk=CROSS_CONTACT_NONE,
    ),
    component_payload(
        "Cheddar slice", grams=20, calories_per_100g=400, sodium_mg_per_100g=620,
        added_sugar_g_per_100g=0, allergen_group=ALLERGEN_MILK,
        cross_contact_risk=CROSS_CONTACT_SHARED_LINE,
    ),
]

ALMOND_SLAW_COMPONENTS: List[Dict[str, Any]] = [
    component_payload(
        "Shredded cabbage", grams=120, calories_per_100g=25, sodium_mg_per_100g=18,
        added_sugar_g_per_100g=0, allergen_group=ALLERGEN_NONE,
        cross_contact_risk=CROSS_CONTACT_NONE,
    ),
    component_payload(
        "Toasted almonds", grams=15, calories_per_100g=600, sodium_mg_per_100g=4,
        added_sugar_g_per_100g=0, allergen_group=ALLERGEN_TREE_NUT,
        cross_contact_risk=CROSS_CONTACT_SHARED_EQUIPMENT,
    ),
    component_payload(
        "Egg dressing", grams=30, calories_per_100g=300, sodium_mg_per_100g=400,
        added_sugar_g_per_100g=3, allergen_group=ALLERGEN_EGG,
        cross_contact_risk=CROSS_CONTACT_NONE,
    ),
]

ALMOND_SLAW = "Almond Slaw"
GRILL_SANDWICH = "Grill Sandwich"


def _covered_brand_with_two_uncertified_items(
    api: ApiClient,
) -> Tuple[Env, Dict[str, Any], Dict[str, Any]]:
    env = seed_registry(
        api,
        code="ID-MIN",
        name="Idaho",
        preemption_mode=PREEMPTION_PREEMPTED,
        unit_count=COVERED_UNIT_THRESHOLD,
        unit_label="ID-0001",
        unit_label_prefix="ID-B",
    )
    grill = make_menu_item(env, name=GRILL_SANDWICH)
    slaw = make_menu_item(env, name=ALMOND_SLAW)
    return env, grill, slaw


def _draft_binder_packet(env: Env, cross_contact_statement: str = "") -> Dict[str, Any]:
    return draft_packet(
        env,
        cross_contact_statement=cross_contact_statement,
        written_info_channels=[CHANNEL_IN_STORE_BINDER],
    )


def test_the_matrix_lists_every_non_exempt_item_before_any_certification(api):
    """PRD §3.5: "The matrix items are the brand's menu items whose
    `labeling_exempt` is false, ordered by `name` ascending." "`covered_item_count`
    is the number of those items that actually have a recipe in `APPROVED` — a
    non-exempt item still waiting on certification is in the matrix's population
    but does not count as covered."

    Design: Corner/calculations/allergen_matrix_is_name_ordered_and_complete_only_when_every_item_is_certified
    """
    env, grill, slaw = _covered_brand_with_two_uncertified_items(api)

    packet = _draft_binder_packet(env)

    assert packet["packet_version"] == 1
    assert packet["covered_item_count"] == 0
    assert packet["allergen_matrix_complete"] is False
    assert packet["cross_contact_statement_required"] is False

    rows = packet["allergen_rows"]
    assert len(rows) == 2
    assert_ordered_by(rows, "item_name")
    assert [row["item_name"] for row in rows] == [ALMOND_SLAW, GRILL_SANDWICH]
    assert [row["menu_item_id"] for row in rows] == [slaw["id"], grill["id"]]
    for row in rows:
        assert row["allergen_groups"] == []
        assert row["cross_contact_groups"] == []


def test_a_matrix_that_trails_the_item_count_stays_incomplete(api):
    """PRD §3.5: "A brand with four non-exempt items and three certifications has
    an incomplete matrix, and so does a brand with no non-exempt items at all."
    "An item's `allergen_groups` is the alphabetically ascending list of distinct
    `allergen_group` values across the components of that item's `APPROVED`
    recipe, with `NONE` excluded; its `cross_contact_groups` is the
    alphabetically ascending list of distinct `allergen_group` values across the
    same components restricted to those whose `cross_contact_risk` is not
    `NONE`, again with `NONE` excluded."

    Design: Corner/calculations/allergen_matrix_is_name_ordered_and_complete_only_when_every_item_is_certified
    """
    env, grill, _slaw = _covered_brand_with_two_uncertified_items(api)
    _draft_binder_packet(env)
    certify_recipe_version(env, grill["id"], GRILL_SANDWICH_COMPONENTS)

    packet = _draft_binder_packet(env)

    assert packet["packet_version"] == 2
    assert packet["covered_item_count"] == 1
    assert packet["allergen_matrix_complete"] is False
    assert packet["cross_contact_statement_required"] is True

    grill_row = packet["allergen_rows"][1]
    assert grill_row["item_name"] == GRILL_SANDWICH
    assert grill_row["allergen_groups"] == [ALLERGEN_MILK, ALLERGEN_WHEAT]
    assert grill_row["cross_contact_groups"] == [ALLERGEN_MILK]

    slaw_row = packet["allergen_rows"][0]
    assert slaw_row["item_name"] == ALMOND_SLAW
    assert slaw_row["allergen_groups"] == []


def test_the_matrix_completes_only_once_the_second_item_is_certified(api):
    """PRD §3.5: "`cross_contact_statement_required` is true when any component of
    any `APPROVED` recipe of any non-exempt item of the brand has a
    `cross_contact_risk` other than `NONE`." "The new packet takes `status`
    `DRAFT`, `published_at` null, and `packet_version` set to 1 for the brand's
    first packet or to the brand's highest existing `packet_version` plus 1
    thereafter."

    Design: Corner/calculations/allergen_matrix_is_name_ordered_and_complete_only_when_every_item_is_certified
    """
    env, grill, slaw = _covered_brand_with_two_uncertified_items(api)
    _draft_binder_packet(env)
    certify_recipe_version(env, grill["id"], GRILL_SANDWICH_COMPONENTS)
    _draft_binder_packet(env)
    certify_recipe_version(env, slaw["id"], ALMOND_SLAW_COMPONENTS)

    packet = draft_packet(
        env,
        cross_contact_statement=(
            "Items may contain traces of tree nuts and milk from shared equipment."
        ),
        written_info_channels=[CHANNEL_IN_STORE_BINDER, CHANNEL_WEBSITE],
    )

    assert packet["packet_version"] == 3
    assert packet["covered_item_count"] == 2
    assert packet["allergen_matrix_complete"] is True
    assert packet["cross_contact_statement_required"] is True

    slaw_row, grill_row = packet["allergen_rows"]
    assert slaw_row["item_name"] == ALMOND_SLAW
    assert slaw_row["allergen_groups"] == [ALLERGEN_EGG, ALLERGEN_TREE_NUT]
    assert slaw_row["cross_contact_groups"] == [ALLERGEN_TREE_NUT]
    assert grill_row["item_name"] == GRILL_SANDWICH
    assert grill_row["allergen_groups"] == [ALLERGEN_MILK, ALLERGEN_WHEAT]
    assert grill_row["cross_contact_groups"] == [ALLERGEN_MILK]

    rows, meta = validate_paginated(
        env.api.list_brand_disclosure_packets(env.brand_id, env.officer)
    )
    assert meta["total_count"] == 3
    for row in rows:
        assert row["status"] == PACKET_DRAFT


# ---------------------------------------------------------------------------
# Money: four board-level violations and the fee tier they reach
# ---------------------------------------------------------------------------
ALL_FOUR_BOARD_TYPES = (
    BOARD_PRIMARY_MENU_BOARD,
    BOARD_DRIVE_THRU_BOARD,
    BOARD_PRINTED_MENU,
    BOARD_THIRD_PARTY_DELIVERY,
)


def _sandwich_at(calories_per_100g: Any) -> List[Dict[str, Any]]:
    return [
        _hundred_gram_component(
            "Sandwich as served", calories_per_100g, 200,
            allergen_group=ALLERGEN_WHEAT,
        )
    ]


def _four_boards_awaiting_a_reprint(
    api: ApiClient, enforcement_tier: str, code: str
) -> Tuple[Env, List[str]]:
    """One unit carrying all four board types, every one of them out of step."""
    env = seed_registry(
        api,
        code=code,
        name="New York",
        preemption_mode=PREEMPTION_PREEMPTED,
        enforcement_tier=enforcement_tier,
        unit_count=COVERED_UNIT_THRESHOLD,
        unit_label="NY-0001",
        unit_label_prefix="NY-B",
    )
    item = make_menu_item(env)
    certify_recipe_version(env, item["id"], _sandwich_at(100))
    draft_and_publish_packet(env)

    board_ids: List[str] = []
    for board_type in ALL_FOUR_BOARD_TYPES:
        board = create_board(env, board_type=board_type)
        add_listing(env, board.board_id, item["id"])
        publish_board(env, board.board_id, effective_from=CLOCK_EPOCH_COMPACT)
        board_ids.append(board.board_id)

    certify_recipe_version(
        env,
        item["id"],
        _sandwich_at(400),
        change_note="Portion doubled",
        decision_note="Reformulated portion certified",
    )
    return env, board_ids


def _escalated_citation(env: Env) -> str:
    action = open_citation(
        env,
        CITATION_CALORIES_NOT_DECLARED,
        inspection_note="Four boards showing superseded calorie figures",
    )
    file_response(
        env, action["id"], RESPONSE_DISPUTED,
        response_note="Boards are within the grace period",
    )
    regulator_action(
        env, action["id"], ACTION_TYPE_REQUEST_INFO,
        action_note="Provide the reprint schedule",
    )
    file_response(
        env, action["id"], RESPONSE_DISPUTED,
        response_note="No reprint schedule available",
    )
    regulator_action(
        env, action["id"], ACTION_TYPE_ESCALATE,
        action_note="No reprint schedule supplied",
    )
    return action["id"]


def _assess_per_board(env: Env, action_id: str) -> Dict[str, Any]:
    return validate_unpaginated(
        env.api.create_regulator_action(
            action_id,
            regulator_action_payload(
                action_type=ACTION_TYPE_ASSESS_PENALTY,
                penalty_basis=PENALTY_BASIS_PER_BOARD,
                action_note="Per-board assessment across four boards",
            ),
            env.regulator,
        )
    )


def test_four_board_violations_in_an_enhanced_authority_reach_the_top_fee_tier(api):
    """PRD §3.9: "Under `PER_BOARD`, `violation_unit_count` is the number of the
    cited establishment's boards whose `publication_status` is `PUBLISHED` and
    whose `calorie_compliance_status` is either `REPRINT_REQUIRED` or `OVERDUE`".
    "The tier multiplier is one and a half when the citing authority's
    `enforcement_tier` is `ENHANCED`". "twelve per cent above that."

    Design: Corner/calculations/penalty_fee_reaches_tier_three_above_the_second_ceiling
    """
    env, _board_ids = _four_boards_awaiting_a_reprint(api, TIER_ENHANCED, "NY-ENH")

    _rows, meta = validate_paginated(
        env.api.list_menu_boards(
            env.officer,
            params={
                "establishment_id": env.establishment_id,
                "calorie_compliance_status": COMPLIANCE_REPRINT_REQUIRED,
            },
        )
    )
    assert meta["total_count"] == 4

    assessed = _assess_per_board(env, _escalated_citation(env))

    assert assessed["status"] == ACTION_PENALTY_ASSESSED
    assert assessed["penalty_basis"] == PENALTY_BASIS_PER_BOARD
    assert assessed["violation_unit_count"] == 4

    # 50000 * 4 * 1.5 == 300000, which is strictly above the second ceiling.
    expected_base = int(BASE_VIOLATION_CENTS * 4 * ENHANCED_MULTIPLIER)
    assert expected_base == 300000
    assert expected_base > FEE_TIER_2_CEILING_CENTS
    expected_fee = int(expected_base * FEE_RATE_TIER_3)
    assert expected_fee == 36000

    assert_money_cents(assessed["base_penalty_cents"], expected_base, "base_penalty_cents")
    assert_money_cents(assessed["admin_fee_cents"], expected_fee, "admin_fee_cents")
    assert_money_cents(
        assessed["penalty_total_cents"], expected_base + expected_fee,
        "penalty_total_cents",
    )

    assert_money_cents(
        env.read_establishment()["outstanding_penalty_cents"], 336000,
        "Establishment.outstanding_penalty_cents",
    )
    assert_money_cents(
        env.read_jurisdiction()["assessed_penalty_cents_total"], 336000,
        "Jurisdiction.assessed_penalty_cents_total",
    )


def test_the_enhanced_tier_leaves_the_thirty_day_reprint_grace_alone(api):
    """PRD §3.4: "`calorie_compliance_status` from `CURRENT` to
    `REPRINT_REQUIRED` with `reprint_deadline` set to the logical clock plus that
    board's authority's `reprint_grace_days` days." PRD §3.1: "`reprint_grace_days`
    is 30 when `extra_requirement` is `NONE` and 14 for every other value".

    Design: Corner/calculations/penalty_fee_reaches_tier_three_above_the_second_ceiling
    """
    env, board_ids = _four_boards_awaiting_a_reprint(api, TIER_ENHANCED, "NY-ENH")

    assert env.read_jurisdiction()["reprint_grace_days"] == (
        GRACE_DAYS_NO_EXTRA_REQUIREMENT
    )
    for board_id in board_ids:
        board = env.read_board(board_id)
        assert board["publication_status"] == PUBLICATION_PUBLISHED
        assert board["calorie_compliance_status"] == COMPLIANCE_REPRINT_REQUIRED
        assert_instant_equals(
            board["reprint_deadline"],
            instant_plus_days(CLOCK_EPOCH_COMPACT, GRACE_DAYS_NO_EXTRA_REQUIREMENT),
            "reprint_deadline",
        )


def test_the_same_four_boards_in_a_federally_aligned_authority_stay_a_tier_lower(api):
    """PRD §3.9: "The administrative fee rate is then read" "off
    `base_penalty_cents`, never off the fee-inclusive total" — "eight per cent
    when it is above that but at or below two hundred and fifty thousand cents".
    "plain one when it is `FEDERAL_ALIGNED`."

    Design: Corner/calculations/penalty_fee_reaches_tier_three_above_the_second_ceiling
    """
    env, _board_ids = _four_boards_awaiting_a_reprint(
        api, TIER_FEDERAL_ALIGNED, "NY-FED"
    )

    assessed = _assess_per_board(env, _escalated_citation(env))

    assert assessed["violation_unit_count"] == 4
    expected_base = BASE_VIOLATION_CENTS * 4
    assert expected_base == 200000
    assert expected_base <= FEE_TIER_2_CEILING_CENTS
    expected_fee = int(expected_base * FEE_RATE_TIER_2)
    assert expected_fee == 16000

    assert_money_cents(assessed["base_penalty_cents"], expected_base, "base_penalty_cents")
    assert_money_cents(assessed["admin_fee_cents"], expected_fee, "admin_fee_cents")
    assert_money_cents(
        assessed["penalty_total_cents"], 216000, "penalty_total_cents"
    )
    assert_money_cents(
        env.read_establishment()["outstanding_penalty_cents"], 216000,
        "Establishment.outstanding_penalty_cents",
    )
