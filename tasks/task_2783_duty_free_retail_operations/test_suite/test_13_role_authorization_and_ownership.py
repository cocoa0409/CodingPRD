"""The five roles as peers: each drives its own surface, none reaches into another's."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_ITINERARY_OWNER,
)
from test_helpers.assertions import (
    assert_instant,
    assert_nulls,
    assert_stock_quantities,
    created,
    ids_of,
    ok,
    page,
)
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    CUSTOMS_AUDITOR_HEADERS,
    SALES_ASSOCIATE_HEADERS,
    STOCK_CONTROLLER_HEADERS,
    TERMINAL_ADMIN_HEADERS,
    make_passenger_headers,
)

PERIOD_END = "2026-09-01T00:00:00Z"


def test_every_role_drives_its_own_exclusive_surface_to_completion(api):
    """One reservation travels from the traveller through the warehouse, the till, the
    landlord's settlement and the customs adjudication, each leg on its own role's header.

    PRD 2.1: "`StockController` — the bonded warehouse controller. Opens stock ledgers, posts receipts and audit adjustments, reverses its own manual movements, prepares customs stock-count audits and submits physical counts, and converts pre-orders into baskets."

    Design: Corner/rbac/each_role_executes_its_own_exclusive_operations_end_to_end
    """
    terminal = fx.register_terminal(api, iata_code="SIN", country_code="SG")
    brand = fx.register_brand(api, name="Aurora Spirits", category="LIQUOR")
    whisky = fx.listed_product(
        api,
        brand["id"],
        sku="AUR-WHISKY-700",
        category="LIQUOR",
        is_liquid=True,
        liquid_ml=700,
    )
    fx.publish_allowance_rule(
        api,
        destination_country="AU",
        category="LIQUOR",
        allowance_units=10,
        advisory_text="Australia: 2.25 L of alcohol per adult traveller.",
    )
    grant = fx.grant_exclusivity(
        api,
        brand["id"],
        terminal["id"],
        category="LIQUOR",
        scope="TERMINAL_EXCLUSIVE",
        effective_from=CLOCK_START,
        effective_to="2026-12-01T00:00:00Z",
    )
    agreement = fx.active_agreement(api, terminal["id"])
    stock_item = fx.stocked_ledger(api, terminal["id"], whisky["id"], 20)
    itinerary = fx.scanned_itinerary(api, terminal["id"], departure_utc="2026-08-20T10:00:00Z")

    passenger = make_passenger_headers(itinerary["id"])
    seen = ok(api.get_stock_item(stock_item["id"], passenger))
    reservation = created(
        api.create_pre_order(
            f.pre_order_payload(
                itinerary["id"],
                stock_item["id"],
                2,
                seen["version"],
                reservation_window_start="2026-08-02T00:00:00Z",
                reservation_window_end="2026-08-20T09:00:00Z",
            ),
            passenger,
        )
    )
    assert reservation["status"] == "RESERVED"

    fx.advance_clock(api, "2026-08-02T00:00:00Z")
    converted = ok(api.convert_pre_order(reservation["id"], STOCK_CONTROLLER_HEADERS))
    assert converted["status"] == "CONVERTED"
    sale_id = converted["converted_sale_id"]

    ok(api.clear_eligibility(sale_id, SALES_ASSOCIATE_HEADERS))
    picked = ok(api.pickup_sale(sale_id, SALES_ASSOCIATE_HEADERS))
    assert picked["channel"] == "PRE_ORDER"
    assert picked["fulfillment_status"] == "PICKED_UP"
    assert picked["gross_amount_cents"] == 16000

    projection = ok(api.get_rent_projection(agreement["id"], TERMINAL_ADMIN_HEADERS))
    assert projection["gross_sales_cents"] == 16000

    fx.advance_clock(api, PERIOD_END)
    settled = fx.close_agreement(api, agreement["id"])
    assert settled["status"] == "CLOSED"
    assert settled["gross_sales_cents"] == 16000
    assert settled["final_rent_cents"] == 10000

    audit = fx.open_audit(api, terminal["id"], stock_item["id"])
    fx.submit_count(api, audit["id"], 18)
    adjudicated = fx.adjudicate_audit(api, audit["id"])
    assert adjudicated["status"] == "CLOSED_CLEAN"
    assert adjudicated["shrinkage_qty"] == 0
    assert adjudicated["assessed_duty_cents"] == 0

    revoked = ok(api.revoke_grant(grant["id"], TERMINAL_ADMIN_HEADERS))
    assert revoked["status"] == "REVOKED"
    assert_instant(revoked["revoked_at"], PERIOD_END, "revoked_at")
    suspended = ok(api.suspend_brand(brand["id"], TERMINAL_ADMIN_HEADERS))
    assert suspended["status"] == "SUSPENDED"
    assert_instant(suspended["suspended_at"], PERIOD_END, "suspended_at")

    ledger = ok(api.get_stock_item(stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(ledger, on_hand=18, reserved=0, available=18)


def test_no_role_may_reach_into_another_roles_exclusive_operation(api):
    """Seven crossings of the role boundary, including the administrator into the warehouse
    and the auditor into the count they will adjudicate, and none of them writes anything.

    PRD 2.1: "When the headers are well formed but the named role is not authorised for the operation being called, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/another_roles_exclusive_operation_is_unauthorized_for_every_peer_role
    """
    estate = fx.liquor_estate(api, allowance_units=10)
    itinerary = fx.scanned_itinerary(api, estate.terminal["id"], departure_utc="2026-08-20T10:00:00Z")
    audit = fx.open_audit(api, estate.terminal["id"], estate.stock_item["id"])

    validate_error(
        api.create_movement(
            f.movement_payload(estate.stock_item["id"], "AUDIT_ADJUSTMENT", 5), TERMINAL_ADMIN_HEADERS
        ),
        ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.create_sale(f.sale_payload(itinerary["id"]), STOCK_CONTROLLER_HEADERS), ERR_FORBIDDEN_ROLE
    )
    validate_error(
        api.create_brand(f.brand_payload(name="Embassy Cigars", category="TOBACCO"), SALES_ASSOCIATE_HEADERS),
        ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.get_rent_projection(estate.agreement["id"], SALES_ASSOCIATE_HEADERS), ERR_FORBIDDEN_ROLE
    )
    validate_error(
        api.submit_audit(audit["id"], f.audit_submit_payload(9), CUSTOMS_AUDITOR_HEADERS),
        ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.close_audit(audit["id"], make_passenger_headers(itinerary["id"])), ERR_FORBIDDEN_ROLE
    )
    validate_error(
        api.set_clock("2026-08-10T00:00:00Z", STOCK_CONTROLLER_HEADERS), ERR_FORBIDDEN_ROLE
    )

    ledger = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(ledger, on_hand=10, reserved=0, available=10)

    movements, _ = page(
        api.list_movements(STOCK_CONTROLLER_HEADERS, {"stock_item_id": estate.stock_item["id"]})
    )
    assert len(movements) == 1
    assert movements[0]["movement_type"] == "RECEIPT"

    sales, _ = page(api.list_sales(SALES_ASSOCIATE_HEADERS, {"itinerary_id": itinerary["id"]}))
    assert sales == []

    brands, _ = page(api.list_brands(TERMINAL_ADMIN_HEADERS))
    assert ids_of(brands) == [estate.brand["id"]]

    stored_audit = ok(api.get_audit(audit["id"], CUSTOMS_AUDITOR_HEADERS))
    assert stored_audit["status"] == "DRAFT"
    assert_nulls(stored_audit, "counted_qty", "auditor_user_id")

    late_brand = fx.register_brand(api, name="Embassy Cigars", category="TOBACCO")
    assert_instant(late_brand["created_at"], CLOCK_START, "created_at")


def test_a_passenger_reads_only_the_records_that_trace_back_to_their_own_itinerary(api):
    """The traveller sees their own itinerary, basket and line and the open catalogue, and is
    refused on the neighbouring traveller's rows that an operator role reads freely.

    PRD 2.1: "The same rule scopes a passenger's reads: itinerary-scoped records — the itinerary itself, its sales, its sale lines, its sealed bags and its pre-orders — are visible to a `Passenger` only when they trace back to that passenger's own itinerary, and a request for someone else's record is rejected with `ERR_NOT_ITINERARY_OWNER`."

    Design: Corner/rbac/passenger_reads_outside_the_callers_own_itinerary_are_forbidden
    """
    estate = fx.liquor_estate(api, receipt_qty=20, allowance_units=10)
    itinerary_a = fx.scanned_itinerary(
        api,
        estate.terminal["id"],
        passenger_ref="PAX-0152",
        nationality_code="CN",
        boarding_pass_barcode="BP-0152",
        departure_utc="2026-08-20T10:00:00Z",
    )
    itinerary_b = fx.scanned_itinerary(
        api,
        estate.terminal["id"],
        passenger_ref="PAX-0153",
        nationality_code="JP",
        boarding_pass_barcode="BP-0153",
        departure_utc="2026-08-21T10:00:00Z",
    )
    sale_a = fx.open_basket(api, itinerary_a["id"])
    line_a = fx.append_line(api, sale_a["id"], estate.product["id"], 1)
    reservation_b = fx.place_reservation(
        api,
        itinerary_b["id"],
        estate.stock_item,
        3,
        reservation_window_start="2026-08-02T00:00:00Z",
        reservation_window_end="2026-08-21T09:00:00Z",
    )

    passenger_a = make_passenger_headers(itinerary_a["id"])
    passenger_b = make_passenger_headers(itinerary_b["id"])

    assert ok(api.get_itinerary(itinerary_a["id"], passenger_a))["id"] == itinerary_a["id"]
    assert ok(api.get_sale(sale_a["id"], passenger_a))["id"] == sale_a["id"]
    assert ok(api.get_sale_line(line_a["id"], passenger_a))["id"] == line_a["id"]
    assert ok(api.get_product(estate.product["id"], passenger_a))["assortment_status"] == "LISTED"

    validate_error(api.get_itinerary(itinerary_b["id"], passenger_a), ERR_NOT_ITINERARY_OWNER)
    validate_error(api.get_pre_order(reservation_b["id"], passenger_a), ERR_NOT_ITINERARY_OWNER)

    own = ok(api.get_pre_order(reservation_b["id"], passenger_b))
    assert own["qty"] == 3
    assert own["status"] == "RESERVED"
    assert ok(api.get_pre_order(reservation_b["id"], STOCK_CONTROLLER_HEADERS))["status"] == "RESERVED"

    ledger = ok(api.get_stock_item(estate.stock_item["id"], STOCK_CONTROLLER_HEADERS))
    assert_stock_quantities(ledger, on_hand=20, reserved=3, available=17)
