"""Dealer-order flat pricing vs contractor tiered pricing, and purchase gates."""
from test_helpers import (
    CD,
    CLA,
    ET,
    RM,
    ApiErrorId,
    api_client,
    create_product_line_payload,
    get_success_data,
    make_dealer_principal_headers,
    place_order,
    post_purchase,
    record_calibration,
    set_clock,
    setup_base,
    setup_contractor,
    setup_dealer,
    setup_effective_change,
    setup_equipment,
    setup_formula,
    setup_license,
    setup_onboarded_dealer,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFlatVsTieredPricing:
    def test_dealer_order_flat_vs_silver_contractor_price(self, api):
        """PRD section 3.5: "At submission the server records
        `unit_price_cents` as the line's `base_price_cents` (dealer orders
        receive no tier discount) and `invoice_cents` as `units` multiplied
        by that unit price."
        PRD section 3.6: "The discount is 0.00 for `STANDARD`, 0.05 for
        `SILVER`, 0.10 for `GOLD`, and 0.15 for `PLATINUM`."

        Design: Difficulty/dual_variant_calc/dealer_order_flat_price_vs_contractor_tiered_price
        """
        ctx = setup_onboarded_dealer(
            line_overrides={
                "code": "LX",
                "name": "Legacy Exterior",
                "channel_class": "DEALER_EXCLUSIVE",
                "base_price_cents": 1000,
            },
        )
        contractor = setup_contractor(ctx["dealer"]["id"])
        # Seed to exactly SILVER: 1000 units at flat 1000 -> 1000000 cents.
        seed = post_purchase(
            ctx["dealer"]["id"], contractor["id"], ctx["line"]["id"], units=1000,
        )
        assert seed["invoice_cents"] == 1_000_000
        # Advance past the purchase month so the seed enters the trailing
        # twelve-full-calendar-month window of PRD section 2.6.
        set_clock("2026-10-01T00:00:00Z")
        order = place_order(
            ctx["dealer"]["id"], ctx["line"]["id"], units=10, purpose="RESTOCK",
        )
        purchase = post_purchase(
            ctx["dealer"]["id"], contractor["id"], ctx["line"]["id"], units=10,
        )
        assert order["unit_price_cents"] == 1000
        assert order["invoice_cents"] == 10000
        assert purchase["tier_at_post"] == "SILVER"
        assert purchase["unit_price_cents"] == 950
        assert purchase["invoice_cents"] == 9500
        assert order["unit_price_cents"] - purchase["unit_price_cents"] == 50

    def test_restock_order_accepted_for_active_dealer(self, api):
        """PRD section 3.5: "The dealer's status must be `ONBOARDING` or
        `ACTIVE` at order placement: the initial-stock order is placed during
        onboarding, before activation is reachable, and any other dealer
        status is rejected with `ERR_DEALER_NOT_ACTIVE`. The order names a
        `product_line_id` ... a positive `units` count, and a `purpose` of
        `INITIAL_STOCK` or `RESTOCK`."

        Design: Difficulty/dual_variant_calc/dealer_order_flat_price_vs_contractor_tiered_price
        """
        ctx = setup_onboarded_dealer()
        order = place_order(
            ctx["dealer"]["id"], ctx["line"]["id"], units=10, purpose="RESTOCK",
        )
        assert order["status"] == "SUBMITTED"
        assert order["purpose"] == "RESTOCK"


class TestPurchaseGatedByLicenseState:
    def test_purchase_rejected_when_license_pending(self, api):
        """PRD section 3.6: "the dealer must hold an `ACTIVE` license
        covering the purchased line's colorant system — `PENDING`, `EXPIRED`,
        `SUSPENDED`, or `REVOKED` do not suffice — else
        `ERR_LICENSE_NOT_ACTIVE`".

        Design: Difficulty/cross_entity_state_dependency/purchase_gated_by_license_and_equipment_states
        """
        ctx = setup_onboarded_dealer()
        # Second system + line; unit installed but never calibrated, so the
        # second license stays PENDING (PRD 3.3: a license becomes ACTIVE
        # only via a PASS calibration on a matching unit).
        system2 = get_success_data(
            api_client.create_colorant_system(
                {
                    "code": "G26",
                    "name": "Gen-26 Colorant System",
                    "generation": 26,
                    "annual_license_fee_cents": 3_000_000,
                    "min_initial_inventory_units": 20,
                },
                CLA,
            )
        )
        line2 = get_success_data(
            api_client.create_product_line(
                create_product_line_payload(system2["id"], code="S2", name="Specialty Two"),
                CLA,
            )
        )
        contractor = setup_contractor(ctx["dealer"]["id"])
        setup_equipment(ctx["dealer"]["id"], system2["id"], serial_no="SN-200")
        lic2 = setup_license(ctx["dealer"]["id"], system2["id"])
        assert lic2["status"] == "PENDING"
        resp = api.create_purchase(
            {
                "contractor_account_id": contractor["id"],
                "product_line_id": line2["id"],
                "units": 5,
            },
            make_dealer_principal_headers(ctx["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)

    def test_purchase_rejected_when_license_suspended_after_fail(self, api):
        """PRD section 3.6: "the dealer must hold an `ACTIVE` license
        covering the purchased line's colorant system — `PENDING`, `EXPIRED`,
        `SUSPENDED`, or `REVOKED` do not suffice — else
        `ERR_LICENSE_NOT_ACTIVE`".
        PRD section 3.3: "whenever a `FAIL` calibration or an overdue sweep
        leaves no `CALIBRATED` unit for the license's colorant system at that
        dealer, the license cascades from `ACTIVE` to `SUSPENDED`".

        Design: Difficulty/cross_entity_state_dependency/purchase_gated_by_license_and_equipment_states
        """
        ctx = setup_onboarded_dealer()
        contractor = setup_contractor(ctx["dealer"]["id"])
        record_calibration(ctx["equipment"]["id"], "FAIL")
        lic = validate_success(api.get_license(ctx["license"]["id"], RM))
        assert lic["status"] == "SUSPENDED"
        resp = api.create_purchase(
            {
                "contractor_account_id": contractor["id"],
                "product_line_id": ctx["line"]["id"],
                "units": 5,
            },
            make_dealer_principal_headers(ctx["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)


class TestPendingRematchBlocksPurchase:
    def test_purchase_rejected_while_rematch_pending(self, api):
        """PRD section 3.6: "if any formula of the purchased line has
        `rematch_pending` true under an `EFFECTIVE` formulation change while
        this dealer's rematch task for that formula is still `PENDING`, the
        purchase is refused with `ERR_REMATCH_REQUIRED` until the task is
        `DONE` (see §3.8)."

        Design: Corner/validations/purchase_pending_rematch_blocked
        """
        ctx = setup_onboarded_dealer()
        setup_formula(ctx["line"]["id"])
        contractor = setup_contractor(ctx["dealer"]["id"])
        _change, tasks_resp = setup_effective_change(ctx)
        tasks, _meta = validate_paginated(tasks_resp)
        assert len(tasks) == 1
        resp = api.create_purchase(
            {
                "contractor_account_id": contractor["id"],
                "product_line_id": ctx["line"]["id"],
                "units": 1,
            },
            make_dealer_principal_headers(ctx["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REMATCH_REQUIRED)

    def test_purchase_succeeds_after_rematch_done(self, api):
        """PRD section 3.8: "Recall from §3.6 that a `PENDING` rematch task
        blocks contractor purchases of the affected line at that dealer with
        `ERR_REMATCH_REQUIRED`; completing the task is what reopens the
        line."

        Design: Corner/validations/purchase_pending_rematch_blocked
        """
        ctx = setup_onboarded_dealer()
        setup_formula(ctx["line"]["id"])
        contractor = setup_contractor(ctx["dealer"]["id"])
        _change, tasks_resp = setup_effective_change(ctx)
        tasks, _meta = validate_paginated(tasks_resp)
        task_id = tasks[0]["id"]
        validate_success(
            api.complete_rematch_task(task_id, make_dealer_principal_headers(ctx["dealer"]["id"]))
        )
        purchase = post_purchase(
            ctx["dealer"]["id"], contractor["id"], ctx["line"]["id"], units=1,
        )
        assert purchase["status"] == "POSTED"
