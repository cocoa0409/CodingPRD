"""Commitments, overage pricing, OCC on commitment create, and the
ACTIVE -> EXHAUSTED -> ACTIVE cycle (PRD §2.8, §2.9, §3.4)."""
from test_helpers import (
    ApiErrorId,
    create_account,
    create_commitment_payload,
    create_plan_tier_config,
    get_meter_accumulator,
    post_usage,
    set_clock,
    setup_account_with_period,
    setup_commitment_with_consumption,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BA, close_period, create_active_commitment


class TestCommitmentCreateOcc:
    def test_stale_expected_version_rejected(self, api):
        """PRD §2.8: "Creating a `Commitment` requires the request to carry
        `expected_billing_account_version`, the `version` of the parent
        `BillingAccount` the client last observed. If the account's current
        `version` no longer matches — because another writer advanced it since the
        read — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.8: "Both creations, on success, increment the parent
        `BillingAccount`'s `version` by 1."

        Design: Corner/validations/occ_stale_version_on_commitment_create
        """
        set_clock()
        create_plan_tier_config()
        account = create_account(name="OCC")
        first = validate_success(
            api.create_commitment(
                account["id"],
                create_commitment_payload(account["version"], meter="INFRA_HOST",
                                          committed_quantity=5),
                BA,
            ),
            expected_status=201,
        )
        assert first["status"] == "DRAFT"
        # The first create bumped account.version, so the captured version is stale.
        resp = api.create_commitment(
            account["id"],
            create_commitment_payload(account["version"], meter="LOG_INDEX",
                                      committed_quantity=5,
                                      committed_unit_rate_cents=1,
                                      overage_unit_rate_cents=5),
            BA,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    def test_current_expected_version_accepted(self, api):
        """PRD §2.8: "Creating a `Commitment` requires the request to carry
        `expected_billing_account_version`, the `version` of the parent
        `BillingAccount` the client last observed."

        Design: Corner/validations/occ_stale_version_on_commitment_create
        """
        set_clock()
        create_plan_tier_config()
        account = create_account(name="OCC-ok")
        created = validate_success(
            api.create_commitment(
                account["id"],
                create_commitment_payload(account["version"], committed_quantity=5),
                BA,
            ),
            expected_status=201,
        )
        assert created["status"] == "DRAFT"
        refreshed = validate_success(api.get_billing_account(account["id"], BA))
        assert refreshed["version"] == account["version"] + 1


class TestCommitmentWindowOverlap:
    def test_touching_endpoints_overlap(self, api):
        """PRD §2.9: "A `Commitment`'s window is **closed on both ends**: it covers
        instants from `window_start_utc` through `window_end_utc` inclusive. Two
        commitments for the same account and the same meter whose closed intervals
        share any instant — including touching at a single endpoint — are rejected
        with `ERR_COMMITMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/commitment_window_closed_interval_overlap
        """
        set_clock()
        create_plan_tier_config()
        account = create_account(name="Overlap Closed")
        validate_success(
            api.create_commitment(
                account["id"],
                create_commitment_payload(account["version"], committed_quantity=5),
                BA,
            ),
            expected_status=201,
        )
        resp = api.create_commitment(
            account["id"],
            create_commitment_payload(
                account["version"] + 1,
                committed_quantity=5,
                window_start_utc="2026-09-30T23:59:59Z",
                window_end_utc="2026-10-31T23:59:59Z",
            ),
            BA,
        )
        validate_error(resp, ApiErrorId.ERR_COMMITMENT_WINDOW_OVERLAP.value)

    def test_non_overlapping_windows_accepted(self, api):
        """PRD §2.9: "Two commitments for the same account and the same meter whose
        closed intervals share any instant — including touching at a single endpoint
        — are rejected with `ERR_COMMITMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/commitment_window_closed_interval_overlap
        """
        set_clock()
        create_plan_tier_config()
        account = create_account(name="Overlap OK")
        validate_success(
            api.create_commitment(
                account["id"],
                create_commitment_payload(account["version"], committed_quantity=5),
                BA,
            ),
            expected_status=201,
        )
        # Starts one second AFTER the first window's inclusive end: no shared
        # instant, so the closed-interval rule admits it.
        created = validate_success(
            api.create_commitment(
                account["id"],
                create_commitment_payload(
                    account["version"] + 1,
                    committed_quantity=5,
                    window_start_utc="2026-10-01T00:00:00Z",
                    window_end_utc="2026-10-31T23:59:59Z",
                ),
                BA,
            ),
            expected_status=201,
        )
        assert created["status"] == "DRAFT"

    def test_overlapping_window_rejected_with_account_still_good(self, api):
        """PRD §3.4: "Creation additionally enforces two guards, in pipeline order
        (§2.5): the account's `standing` must be `GOOD` (otherwise
        `ERR_ACCOUNT_DELINQUENT`), and the closed window from `window_start_utc`
        through `window_end_utc` must not share any instant with another commitment
        on the same account and meter (otherwise `ERR_COMMITMENT_WINDOW_OVERLAP`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_commitment_create
        """
        set_clock()
        create_plan_tier_config()
        account = create_account(name="Conflict A")
        validate_success(
            api.create_commitment(
                account["id"],
                create_commitment_payload(account["version"], committed_quantity=5),
                BA,
            ),
            expected_status=201,
        )
        # Account standing is GOOD; only the window-overlap guard can fire.
        resp = api.create_commitment(
            account["id"],
            create_commitment_payload(
                account["version"] + 1,
                committed_quantity=5,
                window_start_utc="2026-09-15T00:00:00Z",
                window_end_utc="2026-10-15T23:59:59Z",
            ),
            BA,
        )
        validate_error(resp, ApiErrorId.ERR_COMMITMENT_WINDOW_OVERLAP.value)

    def test_overlap_scoped_to_same_meter(self, api):
        """PRD §2.9: "Two commitments for the same account and the same meter whose
        closed intervals share any instant — including touching at a single endpoint
        — are rejected with `ERR_COMMITMENT_WINDOW_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_commitment_create
        """
        set_clock()
        create_plan_tier_config()
        account = create_account(name="Conflict B")
        validate_success(
            api.create_commitment(
                account["id"],
                create_commitment_payload(account["version"], committed_quantity=5),
                BA,
            ),
            expected_status=201,
        )
        # Same window but a DIFFERENT meter: the overlap rule is per account+meter.
        created = validate_success(
            api.create_commitment(
                account["id"],
                create_commitment_payload(
                    account["version"] + 1, meter="LOG_INDEX", committed_quantity=5,
                    committed_unit_rate_cents=1, overage_unit_rate_cents=5,
                ),
                BA,
            ),
            expected_status=201,
        )
        assert created["meter"] == "LOG_INDEX"


class TestActivationAndStanding:
    def test_activate_succeeds_when_account_good(self, api):
        """PRD §3.4: "Activation repeats the two guards — the account must still be
        in `GOOD` standing, and the no-overlap rule is re-evaluated against the
        commitment's closed window — and moves the commitment to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/commitment_activate_requires_account_good_standing
        """
        set_clock()
        create_plan_tier_config()
        account = create_account(name="Standing Test")
        commitment = validate_success(
            api.create_commitment(
                account["id"],
                create_commitment_payload(account["version"], committed_quantity=5),
                BA,
            ),
            expected_status=201,
        )
        # The account was created with standing GOOD (PRD §3.1) and nothing has
        # changed it, so activation succeeds.
        activated = validate_success(
            api.activate_commitment(account["id"], commitment["id"], BA)
        )
        assert activated["status"] == "ACTIVE"

    def test_activate_rejects_non_draft_commitment(self, api):
        """PRD §2.5: "Entity state preconditions. The action-specific state machine
        precondition must hold (for example, commitment activation requires the
        commitment to be `DRAFT` ...) — otherwise `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/commitment_activate_requires_account_good_standing
        """
        account, period = setup_account_with_period(name="Activate Twice")
        commitment, account = create_active_commitment(
            account["id"], committed_quantity=5
        )
        assert commitment["status"] == "ACTIVE"
        resp = api.activate_commitment(account["id"], commitment["id"], BA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestOverageSplit:
    def test_straddling_quantity_splits_committed_and_overage(self, api):
        """PRD §3.4: "When a meter's quantity updates, the charge for the new
        quantity is split before rating: the committed portion is the smaller of the
        new quantity and the commitment's remaining headroom (its
        `committed_quantity` minus its `consumed_quantity`, floored at zero), the
        overage portion is whatever of the new quantity exceeds the committed
        portion (floored at zero)".
        PRD §3.4: "Every meter accumulator in the period carries three reconciling
        quantities: the cumulative `quantity` metered, the
        `committed_consumed_quantity` debited against an active commitment, and the
        `on_demand_quantity`, which is always the `quantity` minus the
        `committed_consumed_quantity`."

        Design: Difficulty/combinatorial_formula/overage_charge_three_input_tiered_selection
        """
        account, period, commitment = setup_commitment_with_consumption(
            name="Overage Test", meter="INFRA_HOST", committed_quantity=10,
            committed_rate=100, overage_rate=500, consume=8,
        )
        assert commitment["consumed_quantity"] == 8
        # Trigger: a 5-unit record straddles the 2 units of remaining headroom.
        post_usage(account["id"], period["id"], "INFRA_HOST", 5)

        acc = get_meter_accumulator(account["id"], period["id"], "INFRA_HOST")
        assert acc["quantity"] == 13
        assert acc["committed_consumed_quantity"] == 10
        assert acc["on_demand_quantity"] == 3

        commitment = validate_success(
            api.get_commitment_flat(commitment["id"], BA)
        )
        assert commitment["consumed_quantity"] == 10
        assert commitment["status"] == "EXHAUSTED"

    def test_overage_portion_billed_after_exhaustion(self, api):
        """PRD §3.4: "When `consumed_quantity` reaches `committed_quantity`, the
        commitment transitions automatically from `ACTIVE` to `EXHAUSTED`, and
        subsequent usage on the meter routes entirely to on-demand pricing."

        Design: Difficulty/combinatorial_formula/overage_charge_three_input_tiered_selection
        """
        account, period, commitment = setup_commitment_with_consumption(
            name="Post Exhaust", meter="TRACE", committed_quantity=4,
            committed_rate=100, overage_rate=500, consume=4,
        )
        commitment = validate_success(
            api.get_commitment_flat(commitment["id"], BA)
        )
        assert commitment["status"] == "EXHAUSTED"
        # Usage after exhaustion routes entirely to on-demand.
        post_usage(account["id"], period["id"], "TRACE", 3)
        acc = get_meter_accumulator(account["id"], period["id"], "TRACE")
        assert acc["quantity"] == 7
        assert acc["committed_consumed_quantity"] == 4
        assert acc["on_demand_quantity"] == 3


class TestTopUpCycle:
    def test_exhausted_to_active_on_top_up(self, api):
        """PRD §3.4: "Exhaustion is not final: while the logical clock has not yet
        passed the `window_end_utc`, a `BillingAdmin` may top the commitment up,
        supplying a `top_up_quantity` that is added to `committed_quantity` and
        returning the commitment to `ACTIVE` so consumption resumes against it."

        Design: Difficulty/non_linear_state_machine/commitment_exhausted_top_up_cycle
        """
        account, period, commitment = setup_commitment_with_consumption(
            name="Commitment Cycle", meter="INFRA_HOST", committed_quantity=10,
            committed_rate=100, overage_rate=500, consume=10,
        )
        commitment = validate_success(
            api.get_commitment_flat(commitment["id"], BA)
        )
        assert commitment["status"] == "EXHAUSTED"

        topped = validate_success(
            api.top_up_commitment(account["id"], commitment["id"],
                                  {"top_up_quantity": 5}, BA)
        )
        assert topped["status"] == "ACTIVE"
        assert topped["committed_quantity"] == 15
        assert topped["consumed_quantity"] == 10

    def test_consumption_resumes_after_top_up(self, api):
        """PRD §3.4: "supplying a `top_up_quantity` that is added to
        `committed_quantity` and returning the commitment to `ACTIVE` so consumption
        resumes against it."

        Design: Difficulty/non_linear_state_machine/commitment_exhausted_top_up_cycle
        """
        account, period, commitment = setup_commitment_with_consumption(
            name="TopUp Resume", meter="TRACE", committed_quantity=5,
            committed_rate=100, overage_rate=500, consume=5,
        )
        validate_success(
            api.top_up_commitment(account["id"], commitment["id"],
                                  {"top_up_quantity": 5}, BA)
        )
        post_usage(account["id"], period["id"], "TRACE", 2)
        commitment = validate_success(
            api.get_commitment_flat(commitment["id"], BA)
        )
        assert commitment["status"] == "ACTIVE"
        assert commitment["consumed_quantity"] == 7
        assert commitment["committed_quantity"] == 10
        acc = get_meter_accumulator(account["id"], period["id"], "TRACE")
        assert acc["committed_consumed_quantity"] == 7
        assert acc["on_demand_quantity"] == 0


class TestCommitmentSettlement:
    def test_consumed_plus_expired_equals_committed_after_close(self, api):
        """PRD §3.4: "When the parent billing period closes and the commitment's
        window has elapsed, an `ACTIVE` commitment moves to `SETTLED` and its
        `expired_quantity` is set to the unused remainder — its `committed_quantity`
        minus its `consumed_quantity`."
        PRD §3.9: "every commitment under the account whose window has elapsed
        settles per §3.4, converting unconsumed quantity into `expired_quantity`."

        Design: Difficulty/compensating_invariant/commitment_quantity_conservation_across_topup
        """
        account, period = setup_account_with_period(name="Invariant Commit")
        commitment, account = create_active_commitment(
            account["id"], meter="LOG_INDEX", committed_quantity=10,
            committed_rate=1, overage_rate=5,
        )
        post_usage(account["id"], period["id"], "LOG_INDEX", 10)
        commitment = validate_success(api.get_commitment_flat(commitment["id"], BA))
        assert commitment["status"] == "EXHAUSTED"
        validate_success(
            api.top_up_commitment(account["id"], commitment["id"],
                                  {"top_up_quantity": 5}, BA)
        )
        post_usage(account["id"], period["id"], "LOG_INDEX", 3)

        close_period(account["id"], period["id"])
        commitment = validate_success(api.get_commitment_flat(commitment["id"], BA))
        assert commitment["status"] == "SETTLED"
        assert commitment["consumed_quantity"] == 13
        assert commitment["committed_quantity"] == 15
        assert commitment["expired_quantity"] == 2
        assert commitment["consumed_quantity"] + commitment["expired_quantity"] == (
            commitment["committed_quantity"]
        )

    def test_exhausted_commitment_settles_with_zero_expired(self, api):
        """PRD §3.4: "An `EXHAUSTED` commitment settling at period close records an
        `expired_quantity` of 0. `SETTLED` is terminal."

        Design: Difficulty/compensating_invariant/commitment_quantity_conservation_across_topup
        """
        account, period, commitment = setup_commitment_with_consumption(
            name="Exhausted Settle", meter="SYNTHETIC", committed_quantity=6,
            committed_rate=1, overage_rate=5, consume=6,
        )
        commitment = validate_success(api.get_commitment_flat(commitment["id"], BA))
        assert commitment["status"] == "EXHAUSTED"
        close_period(account["id"], period["id"])
        commitment = validate_success(api.get_commitment_flat(commitment["id"], BA))
        assert commitment["status"] == "SETTLED"
        assert commitment["expired_quantity"] == 0
        assert commitment["consumed_quantity"] == 6
