"""Resource creation shape, defaults, uniqueness, pagination, and clock default."""
from test_helpers import (
    ADMIN,
    CLA,
    ET,
    RM,
    ApiErrorId,
    api_client,
    assert_region,
    create_formula_payload,
    create_product_line_payload,
    create_region_payload,
    get_success_data,
    make_dealer_principal_headers,
    place_order,
    setup_base,
    setup_dealer,
    setup_equipment,
    setup_onboarded_dealer,
    setup_region,
    setup_system,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRegionCreation:
    def test_create_region_returns_declared_fields_and_zero_counters(self, api):
        """PRD section 3.1: "Two derived counters are maintained on each
        region: `active_dealer_count`, the number of dealers in the region
        whose status is `ACTIVE` or `SUSPENDED`, and
        `pending_application_count`, the number of applications in the region
        in `SUBMITTED` status. Both start at 0".
        PRD section 2.4: "The `version` integer starts at 1 on creation and
        increments by 1 on every mutation of the resource".
        PRD section 2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/entities/create_region_returns_declared_fields_and_system_counters
        """
        resp = api.create_region(create_region_payload(), ADMIN)
        body = resp.json()
        data = validate_success(resp, expected_status=201)
        assert_region(data)
        assert data["code"] == "NE"
        assert data["version"] == 1
        assert data["active_dealer_count"] == 0
        assert data["pending_application_count"] == 0
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]
        assert body["response_type"] == "object"

    def test_region_code_unique(self, api):
        """PRD section 3.1: "Uniqueness is enforced across the catalogue: a
        region `code`, an equipment `serial_no`, a colorant system `code`, a
        product line `code`, or a formula `code` that duplicates an existing
        value in its scope is rejected with `ERR_DUPLICATE` (HTTP 409)."

        Design: Corner/entities/create_region_returns_declared_fields_and_system_counters
        """
        setup_region()
        resp = api.create_region(create_region_payload(), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE, expected_status=409)


class TestDealerDefaults:
    def test_fresh_dealer_defaults(self, api):
        """PRD section 3.2: "Creation has a side effect: the server also
        creates the applicant `Dealer` record in `APPLIED` status".
        PRD section 2.8: "Each dealer's `channel_posture` is one of
        `INDEPENDENT_ONLY`, `OVERRIDE_REQUIRED`, or `BLOCKED`, rederived from
        confirmed channel events on every event posting or supersession."
        PRD section 3.3: "The dealer's `inventory_minimum_met` flag starts
        false and flips to true when such an `INITIAL_STOCK` order reaches
        `INVOICED`".
        PRD section 3.7: "The `bigbox_share_pct` is one hundred times the
        numerator divided by the denominator, rounded half-up to two decimal
        places — and is 0 when the denominator is 0."

        Design: Corner/entities/dealer_default_channel_posture_and_zero_counters
        """
        region = setup_region()
        dealer = setup_dealer(region["id"])
        assert dealer["status"] == "APPLIED"
        assert dealer["channel_posture"] == "INDEPENDENT_ONLY"
        assert dealer["bigbox_share_pct"] == 0
        assert dealer["coop_balance_cents"] == 0
        assert dealer["inventory_minimum_met"] is False
        assert dealer["branding_compliant"] is False


class TestRequiredFields:
    def test_equipment_missing_serial_rejected(self, api):
        """PRD section 3.3: "An `EquipmentTech` installs a unit at the dealer
        by providing `dealer_id`, a `serial_no` unique across all equipment,
        a `model`, the `colorant_system_id` the unit tints for, and an
        `installed_on` date".
        PRD section 2.5: "(22) general request shape — required fields
        present, types valid, enum members valid, numeric ranges respected —
        else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_equipment_missing_serial_returns_invalid_request
        """
        ctx = setup_base(with_line=False)
        dealer = setup_dealer(ctx["region"]["id"])
        get_success_data(api.begin_onboarding(dealer["id"], RM))
        resp = api.create_equipment(
            {
                "dealer_id": dealer["id"],
                "model": "Corob D600",
                "colorant_system_id": ctx["system"]["id"],
                "installed_on": "2026-09-01T00:00:00Z",
            },
            ET,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestFormulaCodeUniqueness:
    def test_duplicate_code_in_same_line_rejected_reuse_across_lines_ok(self, api):
        """PRD section 3.1: "Color formulas are created under a product line
        with a `product_line_id`, a `code` unique within that line, a
        `display_name`, and an `effective_from` date that must not be in the
        future".
        PRD section 3.1: "Uniqueness is enforced across the catalogue: a
        region `code`, an equipment `serial_no`, a colorant system `code`, a
        product line `code`, or a formula `code` that duplicates an existing
        value in its scope is rejected with `ERR_DUPLICATE` (HTTP 409)."

        Design: Corner/entities/formula_code_unique_per_line_but_reusable_across_lines
        """
        ctx = setup_base()
        line2 = get_success_data(
            api.create_product_line(
                create_product_line_payload(ctx["system"]["id"], code="L2", name="Line Two"),
                CLA,
            )
        )
        get_success_data(
            api.create_formula(create_formula_payload(ctx["line"]["id"], code="F"), CLA)
        )
        resp = api.create_formula(
            create_formula_payload(ctx["line"]["id"], code="F", display_name="Gray Dup"), CLA,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE, expected_status=409)
        ok = validate_success(
            api.create_formula(
                create_formula_payload(line2["id"], code="F", display_name="Gray Other Line"),
                CLA,
            ),
            expected_status=201,
        )
        assert ok["code"] == "F"


class TestDuplicateSerial:
    def test_duplicate_serial_rejected_across_dealers(self, api):
        """PRD section 3.3: "An `EquipmentTech` installs a unit at the dealer
        by providing `dealer_id`, a `serial_no` unique across all equipment".
        PRD section 3.1: "Uniqueness is enforced across the catalogue: a
        region `code`, an equipment `serial_no`, a colorant system `code`, a
        product line `code`, or a formula `code` that duplicates an existing
        value in its scope is rejected with `ERR_DUPLICATE` (HTTP 409)."

        Design: Corner/validations/duplicate_serial_rejected
        """
        ctx = setup_base(with_line=False)
        dealer1 = setup_dealer(ctx["region"]["id"])
        get_success_data(api.begin_onboarding(dealer1["id"], RM))
        dealer2 = setup_dealer(
            ctx["region"]["id"], legal_name="Second Paint Co",
            latitude=43.0, longitude=-72.0,
        )
        get_success_data(api.begin_onboarding(dealer2["id"], RM))
        setup_equipment(dealer1["id"], ctx["system"]["id"])
        resp = api.create_equipment(
            {
                "dealer_id": dealer2["id"],
                "serial_no": "SN-100",
                "model": "Corob D600",
                "colorant_system_id": ctx["system"]["id"],
                "installed_on": "2026-09-01T00:00:00Z",
            },
            ET,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE, expected_status=409)


class TestPagination:
    def test_dealer_list_pagination_envelope(self, api):
        """PRD section 2.3: "The `meta` object of a list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`,
        where `total_count` is the total number of matching records and
        `has_more` indicates whether additional records exist beyond the
        returned window."
        PRD section 2.2: "The `response_type` is either "object" for a
        single resource or "array" for a list of resources."

        Design: Corner/endpoints/dealer_list_pagination_envelope
        """
        region = setup_region()
        setup_dealer(region["id"])
        setup_dealer(
            region["id"], legal_name="Second Paint Co",
            latitude=43.0, longitude=-72.0,
        )
        resp = api.list_dealers(RM, params={"limit": 1, "offset": 0})
        body = resp.json()
        data, meta = validate_paginated(resp)
        assert body["response_type"] == "array"
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        _data2, meta2 = validate_paginated(
            api.list_dealers(RM, params={"limit": 1, "offset": 1})
        )
        assert len(_data2) == 1
        assert meta2["has_more"] is False


class TestClockDefault:
    def test_formula_with_future_effective_from_rejected_at_default_clock(self, api):
        """PRD section 2.4: "Before any clock-setting call, the logical clock
        reads exactly 2026-09-01T00:00:00Z and never falls back to wall-clock
        time."
        PRD section 3.1: "Color formulas are created under a product line
        with a `product_line_id`, a `code` unique within that line, a
        `display_name`, and an `effective_from` date that must not be in the
        future, either at creation or when the formula is later replaced."

        Design: Corner/endpoints/clock_default_before_first_set
        """
        # No clock-set call: the default 2026-09-01 must be in force.
        region = setup_region()
        system = setup_system()
        line = get_success_data(
            api.create_product_line(
                create_product_line_payload(system["id"]), CLA,
            )
        )
        resp = api.create_formula(
            create_formula_payload(
                line["id"], code="FUT", display_name="Future Color",
                effective_from="2026-09-02T00:00:00Z",
            ),
            CLA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestOrderLifecycle:
    def test_new_order_starts_submitted_with_flat_pricing(self, api):
        """PRD section 3.5: "At submission the server records
        `unit_price_cents` as the line's `base_price_cents` (dealer orders
        receive no tier discount) and `invoice_cents` as `units` multiplied
        by that unit price. A new order starts `SUBMITTED`."

        Design: Corner/state_machines/initial_stock_order_creates_in_submitted
        """
        ctx = setup_base()
        dealer = setup_dealer(ctx["region"]["id"])
        get_success_data(api.begin_onboarding(dealer["id"], RM))
        order = place_order(dealer["id"], ctx["line"]["id"], units=40)
        assert order["status"] == "SUBMITTED"
        assert order["unit_price_cents"] == 100
        assert order["invoice_cents"] == 4000

    def test_double_cancel_rejected(self, api):
        """PRD section 3.5: "An order in `SUBMITTED` or `APPROVED` may be
        cancelled to `CANCELLED` by the owning `DealerPrincipal`".
        PRD section 2.5: "(5) transition validity — the target resource is in a state from which the requested transition exists, else `ERR_INVALID_STATE`".

        Design: Corner/state_machines/double_cancel_order_is_idempotency_error
        """
        ctx = setup_base()
        dealer = setup_dealer(ctx["region"]["id"])
        get_success_data(api.begin_onboarding(dealer["id"], RM))
        order = place_order(dealer["id"], ctx["line"]["id"], units=40)
        first = validate_success(
            api.cancel_order(order["id"], make_dealer_principal_headers(dealer["id"]))
        )
        assert first["status"] == "CANCELLED"
        resp = api.cancel_order(order["id"], make_dealer_principal_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
