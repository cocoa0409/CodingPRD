"""The plain surface: round trips, page windows and junction rows.

Nothing here is exotic. A row is created, read back and found to carry the
defaults the specification promised; a list is walked twice to see its page
window move; a batch is asked to fail and found to have written nothing; and
one junction row is looked up from both of the ends it joins.
"""

from typing import Any, Dict, List, Tuple

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_INVALID_PAGINATION,
    ERR_JURISDICTION_NOT_FOUND,
    ERR_MENU_ITEM_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_brand_counters,
    assert_created_at_ascending,
    assert_instant_equals,
    assert_money_cents,
    expected_display_calorie_text,
    ids_of,
    validate_unpaginated,
)
from test_helpers.constants import (
    ALLERGEN_WHEAT,
    CLOCK_EPOCH_COMPACT,
    COVERAGE_COVERED,
    COVERAGE_NOT_COVERED,
    CROSS_CONTACT_NONE,
    DEFAULT_SODIUM_WARNING_THRESHOLD_MG,
    EXTRA_REQUIREMENT_NONE,
    GRACE_DAYS_NO_EXTRA_REQUIREMENT,
    LISTING_LISTED,
    POSTURE_EXEMPT,
    PREEMPTION_PREEMPTED,
    REASON_BELOW_UNIT_THRESHOLD,
    REASON_COVERED_BY_UNIT_COUNT,
    REASON_NO_STANDARD_MENU_ITEMS,
    ROLE_BASE,
    STATEMENT_FEDERAL_DEFAULT,
    TIER_FEDERAL_ALIGNED,
    UNIT_OPERATING,
)
from test_helpers.factories import (
    OMIT,
    component_payload,
    establishment_batch_payload,
    jurisdiction_payload,
    listing_payload,
)
from test_helpers.fixtures import (
    Env,
    certify_recipe_version,
    create_board,
    make_brand,
    make_establishment,
    make_menu_item,
    set_clock,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    make_brand_officer_headers,
    make_regulator_headers,
)

SANDWICH_CALORIES_PER_100G = 100
SANDWICH_GRAMS = 100
DECLARED_CALORIES = 100


def _minimal_authority(
    api: ApiClient, code: str = "ID-MIN", name: str = "Idaho"
) -> Dict[str, Any]:
    """An authority whose body carries only the three mandatory fields."""
    return get_success_data(
        api.create_jurisdiction(
            jurisdiction_payload(
                code=code,
                name=name,
                preemption_mode=PREEMPTION_PREEMPTED,
                extra_requirement=OMIT,
                enforcement_tier=OMIT,
            ),
            PLATFORM_ADMIN,
        )
    )


def _sandwich_as_served() -> Dict[str, Any]:
    """One BASE component of 100 g at 100 Cal per 100 g."""
    return component_payload(
        component_name="Sandwich as served",
        role=ROLE_BASE,
        grams=SANDWICH_GRAMS,
        calories_per_100g=SANDWICH_CALORIES_PER_100G,
        sodium_mg_per_100g=200,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_WHEAT,
        cross_contact_risk=CROSS_CONTACT_NONE,
    )


def _three_units_one_at_a_time(
    api: ApiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """A brand whose three units were registered in a known order."""
    set_clock(api)
    jurisdiction = _minimal_authority(api)
    brand = make_brand(api)
    officer = make_brand_officer_headers(brand["id"])
    units = [
        make_establishment(
            api,
            brand_id=brand["id"],
            jurisdiction_id=jurisdiction["id"],
            unit_label="ID-0001",
            unit_status=UNIT_OPERATING,
        ),
        make_establishment(
            api,
            brand_id=brand["id"],
            jurisdiction_id=jurisdiction["id"],
            unit_label="ID-0002",
            unit_status=UNIT_OPERATING,
            headers=officer,
        ),
        make_establishment(
            api,
            brand_id=brand["id"],
            jurisdiction_id=jurisdiction["id"],
            unit_label="ID-0003",
            unit_status=UNIT_OPERATING,
            headers=officer,
        ),
    ]
    return jurisdiction, brand, units


def test_an_authority_created_with_only_its_three_required_fields_defaults_the_rest(api):
    """Five omitted optional fields come back filled in by the specification.

    PRD 3.1 on authority registration: "`extra_requirement` names the state or
    local rule layered on top of the federal one and is `NONE`,
    `SODIUM_WARNING` or `ADDED_SUGAR_ICON`, defaulting to `NONE`.
    `enforcement_tier` selects the penalty multiplier tier and is
    `FEDERAL_ALIGNED` or `ENHANCED`, defaulting to `FEDERAL_ALIGNED`." The same
    paragraph continues: "`sodium_warning_threshold_mg` is the declared-sodium
    level at or above which a printed line must carry the sodium warning icon;
    it accepts any integer from 0 through 10000 and defaults to 2300.
    `required_succinct_statement_variant` fixes the succinct-statement wording
    that boards in this authority must carry and is `FEDERAL_DEFAULT` or
    `STATE_EXTENDED`, defaulting to `FEDERAL_DEFAULT`. Two figures are derived
    rather than supplied: `assessed_penalty_cents_total` starts at 0, and
    `reprint_grace_days` is 30 when `extra_requirement` is `NONE` and 14 for
    every other value".

    Design: Corner/endpoints/registry_round_trip_and_list_pagination_bounds
    """
    set_clock(api)
    created = _minimal_authority(api)

    read = validate_unpaginated(
        api.get_jurisdiction(created["id"], make_regulator_headers(created["id"]))
    )

    assert read["id"] == created["id"]
    assert read["code"] == "ID-MIN"
    assert read["name"] == "Idaho"
    assert read["preemption_mode"] == PREEMPTION_PREEMPTED
    assert read["extra_requirement"] == EXTRA_REQUIREMENT_NONE
    assert read["enforcement_tier"] == TIER_FEDERAL_ALIGNED
    assert read["sodium_warning_threshold_mg"] == DEFAULT_SODIUM_WARNING_THRESHOLD_MG
    assert read["required_succinct_statement_variant"] == STATEMENT_FEDERAL_DEFAULT
    assert read["reprint_grace_days"] == GRACE_DAYS_NO_EXTRA_REQUIREMENT
    assert_money_cents(
        read["assessed_penalty_cents_total"], 0, "assessed_penalty_cents_total"
    )


def test_a_brand_with_three_units_reads_back_exempt_for_want_of_an_item(api):
    """Three unit registrations move the counter and the version, not coverage.

    PRD 3.1: "If `standard_item_count` is 0, `coverage_status` is
    `NOT_COVERED` and `coverage_reason` is `NO_STANDARD_MENU_ITEMS`." and
    "Registering a single unit re-runs the coverage determination on the
    `OPERATING_ONLY` basis and increments the brand's `version` once." PRD 2.9
    fixes the posture that follows: "`EXEMPT` — when `coverage_status` is
    `NOT_COVERED`."

    Design: Corner/endpoints/registry_round_trip_and_list_pagination_bounds
    """
    _jurisdiction, brand, _units = _three_units_one_at_a_time(api)

    read = validate_unpaginated(api.get_brand(brand["id"], PLATFORM_ADMIN))

    assert read["id"] == brand["id"]
    assert_brand_counters(
        read,
        coverage_status=COVERAGE_NOT_COVERED,
        coverage_reason=REASON_NO_STANDARD_MENU_ITEMS,
        counted_unit_count=3,
        standard_item_count=0,
        compliance_posture=POSTURE_EXEMPT,
    )
    assert read["version"] == brand["version"] + 3, (
        "three single-unit registrations must bump the brand three times: "
        f"created at {brand['version']}, read at {read['version']}"
    )


def test_the_unit_list_walks_three_rows_in_created_at_order_across_two_pages(api):
    """A limit of 2 splits three rows into a full page and a remainder.

    PRD 2.3: "`limit` controls page size; it defaults to 10, its minimum
    accepted value is 1 and its maximum accepted value is 100. `offset`
    controls how many rows are skipped before the page begins; it defaults to 0
    and its minimum accepted value is 0." The same section fixes the meta
    object — "`total_count` giving the number of rows that match the filter
    before the page window is applied, and `has_more` set to true when rows
    matching the filter remain beyond the current window" — and the order:
    "Unless a specific list endpoint states otherwise, list results are ordered
    by `created_at` ascending." PRD 2.3 also allows the filter used here: "The
    establishment list filters on `brand_id`, `jurisdiction_id` and
    `unit_status`".

    Design: Corner/endpoints/registry_round_trip_and_list_pagination_bounds
    """
    _jurisdiction, brand, units = _three_units_one_at_a_time(api)
    expected_ids = [unit["id"] for unit in units]

    first_page, first_meta = validate_paginated(
        api.list_establishments(
            PLATFORM_ADMIN,
            params={"brand_id": brand["id"], "limit": 2, "offset": 0},
        )
    )
    second_page, second_meta = validate_paginated(
        api.list_establishments(
            PLATFORM_ADMIN,
            params={"brand_id": brand["id"], "limit": 2, "offset": 2},
        )
    )

    assert ids_of(first_page) == expected_ids[:2]
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert_created_at_ascending(first_page)

    assert ids_of(second_page) == expected_ids[2:]
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    whole, whole_meta = validate_paginated(
        api.list_establishments(
            PLATFORM_ADMIN, params={"brand_id": brand["id"], "limit": 100}
        )
    )
    assert ids_of(whole) == expected_ids
    assert whole_meta["total_count"] == 3
    assert whole_meta["has_more"] is False
    assert_created_at_ascending(whole)
    assert [row["unit_label"] for row in whole] == ["ID-0001", "ID-0002", "ID-0003"]


def test_the_page_window_bounds_refuse_zero_one_hundred_one_and_minus_one(api):
    """The three out-of-range window values are refused; the edges are not.

    PRD 2.3: "A supplied `limit` below 1 or above 100, or a supplied `offset`
    below 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400) — so `limit`
    of 0 and `limit` of 101 are both refused while `limit` of 1 and `limit` of
    100 are both accepted."

    Design: Corner/endpoints/registry_round_trip_and_list_pagination_bounds
    """
    _jurisdiction, brand, units = _three_units_one_at_a_time(api)
    scoped = {"brand_id": brand["id"]}

    for rejected in ({"limit": 0}, {"limit": 101}, {"limit": 10, "offset": -1}):
        params = dict(scoped)
        params.update(rejected)
        validate_error(
            api.list_establishments(PLATFORM_ADMIN, params=params),
            ERR_INVALID_PAGINATION,
            400,
        )

    smallest, smallest_meta = validate_paginated(
        api.list_establishments(PLATFORM_ADMIN, params={**scoped, "limit": 1})
    )
    assert ids_of(smallest) == [units[0]["id"]]
    assert smallest_meta["limit"] == 1
    assert smallest_meta["total_count"] == 3
    assert smallest_meta["has_more"] is True

    largest, largest_meta = validate_paginated(
        api.list_establishments(PLATFORM_ADMIN, params={**scoped, "limit": 100})
    )
    assert len(largest) == 3
    assert largest_meta["limit"] == 100
    assert largest_meta["has_more"] is False


def test_a_nineteen_unit_batch_lands_as_one_transaction_with_one_redetermination(api):
    """Nineteen rows, one label sequence, one coverage run, one version bump.

    PRD 3.1 on bulk registration: "The created units are inserted in
    `created_at` ascending order and labelled with the prefix, a hyphen, and a
    four-digit zero-padded sequence number beginning at `0001`; when
    `unit_label_prefix` is omitted the literal prefix `UNIT` is used. The
    response summarises the batch rather than echoing every row: `brand_id`,
    `created_count`, the `unit_status` the batch was created in,
    `first_created_establishment_id`, and the brand's resulting
    `brand_coverage_status` and `brand_counted_unit_count`. Coverage is
    re-determined exactly once after the whole batch lands, and the brand's
    `version` increments exactly once — not once per unit." Because the brand
    holds no items, PRD 3.1's first branch still answers: "If
    `standard_item_count` is 0, `coverage_status` is `NOT_COVERED` and
    `coverage_reason` is `NO_STANDARD_MENU_ITEMS`." PRD 4 gives the status:
    "An operation that brings a new resource row into existence answers" 201.

    Design: Corner/endpoints/unit_batches_are_all_or_nothing_and_label_in_creation_order
    """
    set_clock(api)
    jurisdiction = _minimal_authority(api, code="OR-STD", name="Oregon")
    brand = make_brand(api)

    summary = validate_unpaginated(
        api.create_establishment_batch(
            brand["id"],
            establishment_batch_payload(
                jurisdiction_id=jurisdiction["id"],
                unit_count=19,
                unit_status=UNIT_OPERATING,
                unit_label_prefix="OR-B",
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )

    assert summary["brand_id"] == brand["id"]
    assert summary["created_count"] == 19
    assert summary["unit_status"] == UNIT_OPERATING
    assert summary["brand_coverage_status"] == COVERAGE_NOT_COVERED
    assert summary["brand_counted_unit_count"] == 19
    assert summary["first_created_establishment_id"]

    rows, meta = validate_paginated(
        api.list_establishments(
            PLATFORM_ADMIN, params={"brand_id": brand["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 19
    assert_created_at_ascending(rows)
    assert [row["unit_label"] for row in rows] == [
        f"OR-B-{index:04d}" for index in range(1, 20)
    ]
    assert rows[0]["id"] == summary["first_created_establishment_id"]
    assert rows[0]["unit_label"] == "OR-B-0001"

    read_brand = validate_unpaginated(api.get_brand(brand["id"], PLATFORM_ADMIN))
    assert_brand_counters(
        read_brand,
        coverage_status=COVERAGE_NOT_COVERED,
        coverage_reason=REASON_NO_STANDARD_MENU_ITEMS,
        counted_unit_count=19,
        standard_item_count=0,
        compliance_posture=POSTURE_EXEMPT,
    )
    assert read_brand["version"] == brand["version"] + 1, (
        "the whole batch must bump the brand exactly once: created at "
        f"{brand['version']}, read at {read_brand['version']}"
    )


def test_a_batch_naming_an_unknown_authority_creates_nothing_at_all(api):
    """The body foreign key fails the whole batch, not part of it.

    PRD 2.6 rung 8: "Every foreign key supplied in the request body resolves to
    an existing row, else the referenced entity's not-found error. Applies to
    unit registration, unit batch registration, menu-item creation, board
    creation, listing creation, variance filing and citation opening." PRD 2.5
    names the error carried by that rung for an authority:
    `ERR_JURISDICTION_NOT_FOUND`, "each with HTTP 404".

    Design: Corner/endpoints/unit_batches_are_all_or_nothing_and_label_in_creation_order
    """
    set_clock(api)
    _minimal_authority(api, code="OR-STD", name="Oregon")
    brand = make_brand(api)

    validate_error(
        api.create_establishment_batch(
            brand["id"],
            establishment_batch_payload(
                jurisdiction_id=NON_EXISTENT_UUID,
                unit_count=5,
                unit_status=UNIT_OPERATING,
                unit_label_prefix="OR-X",
            ),
            make_brand_officer_headers(brand["id"]),
        ),
        ERR_JURISDICTION_NOT_FOUND,
        404,
    )

    rows, meta = validate_paginated(
        api.list_establishments(
            PLATFORM_ADMIN, params={"brand_id": brand["id"], "limit": 100}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0

    read_brand = validate_unpaginated(api.get_brand(brand["id"], PLATFORM_ADMIN))
    assert read_brand["counted_unit_count"] == 0
    assert read_brand["version"] == brand["version"], (
        "a refused batch must leave the brand version untouched: created at "
        f"{brand['version']}, read at {read_brand['version']}"
    )


def _covered_brand_with_a_draft_board(api: ApiClient) -> Tuple[Env, str, str]:
    """A COVERED brand, one certified item declaring 100 Cal, one DRAFT board."""
    set_clock(api)
    jurisdiction = _minimal_authority(api)
    brand = make_brand(api)
    summary = get_success_data(
        api.create_establishment_batch(
            brand["id"],
            establishment_batch_payload(
                jurisdiction_id=jurisdiction["id"],
                unit_count=20,
                unit_status=UNIT_OPERATING,
                unit_label_prefix="ID-B",
            ),
            PLATFORM_ADMIN,
        )
    )
    establishment = get_success_data(
        api.get_establishment(
            summary["first_created_establishment_id"], PLATFORM_ADMIN
        )
    )
    env = Env(
        api=api,
        jurisdiction=jurisdiction,
        brand=brand,
        establishment=establishment,
    )
    item = make_menu_item(env)
    certify_recipe_version(env, item["id"], [_sandwich_as_served()])
    board = create_board(env).board
    return env, item["id"], board["id"]


def test_a_line_naming_no_menu_item_leaves_the_board_empty(api):
    """The path board resolves, the body item does not, and nothing is printed.

    PRD 2.5: "Foreign keys carried in a request body are resolved only after the
    path has fully resolved, and they report the not-found error of the entity
    they reference." PRD 2.6 rung 8 places that resolution before every state
    check: "Every foreign key supplied in the request body resolves to an
    existing row, else the referenced entity's not-found error. Applies to unit
    registration, unit batch registration, menu-item creation, board creation,
    listing creation, variance filing and citation opening."

    Design: Corner/endpoints/listing_creation_links_the_board_and_the_item_in_both_directions
    """
    env, _item_id, board_id = _covered_brand_with_a_draft_board(api)

    validate_error(
        env.api.create_listing(
            board_id,
            listing_payload(menu_item_id=NON_EXISTENT_UUID, sodium_warning_icon=False),
            env.publisher,
        ),
        ERR_MENU_ITEM_NOT_FOUND,
        404,
    )

    board = env.read_board(board_id)
    assert board["listing_count"] == 0
    assert board["stale_listing_count"] == 0

    rows, meta = validate_paginated(
        env.api.list_menu_board_listings(
            board_id, env.publisher, params={"limit": 10, "offset": 0}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_one_listing_is_readable_from_the_board_side_and_the_item_side(api):
    """A single POST makes the junction row reachable from both of its ends.

    PRD 3.6: "On success the line starts at `listing_status` `LISTED` with its
    `menu_board_id` pointing at the board, and `display_calorie_text`,
    `declared_min_snapshot` and `declared_max_snapshot` captured from the item's
    `declared_calorie_min` and `declared_calorie_max` as they stand at that
    moment. `MenuBoard.listing_count` is recomputed." PRD 3.4 fixes the printed
    text: "`display_calorie_text` on a board line is the item's
    `declared_calorie_min` followed by a space and the word `Cal` when
    `declared_calorie_min` and `declared_calorie_max` are equal".

    Design: Corner/endpoints/listing_creation_links_the_board_and_the_item_in_both_directions
    """
    env, item_id, board_id = _covered_brand_with_a_draft_board(api)
    item = env.read_item(item_id)
    assert item["declared_calorie_min"] == DECLARED_CALORIES
    assert item["declared_calorie_max"] == DECLARED_CALORIES

    listing = validate_unpaginated(
        env.api.create_listing(
            board_id,
            listing_payload(menu_item_id=item_id, sodium_warning_icon=False),
            env.publisher,
        ),
        201,
    )

    assert listing["menu_board_id"] == board_id
    assert listing["menu_item_id"] == item_id
    assert listing["listing_status"] == LISTING_LISTED
    assert listing["sodium_warning_icon"] is False
    assert listing["declared_min_snapshot"] == DECLARED_CALORIES
    assert listing["declared_max_snapshot"] == DECLARED_CALORIES
    assert listing["display_calorie_text"] == expected_display_calorie_text(
        DECLARED_CALORIES, DECLARED_CALORIES
    )

    from_the_board, board_meta = validate_paginated(
        env.api.list_menu_board_listings(
            board_id, env.publisher, params={"limit": 10, "offset": 0}
        )
    )
    assert ids_of(from_the_board) == [listing["id"]]
    assert board_meta["total_count"] == 1

    from_the_item, item_meta = validate_paginated(
        env.api.list_menu_item_listings(
            item_id, env.officer, params={"limit": 10, "offset": 0}
        )
    )
    assert ids_of(from_the_item) == [listing["id"]]
    assert item_meta["total_count"] == 1
    assert from_the_item[0]["menu_board_id"] == board_id

    board = env.read_board(board_id)
    assert board["listing_count"] == 1
    assert board["stale_listing_count"] == 0


def _nineteen_units_and_one_certified_item(api: ApiClient) -> Env:
    """One unit short of the federal threshold, with one declared item."""
    set_clock(api)
    jurisdiction = _minimal_authority(api)
    brand = make_brand(api)
    summary = get_success_data(
        api.create_establishment_batch(
            brand["id"],
            establishment_batch_payload(
                jurisdiction_id=jurisdiction["id"],
                unit_count=19,
                unit_status=UNIT_OPERATING,
                unit_label_prefix="ID-B",
            ),
            PLATFORM_ADMIN,
        )
    )
    establishment = get_success_data(
        api.get_establishment(
            summary["first_created_establishment_id"], PLATFORM_ADMIN
        )
    )
    env = Env(
        api=api,
        jurisdiction=jurisdiction,
        brand=brand,
        establishment=establishment,
    )
    item = make_menu_item(env)
    certify_recipe_version(env, item["id"], [_sandwich_as_served()])
    return env


def _read_summary_as_regulator(env: Env) -> Dict[str, Any]:
    return validate_unpaginated(
        env.api.get_brand_compliance_summary(
            env.brand_id, make_regulator_headers(env.jurisdiction_id)
        )
    )


def test_the_summary_reports_nineteen_units_below_the_unit_threshold(api):
    """Every field of the computed read agrees with the rows behind it.

    PRD 3.1: "For operators who want the whole picture in one read, a brand's
    compliance summary is recomputed from current rows at read time rather than
    served from stored counters. It returns `brand_id`, `coverage_status`,
    `coverage_reason`, `counted_unit_count`, `standard_item_count`,
    `compliance_posture`, `open_reprint_obligation_count`,
    `overdue_board_count`, `open_enforcement_escalated_count`,
    `has_published_disclosure_packet`, and `outstanding_penalty_cents_total` —
    the sum of `outstanding_penalty_cents` across every unit of the brand." With
    nineteen counted units and one non-exempt item the decision of PRD 3.1 ends
    at its last branch: "Otherwise `coverage_status` is `NOT_COVERED` and
    `coverage_reason` is `BELOW_UNIT_THRESHOLD`." PRD 2.9 then gives the
    posture: "`EXEMPT` — when `coverage_status` is `NOT_COVERED`."

    Design: Corner/endpoints/compliance_summary_is_recomputed_from_current_rows_on_every_read
    """
    env = _nineteen_units_and_one_certified_item(api)

    summary = _read_summary_as_regulator(env)

    assert summary["brand_id"] == env.brand_id
    assert summary["coverage_status"] == COVERAGE_NOT_COVERED
    assert summary["coverage_reason"] == REASON_BELOW_UNIT_THRESHOLD
    assert summary["counted_unit_count"] == 19
    assert summary["standard_item_count"] == 1
    assert summary["compliance_posture"] == POSTURE_EXEMPT
    assert summary["open_reprint_obligation_count"] == 0
    assert summary["overdue_board_count"] == 0
    assert summary["open_enforcement_escalated_count"] == 0
    assert summary["has_published_disclosure_packet"] is False
    assert_money_cents(
        summary["outstanding_penalty_cents_total"],
        0,
        "outstanding_penalty_cents_total",
    )

    brand = env.read_brand()
    for field in (
        "coverage_status",
        "coverage_reason",
        "counted_unit_count",
        "standard_item_count",
        "compliance_posture",
        "open_reprint_obligation_count",
        "overdue_board_count",
        "open_enforcement_escalated_count",
        "has_published_disclosure_packet",
    ):
        assert summary[field] == brand[field], (
            f"summary.{field} must agree with the brand row: "
            f"{summary[field]!r} against {brand[field]!r}"
        )


def test_the_twentieth_unit_moves_the_same_summary_call_to_covered(api):
    """One more unit, the same call, a different answer.

    PRD 3.1: "Otherwise, if `counted_unit_count` is at least twenty,
    `coverage_status` is `COVERED` and `coverage_reason` is
    `COVERED_BY_UNIT_COUNT`." The count that changes is the one PRD 3.1 defines
    as "the number of the brand's units whose `unit_status` is `OPERATING` and
    whose `operates_under_brand_name` is true", and the item count does not
    move because it is "the number of the brand's menu items whose
    `labeling_exempt` is false".

    Design: Corner/endpoints/compliance_summary_is_recomputed_from_current_rows_on_every_read
    """
    env = _nineteen_units_and_one_certified_item(api)
    before = _read_summary_as_regulator(env)
    assert before["coverage_status"] == COVERAGE_NOT_COVERED

    make_establishment(
        env.api,
        brand_id=env.brand_id,
        jurisdiction_id=env.jurisdiction_id,
        unit_label="ID-B-0020",
        unit_status=UNIT_OPERATING,
        headers=env.officer,
    )

    after = _read_summary_as_regulator(env)

    assert after["coverage_status"] == COVERAGE_COVERED
    assert after["coverage_reason"] == REASON_COVERED_BY_UNIT_COUNT
    assert after["counted_unit_count"] == 20
    assert after["standard_item_count"] == 1
    assert after["has_published_disclosure_packet"] is False
    assert_money_cents(
        after["outstanding_penalty_cents_total"],
        0,
        "outstanding_penalty_cents_total",
    )

    brand = env.read_brand()
    for field in (
        "coverage_status",
        "coverage_reason",
        "counted_unit_count",
        "standard_item_count",
        "compliance_posture",
        "has_published_disclosure_packet",
    ):
        assert after[field] == brand[field], (
            f"summary.{field} must agree with the brand row: "
            f"{after[field]!r} against {brand[field]!r}"
        )
