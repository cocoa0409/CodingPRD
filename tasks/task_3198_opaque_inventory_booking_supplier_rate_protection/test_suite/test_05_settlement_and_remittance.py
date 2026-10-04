"""Settlement remittance variants and goodwill chargeback boundary tests."""
from test_helpers import (
    ADMIN,
    CS,
    FO,
    ApiErrorId,
    accept_bid,
    approve_batch,
    assert_booking_remittance_sums,
    api_client,
    booking_for_customer,
    create_batch,
    create_customer,
    create_property,
    create_rate_window,
    create_supplier,
    evaluate_bid,
    get_success_data,
    make_customer_headers,
    open_complaint,
    place_bid,
    reset_clock,
    resolve_case,
    setup_accepted_booking,
    setup_booking_with_goodwill,
    setup_inventory,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSupplierRemittanceVariants:
    def test_provisional_remittance_at_booking_creation(self):
        """PRD §3.4: "The provisional `supplier_remittance_cents` is the
        `charged_price_cents` multiplied by one minus the supplier's
        `opaque_commission_pct`, rounded down to a whole cent; the provisional
        `platform_commission_cents` is the remainder of the charged price after
        the remittance — the two always sum exactly to the charge."

        Design: Difficulty/dual_variant_calc/supplier_remittance_provisional_vs_final_on_goodwill_chargeback
        """
        supplier, prop, window, customer, bid, booking = setup_accepted_booking(
            "NB1",
            supplier_overrides={"opaque_commission_pct": 0.18},
        )
        # charged = ceil(15000*2*0.9) = 27000; provisional remittance =
        # floor(27000 * 0.82) = 22140; commission = 27000 - 22140 = 4860.
        assert booking["charged_price_cents"] == 27000
        assert booking["supplier_remittance_cents"] == 22140
        assert booking["platform_commission_cents"] == 4860
        assert_booking_remittance_sums(booking)

    def test_final_remittance_after_goodwill_chargeback_on_approve(self):
        """PRD §3.6: "a `PARTIALLY_REFUNDED` booking where the chargeback applies
        recomputes both figures on the reduced base of `charged_price_cents`
        minus `goodwill_credit_cents` — the remittance is that reduced base
        multiplied by one minus the supplier's `opaque_commission_pct`, rounded
        down to a whole cent, and the commission is the remainder of the
        reduced base; every other booking keeps its provisional values."

        Design: Difficulty/dual_variant_calc/supplier_remittance_provisional_vs_final_on_goodwill_chargeback
        """
        supplier, prop, window, customer, bid, booking, case = setup_booking_with_goodwill(
            "NB2",
            5000,
            supplier_overrides={"opaque_commission_pct": 0.18},
        )
        # ratio 5000/27000 = 0.1852 > 0.15 → chargeback applies.
        # Provisional after grant-goodwill is unchanged.
        assert booking["payment_status"] == "PARTIALLY_REFUNDED"
        assert booking["supplier_remittance_cents"] == 22140
        assert booking["platform_commission_cents"] == 4860

        batch = create_batch(supplier["id"])
        approved = approve_batch(batch)
        assert approved["goodwill_deduction_cents"] == 5000
        assert approved["net_remittance_cents"] == (
            approved["gross_remittance_cents"] - approved["goodwill_deduction_cents"]
        )

        final_booking = get_success_data(api_client.get_booking(booking["id"], ADMIN))
        # Final variant on 27000-5000=22000: floor(22000*0.82)=18040, 3960.
        assert final_booking["supplier_remittance_cents"] == 18040
        assert final_booking["platform_commission_cents"] == 3960
        assert final_booking["fulfillment_status"] == "SETTLED"
        assert final_booking["payment_status"] == "PARTIALLY_REFUNDED"


class TestGoodwillChargebackBoundary:
    def test_ratio_exactly_at_threshold_leaves_cost_with_platform(self):
        """PRD §3.6: "the supplier absorbs the goodwill if and only if that
        ratio is strictly greater than 0.15 — a ratio of exactly 0.15 leaves
        the cost with the platform."

        Design: Difficulty/combinatorial_formula/goodwill_chargeback_rounding_boundary_mode_b
        """
        # 4050/27000 == 0.15 exactly → strict > fails → no chargeback.
        supplier, prop, window, customer, bid, booking, case = setup_booking_with_goodwill(
            "NB3",
            4050,
            supplier_overrides={"opaque_commission_pct": 0.18},
        )
        batch = create_batch(supplier["id"])
        assert batch["goodwill_deduction_cents"] == 0
        assert batch["net_remittance_cents"] == batch["gross_remittance_cents"]

        approved = approve_batch(batch)
        final_booking = get_success_data(api_client.get_booking(booking["id"], ADMIN))
        # Chargeback does not apply → final equals provisional.
        assert final_booking["supplier_remittance_cents"] == 22140
        assert final_booking["platform_commission_cents"] == 4860

    def test_ratio_one_cent_above_threshold_charges_supplier(self):
        """PRD §3.6: "the supplier absorbs the goodwill if and only if that
        ratio is strictly greater than 0.15 — a ratio of exactly 0.15 leaves
        the cost with the platform."

        Design: Difficulty/combinatorial_formula/goodwill_chargeback_rounding_boundary_mode_b
        """
        # 4051/27000 = 0.1500…371 → rounds to 0.1500? No: 4051/27000 = 0.150037,
        # rounded half-up to 4 decimals = 0.1500... Let me recompute: the PRD
        # rounds the ratio to 4 decimals before comparing, so pick a goodwill
        # that clears 0.15 unambiguously: 4052/27000 = 0.15007 → 0.1501 > 0.15.
        supplier, prop, window, customer, bid, booking, case = setup_booking_with_goodwill(
            "NB4",
            4052,
            supplier_overrides={"opaque_commission_pct": 0.18},
        )
        batch = create_batch(supplier["id"])
        assert batch["goodwill_deduction_cents"] == 4052
        assert batch["net_remittance_cents"] == (
            batch["gross_remittance_cents"] - 4052
        )


class TestSettlementOverlapAndEmptyBatch:
    def test_empty_booking_ids_blocks_batch_approval(self):
        """PRD §3.6: "Approval — guarded by the optimistic-concurrency rule of
        §2.7 on the batch's `version` — moves the batch `DRAFT → APPROVED` and
        is permitted only when `booking_ids` is non-empty (an empty selection
        is rejected with `ERR_BATCH_EMPTY`, HTTP 422) and the supplier is not
        `TERMINATED`."

        Design: Difficulty/boundary_precision_check/empty_booking_ids_blocks_batch_approval
        """
        reset_clock()
        supplier = create_supplier()
        batch = create_batch(supplier["id"], "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z")
        assert batch["booking_ids"] == []

        resp = api_client.approve_settlement_batch(
            batch["id"],
            {"expected_settlement_batch_version": batch["version"]},
            FO,
        )
        validate_error(resp, ApiErrorId.ERR_BATCH_EMPTY)
        refreshed = get_success_data(api_client.get_settlement_batch(batch["id"], FO))
        assert refreshed["status"] == "DRAFT"


class TestSettlementSelectionBoundaries:
    def test_checkout_at_period_end_excluded_checkout_at_period_start_included(self):
        """PRD §3.6: "the batch gathers every booking whose `supplier_id`
        matches the batch's supplier, whose `fulfillment_status` is `CONFIRMED`,
        and whose `check_out_date` falls on or after the period start and
        strictly before the period end; sorts them by `check_out_date`
        ascending and then by booking `created_at` ascending; and records the
        sorted id list as `booking_ids`."

        Design: Corner/calculations/settlement_selection_orders_by_checkout_then_created_at
        """
        reset_clock()
        supplier = create_supplier()
        get_success_data(api_client.create_disclosure_zone(
            {"neighborhood_code": "NB28", "min_star_rating": 3,
             "revealed_amenity_codes": ["POOL"]}, ADMIN
        ))
        prop = create_property(supplier["id"], neighborhood_code="NB28")
        create_rate_window(
            prop["id"],
            check_in_date="2026-10-01T00:00:00Z",
            check_out_date="2026-11-05T00:00:00Z",
            rooms_allocated=10,
        )
        # C1 checks out 2026-10-31 (inside the October period).
        c1 = create_customer()
        b1 = place_bid(c1, neighborhood_code="NB28",
                       check_in_date="2026-10-30T00:00:00Z",
                       check_out_date="2026-10-31T00:00:00Z")
        accept_bid(b1, c1)
        booking1 = booking_for_customer(c1)

        # C2 checks out 2026-11-01 (exactly period_end → excluded).
        c2 = create_customer()
        b2 = place_bid(c2, neighborhood_code="NB28",
                       check_in_date="2026-10-31T00:00:00Z",
                       check_out_date="2026-11-01T00:00:00Z")
        accept_bid(b2, c2)
        booking2 = booking_for_customer(c2)

        batch = create_batch(supplier["id"], "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")
        assert batch["booking_ids"] == [booking1["id"]]

        # C2's booking instead lands in the November batch (inclusive start).
        batch2 = create_batch(supplier["id"], "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z")
        assert batch2["booking_ids"] == [booking2["id"]]


class TestSupplierTerminationGuard:
    def test_terminate_blocked_by_open_batch_then_succeeds_after_void(self):
        """PRD §3.1: "Termination closes the supplier's open windows in the
        same cascade and is permitted only when no `DRAFT` or `APPROVED`
        settlement batch exists for that supplier; an open batch blocks
        termination with `ERR_SUPPLIER_HAS_OPEN_BATCH` (HTTP 409)."

        Design: Corner/state_machines/supplier_terminate_blocked_by_open_batch
        """
        reset_clock()
        supplier = create_supplier()
        batch = create_batch(supplier["id"])

        resp = api_client.terminate_supplier(supplier["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_HAS_OPEN_BATCH)

        get_success_data(api_client.void_settlement_batch(batch["id"], FO))
        terminated = get_success_data(api_client.terminate_supplier(supplier["id"], ADMIN))
        assert terminated["status"] == "TERMINATED"
