"""Entitlement resolution, pricing formulas, and incident accounting."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_coverage_entitlement,
    book_appointment,
    complete_accidental_repair_with_plan,
    create_coverage_plan,
    create_entitlement,
    get_coverage_plan,
    get_repair_order,
    make_customer_headers,
    make_customer_service_headers,
    make_technician_headers,
    open_accidental_repair_with_entitlement,
    open_repair_order,
    resolve_entitlement,
    set_clock,
    setup_customer_and_device,
    setup_network,
    setup_ready_for_pickup_order,
    setup_repair_order,
    validate_error,
    walk_to_ready_for_pickup,
    validate_success,
    walk_to_completed,
)


class TestProvisionalVsFinalPrice:
    def test_out_of_warranty_provisional_vs_final_price(self, api):
        """PRD §3.4: "The new repair order opens in `TRIAGED` with
        `current_location_id` equal to its `origin_location_id`,
        `repeat_repair_count` at zero, and a provisional `quoted_price_cents`
        computed from the issue category's base price alone — the provisional
        quote deliberately omits the age surcharge and model multiplier until
        entitlement resolution (§3.6)."
        PRD §3.6: "The **final quote**, applied when the entitlement resolves to
        `NOT_ENTITLED` or `PARTIALLY_ENTITLED` (and whenever a repair proceeds
        with no active coverage), uses the full out-of-warranty formula: start
        from the same base price; if the device is more than two years old —
        measured from `purchase_date` to the current logical time, with a year
        counted as 365.25 days — add an age surcharge equal to 15 percent of the
        base price; then, if the `model_code` is one of the premium models
        IPHONE_15_PRO, IPHONE_15_PRO_MAX, or MACBOOK_PRO_16, multiply the sum of
        base price and any age surcharge by 1.25 (otherwise by exactly one). The
        result is rounded half up to whole cents."
        PRD §3.6: "Resolving any entitlement copies its computed
        `quoted_price_cents` onto the repair order's own `quoted_price_cents`."

        Design: Difficulty/dual_variant_calc/out_of_warranty_provisional_vs_final_price
        """
        set_clock()
        # IPHONE_15_PRO purchased 2024-01-01 -> >2 years old at 2026-09-01.
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(
                device_overrides={"model_code": "IPHONE_15_PRO",
                                  "purchase_date": "2024-01-01T00:00:00Z"},
                issue_category="SCREEN_DAMAGE",
            )
        )
        assert repair_order["quoted_price_cents"] == 19900

        entitlement = create_entitlement(repair_order, technician)
        resp = api.resolve_entitlement(
            entitlement["id"], {"expected_coverage_plan_version": 1},
            make_technician_headers(technician["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["entitlement_status"] == "NOT_ENTITLED"
        # (19900 + 0.15 * 19900) * 1.25 = 28606.25 -> 28606 half-up
        assert data["quoted_price_cents"] == 28606

        order = get_repair_order(repair_order["id"])
        assert order["quoted_price_cents"] == 28606

    def test_entitled_resolution_replaces_provisional_with_service_fee(self, api):
        """PRD §3.4: "The new repair order opens in `TRIAGED` with
        `current_location_id` equal to its `origin_location_id`,
        `repeat_repair_count` at zero, and a provisional `quoted_price_cents`
        computed from the issue category's base price alone — the provisional
        quote deliberately omits the age surcharge and model multiplier until
        entitlement resolution (§3.6)."
        PRD §3.6: "On success the entitlement's `quoted_price_cents` becomes the
        plan's `service_fee_cents` when the damage is accidental, and zero
        otherwise; the repair order's `quoted_price_cents` is updated to match."

        Design: Difficulty/dual_variant_calc/out_of_warranty_provisional_vs_final_price
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(
                issue_category="SCREEN_DAMAGE", is_accidental_damage=True,
            )
        )
        # Provisional quote is the SCREEN_DAMAGE base price alone.
        assert repair_order["quoted_price_cents"] == 19900

        plan = create_coverage_plan(
            device, plan_type="APPLECARE_PLUS",
            accidental_damage_incident_limit=2, service_fee_cents=2900,
        )
        entitlement = create_entitlement(repair_order, technician, plan["id"])
        data = resolve_entitlement(entitlement, plan, technician)
        assert data["entitlement_status"] == "ENTITLED"
        assert data["quoted_price_cents"] == 2900
        order = get_repair_order(repair_order["id"])
        assert order["quoted_price_cents"] == 2900

    def test_provisional_quote_is_base_price_alone(self, api):
        """PRD §3.6: "The **provisional quote**, set when the repair order is
        created, is simply the base price for the `issue_category`: 19900 cents
        for `SCREEN_DAMAGE`, 6900 for `BATTERY`, 39900 for `WATER_DAMAGE`, 4900
        for `SOFTWARE`, and 29900 for `HARDWARE_OTHER`."

        Design: Difficulty/dual_variant_calc/out_of_warranty_provisional_vs_final_price
        """
        set_clock()
        for issue, expected in [
            ("SCREEN_DAMAGE", 19900),
            ("BATTERY", 6900),
            ("WATER_DAMAGE", 39900),
            ("SOFTWARE", 4900),
            ("HARDWARE_OTHER", 29900),
        ]:
            result = setup_repair_order(issue_category=issue)
            repair_order = result[5]
            assert repair_order["quoted_price_cents"] == expected, (
                f"{issue}: provisional quote should be the base price "
                f"{expected}, got {repair_order['quoted_price_cents']}"
            )


class TestTieredPricingInteraction:
    def test_out_of_warranty_tiered_age_and_model_interaction(self, api):
        """PRD §3.6: "The **final quote**, applied when the entitlement resolves
        to `NOT_ENTITLED` or `PARTIALLY_ENTITLED` (and whenever a repair proceeds
        with no active coverage), uses the full out-of-warranty formula: start
        from the same base price; if the device is more than two years old —
        measured from `purchase_date` to the current logical time, with a year
        counted as 365.25 days — add an age surcharge equal to 15 percent of the
        base price; then, if the `model_code` is one of the premium models
        IPHONE_15_PRO, IPHONE_15_PRO_MAX, or MACBOOK_PRO_16, multiply the sum of
        base price and any age surcharge by 1.25 (otherwise by exactly one). The
        result is rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/out_of_warranty_tiered_age_and_model_interaction
        """
        set_clock()
        expected = {
            # (19900 + 2985) * 1.25 = 28606.25 -> 28606
            ("IPHONE_15_PRO", "2024-01-01T00:00:00Z"): 28606,
            # (19900 + 0) * 1.25 = 24875
            ("IPHONE_15_PRO", "2025-06-01T00:00:00Z"): 24875,
            # (19900 + 2985) * 1.0 = 22885
            ("IPHONE_14", "2024-01-01T00:00:00Z"): 22885,
            # (19900 + 0) * 1.0 = 19900
            ("IPHONE_14", "2025-06-01T00:00:00Z"): 19900,
        }
        for (model_code, purchase_date), price in expected.items():
            customer, device, location, technician, appointment, repair_order = (
                setup_repair_order(
                    device_overrides={"model_code": model_code,
                                      "purchase_date": purchase_date},
                    issue_category="SCREEN_DAMAGE",
                )
            )
            entitlement = create_entitlement(repair_order, technician)
            resp = api.resolve_entitlement(
                entitlement["id"], {"expected_coverage_plan_version": 1},
                make_technician_headers(technician["id"]),
            )
            data = validate_success(resp, expected_status=200)
            assert data["entitlement_status"] == "NOT_ENTITLED"
            assert data["quoted_price_cents"] == price, (
                f"({model_code}, {purchase_date}): expected final quote {price}, "
                f"got {data['quoted_price_cents']}"
            )

    def test_out_of_warranty_age_exactly_two_years_gets_no_surcharge(self, api):
        """PRD §3.6: "if the device is more than two years old — measured from
        `purchase_date` to the current logical time, with a year counted as
        365.25 days — add an age surcharge equal to 15 percent of the base price"

        Design: Difficulty/combinatorial_formula/out_of_warranty_tiered_age_and_model_interaction
        """
        set_clock()
        # 2024-08-31T12:00 -> 2026-09-01T00:00 is exactly 730.5 days
        # = 2 * 365.25, i.e. exactly two years, not MORE than two years,
        # so no age surcharge applies.
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(
                device_overrides={"model_code": "IPHONE_14",
                                  "purchase_date": "2024-08-31T12:00:00Z"},
                issue_category="SCREEN_DAMAGE",
            )
        )
        entitlement = create_entitlement(repair_order, technician)
        resp = api.resolve_entitlement(
            entitlement["id"], {"expected_coverage_plan_version": 1},
            make_technician_headers(technician["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["entitlement_status"] == "NOT_ENTITLED"
        assert data["quoted_price_cents"] == 19900


class TestSimpleCalculationResults:
    def test_out_of_warranty_price_screen_damage_base(self, api):
        """PRD §3.6: "The **provisional quote**, set when the repair order is
        created, is simply the base price for the `issue_category`: 19900 cents
        for `SCREEN_DAMAGE`, 6900 for `BATTERY`, 39900 for `WATER_DAMAGE`, 4900
        for `SOFTWARE`, and 29900 for `HARDWARE_OTHER`."
        PRD §3.6: "**No entitlement** to `NOT_ENTITLED` applies when the plan is
        not `ACTIVE` or the proof-of-purchase requirement is unmet; the
        `quoted_price_cents` is again the full out-of-warranty final quote."

        Design: Corner/calculations/out_of_warranty_price_screen_damage_base
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(
                device_overrides={"model_code": "IPHONE_14",
                                  "purchase_date": "2025-06-01T00:00:00Z"},
                issue_category="SCREEN_DAMAGE",
            )
        )
        entitlement = create_entitlement(repair_order, technician)
        resp = api.resolve_entitlement(
            entitlement["id"], {"expected_coverage_plan_version": 1},
            make_technician_headers(technician["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["entitlement_status"] == "NOT_ENTITLED"
        assert data["quoted_price_cents"] == 19900
        order = get_repair_order(repair_order["id"])
        assert order["quoted_price_cents"] == 19900

    def test_entitlement_price_zero_for_non_accidental_under_warranty(self, api):
        """PRD §3.6: "On success the entitlement's `quoted_price_cents` becomes
        the plan's `service_fee_cents` when the damage is accidental, and zero
        otherwise; the repair order's `quoted_price_cents` is updated to match."

        Design: Corner/calculations/entitlement_price_zero_for_non_accidental_under_warranty
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(
                device_overrides={"purchase_date": "2025-06-01T00:00:00Z"},
                issue_category="SOFTWARE", is_accidental_damage=False,
            )
        )
        plan = create_coverage_plan(
            device, plan_type="LIMITED_WARRANTY",
            starts_on="2025-06-01T00:00:00Z", expires_on="2026-12-01T00:00:00Z",
            accidental_damage_incident_limit=0, service_fee_cents=0,
        )
        entitlement = create_entitlement(repair_order, technician, plan["id"])
        data = resolve_entitlement(entitlement, plan, technician)
        assert data["entitlement_status"] == "ENTITLED"
        assert data["quoted_price_cents"] == 0
        assert_coverage_entitlement(data)


class TestIncidentThreshold:
    def test_entitlement_price_threshold_rounding(self, api):
        """PRD §3.6: "**Full entitlement** to `ENTITLED` requires the plan's
        `coverage_status` to be `ACTIVE`, the proof-of-purchase condition
        satisfied (either the device's `proof_of_purchase_on_file` is true or
        `requires_proof_of_purchase` is false), and — for accidental damage —
        `accidental_damage_incidents_used` strictly below
        `accidental_damage_incident_limit`."
        PRD §3.7: "if the entitlement stands at `ENTITLED`, the damage is
        accidental, and `incident_counted` is still false, the plan's
        `accidental_damage_incidents_used` increments by one and
        `incident_counted` becomes true — exactly one incident per repair, never
        double-counted."

        Design: Difficulty/combinatorial_formula/entitlement_price_threshold_rounding
        """
        set_clock()
        customer, device = setup_customer_and_device()
        location, technician = setup_network()
        plan = create_coverage_plan(
            device, plan_type="APPLECARE_PLUS",
            accidental_damage_incident_limit=2, service_fee_cents=2900,
        )

        # First accidental repair: resolved ENTITLED, price = service fee.
        ro1, ent1 = open_accidental_repair_with_entitlement(
            customer, device, location, technician, plan,
            "2026-09-02T10:00:00Z", "2026-09-02T10:30:00Z", seed_parts=True)
        resolved1 = resolve_entitlement(ent1, plan, technician)
        assert resolved1["entitlement_status"] == "ENTITLED"
        assert resolved1["quoted_price_cents"] == 2900
        walk_to_completed(ro1, device, technician, customer)
        assert get_coverage_plan(plan["id"])["accidental_damage_incidents_used"] == 1

        # Second accidental repair: 1 < 2, still ENTITLED at the service fee.
        ro2, ent2 = open_accidental_repair_with_entitlement(
            customer, device, location, technician, plan,
            "2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z")
        resolved2 = resolve_entitlement(ent2, plan, technician)
        assert resolved2["entitlement_status"] == "ENTITLED"
        assert resolved2["quoted_price_cents"] == 2900
        walk_to_completed(ro2, device, technician, customer)
        assert get_coverage_plan(plan["id"])["accidental_damage_incidents_used"] == 2

    def test_entitlement_resolve_with_stale_plan_version_rejected(self, api):
        """PRD §2.5: "Resolving a coverage entitlement requires
        `expected_coverage_plan_version`, matched against the referenced
        `CoveragePlan`'s current `version`. A mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing resolution against a plan
        whose incident count or expiration has changed since the client last
        read it."

        Design: Difficulty/combinatorial_formula/entitlement_price_threshold_rounding
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(issue_category="SCREEN_DAMAGE",
                               is_accidental_damage=True)
        )
        plan = create_coverage_plan(
            device, plan_type="APPLECARE_PLUS",
            accidental_damage_incident_limit=2, service_fee_cents=2900,
        )
        entitlement = create_entitlement(repair_order, technician, plan["id"])
        # The client captured the plan version before creating the entitlement;
        # any later plan mutation (e.g. a cancel reverted, or an incident
        # counted by another repair's completion) would advance it. Re-read to
        # get the live version, then submit a stale one.
        live_version = get_coverage_plan(plan["id"])["version"]
        resp = api.resolve_entitlement(
            entitlement["id"],
            {"expected_coverage_plan_version": live_version + 1},
            make_technician_headers(technician["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value,
                       expected_status=412)

    def test_coverage_incident_limit_exact_boundary(self, api):
        """PRD §3.6: "**Full entitlement** to `ENTITLED` requires the plan's
        `coverage_status` to be `ACTIVE`, the proof-of-purchase condition
        satisfied (either the device's `proof_of_purchase_on_file` is true or
        `requires_proof_of_purchase` is false), and — for accidental damage —
        `accidental_damage_incidents_used` strictly below
        `accidental_damage_incident_limit`."
        PRD §3.6: "**Partial entitlement** to `PARTIALLY_ENTITLED` covers the
        exhausted-incidents case: the plan is `ACTIVE` and proof requirements
        are met, but `accidental_damage_incidents_used` has already reached
        `accidental_damage_incident_limit`. The `quoted_price_cents` falls back
        to the full out-of-warranty final quote, and no incident is consumed."

        Design: Difficulty/boundary_precision_check/coverage_incident_limit_exact_boundary
        """
        set_clock()
        customer, device = setup_customer_and_device()
        location, technician = setup_network()
        plan = create_coverage_plan(
            device, plan_type="APPLECARE_PLUS",
            accidental_damage_incident_limit=2, service_fee_cents=2900,
        )

        # Two full repairs consume both incidents (used == 2 == limit).
        complete_accidental_repair_with_plan(
            customer, device, location, technician, plan,
            "2026-09-02T10:00:00Z", "2026-09-02T10:30:00Z")
        complete_accidental_repair_with_plan(
            customer, device, location, technician, plan,
            "2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z")
        assert get_coverage_plan(plan["id"])["accidental_damage_incidents_used"] == 2

        # Third accidental repair at the exact boundary resolves
        # PARTIALLY_ENTITLED at the full out-of-warranty quote (19900: <2y
        # standard model with SCREEN_DAMAGE), and consumes no further incident.
        ro3, ent3 = open_accidental_repair_with_entitlement(
            customer, device, location, technician, plan,
            "2026-09-04T10:00:00Z", "2026-09-04T10:30:00Z")
        fresh_plan = get_coverage_plan(plan["id"])
        resp = api.resolve_entitlement_partial(
            ent3["id"], {"expected_coverage_plan_version": fresh_plan["version"]},
            make_technician_headers(technician["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["entitlement_status"] == "PARTIALLY_ENTITLED"
        assert data["quoted_price_cents"] == 19900
        assert get_coverage_plan(plan["id"])["accidental_damage_incidents_used"] == 2

    def test_resolve_full_entitlement_rejected_when_incidents_exhausted(self, api):
        """PRD §3.6: "**Full entitlement** to `ENTITLED` requires the plan's
        `coverage_status` to be `ACTIVE`, the proof-of-purchase condition
        satisfied (either the device's `proof_of_purchase_on_file` is true or
        `requires_proof_of_purchase` is false), and — for accidental damage —
        `accidental_damage_incidents_used` strictly below
        `accidental_damage_incident_limit`. If the plan is inactive or has no
        incidents remaining, the resolve is rejected with
        `ERR_COVERAGE_EXHAUSTED` (HTTP 422) rather than silently downgraded."

        Design: Difficulty/boundary_precision_check/coverage_incident_limit_exact_boundary
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(issue_category="SCREEN_DAMAGE",
                               is_accidental_damage=True)
        )
        # limit 0: no incidents remain from the start.
        plan = create_coverage_plan(
            device, plan_type="APPLECARE_PLUS",
            accidental_damage_incident_limit=0, service_fee_cents=2900,
        )
        entitlement = create_entitlement(repair_order, technician, plan["id"])
        fresh_plan = get_coverage_plan(plan["id"])
        resp = api.resolve_entitlement(
            entitlement["id"],
            {"expected_coverage_plan_version": fresh_plan["version"]},
            make_technician_headers(technician["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COVERAGE_EXHAUSTED.value,
                       expected_status=422)


class TestWaiveAndResolutionErrors:
    def test_coverage_entitlement_waive_sets_price_to_zero(self, api):
        """PRD §3.6: "Separately, a `CustomerService` agent — and only
        `CustomerService`; any other role receives `ERR_UNAUTHORIZED` — may waive
        the entitlement, moving it to `WAIVED` and setting both the
        entitlement's and the repair order's `quoted_price_cents` to zero as a
        courtesy."

        Design: Corner/endpoints/coverage_entitlement_waive_sets_price_to_zero
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order()
        )
        entitlement = create_entitlement(repair_order, technician)
        resp = api.waive_entitlement(
            entitlement["id"], make_customer_service_headers())
        data = validate_success(resp, expected_status=200)
        assert data["entitlement_status"] == "WAIVED"
        assert data["quoted_price_cents"] == 0
        order = get_repair_order(repair_order["id"])
        assert order["quoted_price_cents"] == 0

    def test_waived_order_completion_consumes_no_incident(self, api):
        """PRD §3.6: "Separately, a `CustomerService` agent — and only
        `CustomerService`; any other role receives `ERR_UNAUTHORIZED` — may waive
        the entitlement, moving it to `WAIVED` and setting both the
        entitlement's and the repair order's `quoted_price_cents` to zero as a
        courtesy."
        PRD §3.7: "if the entitlement stands at `ENTITLED`, the damage is
        accidental, and `incident_counted` is still false, the plan's
        `accidental_damage_incidents_used` increments by one and
        `incident_counted` becomes true — exactly one incident per repair, never
        double-counted."

        Design: Difficulty/compensating_invariant/coverage_incident_count_conservation_on_waive
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(issue_category="SCREEN_DAMAGE",
                               is_accidental_damage=True, seed_parts=True)
        )
        plan = create_coverage_plan(
            device, plan_type="APPLECARE_PLUS",
            accidental_damage_incident_limit=2, service_fee_cents=2900,
        )
        entitlement = create_entitlement(repair_order, technician, plan["id"])
        resp = api.waive_entitlement(
            entitlement["id"], make_customer_service_headers())
        waived = validate_success(resp, expected_status=200)
        assert waived["entitlement_status"] == "WAIVED"

        walk_to_ready_for_pickup(repair_order, device, technician)
        resp = api.complete_pickup(
            repair_order["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["repair_status"] == "COMPLETED"

        # A WAIVED entitlement is not ENTITLED, so completion consumes nothing.
        assert get_coverage_plan(plan["id"])["accidental_damage_incidents_used"] == 0

    def test_technician_cannot_waive_coverage(self, api):
        """PRD §3.6: "Separately, a `CustomerService` agent — and only
        `CustomerService`; any other role receives `ERR_UNAUTHORIZED` — may waive
        the entitlement, moving it to `WAIVED` and setting both the
        entitlement's and the repair order's `quoted_price_cents` to zero as a
        courtesy."

        Design: Corner/rbac/technician_cannot_waive_coverage
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order()
        )
        entitlement = create_entitlement(repair_order, technician)
        resp = api.waive_entitlement(
            entitlement["id"], make_technician_headers(technician["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    def test_state_vs_business_fiscal_on_entitlement_resolve(self, api):
        """PRD §3.6: "**Full entitlement** to `ENTITLED` requires the plan's
        `coverage_status` to be `ACTIVE` ... If the plan is inactive or has no
        incidents remaining, the resolve is rejected with
        `ERR_COVERAGE_EXHAUSTED` (HTTP 422) rather than silently downgraded."

        A CANCELLED plan is inactive, so resolving a full entitlement against
        it is rejected with ERR_COVERAGE_EXHAUSTED (422); the entitlement's own
        PENDING_VERIFICATION state is valid for the transition, so
        ERR_INVALID_STATE must NOT surface.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_entitlement_resolve
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(issue_category="SCREEN_DAMAGE",
                               is_accidental_damage=True)
        )
        plan = create_coverage_plan(
            device, plan_type="APPLECARE_PLUS",
            accidental_damage_incident_limit=0, service_fee_cents=2900,
        )
        # Cancel the plan: it is no longer ACTIVE, so coverage eligibility
        # fails and the resolve is rejected with ERR_COVERAGE_EXHAUSTED.
        resp = api.cancel_coverage_plan(plan["id"], make_customer_service_headers())
        validate_success(resp, expected_status=200)

        entitlement = create_entitlement(repair_order, technician, plan["id"])
        resp = api.resolve_entitlement(
            entitlement["id"], {"expected_coverage_plan_version": plan["version"]},
            make_technician_headers(technician["id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_COVERAGE_EXHAUSTED.value,
                             expected_status=422)
        assert err["error_id"] != ApiErrorId.ERR_INVALID_STATE.value

    def test_resolve_on_already_resolved_entitlement_returns_invalid_state(self, api):
        """PRD §3.6: "Resolution requires `expected_coverage_plan_version` and
        comes in three forms, all evaluated only from `PENDING_VERIFICATION`:"
        PRD §2.6: "When several validations could reject the same request, they
        are evaluated in a fixed priority order, and the earliest failing check
        determines the response. The order is: first authentication (missing
        headers, `ERR_UNAUTHENTICATED`); second authorization (role not
        permitted, `ERR_UNAUTHORIZED`); third existence of path-parameter
        entities, validated left to right along the URL (`ERR_NOT_FOUND` or the
        entity-specific not-found code); fourth state validity for the requested
        transition (`ERR_INVALID_STATE`); then the domain checks in this
        sequence — ... coverage eligibility (`ERR_COVERAGE_EXHAUSTED`), ..."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_entitlement_resolve
        """
        set_clock()
        customer, device, location, technician, appointment, repair_order = (
            setup_repair_order(issue_category="SCREEN_DAMAGE",
                               is_accidental_damage=True)
        )
        plan = create_coverage_plan(
            device, plan_type="APPLECARE_PLUS",
            accidental_damage_incident_limit=2, service_fee_cents=2900,
        )
        entitlement = create_entitlement(repair_order, technician, plan["id"])
        resolved = resolve_entitlement(entitlement, plan, technician)
        assert resolved["entitlement_status"] == "ENTITLED"

        # The entitlement is no longer PENDING_VERIFICATION, so a second resolve
        # is state-invalid even though coverage itself still has headroom.
        resp = api.resolve_entitlement(
            entitlement["id"],
            {"expected_coverage_plan_version":
             get_coverage_plan(plan["id"])["version"]},
            make_technician_headers(technician["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value,
                       expected_status=409)
