"""Subscriptions, cost sharing, escalation, and withdrawal: the capacity
gate boundary, the waterfall overrun allocation, tiered withdrawal penalties,
the conserved megawatt pool, dollar conservation with the funding gap, and
optimistic concurrency on the agreement version."""

from test_helpers import (
    ApiErrorId,
    APPLICANT,
    DOE,
    REVIEWER,
    assert_cost_share_agreement,
    assert_subscription,
    create_certified_dca,
    create_cost_share_agreement,
    create_dca,
    create_subscription,
    escalate_payload,
    execute_subscription,
    make_utility_headers,
    read_cost_share_agreement,
    read_dca,
    read_subscription,
    subscription_payload,
    validate_error,
    validate_success,
    withdraw_subscription,
)


def _locked_pair(api, docket_number):
    """A certified DCA with participant share 800 and two LOCKED commitments:
    A (60 MW, share 480) and B (40 MW, share 320)."""
    world = create_certified_dca(
        api,
        subscriptions=(("util-a", 60), ("util-b", 40)),
        csa_total_cost_usd=1000,
        csa_gov_contribution_usd=200,
        docket_number=docket_number,
    )
    subs = {s["utility_id"]: s for s in world["subscriptions"]}
    return world, subs["util-a"], subs["util-b"]


class TestCapacityGateBoundary:
    """committed_mw equal to available_mw is accepted; one more is not."""

    def test_execute_at_exact_capacity_accepted_then_next_rejected(self, api):
        """PRD §3.5: "Execution moves `DRAFT → EXECUTED` and is
        capacity-gated: the commitment's `committed_mw` must not exceed the
        application's current `available_mw`, and the application must be in
        `SUBMITTED`, `SAFETY_REVIEW`, or `ADVANCED_REVIEW`. A commitment that
        would oversubscribe the plant is rejected with `ERR_CAPACITY_EXCEEDED`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/capacity_gate_boundary_exactly_available
        """
        dca = create_dca(api, docket_number="52-600", plant_net_capacity_mw=100)
        exact = create_subscription(api, dca["id"], "u-exact", 100)
        over = create_subscription(api, dca["id"], "u-over", 1)

        executed = execute_subscription(api, exact["id"], "u-exact")
        assert executed["status"] == "EXECUTED"
        # The boundary consumed the whole pool; one more megawatt overflows.
        resp = api.execute_subscription(over["id"], make_utility_headers("u-over"))
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 422)

    def test_execute_one_mw_over_capacity_rejected(self, api):
        """PRD §3.5: "Execution moves `DRAFT → EXECUTED` and is
        capacity-gated: the commitment's `committed_mw` must not exceed the
        application's current `available_mw`, and the application must be in
        `SUBMITTED`, `SAFETY_REVIEW`, or `ADVANCED_REVIEW`. A commitment that
        would oversubscribe the plant is rejected with `ERR_CAPACITY_EXCEEDED`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/capacity_gate_boundary_exactly_available
        """
        dca = create_dca(api, docket_number="52-603", plant_net_capacity_mw=100)
        over = create_subscription(api, dca["id"], "u-over", 101)
        resp = api.execute_subscription(over["id"], make_utility_headers("u-over"))
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 422)


class TestEscalationWaterfall:
    """The overrun waterfall: floor per participant, capacity binds, and the
    funding gap absorbs what nobody can."""

    def test_overrun_allocates_pro_rata_within_capacity(self, api):
        """PRD §3.5: "Each participant's pro-rata share is the overrun
        multiplied by its `committed_mw` and divided by the total committed
        megawatts across the participants being allocated, floored to whole
        dollars. A participant's capacity to absorb is its current
        `withdrawal_reserve_usd` — for a `LOCKED` commitment this reserve may
        already be partially consumed by earlier escalations; the allocation
        is evaluated against the current reserve snapshot, never against the
        original `cost_share_total_usd`."

        Design: Difficulty/combinatorial_formula/escalation_waterfall_multi_input_nested_min
        """
        world, sub_a, sub_b = _locked_pair(api, "52-100")
        csa = world["csa"]
        assert_cost_share_agreement(csa)
        assert csa["participant_share_usd"] == 800
        assert sub_a["cost_share_total_usd"] == 480
        assert sub_b["cost_share_total_usd"] == 320

        csa_after = validate_success(
            api.escalate_cost_share(csa["id"], escalate_payload(100), DOE)
        )
        # floor(100*60/100) = 60 and floor(100*40/100) = 40; both capacities
        # (480, 320) absorb their shares fully.
        assert read_subscription(api, sub_a["id"])["allocated_overrun_usd"] == 60
        assert read_subscription(api, sub_b["id"])["allocated_overrun_usd"] == 40
        assert read_dca(api, world["dca"]["id"])["funding_gap_usd"] == 0
        # allocated_to_participants_usd sums cost_share_total + overrun over
        # all commitments: 800 base + 100 overrun.
        assert csa_after["allocated_to_participants_usd"] == 900

    def test_overrun_beyond_capacity_feeds_funding_gap(self, api):
        """PRD §3.5: "The participant absorbs the smaller of its pro-rata
        share and its capacity: `allocated_overrun_usd` grows by that amount
        and, for an `EXECUTED` commitment, `withdrawal_reserve_usd` shrinks by
        it. When the pro-rata share exceeds capacity, the excess is added to
        the application's `funding_gap_usd`."

        Design: Difficulty/combinatorial_formula/escalation_waterfall_multi_input_nested_min
        """
        world, sub_a, sub_b = _locked_pair(api, "52-101")
        csa = world["csa"]
        validate_success(api.escalate_cost_share(csa["id"], escalate_payload(1000), DOE))
        # Pro-rata 600 > 480 and 400 > 320: each participant absorbs only up
        # to its reserve; the excess (120 + 80) lands in the funding gap.
        assert read_subscription(api, sub_a["id"])["allocated_overrun_usd"] == 480
        assert read_subscription(api, sub_b["id"])["allocated_overrun_usd"] == 320
        assert read_dca(api, world["dca"]["id"])["funding_gap_usd"] == 200


class TestEscalationConservation:
    """The dollar-conservation invariant holds across the gap."""

    def test_conservation_with_gap_term(self, api):
        """PRD §3.5: "After every escalation and after every withdrawal, the
        sum over all of the application's commitments — of any status — of
        `cost_share_total_usd` plus `allocated_overrun_usd` must equal the
        agreement's `participant_share_usd`, reduced by the application's
        `funding_gap_usd` when the gap is positive."

        Design: Difficulty/compensating_invariant/escalation_with_offramp_conserves_dollar_allocation
        """
        world, sub_a, sub_b = _locked_pair(api, "52-801")
        csa = world["csa"]
        validate_success(api.escalate_cost_share(csa["id"], escalate_payload(1000), DOE))

        dca = read_dca(api, world["dca"]["id"])
        assert dca["funding_gap_usd"] == 200
        a = read_subscription(api, sub_a["id"])
        b = read_subscription(api, sub_b["id"])
        total = (
            a["cost_share_total_usd"]
            + a["allocated_overrun_usd"]
            + b["cost_share_total_usd"]
            + b["allocated_overrun_usd"]
        )
        assert total == 1600
        # 1600 == participant_share (800) + allocated overrun (800), and the
        # remaining 200 of the 1000 overrun is exactly the funding gap.
        assert total == csa["participant_share_usd"] + 1000 - dca["funding_gap_usd"]

    def test_conservation_after_partial_escalation_without_gap(self, api):
        """PRD §3.5: "After every escalation and after every withdrawal, the
        sum over all of the application's commitments — of any status — of
        `cost_share_total_usd` plus `allocated_overrun_usd` must equal the
        agreement's `participant_share_usd`, reduced by the application's
        `funding_gap_usd` when the gap is positive."

        Design: Difficulty/compensating_invariant/escalation_with_offramp_conserves_dollar_allocation
        """
        world, sub_a, sub_b = _locked_pair(api, "52-802")
        csa = world["csa"]
        validate_success(api.escalate_cost_share(csa["id"], escalate_payload(400), DOE))

        dca = read_dca(api, world["dca"]["id"])
        assert dca["funding_gap_usd"] == 0
        a = read_subscription(api, sub_a["id"])
        b = read_subscription(api, sub_b["id"])
        total = (
            a["cost_share_total_usd"]
            + a["allocated_overrun_usd"]
            + b["cost_share_total_usd"]
            + b["allocated_overrun_usd"]
        )
        # No gap: the whole 400 overrun is absorbed (240 + 160).
        assert total == csa["participant_share_usd"] + 400


class TestMegawattConservation:
    """Execute then withdraw returns the whole pool."""

    def test_execute_then_withdraw_restores_available_mw(self, api):
        """PRD §3.5: "Withdrawal then recomputes the application's
        `subscribed_mw` and `available_mw`, frees the withdrawing
        participant's allocated share by recomputing the agreement's
        `allocated_to_participants_usd`, and increments the commitment's
        `version`."
        PRD §3.1: "Two computed fields track the subscription position
        continuously: `subscribed_mw` is the sum of `committed_mw` over the
        application's subscription commitments whose status is `EXECUTED` or
        `LOCKED`, and `available_mw` is `plant_net_capacity_mw` minus
        `subscribed_mw`."

        Design: Difficulty/compensating_invariant/subscription_execute_withdraw_conserves_available_mw
        """
        dca = create_dca(api, docket_number="52-800", plant_net_capacity_mw=100)
        csa = create_cost_share_agreement(api, dca["id"], 500, 100)
        sub = create_subscription(api, dca["id"], "u1", 30)
        execute_subscription(api, sub["id"], "u1")

        mid = read_dca(api, dca["id"])
        assert mid["available_mw"] == 70
        assert mid["subscribed_mw"] == 30

        # Executed within the first 30 days of the default clock, so no
        # penalty applies; the pool is restored in full.
        withdrawn = withdraw_subscription(api, sub["id"], "u1", csa["version"])
        assert withdrawn["status"] == "WITHDRAWN"
        end = read_dca(api, dca["id"])
        assert end["available_mw"] == 100
        assert end["subscribed_mw"] == 0

    def test_partial_execute_leaves_exact_headroom(self, api):
        """PRD §3.1: "Two computed fields track the subscription position
        continuously: `subscribed_mw` is the sum of `committed_mw` over the
        application's subscription commitments whose status is `EXECUTED` or
        `LOCKED`, and `available_mw` is `plant_net_capacity_mw` minus
        `subscribed_mw`."

        Design: Difficulty/compensating_invariant/subscription_execute_withdraw_conserves_available_mw
        """
        dca = create_dca(api, docket_number="52-803", plant_net_capacity_mw=100)
        sub = create_subscription(api, dca["id"], "u1", 30)
        execute_subscription(api, sub["id"], "u1")
        mid = read_dca(api, dca["id"])
        assert mid["subscribed_mw"] == 30
        assert mid["available_mw"] == 70
        # A second commitment fits exactly into the remaining headroom.
        sub2 = create_subscription(api, dca["id"], "u2", 70)
        executed = execute_subscription(api, sub2["id"], "u2")
        assert executed["status"] == "EXECUTED"
        assert read_dca(api, dca["id"])["available_mw"] == 0


class TestOccStaleVersion:
    """Withdrawal pins the client's view of the agreement's version."""

    def test_second_withdrawal_with_stale_version_rejected(self, api):
        """PRD §2.6: "If the agreement's version has advanced since that
        observation — for example because another withdrawal or an escalation
        has reallocated the participant pool in the meantime — the withdrawal
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/stale_version_occ_on_withdraw
        """
        dca = create_dca(api, docket_number="52-960", plant_net_capacity_mw=100)
        csa = create_cost_share_agreement(api, dca["id"], 500, 0)
        sub1 = create_subscription(api, dca["id"], "u1", 10)
        sub2 = create_subscription(api, dca["id"], "u2", 10)
        execute_subscription(api, sub1["id"], "u1")
        execute_subscription(api, sub2["id"], "u2")

        observed_version = csa["version"]
        first = withdraw_subscription(api, sub1["id"], "u1", observed_version)
        assert first["status"] == "WITHDRAWN"
        # The first withdrawal advanced the agreement's version; the second
        # withdrawal still carries the stale observation.
        resp = api.withdraw_subscription(
            sub2["id"],
            {"expected_cost_share_agreement_version": observed_version},
            make_utility_headers("u2"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_withdrawal_with_current_version_succeeds(self, api):
        """PRD §2.6: "A subscription-withdrawal request must carry
        `expected_cost_share_agreement_version`, a non-optional field carrying
        the `version` of the parent `CostShareAgreement` as last observed by
        the client."

        Design: Corner/errors/stale_version_occ_on_withdraw
        """
        dca = create_dca(api, docket_number="52-961", plant_net_capacity_mw=100)
        csa = create_cost_share_agreement(api, dca["id"], 500, 0)
        sub1 = create_subscription(api, dca["id"], "u1", 10)
        sub2 = create_subscription(api, dca["id"], "u2", 10)
        execute_subscription(api, sub1["id"], "u1")
        execute_subscription(api, sub2["id"], "u2")

        withdraw_subscription(api, sub1["id"], "u1", csa["version"])
        # Re-reading the agreement yields the advanced version; the second
        # withdrawal against the fresh version succeeds.
        fresh = read_cost_share_agreement(api, csa["id"])
        assert fresh["version"] != csa["version"]
        second = withdraw_subscription(api, sub2["id"], "u2", fresh["version"])
        assert second["status"] == "WITHDRAWN"
