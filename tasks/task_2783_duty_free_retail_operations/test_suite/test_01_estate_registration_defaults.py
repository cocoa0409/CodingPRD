"""Registration of the commercial estate and the server-owned default values."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_instant,
    assert_nulls,
    assert_sale_amounts,
    assert_sale_dimensions,
    assert_stock_quantities,
    assert_versioned_shape,
    created,
    ok,
    page,
)
from test_helpers.constants import (
    CLOCK_START,
    DEFAULT_LIQUID_LIMIT_ML,
    DEFAULT_REQUIRED_NATIONALITY_SHARE_BPS,
    DEFAULT_SEALED_BAG_REGIME,
)
from test_helpers.test_users import (
    CUSTOMS_AUDITOR_HEADERS,
    SALES_ASSOCIATE_HEADERS,
    STOCK_CONTROLLER_HEADERS,
    TERMINAL_ADMIN_HEADERS,
    USER_STOCK,
    make_passenger_headers,
)


def test_terminal_omitted_optional_inputs_take_their_declared_defaults(api):
    """A terminal registered without the connecting-passenger inputs is ICAO_STEB at one litre.

    PRD 3.1: "`sealed_bag_regime`, either `ICAO_STEB` or `NONE`, which defaults to `ICAO_STEB`; and `liquid_limit_ml`, the maximum aggregate millilitres of liquid goods one sealed bag may hold, which must not be negative and defaults to 1000"

    Design: Corner/entities/terminal_defaults_sealed_bag_regime_liquid_limit_and_counters
    """
    terminal = created(
        api.create_terminal(
            f.terminal_payload(iata_code="NRT", name="Narita Duty Free", country_code="JP"),
            TERMINAL_ADMIN_HEADERS,
        )
    )

    assert terminal["sealed_bag_regime"] == DEFAULT_SEALED_BAG_REGIME
    assert terminal["liquid_limit_ml"] == DEFAULT_LIQUID_LIMIT_ML

    read_back = ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert read_back["sealed_bag_regime"] == DEFAULT_SEALED_BAG_REGIME
    assert read_back["liquid_limit_ml"] == DEFAULT_LIQUID_LIMIT_ML


def test_terminal_server_maintained_counters_start_empty(api):
    """The mix map, the scan count and the accrued liability are server-owned zeros.

    PRD 3.1: "A freshly registered terminal has an empty `traveler_nationality_mix` object, a `scanned_itinerary_count_30d` of 0 and an `unaccounted_duty_liability_cents` of 0; all three are maintained by the server and never supplied by a client."

    Design: Corner/entities/terminal_defaults_sealed_bag_regime_liquid_limit_and_counters
    """
    terminal = created(
        api.create_terminal(
            f.terminal_payload(
                iata_code="NRT",
                name="Narita Duty Free",
                country_code="JP",
                traveler_nationality_mix={"CN": 9000},
                scanned_itinerary_count_30d=77,
                unaccounted_duty_liability_cents=123456,
            ),
            TERMINAL_ADMIN_HEADERS,
        )
    )

    assert terminal["traveler_nationality_mix"] == {}
    assert terminal["scanned_itinerary_count_30d"] == 0
    assert terminal["unaccounted_duty_liability_cents"] == 0


def test_client_supplied_identity_and_version_are_ignored_on_create(api):
    """A body that smuggles id, timestamps or version cannot pin them.

    PRD 2.5: "a `version`, an integer that starts at 1 when the resource is created and increments by exactly 1 on every mutation"

    Design: Corner/entities/client_supplied_id_created_at_and_version_are_ignored_on_create
    """
    smuggled_id = "11111111-1111-4111-8111-111111111111"
    terminal = created(
        api.create_terminal(
            f.terminal_payload(
                iata_code="NRT",
                name="Narita Duty Free",
                country_code="JP",
                id=smuggled_id,
                created_at="2020-01-01T00:00:00Z",
                updated_at="2020-01-01T00:00:00Z",
                version=0,
            ),
            TERMINAL_ADMIN_HEADERS,
        )
    )

    assert terminal["id"] != smuggled_id
    assert_versioned_shape(terminal, 1, "terminal")
    assert_instant(terminal["created_at"], CLOCK_START, "terminal created_at")
    assert_instant(terminal["updated_at"], CLOCK_START, "terminal updated_at")


def test_a_created_resource_round_trips_through_its_own_read(api):
    """The identity written on create is the identity the follow-up read returns.

    PRD 2.5: "Every resource carries an `id`, which is a server-minted UUID with no type prefix, and a `created_at`, an ISO 8601 UTC timestamp with three fractional digits."

    Design: Corner/entities/client_supplied_id_created_at_and_version_are_ignored_on_create
    """
    terminal = created(
        api.create_terminal(
            f.terminal_payload(iata_code="NRT", name="Narita Duty Free", country_code="JP"),
            TERMINAL_ADMIN_HEADERS,
        )
    )

    read_back = ok(api.get_terminal(terminal["id"], TERMINAL_ADMIN_HEADERS))
    assert read_back["id"] == terminal["id"]
    assert_instant(read_back["created_at"], terminal["created_at"], "created_at")
    assert read_back["version"] == terminal["version"] == 1


def test_a_new_product_starts_pending_and_not_a_liquid(api):
    """A product is unsellable and non-liquid until somebody says otherwise.

    PRD 3.2: "Every new product starts with `assortment_status` of `PENDING` and `listed_at` null."

    Design: Corner/entities/product_and_sale_lifecycle_defaults_start_at_pending_cart_and_suspended
    """
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")

    product = created(
        api.create_product(
            f.product_payload(
                brand["id"],
                sku="AUR-RUM-700",
                category="LIQUOR",
                unit_price_cents=4000,
                target_nationality_code="CN",
            ),
            TERMINAL_ADMIN_HEADERS,
        )
    )

    assert product["assortment_status"] == "PENDING"
    assert product["is_liquid"] is False
    assert product["liquid_ml"] is None
    assert product["required_nationality_share_bps"] == DEFAULT_REQUIRED_NATIONALITY_SHARE_BPS
    assert product["listed_at"] is None


def test_a_new_basket_is_in_cart_and_in_duty_suspension_at_once(api):
    """The till dimension and the customs dimension both start at their opening value.

    PRD 3.5: "A new basket carries `fulfillment_status` of `CART` on its till dimension and `duty_status` of `SUSPENDED` on its customs dimension, with `gross_amount_cents`, `exempt_amount_cents` and `duty_liability_cents` at 0"

    Design: Corner/entities/product_and_sale_lifecycle_defaults_start_at_pending_cart_and_suspended
    """
    terminal = fx.register_terminal(
        api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE", liquid_limit_ml=3000
    )
    fx.active_agreement(api, terminal["id"])
    itinerary = fx.scanned_itinerary(api, terminal["id"], passenger_ref="PAX-0101")

    sale = created(
        api.create_sale(f.sale_payload(itinerary["id"], "IN_STORE"), SALES_ASSOCIATE_HEADERS)
    )

    assert_sale_dimensions(sale, "CART", "SUSPENDED")
    assert_sale_amounts(sale, 0, 0, 0)
    assert_nulls(
        sale,
        "effective_destination_country",
        "eligibility_variant",
        "cleared_at",
        "picked_up_at",
        "voided_at",
    )
    assert sale["arrival_advisory"] == []
    assert sale["sealed_bag_required"] is False
    assert sale["terminal_id"] == terminal["id"]


def test_a_newly_opened_bonded_ledger_derives_zero_whatever_the_body_claims(api):
    """Quantities and duty-suspended value are derived, so a create cannot seed them.

    PRD 3.3: "A newly opened ledger has `on_hand_qty`, `reserved_qty`, `available_qty` and `duty_suspended_value_cents` all at 0, `last_reconciled_at` null, and a `version` of 1."

    Design: Corner/entities/sale_and_stock_totals_cannot_be_set_from_the_request_body
    """
    terminal = fx.register_terminal(
        api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE", liquid_limit_ml=3000
    )
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    product = fx.register_product(
        api, brand["id"], sku="AUR-WHISKY-700", is_liquid=True, liquid_ml=700
    )

    stock_item = created(
        api.create_stock_item(
            f.stock_item_payload(
                terminal["id"],
                product["id"],
                on_hand_qty=500,
                reserved_qty=40,
                available_qty=460,
                duty_suspended_value_cents=999999,
                last_reconciled_at=CLOCK_START,
            ),
            STOCK_CONTROLLER_HEADERS,
        )
    )

    assert_stock_quantities(stock_item, 0, 0, 0)
    assert stock_item["last_reconciled_at"] is None
    assert stock_item["version"] == 1


def test_basket_totals_cannot_be_seeded_from_the_request_body(api):
    """A basket opens at zero turnover even when the body offers figures.

    PRD 3.5: "The server copies `terminal_id` from the itinerary's `departure_terminal_id` and `agreement_id` from that terminal's one `ACTIVE` agreement."

    Design: Corner/entities/sale_and_stock_totals_cannot_be_set_from_the_request_body
    """
    terminal = fx.register_terminal(
        api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE", liquid_limit_ml=3000
    )
    agreement = fx.active_agreement(api, terminal["id"])
    itinerary = fx.scanned_itinerary(api, terminal["id"], passenger_ref="PAX-0102")

    sale = created(
        api.create_sale(
            f.sale_payload(
                itinerary["id"],
                "IN_STORE",
                gross_amount_cents=50000,
                duty_liability_cents=4200,
                fulfillment_status="PICKED_UP",
            ),
            SALES_ASSOCIATE_HEADERS,
        )
    )

    assert_sale_amounts(sale, 0, 0, 0)
    assert_sale_dimensions(sale, "CART", "SUSPENDED")
    assert sale["terminal_id"] == terminal["id"]
    assert sale["agreement_id"] == agreement["id"]


def test_every_lifecycle_aggregate_opens_in_its_declared_initial_state(api):
    """An agreement is DRAFT, a grant is already ACTIVE and an audit is DRAFT at round one.

    PRD 3.10: "A drafted agreement starts in `DRAFT` standing with `gross_sales_cents` and `percentage_rent_cents` at 0, `final_rent_cents`, `marketing_credit_cents`, `net_rent_cents` and `rent_basis` all null, and `closed_at` null."

    Design: Corner/state_machines/every_lifecycle_entity_starts_in_its_declared_initial_state
    """
    terminal = fx.register_terminal(
        api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE", liquid_limit_ml=3000
    )
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    product = fx.register_product(
        api, brand["id"], sku="AUR-WHISKY-700", is_liquid=True, liquid_ml=700
    )
    stock_item = fx.open_ledger(api, terminal["id"], product["id"])

    agreement = fx.draft_agreement(api, terminal["id"])
    grant = fx.grant_exclusivity(
        api, brand["id"], terminal["id"], scope="CATEGORY_PREFERRED", effective_to="2026-09-01T00:00:00Z"
    )
    audit = fx.open_audit(api, terminal["id"], stock_item["id"], "2026-08")

    assert agreement["status"] == "DRAFT"
    assert agreement["gross_sales_cents"] == 0
    assert agreement["percentage_rent_cents"] == 0
    assert_nulls(agreement, "final_rent_cents", "marketing_credit_cents", "net_rent_cents", "rent_basis", "closed_at")

    assert grant["status"] == "ACTIVE"
    assert grant["revoked_at"] is None

    assert audit["status"] == "DRAFT"
    assert audit["round_count"] == 1
    assert_nulls(audit, "counted_qty", "expected_qty_snapshot", "auditor_user_id", "info_request_note", "closed_at")
    assert audit["preparer_user_id"] == USER_STOCK
    assert brand["status"] == "ACTIVE"


def test_an_audit_opens_with_no_count_and_no_adjudicator(api):
    """The count, the snapshot and the assessment figures are all still unwritten.

    PRD 3.9: "creates the audit in `DRAFT` standing with `counted_qty` and `expected_qty_snapshot` null, `shrinkage_qty`, `assessable_qty` and `assessed_duty_cents` at 0, `round_count` at 1, `auditor_user_id`, `info_request_note` and `closed_at` all null."

    Design: Corner/state_machines/every_lifecycle_entity_starts_in_its_declared_initial_state
    """
    estate = fx.liquor_estate(api, with_agreement=False)

    audit = fx.open_audit(api, estate.terminal["id"], estate.stock_item["id"], "2026-08")

    assert audit["shrinkage_qty"] == 0
    assert audit["assessable_qty"] == 0
    assert audit["assessed_duty_cents"] == 0
    read_back = ok(api.get_audit(audit["id"], CUSTOMS_AUDITOR_HEADERS))
    assert read_back["status"] == "DRAFT"
    assert read_back["round_count"] == 1
    assert read_back["counted_qty"] is None


def test_reference_aggregates_round_trip_through_their_single_resource_reads(api):
    """A brand, an allowance rule and a grant come back byte for byte on their own reads.

    PRD 3.1: "A brand's `status` starts at `ACTIVE` with `suspended_at` null."

    Design: Corner/endpoints/reference_aggregate_creates_round_trip_through_their_single_resource_reads
    """
    terminal = fx.register_terminal(
        api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE", liquid_limit_ml=3000
    )
    advisory = "Australia: 2.25 L of alcohol per adult traveller."

    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    rule = fx.publish_allowance_rule(
        api, destination_country="AU", category="LIQUOR", allowance_units=10, advisory_text=advisory
    )
    grant = fx.grant_exclusivity(
        api,
        brand["id"],
        terminal["id"],
        category="LIQUOR",
        scope="CATEGORY_PREFERRED",
        effective_from=CLOCK_START,
        effective_to="2026-12-01T00:00:00Z",
    )

    brand_read = ok(api.get_brand(brand["id"], SALES_ASSOCIATE_HEADERS))
    assert brand_read["name"] == "Aurora Spirits"
    assert brand_read["category"] == "LIQUOR"
    assert brand_read["status"] == "ACTIVE"
    assert brand_read["suspended_at"] is None

    rule_read = ok(api.get_allowance_rule(rule["id"], make_passenger_headers(terminal["id"])))
    assert rule_read["allowance_units"] == 10
    assert rule_read["advisory_text"] == advisory
    assert rule_read["status"] == "ACTIVE"
    assert rule_read["superseded_at"] is None

    grant_read = ok(api.get_grant(grant["id"], STOCK_CONTROLLER_HEADERS))
    assert grant_read["scope"] == "CATEGORY_PREFERRED"
    assert grant_read["status"] == "ACTIVE"
    assert grant_read["revoked_at"] is None
    assert_instant(grant_read["effective_from"], CLOCK_START, "effective_from")
    assert_instant(grant_read["effective_to"], "2026-12-01T00:00:00Z", "effective_to")


def test_the_brand_collection_filter_narrows_to_the_matching_row(api):
    """The declared brand filters are equality filters over the stored rows.

    PRD 2.3: "Brands filter on `category` and `status`."

    Design: Corner/endpoints/reference_aggregate_creates_round_trip_through_their_single_resource_reads
    """
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    fx.register_brand(api, name="Embassy Cigars", category="TOBACCO")

    rows, meta = page(
        api.list_brands(TERMINAL_ADMIN_HEADERS, {"category": "LIQUOR", "status": "ACTIVE"})
    )

    assert [row["id"] for row in rows] == [brand["id"]]
    assert meta["total_count"] == 1


def test_the_logical_clock_starts_at_the_mandated_default(api):
    """The first write is stamped from the boot value, never from wall-clock time.

    PRD 2.4: "starts at exactly `2026-08-01T00:00:00Z` when the service boots and only ever moves when a `TerminalAdmin` drives it"

    Design: Corner/endpoints/the_logical_clock_starts_at_the_mandated_default_and_stamps_every_write
    """
    terminal = fx.register_terminal(
        api, iata_code="SIN", country_code="SG", sealed_bag_regime="NONE", liquid_limit_ml=3000
    )

    assert_instant(terminal["created_at"], CLOCK_START, "terminal created_at")

    projection = validate_success(api.set_clock("2026-08-15T06:30:00Z", TERMINAL_ADMIN_HEADERS))
    assert_instant(projection["current_utc"], "2026-08-15T06:30:00Z", "current_utc")


def test_every_write_after_an_advance_shares_the_same_logical_stamp(api):
    """Two writes between clock moves carry an identical created_at.

    PRD 2.4: "Wherever this document says "the current instant", "now", or stamps a timestamp field, the value written is the logical clock at the moment the request is processed."

    Design: Corner/endpoints/the_logical_clock_starts_at_the_mandated_default_and_stamps_every_write
    """
    fx.advance_clock(api, "2026-08-15T06:30:00Z")

    aurora = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    embassy = fx.register_brand(api, name="Embassy Cigars", category="TOBACCO")

    assert_instant(aurora["created_at"], "2026-08-15T06:30:00Z", "aurora created_at")
    assert_instant(embassy["created_at"], "2026-08-15T06:30:00Z", "embassy created_at")

    suspended = ok(api.suspend_brand(aurora["id"], TERMINAL_ADMIN_HEADERS))
    assert suspended["status"] == "SUSPENDED"
    assert_instant(suspended["suspended_at"], "2026-08-15T06:30:00Z", "suspended_at")

    sibling = ok(api.get_brand(embassy["id"], TERMINAL_ADMIN_HEADERS))
    assert sibling["status"] == "ACTIVE"
