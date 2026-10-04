"""Lot capacity boundaries, schedule-close cascade, OCC on lot and store,
gap-check scoping, hazmat daily tally."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_campaign,
    create_account,
    create_campaign_ready,
    create_chick_order_payload,
    create_finalized_propane_sale,
    create_hatchery_schedule_payload,
    create_on_sale_lot,
    create_open_store,
    create_store,
    create_store,
    create_provisional_sale,
    create_published_schedule,
    make_customer_headers,
    place_chick_order,
    set_clock,
    setup_reserved_order,
    setup_spring_store,
    validate_error,
    validate_success,
)

RA = TEST_USERS["regional_admin_headers"]
MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]

SPRING_NOW = "2026-03-10T10:00:00Z"
FALL_NOW = "2026-09-20T10:00:00Z"
FLOOR_NOW = "2026-09-10T09:00:00Z"


def test_lot_capacity_boundary_exactly_on_hand(api):
    """PRD §3.4: "must not exceed the lot's `quantity_on_hand` (otherwise `ERR_LOT_CAPACITY_EXCEEDED`)."

    Design: Corner/validations/lot_capacity_boundary_exactly_on_hand
    """
    set_clock(SPRING_NOW)
    store = create_open_store(
        season="SPRING_PLANTING", aisle_count=2,
        name="Waxahachie Farm & Ranch", region_code="TX-NORTH",
    )
    schedule = create_published_schedule(
        store, species="DUCK", breed="Pekin",
        min_purchase_qty=4, base_price_cents_per_bird=599,
    )
    lot = create_on_sale_lot(store, schedule, quantity_received=10)
    account = create_account()
    cust = make_customer_headers(account["id"])

    over = api.create_chick_order(
        create_chick_order_payload(
            store["id"], lot["id"], account["id"], lot["version"], quantity=11,
        ),
        cust,
    )
    validate_error(over, ApiErrorId.ERR_LOT_CAPACITY_EXCEEDED)

    # The last bird is sellable: quantity == quantity_on_hand succeeds.
    exact = validate_success(
        api.create_chick_order(
            create_chick_order_payload(
                store["id"], lot["id"], account["id"], lot["version"], quantity=10,
            ),
            cust,
        ),
        expected_status=201,
    )
    assert exact["status"] == "RESERVED"

    lot_after = validate_success(api.get_livestock_lot(lot["id"], MGR))
    assert lot_after["quantity_on_hand"] == 0


def test_schedule_close_cascades_lots_and_orders_with_release(api):
    """PRD §3.2: "A `PUBLISHED` schedule closes to `CLOSED` — attempted from any other status it fails with `ERR_SCHEDULE_NOT_PUBLISHED` — and the closure cascades: every `ON_SALE` lot under the schedule moves to `SALE_CLOSED`, and each lot closure expires its `RESERVED` and `BROODER_VERIFIED` chick orders to `EXPIRED` with the reserved quantity released back to `quantity_on_hand`."

    Design: Corner/state_machines/schedule_close_cascades_lots_and_orders_with_release
    """
    ctx = setup_reserved_order()

    closed = validate_success(api.close_hatchery_schedule(ctx["schedule"]["id"], {}, MGR))
    assert closed["status"] == "CLOSED"

    lot = validate_success(api.get_livestock_lot(ctx["lot"]["id"], MGR))
    assert lot["status"] == "SALE_CLOSED"
    assert lot["quantity_on_hand"] == 100  # 6 reserved birds released

    order = validate_success(api.get_chick_order(ctx["order"]["id"], MGR))
    assert order["status"] == "EXPIRED"


def test_stale_store_version_on_campaign_activation(api):
    """PRD §2.7: "Activating a season campaign requires the request to carry `expected_store_version`, the store `version` the client last observed. ... a client whose observed store version no longer matches the store's current `version` is acting on an out-of-date view of which campaign is live; the activation is rejected with `ERR_STALE_STORE_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_store_version_on_campaign_activation
    """
    set_clock(FLOOR_NOW)
    store = create_store()
    camp1 = create_campaign_ready(store, "FALL_FEED")
    camp2 = create_campaign_ready(store, "WINTER_HEATING")

    activated = validate_success(
        api.activate_campaign(camp1["id"], {"expected_store_version": 1}, RA)
    )
    assert activated["status"] == "ACTIVE"

    store_now = validate_success(api.get_store(store["id"], RA))
    assert store_now["version"] == 2

    # A second activation still carrying version 1 is stale.
    resp = api.activate_campaign(camp2["id"], {"expected_store_version": 1}, RA)
    validate_error(resp, ApiErrorId.ERR_STALE_STORE_VERSION, expected_status=412)

    camp2_after = validate_success(api.get_season_campaign(camp2["id"], RA))
    assert camp2_after["status"] == "READY"


def test_stale_lot_version_on_chick_order_create(api):
    """PRD §2.7: "Creating a chick order requires the request to carry `expected_livestock_lot_version`, the lot `version` the client last observed. Because a reservation legitimately decrements the lot's sellable quantity, a client whose observed lot version no longer matches the lot's current `version` is deciding on an out-of-date view of remaining availability; the reservation is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_lot_version_on_chick_order_create
    """
    ctx = setup_spring_store()
    account = create_account()
    cust = make_customer_headers(account["id"])

    first = place_chick_order(
        ctx["store"], ctx["lot"], account, quantity=6,
        lot_version=ctx["lot_version"],
    )
    assert first["status"] == "RESERVED"

    # Reuse the pre-reservation lot version: stale by one reservation.
    resp = api.create_chick_order(
        create_chick_order_payload(
            ctx["store"]["id"], ctx["lot"]["id"], account["id"],
            ctx["lot_version"], quantity=6,
        ),
        cust,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LOT_VERSION, expected_status=412)

    lot = validate_success(api.get_livestock_lot(ctx["lot"]["id"], MGR))
    assert lot["quantity_on_hand"] == 94


def test_occ_lot_version_bumps_on_every_mutation(api):
    """PRD §2.4: "an integer `version` that starts at 1 and increments by exactly one on every mutation of that resource."
    PRD §3.4: "The reservation decrements the lot's `quantity_on_hand` by the ordered quantity and increments the lot's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_lot_version_bumps_on_every_mutation
    """
    ctx = setup_spring_store()
    account = create_account()

    assert ctx["lot"]["version"] == 2  # create 1, open-sale 2

    order = place_chick_order(
        ctx["store"], ctx["lot"], account, quantity=6,
        lot_version=ctx["lot_version"],
    )
    lot3 = validate_success(api.get_livestock_lot(ctx["lot"]["id"], MGR))
    assert lot3["version"] == 3

    validate_success(
        api.cancel_chick_order(
            order["id"], {"reason": "changed mind"},
            make_customer_headers(account["id"]),
        )
    )
    lot4 = validate_success(api.get_livestock_lot(ctx["lot"]["id"], MGR))
    assert lot4["version"] == 4


def test_store_version_derived_posture_consistent_after_supersede(api):
    """PRD §3.1: "First, any other `ACTIVE` campaign on the same store is superseded to `COMPLETED`. Second, the store's `posture` is recomputed to the new campaign's `season`, `active_campaign_id` points at the newly active campaign, and the store's `version` increments."

    Design: Corner/cross_cutting_complexity_layers/store_version_derived_posture_consistent_after_supersede
    """
    ctx = setup_spring_store()
    assert ctx["store"]["posture"] == "SPRING_PLANTING"
    spring_campaign_id = ctx["campaign_id"]
    version_before = validate_success(api.get_store(ctx["store"]["id"], RA))["version"]

    winter_campaign = create_campaign_ready(ctx["store"], "WINTER_HEATING")
    activate_campaign(winter_campaign["id"])

    store = validate_success(api.get_store(ctx["store"]["id"], RA))
    assert store["posture"] == "WINTER_HEATING"
    assert store["active_campaign_id"] == winter_campaign["id"]
    assert store["version"] == version_before + 1

    old = validate_success(api.get_season_campaign(spring_campaign_id, RA))
    assert old["status"] == "COMPLETED"


def test_posture_gate_reevaluates_immediately_after_flip(api):
    """PRD §3.4: "creating one requires the selling store's posture to be `SPRING_PLANTING`, failing otherwise with `ERR_POSTURE_NOT_SPRING_PLANTING`."
    PRD §3.1: "Third, if the new posture is anything other than `SPRING_PLANTING`, every `PUBLISHED` hatchery schedule on the store is closed to `CLOSED`. Fourth, each such schedule closure forces every `ON_SALE` livestock lot beneath it to `SALE_CLOSED`."

    Design: Corner/cross_cutting_complexity_layers/posture_gate_reevaluates_immediately_after_flip
    """
    ctx = setup_spring_store()
    account = create_account()

    # A long-window schedule (still PUBLISHED) with an ON_SALE lot succeeds
    # under spring posture.
    schedule2 = create_published_schedule(
        ctx["store"], species="DUCK", breed="Pekin",
        hatch_date="2026-02-25T00:00:00Z",
        sale_window_start="2026-03-01T00:00:00Z",
        sale_window_end="2026-12-31T23:59:59Z",
    )
    lot2 = create_on_sale_lot(ctx["store"], schedule2)
    order = place_chick_order(
        ctx["store"], lot2, account, quantity=6,
        lot_version=lot2["version"], pickup_date="2026-03-12T10:00:00Z",
    )
    assert order["status"] == "RESERVED"

    fall_campaign = create_campaign_ready(ctx["store"], "FALL_FEED")
    activate_campaign(fall_campaign["id"])

    store = validate_success(api.get_store(ctx["store"]["id"], RA))
    assert store["posture"] == "FALL_FEED"

    lot2_after = validate_success(api.get_livestock_lot(lot2["id"], MGR))
    assert lot2_after["status"] == "SALE_CLOSED"

    # The next order attempt against the store cannot succeed: the posture
    # gate blocks chick orders outside spring.
    resp = api.create_chick_order(
        create_chick_order_payload(
            ctx["store"]["id"], lot2["id"], account["id"],
            lot2_after["version"], quantity=6, pickup_date="2026-03-12T10:00:00Z",
        ),
        make_customer_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_POSTURE_NOT_SPRING_PLANTING)


def test_hazmat_daily_tally_resets_across_utc_dates(api):
    """PRD §3.6: "the store's `hazmat_gallons_used_today` plus this sale's `propane_gallons` must not exceed the daily hazmat cap of 40 gallons, or finalization fails with `ERR_HAZMAT_DAILY_CAP_EXCEEDED`."
    PRD §2.6: "The store resource also exposes `hazmat_gallons_used_today`, a computed tally of the propane gallons dispensed by all `FINALIZED` `PROPANE_EXCHANGE` weighted sales whose `finalized_at` calendar date (UTC, logical clock) equals the current logical date."

    Design: Corner/cross_cutting_complexity_layers/hazmat_daily_tally_resets_across_utc_dates
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")

    create_finalized_propane_sale(store)
    create_finalized_propane_sale(store)
    third = create_provisional_sale(
        store, sale_kind="PROPANE_EXCHANGE", container_class="CYLINDER_20",
        gross_weight_lbs=101.8,
    )

    resp = api.finalize_weighted_sale(third["id"], {"measured_tare_lbs": 17}, ASSOC)
    validate_error(resp, ApiErrorId.ERR_HAZMAT_DAILY_CAP_EXCEEDED)

    third_after = validate_success(api.get_weighted_sale(third["id"], ASSOC))
    assert third_after["status"] == "PROVISIONAL"

    # After midnight the daily tally resets; an identical sale finalizes.
    set_clock("2026-09-11T00:00:01Z")
    fourth = create_provisional_sale(
        store, sale_kind="PROPANE_EXCHANGE", container_class="CYLINDER_20",
        gross_weight_lbs=101.8,
    )
    fin = validate_success(
        api.finalize_weighted_sale(fourth["id"], {"measured_tare_lbs": 17}, ASSOC)
    )
    assert fin["status"] == "FINALIZED"

    store_now = validate_success(api.get_store(store["id"], MGR))
    assert store_now["hazmat_gallons_used_today"] == 20.0


def test_schedule_gap_ignores_different_species_and_cancelled(api):
    """PRD §3.2: "For the same store and the same `species`, the candidate's closed sale window must be separated from every other `PUBLISHED` schedule's closed window by a sanitization gap of at least 7 full days on both sides ... Schedules in `DRAFT`, `CLOSED`, or `CANCELLED` are ignored by this check."
    PRD §3.2: "A schedule still in `DRAFT` can instead be cancelled by closing it with `reason` set to `CANCELLED`, moving it `DRAFT → CANCELLED`"

    Design: Corner/cross_cutting_complexity_layers/schedule_gap_ignores_different_species_and_cancelled
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")

    chicken = create_published_schedule(
        store, species="CHICKEN_LAYER", breed="Rhode Island Red",
        sale_window_start="2026-03-01T00:00:00Z",
        sale_window_end="2026-03-31T23:59:59Z",
    )

    # A same-store chicken schedule in DRAFT that overlaps everything; cancel
    # it out of the gap-check candidate set.
    draft = validate_success(
        api.create_hatchery_schedule(
            create_hatchery_schedule_payload(
                store["id"], species="CHICKEN_MEAT", breed="Cornish Cross",
                hatch_date="2026-02-20T00:00:00Z",
                sale_window_start="2026-02-25T00:00:00Z",
                sale_window_end="2026-12-31T23:59:59Z",
                daily_capacity=100, min_purchase_qty=4,
                base_price_cents_per_bird=299,
            ),
            MGR,
        ),
        expected_status=201,
    )
    cancelled = validate_success(
        api.close_hatchery_schedule(draft["id"], {"reason": "CANCELLED"}, MGR)
    )
    assert cancelled["status"] == "CANCELLED"

    # A different species inside the chicken window publishes cleanly.
    duck = validate_success(
        api.create_hatchery_schedule(
            create_hatchery_schedule_payload(
                store["id"], species="DUCK", breed="Pekin",
                hatch_date="2026-03-05T00:00:00Z",
                sale_window_start="2026-03-10T00:00:00Z",
                sale_window_end="2026-03-20T23:59:59Z",
                daily_capacity=100, min_purchase_qty=4,
                base_price_cents_per_bird=599,
            ),
            MGR,
        ),
        expected_status=201,
    )
    published = validate_success(api.publish_hatchery_schedule(duck["id"], MGR))
    assert published["status"] == "PUBLISHED"
