"""Uniqueness scope, cross-entity guards, temporal edges and aggregate limits."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories
from test_helpers import fixtures as F
from test_helpers.constants import DELI_FOUR_RUNGS, MISSING_ID
from test_helpers.test_users import (
    clerk_headers,
    make_clerk_headers,
    make_manager_headers,
    make_partner_headers,
    manager_headers,
)

RECORDER_USER_ID = "u-clerk-1"
VERIFIER_USER_ID = "u-mgr-1"


def test_a_second_item_with_the_same_upc_in_one_department_is_refused(api):
    """The repeat create is a 409 and leaves the first item's price untouched.

    PRD 3.1: "An item belongs to a department by `department_id` and carries a `upc` of
    exactly 12 digits, unique within its department -- a repeat is refused with
    `ERR_ITEM_UPC_DUPLICATE`."

    PRD 2.11: "40. Uniqueness -- store number globally, ladder name globally, department code
    within a store, item UPC within a department -- on store creation, ladder creation,
    department creation and item creation -- `ERR_STORE_NUMBER_DUPLICATE`,
    `ERR_LADDER_NAME_DUPLICATE`, `ERR_DEPARTMENT_CODE_DUPLICATE` or
    `ERR_ITEM_UPC_DUPLICATE` (409)."

    Design: Corner/validations/duplicate_upc_inside_one_department_is_rejected
    """
    chain = F.build_meat_chain(api, with_lot=False)
    assert chain.item["upc"] == "000111222333"

    repeat = api.create_item(
        factories.create_item_payload(
            chain.department["id"],
            upc="000111222333",
            description="Ribeye Steak 12oz (relabel)",
            base_retail_cents=649,
            unit_cost_cents=430,
            daily_forecast_units=3.00,
        ),
        manager_headers(),
    )
    validate_error(repeat, "ERR_ITEM_UPC_DUPLICATE", expected_status=409)

    rows, meta = validate_paginated(
        api.list_items(
            manager_headers(),
            params={"department_id": chain.department["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1
    A.assert_ids_equal(rows, [chain.item["id"]])

    survivor = F.reload_item(api, chain.item["id"])
    A.assert_money_cents(survivor["base_retail_cents"], 599, "base_retail_cents")
    A.assert_money_cents(survivor["unit_cost_cents"], 420, "unit_cost_cents")
    A.assert_fields(survivor, description="Ribeye Steak 12oz", version=1)


def test_the_same_upc_is_free_to_appear_once_in_each_department(api):
    """Uniqueness is scoped to the department, so MEAT and DELI may share a UPC.

    PRD 3.1: "An item belongs to a department by `department_id` and carries a `upc` of
    exactly 12 digits, unique within its department -- a repeat is refused with
    `ERR_ITEM_UPC_DUPLICATE`."

    PRD 2.11: "40. Uniqueness -- store number globally, ladder name globally, department code
    within a store, item UPC within a department".

    Design: Corner/validations/same_upc_in_a_different_department_is_accepted
    """
    chain = F.build_meat_chain(api, with_lot=False)
    ladder_deli = F.build_ladder(
        api,
        name="DELI-STD-2026",
        department_code="DELI",
        rungs=[DELI_FOUR_RUNGS[0], DELI_FOUR_RUNGS[2]],
    )
    department_deli = F.build_department(
        api,
        chain.store["id"],
        ladder_deli["id"],
        code="DELI",
        shelf_life_days_default=4,
    )

    accepted = validate_success(
        api.create_item(
            factories.create_item_payload(
                department_deli["id"],
                upc="000111222333",
                description="Rotisserie Chicken",
                base_retail_cents=700,
                unit_cost_cents=300,
                daily_forecast_units=5.00,
            ),
            manager_headers(),
        ),
        expected_status=201,
    )

    A.assert_fields(
        accepted,
        department_id=department_deli["id"],
        upc="000111222333",
        description="Rotisserie Chicken",
        version=1,
    )

    meat_rows, meat_meta = validate_paginated(
        api.list_items(
            manager_headers(),
            params={"department_id": chain.department["id"], "limit": 100},
        )
    )
    assert meat_meta["total_count"] == 1
    A.assert_ids_equal(meat_rows, [chain.item["id"]])

    deli_rows, deli_meta = validate_paginated(
        api.list_items(
            manager_headers(),
            params={"department_id": department_deli["id"], "limit": 100},
        )
    )
    assert deli_meta["total_count"] == 1
    A.assert_ids_equal(deli_rows, [accepted["id"]])


def test_cold_chain_certification_is_read_off_the_partner_receiving_the_meat(api):
    """One MEAT lot, two pickups: the uncertified partner is refused, the certified one is not.

    PRD 3.7: "If the lot's department `code` is `MEAT` or `SEAFOOD`, the partner's
    `cold_chain_certified` must be true; an uncertified partner receiving refrigerated
    protein is refused with `ERR_COLD_CHAIN_NOT_CERTIFIED` and HTTP 422. Departments other
    than `MEAT` and `SEAFOOD` impose no cold-chain requirement."

    PRD 2.11: "15. Cold-chain certification for `MEAT` and `SEAFOOD`, on manifest-line
    creation -- `ERR_COLD_CHAIN_NOT_CERTIFIED` (422)."

    PRD 3.7: "`provisional_value_cents` is the sum, over every manifest line on the pickup in
    `ASSIGNED`, of that line's `quantity_units` multiplied by its
    `unit_price_cents_snapshot`."

    Validity here turns on a field of a third entity: the lot, the item and the department are
    identical across both calls, and only the partner differs.

    Design: Corner/validations/cold_chain_certification_is_read_from_the_partner_not_the_lot
    """
    chain = F.build_meat_chain(
        api,
        store_overrides={
            "dock_door_codes": ["D1", "D2"],
            "donation_program_enabled": True,
        },
    )
    partner_ambient = F.build_partner(
        api,
        name="Ambient Pantry",
        contact_email="ops@ambient.example",
        service_region_code="MID-ATL",
        accepted_department_codes=["MEAT"],
    )
    partner_chilled = F.build_partner(
        api,
        name="Chilled Relief",
        contact_email="ops@chilled.example",
        service_region_code="MID-ATL",
        accepted_department_codes=["MEAT"],
        cold_chain_certified=True,
    )
    assert partner_ambient["cold_chain_certified"] is False
    assert partner_chilled["cold_chain_certified"] is True

    F.set_clock(api, "2026-08-13T12:00:00.000Z")
    pickup_ambient = F.book_pickup(
        api,
        chain.store["id"],
        partner_ambient["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-13T14:00:00.000Z",
        scheduled_window_end="2026-08-13T15:00:00.000Z",
        headers=manager_headers(),
    )
    pickup_chilled = F.book_pickup(
        api,
        chain.store["id"],
        partner_chilled["id"],
        dock_door_code="D2",
        scheduled_window_start="2026-08-13T14:00:00.000Z",
        scheduled_window_end="2026-08-13T15:00:00.000Z",
        headers=manager_headers(),
    )

    refused = api.create_donation_assignment(
        pickup_ambient["id"],
        factories.create_donation_assignment_payload(chain.lot["id"], 10),
        clerk_headers(),
    )
    validate_error(refused, "ERR_COLD_CHAIN_NOT_CERTIFIED", expected_status=422)

    assert F.reload_lot(api, chain.lot["id"])["status"] == "FRESH"
    assert F.reload_pickup(api, pickup_ambient["id"])["assignment_count"] == 0

    accepted = F.pledge_lot(api, pickup_chilled["id"], chain.lot["id"], 10)
    A.assert_fields(accepted, status="ASSIGNED", quantity_units=10)
    A.assert_money_cents(
        accepted["unit_price_cents_snapshot"], 599, "unit_price_cents_snapshot"
    )
    A.assert_money_cents(accepted["line_value_cents"], 5990, "line_value_cents")
    A.assert_money_cents(accepted["line_credit_cents"], 0, "line_credit_cents")

    reserved = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(reserved, status="DONATION_PENDING", quantity_on_hand=24, units_donated=0)
    A.assert_lot_units_conservation(reserved)

    sealed_side = F.reload_pickup(api, pickup_chilled["id"])
    A.assert_fields(sealed_side, assignment_count=1)
    A.assert_money_cents(
        sealed_side["provisional_value_cents"], 5990, "provisional_value_cents"
    )


def test_the_donation_window_opens_at_the_forty_eight_hour_instant_not_before(api):
    """One millisecond early the pledge is refused; at the instant itself it is accepted.

    PRD 3.7: "The logical clock is at or after 48 hours before the lot's `sell_by_at`.
    Product with more than two days of life left is still saleable, so the donation window
    has not opened, and the attempt is refused with `ERR_DONATION_WINDOW_CLOSED` and HTTP
    422. Taken with the previous condition this is the half-open window of 2.10: the instant
    exactly 48 hours before sell-by qualifies, the sell-by instant itself does not."

    PRD 2.11: "27. The donation window has opened, on manifest-line creation --
    `ERR_DONATION_WINDOW_CLOSED` (422)."

    A lot produced 2026-08-10 in a department with a 5-day default sells by
    2026-08-15T00:00:00.000Z, so its window opens at 2026-08-13T00:00:00.000Z.

    Design: Corner/validations/donation_window_opens_exactly_fortyeight_hours_before_sell_by
    """
    chain = F.build_produce_chain(
        api,
        store_overrides={"dock_door_codes": ["D1"], "donation_program_enabled": True},
        item_overrides={
            "upc": "000444555666",
            "description": "Blueberries 6oz",
            "base_retail_cents": 599,
            "unit_cost_cents": 300,
            "daily_forecast_units": 8.00,
        },
        lot_overrides={"production_date": "2026-08-10", "quantity_original": 10},
    )
    A.assert_instant_equals(
        chain.lot["sell_by_at"], "2026-08-15T00:00:00.000Z", "sell_by_at"
    )
    pickup = F.book_pickup(
        api,
        chain.store["id"],
        chain.partner["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-13T14:00:00.000Z",
        scheduled_window_end="2026-08-13T15:00:00.000Z",
        headers=manager_headers(),
    )

    F.set_clock(api, "2026-08-12T23:59:59.999Z")
    too_early = api.create_donation_assignment(
        pickup["id"],
        factories.create_donation_assignment_payload(chain.lot["id"], 10),
        clerk_headers(),
    )
    validate_error(too_early, "ERR_DONATION_WINDOW_CLOSED", expected_status=422)

    untouched = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(untouched, status="FRESH", quantity_on_hand=10)
    assert F.reload_pickup(api, pickup["id"])["assignment_count"] == 0

    F.set_clock(api, "2026-08-13T00:00:00.000Z")
    accepted = F.pledge_lot(api, pickup["id"], chain.lot["id"], 10)
    A.assert_fields(accepted, status="ASSIGNED", quantity_units=10)

    reserved = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(reserved, status="DONATION_PENDING", quantity_on_hand=10)


def test_two_individually_legal_write_offs_collide_over_the_lots_remaining_units(api):
    """20 sold and 5 shrunk are each under 24, but together they overrun the lot.

    PRD 3.6: "`quantity_units` must be greater than 0 and at most the lot's
    `quantity_on_hand`; more than that is refused with `ERR_INSUFFICIENT_UNITS`."

    PRD 2.11: "34. Requested units do not exceed the lot's units on hand, on sale posting,
    shrink recording, shrink resubmission, shrink verification and manifest-line creation --
    `ERR_INSUFFICIENT_UNITS` (422)."

    PRD 3.5: "When a sale takes `quantity_on_hand` to exactly 0, the lot moves from `FRESH`
    or `MARKED_DOWN` to `DEPLETED` in the same operation [...] The same depletion transition
    fires when a shrink verification drains the last unit."

    PRD 2.9: "Lots that are `DONATED`, `WITHDRAWN` or `DEPLETED` are excluded entirely."

    Conservation still holds at the end: 24 == 0 on hand + 20 sold + 4 shrunk + 0 donated.

    Design: Corner/validations/individually_valid_sale_and_shrink_collectively_exceed_the_lot
    """
    chain = F.build_meat_chain(api)
    sold = F.post_sale(api, chain.lot["id"], 20, register_lane_code="L07")
    A.assert_fields(sold, quantity_on_hand=4, units_sold=20, status="FRESH")

    over = api.create_shrink_event(
        factories.create_shrink_event_payload(chain.lot["id"], 5, cause_code="DAMAGE"),
        make_clerk_headers(RECORDER_USER_ID),
    )
    validate_error(over, "ERR_INSUFFICIENT_UNITS", expected_status=422)
    assert F.reload_lot(api, chain.lot["id"])["quantity_on_hand"] == 4

    exact = validate_success(
        api.create_shrink_event(
            factories.create_shrink_event_payload(chain.lot["id"], 4, cause_code="DAMAGE"),
            make_clerk_headers(RECORDER_USER_ID),
        ),
        expected_status=201,
    )
    A.assert_fields(exact, status="RECORDED", quantity_units=4, cause_code="DAMAGE")

    verified = validate_success(
        api.verify_shrink_event(exact["id"], make_manager_headers(VERIFIER_USER_ID)),
        expected_status=200,
    )
    assert verified["status"] == "VERIFIED"

    drained = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(
        drained,
        quantity_on_hand=0,
        units_sold=20,
        units_shrunk=4,
        units_donated=0,
        status="DEPLETED",
    )
    A.assert_lot_units_conservation(drained)

    department = F.reload_department(api, chain.department["id"])
    A.assert_money_cents(
        department["markdown_liability_cents"], 0, "markdown_liability_cents"
    )


def test_sampling_shrink_is_gated_by_the_items_own_flag_and_nothing_else(api):
    """The identical SAMPLING record flips from 422 to 201 once the item allows sampling.

    PRD 3.6: "`SAMPLING` is special: it is only accepted when the lot's item has
    `sampling_allowed` set true, and otherwise the record is refused with
    `ERR_SAMPLING_NOT_ALLOWED` and HTTP 422."

    PRD 3.1: "`sampling_allowed`, defaulting to false, decides whether shrink may ever be
    booked against this item under the sampling cause code" and "An administrator or manager
    may later revise an item's `status`, `daily_forecast_units`, `donation_eligible` and
    `sampling_allowed`, and each revision bumps the item's `version` by one".

    PRD 3.6: "`cost_value_cents` is the fully loaded cost of the shrink: the units written
    off multiplied by that cost snapshot, then increased by a waste-handling surcharge of 3.5
    percent, then rounded half up to whole cents."  Two units at 420 cents is 840, and 840
    times 1.035 is 869.4, which rounds half up to 869 -- the surcharge is not optional.

    Design: Corner/validations/sampling_cause_code_depends_on_the_items_sampling_flag
    """
    chain = F.build_meat_chain(api)
    assert chain.item["sampling_allowed"] is False

    gated = api.create_shrink_event(
        factories.create_shrink_event_payload(chain.lot["id"], 2, cause_code="SAMPLING"),
        make_clerk_headers(RECORDER_USER_ID),
    )
    validate_error(gated, "ERR_SAMPLING_NOT_ALLOWED", expected_status=422)

    patched = validate_success(
        api.update_item(
            chain.item["id"],
            factories.update_item_payload(sampling_allowed=True),
            manager_headers(),
        ),
        expected_status=200,
    )
    A.assert_fields(patched, sampling_allowed=True, version=2)

    allowed = validate_success(
        api.create_shrink_event(
            factories.create_shrink_event_payload(
                chain.lot["id"], 2, cause_code="SAMPLING"
            ),
            make_clerk_headers(RECORDER_USER_ID),
        ),
        expected_status=201,
    )
    A.assert_fields(allowed, cause_code="SAMPLING", status="RECORDED", quantity_units=2)
    A.assert_money_cents(
        allowed["unit_cost_cents_snapshot"], 420, "unit_cost_cents_snapshot"
    )
    A.assert_money_cents(allowed["cost_value_cents"], 869, "cost_value_cents")

    rows, meta = validate_paginated(
        api.list_shrink_events(
            manager_headers(),
            params={"lot_id": chain.lot["id"], "cause_code": "SAMPLING", "limit": 100},
        )
    )
    assert meta["total_count"] == 1
    A.assert_ids_equal(rows, [allowed["id"]])


def test_an_unknown_pickup_id_answers_404_before_ownership_can_be_read(api):
    """A partner naming a missing pickup gets 404; naming someone else's gets 403.

    PRD 2.1: "Ownership checks on any pickup or manifest resource compare the pickup's
    `partner_id` foreign key to `X-User-ID`: a `DonationPartner` confirming, completing,
    cancelling or reading a pickup whose `partner_id` is not its own `X-User-ID` receives
    `ERR_UNAUTHORIZED` with HTTP 403. That ownership check runs **after** the endpoint's role
    check and **after** path-identifier existence has been established, so a
    `DonationPartner` naming a pickup identifier that does not exist at all still receives a
    404, not a 403."

    PRD 2.11: "4. Path-identifier existence, validated left to right" ahead of "6. Resource
    ownership for entity-backed roles: a `DonationPartner` must own the pickup it confirms,
    completes, cancels or reads by identifier -- `ERR_UNAUTHORIZED` (403)."

    Design: Corner/validations/unknown_pickup_id_answers_404_before_the_ownership_check_can_run
    """
    store = F.build_store(
        api, dock_door_codes=["D1"], donation_program_enabled=True
    )
    partner_alpha = F.build_partner(
        api,
        name="Alpha Pantry",
        contact_email="ops@alpha.example",
        service_region_code="MID-ATL",
        accepted_department_codes=["PRODUCE"],
    )
    partner_beta = F.build_partner(
        api,
        name="Beta Pantry",
        contact_email="ops@beta.example",
        service_region_code="MID-ATL",
        accepted_department_codes=["PRODUCE"],
    )
    pickup = F.book_pickup(
        api,
        store["id"],
        partner_alpha["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-13T14:00:00.000Z",
        scheduled_window_end="2026-08-13T15:00:00.000Z",
        headers=manager_headers(),
    )

    missing = api.confirm_donation_pickup(
        MISSING_ID, make_partner_headers(partner_beta["id"])
    )
    validate_error(missing, "ERR_PICKUP_NOT_FOUND", expected_status=404)

    not_yours = api.confirm_donation_pickup(
        pickup["id"], make_partner_headers(partner_beta["id"])
    )
    validate_error(not_yours, "ERR_UNAUTHORIZED", expected_status=403)

    still_scheduled = F.reload_pickup(api, pickup["id"])
    A.assert_fields(still_scheduled, logistics_status="SCHEDULED", version=1)

    confirmed = F.confirm_pickup(api, pickup["id"], partner_alpha["id"])
    A.assert_fields(confirmed, logistics_status="CONFIRMED", manifest_status="DRAFT")
