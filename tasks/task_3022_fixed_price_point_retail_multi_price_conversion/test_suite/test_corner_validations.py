"""Authentication order, request-shape order, unique keys and the aggregate release bound."""


from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    BUYER_HEADERS,
    DCO_HEADERS,
    E,
    SOM_HEADERS,
    api_client,
    build_user_headers,
    validate_error,
    validate_success,
    fixtures,
)

AUTH_QUOTE = (
    "Every request to the merchandise API must carry two mandatory headers. `X-User-ID` "
    "identifies the acting party and `X-User-Role` declares the operational capacity in which "
    "that party is acting. If either header is absent, or if `X-User-Role` is not one of the "
    "seven declared roles, the request is rejected with `ERR_MISSING_USER_CONTEXT` and an HTTP "
    "401 response."
)
ROLE_QUOTE = (
    "Independently of authentication, every endpoint declares the set of roles permitted to call "
    "it; a request whose role is authenticated but not listed for that endpoint is rejected with "
    "`ERR_INSUFFICIENT_ROLE` and an HTTP 403 response."
)
ORDER_QUOTE = (
    "These two checks run before any resource lookup or business rule, and they apply to every "
    "endpoint in the catalogue without exception."
)
SHAPE_QUOTE = (
    "declared request-shape constraints such as a count below its floor, an upper bound not "
    "strictly after its lower bound, a `to_price_point_id` equal to its `from_price_point_id`, a "
    "`decision` outside `RETAIN` and `DELETE`, or a `method` outside `FREIGHT_PASS_THROUGH` and "
    "`VENDOR_PRICE_CHANGE`, all reported as `ERR_INVALID_REQUEST` at HTTP 400"
)
UNIQUE_QUOTE = (
    "unique-key collisions on item SKU, vendor name, store number and container number, reported "
    "as `ERR_DUPLICATE_SKU` at HTTP 409"
)
STATE_CTA_QUOTE = (
    "the acting resource's required source state, checked against the `from` state its transition "
    "declares and reported with that transition's state error at HTTP 409"
)
RELEASE_BOUND_QUOTE = (
    "A release carries a `release_units` value that must be at least one and must not exceed the "
    "line's current `remaining_units`; a value above the remainder is rejected with "
    "`ERR_RELEASE_EXCEEDS_ALLOCATION` and HTTP 422, and a value below one is refused as malformed."
)
RELEASE_HOP_QUOTE = (
    "adds the same quantity to the item's `on_hand_units`, from which the item's "
    "`is_shelf_overflow` flag is recomputed as on-hand units multiplied by `sqft_per_unit` being "
    "greater than `shelf_package_capacity`."
)
LANDED_STATE_QUOTE = (
    "The item moves from `PRICE_ASSIGNED` into `COST_PENDING`, and from that point the cost may "
    "be revised any number of times while the item has not yet been cleared to sell"
)
NOT_PRICE_ASSIGNED_QUOTE = (
    "The item moves from `PRICE_ASSIGNED` into `COST_PENDING`"
)
IDEMPOTENT_QUOTE = (
    "a `COST_PENDING` item accepts further landed-cost applications that leave it in "
    "`COST_PENDING`, each one appending a fresh history row and re-deriving the item's cost fields"
)


def test_the_clock_endpoint_separates_missing_context_from_an_unauthorized_role(api):
    """Absent headers are a 401; a well-formed but unlisted role is a 403.

    PRD §2.1: "Every request to the merchandise API must carry two mandatory headers. `X-User-ID`
    identifies the acting party and `X-User-Role` declares the operational capacity in which that
    party is acting. If either header is absent, or if `X-User-Role` is not one of the seven
    declared roles, the request is rejected with `ERR_MISSING_USER_CONTEXT` and an HTTP 401
    response."
    PRD §2.1: "Independently of authentication, every endpoint declares the set of roles permitted
    to call it; a request whose role is authenticated but not listed for that endpoint is rejected
    with `ERR_INSUFFICIENT_ROLE` and an HTTP 403 response."
    PRD §2.1: "These two checks run before any resource lookup or business rule, and they apply to
    every endpoint in the catalogue without exception."

    Design: Corner/validations/clock_endpoint_requires_the_platform_admin_role
    """
    unauthorized = api.set_clock("2026-10-01T00:00:00Z", BUYER_HEADERS)
    validate_error(unauthorized, E.ERR_INSUFFICIENT_ROLE.value)
    assert unauthorized.json()["data"]["error_id"] != E.ERR_MISSING_USER_CONTEXT.value, (
        "the headers were present, so the authentication check passed and the role check decided"
    )

    validate_error(
        api.set_clock("2026-10-01T00:00:00Z", build_user_headers("", "")),
        E.ERR_MISSING_USER_CONTEXT.value,
    )

    allowed = validate_success(api.set_clock("2026-10-01T00:00:00Z", ADMIN_HEADERS), 200)
    assert allowed["current_utc"].startswith("2026-10-01T00:00:00")


def test_a_broken_request_shape_is_answered_before_the_item_state_is_examined(api):
    """A landed-cost write on a wrong-state item is decided by the source-state check.

    PRD §2.8: "The full precedence chain, from first to last, is: the two authentication checks
    of §2.1; path-identifier resolution, left to right; body foreign-key resolution, in declared
    order; the acting resource's required source state, checked against the `from` state its
    transition declares and reported with that transition's state error at HTTP 409; ... declared
    request-shape constraints such as ... a `method` outside `FREIGHT_PASS_THROUGH` and
    `VENDOR_PRICE_CHANGE`, all reported as `ERR_INVALID_REQUEST` at HTTP 400"
    PRD §3.2: "The item moves from `PRICE_ASSIGNED` into `COST_PENDING`"

    The state check is listed before the shape check, so a request that is BOTH malformed and
    aimed at a DENOMINATED item reports the state error, not the shape error.

    Design: Corner/validations/required_field_omission_beats_state_precondition_on_landed_costs
    """
    fixtures.set_clock()
    vendor = fixtures.create_vendor()
    item = fixtures.create_item(vendor["id"], sku="1001", base_landed_cost_cents=105)

    shape_broken = api.apply_landed_cost(item["id"], {"method": "VENDOR_PRICE_CHANGE"}, BUYER_HEADERS)
    validate_error(shape_broken, E.ERR_ITEM_NOT_PRICE_ASSIGNED.value)
    assert shape_broken.json()["data"]["error_id"] != E.ERR_INVALID_REQUEST.value, (
        "the source-state check runs before the declared request-shape check"
    )

    well_formed = api.apply_landed_cost(
        item["id"], {"method": "VENDOR_PRICE_CHANGE", "applied_amount_cents": 105}, BUYER_HEADERS)
    validate_error(well_formed, E.ERR_ITEM_NOT_PRICE_ASSIGNED.value)

    read = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert read["status"] == "DENOMINATED"
    assert read["landed_cost_cents"] == 0
    assert validate_success(api.list_item_landed_costs(item["id"], ANALYST_HEADERS), 200) == []


def test_a_repeated_store_number_is_rejected_at_the_unique_key_check(api):
    """A second store on a taken number is a 409, and the first row is left alone.

    PRD §2.8: "unique-key collisions on item SKU, vendor name, store number and container number,
    reported as `ERR_DUPLICATE_SKU` at HTTP 409"
    PRD §3.8: "A store is registered by a `StoreOperationsManager` with a `store_number` that must
    be unique and a `shelf_facing_capacity_sqft` that is the total shelf facing it can commit
    across concurrent aisle resets."

    Design: Corner/validations/duplicate_store_number_is_rejected_at_the_unique_key_priority
    """
    fixtures.set_clock()
    store = fixtures.create_store(store_number="1927", shelf_facing_capacity_sqft=400.0)

    duplicate = api.create_store(
        {"store_number": "1927", "shelf_facing_capacity_sqft": 300.0}, SOM_HEADERS)
    validate_error(duplicate, E.ERR_DUPLICATE_SKU.value)

    stores = validate_success(api.list_stores(ANALYST_HEADERS), 200)
    assert len(stores) == 1, "the duplicate never persisted"
    assert stores[0]["id"] == store["id"]
    assert stores[0]["shelf_facing_capacity_sqft"] == 400.0, (
        "the second attempt did not overwrite the first row"
    )


def test_releasing_exactly_the_remainder_passes_and_one_unit_more_is_refused(api):
    """The bound is the line's remaining units, and a refused over-release moves no stock.

    PRD §3.7: "A release carries a `release_units` value that must be at least one and must not
    exceed the line's current `remaining_units`; a value above the remainder is rejected with
    `ERR_RELEASE_EXCEEDS_ALLOCATION` and HTTP 422, and a value below one is refused as malformed."
    PRD §3.7: "adds the same quantity to the item's `on_hand_units`, from which the item's
    `is_shelf_overflow` flag is recomputed as on-hand units multiplied by `sqft_per_unit` being
    greater than `shelf_package_capacity`."

    Design: Corner/validations/release_units_above_the_line_allocation_is_rejected
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    item = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="1001", sqft_per_unit=0.1,
        shelf_package_capacity=4.0)
    container = fixtures.create_received_container(vendor["id"], total_freight_cents=0)
    line = fixtures.allocate(container["id"], store["id"], item["id"],
                             sequence=1, requested_units=40)

    over = api_client.release_allocation_line(line["id"], 41, DCO_HEADERS)
    validate_error(over, E.ERR_RELEASE_EXCEEDS_ALLOCATION.value)
    assert validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)["on_hand_units"] == 0, (
        "the refused over-release added nothing to the shelf"
    )

    below_floor = api_client.release_allocation_line(line["id"], 0, DCO_HEADERS)
    validate_error(below_floor, E.ERR_INVALID_REQUEST.value)

    exact = validate_success(api_client.release_allocation_line(line["id"], 40, DCO_HEADERS), 200)
    assert exact["status"] == "RELEASED"
    assert exact["released_units"] == 40
    assert exact["remaining_units"] == 0

    read = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert read["on_hand_units"] == 40