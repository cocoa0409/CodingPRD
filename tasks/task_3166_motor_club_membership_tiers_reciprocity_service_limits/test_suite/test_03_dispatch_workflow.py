"""Dispatch workflow, provider selection, SLA, and billing corner + difficulty
coverage (PRD §3.5-3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_dispatch,
    arrive_dispatch,
    complete_dispatch,
    create_and_complete_call,
    create_and_dispatch_call,
    create_part_stock,
    create_provider,
    create_service_call,
    dispatch_call,
    get_membership,
    get_success_data,
    set_clock,
    setup_dispatchable_scenario,
    setup_foreign_call_scenario,
    setup_membership_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

PROVIDER_OPS = TEST_USERS["provider_ops_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


class TestProvisionalVersusFinalMileage:
    def test_provisional_uses_requested_miles(self, api):
        """PRD §3.6: "The dispatch also records a
        `provisional_mileage_charge_cents` — a forward-looking overage estimate
        computed on the requested-miles basis per the provisional variant of
        §3.7 — which is preview only and is never posted to the member's
        account." PRD §3.7: "the effective miles are the actual miles minus 3,
        floored at zero ... the overage miles are the effective miles beyond the
        tier's `included_tow_miles`, floored at zero, and the
        `mileage_charge_cents` is the overage miles times the tier's
        `overage_rate_cents_per_mile`".

        Design: Difficulty/dual_variant_calc/tow_overage_provisional_vs_final_estimate
        """
        base = setup_dispatchable_scenario("CLASSIC")
        call = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=30,
        )
        dispatch = dispatch_call(call["id"], call["version"])
        # provisional: requested 30 -> effective 27 -> overage 22 x 650
        assert dispatch["provisional_mileage_charge_cents"] == 14300
        assert dispatch["dispatched_tow_miles"] == 30

    def test_final_uses_actual_miles_and_differs(self, api):
        """PRD §3.7: "The final variant of the tow-overage calculation runs on
        the dispatch's `actual_tow_miles` against the call's pinned
        `benefit_tier_code` — never the membership's current tier." PRD §3.7:
        "Completing a benefit-eligible call increments the membership's
        `calls_used_current_term` by one — cap consumption happens at
        completion, never at dispatch".

        Design: Difficulty/dual_variant_calc/tow_overage_provisional_vs_final_estimate
        """
        base = setup_dispatchable_scenario("CLASSIC")
        pair = create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=30,
        )
        dispatch = pair["dispatch"]
        accept_dispatch(dispatch["id"], en_route=True)
        arrive_dispatch(dispatch["id"])
        done = complete_dispatch(dispatch["id"], actual_tow_miles=24)
        # final: actual 24 -> effective 21 -> overage 16 x 650
        assert done["mileage_charge_cents"] == 10400
        assert done["provisional_mileage_charge_cents"] == 14300
        assert done["mileage_charge_cents"] != done["provisional_mileage_charge_cents"]
        assert get_membership(base["membership"]["id"])["calls_used_current_term"] == 1


class TestRedispatchCycle:
    def test_fail_returns_call_to_requested(self, api, dispatcher_headers):
        """PRD §3.6: "moves the dispatch to terminal `FAILED`, and loops the
        parent call from `DISPATCHED` back to `REQUESTED`."

        Design: Difficulty/non_linear_state_machine/service_call_redispatch_cycle
        """
        base = setup_dispatchable_scenario("CLASSIC")
        p1 = base["provider"]
        p2 = create_provider(base["club"]["id"], name="NCA Fleet 2")
        pair = create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=10,
        )
        assert pair["dispatch"]["provider_id"] == p1["id"]
        fail_resp = api.fail_dispatch(pair["dispatch"]["id"], {"failure_reason": "PROVIDER_DECLINED"},
                                      PROVIDER_OPS)
        validate_success(fail_resp)
        call_after = get_success_data(api.get_service_call(pair["call"]["id"], dispatcher_headers))
        assert call_after["status"] == "REQUESTED"
        assert call_after["benefit_eligible"] is True
        assert get_membership(base["membership"]["id"])["calls_used_current_term"] == 0

    def test_redispatch_excludes_failed_provider_and_increments_sequence(self, api, dispatcher_headers):
        """PRD §3.6: "The next dispatch attempt receives the next
        `sequence_number` and re-runs selection with the failed provider
        excluded from that retry's candidate pool."

        Design: Difficulty/non_linear_state_machine/service_call_redispatch_cycle
        """
        base = setup_dispatchable_scenario("CLASSIC")
        p1 = base["provider"]
        p2 = create_provider(base["club"]["id"], name="NCA Fleet 2")
        pair = create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=10,
        )
        assert pair["dispatch"]["provider_id"] == p1["id"]
        validate_success(api.fail_dispatch(pair["dispatch"]["id"], {"failure_reason": "PROVIDER_DECLINED"},
                                           PROVIDER_OPS))
        call_after = get_success_data(api.get_service_call(pair["call"]["id"], dispatcher_headers))
        dispatch2 = dispatch_call(call_after["id"], call_after["version"])
        assert dispatch2["sequence_number"] == 2
        assert dispatch2["provider_id"] == p2["id"]


class TestDispatchBlockedWhenMembershipLapsed:
    def test_lapsed_membership_call_rejected(self, api, member_services_rep_headers, dispatcher_headers):
        """PRD §3.5: "the membership's `status` must be `ACTIVE`, `REINSTATED`,
        or `GRACE` — calls on `LAPSED` or `CANCELLED` memberships are rejected
        with `ERR_MEMBERSHIP_NOT_SERVICEABLE`".

        Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_when_membership_lapsed
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        validate_success(api.lapse_membership(base["membership"]["id"], member_services_rep_headers))
        resp = api.create_service_call(
            {"membership_id": base["membership"]["id"], "requesting_member_id": base["primary"]["id"],
             "service_type": "TOW", "breakdown_location_state": "CA", "requested_tow_miles": 10},
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_SERVICEABLE, expected_status=422)
        calls, _meta = validate_paginated(
            api.list_service_calls(dispatcher_headers, params={"membership_id": base["membership"]["id"]})
        )
        assert calls == []

    def test_cancelled_membership_call_rejected(self, api, member_services_rep_headers, dispatcher_headers):
        """PRD §3.5: "calls on `LAPSED` or `CANCELLED` memberships are rejected
        with `ERR_MEMBERSHIP_NOT_SERVICEABLE`".

        Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_when_membership_lapsed
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        validate_success(api.cancel_membership(base["membership"]["id"], member_services_rep_headers))
        resp = api.create_service_call(
            {"membership_id": base["membership"]["id"], "requesting_member_id": base["primary"]["id"],
             "service_type": "TOW", "breakdown_location_state": "CA", "requested_tow_miles": 10},
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_SERVICEABLE, expected_status=422)


class TestProviderSuspendBlockedByOpenDispatch:
    def test_suspend_rejected_while_dispatch_assigned(self, api, club_admin_headers):
        """PRD §3.6: "A club administrator may suspend a provider only while it
        holds no non-terminal dispatch — attempting suspension with work still
        in flight is rejected with `ERR_PROVIDER_BUSY`".

        Design: Difficulty/cross_entity_state_dependency/provider_suspend_blocked_by_open_dispatch
        """
        base = setup_dispatchable_scenario("CLASSIC")
        create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=10,
        )
        resp = api.update_provider(base["provider"]["id"], {"status": "SUSPENDED"}, club_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_BUSY, expected_status=422)

    def test_suspend_succeeds_after_completion_and_excludes_from_pool(self, api, club_admin_headers,
                                                                      dispatcher_headers):
        """PRD §3.6: "a suspended provider is excluded from all future dispatch
        candidate pools."

        Design: Difficulty/cross_entity_state_dependency/provider_suspend_blocked_by_open_dispatch
        """
        base = setup_dispatchable_scenario("CLASSIC")
        provider = base["provider"]
        create_and_complete_call(
            base["membership"]["id"], base["primary"]["id"],
            complete_payload={"actual_tow_miles": 5},
            breakdown_location_state="CA", requested_tow_miles=10,
        )
        resp = api.update_provider(provider["id"], {"status": "SUSPENDED"}, club_admin_headers)
        assert validate_success(resp)["status"] == "SUSPENDED"
        # Next dispatch attempt finds an empty pool and auto-cancels NO_PROVIDER.
        call = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        api.dispatch_service_call(call["id"], {"expected_service_call_version": call["version"]}, dispatcher_headers)
        after = get_success_data(api.get_service_call(call["id"], dispatcher_headers))
        assert after["status"] == "CANCELLED"
        assert after["cancel_reason"] == "NO_PROVIDER"
        dispatches, _meta = validate_paginated(
            api.list_dispatches_for_call(call["id"], dispatcher_headers)
        )
        assert dispatches == []


class TestShiftWindowHalfOpen:
    def test_dispatch_at_shift_start_succeeds(self, api, dispatcher_headers):
        """PRD §3.6: "the provider's availability window is open — the
        minute-of-day of the logical now falls within the half-open interval
        from `shift_start_minute` to `shift_end_minute`".

        Design: Difficulty/resource_temporal_overlap/provider_shift_window_half_open_eligibility
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        provider = create_provider(
            base["club"]["id"], name="NCA Days", shift_start_minute=480, shift_end_minute=960,
        )
        set_clock("2026-09-01T08:00:00Z")
        call = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        dispatch = dispatch_call(call["id"], call["version"])
        assert dispatch["provider_id"] == provider["id"]

    def test_dispatch_at_shift_end_auto_cancels_no_provider(self, api, dispatcher_headers):
        """PRD §3.6: "the minute-of-day of the logical now falls within the
        half-open interval from `shift_start_minute` to `shift_end_minute`".
        PRD §3.6: "When no candidate survives, no `Dispatch` row is created at
        all; the call transitions straight from `REQUESTED` to `CANCELLED` with
        `cancel_reason` set to `NO_PROVIDER`".

        Design: Difficulty/resource_temporal_overlap/provider_shift_window_half_open_eligibility
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        create_provider(base["club"]["id"], name="NCA Days", shift_start_minute=480, shift_end_minute=960)
        set_clock("2026-09-01T16:00:00Z")
        call = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        api.dispatch_service_call(call["id"], {"expected_service_call_version": call["version"]}, dispatcher_headers)
        after = get_success_data(api.get_service_call(call["id"], dispatcher_headers))
        assert after["status"] == "CANCELLED"
        assert after["cancel_reason"] == "NO_PROVIDER"
        dispatches, _meta = validate_paginated(
            api.list_dispatches_for_call(call["id"], dispatcher_headers)
        )
        assert dispatches == []


class TestProviderConcurrencyCapacity:
    def test_at_capacity_provider_skipped_for_second_call(self, api):
        """PRD §3.6: "the provider's current load — its count of non-terminal
        dispatches, those in `ASSIGNED`, `ACCEPTED`, `EN_ROUTE`, or `ARRIVED` —
        is strictly below its `max_concurrent_dispatches`".

        Design: Difficulty/resource_temporal_overlap/provider_concurrency_capacity_aggregate_overlap
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        p1 = create_provider(base["club"]["id"], name="NCA Fleet 1", max_concurrent_dispatches=1)
        p2 = create_provider(base["club"]["id"], name="NCA Fleet 2", max_concurrent_dispatches=1)
        call1 = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        d1 = dispatch_call(call1["id"], call1["version"])
        assert d1["provider_id"] == p1["id"]
        call2 = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        d2 = dispatch_call(call2["id"], call2["version"])
        assert d2["provider_id"] == p2["id"], "P1 at capacity must be skipped for the second call"

    def test_capacity_freed_by_terminal_state(self, api):
        """PRD §3.6: "the provider's current load — its count of non-terminal
        dispatches, those in `ASSIGNED`, `ACCEPTED`, `EN_ROUTE`, or `ARRIVED` —
        is strictly below its `max_concurrent_dispatches`".

        Design: Difficulty/resource_temporal_overlap/provider_concurrency_capacity_aggregate_overlap
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        p1 = create_provider(base["club"]["id"], name="NCA Fleet 1", max_concurrent_dispatches=1)
        create_provider(base["club"]["id"], name="NCA Fleet 2", max_concurrent_dispatches=1)
        call1 = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        d1 = dispatch_call(call1["id"], call1["version"])
        assert d1["provider_id"] == p1["id"]
        accept_dispatch(d1["id"], en_route=True)
        arrive_dispatch(d1["id"])
        complete_dispatch(d1["id"], actual_tow_miles=5)
        call3 = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        d3 = dispatch_call(call3["id"], call3["version"])
        assert d3["provider_id"] == p1["id"], "completed dispatch frees P1's slot"


class TestDispatchFailRetryCapacityInvariant:
    def test_fail_releases_capacity_and_consumes_nothing(self, api, member_services_rep_headers):
        """PRD §3.7: "cap consumption happens at completion, never at dispatch,
        so a failed or cancelled attempt costs the member nothing against the
        cap." PRD §3.6: "loops the parent call from `DISPATCHED` back to
        `REQUESTED`" and the failed dispatch is terminal.

        Design: Difficulty/compensating_invariant/dispatch_fail_retry_capacity_invariant
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        p1 = create_provider(base["club"]["id"], name="NCA Fleet 1", max_concurrent_dispatches=1)
        p2 = create_provider(base["club"]["id"], name="NCA Fleet 2", max_concurrent_dispatches=1)
        call = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        d1 = dispatch_call(call["id"], call["version"])
        assert d1["provider_id"] == p1["id"]
        validate_success(api.fail_dispatch(d1["id"], {"failure_reason": "PROVIDER_DECLINED"},
                                           PROVIDER_OPS))
        d1_after = get_success_data(api.get_dispatch(d1["id"], DISPATCHER))
        assert d1_after["status"] == "FAILED"
        call_after = get_success_data(api.get_service_call(call["id"], member_services_rep_headers))
        d2 = dispatch_call(call_after["id"], call_after["version"])
        assert d2["provider_id"] == p2["id"]
        assert d2["sequence_number"] == 2
        accept_dispatch(d2["id"], en_route=True)
        arrive_dispatch(d2["id"])
        complete_dispatch(d2["id"], actual_tow_miles=5)
        m = get_membership(base["membership"]["id"])
        assert m["calls_used_current_term"] == 1, "the failed attempt consumed nothing"
        # one benefit-eligible 5-mile tow under CLASSIC (incl 5, bonus 3): no charge
        assert m["account_credit_cents"] == 0

    def test_fail_then_retry_membership_credit_reflects_single_completion(self, api):
        """PRD §3.7: "the membership's `account_credit_cents` decreases by
        `total_member_charge_cents`" — exactly once for the single completed
        call. PRD §3.7: "cap consumption happens at completion, never at
        dispatch".

        Design: Difficulty/compensating_invariant/dispatch_fail_retry_capacity_invariant
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        create_provider(base["club"]["id"], name="NCA Fleet 1")
        create_provider(base["club"]["id"], name="NCA Fleet 2")
        call = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=20,
        )
        d1 = dispatch_call(call["id"], call["version"])
        validate_success(api.fail_dispatch(d1["id"], {"failure_reason": "PROVIDER_DECLINED"},
                                           PROVIDER_OPS))
        call_after = get_success_data(api.get_service_call(call["id"], DISPATCHER))
        d2 = dispatch_call(call_after["id"], call_after["version"])
        accept_dispatch(d2["id"], en_route=True)
        arrive_dispatch(d2["id"])
        done = complete_dispatch(d2["id"], actual_tow_miles=20)
        # effective 17 - included 5 = 12 overage miles x 650 = 7800
        assert done["mileage_charge_cents"] == 7800
        m = get_membership(base["membership"]["id"])
        assert m["account_credit_cents"] == -7800, "exactly one call's charges, not two"


class TestSlaBoundaryInclusive:
    def test_arrive_exactly_at_promise_meets_sla(self, api, provider_ops_headers):
        """PRD §3.6: "computes `sla_met` as true exactly when `arrived_at` is no
        later than `promised_arrive_by` — the boundary is inclusive, so arriving
        at the promised instant counts as meeting the SLA."

        Design: Corner/state_machines/dispatch_arrive_sla_boundary_inclusive
        """
        base = setup_dispatchable_scenario("CLASSIC")
        pair = create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        accept_dispatch(pair["dispatch"]["id"], en_route=True)
        set_clock("2026-09-01T00:45:00Z")
        resp = api.arrive_dispatch(pair["dispatch"]["id"], provider_ops_headers)
        assert validate_success(resp)["sla_met"] is True

    def test_arrive_one_minute_late_misses_sla(self, api, provider_ops_headers):
        """PRD §3.6: "computes `sla_met` as true exactly when `arrived_at` is no
        later than `promised_arrive_by` — the boundary is inclusive".

        Design: Corner/state_machines/dispatch_arrive_sla_boundary_inclusive
        """
        base = setup_dispatchable_scenario("CLASSIC")
        pair = create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        accept_dispatch(pair["dispatch"]["id"], en_route=True)
        set_clock("2026-09-01T00:46:00Z")
        resp = api.arrive_dispatch(pair["dispatch"]["id"], provider_ops_headers)
        assert validate_success(resp)["sla_met"] is False


class TestServiceCallExpiry:
    def test_requested_call_expires_after_24_hours(self, api, dispatcher_headers, settlement_clerk_headers):
        """PRD §2.4: "Any `ServiceCall` still sitting in `REQUESTED` more than
        twenty-four hours after its `created_at` transitions to `EXPIRED`. An
        expired call consumed no benefit and generates no settlement line."

        Design: Corner/state_machines/service_call_expiry_via_clock
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        call = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        set_clock("2026-09-02T00:00:01Z")
        after = get_success_data(api.get_service_call(call["id"], dispatcher_headers))
        assert after["status"] == "EXPIRED"
        assert get_membership(base["membership"]["id"])["calls_used_current_term"] == 0
        lines, _meta = validate_paginated(api.list_settlement_lines(settlement_clerk_headers))
        assert lines == []


class TestDispatchInvalidTransitions:
    def test_complete_from_assigned_rejected(self, api, provider_ops_headers, dispatcher_headers):
        """PRD §2.8 step 6: "the target resource is in a state that permits the
        operation: dispatch only from `REQUESTED`, completion only from
        `ARRIVED`".

        Design: Corner/state_machines/dispatch_complete_from_assigned_rejected
        """
        base = setup_dispatchable_scenario("CLASSIC")
        pair = create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        resp = api.complete_dispatch(pair["dispatch"]["id"], {"actual_tow_miles": 5}, provider_ops_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = get_success_data(api.get_dispatch(pair["dispatch"]["id"], dispatcher_headers))
        assert after["status"] == "ASSIGNED"
        assert after["mileage_charge_cents"] == 0

    def test_fail_completed_dispatch_rejected(self, api, provider_ops_headers, dispatcher_headers):
        """PRD §3.6: "Failing a dispatch from `ASSIGNED`, `ACCEPTED`, or
        `EN_ROUTE`" — COMPLETED is terminal. PRD §2.8 step 6: "Violations return
        `ERR_INVALID_STATE`."

        Design: Corner/endpoints/dispatch_fail_terminal_rejected
        """
        base = setup_dispatchable_scenario("CLASSIC")
        pair = create_and_complete_call(
            base["membership"]["id"], base["primary"]["id"],
            complete_payload={"actual_tow_miles": 5},
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        resp = api.fail_dispatch(pair["dispatch"]["id"], {"failure_reason": "PROVIDER_DECLINED"},
                                 provider_ops_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = get_success_data(api.get_dispatch(pair["dispatch"]["id"], dispatcher_headers))
        assert after["status"] == "COMPLETED"


class TestDispatchCancelBoundary:
    def test_cancel_while_assigned_succeeds_and_cascades(self, api, dispatcher_headers):
        """PRD §3.6: "A successful cancel sets the call's `cancel_reason` to
        `MEMBER_REQUEST` and cascades the linked dispatch to `CANCELLED`, freeing
        one slot of the provider's concurrency capacity."

        Design: Corner/validations/dispatch_cancel_beyond_en_route_rejected
        """
        base = setup_dispatchable_scenario("CLASSIC")
        pair = create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        resp = api.cancel_service_call(pair["call"]["id"], dispatcher_headers)
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "MEMBER_REQUEST"
        d = get_success_data(api.get_dispatch(pair["dispatch"]["id"], dispatcher_headers))
        assert d["status"] == "CANCELLED"

    def test_cancel_while_en_route_rejected(self, api, dispatcher_headers):
        """PRD §3.6: "Once `DISPATCHED`, cancellation is permitted only while
        the linked non-terminal dispatch is `ASSIGNED` or `ACCEPTED` — past
        that, with the provider rolling or on scene, the member owes a service
        attempt and the cancel is rejected with `ERR_DISPATCH_BEYOND_CANCEL`."

        Design: Corner/validations/dispatch_cancel_beyond_en_route_rejected
        """
        base = setup_dispatchable_scenario("CLASSIC")
        pair = create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        accept_dispatch(pair["dispatch"]["id"], en_route=True)
        resp = api.cancel_service_call(pair["call"]["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_DISPATCH_BEYOND_CANCEL, expected_status=422)


class TestEffectiveArrivalTargetRounding:
    def test_rounding_half_up_to_68_minutes(self, api):
        """PRD §3.6: "The promised arrival instant `promised_arrive_by` is
        `assigned_at` plus the effective arrival target: the servicing club's
        `default_arrival_target_minutes` multiplied by the chosen provider's
        `sla_multiplier`, rounded half-up to whole minutes."

        Design: Corner/calculations/effective_arrival_target_rounding
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        create_provider(base["club"]["id"], name="NCA Fleet 1", provider_kind="CONTRACTED", sla_multiplier=1.5)
        call = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        dispatch = dispatch_call(call["id"], call["version"])
        # round_half_up(45 x 1.5) = 68 minutes after the 2026-09-01T00:00:00Z default clock
        assert dispatch["promised_arrive_by"] == "2026-09-01T01:08:00.000Z"


class TestGraceCallMemberPay:
    def test_grace_call_forced_member_pay_and_excluded_line(self, api, settlement_clerk_headers):
        """PRD §3.5: "Calls created while the membership is in `GRACE` are
        always member-pay: `benefit_eligible` is forced false regardless of the
        counter." PRD §3.7: "If the call was member-pay, the line is instead
        born with `excluded` true and `exclusion_reason` `MEMBER_PAY`".

        Design: Corner/calculations/grace_call_member_pay_and_no_settlement
        """
        scenario = setup_foreign_call_scenario()
        set_clock("2027-09-02T00:00:00Z")  # membership enters GRACE via sweep
        call = create_service_call(
            scenario["membership"]["id"], scenario["primary"]["id"],
            breakdown_location_state="CS", requested_tow_miles=10,
        )
        assert call["benefit_eligible"] is False
        dispatch = dispatch_call(call["id"], call["version"])
        accept_dispatch(dispatch["id"], en_route=True)
        arrive_dispatch(dispatch["id"])
        complete_dispatch(dispatch["id"], actual_tow_miles=10)
        lines, _meta = validate_paginated(
            api.list_settlement_lines(CLERK, params={"service_call_id": call["id"]})
        )
        assert len(lines) == 1
        line = lines[0]
        assert line["excluded"] is True
        assert line["exclusion_reason"] == "MEMBER_PAY"

    def test_grace_call_full_price_book_charge_and_no_cap_consumption(self, api, settlement_clerk_headers):
        """PRD §3.7: "For a member-pay call (`benefit_eligible` false), there is
        no included-mile deduction at all: the member is billed the full
        effective miles times the overage rate." PRD §3.7: "Completing a
        benefit-eligible call increments the membership's
        `calls_used_current_term` by one".

        Design: Corner/calculations/grace_call_member_pay_and_no_settlement
        """
        scenario = setup_foreign_call_scenario()
        set_clock("2027-09-02T00:00:00Z")
        call = create_service_call(
            scenario["membership"]["id"], scenario["primary"]["id"],
            breakdown_location_state="CS", requested_tow_miles=10,
        )
        dispatch = dispatch_call(call["id"], call["version"])
        accept_dispatch(dispatch["id"], en_route=True)
        arrive_dispatch(dispatch["id"])
        done = complete_dispatch(dispatch["id"], actual_tow_miles=10)
        # member-pay: effective 10-3 = 7 miles x 650 = 4550, no included deduction
        assert done["total_member_charge_cents"] == 4550
        assert get_membership(scenario["membership"]["id"])["calls_used_current_term"] == 0


class TestBatteryPartSaleStock:
    def test_battery_completion_charges_parts_and_decrements_stock(self, api, club_admin_headers):
        """PRD §3.7: "`parts_charge_cents` is the sum over `parts_used` of each
        part's price-book price times its quantity. The federation parts price
        book fixes `BAT-G24` at 14500 cents". PRD §3.7: "On success the stock
        decrements per `parts_used`".

        Design: Corner/calculations/battery_part_sale_decrements_truck_stock
        """
        base = setup_dispatchable_scenario("PLUS", provider_overrides={"capabilities": ["BATTERY"],
                                                                       "max_concurrent_dispatches": 3})
        create_part_stock(base["provider"]["id"], part_sku="BAT-G24", part_kind="BATTERY", quantity_on_hand=3)
        pair = create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            service_type="BATTERY", breakdown_location_state="CA",
        )
        accept_dispatch(pair["dispatch"]["id"], en_route=True)
        arrive_dispatch(pair["dispatch"]["id"])
        done = complete_dispatch(pair["dispatch"]["id"], parts_used=[{"part_sku": "BAT-G24", "quantity": 1}])
        assert done["parts_charge_cents"] == 14500
        assert done["total_member_charge_cents"] == 14500  # no mileage for BATTERY
        stocks, _meta = validate_paginated(
            api.list_truck_part_stocks_for(base["provider"]["id"], club_admin_headers)
        )
        assert stocks[0]["quantity_on_hand"] == 2

    def test_insufficient_stock_rejected_and_dispatch_stays_arrived(self, api, dispatcher_headers):
        """PRD §3.7: "with `quantity_on_hand` at least the requested quantity,
        or the completion is rejected with `ERR_INSUFFICIENT_TRUCK_STOCK` and
        the dispatch stays `ARRIVED`".

        Design: Corner/calculations/battery_part_sale_decrements_truck_stock
        """
        base = setup_dispatchable_scenario("PLUS", provider_overrides={"capabilities": ["BATTERY"],
                                                                       "max_concurrent_dispatches": 3})
        create_part_stock(base["provider"]["id"], part_sku="BAT-G24", part_kind="BATTERY", quantity_on_hand=3)
        pair = create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            service_type="BATTERY", breakdown_location_state="CA",
        )
        accept_dispatch(pair["dispatch"]["id"], en_route=True)
        arrive_dispatch(pair["dispatch"]["id"])
        resp = api.complete_dispatch(pair["dispatch"]["id"],
                                     {"parts_used": [{"part_sku": "BAT-G24", "quantity": 5}]},
                                     PROVIDER_OPS)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_TRUCK_STOCK, expected_status=422)
        after = get_success_data(api.get_dispatch(pair["dispatch"]["id"], dispatcher_headers))
        assert after["status"] == "ARRIVED"


class TestCompletionImmediateConsistency:
    def test_completion_response_and_follow_up_get_agree(self, api, dispatcher_headers, member_services_rep_headers):
        """PRD §3.7: "The dispatch lands in `COMPLETED` with `completed_at`
        stamped, and the parent call moves from `ON_SCENE` to `COMPLETED` in the
        same atomic step." PRD §3.7: "the membership's `account_credit_cents`
        decreases by `total_member_charge_cents`".

        Design: Corner/consistency_model/completion_writes_immediately_visible
        """
        base = setup_dispatchable_scenario("CLASSIC")
        pair = create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=20,
        )
        accept_dispatch(pair["dispatch"]["id"], en_route=True)
        arrive_dispatch(pair["dispatch"]["id"])
        resp = api.complete_dispatch(pair["dispatch"]["id"], {"actual_tow_miles": 20},
                                     PROVIDER_OPS)
        done = validate_success(resp)
        assert done["status"] == "COMPLETED"
        # (20 - 3 - 5) x 650 = 7800
        assert done["mileage_charge_cents"] == 7800
        assert done["total_member_charge_cents"] == 7800
        reread = get_success_data(api.get_dispatch(pair["dispatch"]["id"], dispatcher_headers))
        assert reread["mileage_charge_cents"] == 7800
        m = get_membership(base["membership"]["id"])
        assert m["calls_used_current_term"] == 1
        assert m["account_credit_cents"] == -7800


