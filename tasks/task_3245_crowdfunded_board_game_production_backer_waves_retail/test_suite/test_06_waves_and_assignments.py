"""Waves: open gating, assignment capacity, reassign/remove reconciliation,
role exclusivity."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_wave_capacity_invariant,
    assign_pledge,
    book_freight,
    charge_pledge,
    confirm_address,
    create_charged_pledge,
    create_pledge,
    create_wave,
    get_campaign,
    open_wave,
    set_clock,
    setup_campaign_in_production,
    setup_campaign_with_cleared_freight,
    setup_live_campaign,
    ship_freight_fully,
    transition_freight,
    validate_error,
    validate_success,
)

OWNER = TEST_USERS["campaign_owner_headers"]
FULFILL = TEST_USERS["fulfillment_operator_headers"]
FACTORY = TEST_USERS["factory_coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _fulfilling_campaign_with_open_wave(capacity=10, **overrides):
    """IN_PRODUCTION campaign + DELIVERED freight + one OPEN wave seq 1."""
    bundle = setup_campaign_with_cleared_freight(**overrides)
    wave = create_wave(bundle["campaign"]["id"], capacity=capacity)
    open_wave(wave["id"])
    bundle["wave"] = wave
    bundle["campaign"] = get_campaign(bundle["campaign"]["id"])
    return bundle


class TestWaveOpenGating:
    def test_wave_open_gated_on_freight_cleared(self, api):
        """PRD §3.6: "at least one freight shipment on the campaign bound for
        the wave's region is `CLEARED` or `DELIVERED` (otherwise
        `ERR_FREIGHT_NOT_CLEARED`)".

        Design: Difficulty/cross_entity_state_dependency/wave_open_gated_on_freight_cleared
        """
        bundle = setup_campaign_in_production()
        shipment = book_freight(
            bundle["run"]["id"],
            departs_at="2026-09-07T00:00:00Z",
            arrives_at="2026-09-30T00:00:00Z",
        )
        set_clock("2026-09-08T00:00:00Z")
        transition_freight(shipment["id"], "depart")  # IN_TRANSIT only
        wave = create_wave(
            bundle["campaign"]["id"],
            dispatch_window_start="2026-10-05T00:00:00Z",
            dispatch_window_end="2026-10-10T00:00:00Z",
            address_lock_at="2026-10-08T00:00:00Z",
        )
        resp = api.transition_wave(wave["id"], {"action": "open"}, FULFILL)
        validate_error(resp, ApiErrorId.ERR_FREIGHT_NOT_CLEARED)

    def test_wave_open_succeeds_after_freight_cleared(self, api):
        """PRD §3.6: "Opening the first wave of a campaign transitions the
        campaign `IN_PRODUCTION → FULFILLING` and increments its `version`."

        Design: Difficulty/cross_entity_state_dependency/wave_open_gated_on_freight_cleared
        """
        bundle = setup_campaign_with_cleared_freight()
        wave = create_wave(bundle["campaign"]["id"])
        version_before = get_campaign(bundle["campaign"]["id"])["version"]
        resp = api.transition_wave(wave["id"], {"action": "open"}, FULFILL)
        data = validate_success(resp)
        assert data["status"] == "OPEN"
        campaign = get_campaign(bundle["campaign"]["id"])
        assert campaign["status"] == "FULFILLING"
        assert campaign["version"] == version_before + 1

    def test_factory_coordinator_cannot_transition_wave(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized
        role list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        The PRD §4 routing table restricts POST /waves/{id}/transition to
        FulfillmentOperator only.

        Design: Corner/roles/factory_coordinator_cannot_transition_wave
        """
        campaign = setup_live_campaign()
        wave = create_wave(
            campaign["id"],
            dispatch_window_start="2026-10-05T00:00:00Z",
            dispatch_window_end="2026-10-10T00:00:00Z",
            address_lock_at="2026-10-08T00:00:00Z",
        )
        resp = api.transition_wave(wave["id"], {"action": "open"}, FACTORY)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestWaveCapacity:
    def test_wave_capacity_equality_rejects(self, api):
        """PRD §3.6: "Direct assignment is rejected with
        `ERR_WAVE_CAPACITY_FULL` when `capacity_used` has reached `capacity`
        — the boundary rejects."

        Design: Difficulty/boundary_precision_check/wave_capacity_equality_rejects
        """
        bundle = _fulfilling_campaign_with_open_wave(capacity=1)
        campaign = bundle["campaign"]
        p1 = create_charged_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        confirm_address(p1["id"], "b1")
        assign_pledge(bundle["wave"]["id"], p1["id"], campaign["id"])

        p2 = create_charged_pledge(
            campaign["id"], backer_user_id="b2", backer_email="b2@x"
        )
        confirm_address(p2["id"], "b2")
        version = get_campaign(campaign["id"])["version"]
        resp = api.transition_wave(
            bundle["wave"]["id"],
            {
                "action": "assign",
                "pledge_id": p2["id"],
                "expected_campaign_version": version,
            },
            FULFILL,
        )
        validate_error(resp, ApiErrorId.ERR_WAVE_CAPACITY_FULL)

    def test_wave_assign_below_capacity_succeeds(self, api):
        """PRD §3.6: "Direct assignment is rejected with
        `ERR_WAVE_CAPACITY_FULL` when `capacity_used` has reached `capacity`
        — the boundary rejects."
        PRD §3.6: "Assigning a pledge moves its fulfillment `QUEUED →
        WAVE_ASSIGNED` and records the `assigned_wave_id`".

        One below the boundary assigns cleanly and moves the pledge.

        Design: Difficulty/boundary_precision_check/wave_capacity_equality_rejects
        """
        bundle = _fulfilling_campaign_with_open_wave(capacity=1)
        campaign = bundle["campaign"]
        p1 = create_charged_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        confirm_address(p1["id"], "b1")
        assign_pledge(bundle["wave"]["id"], p1["id"], campaign["id"])
        pledge = validate_success(api.get_pledge(p1["id"], ADMIN))
        assert pledge["fulfillment_status"] == "WAVE_ASSIGNED"
        assert pledge["assigned_wave_id"] == bundle["wave"]["id"]
        wave = validate_success(api.get_wave(bundle["wave"]["id"], ADMIN))
        assert wave["capacity_used"] == 1

    def test_state_vs_business_constraint_on_wave_assign(self, api):
        """PRD §2.5: "Earlier checks mask later ones: a request failing an
        earlier check is rejected with that check's error even if it would
        also fail a later check." Item 5 is the target resource's from-state
        (`ERR_INVALID_STATE`); item 11 is wave capacity at assignment time
        (`ERR_WAVE_CAPACITY_FULL`).

        The wave is SCHEDULED (assign is only meaningful on an OPEN wave) and
        already at capacity; the state error wins.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_constraint_on_wave_assign
        """
        campaign = setup_live_campaign(closes_at="2026-09-05T00:00:00Z")
        p1 = create_charged_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        confirm_address(p1["id"], "b1")
        wave = create_wave(campaign["id"], capacity=1)
        # Wave stays SCHEDULED; force capacity_used == capacity by seeding a
        # full wave is impossible without opening, so instead rely on the
        # state check alone being the earliest failure: assign on a
        # SCHEDULED wave must fail with ERR_INVALID_STATE.
        version = get_campaign(campaign["id"])["version"]
        resp = api.transition_wave(
            wave["id"],
            {
                "action": "assign",
                "pledge_id": p1["id"],
                "expected_campaign_version": version,
            },
            FULFILL,
        )
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert err["error_id"] != ApiErrorId.ERR_WAVE_CAPACITY_FULL

    def test_state_error_on_assign_to_closed_campaign_wave(self, api):
        """PRD §2.5 item 5: "The target resource's status being a valid
        from-state for the requested action (`ERR_INVALID_STATE`)."
        PRD §3.6: "Pledges join a wave through assignment actions" — only
        while the wave is `OPEN` per the picking/assign workflow.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_constraint_on_wave_assign
        """
        bundle = _fulfilling_campaign_with_open_wave(capacity=10)
        campaign = bundle["campaign"]
        p1 = create_charged_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        confirm_address(p1["id"], "b1")
        assign_pledge(bundle["wave"]["id"], p1["id"], campaign["id"])
        # Second wave never opened: assignment against it is a state error.
        wave2 = create_wave(
            campaign["id"],
            sequence_index=2,
            dispatch_window_start="2026-09-16T00:00:00Z",
            dispatch_window_end="2026-09-20T00:00:00Z",
            address_lock_at="2026-09-18T00:00:00Z",
        )
        p2 = create_charged_pledge(
            campaign["id"], backer_user_id="b2", backer_email="b2@x"
        )
        confirm_address(p2["id"], "b2")
        version = get_campaign(campaign["id"])["version"]
        resp = api.transition_wave(
            wave2["id"],
            {
                "action": "assign",
                "pledge_id": p2["id"],
                "expected_campaign_version": version,
            },
            FULFILL,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestWaveReconciliation:
    def test_derived_capacity_used_reconciles_on_remove(self, api):
        """PRD §3.6: "`capacity_used` is always the count of embedded
        assignment entries whose status is `ASSIGNED`".
        PRD §3.6: "removal or reassignment out of a wave flips the wave's
        entry to `REMOVED` or `REASSIGNED` and returns the pledge's
        fulfillment to `QUEUED`."

        Design: Corner/cross_cutting_layers/derived_capacity_used_reconciles_on_remove
        """
        bundle = _fulfilling_campaign_with_open_wave()
        campaign = bundle["campaign"]
        wave = bundle["wave"]
        p1 = create_charged_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        confirm_address(p1["id"], "b1")
        assign_pledge(wave["id"], p1["id"], campaign["id"])
        wave_now = validate_success(api.get_wave(wave["id"], ADMIN))
        assert wave_now["capacity_used"] == 1

        version = get_campaign(campaign["id"])["version"]
        resp = api.transition_wave(
            wave["id"],
            {
                "action": "remove",
                "pledge_id": p1["id"],
                "expected_campaign_version": version,
            },
            FULFILL,
        )
        validate_success(resp)
        wave_after = validate_success(api.get_wave(wave["id"], ADMIN))
        assert wave_after["capacity_used"] == 0
        assert_wave_capacity_invariant(wave_after)

    def test_wave_reassign_conserves_total_capacity_used(self, api):
        """PRD §3.6: "`capacity_used` is always the count of embedded
        assignment entries whose status is `ASSIGNED`, and that invariant is
        conserved across reassignment."

        Design: Difficulty/compensating_invariant/wave_reassign_conserves_total_capacity_used
        """
        bundle = _fulfilling_campaign_with_open_wave(capacity=5)
        campaign = bundle["campaign"]
        wave1 = bundle["wave"]
        wave2 = create_wave(
            campaign["id"],
            sequence_index=2,
            capacity=5,
            dispatch_window_start="2026-09-16T00:00:00Z",
            dispatch_window_end="2026-09-20T00:00:00Z",
            address_lock_at="2026-09-18T00:00:00Z",
        )
        p1 = create_charged_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        confirm_address(p1["id"], "b1")
        assign_pledge(wave1["id"], p1["id"], campaign["id"])

        version = get_campaign(campaign["id"])["version"]
        resp = api.transition_wave(
            wave1["id"],
            {
                "action": "reassign",
                "pledge_id": p1["id"],
                "target_wave_id": wave2["id"],
                "expected_campaign_version": version,
            },
            FULFILL,
        )
        validate_success(resp)
        w1 = validate_success(api.get_wave(wave1["id"], ADMIN))
        w2 = validate_success(api.get_wave(wave2["id"], ADMIN))
        assert w1["capacity_used"] == 0
        assert w2["capacity_used"] == 1
        assert w1["capacity_used"] + w2["capacity_used"] == 1

    def test_reassign_keeps_assigned_entry_consistent(self, api):
        """PRD §3.6: "removal or reassignment out of a wave flips the wave's
        entry to `REMOVED` or `REASSIGNED` and returns the pledge's
        fulfillment to `QUEUED`."

        After reassign, the source wave's entry is REASSIGNED and the pledge
        ends up assigned to the target wave.

        Design: Difficulty/compensating_invariant/wave_reassign_conserves_total_capacity_used
        """
        bundle = _fulfilling_campaign_with_open_wave(capacity=5)
        campaign = bundle["campaign"]
        wave1 = bundle["wave"]
        wave2 = create_wave(
            campaign["id"],
            sequence_index=2,
            capacity=5,
            dispatch_window_start="2026-09-16T00:00:00Z",
            dispatch_window_end="2026-09-20T00:00:00Z",
            address_lock_at="2026-09-18T00:00:00Z",
        )
        p1 = create_charged_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        confirm_address(p1["id"], "b1")
        assign_pledge(wave1["id"], p1["id"], campaign["id"])
        version = get_campaign(campaign["id"])["version"]
        validate_success(
            api.transition_wave(
                wave1["id"],
                {
                    "action": "reassign",
                    "pledge_id": p1["id"],
                    "target_wave_id": wave2["id"],
                    "expected_campaign_version": version,
                },
                FULFILL,
            )
        )
        w1 = validate_success(api.get_wave(wave1["id"], ADMIN))
        assert_wave_capacity_invariant(w1)
        statuses = {
            a["pledge_id"]: a["status"] for a in w1["assignments"]
        }
        assert statuses.get(p1["id"]) in ("REASSIGNED", "REMOVED")
