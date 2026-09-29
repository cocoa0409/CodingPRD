"""Two windows contending for one resource, under two opposite interval semantics.

Half-open grant windows that meet at an instant are adjacent and both live; closed
shelf windows that meet at an instant genuinely coexist there and must be summed.
"""
from test_helpers import (
    HEADERS_ASSORTMENT_PLANNER,
    HEADERS_COMPLIANCE_OFFICER,
    HEADERS_FUND_CONTROLLER,
    constants as C,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def _scene_two_adjacent_grants(api):
    """One sponsor and delegate holding [08-01, 08-10) and [08-10, 08-20)."""
    sponsor = fx.create_patron(api, full_name="CPO R Halvorsen", id_card_class="ACTIVE_DUTY")
    delegate = fx.create_patron(
        api, full_name="T Halvorsen", id_card_class="DEPENDENT", sponsor_patron_id=sponsor["id"]
    )
    first_response = api.create_delegation(
        factories.delegation_payload(
            sponsor_patron_id=sponsor["id"],
            delegate_patron_id=delegate["id"],
            expected_delegate_patron_version=delegate["version"],
            valid_from=C.AUG_01,
            valid_to=C.AUG_10,
            per_sale_spend_cap_cents=40000,
        ),
        HEADERS_COMPLIANCE_OFFICER,
    )
    first = validate_success(first_response, 201)
    delegate_v1 = validate_success(api.get_patron(delegate["id"], HEADERS_COMPLIANCE_OFFICER))
    second_response = api.create_delegation(
        factories.delegation_payload(
            sponsor_patron_id=sponsor["id"],
            delegate_patron_id=delegate["id"],
            expected_delegate_patron_version=delegate_v1["version"],
            valid_from=C.AUG_10,
            valid_to=C.AUG_20,
            per_sale_spend_cap_cents=40000,
        ),
        HEADERS_COMPLIANCE_OFFICER,
    )
    second = validate_success(second_response, 201)
    delegate_v2 = validate_success(api.get_patron(delegate["id"], HEADERS_COMPLIANCE_OFFICER))
    return {
        "sponsor": sponsor,
        "delegate": delegate,
        "first": first,
        "second": second,
        "second_status": second_response.status_code,
        "delegate_v2": delegate_v2,
    }


def test_grants_meeting_at_one_instant_are_adjacent_and_both_stay_active(api):
    """[08-01, 08-10) and [08-10, 08-20) coexist, neither superseding the other.

    PRD 3.3: "Because windows are half-open, two grants that merely meet at an
    endpoint are adjacent rather than overlapping and are perfectly legal — a grant
    running to a given instant and a grant starting at that same instant coexist
    happily."
    PRD 3.3: "The window is expressed by `valid_from` and `valid_to`, both ISO 8601
    UTC instants, and it is **half-open**: the grant covers an instant when
    `valid_from` is at or before that instant and `valid_to` is strictly after it."

    Design: Difficulty/resource_temporal_overlap/same_pair_delegation_windows_half_open_adjacent_allowed_overlap_rejected
    """
    scene = _scene_two_adjacent_grants(api)
    assert scene["second_status"] == 201

    first = validate_success(api.get_delegation(scene["first"]["id"], HEADERS_COMPLIANCE_OFFICER))
    second = validate_success(api.get_delegation(scene["second"]["id"], HEADERS_COMPLIANCE_OFFICER))
    assert first["status"] == "ACTIVE"
    assert first["superseded_by_delegation_id"] is None
    assert second["status"] == "ACTIVE"
    assert second["superseded_by_delegation_id"] is None

    _rows, meta = validate_paginated(
        api.list_delegations(
            {"delegate_patron_id": scene["delegate"]["id"], "status": "ACTIVE"},
            HEADERS_COMPLIANCE_OFFICER,
        )
    )
    assert meta["total_count"] == 2


def test_a_third_grant_straddling_both_windows_is_rejected_and_bumps_nothing(api):
    """[08-05, 08-15) intersects both interiors, so it collides and writes nothing.

    PRD 3.3: "Two grants whose interiors intersect collide, and the new one is
    rejected with `ERR_DELEGATION_WINDOW_OVERLAP` (HTTP 409)."
    PRD 2.7: "A successful grant itself increments the delegate patron's `version`
    by 1."

    Design: Difficulty/resource_temporal_overlap/same_pair_delegation_windows_half_open_adjacent_allowed_overlap_rejected
    """
    scene = _scene_two_adjacent_grants(api)

    response = api.create_delegation(
        factories.delegation_payload(
            sponsor_patron_id=scene["sponsor"]["id"],
            delegate_patron_id=scene["delegate"]["id"],
            expected_delegate_patron_version=scene["delegate_v2"]["version"],
            valid_from=C.AUG_05,
            valid_to=C.AUG_15,
            per_sale_spend_cap_cents=40000,
        ),
        HEADERS_COMPLIANCE_OFFICER,
    )
    validate_error(response, "ERR_DELEGATION_WINDOW_OVERLAP", 409)

    delegate = validate_success(
        api.get_patron(scene["delegate"]["id"], HEADERS_COMPLIANCE_OFFICER)
    )
    assert delegate["version"] == scene["delegate_v2"]["version"]


def _scene_sixteen_facings_on_a_closed_window(api):
    """A 24-facing shelf block already holding 16 facings over [08-01, 08-10]."""
    store = fx.create_store(
        api,
        name="Yokota Commissary",
        channel="COMMISSARY",
        region="OVERSEAS",
        surcharge_rate_bp=500,
        shelf_block_capacity_facings=24,
    )
    product_c = fx.create_product(
        api,
        sku="SKU-GRO-M31",
        name="Rolled Oats 3lb",
        category="GROCERY_STAPLE",
        unit_cost_cents=320,
    )
    product_d = fx.create_product(
        api,
        sku="SKU-GRO-M32",
        name="Peanut Butter 40oz",
        category="GROCERY_STAPLE",
        unit_cost_cents=410,
    )
    assortment_c = fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product_c["id"],
        shelf_block="M3",
        facings=16,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_10,
        expected_store_version=store["version"],
    )
    return {
        "store": store,
        "store_after_first": fx.read_store(api, store["id"]),
        "product_c": product_c,
        "product_d": product_d,
        "assortment_c": assortment_c,
    }


def test_closed_windows_touching_at_one_instant_overlap_and_breach_capacity(api):
    """[08-01, 08-10] and [08-10, 08-20] share 08-10, so 16 + 16 exceeds 24.

    PRD 3.4: "The closed interval has a consequence that trips people up: two
    allocations that merely touch at a single endpoint instant *do* overlap, because
    that shared instant belongs to both of them."
    PRD 3.4: "A sum exactly equal to capacity passes; anything above it is rejected
    with `ERR_SHELF_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/closed_window_assortments_touching_at_endpoint_exceed_shelf_capacity
    """
    scene = _scene_sixteen_facings_on_a_closed_window(api)

    response = api.create_assortment(
        factories.assortment_payload(
            store_id=scene["store"]["id"],
            product_id=scene["product_d"]["id"],
            expected_store_version=scene["store_after_first"]["version"],
            shelf_block="M3",
            facings=16,
            supply_mode="WAREHOUSE",
            effective_from=C.AUG_10,
            effective_to=C.AUG_20,
        ),
        HEADERS_ASSORTMENT_PLANNER,
    )
    validate_error(response, "ERR_SHELF_CAPACITY_EXCEEDED", 409)


def test_the_rejected_allocation_is_absent_and_leaves_the_store_version_alone(api):
    """The block still lists one allocation and the store's version did not move.

    PRD 3.4: "For the target pairing of `store_id` and `shelf_block`, the system
    adds up `facings` over every `ACTIVE` allocation whose closed window intersects
    the incoming closed window, adds the incoming `facings` to that sum, and
    requires the result to be no greater than the store's
    `shelf_block_capacity_facings`."
    PRD 2.7: "A successful allocation itself increments that store's `version` by 1,
    so a client creating several allocations against one store must re-read the
    store between writes."

    Design: Difficulty/resource_temporal_overlap/closed_window_assortments_touching_at_endpoint_exceed_shelf_capacity
    """
    scene = _scene_sixteen_facings_on_a_closed_window(api)

    validate_error(
        api.create_assortment(
            factories.assortment_payload(
                store_id=scene["store"]["id"],
                product_id=scene["product_d"]["id"],
                expected_store_version=scene["store_after_first"]["version"],
                shelf_block="M3",
                facings=16,
                supply_mode="WAREHOUSE",
                effective_from=C.AUG_10,
                effective_to=C.AUG_20,
            ),
            HEADERS_ASSORTMENT_PLANNER,
        ),
        "ERR_SHELF_CAPACITY_EXCEEDED",
        409,
    )

    rows, meta = validate_paginated(
        api.list_assortments(
            {"store_id": scene["store"]["id"], "shelf_block": "M3"}, HEADERS_ASSORTMENT_PLANNER
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == scene["assortment_c"]["id"]
    assert rows[0]["facings"] == 16
    assert rows[0]["status"] == "ACTIVE"

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["version"] == scene["store_after_first"]["version"]
