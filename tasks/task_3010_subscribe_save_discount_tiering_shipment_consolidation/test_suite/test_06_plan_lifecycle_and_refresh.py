"""Delivery plan lifecycle, line skip/unskip cycles, and version-guarded
refresh."""
from test_helpers import (
    ApiErrorId,
    assert_inventory_conservation,
    create_price_event_payload,
    get_plan,
    get_subscription_by_id,
    list_plan_lines,
    lock_plan,
    make_customer_headers,
    make_platform_admin_headers,
    set_clock,
    setup_customer_with_plan,
    validate_error,
    validate_success,
)

ADMIN = make_platform_admin_headers()


class TestPlanStateGuards:
    def test_lock_a_locked_plan_returns_plan_not_open(self, api):
        """PRD §3.6: "the customer locks an `OPEN` plan — any other
        `plan_status` is rejected with `ERR_PLAN_NOT_OPEN`".

        Design: Corner/state_machines/lock_a_locked_plan_returns_plan_not_open
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1,
        )
        lock_plan(plan, customer)
        resp = api.lock_plan(plan["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_OPEN.value, 409)
        refreshed = get_plan(plan["id"], as_customer=customer)
        assert refreshed["plan_status"] == "LOCKED"

    def test_ship_open_plan_returns_plan_not_locked(self, api):
        """PRD §3.9: "a `PlatformAdmin` ships a `LOCKED` plan — anything else is
        `ERR_PLAN_NOT_LOCKED`".

        Design: Corner/state_machines/ship_open_plan_returns_plan_not_locked
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1,
        )
        resp = api.ship_plan(plan["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_LOCKED.value, 409)
        refreshed = validate_success(
            api.get_inventory_placement(placement["id"], ADMIN),
        )
        assert refreshed["reserved_units"] == 0
        assert refreshed["shipped_units"] == 0

    def test_lock_response_carries_final_totals_immediately(self, api):
        """PRD §3.6: "The plan emerges `LOCKED` with `charged_total_cents`,
        `gross_line_total_cents`, `tier_discount_pct`, and `active_line_count`
        all set."

        Design: Corner/consistency_model/lock_response_carries_final_totals_immediately
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1, quantity=2,
        )
        resp = api.lock_plan(plan["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp)
        assert data["plan_status"] == "LOCKED"
        assert data["charged_total_cents"] == 2000
        assert data["gross_line_total_cents"] == 2000


class TestLineSkipUnskipCycle:
    def _setup_three_line_plan(self, api):
        return setup_customer_with_plan(num_subscriptions=3)

    def test_skip_cascades_line_count_tier_repricing_total(self, api):
        """PRD §3.10: "Skipping a `SCHEDULED` non-bonus line moves it to
        `SKIPPED` with `skip_reason` `CUSTOMER`".
        PRD §3.10: "Any change to the set of `SCHEDULED` lines recomputes
        `active_line_count`; the count change itself re-triggers tier selection;
        and the tier change re-triggers estimated per-line repricing and a fresh
        `estimated_total_cents`."

        Design: Difficulty/transitive_cascade/skip_cascades_line_count_tier_repricing_total
        """
        customer, product, placement, subs, plan = self._setup_three_line_plan(api)
        line = list_plan_lines(plan, as_customer=customer)[0]
        headers = make_customer_headers(customer["id"])
        validate_success(api.skip_line(plan["id"], line["id"], headers))
        refreshed_line = validate_success(api.get_plan_line(line["id"], headers))
        assert refreshed_line["line_status"] == "SKIPPED"
        assert refreshed_line["skip_reason"] == "CUSTOMER"
        refreshed_plan = get_plan(plan["id"], as_customer=customer)
        assert refreshed_plan["active_line_count"] == 2
        assert refreshed_plan["tier_discount_pct"] == 0.00
        assert refreshed_plan["estimated_total_cents"] == 2000

    def test_skip_unskip_cycle_restores_tier(self, api):
        """PRD §3.10: "unskipping requires the line to be `SKIPPED` with
        `skip_reason` `CUSTOMER` and its subscription to be `ACTIVE` — a line
        whose subscription has since moved on is rejected with
        `ERR_SUBSCRIPTION_NOT_ACTIVE` — and returns the line to `SCHEDULED` with
        `skip_reason` cleared."

        Design: Difficulty/non_linear_state_machine/planline_skip_unskip_cycle_restores_tier
        """
        customer, product, placement, subs, plan = self._setup_three_line_plan(api)
        line = list_plan_lines(plan, as_customer=customer)[0]
        headers = make_customer_headers(customer["id"])
        validate_success(api.skip_line(plan["id"], line["id"], headers))
        validate_success(api.unskip_line(plan["id"], line["id"], headers))
        refreshed_line = validate_success(api.get_plan_line(line["id"], headers))
        assert refreshed_line["line_status"] == "SCHEDULED"
        assert refreshed_line["skip_reason"] is None
        refreshed_plan = get_plan(plan["id"], as_customer=customer)
        assert refreshed_plan["active_line_count"] == 3
        assert refreshed_plan["tier_discount_pct"] == 0.05
        assert refreshed_plan["estimated_total_cents"] == 2850

    def test_unskip_a_scheduled_line_returns_line_not_skippable(self, api):
        """PRD §3.10: "unskipping requires the line to be `SKIPPED` with
        `skip_reason` `CUSTOMER`".
        PRD §3.10: "Skipping a `SCHEDULED` non-bonus line moves it to `SKIPPED`
        with `skip_reason` `CUSTOMER`; skipping a line that is not `SCHEDULED` —
        or any bonus line — is rejected with `ERR_LINE_NOT_SKIPPABLE`".

        Design: Corner/state_machines/unskip_a_scheduled_line_returns_line_not_skippable
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1,
        )
        line = list_plan_lines(plan, as_customer=customer)[0]
        headers = make_customer_headers(customer["id"])
        resp = api.unskip_line(plan["id"], line["id"], headers)
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_SKIPPABLE.value, 409)
        refreshed_line = validate_success(api.get_plan_line(line["id"], headers))
        assert refreshed_line["line_status"] == "SCHEDULED"


class TestPlanRefreshOcc:
    def test_successful_refresh_increments_version(self, api):
        """PRD §3.6: "Refresh re-runs steps 1 through 3 of the pipeline in
        estimated mode — re-evaluating availability, substitution, and caps
        against current prices — recomputes the tier and
        `estimated_total_cents`, and increments the plan's `version` by exactly
        1."

        Design: Corner/cross_cutting_layers/stale_plan_refresh_returns_412_and_version_increments_on_success
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1,
        )
        headers = make_customer_headers(customer["id"])
        observed = get_plan(plan["id"], as_customer=customer)
        resp = api.refresh_plan(
            plan["id"], {"expected_plan_version": observed["version"]}, headers,
        )
        data = validate_success(resp)
        assert data["version"] == observed["version"] + 1

    def test_stale_plan_refresh_returns_412(self, api):
        """PRD §2.11: "If the plan's current `version` differs from
        `expected_plan_version` — because some other write has advanced it since
        the client's last read — the refresh is rejected with
        `ERR_STALE_PLAN_VERSION` (HTTP 412), forcing the client to re-read the
        plan before re-estimating it."

        Design: Corner/cross_cutting_layers/stale_plan_refresh_returns_412_and_version_increments_on_success
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1,
        )
        headers = make_customer_headers(customer["id"])
        observed = get_plan(plan["id"], as_customer=customer)
        refreshed = validate_success(api.refresh_plan(
            plan["id"], {"expected_plan_version": observed["version"]}, headers,
        ))
        resp = api.refresh_plan(
            plan["id"],
            {"expected_plan_version": refreshed["version"] - 1},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PLAN_VERSION.value, 412)
        current = get_plan(plan["id"], as_customer=customer)
        assert current["version"] == refreshed["version"]

    def test_auto_skipped_line_recovers_on_refresh_after_price_drop(self, api):
        """PRD §3.10: "While the plan remains `OPEN`, a refresh that finds an
        `AUTO_SKIPPED` line's conditions healed — the current unit price at or
        under the subscription's cap (or the cap null) and the product
        `IN_STOCK` in region with sufficient on hand — restores the line to
        `SCHEDULED`, clears `skip_reason`, and triggers the same count-tier-total
        recomputation chain."

        Design: Corner/cross_cutting_layers/auto_skipped_line_recovers_on_refresh_after_price_drop
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=3,
            subscription_overrides_list=[{"price_cap_cents": 1050}] + [{}] * 2,
        )
        capped_sub = subs[0]
        headers = make_customer_headers(customer["id"])
        validate_success(api.create_price_event(
            product["id"],
            create_price_event_payload(1200, "2026-09-02T00:00:00Z"),
            ADMIN,
        ), 201)
        set_clock("2026-09-03T00:00:00Z")
        observed = get_plan(plan["id"], as_customer=customer)
        first = validate_success(api.refresh_plan(
            plan["id"], {"expected_plan_version": observed["version"]}, headers,
        ))
        # 2 surviving lines priced 1200 each, tier 0.00: estimate 2400.
        assert first["active_line_count"] == 2
        assert first["tier_discount_pct"] == 0.00
        assert first["estimated_total_cents"] == 2400

        validate_success(api.create_price_event(
            product["id"],
            create_price_event_payload(1000, "2026-09-04T00:00:00Z"),
            ADMIN,
        ), 201)
        set_clock("2026-09-05T00:00:00Z")
        second = validate_success(api.refresh_plan(
            plan["id"], {"expected_plan_version": first["version"]}, headers,
        ))
        # The capped line is back on the schedule.
        lines = list_plan_lines(plan, as_customer=customer)
        capped_line = [
            line for line in lines
            if line["subscription_id"] == capped_sub["id"]
        ][0]
        assert capped_line["line_status"] == "SCHEDULED"
        assert capped_line["skip_reason"] is None
        assert second["active_line_count"] == 3
        assert second["tier_discount_pct"] == 0.05
        assert second["estimated_total_cents"] == 2850
