"""Entity-level surface: creation defaults, derived fields and the graph.

These cases probe what a row looks like the moment it is written and how the
register reads it back, before any of the cascades of section 3 get involved.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_BRAND_NOT_FOUND,
    ERR_MENU_BOARD_NOT_FOUND,
    ERR_MENU_ITEM_NOT_FOUND,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_brand_counters,
    assert_common_fields,
    assert_component_field_shape,
    assert_fields_are_none,
    assert_numeric_equals,
    ids_of,
    validate_unpaginated,
)
from test_helpers.constants import (
    BOARD_DRIVE_THRU_BOARD,
    BOARD_PRIMARY_MENU_BOARD,
    COVERAGE_COVERED,
    COVERAGE_NOT_COVERED,
    EXTRA_REQUIREMENT_NONE,
    EXTRA_REQUIREMENT_SODIUM_WARNING,
    GRACE_DAYS_NO_EXTRA_REQUIREMENT,
    GRACE_DAYS_WITH_EXTRA_REQUIREMENT,
    ITEM_CLASS_STANDARD,
    LISTING_LISTED,
    POSTURE_COMPLIANT,
    POSTURE_EXEMPT,
    PREEMPTION_PREEMPTED,
    PREEMPTION_VARIANCE_ALLOWED,
    REASON_NO_STANDARD_MENU_ITEMS,
    ROLE_BASE,
    STATEMENT_FEDERAL_DEFAULT,
    TIER_ENHANCED,
    TIER_FEDERAL_ALIGNED,
    UNIT_OPERATING,
    UNIT_PLANNED,
    UNIT_TEMPORARILY_CLOSED,
)
from test_helpers.factories import (
    OMIT,
    brand_payload,
    chicken_breast_component,
    component_payload,
    establishment_payload,
    jurisdiction_payload,
    listing_payload,
    menu_board_payload,
    menu_item_payload,
    recipe_payload,
)
from test_helpers.fixtures import make_brand, make_jurisdiction, set_clock
from test_helpers.test_users import (
    ANALYST_SUBMITTER,
    PLATFORM_ADMIN,
    make_brand_officer_headers,
    make_publisher_headers,
    make_regulator_headers,
)


def test_brand_creation_seeds_every_derived_coverage_and_posture_field(api):
    """PRD §3.1: "A freshly registered brand is deliberately inert:
    `coverage_status` is seeded to `NOT_COVERED` with `coverage_reason`
    `NO_STANDARD_MENU_ITEMS`, `counted_unit_count` and `standard_item_count` are
    0, `open_reprint_obligation_count`, `overdue_board_count` and
    `open_enforcement_escalated_count` are 0, `has_published_disclosure_packet`
    is false, and the posture ladder of §2.9 therefore lands on `EXEMPT`."

    Design: Corner/entities/brand_creation_seeds_derived_coverage_and_posture_defaults
    """
    set_clock(api)

    brand = validate_success(api.create_brand(brand_payload(), PLATFORM_ADMIN), 201)

    assert brand["legal_name"] == "Golden Grill Holdings LLC"
    assert brand["doing_business_as"] == "Golden Grill"
    assert_brand_counters(
        brand,
        coverage_status=COVERAGE_NOT_COVERED,
        coverage_reason=REASON_NO_STANDARD_MENU_ITEMS,
        counted_unit_count=0,
        standard_item_count=0,
        compliance_posture=POSTURE_EXEMPT,
        open_reprint_obligation_count=0,
        overdue_board_count=0,
        open_enforcement_escalated_count=0,
        has_published_disclosure_packet=False,
    )
    assert_common_fields(brand, expected_version=1, label="brand")


def test_system_and_computed_fields_sent_in_the_body_are_ignored(api):
    """PRD §2.4: "Clients never supply an `id`; a client-supplied `id` in a
    request body is not honoured." "`version` is an integer that starts at 1 when
    the row is created". PRD §3.1: "`coverage_status` is seeded to `NOT_COVERED`".

    Design: Corner/entities/brand_creation_system_and_computed_body_fields_input_ignored
    """
    set_clock(api)

    brand = validate_success(
        api.create_brand(
            brand_payload(
                legal_name="Silver Spoon Group LLC",
                doing_business_as="Silver Spoon",
                id=NON_EXISTENT_UUID,
                created_at="2020-01-01T00:00:00Z",
                version=99,
                coverage_status=COVERAGE_COVERED,
                compliance_posture=POSTURE_COMPLIANT,
                counted_unit_count=500,
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )

    assert brand["id"] != NON_EXISTENT_UUID
    assert brand["version"] == 1
    assert_brand_counters(
        brand,
        coverage_status=COVERAGE_NOT_COVERED,
        compliance_posture=POSTURE_EXEMPT,
        counted_unit_count=0,
    )


def test_jurisdiction_optional_inputs_fall_back_to_their_declared_defaults(api):
    """PRD §3.1: "`extra_requirement` names the state or local rule layered on
    top of the federal one and is `NONE`, `SODIUM_WARNING` or `ADDED_SUGAR_ICON`,
    defaulting to `NONE`." "`enforcement_tier` selects the penalty multiplier
    tier and is `FEDERAL_ALIGNED` or `ENHANCED`, defaulting to
    `FEDERAL_ALIGNED`." "it accepts any integer from 0 through 10000 and defaults
    to 2300."

    Design: Corner/entities/jurisdiction_optional_field_defaults_applied_when_omitted
    """
    set_clock(api)

    authority = validate_success(
        api.create_jurisdiction(
            jurisdiction_payload(
                code="ID-MIN",
                name="Idaho",
                preemption_mode=PREEMPTION_PREEMPTED,
                extra_requirement=OMIT,
                enforcement_tier=OMIT,
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )

    assert authority["preemption_mode"] == PREEMPTION_PREEMPTED
    assert authority["extra_requirement"] == EXTRA_REQUIREMENT_NONE
    assert authority["enforcement_tier"] == TIER_FEDERAL_ALIGNED
    assert authority["sodium_warning_threshold_mg"] == 2300
    assert authority["required_succinct_statement_variant"] == STATEMENT_FEDERAL_DEFAULT
    assert authority["reprint_grace_days"] == GRACE_DAYS_NO_EXTRA_REQUIREMENT
    assert authority["assessed_penalty_cents_total"] == 0


def test_reprint_grace_days_is_derived_from_the_extra_requirement(api):
    """PRD §3.1: "`assessed_penalty_cents_total` starts at 0, and
    `reprint_grace_days` is 30 when `extra_requirement` is `NONE` and 14 for
    every other value".

    Design: Corner/entities/jurisdiction_reprint_grace_days_computed_from_extra_requirement
    """
    set_clock(api)

    with_warning = make_jurisdiction(
        api,
        code="NY-SOD",
        name="New York",
        preemption_mode=PREEMPTION_VARIANCE_ALLOWED,
        extra_requirement=EXTRA_REQUIREMENT_SODIUM_WARNING,
        enforcement_tier=TIER_ENHANCED,
        sodium_warning_threshold_mg=900,
    )
    plain = make_jurisdiction(
        api,
        code="ID-PLAIN",
        name="Idaho",
        preemption_mode=PREEMPTION_VARIANCE_ALLOWED,
        extra_requirement=EXTRA_REQUIREMENT_NONE,
        enforcement_tier=TIER_ENHANCED,
        sodium_warning_threshold_mg=900,
    )

    assert with_warning["reprint_grace_days"] == GRACE_DAYS_WITH_EXTRA_REQUIREMENT
    assert with_warning["sodium_warning_threshold_mg"] == 900
    assert plain["reprint_grace_days"] == GRACE_DAYS_NO_EXTRA_REQUIREMENT

    reread = validate_unpaginated(
        api.get_jurisdiction(with_warning["id"], PLATFORM_ADMIN)
    )
    assert reread["reprint_grace_days"] == GRACE_DAYS_WITH_EXTRA_REQUIREMENT
    assert validate_unpaginated(api.get_jurisdiction(plain["id"], PLATFORM_ADMIN))[
        "reprint_grace_days"
    ] == GRACE_DAYS_NO_EXTRA_REQUIREMENT


# ---------------------------------------------------------------------------
# The unit estate: defaults, retrieval and the paginated list
# ---------------------------------------------------------------------------
def _one_brand_in_one_authority(api: ApiClient) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    set_clock(api)
    authority = make_jurisdiction(
        api, code="ID-MIN", name="Idaho", preemption_mode=PREEMPTION_PREEMPTED
    )
    brand = make_brand(api)
    return authority, brand


def test_a_unit_registered_without_a_status_lands_in_planned_and_counts_nothing(api):
    """PRD §3.1: "`unit_status` defaults to `PLANNED` when omitted but may be
    supplied as `OPERATING` outright". "`operates_under_brand_name` defaults to
    true and records whether the unit actually does business under the brand's
    `doing_business_as`". "Units in `PLANNED` or `PERMANENTLY_CLOSED`, and units
    whose `operates_under_brand_name` is false, are excluded under both bases."

    Design: Corner/entities/establishment_defaults_planned_status_and_brand_name_flag
    """
    authority, brand = _one_brand_in_one_authority(api)

    unit = validate_success(
        api.create_establishment(
            establishment_payload(
                brand_id=brand["id"],
                jurisdiction_id=authority["id"],
                unit_label="ID-0001",
                unit_status=OMIT,
                operates_under_brand_name=OMIT,
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )

    assert unit["unit_status"] == UNIT_PLANNED
    assert unit["operates_under_brand_name"] is True
    assert unit["outstanding_penalty_cents"] == 0
    assert unit["board_count"] == 0

    assert_brand_counters(
        validate_unpaginated(api.get_brand(brand["id"], PLATFORM_ADMIN)),
        counted_unit_count=0,
        coverage_status=COVERAGE_NOT_COVERED,
    )


def test_a_unit_reads_back_exactly_as_it_was_registered(api):
    """PRD §3.1: "A single unit registration carries the `brand_id` of the owning
    chain, the `jurisdiction_id` of the authority whose labeling rules bind it, a
    `unit_label` of 1 to 40 non-blank characters that must be unique within the
    brand, an optional `unit_status`, and an optional `operates_under_brand_name`."
    PRD §2.3: "Single-resource responses omit all four."

    Design: Corner/entities/establishment_retrieval_returns_the_stored_row
    """
    authority, brand = _one_brand_in_one_authority(api)
    created = validate_success(
        api.create_establishment(
            establishment_payload(
                brand_id=brand["id"],
                jurisdiction_id=authority["id"],
                unit_label="ID-0001",
                unit_status=UNIT_OPERATING,
                operates_under_brand_name=True,
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )

    fetched = validate_unpaginated(
        api.get_establishment(created["id"], make_regulator_headers(authority["id"]))
    )

    assert fetched["id"] == created["id"]
    assert fetched["brand_id"] == brand["id"]
    assert fetched["jurisdiction_id"] == authority["id"]
    assert fetched["unit_label"] == "ID-0001"
    assert fetched["unit_status"] == UNIT_OPERATING
    assert_common_fields(fetched, expected_version=1, label="establishment")


def test_the_unit_list_reports_total_count_and_has_more_around_the_page(api):
    """PRD §2.3: "`total_count` giving the number of rows that match the filter
    before the page window is applied, and `has_more` set to true when rows
    matching the filter remain beyond the current window." PRD §2.5: "The
    establishment list filters on `brand_id`, `jurisdiction_id` and `unit_status`".

    Design: Corner/entities/establishment_listing_is_paginated_with_total_count_and_has_more
    """
    authority, brand = _one_brand_in_one_authority(api)
    labels_and_statuses = (
        ("ID-0001", UNIT_OPERATING),
        ("ID-0002", UNIT_OPERATING),
        ("ID-0003", UNIT_TEMPORARILY_CLOSED),
    )
    created = [
        validate_success(
            api.create_establishment(
                establishment_payload(
                    brand_id=brand["id"],
                    jurisdiction_id=authority["id"],
                    unit_label=label,
                    unit_status=status,
                ),
                PLATFORM_ADMIN,
            ),
            201,
        )
        for label, status in labels_and_statuses
    ]

    first_page, meta = validate_paginated(
        api.list_establishments(
            PLATFORM_ADMIN, params={"brand_id": brand["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_establishments(
            PLATFORM_ADMIN, params={"brand_id": brand["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    operating, operating_meta = validate_paginated(
        api.list_establishments(
            PLATFORM_ADMIN,
            params={"brand_id": brand["id"], "unit_status": UNIT_OPERATING},
        )
    )
    assert ids_of(operating) == [created[0]["id"], created[1]["id"]]
    assert operating_meta["total_count"] == 2


def test_an_unknown_board_id_reports_the_boards_own_not_found_error(api):
    """PRD §2.6 rung 7: "Every templated path identifier resolves to an existing
    row, else that resource type's not-found error." PRD §2.5 names
    `ERR_MENU_BOARD_NOT_FOUND` among those errors, "each with HTTP 404".

    Design: Corner/entities/menu_board_unknown_path_id_not_found
    """
    set_clock(api)

    error = validate_error(
        api.get_menu_board(NON_EXISTENT_UUID, PLATFORM_ADMIN),
        ERR_MENU_BOARD_NOT_FOUND,
        404,
    )
    assert isinstance(error["message"], str) and error["message"].strip() != ""


# ---------------------------------------------------------------------------
# Menu items and recipe sheets: well-formedness, immutability and parentage
# ---------------------------------------------------------------------------
def _brand_only(api: ApiClient) -> Tuple[Dict[str, Any], Dict[str, str]]:
    set_clock(api)
    brand = make_brand(api)
    return brand, make_brand_officer_headers(brand["id"])


def test_a_menu_item_without_a_first_offered_date_is_refused(api):
    """PRD §3.2: "Menu-item creation carries the `brand_id`, the item's `name` as
    printed on menus — 1 to 120 non-blank characters, unique within the brand —
    its `item_class`, an optional `variable_type`, and `first_offered_on`, the ISO
    8601 calendar date on which the item first appeared on a menu." PRD §2.6 rung
    5: "The request body is well-formed: every required field present".

    Design: Corner/entities/menu_item_creation_missing_required_first_offered_on_rejected
    """
    brand, officer = _brand_only(api)

    validate_error(
        api.create_menu_item(
            menu_item_payload(
                brand_id=brand["id"],
                name="Grill Sandwich",
                item_class=ITEM_CLASS_STANDARD,
                variable_type=OMIT,
                first_offered_on=OMIT,
            ),
            officer,
        ),
        ERR_VALIDATION,
        400,
    )

    _rows, meta = validate_paginated(
        api.list_menu_items(officer, params={"brand_id": brand["id"]})
    )
    assert meta["total_count"] == 0

    stored = validate_unpaginated(api.get_brand(brand["id"], officer))
    assert stored["standard_item_count"] == 0
    assert stored["version"] == 1


def test_an_unknown_item_class_and_a_negative_portion_weight_are_both_malformed(api):
    """PRD §3.2: "`item_class` is the FDA classification that drives every
    exclusion rule and is one of `STANDARD`, `TEMPORARY`, `TEST_MARKET`,
    `DAILY_SPECIAL`, `CUSTOM_ORDER` or `SELF_SERVICE`." PRD §3.3: "`grams` must be
    strictly greater than 0 and carry at most two decimal places." PRD §2.6 rung
    5: "every enum-valued field carrying a value inside its declared domain, every
    integer non-negative where declared so".

    Design: Corner/entities/menu_item_creation_invalid_enum_item_class_rejected
    """
    brand, officer = _brand_only(api)
    item = validate_success(
        api.create_menu_item(
            menu_item_payload(brand_id=brand["id"], name="Grill Sandwich"), officer
        ),
        201,
    )
    recipe = validate_success(
        api.create_recipe(
            item["id"],
            recipe_payload(expected_menu_item_version=item["version"]),
            ANALYST_SUBMITTER,
        ),
        201,
    )

    validate_error(
        api.create_menu_item(
            menu_item_payload(
                brand_id=brand["id"], name="Seasonal Wrap", item_class="SEASONAL"
            ),
            officer,
        ),
        ERR_VALIDATION,
        400,
    )
    validate_error(
        api.add_recipe_component(
            recipe["id"],
            component_payload(
                component_name="Negative filler",
                role=ROLE_BASE,
                grams=-10,
                calories_per_100g=100,
                sodium_mg_per_100g=50,
            ),
            ANALYST_SUBMITTER,
        ),
        ERR_VALIDATION,
        400,
    )

    untouched = validate_unpaginated(api.get_recipe(recipe["id"], officer))
    assert untouched["component_count"] == 0
    assert_numeric_equals(
        untouched["computed_base_calories"], 0, "computed_base_calories"
    )


def test_a_stored_component_carries_no_version_and_no_updated_at(api):
    """PRD §2.4: "`RecipeComponent` is the single exception: a component row
    carries only `id` and `created_at`. It has no `updated_at` and no `version`,
    and neither field appears in its representation." PRD §3.3:
    "`component_calories` is `calories_per_100g` multiplied by `grams` divided by
    100, rounded half up to two decimal places".

    Design: Corner/entities/recipe_component_is_immutable_and_carries_no_version_field
    """
    brand, officer = _brand_only(api)
    item = validate_success(
        api.create_menu_item(
            menu_item_payload(brand_id=brand["id"], name="Grill Sandwich"), officer
        ),
        201,
    )
    recipe = validate_success(
        api.create_recipe(
            item["id"],
            recipe_payload(expected_menu_item_version=item["version"]),
            ANALYST_SUBMITTER,
        ),
        201,
    )

    component = validate_success(
        api.add_recipe_component(
            recipe["id"], chicken_breast_component(), ANALYST_SUBMITTER
        ),
        201,
    )

    assert component["recipe_id"] == recipe["id"]
    assert_component_field_shape(component)
    assert_numeric_equals(
        component["component_calories"], "196.00", "component_calories"
    )
    assert_numeric_equals(
        component["component_sodium_mg"], "336.00", "component_sodium_mg"
    )
    assert_numeric_equals(
        component["added_sugar_g_per_100g"], 0, "added_sugar_g_per_100g"
    )
    assert_fields_are_none(
        component,
        ["choice_group", "selection_mode", "selection_limit"],
        "a BASE component",
    )

    rows, _meta = validate_paginated(
        api.list_recipe_components(recipe["id"], ANALYST_SUBMITTER)
    )
    assert ids_of(rows) == [component["id"]]

    rebuilt = validate_unpaginated(api.get_recipe(recipe["id"], ANALYST_SUBMITTER))
    assert rebuilt["component_count"] == 1
    assert_numeric_equals(
        rebuilt["computed_base_calories"], "196.00", "computed_base_calories"
    )


def test_a_recipe_cannot_be_opened_under_an_unknown_parent_item(api):
    """PRD §2.6 rung 7: "Every templated path identifier resolves to an existing
    row, else that resource type's not-found error." The optimistic-concurrency
    rung comes later: "Because this rung sits after existence and before every
    state precondition, a stale version against an already-terminal parent
    reports the stale-version error, not a state error."

    Design: Corner/entities/recipe_creation_for_unknown_parent_menu_item_not_found
    """
    brand, officer = _brand_only(api)
    item = validate_success(
        api.create_menu_item(
            menu_item_payload(brand_id=brand["id"], name="Grill Sandwich"), officer
        ),
        201,
    )

    validate_error(
        api.create_recipe(
            NON_EXISTENT_UUID,
            recipe_payload(
                expected_menu_item_version=item["version"],
                change_note="Recipe for a nonexistent item",
            ),
            ANALYST_SUBMITTER,
        ),
        ERR_MENU_ITEM_NOT_FOUND,
        404,
    )

    _rows, meta = validate_paginated(
        api.list_recipes(officer, params={"menu_item_id": item["id"]})
    )
    assert meta["total_count"] == 0


def test_an_unknown_brand_id_in_the_body_reports_the_brands_not_found_error(api):
    """PRD §2.6 rung 8: "Every foreign key supplied in the request body resolves to
    an existing row, else the referenced entity's not-found error. Applies to unit
    registration, unit batch registration, menu-item creation, board creation,
    listing creation, variance filing and citation opening."

    Design: Corner/entities/menu_item_creation_with_unknown_body_brand_id_not_found
    """
    set_clock(api)

    validate_error(
        api.create_menu_item(
            menu_item_payload(brand_id=NON_EXISTENT_UUID, name="Grill Sandwich"),
            make_brand_officer_headers(NON_EXISTENT_UUID),
        ),
        ERR_BRAND_NOT_FOUND,
        404,
    )


def test_one_item_on_two_boards_yields_two_lines_reachable_from_both_sides(api):
    """PRD §3.6: "On success the line starts at `listing_status` `LISTED` with its
    `menu_board_id` pointing at the board, and `display_calorie_text`,
    `declared_min_snapshot` and `declared_max_snapshot` captured from the item's
    `declared_calorie_min` and `declared_calorie_max` as they stand at that
    moment." "The board-and-item pair must not already be carried by a line whose
    `listing_status` is `LISTED` or `STALE`, else `ERR_DUPLICATE_LISTING`".

    Design: Corner/entities/menu_board_listing_junction_links_board_and_item
    """
    set_clock(api)
    authority = make_jurisdiction(
        api, code="ID-MIN", name="Idaho", preemption_mode=PREEMPTION_PREEMPTED
    )
    brand = make_brand(api)
    officer = make_brand_officer_headers(brand["id"])
    unit = validate_success(
        api.create_establishment(
            establishment_payload(
                brand_id=brand["id"],
                jurisdiction_id=authority["id"],
                unit_label="ID-0001",
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )
    publisher = make_publisher_headers(unit["id"])
    item = validate_success(
        api.create_menu_item(
            menu_item_payload(brand_id=brand["id"], name="Grill Sandwich"), officer
        ),
        201,
    )
    boards = [
        validate_success(
            api.create_menu_board(
                menu_board_payload(establishment_id=unit["id"], board_type=board_type),
                publisher,
            ),
            201,
        )
        for board_type in (BOARD_PRIMARY_MENU_BOARD, BOARD_DRIVE_THRU_BOARD)
    ]

    first_line = validate_success(
        api.create_listing(boards[0]["id"], listing_payload(item["id"]), publisher), 201
    )
    second_line = validate_success(
        api.create_listing(boards[1]["id"], listing_payload(item["id"]), publisher), 201
    )

    assert first_line["listing_status"] == LISTING_LISTED
    assert first_line["menu_board_id"] == boards[0]["id"]
    assert first_line["menu_item_id"] == item["id"]
    assert_fields_are_none(
        first_line,
        ["declared_min_snapshot", "declared_max_snapshot", "display_calorie_text"],
        "a line printed before certification",
    )
    assert second_line["id"] != first_line["id"]

    from_the_board, _meta = validate_paginated(
        api.list_menu_board_listings(boards[0]["id"], publisher)
    )
    assert ids_of(from_the_board) == [first_line["id"]]
    assert validate_unpaginated(
        api.get_menu_board(boards[0]["id"], officer)
    )["listing_count"] == 1

    from_the_item, item_meta = validate_paginated(
        api.list_menu_item_listings(item["id"], officer)
    )
    assert item_meta["total_count"] == 2
    assert set(ids_of(from_the_item)) == {first_line["id"], second_line["id"]}
