"""Validation precedence, request shape, authentication and the ownership lattice."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN,
    ApiErrorId,
    ANON,
    build_order,
    make_bid,
    make_center,
    make_customer,
    make_customer_headers,
    make_lot,
    make_lot_ready,
    make_order_buildable,
    make_operator_headers,
    make_subscription,
    make_supplier,
    make_supplier_headers,
    reset_clock,
    setup_box_scenario,
    setup_center_supplier_lot,
    setup_subscriber,
)
from test_helpers.fixtures import (
    award_lot,
    file_claim,
    line_plan,
    order_items,
    pack_order,
    refresh_lot,
    refresh_order,
)


def _award_and_ready(api, lot, supplier):
    make_bid(api, lot["id"], supplier["id"], cost=100,
             quantity=lot["quantity_available"])
    return make_lot_ready(api, award_lot(api, lot), "PASS")


# ---------------------------------------------------------------------------
# The precedence pair: allergen exclusion outranks the version check
# ---------------------------------------------------------------------------
def test_allergen_conflict_outranks_the_stale_version_check(api):
    """PRD §3.9: "Sixth is allergen exclusion: no lot whose `allergen_codes`
    intersect the customer's `dietary_allergy_codes` may be drawn into a box or
    left inside one, and the offence is refused with `ERR_ALLERGEN_CONFLICT`
    and HTTP status 422 on both the build and the finalise operations."
    PRD §3.9: "when more than one check could legitimately fail, the one that
    sits earliest in this ordering is the one that produces the response"

    Design: Difficulty/priority_pair_validation_conflict/allergen_conflict_outranks_the_stale_version_check
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE", max_concurrent_building_cycles=5)
    supplier = make_supplier(api, name="Peanut Lane Farms", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                   procurement_grade="SURPLUS", unit_weight_grams=200,
                   unit_cost_cents=100, quantity_available=200,
                   allergen_codes=["PEANUT"])
    lot = _award_and_ready(api, lot, supplier)
    customer, subscription = setup_subscriber(
        api, region="NE", email="peanut@example.com",
        dietary_allergy_codes=["PEANUT", "SHELLFISH"],
    )
    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )

    buildable = make_order_buildable(api, order, center)
    assert buildable["status"] == "READY_TO_BUILD", (
        "Setup failed: the order must be buildable before the precedence probe"
    )
    assert lot["quality_status"] == "PASS" and lot["status"] == "READY"
    response = api.build_box_order(
        buildable["id"],
        {"expected_box_order_version": buildable["version"] - 1,
         "line_plan": line_plan((lot["id"], 8))},
        make_operator_headers(center["id"]),
    )
    error = validate_error(response, ApiErrorId.ERR_ALLERGEN_CONFLICT, 422)
    assert error["error_id"] != "ERR_STALE_VERSION"

    read = refresh_order(api, buildable)
    assert read["status"] == "READY_TO_BUILD"
    assert read["version"] == buildable["version"]
    assert len(order_items(api, buildable, "INCLUDED")) == 0


def test_build_with_a_stale_order_version_is_refused_before_any_line_is_written(api):
    """PRD §3.9: "the optimistic concurrency comparison runs first: the supplied
    `expected_<parent>_version` must equal the parent entity's current version,
    and a mismatch yields `ERR_STALE_VERSION` with HTTP status 412 before the
    state of the target resource is examined at all."

    Design: Corner/validations/build_with_a_stale_order_version_is_refused_before_any_line_is_written
    """
    scenario = setup_box_scenario(
        api, cycles=(2,),
        lot_overrides={"category": "FRUIT", "unit_weight_grams": 100,
                       "unit_cost_cents": 100, "quantity_available": 300},
    )
    order, lot, center = scenario["orders"][0], scenario["lot"], scenario["center"]

    response = api.build_box_order(
        order["id"],
        {"expected_box_order_version": order["version"] - 1,
         "line_plan": line_plan((lot["id"], 6))},
        make_operator_headers(center["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

    read = refresh_order(api, order)
    assert read["status"] == "DRAFT"
    assert len(order_items(api, order, "INCLUDED")) == 0


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------
def test_unknown_field_on_a_write_is_refused(api):
    """PRD §3.9: "Every field the endpoint declares as required must be present,
    every supplied enum member must be one the endpoint actually declares, and a
    supplied `barcode_gtin` must be exactly fourteen digits; a failure yields
    `ERR_INVALID_REQUEST` with HTTP status 400."

    Design: Corner/validations/unknown_field_on_a_write_is_refused
    """
    center, supplier, lot = setup_center_supplier_lot(api, code="DEMO-NE", region="NE")
    customer, subscription = setup_subscriber(api, region="NE", email="uf@example.com")
    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )

    response = api.finalize_box_order(
        order["id"],
        {"expected_box_order_version": order["version"], "finalize_note": "please ship"},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    assert get_success_data(api.get_subscription(subscription["id"], ADMIN))["status"] == "ACTIVE"


def test_conventional_quote_barcode_must_be_exactly_fourteen_digits(api):
    """PRD §2.9: "The `barcode_gtin` must be exactly fourteen digits; a value
    of any other length is a malformed request."
    PRD §3.9: "a supplied `barcode_gtin` must be exactly fourteen digits; a
    failure yields `ERR_INVALID_REQUEST` with HTTP status 400."

    Design: Corner/validations/conventional_quote_barcode_must_be_exactly_fourteen_digits
    """
    center, supplier, lot = setup_center_supplier_lot(api, code="DEMO-NE", region="NE")

    response = api.create_quote(
        {"supply_lot_id": lot["id"], "retailer_label": "Conventional Co",
         "source_url": "https://ref.example.com/bc", "captured_at": "2026-08-30T00:00:00Z",
         "conventional_unit_price_cents": 500, "barcode_gtin": "1234567890123"},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    assert len(get_success_data(api.list_lot_quotes(lot["id"], ADMIN))) == 0
    assert len(get_success_data(api.list_quotes(ADMIN, {"supply_lot_id": lot["id"]}))) == 0


def test_substantiation_requires_a_source_of_the_lots_own_grade(api):
    """PRD §2.9: "A lot with a `ConventionalQuote` on file that has no
    same-grade source, or that has more than three sources, fails
    substantiation, and that failed assessment is refused with
    `ERR_SUBSTANTIATION_REQUIRED` and HTTP status 422."
    PRD §3.6: "a lot with only non-equivalent evidence, or with no evidence at
    all, is priced off the `CONVENTIONAL` multiplier of 1.40"

    Design: Corner/validations/substantiation_requires_a_source_of_the_lots_own_grade
    """
    center, supplier, lot = setup_center_supplier_lot(api, code="DEMO-NE", region="NE")
    quote = get_success_data(
        api.create_quote(
            {"supply_lot_id": lot["id"], "retailer_label": "Conventional Co",
             "source_url": "https://ref.example.com/sb", "captured_at": "2026-08-30T00:00:00Z",
             "conventional_unit_price_cents": 500, "barcode_gtin": "00012345678921",
             "grade_equivalent": False},
            ADMIN,
        )
    )

    response = api.substantiate_quote(quote["id"], {}, ADMIN)
    validate_error(response, ApiErrorId.ERR_SUBSTANTIATION_REQUIRED, 422)

    refreshed = refresh_lot(api, lot)
    assert refreshed["display_price_cents"] == 140  # CONVENTIONAL 1.40 on 100 cents
    quotes = get_success_data(api.list_lot_quotes(lot["id"], ADMIN))
    assert len(quotes) == 1
    assert quotes[0]["is_primary"] is True
    assert quotes[0]["substantiation_status"] == "UNSUBSTANTIATED"


def test_second_order_in_the_same_cycle_is_refused(api):
    """PRD §3.4: "the order may not duplicate a `serving_cycle_index` that the
    same subscription has already produced — a second order for a cycle that is
    already covered is refused with `ERR_SUBSCRIPTION_INELIGIBLE` and HTTP
    status 409."
    PRD §3.9: "Twelfth is subscription cadence eligibility"

    Design: Corner/validations/second_order_in_the_same_cycle_is_refused
    """
    center, supplier, lot = setup_center_supplier_lot(api, code="DEMO-NE", region="NE")
    customer, subscription = setup_subscriber(api, region="NE", email="du@example.com")
    payload = {"customer_id": customer["id"], "subscription_id": subscription["id"],
               "serving_cycle_index": 2, "cuisine_preference": "STANDARD"}
    validate_success(api.create_box_order(payload, ADMIN), 201)

    response = api.create_box_order(payload, ADMIN)
    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_INELIGIBLE, 409)

    rows = get_success_data(api.list_box_orders(ADMIN, {"subscription_id": subscription["id"]}))
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Authentication and ownership
# ---------------------------------------------------------------------------
def test_pack_without_a_role_header_is_unauthenticated(api):
    """PRD §2.1: "If either header is absent, if the role is not one of the
    recognized five values, or if an entity-backed identifier does not resolve
    to a stored row, the request is refused with `ERR_UNAUTHENTICATED` and HTTP
    status 401."
    PRD §3.9: "First, the `X-User-ID` and `X-User-Role` headers must both be present"

    Design: Corner/errors/order_pack_without_a_role_header_is_unauthenticated
    """
    scenario = setup_box_scenario(
        api, cycles=(2,),
        lot_overrides={"category": "FRUIT", "unit_weight_grams": 100,
                       "unit_cost_cents": 100, "quantity_available": 300},
    )
    built = build_order(api, scenario["orders"][0], scenario["center"],
                        line_plan((scenario["lot"]["id"], 6)))

    response = api.pack_box_order(
        built["id"], {"expected_box_order_version": built["version"]},
        {"Content-Type": "application/json"},
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    read = refresh_order(api, built)
    assert read["status"] == "BUILDING"


def test_customer_cannot_read_another_customers_box_order(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
    the acting `Customer`; ownership checks on any resource that references a
    `Customer` compare the resource's `customer_id` field to `X-User-ID`"
    PRD §2.1: "An authenticated caller whose role is not permitted for the
    operation, or an entity-backed caller acting on a resource it does not own,
    is refused with `ERR_UNAUTHORIZED` and HTTP status 403."

    Design: Corner/errors/customer_role_cannot_read_another_customers_box_order
    """
    scenario = setup_box_scenario(
        api, cycles=(2,),
        lot_overrides={"category": "FRUIT", "unit_weight_grams": 100,
                       "unit_cost_cents": 100, "quantity_available": 300},
    )
    order = scenario["orders"][0]
    peer = make_customer(api, email="peer@example.com", full_name="Peer Pat",
                         service_region="NE")

    response = api.get_box_order(order["id"], make_customer_headers(peer["id"]))
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)

    own = validate_success(
        api.get_box_order(
            order["id"],
            make_customer_headers(scenario["customer"]["id"]),
        ),
        200,
    )
    assert own["id"] == order["id"]


def test_registration_in_a_region_without_an_active_center_is_refused(api):
    """PRD §2.6: "If the eligible set is empty, registration is refused with
    `ERR_NO_CENTER_AVAILABLE` and HTTP status 422."
    PRD §3.9: "Fifteenth and last is regional center availability: registration
    requires at least one active fulfillment center in the customer's
    `service_region`"

    Design: Corner/errors/registration_in_a_region_without_an_active_center_is_refused
    """
    reset_clock(api)
    make_center(api, code="DEMO-SO", region="SO")

    response = api.register_customer(
        {"email": "nomw@example.com", "full_name": "Nom Wa", "service_region": "MW"}, ANON
    )
    # §2.6: an empty eligible set refuses registration and no Customer row may
    # survive the refusal. The refusal is asserted by re-reading the collection
    # rather than by any filter, so the probe does not depend on an optional
    # query parameter the endpoint does not declare.
    validate_error(response, ApiErrorId.ERR_NO_CENTER_AVAILABLE, 422)

    assert all(
        row["email"] != "nomw@example.com"
        for row in get_success_data(api.list_customers(ADMIN))
    )


# ---------------------------------------------------------------------------
# The role lattice
# ---------------------------------------------------------------------------
def test_supplier_cannot_list_a_lot_inside_another_suppliers_scope(api):
    """PRD §2.1: "a `SupplyLot` addressed through the supplier-scoped listing
    path must belong to that supplier as well."
    PRD §2.1: "an entity-backed caller acting on a resource it does not own, is
    refused with `ERR_UNAUTHORIZED` and HTTP status 403."

    Design: Corner/roles/supplier_cannot_list_a_lot_inside_another_suppliers_scope
    """
    center, supplier, lot = setup_center_supplier_lot(api, code="DEMO-NE", region="NE")
    peer = make_supplier(api, name="Peer Supplier", region="NE")

    response = api.create_lot(
        peer["id"],
        {"fulfillment_center_id": center["id"], "product_name": "STOLEN",
         "category": "FRUIT", "procurement_grade": "SURPLUS", "unit_weight_grams": 100,
         "quantity_available": 10, "unit_cost_cents": 100,
         "harvest_date": "2026-09-01T00:00:00Z", "expiry_date": "2026-09-20T00:00:00Z",
         "ready_date": "2026-09-05T00:00:00Z"},
        make_supplier_headers(supplier["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)

    assert len(get_success_data(api.list_supplier_lots(peer["id"], ADMIN))) == 0


def test_customer_cannot_build_its_own_box(api):
    """PRD §2.1: "building and packing a box are reserved to the
    `FulfillmentOperator` of the owning center."
    PRD §2.1: "An authenticated caller whose role is not permitted for the operation, or an
    entity-backed caller acting on a resource it does not own, is refused with
    `ERR_UNAUTHORIZED` and HTTP status 403."

    Design: Corner/roles/customer_cannot_build_its_own_box
    """
    scenario = setup_box_scenario(
        api, cycles=(2,),
        lot_overrides={"category": "FRUIT", "unit_weight_grams": 100,
                       "unit_cost_cents": 100, "quantity_available": 300},
    )
    order = scenario["orders"][0]
    lot = scenario["lot"]

    response = api.build_box_order(
        order["id"],
        {"expected_box_order_version": order["version"],
         "line_plan": line_plan((lot["id"], 6))},
        make_customer_headers(scenario["customer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)

    assert refresh_order(api, order)["status"] == "DRAFT"


def test_operator_cannot_build_at_another_center(api):
    """PRD §2.1: "When `X-User-Role` is `FulfillmentOperator`, `X-User-ID` is
    the `id` of the acting `FulfillmentCenter`; a `BoxOrder` whose
    `fulfillment_center_id` equals `X-User-ID` is within that operator's scope"
    PRD §2.1: "an entity-backed caller acting on a resource it does not own, is
    refused with `ERR_UNAUTHORIZED` and HTTP status 403."

    Design: Corner/roles/operator_cannot_build_at_another_center
    """
    reset_clock(api)
    aaa = make_center(api, code="AAA-NE", region="NE", max_concurrent_building_cycles=5)
    zzz = make_center(api, code="ZZZ-NE", region="NE", max_concurrent_building_cycles=5)
    supplier = make_supplier(api, name="Operator Farms", region="NE")
    lot = make_lot(api, supplier["id"], aaa["id"], category="FRUIT",
                   procurement_grade="SURPLUS", unit_weight_grams=100,
                   unit_cost_cents=100, quantity_available=300)
    lot = _award_and_ready(api, lot, supplier)
    customer, subscription = setup_subscriber(api, region="NE", email="op@example.com")
    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )

    assert order["fulfillment_center_id"] == aaa["id"]

    response = api.build_box_order(
        order["id"],
        {"expected_box_order_version": order["version"],
         "line_plan": line_plan((lot["id"], 6))},
        make_operator_headers(zzz["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)

    buildable = make_order_buildable(api, order, aaa)
    built = validate_success(
        api.build_box_order(
            buildable["id"],
            {"expected_box_order_version": buildable["version"],
             "line_plan": line_plan((lot["id"], 6))},
            make_operator_headers(aaa["id"]),
        ),
        200,
    )
    assert built["status"] == "BUILDING"


def test_platform_admin_adjudicates_a_claim_the_operator_may_only_read(api):
    """PRD §2.1: "Reviewing a claim is a protected write by an administrator"
    PRD §2.1: "Claim adjudication is a PlatformAdmin exclusive while a
    FulfillmentOperator can read the claim list"
    PRD §2.1: "An authenticated caller whose role is not permitted for the operation, or an
    entity-backed caller acting on a resource it does not own, is refused with
    `ERR_UNAUTHORIZED` and HTTP status 403."

    Design: Corner/roles/platform_admin_can_adjudicate_a_claim_the_operator_may_only_read
    """
    scenario = setup_box_scenario(
        api, cycles=(2,),
        lot_overrides={"category": "FRUIT", "unit_weight_grams": 100,
                       "unit_cost_cents": 100, "quantity_available": 300},
    )
    center, order = scenario["center"], scenario["orders"][0]
    built = build_order(api, order, center, line_plan((scenario["lot"]["id"], 6)))
    packed = pack_order(api, built, center)
    item = [i for i in order_items(api, packed) if i["status"] == "INCLUDED"][0]
    claim = file_claim(api, packed, item["id"], reason_code="SPOILED",
                       requested_credit_cents=500)

    readable = api.list_order_quality_claims(packed["id"], make_operator_headers(center["id"]))
    assert readable.status_code == 200
    assert len(readable.json()["data"]) == 1

    response = api.review_quality_claim(
        claim["id"], {"outcome": "UPHELD", "expected_claim_version": claim["version"]},
        make_operator_headers(center["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)

    after = get_success_data(api.list_order_quality_claims(packed["id"], ADMIN))
    assert after[0]["status"] == "IN_REVIEW"
    assert after[0]["credited_cents"] == 0