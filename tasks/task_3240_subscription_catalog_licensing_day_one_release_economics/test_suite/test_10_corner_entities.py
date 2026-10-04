"""Breadth coverage of the create/read/list contract for the catalogue's
first-class resources."""
import pytest

from test_helpers import (
    TEST_USERS,
    NON_EXISTENT_UUID,
    create_publisher,
    create_region,
    create_title,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def test_region_create_returns_the_stored_configuration(api):
    """PRD §3.1: "Regions are created by supplying a `region_code` that must be unique, an ISO 4217 `currency_code`, a
    strictly positive `price_multiplier`, an `availability_ceiling_titles` of at least one, and a
    `catalog_tier_floor`."
    PRD §2.5: "A `Region` and an `EngagementEvent` are created with only `id`
    and `created_at`: neither carries `updated_at` nor `version`".

    Design: Corner/entities/region_create_returns_the_stored_configuration_with_zeroed_capacity
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    region = validate_success(
        api.create_region(
            {
                "region_code": "NA",
                "currency_code": "USD",
                "price_multiplier": 1.20,
                "availability_ceiling_titles": 4000,
                "catalog_tier_floor": "ESSENTIAL",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert region["region_code"] == "NA"
    assert region["currency_code"] == "USD"
    assert region["price_multiplier"] == pytest.approx(1.20, abs=0.0001)
    assert region["availability_ceiling_titles"] == 4000
    assert region["catalog_tier_floor"] == "ESSENTIAL"
    assert "version" not in region, "Region carries no version field"
    assert "updated_at" not in region, "Region carries no updated_at field"


def test_a_fresh_region_reports_zero_requirement_and_full_headroom(api):
    """PRD §3.7: "On the supply side, usable slots are the region's
    `availability_ceiling_titles` multiplied by 30".
    PRD §3.7: "The deficit, exposed as `capacity_deficit_slots`, is the raw
    requirement minus the usable slots, so a negative deficit means headroom."

    Design: Corner/entities/region_create_returns_the_stored_configuration_with_zeroed_capacity
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    validate_success(
        api.create_region(
            {
                "region_code": "NA",
                "currency_code": "USD",
                "price_multiplier": 1.20,
                "availability_ceiling_titles": 4000,
                "catalog_tier_floor": "ESSENTIAL",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    region = validate_success(api.get_region("NA", ADMIN))
    assert region["capacity_required_slots"] == pytest.approx(200.00, abs=0.01), \
        "no entry contributes base or spike slots, but the region still carries " \
        "its fixed 200-slot overhead"
    assert region["capacity_usable_slots"] == pytest.approx(120000.00, abs=0.01), \
        "4000 titles times thirty slots per ceiling unit"
    assert region["capacity_deficit_slots"] == pytest.approx(-119800.00, abs=0.01)
    assert region["capacity_status"] == "WITHIN_CAPACITY"


def test_publisher_read_exposes_the_rollup_figures(api):
    """PRD §3.1: "A newly registered publisher is `ACTIVE` with a `deal_count` of zero and a `lifetime_licensing_cost_cents` of zero".

    Design: Corner/entities/publisher_get_returns_the_rollup_figures_and_rejects_an_unknown_id
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    publisher = create_publisher(api)
    read = validate_success(api.get_publisher(publisher["id"], ADMIN))
    assert read["status"] == "ACTIVE"
    assert read["deal_count"] == 0
    assert read["lifetime_licensing_cost_cents"] == pytest.approx(0.00, abs=0.01)
    assert read["name"] == publisher["name"]


def test_an_unallocated_publisher_id_yields_the_entity_specific_404(api):
    """PRD §2.4: "A path or body identifier that names no `Publisher` is
    rejected with `ERR_PUBLISHER_NOT_FOUND` (404)."

    Design: Corner/entities/publisher_get_returns_the_rollup_figures_and_rejects_an_unknown_id
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    create_publisher(api)
    validate_error(api.get_publisher(NON_EXISTENT_UUID, ADMIN),
                   "ERR_PUBLISHER_NOT_FOUND")


def test_title_listing_is_paged_and_filtered_by_publisher(api):
    """PRD §2.3: "`limit` is the maximum number of entries to return; when it is
    not supplied it defaults to 10, and it must lie between 1 and 100 inclusive.
    `offset` is the number of matching entries to skip and defaults to 0 when
    omitted."
    PRD §2.3: "`total_count` is the number of matching resources before paging
    and `has_more` states whether further matches exist beyond the returned
    window."

    Design: Corner/entities/titles_list_paginates_and_filters_by_publisher
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    first = create_publisher(api, name="Nova Interactive")
    second = create_publisher(api, name="Halcyon Works")
    create_title(api, first["id"], name="Crimson Drift", platform_set=["CONSOLE", "PC"],
                 day_one_eligible=True, list_price_cents=7000, unit_sales_30d=25000)
    create_title(api, first["id"], name="Second Wind", platform_set=["PC"],
                 day_one_eligible=False, list_price_cents=4000, unit_sales_30d=9000)
    create_title(api, second["id"], name="Static Vale", platform_set=["PC", "CLOUD"],
                 day_one_eligible=False, list_price_cents=4000, unit_sales_30d=8000)

    page_one, meta_one = validate_paginated(
        api.list_titles(ANALYST, params={"limit": 2, "offset": 0})
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        api.list_titles(ANALYST, params={"limit": 2, "offset": 2})
    )
    assert len(page_two) == 1
    assert meta_two["has_more"] is False

    filtered, meta_filtered = validate_paginated(
        api.list_titles(ANALYST, params={"publisher_id": second["id"], "limit": 10, "offset": 0})
    )
    assert len(filtered) == 1
    assert filtered[0]["name"] == "Static Vale"
    assert meta_filtered["total_count"] == 1, \
        "the filter narrows the count, not just the page"

    defaulted, meta_default = validate_paginated(api.list_titles(ANALYST))
    assert len(defaulted) == 3
    assert meta_default["limit"] == 10 and meta_default["offset"] == 0, \
        "an unsupplied limit defaults to 10 and an unsupplied offset to 0"
    for row in defaulted:
        assert row["status"] == "DRAFT"


def test_title_create_without_publisher_id_is_a_request_format_failure(api):
    """PRD §3.1: "Titles are registered against a publisher under a `name`".
    PRD §2.11: "a permitted-role request with a missing or undeclared body field
    is rejected with `ERR_INVALID_REQUEST` (400) before any identifier is
    resolved".

    Design: Corner/entities/title_create_missing_publisher_id_returns_invalid_request
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    create_publisher(api)
    validate_error(
        api.create_title(
            {"name": "Orphan Title", "platform_set": ["PC"], "day_one_eligible": False,
             "list_price_cents": 4000},
            ADMIN,
        ),
        "ERR_INVALID_REQUEST",
    )
    rows, meta = validate_paginated(api.list_titles(ANALYST))
    assert rows == []
    assert meta["total_count"] == 0, "the rejected create persisted nothing"


def test_title_create_defaults_the_optional_commercial_inputs(api):
    """PRD §3.1: "`day_one_eligible`, a boolean defaulting to false that
    declares whether the title is even a candidate for a day-one catalogue
    release; `list_price_cents`, a non-negative whole-cent global default unit
    sale price before any regional adjustment; and `unit_sales_30d`, an integer
    defaulting to zero".
    PRD §3.1: "A new title starts in `DRAFT` status and with a
    `weighted_engagement_score` of zero".

    Design: Corner/entities/title_create_defaults_day_one_eligible_and_unit_sales
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    publisher = create_publisher(api)
    title = validate_success(
        api.create_title(
            {"publisher_id": publisher["id"], "name": "Quiet Harbor",
             "platform_set": ["PC"], "list_price_cents": 2000},
            ADMIN,
        ),
        expected_status=201,
    )
    assert title["day_one_eligible"] is False, "the flag defaults to false"
    assert title["unit_sales_30d"] == 0, "the baseline defaults to zero"
    assert title["weighted_engagement_score"] == pytest.approx(0.00, abs=0.01), \
        "no catalogue entries contribute yet"

    read = validate_success(api.get_title(title["id"], ADMIN))
    assert read["status"] == "DRAFT"