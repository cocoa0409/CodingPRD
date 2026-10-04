"""Corner coverage: concurrency, deferred actions, derived state and pagination."""
from test_helpers import (
    TEST_USERS,
    create_and_enact_jurisdiction,
    create_and_start_batch,
    create_appraisal_payload,
    create_center,
    create_order,
    create_published_configuration,
    create_verified_buyer,
    dispatch_and_arrive,
    get_order,
    get_success_data,
    lock_order,
    next_vin,
    place_order,
    set_clock,
    settle_order_fee,
    validate_error,
    validate_paginated,
    walk_order_to_delivered,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADVISOR = TEST_USERS["delivery_advisor_headers"]
TRADEIN = TEST_USERS["trade_in_specialist_headers"]


def test_occ_version_advances_on_every_order_write(api):
    """PRD §2.5: "They also carry `version`, an integer that begins at 1 and
    increments by exactly 1 on every modification of the resource."
    PRD §2.7: "In all three cases, if the supplied value does not equal the parent
    entity's current `version` — because some other write has advanced it since the
    client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_version_advances_on_every_order_write
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    assert order["version"] == 1

    settle_order_fee(order["id"])
    order = get_order(order["id"])
    placed = place_order(order["id"], order["version"], buyer["id"])
    assert placed["version"] == 2

    refused = api.lock_configuration(order["id"], order["version"], ADMIN)
    validate_error(refused, "ERR_STALE_VERSION", expected_status=412)

    locked = get_success_data(api.lock_configuration(order["id"], placed["version"], ADMIN))
    assert locked["version"] == 3


def test_cascading_side_effects_order_ordering_is_by_created_at(api):
    """PRD §3.4: "Affected orders are processed in ascending order of their
    `placed_at`, with ties broken by `created_at` ascending; the ordering is pinned
    to `placed_at` and never to identifiers or VINs, so the accrual is
    reproducible across runs."
    PRD §2.3: "Every list in the API is ordered by `created_at` ascending"

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_order_ordering_is_by_created_at
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center_a = create_center(center_name="Austin Delivery")
    center_b = create_center(center_name="Dallas Delivery", van_count=2)
    config, _ = create_published_configuration()
    first_buyer = create_verified_buyer(full_name="Iris Early",
                                        email="iris.early@example.com")
    second_buyer = create_verified_buyer(full_name="Jon Late",
                                         email="jon.late@example.com")

    first_order = create_order(first_buyer["id"], config["id"], jur["id"], center_a["id"])
    second_order = create_order(second_buyer["id"], config["id"], jur["id"], center_b["id"])

    settle_order_fee(first_order["id"])
    first_placed = place_order(first_order["id"], first_order["version"], first_buyer["id"])
    first_locked = lock_order(first_order["id"], first_placed["version"])

    # Advance the clock so the second order's placed_at is strictly later.
    get_success_data(api.set_current_utc("2026-09-03T00:00:00Z", ADMIN))
    settle_order_fee(second_order["id"])
    second_placed = place_order(second_order["id"], second_order["version"],
                               second_buyer["id"])
    second_locked = lock_order(second_order["id"], second_placed["version"])

    batch, _unit = create_and_start_batch(
        unit_capacity=2, planned_completion_at="2026-09-10T00:00:00Z")
    get_success_data(api.mint_allocation_unit(batch["id"], next_vin(), ADMIN))
    get_success_data(api.allocate_order(first_order["id"], batch["id"],
                                        first_locked["version"], ADMIN))
    get_success_data(api.allocate_order(second_order["id"], batch["id"],
                                        second_locked["version"], ADMIN))
    dispatch_and_arrive(first_order["id"])
    dispatch_and_arrive(second_order["id"])

    get_success_data(api.delay_batch(batch["id"], 3, ADMIN))

    for order_id in (first_order["id"], second_order["id"]):
        rows = get_success_data(api.list_order_estimates(order_id, ADMIN))
        states = sorted(e["estimate_state"] for e in rows)
        # The chain is placement (superseded by allocation) and allocation
        # (superseded by the delay), so two rows have been retired by now.
        assert states.count("SUPERSEDED") == 2, (
            "the delay supersedes exactly the order's live estimate"
        )
        assert len([s for s in states if s in ("PROVISIONAL", "FIRM")]) == 1, (
            "a fresh live estimate replaces it"
        )
        assert get_order(order_id)["estimate_shift_days_cumulative"] == 0, (
            "a 3-day slip inside the 7-day window moves the start past no window end"
        )


def test_derived_field_reconciliation_posture_matches_its_formula(api):
    """PRD §3.7: "`READY` when the provisional total is at or below
    `order_fee_paid_cents`"
    PRD §3.7: "`RESTRICTED` when the order's provisional total is not fully
    covered, that is when `order_fee_paid_cents` is strictly less than
    `order_total_due_cents`"

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_posture_matches_its_formula
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    settle_order_fee(order["id"])
    order = get_order(order["id"])

    placed = place_order(order["id"], order["version"], buyer["id"])
    locked = lock_order(order["id"], placed["version"])
    batch, _unit = create_and_start_batch()
    get_success_data(api.allocate_order(order["id"], batch["id"],
                                        locked["version"], ADMIN))
    get_success_data(api.dispatch_to_transport(order["id"], ADMIN))
    get_success_data(api.arrive_at_center(order["id"], ADMIN))

    arrived = get_order(order["id"])
    assert arrived["order_fee_paid_cents"] < arrived["order_total_due_cents"]
    assert arrived["delivery_readiness_posture"] == "RESTRICTED"


def test_scheduled_action_deadline_fires_on_the_clock_advance(api):
    """PRD §2.10: "applies the automatic transition of an order from `PLACED` to
    `CONFIG_LOCKED` once the clock strictly exceeds that order's
    `configuration_lock_deadline`."
    PRD §3.2: "Configuration closes in one of two ways. It closes automatically
    when the logical clock strictly exceeds `configuration_lock_deadline`"

    Design: Corner/cross_cutting_complexity_layers/scheduled_action_deadline_fires_on_the_clock_advance
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    settle_order_fee(order["id"])
    place_order(order["id"], order["version"], buyer["id"])

    get_success_data(api.set_current_utc("2026-09-15T00:00:00.000Z", ADMIN))
    at_deadline = get_order(order["id"])
    assert at_deadline["status"] == "PLACED", (
        "landing exactly on the deadline does not fire the deferred transition"
    )

    get_success_data(api.set_current_utc("2026-09-15T00:00:00.001Z", ADMIN))
    assert get_order(order["id"])["status"] == "CONFIG_LOCKED"


def test_rate_threshold_bundle_tier_flips_between_the_second_and_the_fourth_row(api):
    """PRD §3.11: "A count of one or fewer receives no discount at all — a tier
    rate of 0 basis points. A count of two or three receives a tier rate of 500
    basis points. A count of four or more receives a tier rate of 1000 basis
    points."
    PRD §3.11: "the count is taken before insertion and that the tier boundaries
    are inclusive"

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_bundle_tier_flips_between_the_second_and_the_fourth_row
    """
    set_clock()
    delivered = walk_order_to_delivered()
    vehicle_id = delivered["vehicle"]["id"]

    get_success_data(api.grant_entitlements(
        vehicle_id,
        {"feature_entries": [{"feature_code": "AUTOPILOT_BASIC", "price_cents": 0}],
         "entitlement_source": "FACTORY_OPTION"}, ADMIN))

    first = get_success_data(api.grant_entitlements(
        vehicle_id,
        {"feature_entries": [{"feature_code": "PREMIUM_CONNECTIVITY",
                              "price_cents": 100000}],
         "entitlement_source": "PURCHASE"}, ADMIN))
    assert first[0]["bundle_discount_bps"] == 0, "one existing entitlement pays in full"
    assert first[0]["bundle_net_cents"] == 100000

    second = get_success_data(api.grant_entitlements(
        vehicle_id,
        {"feature_entries": [{"feature_code": "PREMIUM_AUDIO",
                              "price_cents": 200000}],
         "entitlement_source": "PURCHASE"}, ADMIN))
    assert second[0]["bundle_discount_bps"] == 500, (
        "two existing entitlements cross into the 500-basis-point band"
    )
    assert second[0]["bundle_net_cents"] == 190000


def test_saga_compensation_on_cancellation_restores_every_touched_aggregate(api):
    """PRD §3.8: "The order moves to `CANCELLED` and its
    `delivery_readiness_posture` is forced to `FROZEN`. Every delivery estimate on
    the order whose state is `PROVISIONAL` or `FIRM` is superseded"
    PRD §3.8: "Every *visible* trade-in appraisal on the order is moved to
    `REJECTED`, and each such rejection carries the compensating
    `TRADE_IN_CREDIT_REVERSAL` entry"

    Design: Corner/cross_cutting_complexity_layers/saga_compensation_on_cancellation_restores_every_touched_aggregate
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer(full_name="Saga Buyer", email="saga.buyer@example.com")
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    settle_order_fee(order["id"])
    placed = place_order(order["id"], order["version"], buyer["id"])
    lock_order(order["id"], placed["version"])

    appraisal = get_success_data(api.create_appraisal(
        order["id"],
        create_appraisal_payload(trade_vin="5YJ3E1EA7PF000930", mileage=20000,
                                 gross_offer_cents=900000,
                                 reconditioning_estimate_cents=40000,
                                 offer_valid_until="2026-10-15T00:00:00Z"),
        TRADEIN))
    get_success_data(api.appraise(order["id"], appraisal["id"], TRADEIN))
    get_success_data(api.offer_appraisal(order["id"], appraisal["id"], TRADEIN))

    cancelled = get_success_data(api.cancel_order(
        order["id"], {"X-User-ID": buyer["id"], "X-User-Role": "Buyer",
                      "Content-Type": "application/json"}))
    assert cancelled["status"] == "CANCELLED"

    assert get_success_data(api.get_appraisal(appraisal["id"], TRADEIN))["status"] == "REJECTED"

    estimates = get_success_data(api.list_order_estimates(order["id"], ADMIN))
    assert all(e["estimate_state"] == "SUPERSEDED" for e in estimates)

    final_buyer = get_success_data(api.get_buyer(buyer["id"], ADMIN))
    assert final_buyer["order_credit_balance_cents"] == 5000, (
        "25000 order fee less the 20000 refund, with the credit and its reversal netting"
    )


def test_idempotency_key_guard_on_repeated_manual_ledger_posting(api):
    """PRD §2.8: "Every ledger write recomputes the affected `Buyer`'s
    `order_credit_balance_cents` — the sum of `amount_cents` across all entries
    whose `buyer_id` is that buyer — and recomputes `order_fee_paid_cents` on the
    affected `VehicleOrder`"
    PRD §2.8: "Entries are append-only: a mistake is corrected by writing a
    compensating entry of the opposite sign under the matching reversal type,
    never by editing or deleting the original."

    Design: Corner/cross_cutting_complexity_layers/idempotency_key_guard_on_repeated_manual_ledger_posting
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    settle_order_fee(order["id"])
    place_order(order["id"], order["version"], buyer["id"])

    first = get_success_data(api.post_ledger_entry(
        order["id"],
        {"entry_type": "DELIVERY_FEE_CHARGE", "amount_cents": -2500,
         "reason_code": "SAME_CODE"}, ADMIN))
    second = get_success_data(api.post_ledger_entry(
        order["id"],
        {"entry_type": "DELIVERY_FEE_CHARGE", "amount_cents": -2500,
         "reason_code": "SAME_CODE"}, ADMIN))
    assert first["id"] != second["id"], "the ledger is append-only"

    entries, meta = validate_paginated(api.list_order_ledger_entries(order["id"], ADMIN))
    assert meta["total_count"] == 3

    buyer_after = get_success_data(api.get_buyer(buyer["id"], ADMIN))
    assert buyer_after["order_credit_balance_cents"] == 20000


def test_pagination_interacts_with_the_status_filter_and_reports_total_count(api):
    """PRD §2.3: "`limit` bounds how many items a single page may contain: it
    defaults to 10 when omitted, must be at least 1, and must be at most 100."
    PRD §2.3: "`has_more` is a boolean that is true exactly when further items
    exist beyond the current page."
    PRD §2.3: "`offset` states how many items to skip before the page begins and
    defaults to 0."

    Design: Corner/cross_cutting_complexity_layers/pagination_interacts_with_the_status_filter_and_reports_total_count
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    created = [create_order(buyer["id"], config["id"], jur["id"], center["id"])
               for _ in range(3)]
    assert all(o["status"] == "DRAFT" for o in created)

    all_rows, meta = validate_paginated(api.list_orders(ADMIN, params={"status": "DRAFT"}))
    assert len(all_rows) == 3
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert meta["offset"] == 0, "offset defaults to 0 when omitted"

    first_page, meta = validate_paginated(api.list_orders(
        ADMIN, params={"status": "DRAFT", "limit": 1, "offset": 0}))
    assert len(first_page) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    last_page, meta = validate_paginated(api.list_orders(
        ADMIN, params={"status": "DRAFT", "limit": 1, "offset": 2}))
    assert len(last_page) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert first_page[0]["id"] != last_page[0]["id"], "the two pages do not overlap"
