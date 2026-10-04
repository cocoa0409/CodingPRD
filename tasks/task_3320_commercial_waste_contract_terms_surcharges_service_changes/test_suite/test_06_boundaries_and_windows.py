"""Boundary and window tests: credit filing window, roll-off overage,
surcharge-config instant uniqueness, notice filing gates, OCC staleness."""
from test_helpers import (
    ApiErrorId,
    set_clock,
    make_customer,
    make_contract,
    add_service_line,
    activate_contract,
    make_fixed_config,
    make_pickup_event,
    make_service_credit,
    make_rate_notice,
    make_service_change,
    approve_service_change,
    make_rolloff_order,
    get_customer_balance,
    get_contract_version,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS, make_customer_headers

OPS = TEST_USERS["ops_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
HAULER = TEST_USERS["hauler_agent_headers"]


class TestCreditFilingWindowBoundary:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        make_fixed_config(
            effective_from="2026-09-01T00:00:00Z",
            admin_pct=0.05, credit_pct_of_base=0.05,
        )
        customer = make_customer(legal_name="Window Co", billing_email="w@x.example")
        contract = make_contract(customer["id"], term_months=12)
        line = add_service_line(
            contract["id"], container_size="CY_4",
            frequency_per_week=5, base_rate_cents=600000,
        )
        activate_contract(contract["id"])
        set_clock("2026-09-02T12:00:00Z")
        ev_a = make_pickup_event(line["id"], "2026-09-02", "MISSED")
        ev_b = make_pickup_event(line["id"], "2026-09-02", "MISSED")
        return customer, line, ev_a, ev_b

    def test_filing_on_day_14_succeeds_day_15_rejected(self, api):
        """PRD section 3.6: "the filing is accepted only while `filed_at` is on
        or before the event's `occurred_date` plus 14 days; filing after that
        14-day window is rejected with `ERR_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/credit_filing_window_day14_vs_day15
        """
        customer, line, ev_a, ev_b = self._setup()
        cust_headers = make_customer_headers(customer["id"])

        # occurred 2026-09-02 + 14 days = 2026-09-16 inclusive.
        set_clock("2026-09-16T00:00:00Z")
        credit = validate_success(
            api.create_service_credit(
                {"service_line_id": line["id"], "pickup_event_id": ev_a["id"]},
                cust_headers,
            ),
            expected_status=201,
        )
        assert credit["credit_cents"] == 30000
        assert credit["status"] == "ACTIVE"

        # Day 15: outside the window.
        set_clock("2026-09-17T00:00:00Z")
        resp = api.create_service_credit(
            {"service_line_id": line["id"], "pickup_event_id": ev_b["id"]},
            cust_headers,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_EXPIRED)

    def test_only_timely_credit_counts_toward_balance(self, api):
        """PRD section 2.7: "it equals the sum of `credit_cents` over every
        service credit in `ACTIVE` status whose service line belongs to a
        contract of this customer".

        Design: Difficulty/boundary_precision_check/credit_filing_window_day14_vs_day15
        """
        customer, line, ev_a, ev_b = self._setup()
        cust_headers = make_customer_headers(customer["id"])
        set_clock("2026-09-16T00:00:00Z")
        validate_success(
            api.create_service_credit(
                {"service_line_id": line["id"], "pickup_event_id": ev_a["id"]},
                cust_headers,
            ),
            expected_status=201,
        )
        set_clock("2026-09-17T00:00:00Z")
        resp = api.create_service_credit(
            {"service_line_id": line["id"], "pickup_event_id": ev_b["id"]},
            cust_headers,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_EXPIRED)
        assert get_customer_balance(customer["id"]) == 30000, (
            "only the in-window credit may move the balance"
        )


class TestRolloffOverageBoundary:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Roll Co", billing_email="ro@x.example")
        order_a = make_rolloff_order(
            customer["id"], delivery_date="2026-09-01T00:00:00Z",
            container_size="YD_20", rental_days=5, included_tons=2.0,
            delivery_fee_cents=10000, daily_rental_cents=1000,
            overage_ton_cents=8000,
        )
        order_b = make_rolloff_order(
            customer["id"], delivery_date="2026-09-01T00:00:00Z",
            container_size="YD_20", rental_days=5, included_tons=2.0,
            delivery_fee_cents=10000, daily_rental_cents=1000,
            overage_ton_cents=8000,
        )
        validate_success(api_client.deliver_rolloff_order(order_a["id"], OPS))
        validate_success(api_client.deliver_rolloff_order(order_b["id"], OPS))
        return customer, order_a, order_b

    def test_exactly_included_tons_yields_zero_overage(self, api):
        """PRD section 3.10: "the billable overage is the greater of 0 and the
        difference `actual_tons` minus `included_tons` rounded up to a whole
        ton — an `actual_tons` exactly equal to `included_tons` yields zero
        overage, overage is charged strictly above the included allowance".

        Design: Difficulty/boundary_precision_check/rolloff_overage_at_exactly_included_tons
        """
        customer, order_a, order_b = self._setup()
        completed = validate_success(
            api.complete_rolloff_order(order_a["id"], {"actual_tons": 2.0}, OPS)
        )
        assert completed["status"] == "COMPLETED"
        assert completed["total_cents"] == 15000, (
            "10000 delivery + 5*1000 rental + 0 overage must give 15000, "
            f"got {completed['total_cents']}"
        )

    def test_fractional_excess_rounds_up_to_whole_ton(self, api):
        """PRD section 3.10: "any fractional excess rounds up via ceiling
        rather than half-up rounding".

        Design: Difficulty/boundary_precision_check/rolloff_overage_at_exactly_included_tons
        """
        customer, order_a, order_b = self._setup()
        completed = validate_success(
            api.complete_rolloff_order(order_b["id"], {"actual_tons": 2.1}, OPS)
        )
        # ceil(2.1 - 2.0) = 1 ton * 8000 = 8000 overage.
        assert completed["total_cents"] == 23000, (
            "10000 delivery + 5*1000 rental + 1*8000 overage must give 23000, "
            f"got {completed['total_cents']}"
        )


class TestSurchargeConfigInstantUniqueness:
    def test_duplicate_effective_from_rejected_adjacent_second_accepted(self, api):
        """PRD section 2.9: "No two surcharge configurations may share the same
        `effective_from`; an attempt to create one with a colliding timestamp
        is rejected with `ERR_DUPLICATE_PENDING` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/surcharge_config_duplicate_effective_from_instant
        """
        set_clock("2026-09-01T00:00:00Z")
        make_fixed_config(
            effective_from="2026-09-01T00:00:00Z", fuel_fixed_pct=0.10,
        )
        dup = api.create_surcharge_config(
            {
                "fuel_mode": "FIXED",
                "fuel_fixed_pct": 0.11,
                "environmental_pct": 0.10,
                "admin_pct": 0.05,
                "contamination_fee_cents": 15000,
                "overweight_fee_cents": 20000,
                "effective_from": "2026-09-01T00:00:00Z",
            },
            ADMIN,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_PENDING)
        ok = api.create_surcharge_config(
            {
                "fuel_mode": "FIXED",
                "fuel_fixed_pct": 0.11,
                "environmental_pct": 0.10,
                "admin_pct": 0.05,
                "contamination_fee_cents": 15000,
                "overweight_fee_cents": 20000,
                "effective_from": "2026-09-01T00:00:01Z",
            },
            ADMIN,
        )
        assert ok.status_code == 201, f"one-second-later config must be accepted: {ok.text}"

    def test_active_window_uses_latest_effective_from_at_or_before_now(self, api):
        """PRD section 2.9: "The active configuration at any moment T is the
        one with the latest `effective_from` that is on or before T."

        Design: Difficulty/resource_temporal_overlap/surcharge_config_duplicate_effective_from_instant
        """
        set_clock("2026-09-01T00:00:00Z")
        make_fixed_config(
            effective_from="2026-09-01T00:00:00Z", contamination_fee_cents=15000,
        )
        make_fixed_config(
            effective_from="2026-09-01T00:00:01Z", contamination_fee_cents=17000,
        )
        customer = make_customer(legal_name="WinCfg Co", billing_email="wc@x.example")
        contract = make_contract(customer["id"], term_months=12)
        line = add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])
        set_clock("2026-09-02T12:00:00Z")
        event = make_pickup_event(
            line["id"], "2026-09-02", "CONTAMINATED",
            photo_evidence_url="https://img.example/c.jpg",
        )
        assert event["contamination_fee_cents"] == 17000


class TestRateNoticeFilingGates:
    def test_effective_date_equal_to_now_rejected(self, api):
        """PRD section 3.3: "The `effective_date` must lie strictly after the
        logical clock at filing time; a date at or before now is rejected with
        `ERR_WINDOW_EXPIRED`."

        Design: Corner/validations/rate_notice_effective_date_not_future
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Rn Co", billing_email="rn2@x.example")
        contract = make_contract(customer["id"], term_months=12)
        add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])
        resp = api.create_rate_notice(
            {
                "contract_id": contract["id"],
                "reason": "CPI",
                "pct_increase": 0.05,
                "effective_date": "2026-09-01T00:00:00Z",
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_EXPIRED)

    def test_zero_pct_increase_rejected(self, api):
        """PRD section 3.3: "a fractional `pct_increase` (for example 0.05
        means a 5 percent increase; it must be strictly greater than 0, and a
        non-positive value is rejected with `ERR_INVALID_AMOUNT`)".

        Design: Corner/validations/rate_notice_zero_pct_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Zero Co", billing_email="z@x.example")
        contract = make_contract(customer["id"], term_months=12)
        add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])
        resp = api.create_rate_notice(
            {
                "contract_id": contract["id"],
                "reason": "CPI",
                "pct_increase": 0,
                "effective_date": "2026-09-10T00:00:00Z",
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT)


class TestLedgerEntryImmutability:
    def test_rate_notice_application_writes_append_only_entry(self, api):
        """PRD section 3.3: "a `LedgerEntry` with `source` equal to
        `RATE_NOTICE` is written capturing the change".
        PRD section 2.5: "Ledger entries are the exception: a `LedgerEntry` is
        immutable once written and carries only `id` and `created_at`; it has
        no `updated_at` and no `version`."

        Design: Corner/entities/pickup_event_immutable_no_version_field
        """
        from prd_bench_local_runner.testing import validate_paginated

        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Led Co", billing_email="l@x.example")
        contract = make_contract(customer["id"], term_months=12)
        add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])
        make_rate_notice(
            contract["id"], pct_increase=0.05,
            effective_date="2026-09-10T00:00:00Z",
        )
        set_clock("2026-09-12T00:00:00Z")
        rows, _meta = validate_paginated(
            api.list_contract_ledger_entries(contract["id"], OPS)
        )
        assert len(rows) == 1
        entry = rows[0]
        assert entry["source"] == "RATE_NOTICE"
        assert entry["old_base_monthly_cents"] == 100000
        assert entry["new_base_monthly_cents"] == 105000
        assert "version" not in entry
        assert "updated_at" not in entry


class TestStaleVersionOnServiceChangeApply:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        customer = make_customer(legal_name="Occ3 Co", billing_email="o3@x.example")
        contract = make_contract(customer["id"], term_months=12)
        line = add_service_line(
            contract["id"], container_size="CY_4",
            frequency_per_week=4, base_rate_cents=400000,
        )
        activate_contract(contract["id"])
        change = make_service_change(
            customer["id"], line["id"],
            new_container_size="CY_4", new_frequency_per_week=5,
            effective_date="2026-09-05T00:00:00Z",
        )
        approve_service_change(change["id"])
        make_rate_notice(
            contract["id"], pct_increase=0.05,
            effective_date="2026-09-03T00:00:00Z",
        )
        version_pre = get_contract_version(contract["id"])
        # Notice applies and the change's effective_date passes; version bumps.
        set_clock("2026-09-06T00:00:00Z")
        return customer, contract, line, change, version_pre

    def test_stale_apply_rejected_then_fresh_version_succeeds(self, api):
        """PRD section 3.4: "The request must carry `expected_contract_version`
        matching the contract's current `version`; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412) per section 2.8, because a rate-notice
        application or a right-of-first-refusal match in between changes the
        base rate the final price is computed from, so the price must be
        re-observed before applying."

        Design: Corner/cross_cutting_layers/stale_version_on_service_change_apply
        """
        customer, contract, line, change, version_pre = self._setup()
        stale = api.apply_service_change(
            change["id"], {"expected_contract_version": version_pre}, OPS
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        version_post = get_contract_version(contract["id"])
        applied = validate_success(
            api.apply_service_change(
                change["id"], {"expected_contract_version": version_post}, OPS
            )
        )
        assert applied["status"] == "APPLIED"
        assert applied["final_applied_rate_cents"] == 577500
        line_after = validate_success(api.get_service_line(line["id"], OPS))
        assert line_after["base_rate_cents"] == 577500

    def test_stale_apply_leaves_request_approved(self, api):
        """PRD section 2.8: "the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), forcing the client to re-observe the contract's pricing
        before re-pricing it."

        Design: Corner/cross_cutting_layers/stale_version_on_service_change_apply
        """
        customer, contract, line, change, version_pre = self._setup()
        stale = api.apply_service_change(
            change["id"], {"expected_contract_version": version_pre}, OPS
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_service_change_request(change["id"], OPS))
        assert after["status"] == "APPROVED"
        line_after = validate_success(api.get_service_line(line["id"], OPS))
        assert line_after["base_rate_cents"] == 420000
