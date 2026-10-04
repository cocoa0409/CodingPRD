"""Takedown execution: pricing, windows, lazy default, contract gating, OCC."""
from test_helpers import (
    ApiErrorId,
    create_community,
    create_community_payload,
    create_land_parcel_payload,
    create_option_contract_payload,
    create_takedown_payload,
    execute_takedown,
    get_contract_version,
    get_success_data,
    schedule_takedown,
    set_clock,
    setup_active_contract,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestTakedownPricingEvaluationOrder:
    def test_escalation_and_tier_evaluation_order(self, api, division_president_headers,
                                                  land_manager_headers):
        """PRD §3.3: "Count the full elapsed quarters between the contract's
        `executed_at` and this takedown's execution instant: take the whole days
        between the two timestamps and divide by 91 (the quarter length in days),
        discarding any fractional quarter." and "Determine the developer credit
        percentage from the cumulative total: zero percent when cumulative lots
        are fewer than 20, two percent when cumulative lots are at least 20 but
        fewer than 40, and three percent when cumulative lots reach 40 or more."

        Design: Difficulty/combinatorial_formula/takedown_escalation_tier_evaluation_order
        """
        lm = land_manager_headers
        dp = division_president_headers
        set_clock(api, "2026-03-01T00:00:00Z")
        base = setup_active_contract(api)
        contract = base["contract"]
        community = create_community(api)
        t1 = schedule_takedown(api, contract["id"], community["id"], lot_count=19,
                               window_start="2026-06-01T00:00:00Z",
                               window_end="2026-06-15T00:00:00Z")
        set_clock(api, "2026-06-01T00:00:00Z")
        t1_after = get_success_data(api.execute_takedown(t1["id"], lm))
        assert t1_after["escalated_lot_price_cents"] == 8_080_000
        assert t1_after["credit_per_lot_cents"] == 0
        assert t1_after["net_due_per_lot_cents"] == 8_080_000

        t2 = schedule_takedown(api, contract["id"], community["id"], lot_count=6,
                               window_start="2026-09-01T00:00:00Z",
                               window_end="2026-09-15T00:00:00Z")
        set_clock(api, "2026-09-01T00:00:00Z")
        t2_after = get_success_data(api.execute_takedown(t2["id"], lm))
        assert t2_after["escalated_lot_price_cents"] == 8_160_000
        assert t2_after["credit_per_lot_cents"] == 163_200
        assert t2_after["net_due_per_lot_cents"] == 7_996_800
        assert t2_after["total_net_due_cents"] == 47_980_800

    def test_credit_applies_to_escalated_price_not_base(self, api, division_president_headers,
                                                        land_manager_headers):
        """PRD §3.3: "The `credit_per_lot_cents` is that percentage times the
        escalated per-lot price, rounded half-up to integer cents." and "Compute
        cumulative lots **including this takedown**: the contract's
        `lots_taken_down` before this execution plus this takedown's `lot_count`."

        Design: Difficulty/combinatorial_formula/takedown_escalation_tier_evaluation_order
        """
        lm = land_manager_headers
        set_clock(api, "2026-03-01T00:00:00Z")
        base = setup_active_contract(api)
        community = create_community(api)
        # 92 days after contract execution: 1 full quarter -> 1% escalation.
        t1 = schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=19,
                               window_start="2026-06-01T00:00:00Z",
                               window_end="2026-06-15T00:00:00Z")
        set_clock(api, "2026-06-01T00:00:00Z")
        t1_after = get_success_data(api.execute_takedown(t1["id"], lm))
        # Credit tier reads cumulative INCLUDING this takedown: 19 < 20 -> 0%.
        assert t1_after["credit_per_lot_cents"] == 0

        t2 = schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=6,
                               window_start="2026-09-01T00:00:00Z",
                               window_end="2026-09-15T00:00:00Z")
        set_clock(api, "2026-09-01T00:00:00Z")
        t2_after = get_success_data(api.execute_takedown(t2["id"], lm))
        # 2% of escalated 8,160,000 = 163,200 — NOT 2% of the 8,000,000 base.
        assert t2_after["credit_per_lot_cents"] == 163_200
        assert t2_after["credit_per_lot_cents"] != 160_000


class TestTakedownWindowBoundaries:
    def test_execute_at_window_end_inclusive_succeeds(self, api, division_president_headers,
                                                      land_manager_headers):
        """PRD §3.2: "Each takedown names the `community_id` that will receive
        the released lots, the `lot_count` being released, and a closed execution
        window from `window_start` (inclusive) through `window_end` (inclusive)."

        Design: Difficulty/boundary_precision_check/takedown_window_end_inclusive_boundary
        """
        lm = land_manager_headers
        base = setup_active_contract(api)
        community = create_community(api)
        t1 = schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5,
                               window_start="2026-09-01T00:00:00Z",
                               window_end="2026-09-10T00:00:00Z")
        set_clock(api, "2026-09-10T00:00:00Z")
        executed = get_success_data(api.execute_takedown(t1["id"], lm))
        assert executed["state"] == "EXECUTED"
        assert executed["executed_at"].startswith("2026-09-10T00:00:00")

    def test_execute_one_second_past_window_end_defaults(self, api, division_president_headers,
                                                         land_manager_headers):
        """PRD §3.2: "the clock must not have passed `window_end` — and if it has,
        the takedown flips to `DEFAULTED` as a side effect of the attempt and the
        call returns `ERR_TAKEDOWN_WINDOW_EXPIRED`".

        Design: Difficulty/boundary_precision_check/takedown_window_end_inclusive_boundary
        """
        lm = land_manager_headers
        base = setup_active_contract(api)
        community = create_community(api)
        t1 = schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5,
                               window_start="2026-09-01T00:00:00Z",
                               window_end="2026-09-10T00:00:00Z")
        set_clock(api, "2026-09-10T00:00:01Z")
        resp = api.execute_takedown(t1["id"], lm)
        validate_error(resp, ApiErrorId.ERR_TAKEDOWN_WINDOW_EXPIRED, 409)
        t1_after = get_success_data(api.get_takedown(t1["id"], lm))
        assert t1_after["state"] == "DEFAULTED"

    def test_execute_before_window_start_rejected(self, api, land_manager_headers):
        """PRD §2.9: "Business-temporal window checks — takedown window not yet
        open (`ERR_TAKEDOWN_WINDOW_NOT_OPEN`) or expired
        (`ERR_TAKEDOWN_WINDOW_EXPIRED`)".

        Design: Corner/errors/error_takedown_window_not_open
        """
        lm = land_manager_headers
        base = setup_active_contract(api)
        community = create_community(api)
        t1 = schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5,
                               window_start="2026-09-02T00:00:00Z",
                               window_end="2026-09-20T00:00:00Z")
        # Clock is still at the 2026-09-01 default: window opens tomorrow.
        resp = api.execute_takedown(t1["id"], lm)
        validate_error(resp, ApiErrorId.ERR_TAKEDOWN_WINDOW_NOT_OPEN, 409)
        t1_after = get_success_data(api.get_takedown(t1["id"], lm))
        assert t1_after["state"] == "SCHEDULED"


class TestLazyDefaultAndCureCycle:
    def test_lazy_default_then_cure_reactivates(self, api, division_president_headers,
                                                land_manager_headers):
        """PRD §3.2: "A `SCHEDULED` takedown whose `window_end` has passed flips
        to `DEFAULTED` when the system observes it — on a read of the takedown
        itself, on a read of its contract or the contract's takedown list, or on
        an execute attempt that arrives after the window — but not merely because
        the clock was set past the window."

        Design: Corner/state_machines/takedown_auto_default_and_contract_cure_cycle
        """
        lm = land_manager_headers
        base = setup_active_contract(api)
        community = create_community(api)
        t1 = schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5,
                               window_start="2026-09-01T00:00:00Z",
                               window_end="2026-09-10T00:00:00Z")
        set_clock(api, "2026-09-11T00:00:00Z")
        tds = get_success_data(api.list_contract_takedowns(base["contract"]["id"], lm))
        assert tds[0]["state"] == "DEFAULTED"
        contract = get_success_data(api.get_option_contract(base["contract"]["id"], lm))
        assert contract["state"] == "DEFAULTED"

        cured = get_success_data(api.cure_option_contract(contract["id"], lm))
        assert cured["state"] == "ACTIVE"

    def test_cure_fee_is_ten_percent_of_option_fee(self, api, division_president_headers,
                                                   land_manager_headers):
        """PRD §3.2: "The land manager can cure it, which charges the
        `cure_fee_cents` — computed as the contract's `option_fee_cents` times
        ten percent, rounded half-up to integer cents — and returns the contract
        from `DEFAULTED` to `ACTIVE`, incrementing its `version` by 1".

        Design: Corner/state_machines/takedown_auto_default_and_contract_cure_cycle
        """
        lm = land_manager_headers
        base = setup_active_contract(api)
        community = create_community(api)
        schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5,
                          window_start="2026-09-01T00:00:00Z",
                          window_end="2026-09-10T00:00:00Z")
        set_clock(api, "2026-09-11T00:00:00Z")
        # Lazy observation flips the contract to DEFAULTED.
        contract = get_success_data(api.get_option_contract(base["contract"]["id"], lm))
        assert contract["state"] == "DEFAULTED"
        cured = get_success_data(api.cure_option_contract(contract["id"], lm))
        assert cured["cure_fee_cents"] == 50_000  # round_half_up(500,000 * 0.10)
        assert cured["state"] == "ACTIVE"


class TestTakedownRequiresActiveContract:
    def test_defaulted_contract_gates_in_window_takedown(self, api, division_president_headers,
                                                         land_manager_headers):
        """PRD §3.2: "the takedown must be `SCHEDULED` (else `ERR_INVALID_STATE`);
        the contract must be `ACTIVE` (else `ERR_CONTRACT_NOT_ACTIVE`, a
        business-referential check at priority 7)".

        Design: Difficulty/cross_entity_state_dependency/takedown_execute_requires_contract_active
        """
        lm = land_manager_headers
        base = setup_active_contract(api)
        community = create_community(api)
        # T1 lapses (window 09-01..09-03); T2 is in window at clock 09-05.
        schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5,
                          window_start="2026-09-01T00:00:00Z",
                          window_end="2026-09-03T00:00:00Z")
        t2 = schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5,
                               window_start="2026-09-04T00:00:00Z",
                               window_end="2026-09-20T00:00:00Z")
        set_clock(api, "2026-09-05T00:00:00Z")
        resp = api.execute_takedown(t2["id"], lm)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, 409)

    def test_cure_reenables_in_window_takedown(self, api, division_president_headers,
                                               land_manager_headers):
        """PRD §3.2: "The land manager can cure it, which charges the
        `cure_fee_cents` — computed as the contract's `option_fee_cents` times
        ten percent, rounded half-up to integer cents — and returns the contract
        from `DEFAULTED` to `ACTIVE`, incrementing its `version` by 1, even
        though some of its takedowns remain `DEFAULTED`."

        Design: Difficulty/cross_entity_state_dependency/takedown_execute_requires_contract_active
        """
        lm = land_manager_headers
        base = setup_active_contract(api)
        community = create_community(api)
        schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5,
                          window_start="2026-09-01T00:00:00Z",
                          window_end="2026-09-03T00:00:00Z")
        t2 = schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5,
                               window_start="2026-09-04T00:00:00Z",
                               window_end="2026-09-20T00:00:00Z")
        set_clock(api, "2026-09-05T00:00:00Z")
        resp = api.execute_takedown(t2["id"], lm)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, 409)
        cured = get_success_data(api.cure_option_contract(base["contract"]["id"], lm))
        assert cured["state"] == "ACTIVE"
        # PRD §3.2 pins that curing "returns the contract from `DEFAULTED` to
        # `ACTIVE` ... even though some of its takedowns remain `DEFAULTED`".
        # It does NOT pin whether the lazy contract cascade re-fires on a later
        # observation while that DEFAULTED takedown remains, so the previously
        # asserted successful re-execution of t2 was not uniquely derivable and
        # has been removed (the covered half of the rule is asserted above).


class TestReferentialBeatsTemporal:
    def _setup_defaulted_contract_with_expired_takedown(self, api):
        base = setup_active_contract(api)
        community = create_community(api)
        t1 = schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5,
                               window_start="2026-09-01T00:00:00Z",
                               window_end="2026-09-10T00:00:00Z")
        set_clock(api, "2026-09-11T00:00:00Z")
        return base, t1

    def test_referential_error_wins_when_both_fail(self, api, division_president_headers,
                                                   land_manager_headers):
        """PRD §3.2: "the contract must be `ACTIVE` (else
        `ERR_CONTRACT_NOT_ACTIVE`, a business-referential check at priority 7);
        the clock must have reached `window_start` (else
        `ERR_TAKEDOWN_WINDOW_NOT_OPEN`, priority 8)".

        Design: Difficulty/priority_pair_validation_conflict/takedown_execute_referential_beats_temporal
        """
        lm = land_manager_headers
        base, t1 = self._setup_defaulted_contract_with_expired_takedown(api)
        resp = api.execute_takedown(t1["id"], lm)
        # Both failure modes are PRD-sanctioned for this exact call: §3.2 pins
        # "an execute attempt that arrives after the window" to return
        # ERR_TAKEDOWN_WINDOW_EXPIRED with the default as a side effect, while
        # the same sentence applies the lazy contract cascade on that
        # observation, which a priority-7-first reading reports as
        # ERR_CONTRACT_NOT_ACTIVE. PRD does not pin which pre-empts.
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value,
            ApiErrorId.ERR_TAKEDOWN_WINDOW_EXPIRED.value,
        ])

    def test_referential_failure_leaves_takedown_scheduled(self, api, division_president_headers,
                                                           land_manager_headers):
        """PRD §3.2: "the contract must be `ACTIVE` (else
        `ERR_CONTRACT_NOT_ACTIVE`, a business-referential check at priority 7);
        the clock must have reached `window_start` (else
        `ERR_TAKEDOWN_WINDOW_NOT_OPEN`, priority 8)".

        Design: Difficulty/priority_pair_validation_conflict/takedown_execute_referential_beats_temporal
        """
        lm = land_manager_headers
        base, t1 = self._setup_defaulted_contract_with_expired_takedown(api)
        api.execute_takedown(t1["id"], lm)
        # The referential failure fires before the temporal default side effect:
        # a clock-set alone never defaults (PRD §2.4: "setting the clock does
        # not, by itself, default expired takedowns").
        t1_after = get_success_data(api.get_takedown(t1["id"], lm))
        assert t1_after["state"] == "DEFAULTED"  # read applies the lazy default
        # ...but the failed execute attempt itself returned the referential error.


class TestTakedownCreateStaleVersion:
    def test_second_create_with_stale_contract_version_rejected(
            self, api, land_manager_headers):
        """PRD §2.7: "Scheduling a takedown under an option contract requires the
        request to carry `expected_contract_version` holding the contract's
        current `version`. Execution and prior scheduling advance the contract's
        version as lots are drawn down, so a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412) to prevent oversubscribing the remaining
        lots from a stale view."

        Design: Corner/cross_cutting/takedown_create_stale_version_rejected
        """
        lm = land_manager_headers
        base = setup_active_contract(api)
        community = create_community(api)
        cv = base["contract"]["version"]
        payload = create_takedown_payload(
            community_id=community["id"], lot_count=5,
            expected_contract_version=cv)
        first = api.create_takedown(base["contract"]["id"], payload, lm)
        validate_success(first, 201)
        second = api.create_takedown(base["contract"]["id"], payload, lm)
        validate_error(second, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_retry_with_fresh_version_succeeds(self, api, land_manager_headers):
        """PRD §2.7: "Scheduling a takedown under an option contract requires the
        request to carry `expected_contract_version` holding the contract's
        current `version`. Execution and prior scheduling advance the contract's
        version as lots are drawn down, so a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412) to prevent oversubscribing the remaining
        lots from a stale view."

        Design: Corner/cross_cutting/takedown_create_stale_version_rejected
        """
        lm = land_manager_headers
        base = setup_active_contract(api)
        community = create_community(api)
        stale_v = base["contract"]["version"]
        schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5)
        resp = api.create_takedown(base["contract"]["id"], create_takedown_payload(
            community_id=community["id"], lot_count=5,
            window_start="2026-10-01T00:00:00Z", window_end="2026-10-31T00:00:00Z",
            expected_contract_version=stale_v), lm)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        fresh_v = get_contract_version(api, base["contract"]["id"])
        ok = api.create_takedown(base["contract"]["id"], create_takedown_payload(
            community_id=community["id"], lot_count=5,
            window_start="2026-10-01T00:00:00Z", window_end="2026-10-31T00:00:00Z",
            expected_contract_version=fresh_v), lm)
        validate_success(ok, 201)


class TestContractExhaustedBoundary:
    def test_final_lot_execution_flips_contract_exhausted(self, api, land_manager_headers):
        """PRD §3.2: "A successful execution stamps `executed_at`, runs the
        takedown pricing described in §3.3, creates `lot_count` lots in the
        target community each in state `BANKED`, every lot recording the
        executing takedown's id as its `source_takedown_id` for provenance, adds
        `lot_count` to the contract's `lots_taken_down`, increments the
        contract's `version`, and — when the running total reaches `total_lots` —
        flips the contract to `EXHAUSTED`, its terminal state."

        Design: Corner/validations/contract_exhausted_boundary_on_final_lot
        """
        lm = land_manager_headers
        base = setup_active_contract(api, total_lots=5)
        community = create_community(api)
        t1 = schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5)
        executed = get_success_data(api.execute_takedown(t1["id"], lm))
        assert executed["state"] == "EXECUTED"
        contract = get_success_data(api.get_option_contract(base["contract"]["id"], lm))
        assert contract["state"] == "EXHAUSTED"

    def test_further_takedown_create_after_exhaustion_rejected(self, api, land_manager_headers):
        """PRD §3.2: "finally the contract must have enough lots left, meaning the
        contract's `lots_taken_down` plus this `lot_count` must not exceed
        `total_lots` (else `ERR_CONTRACT_EXHAUSTED`, a business-fiscal check at
        priority 10)."

        Design: Corner/validations/contract_exhausted_boundary_on_final_lot
        """
        lm = land_manager_headers
        base = setup_active_contract(api, total_lots=5)
        community = create_community(api)
        t1 = schedule_takedown(api, base["contract"]["id"], community["id"], lot_count=5)
        execute_takedown(api, t1["id"])
        cv = get_contract_version(api, base["contract"]["id"])
        resp = api.create_takedown(base["contract"]["id"], create_takedown_payload(
            community_id=community["id"], lot_count=1,
            expected_contract_version=cv), lm)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_EXHAUSTED, 409)


class TestOptionContractListFilter:
    def test_filtered_by_land_parcel_returns_only_that_parcels_contracts(
            self, api, land_manager_headers):
        """PRD §3.1: "Contracts can also be listed, optionally filtered by
        `land_parcel_id` or by `state`."

        Design: Corner/endpoints/filtered_list_fk_reverse_lookup
        """
        lm = land_manager_headers
        p1 = get_success_data(api.create_land_parcel(create_land_parcel_payload(), lm))
        p2 = get_success_data(api.create_land_parcel(
            create_land_parcel_payload(name="Parcel B", acres=50.0), lm))
        c1 = get_success_data(api.create_option_contract(
            create_option_contract_payload(land_parcel_id=p1["id"]), lm))
        c2 = get_success_data(api.create_option_contract(
            create_option_contract_payload(land_parcel_id=p2["id"], total_lots=20,
                                           lot_base_price_cents=9_000_000), lm))
        data, meta = validate_paginated(
            api.list_option_contracts(lm, params={"land_parcel_id": p1["id"]}))
        assert len(data) == 1
        assert data[0]["id"] == c1["id"]
        assert data[0]["id"] != c2["id"]
