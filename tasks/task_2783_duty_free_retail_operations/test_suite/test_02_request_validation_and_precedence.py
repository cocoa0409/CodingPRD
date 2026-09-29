"""Well-formedness, uniqueness scoping, cross-reference coherence and the top of the
rejection ladder."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DUPLICATE_AGREEMENT_PERIOD,
    ERR_DUPLICATE_SKU,
    ERR_DUPLICATE_STOCK_ITEM,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_NOT_ITINERARY_OWNER,
    ERR_PRODUCT_CATEGORY_MISMATCH,
    ERR_PRODUCT_NOT_FOUND,
    ERR_SALE_NOT_FOUND,
    ERR_TERMINAL_MISMATCH,
    ERR_TERMINAL_NOT_FOUND,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_movement_shape,
    assert_stock_quantities,
    created,
    ok,
    page,
)
from test_helpers.constants import MISSING_UUIDS
from test_helpers.test_users import (
    NO_AUTH_HEADERS,
    SALES_ASSOCIATE_HEADERS,
    STOCK_CONTROLLER_HEADERS,
    TERMINAL_ADMIN_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    USER_STOCK,
    make_passenger_headers,
)


def test_a_write_missing_a_required_field_is_malformed(api):
    """A product without a shelf price and a terminal without a country are both refused.

    PRD 2.8: "On every write, all required fields must be present, every enum value must fall inside its declared set, quantities and basis-point figures must lie inside their declared ranges"

    Design: Corner/entities/missing_required_inputs_are_rejected_with_invalid_request
    """
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")

    response = api.create_product(
        {
            "brand_id": brand["id"],
            "sku": "AUR-NOPRICE",
            "category": "LIQUOR",
            "duty_rate_bps": 1500,
            "vat_rate_bps": 900,
            "target_nationality_code": "CN",
        },
        TERMINAL_ADMIN_HEADERS,
    )
    validate_error(response, ERR_INVALID_REQUEST)

    response = api.create_terminal(
        {"iata_code": "SIN", "name": "Changi T3 Duty Free"}, TERMINAL_ADMIN_HEADERS
    )
    validate_error(response, ERR_INVALID_REQUEST)

    products, _ = page(api.list_products(TERMINAL_ADMIN_HEADERS))
    terminals, _ = page(api.list_terminals(TERMINAL_ADMIN_HEADERS))
    assert products == []
    assert terminals == []


def test_an_unresolvable_body_identifier_outranks_the_missing_fields_beside_it(api):
    """The existence tier answers before the well-formedness tier does.

    PRD 2.8: "Every identifier in the URL path is resolved first, left to right, and only then are identifiers carried in the request body resolved."

    Design: Corner/entities/missing_required_inputs_are_rejected_with_invalid_request
    """
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")

    response = api.create_agreement(
        {"terminal_id": brand["id"], "period_code": "2026-08"}, TERMINAL_ADMIN_HEADERS
    )

    validate_error(response, ERR_TERMINAL_NOT_FOUND)
    agreements, _ = page(api.list_agreements(TERMINAL_ADMIN_HEADERS))
    assert agreements == []


def test_an_enum_value_outside_its_declared_set_is_refused(api):
    """A merchandise category and a movement type must both name a declared member.

    PRD 3.2: "Supplier brands are registered next, each with a trading `name` and exactly one merchandise `category` drawn from `LIQUOR`, `TOBACCO`, `FRAGRANCE`, `CONFECTIONERY` and `ELECTRONICS`."

    Design: Corner/entities/enum_and_numeric_range_violations_are_rejected_before_business_logic
    """
    estate = fx.liquor_estate(api, with_agreement=False)

    validate_error(
        api.create_brand(f.brand_payload(name="Bogus Brand", category="PERFUMERY"), TERMINAL_ADMIN_HEADERS),
        ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_movement(
            f.movement_payload(estate.stock_item["id"], "TELEPORT", 5), STOCK_CONTROLLER_HEADERS
        ),
        ERR_INVALID_REQUEST,
    )

    stock_item = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(stock_item, 10, 0)


def test_a_numeric_field_outside_its_declared_range_is_refused(api):
    """A zero line quantity and an out-of-range duty rate are both malformed.

    PRD 3.2: "`duty_rate_bps`, the import duty rate, and `vat_rate_bps`, the value-added tax rate, each between 0 and 10000 basis points inclusive"

    Design: Corner/entities/enum_and_numeric_range_violations_are_rejected_before_business_logic
    """
    estate = fx.liquor_estate(api)
    itinerary = fx.scanned_itinerary(api, estate.terminal["id"], passenger_ref="PAX-0102")
    sale = fx.open_basket(api, itinerary["id"])

    validate_error(
        api.create_product(
            f.product_payload(estate.brand["id"], sku="AUR-BADRATE", duty_rate_bps=12000),
            TERMINAL_ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
    )
    validate_error(
        api.add_sale_line(
            sale["id"],
            f.sale_line_payload(estate.product["id"], 0, sale["version"]),
            SALES_ASSOCIATE_HEADERS,
        ),
        ERR_INVALID_REQUEST,
    )

    unchanged = ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))
    assert unchanged["version"] == sale["version"]
    lines, _ = page(api.list_sale_lines(SALES_ASSOCIATE_HEADERS, {"sale_id": sale["id"]}))
    assert lines == []


def test_an_unknown_identifier_in_the_path_returns_its_own_not_found(api):
    """Each identifier has its own 404 rather than one generic code.

    PRD 2.8: "Each identifier has its own 404: `terminal_id` yields `ERR_TERMINAL_NOT_FOUND`, `brand_id` yields `ERR_BRAND_NOT_FOUND`, `product_id` yields `ERR_PRODUCT_NOT_FOUND`"

    Design: Corner/entities/unknown_ids_return_the_entity_specific_not_found_error
    """
    fx.register_terminal(api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE")

    validate_error(
        api.get_terminal(MISSING_UUIDS["terminal"], TERMINAL_ADMIN_HEADERS), ERR_TERMINAL_NOT_FOUND
    )
    validate_error(api.get_sale(MISSING_UUIDS["sale"], SALES_ASSOCIATE_HEADERS), ERR_SALE_NOT_FOUND)

    body = api.get_sale(MISSING_UUIDS["sale"], SALES_ASSOCIATE_HEADERS).json()
    assert body["data"]["error_id"] == ERR_SALE_NOT_FOUND
    assert body["data"]["message"]


def test_an_unknown_identifier_in_the_body_returns_its_own_not_found(api):
    """A body reference is resolved too, and reports the entity it names.

    PRD 2.8: "When several body identifiers are unresolvable, they are resolved in the order listed here, which is the order the identifiers were introduced above."

    Design: Corner/entities/unknown_ids_return_the_entity_specific_not_found_error
    """
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE")

    validate_error(
        api.create_stock_item(
            f.stock_item_payload(terminal["id"], MISSING_UUIDS["product"]), STOCK_CONTROLLER_HEADERS
        ),
        ERR_PRODUCT_NOT_FOUND,
    )
    validate_error(
        api.create_agreement(f.agreement_payload(MISSING_UUIDS["terminal"]), TERMINAL_ADMIN_HEADERS),
        ERR_TERMINAL_NOT_FOUND,
    )


def test_a_product_category_must_match_its_owning_brand(api):
    """Resolving the brand id is not enough; the categories have to agree.

    PRD 3.2: "a `category` that differs from the owning brand's own `category` is refused with `ERR_PRODUCT_CATEGORY_MISMATCH`"

    Design: Corner/entities/cross_reference_integrity_is_enforced_across_aggregates
    """
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")

    response = api.create_product(
        f.product_payload(
            brand["id"],
            sku="AUR-CIGAR-01",
            category="TOBACCO",
            unit_price_cents=500,
            duty_rate_bps=800,
            vat_rate_bps=450,
            required_nationality_share_bps=0,
        ),
        TERMINAL_ADMIN_HEADERS,
    )

    validate_error(response, ERR_PRODUCT_CATEGORY_MISMATCH)
    products, _ = page(api.list_products(TERMINAL_ADMIN_HEADERS, {"category": "TOBACCO"}))
    assert products == []


def test_a_reservation_must_draw_on_the_travellers_own_departure_terminal(api):
    """A ledger that resolves but sits at another airport is refused.

    PRD 3.8: "the bonded ledger must sit at the traveller's own departure terminal — the stock item's `terminal_id` must equal the itinerary's `departure_terminal_id` — else `ERR_TERMINAL_MISMATCH`"

    Design: Corner/entities/cross_reference_integrity_is_enforced_across_aggregates
    """
    sin = fx.register_terminal(api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE", liquid_limit_ml=3000)
    hkg_estate = fx.liquor_estate(api, iata_code="HKG", country_code="HK", sealed_bag_regime="ICAO_STEB", with_agreement=False)
    itinerary = fx.record_itinerary(api, sin["id"], passenger_ref="PAX-0103", departure_utc="2026-08-20T00:00:00Z")

    response = api.create_pre_order(
        f.pre_order_payload(
            itinerary["id"], hkg_estate.stock_item["id"], 2, hkg_estate.stock_item["version"]
        ),
        make_passenger_headers(itinerary["id"]),
    )

    validate_error(response, ERR_TERMINAL_MISMATCH)
    stock_item = ok(api.get_stock_item(hkg_estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert stock_item["reserved_qty"] == 0
    assert stock_item["version"] == hkg_estate.stock_item["version"]


def test_the_bonded_ledger_key_is_the_terminal_and_product_pairing(api):
    """The same product may be stocked at a second terminal but not twice at one.

    PRD 3.3: "A `StockController` opens one bonded ledger per pairing of a `terminal_id` and a `product_id`; a second ledger for a pairing that already has one is refused with `ERR_DUPLICATE_STOCK_ITEM`."

    Design: Corner/entities/scoped_uniqueness_keys_are_composite_not_global
    """
    sin = fx.register_terminal(api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE", liquid_limit_ml=3000)
    hkg = fx.register_terminal(api, iata_code="HKG", country_code="HK", sealed_bag_regime="ICAO_STEB", liquid_limit_ml=3000)
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    product = fx.register_product(api, brand["id"], sku="SHARED-SKU-1")
    fx.open_ledger(api, sin["id"], product["id"])

    at_hkg = created(
        api.create_stock_item(f.stock_item_payload(hkg["id"], product["id"]), STOCK_CONTROLLER_HEADERS)
    )
    assert at_hkg["terminal_id"] == hkg["id"]

    validate_error(
        api.create_stock_item(f.stock_item_payload(sin["id"], product["id"]), STOCK_CONTROLLER_HEADERS),
        ERR_DUPLICATE_STOCK_ITEM,
    )


def test_the_agreement_key_is_the_terminal_and_period_pairing(api):
    """One period label may recur at another terminal but not at the same one.

    PRD 3.10: "A second agreement for a terminal and period that already has one is refused with `ERR_DUPLICATE_AGREEMENT_PERIOD`."

    Design: Corner/entities/scoped_uniqueness_keys_are_composite_not_global
    """
    sin = fx.register_terminal(api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE", liquid_limit_ml=3000)
    hkg = fx.register_terminal(api, iata_code="HKG", country_code="HK", sealed_bag_regime="ICAO_STEB", liquid_limit_ml=3000)
    at_sin = fx.draft_agreement(api, sin["id"], period_code="2026-08")

    at_hkg = created(
        api.create_agreement(f.agreement_payload(hkg["id"], period_code="2026-08"), TERMINAL_ADMIN_HEADERS)
    )
    assert at_hkg["period_code"] == "2026-08"

    validate_error(
        api.create_agreement(
            f.agreement_payload(sin["id"], period_code="2026-08", rent_pct_bps=900, minimum_guarantee_cents=20000),
            TERMINAL_ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_AGREEMENT_PERIOD,
    )

    unchanged = ok(api.get_agreement(at_sin["id"], TERMINAL_ADMIN_HEADERS))
    assert unchanged["rent_pct_bps"] == 1200
    assert unchanged["minimum_guarantee_cents"] == 10000


def test_a_repeated_sku_is_refused(api):
    """The sku uniqueness key rejects a repeat.

    PRD 3.2: "A repeat `sku` is refused with `ERR_DUPLICATE_SKU`"

    Design: Corner/entities/scoped_uniqueness_keys_are_composite_not_global
    """
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    fx.register_product(api, brand["id"], sku="SHARED-SKU-1", unit_price_cents=8000)

    response = api.create_product(
        f.product_payload(brand["id"], sku="SHARED-SKU-1", unit_price_cents=9000, required_nationality_share_bps=0),
        TERMINAL_ADMIN_HEADERS,
    )

    validate_error(response, ERR_DUPLICATE_SKU)


def test_a_ledger_movement_carries_no_updated_at_and_no_version(api):
    """The immutable accounting entry has identity and a creation stamp only.

    PRD 2.5: "A movement is an immutable accounting entry: it carries `id` and `created_at` only, and has neither `updated_at` nor `version`."

    Design: Corner/entities/bonded_movement_is_append_only_with_no_version_field
    """
    estate = fx.liquor_estate(api, receipt_qty=0, with_agreement=False)

    movement = created(
        api.create_movement(
            f.movement_payload(estate.stock_item["id"], "RECEIPT", 10), STOCK_CONTROLLER_HEADERS
        )
    )

    assert_movement_shape(movement)
    assert movement["reversed"] is False
    assert movement["reversal_of_movement_id"] is None
    assert movement["affects"] == "ON_HAND"
    assert movement["source_ref_type"] == "MANUAL"
    assert movement["source_ref_id"] is None
    assert movement["posted_by_user_id"] == USER_STOCK

    read_back = ok(api.get_movement(movement["id"], STOCK_CONTROLLER_HEADERS))
    assert "updated_at" not in read_back
    assert "version" not in read_back


def test_a_ledger_movement_offers_no_editing_route(api):
    """Correction is by appending a compensating entry, never by editing a row.

    PRD 3.3: "A manual entry is never edited or deleted."

    Design: Corner/entities/bonded_movement_is_append_only_with_no_version_field
    """
    estate = fx.liquor_estate(api, receipt_qty=0, with_agreement=False)
    movement = fx.post_receipt(api, estate.stock_item["id"], 10)

    for method in ("PUT", "PATCH", "DELETE"):
        response = api.raw_request(
            method,
            f"/bonded-movements/{movement['id']}",
            {"qty_delta": 99},
            STOCK_CONTROLLER_HEADERS,
        )
        assert response.status_code >= 400, (
            f"{method} on a movement should not be an accepted route, got {response.status_code}"
        )

    unchanged = ok(api.get_movement(movement["id"], STOCK_CONTROLLER_HEADERS))
    assert unchanged["qty_delta"] == 10
    assert unchanged["reversed"] is False


def test_missing_or_unrecognised_headers_are_rejected_before_anything_else(api):
    """The authentication tier answers even when the target does not exist.

    PRD 2.8: "Headers present and `X-User-Role` recognised, else `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/validations/auth_ladder_rejects_unauthenticated_then_forbidden_role_then_non_owner
    """
    fx.register_terminal(api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE", liquid_limit_ml=3000)

    validate_error(api.get_terminal(MISSING_UUIDS["terminal"], NO_AUTH_HEADERS), ERR_UNAUTHENTICATED)
    validate_error(
        api.get_terminal(MISSING_UUIDS["terminal"], UNKNOWN_ROLE_HEADERS), ERR_UNAUTHENTICATED
    )


def test_role_authorisation_outranks_the_schema_and_ownership_outranks_existence(api):
    """A forbidden role answers before a malformed body, and non-ownership before a missing id.

    PRD 2.8: "For the two passenger-facing writes — placing a reservation and cancelling one — `X-User-ID` must equal the itinerary the request targets: the `itinerary_id` in the body when placing a reservation, and the reservation's own itinerary when cancelling."

    Design: Corner/validations/auth_ladder_rejects_unauthenticated_then_forbidden_role_then_non_owner
    """
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE", liquid_limit_ml=3000)
    itinerary = fx.record_itinerary(api, terminal["id"], passenger_ref="PAX-0117")

    validate_error(
        api.create_terminal({"iata_code": "XX"}, SALES_ASSOCIATE_HEADERS), ERR_FORBIDDEN_ROLE
    )

    someone_else = make_passenger_headers(MISSING_UUIDS["itinerary"])
    validate_error(
        api.create_pre_order(
            f.pre_order_payload(itinerary["id"], MISSING_UUIDS["stock_item"], 1, 1), someone_else
        ),
        ERR_NOT_ITINERARY_OWNER,
    )

    terminals, _ = page(api.list_terminals(TERMINAL_ADMIN_HEADERS))
    assert [row["id"] for row in terminals] == [terminal["id"]]
    pre_orders, _ = page(api.list_pre_orders(TERMINAL_ADMIN_HEADERS))
    assert pre_orders == []
