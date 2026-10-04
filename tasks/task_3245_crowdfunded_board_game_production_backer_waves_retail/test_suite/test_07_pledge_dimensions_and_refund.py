"""Pledge parallel state dimensions, refund cascade, and address locking."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_pledge,
    charge_pledge,
    confirm_address,
    create_charged_pledge,
    create_pledge,
    create_wave,
    get_campaign,
    make_backer_headers,
    open_wave,
    set_clock,
    setup_campaign_with_cleared_freight,
    setup_delivered_pledge,
    setup_live_campaign,
    setup_open_wave_with_assigned_pledge,
    validate_error,
    validate_success,
)

OWNER = TEST_USERS["campaign_owner_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestParallelStateDimensions:
    def test_pledge_parallel_state_dimensions(self, api):
        """PRD §3.3: "Every pledge is born with `charge_status` `PENDING`,
        `address_status` `UNCONFIRMED`, `fulfillment_status` `QUEUED`".
        PRD §3.7: "Confirming an address moves a pledge's `address_status`
        `UNCONFIRMED → CONFIRMED`".
        PRD §3.3: "Refunding moves a pledge `CHARGED → REFUNDED`."

        Confirming the address leaves charge_status PENDING; a later refund
        leaves address CONFIRMED and fulfillment QUEUED.

        Design: Difficulty/non_linear_state_machine/pledge_parallel_state_dimensions
        """
        campaign = setup_live_campaign()
        pledge = create_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        confirm_address(pledge["id"], "b1")
        mid = validate_success(api.get_pledge(pledge["id"], ADMIN))
        assert mid["charge_status"] == "PENDING"
        assert mid["address_status"] == "CONFIRMED"

        charge_pledge(pledge["id"])
        resp = api.transition_pledge(pledge["id"], {"action": "refund"}, OWNER)
        validate_success(resp)
        final = validate_success(api.get_pledge(pledge["id"], ADMIN))
        assert final["charge_status"] == "REFUNDED"
        assert final["address_status"] == "CONFIRMED"
        assert final["fulfillment_status"] == "QUEUED"

    def test_address_confirm_then_change_reopens(self, api):
        """PRD §3.7: "Changing an address moves `CONFIRMED → UNCONFIRMED`
        under the same ownership rule ... a pledge with no wave assigned may
        always re-open its address."

        Design: Difficulty/non_linear_state_machine/pledge_parallel_state_dimensions
        """
        campaign = setup_live_campaign()
        pledge = create_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        confirm_address(pledge["id"], "b1")
        resp = api.transition_pledge(
            pledge["id"],
            {"action": "change-address"},
            make_backer_headers("b1"),
        )
        data = validate_success(resp)
        assert data["address_status"] == "UNCONFIRMED"
        assert data["charge_status"] == "PENDING"


class TestRefundCascade:
    def test_refund_cascades_wave_assignment_removal(self, api):
        """PRD §3.3: "if the pledge's `assigned_wave_id` is not null, removes
        the assignment from that wave — the wave entry flips to `REMOVED`,
        the wave's `capacity_used` decreases by one, `assigned_wave_id`
        clears to null, and fulfillment returns to `QUEUED`."

        Design: Difficulty/transitive_cascade/refund_cascades_wave_assignment_removal
        """
        bundle = setup_open_wave_with_assigned_pledge()
        wave = bundle["wave"]
        pledge = bundle["pledge"]
        before = validate_success(api.get_wave(wave["id"], ADMIN))
        assert before["capacity_used"] == 1

        resp = api.transition_pledge(pledge["id"], {"action": "refund"}, OWNER)
        validate_success(resp)

        after = validate_success(api.get_wave(wave["id"], ADMIN))
        assert after["capacity_used"] == 0
        statuses = {a["pledge_id"]: a["status"] for a in after["assignments"]}
        assert statuses.get(pledge["id"]) == "REMOVED"

        p = validate_success(api.get_pledge(pledge["id"], ADMIN))
        assert p["charge_status"] == "REFUNDED"
        assert p["fulfillment_status"] == "QUEUED"
        assert p["assigned_wave_id"] is None

    def test_refund_rejected_when_already_shipped(self, api):
        """PRD §3.3: "It requires ... the pledge's fulfillment to be neither
        `SHIPPED` nor `DELIVERED` (otherwise `ERR_ALREADY_SHIPPED`)."

        Design: Corner/errors/err_already_shipped_on_refund
        """
        bundle = setup_open_wave_with_assigned_pledge()
        wave = bundle["wave"]
        pledge = bundle["pledge"]
        set_clock(wave["dispatch_window_start"])
        api.transition_wave(
            wave["id"], {"action": "pick", "pledge_id": pledge["id"]},
            TEST_USERS["fulfillment_operator_headers"],
        )
        api.transition_wave(
            wave["id"], {"action": "ship", "pledge_id": pledge["id"]},
            TEST_USERS["fulfillment_operator_headers"],
        )
        resp = api.transition_pledge(pledge["id"], {"action": "refund"}, OWNER)
        validate_error(resp, ApiErrorId.ERR_ALREADY_SHIPPED)

    def test_refund_of_assigned_pledge_recomputes_campaign_aggregates(self, api):
        """PRD §3.3: "The refund subtracts the pledge's total from
        `gross_charged_cents`, decrements `total_backers_charged`, recomputes
        fees and net payable".

        Design: Difficulty/transitive_cascade/refund_cascades_wave_assignment_removal
        """
        bundle = setup_open_wave_with_assigned_pledge()
        campaign = bundle["campaign"]
        pledge = bundle["pledge"]
        before = get_campaign(campaign["id"])
        resp = api.transition_pledge(pledge["id"], {"action": "refund"}, OWNER)
        validate_success(resp)
        after = get_campaign(campaign["id"])
        assert after["gross_charged_cents"] == (
            before["gross_charged_cents"] - pledge["pledge_total_cents"]
        )
        assert after["total_backers_charged"] == before["total_backers_charged"] - 1
        assert after["version"] == before["version"] + 1


class TestAddressLock:
    def test_scheduled_address_lock_fires_on_clock(self, api):
        """PRD §3.7: "When the logical clock reaches the `address_lock_at`
        of a pledge's assigned wave, a `CONFIRMED` address locks
        automatically — `CONFIRMED → LOCKED` — and the pledge's
        `address_locked_at` records the instant."

        Design: Corner/cross_cutting_layers/scheduled_address_lock_fires_on_clock
        """
        bundle = setup_open_wave_with_assigned_pledge()
        wave = bundle["wave"]
        pledge = bundle["pledge"]
        set_clock(wave["address_lock_at"])
        p = validate_success(api.get_pledge(pledge["id"], ADMIN))
        assert p["address_status"] == "LOCKED"

    def test_business_safety_vs_business_referential_on_change_address(self, api):
        """PRD §2.5: "Earlier checks mask later ones: a request failing an
        earlier check is rejected with that check's error even if it would
        also fail a later check." Item 8 is address-lock enforcement on
        change-address (`ERR_ADDRESS_LOCKED`); item 15 is ownership of the
        acted-upon resource (`ERR_FORBIDDEN`).

        A non-owner attempts change-address after the lock instant; the
        safety check wins.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_change_address
        """
        bundle = setup_open_wave_with_assigned_pledge()
        wave = bundle["wave"]
        pledge = bundle["pledge"]
        set_clock(wave["address_lock_at"])
        resp = api.transition_pledge(
            pledge["id"],
            {"action": "change-address"},
            make_backer_headers("b2"),
        )
        err = validate_error(resp, ApiErrorId.ERR_ADDRESS_LOCKED)
        assert err["error_id"] != ApiErrorId.ERR_FORBIDDEN

    def test_locked_address_rejects_owner_change_too(self, api):
        """PRD §3.7: "if the pledge is assigned to a wave and the logical
        clock has reached that wave's `address_lock_at`, the change is
        rejected with `ERR_ADDRESS_LOCKED`".

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_change_address
        """
        bundle = setup_open_wave_with_assigned_pledge()
        wave = bundle["wave"]
        pledge = bundle["pledge"]
        set_clock(wave["address_lock_at"])
        resp = api.transition_pledge(
            pledge["id"],
            {"action": "change-address"},
            make_backer_headers(pledge["backer_user_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ADDRESS_LOCKED)
