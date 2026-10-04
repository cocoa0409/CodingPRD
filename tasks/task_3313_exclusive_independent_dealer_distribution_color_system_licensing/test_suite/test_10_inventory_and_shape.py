"""Reference-inactive gates, minimum inventory, dealer-status gating, request shape."""
from test_helpers import (
    CLA,
    RM,
    ApiErrorId,
    api_client,
    get_success_data,
    make_dealer_principal_headers,
    place_order,
    record_calibration,
    setup_base,
    setup_contractor,
    setup_dealer,
    setup_equipment,
    setup_license,
    setup_onboarding_dealer,
    setup_onboarded_dealer,
    validate_error,
    validate_success,
)


class TestMinimumInventory:
    def test_initial_stock_below_minimum_rejected(self, api):
        """PRD section 3.3: "A dealer order with `purpose` `INITIAL_STOCK`
        must order at least the `min_initial_inventory_units` of the colorant
        system the dealer is licensed for; an initial-stock order below that
        minimum is rejected with `ERR_MIN_INVENTORY_UNMET` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/initial_stock_minimum_39_vs_40_units
        """
        ctx = setup_base()
        dealer = setup_dealer(ctx["region"]["id"])
        get_success_data(api.begin_onboarding(dealer["id"], RM))
        equip = setup_equipment(dealer["id"], ctx["system"]["id"])
        setup_license(dealer["id"], ctx["system"]["id"])
        record_calibration(equip["id"], "PASS")
        resp = api.create_order(
            {
                "dealer_id": dealer["id"],
                "product_line_id": ctx["line"]["id"],
                "units": 39,
                "purpose": "INITIAL_STOCK",
            },
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MIN_INVENTORY_UNMET)

    def test_initial_stock_at_minimum_reaches_active(self, api):
        """PRD section 3.3: "A dealer order with `purpose` `INITIAL_STOCK`
        must order at least the `min_initial_inventory_units` of the colorant
        system the dealer is licensed for".
        PRD section 3.3: "Activation is performed by a `RegionManager` and
        requires all three gates simultaneously: at least one equipment unit
        in `CALIBRATED`, at least one license in `ACTIVE`, and
        `inventory_minimum_met` true. A successful activation moves the
        dealer from `ONBOARDING` to `ACTIVE`".

        Design: Difficulty/boundary_precision_check/initial_stock_minimum_39_vs_40_units
        """
        ctx = setup_onboarded_dealer()
        assert ctx["dealer"]["status"] == "ACTIVE"
        assert ctx["dealer"]["inventory_minimum_met"] is True


from test_helpers import RM as RM


class TestReferenceInactive:
    def test_license_on_retired_system_rejected(self, api):
        """PRD section 3.1: "Retiring a system blocks the grant of new
        licenses on it — any such attempt is rejected with
        `ERR_REFERENCE_INACTIVE` — while leaving existing licenses running
        their course."

        Design: Corner/validations/license_on_retired_system_rejected
        """
        ctx = setup_base(with_line=False)
        dealer = setup_onboarding_dealer(ctx["region"]["id"])
        validate_success(api.retire_colorant_system(ctx["system"]["id"], CLA))
        resp = api.create_license(
            {"dealer_id": dealer["id"], "colorant_system_id": ctx["system"]["id"]},
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_INACTIVE)

    def test_purchase_on_discontinued_line_rejected(self, api):
        """PRD section 3.1: "A line likewise begins `ACTIVE` and may be
        discontinued to `DISCONTINUED`, which blocks any new dealer orders or
        contractor purchases against it with `ERR_REFERENCE_INACTIVE`."

        Design: Corner/validations/purchase_on_discontinued_line_rejected
        """
        ctx = setup_onboarded_dealer()
        contractor = setup_contractor(ctx["dealer"]["id"])
        validate_success(api.discontinue_product_line(ctx["line"]["id"], CLA))
        resp = api.create_purchase(
            {
                "contractor_account_id": contractor["id"],
                "product_line_id": ctx["line"]["id"],
                "units": 1,
            },
            make_dealer_principal_headers(ctx["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_INACTIVE)


class TestDealerNotActiveGate:
    def test_coop_claim_from_onboarding_dealer_rejected(self, api):
        """PRD section 3.5: "A `DealerPrincipal` submits a claim with
        `dealer_id`, a positive `amount_cents`, a free-text `description`,
        and an `activity_date`; the dealer must be `ACTIVE`, else
        `ERR_DEALER_NOT_ACTIVE`."

        Design: Corner/validations/dealer_not_active_gate_on_claims
        """
        ctx = setup_base()
        dealer = setup_dealer(ctx["region"]["id"])
        get_success_data(api.begin_onboarding(dealer["id"], RM))
        equip = setup_equipment(dealer["id"], ctx["system"]["id"])
        setup_license(dealer["id"], ctx["system"]["id"])
        record_calibration(equip["id"], "PASS")
        resp = api.create_coop_claim(
            {
                "dealer_id": dealer["id"],
                "amount_cents": 10,
                "description": "Early flyer",
                "activity_date": "2026-08-20T00:00:00Z",
            },
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEALER_NOT_ACTIVE)

    def test_contractor_enrollment_from_onboarding_dealer_rejected(self, api):
        """PRD section 3.6: "A `DealerPrincipal` enrolls a contractor with
        `dealer_id` and `company_name`; the dealer must be `ACTIVE`, else
        `ERR_DEALER_NOT_ACTIVE`."

        Design: Corner/validations/dealer_not_active_gate_on_claims
        """
        ctx = setup_base()
        dealer = setup_dealer(ctx["region"]["id"])
        get_success_data(api.begin_onboarding(dealer["id"], RM))
        resp = api.create_contractor(
            {"dealer_id": dealer["id"], "company_name": "Ace Painting LLC"},
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEALER_NOT_ACTIVE)


class TestRequestShape:
    def test_refund_above_invoice_rejected(self, api):
        """PRD section 3.6: "Purchases are posted by a `DealerPrincipal`
        against a `contractor_account_id` and a `product_line_id`, with a
        positive `units` count and two optional amounts:
        `reward_points_redeemed` (zero or more, defaulting to 0) and
        `refund_cents` (zero or more, defaulting to 0, and never exceeding
        the purchase's `invoice_cents`)."
        PRD section 2.5: "(22) general request shape — required fields
        present, types valid, enum members valid, numeric ranges respected —
        else `ERR_INVALID_REQUEST`."

        Design: Corner/validations/refund_out_of_range_rejected
        """
        ctx = setup_onboarded_dealer()
        contractor = setup_contractor(ctx["dealer"]["id"])
        resp = api.create_purchase(
            {
                "contractor_account_id": contractor["id"],
                "product_line_id": ctx["line"]["id"],
                "units": 1,
                "refund_cents": 500,
            },
            make_dealer_principal_headers(ctx["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_zero_units_rejected(self, api):
        """PRD section 3.6: "Purchases are posted by a `DealerPrincipal`
        against a `contractor_account_id` and a `product_line_id`, with a
        positive `units` count".
        PRD section 2.5: "(22) general request shape — required fields
        present, types valid, enum members valid, numeric ranges respected —
        else `ERR_INVALID_REQUEST`."

        Design: Corner/validations/refund_out_of_range_rejected
        """
        ctx = setup_onboarded_dealer()
        contractor = setup_contractor(ctx["dealer"]["id"])
        resp = api.create_purchase(
            {
                "contractor_account_id": contractor["id"],
                "product_line_id": ctx["line"]["id"],
                "units": 0,
            },
            make_dealer_principal_headers(ctx["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
