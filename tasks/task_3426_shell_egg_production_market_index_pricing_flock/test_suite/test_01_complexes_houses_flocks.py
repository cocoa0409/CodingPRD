"""Complex, house and flock provisioning: creation defaults, field round-trips,
pagination, not-found codes and payload-shape rejections.
"""

from test_helpers import (
    ADMIN,
    PLANNER,
    NON_EXISTENT_UUID,
    api_client,
    assert_complex,
    assert_flock,
    assert_house,
    assert_instant_equal,
    create_complex,
    create_flock_payload,
    create_house,
    create_planned_flock,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


def test_complex_create_returns_computed_defaults(api):
    """A complex created with only its three input fields returns 201 with the
    derived posture, zeroed inventory buckets and a zeroed ops counter.

    PRD §3.1: "A freshly created complex starts with posture `NORMAL`, every
    inventory bucket at zero — the non-organic pools `corn_inventory_tons` and
    `soy_inventory_tons`, the organic-certified pools
    `corn_organic_inventory_tons` and `soy_organic_inventory_tons`, and the
    three ungraded egg buckets `ungraded_conventional_dozen`,
    `ungraded_cage_free_dozen`, and `ungraded_organic_dozen` — an
    `ops_run_index` of 0, and a `last_ops_run_at` equal to its own
    `created_at`."
    PRD §2.5: "`version` — an integer starting at 1 on creation and
    incrementing on every mutation of the resource".
    PRD §2.4: "Before any call to the clock-setting capability, the server's
    logical clock reads exactly `2026-09-01T00:00:00Z`".

    Design: Corner/entities/complex_create_returns_computed_defaults
    """
    # No clock call: the logical clock starts at its documented default.
    data = validate_success(
        api.create_complex(
            {
                "name": "Heartland Layers",
                "region_code": "MIDWEST",
                "mill_receiving_tons_per_day": 100,
            },
            ADMIN,
        ),
        201,
    )
    assert_complex(data)
    assert is_valid_uuid(data["id"])
    assert data["biosecurity_posture"] == "NORMAL"
    for field in (
        "corn_inventory_tons", "corn_organic_inventory_tons",
        "soy_inventory_tons", "soy_organic_inventory_tons",
        "ungraded_conventional_dozen", "ungraded_cage_free_dozen",
        "ungraded_organic_dozen",
    ):
        assert data[field] == 0, f"{field} must start at 0, got {data[field]}"
    assert data["ops_run_index"] == 0
    assert data["version"] == 1
    assert_instant_equal(data["created_at"], "2026-09-01T00:00:00Z", "created_at")
    assert_instant_equal(
        data["last_ops_run_at"], data["created_at"], "last_ops_run_at"
    )


def test_house_get_roundtrip_all_fields(api):
    """Every stored house field round-trips through GET unchanged.

    PRD §3.1: "Each house takes an operator-assigned `house_code` unique
    within its complex, a `housing_style` of `CONVENTIONAL`, `CAGE_FREE`, or
    `ORGANIC`, and a positive `capacity_hens` ceiling. The house's
    `hen_inventory` begins at zero and is always the sum of
    `current_hen_count` over the house's flocks in `GROWING`, `LAYING`, or
    `MOLT`; its `downtime_until` stays null until a depopulation completes".

    Design: Corner/entities/house_get_roundtrip_all_fields
    """
    complex_ = create_complex()
    created = create_house(
        complex_["id"], house_code="H2", housing_style="CAGE_FREE",
        capacity_hens=80_000,
    )

    house = validate_success(api.get_house(created["id"], PLANNER))
    assert_house(house)
    assert house["house_code"] == "H2"
    assert house["housing_style"] == "CAGE_FREE"
    assert house["capacity_hens"] == 80_000
    assert house["complex_id"] == complex_["id"]
    assert house["hen_inventory"] == 0
    assert house["downtime_until"] is None


def test_flocks_list_paginates_total_count_and_has_more(api):
    """A paged flock list reports total_count over the whole filtered set.

    PRD §2.3: "The `limit` parameter caps the number of returned items; it
    defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100.
    The `offset` parameter skips a number of items from the front of the
    result set and defaults to 0."
    PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."
    PRD §3.2: "Flock lists filter by `status` and `program`."

    Design: Corner/entities/flocks_list_paginates_total_count_and_has_more
    """
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=200_000)
    # Exactly 560 days apart: the half-open occupancy windows abut.
    for code, placement in (
        ("F1", "2026-12-01T00:00:00Z"),
        ("F2", "2028-06-13T00:00:00Z"),
        ("F3", "2029-12-25T00:00:00Z"),
    ):
        create_planned_flock(
            house["id"], flock_code=code, placement_date=placement,
            placed_hen_count=40_000,
        )

    page1, meta1 = validate_paginated(
        api.list_flocks(house["id"], PLANNER, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_flocks(house["id"], PLANNER, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    page_default, meta_default = validate_paginated(
        api.list_flocks(house["id"], PLANNER)
    )
    assert len(page_default) == 3
    assert meta_default["limit"] == 10
    assert meta_default["offset"] == 0

    planned, _ = validate_paginated(
        api.list_flocks(house["id"], PLANNER, params={"status": "PLANNED"})
    )
    assert len(planned) == 3
    laying, _ = validate_paginated(
        api.list_flocks(house["id"], PLANNER, params={"status": "LAYING"})
    )
    assert laying == []


def test_flock_get_unknown_id_returns_404(api):
    """An unallocated flock id yields the entity-specific 404.

    PRD §2.9: "Each resource family has its own not-found error:
    `ERR_COMPLEX_NOT_FOUND`, `ERR_HOUSE_NOT_FOUND`, `ERR_FLOCK_NOT_FOUND`,
    `ERR_CERTIFICATION_NOT_FOUND`, `ERR_DISEASE_EVENT_NOT_FOUND`,
    `ERR_DEPOPULATION_ORDER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_COMMITMENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_SETTLEMENT_NOT_FOUND`, `ERR_FEED_CONTRACT_NOT_FOUND`,
    `ERR_PACKING_RUN_NOT_FOUND`, and `ERR_CAPITAL_PROJECT_NOT_FOUND`."

    Design: Corner/entities/flock_get_unknown_id_returns_404
    """
    error = validate_error(
        api.get_flock(NON_EXISTENT_UUID, PLANNER), ERR.ERR_FLOCK_NOT_FOUND
    )
    assert isinstance(error.get("message"), str) and error["message"]


def test_flock_create_missing_program_returns_invalid_request(api):
    """program is a required input with no default; omitting it is a 400.

    PRD §3.2: "A `ProductionPlanner` plans a **flock** — a scheduled pullet
    placement — against a specific house, supplying a `flock_code` unique
    within the complex, a `program` of `CONVENTIONAL`, `CAGE_FREE`, or
    `ORGANIC`, an `ownership` of `OWNED` or `CONTRACT`, the scheduled
    `placement_date`, and a positive `placed_hen_count`."
    PRD §2.11: "(6) payload shape — required fields present, types and enum
    members valid, no undeclared payload fields, windows whose start must
    precede their end — reported as `ERR_INVALID_REQUEST`".

    Design: Corner/entities/flock_create_missing_program_returns_invalid_request
    """
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)

    response = api.create_flock(
        house["id"],
        {
            "flock_code": "F1",
            "ownership": "OWNED",
            "placement_date": "2026-09-01T00:00:00Z",
            "placed_hen_count": 10_000,
        },
        PLANNER,
    )
    validate_error(response, ERR.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(api.list_flocks(house["id"], PLANNER))
    assert rows == [] and meta["total_count"] == 0


def test_flock_create_invalid_enum_returns_invalid_request(api):
    """The near-miss program string 'CAGE-FREE' is a 400, not a 422.

    PRD §3.2: "a `program` of `CONVENTIONAL`, `CAGE_FREE`, or `ORGANIC`".
    PRD §2.11: "(6) payload shape — required fields present, types and enum
    members valid, no undeclared payload fields, windows whose start must
    precede their end — reported as `ERR_INVALID_REQUEST`".

    Design: Corner/entities/flock_create_invalid_enum_returns_invalid_request
    """
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)

    response = api.create_flock(
        house["id"],
        {
            "flock_code": "F1",
            "program": "CAGE-FREE",
            "ownership": "OWNED",
            "placement_date": "2026-09-01T00:00:00Z",
            "placed_hen_count": 10_000,
        },
        PLANNER,
    )
    validate_error(response, ERR.ERR_INVALID_REQUEST)
    rows, _ = validate_paginated(api.list_flocks(house["id"], PLANNER))
    assert rows == []


def test_complex_create_with_posture_field_returns_invalid_request(api):
    """biosecurity_posture is server-derived; supplying it is a 400.

    PRD §2.7: "A complex's `biosecurity_posture` is never assigned directly;
    it is derived from disease events."
    PRD §2.11: "(6) payload shape — required fields present, types and enum
    members valid, no undeclared payload fields, windows whose start must
    precede their end — reported as `ERR_INVALID_REQUEST`".

    Design: Corner/entities/complex_create_with_posture_field_returns_invalid_request
    """
    response = api.create_complex(
        {
            "name": "Sneaky Farm",
            "region_code": "WEST",
            "mill_receiving_tons_per_day": 100,
            "biosecurity_posture": "NORMAL",
        },
        ADMIN,
    )
    validate_error(response, ERR.ERR_INVALID_REQUEST)


def test_house_create_under_unknown_complex_returns_404(api):
    """The nested create resolves its parent path segment first.

    PRD §2.9: "Requests that address nested resources are validated strictly
    left to right along the path: the server resolves the first identifier,
    then the next, and rejects with the 404 belonging to the *first*
    identifier that does not resolve, without examining the rest of the path."

    Design: Corner/entities/house_create_under_unknown_complex_returns_404
    """
    response = api.create_house(
        NON_EXISTENT_UUID,
        {
            "house_code": "H1",
            "housing_style": "CONVENTIONAL",
            "capacity_hens": 50_000,
        },
        ADMIN,
    )
    validate_error(response, ERR.ERR_COMPLEX_NOT_FOUND)
