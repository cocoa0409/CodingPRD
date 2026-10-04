"""Circle posture, subscription lifecycle, and the fiscal ledgers."""
from test_helpers import (
    TEST_USERS,
    change_tier_payload,
    create_circle,
    create_place_payload,
    get_circle_state,
    get_success_data,
    invite_and_grant_member,
    invite_member,
    make_member_headers,
    post_fix,
    reset_clock,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    compliance_hold_payload,
)
from test_helpers.api_client import api_client


class TestPostureTransitions:
    def test_business_safety_vs_business_fiscal_on_frozen_circle_fix(self, api, system_headers):
        """PRD §2.6: "while the posture is `FROZEN`, every mutation under the
        circle other than subscription reactivation or compliance-hold
        resolution is rejected with `ERR_CIRCLE_FROZEN`, and location-sharing
        reads to non-`Owner` members are refused with the same code."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_frozen_circle_fix
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="FrozenFam")
        member = invite_and_grant_member(circle, owner_headers, display_name="Nix", email="nix@example.com")
        member_headers = make_member_headers(member["id"])
        validate_success(api.revoke_consent(circle["id"], member["id"], member_headers))
        validate_success(api.simulate_suspend(circle["id"], system_headers))
        assert get_circle_state(circle["id"], owner_headers)["circle_posture"] == "FROZEN"
        resp = api.post_fix(
            circle["id"], member["id"],
            {"recorded_at": "2026-09-01T00:00:30Z", "lat": 37.7, "lng": -122.4,
             "accuracy_m": 20, "speed_mps": 0.0, "battery_pct": 80,
             "phone_in_use": False, "motion_context": "STILL"},
            member_headers,
        )
        validate_error(resp, "ERR_CIRCLE_FROZEN")

    def test_frozen_circle_rejects_member_invite(self, api, system_headers):
        """PRD §2.6: "while the posture is `FROZEN`, every mutation under the
        circle other than subscription reactivation or compliance-hold
        resolution is rejected with `ERR_CIRCLE_FROZEN`, and location-sharing
        reads to non-`Owner` members are refused with the same code."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_frozen_circle_fix
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="FrozenInviteFam")
        validate_success(api.simulate_suspend(circle["id"], system_headers))
        resp = api.invite_member(
            circle["id"],
            {"display_name": "X", "birthdate": "1990-01-01T00:00:00Z", "email": "x@example.com"},
            owner_headers,
        )
        validate_error(resp, "ERR_CIRCLE_FROZEN")

    def test_err_circle_frozen_blocks_member_invite(self, api, system_headers):
        """PRD §2.6: "while the posture is `FROZEN`, every mutation under the
        circle other than subscription reactivation or compliance-hold
        resolution is rejected with `ERR_CIRCLE_FROZEN`, and location-sharing
        reads to non-`Owner` members are refused with the same code."

        Design: Corner/errors/err_circle_frozen_blocks_member_invite
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PLUS", name="FrozenFam2")
        validate_success(api.simulate_suspend(circle["id"], system_headers))
        resp = api.invite_member(
            circle["id"],
            {"display_name": "X2", "birthdate": "1990-01-01T00:00:00Z", "email": "x2@example.com"},
            owner_headers,
        )
        validate_error(resp, "ERR_CIRCLE_FROZEN")

    def test_err_circle_frozen_blocks_place_creation(self, api, system_headers):
        """PRD §2.6: "while the posture is `FROZEN`, every mutation under the
        circle other than subscription reactivation or compliance-hold
        resolution is rejected with `ERR_CIRCLE_FROZEN`, and location-sharing
        reads to non-`Owner` members are refused with the same code."

        Design: Corner/errors/err_circle_frozen_blocks_member_invite
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PLUS", name="FrozenPlaceFam")
        validate_success(api.simulate_suspend(circle["id"], system_headers))
        resp = api.create_place(circle["id"], create_place_payload(label="Late"), owner_headers)
        validate_error(resp, "ERR_CIRCLE_FROZEN")


class TestPlaceAlertPostureGate:
    def test_place_alert_confirmation_requires_circle_open(self, api, system_headers):
        """PRD §3.5: "The candidate is confirmed when a subsequent fix from the
        same member lands inside the same geofence (under the membership rule
        above) and the elapsed dwell — the difference between the candidate's
        `window_close_fix_id` recorded time and the `window_open_fix_id`
        recorded time — is at least the place's `dwell_bucket_seconds`,
        provided the circle's posture is `OPEN` at confirmation time."
        PRD §2.6: "The posture takes the value `RESTRICTED` when the
        subscription is `PAST_DUE` or at least one open compliance hold exists"

        Design: Difficulty/cross_entity_state_dependency/place_alert_confirmation_requires_circle_open
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="AlertFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        place = validate_success(api.create_place(
            circle["id"],
            create_place_payload(label="Home", center_lat=37.7000, center_lng=-122.4000,
                                 radius_m=200, accuracy_floor_m=100, dwell_bucket_seconds=60),
            owner_headers,
        ), 201)
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:00:00Z")
        validate_success(api.simulate_payment_failed(circle["id"], system_headers))
        assert get_circle_state(circle["id"], owner_headers)["circle_posture"] == "RESTRICTED"
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:02:00Z", battery_pct=89)
        data, _meta = validate_paginated(
            api.list_place_alerts(circle["id"], place["id"], owner_headers)
        )
        arrivals = [a for a in data if a["event_kind"] == "ARRIVAL"]
        assert arrivals, "expected an arrival candidate to exist"
        for alert in arrivals:
            assert alert["alert_status"] != "CONFIRMED", (
                "confirmation must be withheld while posture is RESTRICTED"
            )

    def test_place_alert_confirms_normally_while_posture_open(self, api, system_headers):
        """PRD §3.5: "The candidate is confirmed when a subsequent fix from the
        same member lands inside the same geofence (under the membership rule
        above) and the elapsed dwell — the difference between the candidate's
        `window_close_fix_id` recorded time and the `window_open_fix_id`
        recorded time — is at least the place's `dwell_bucket_seconds`,
        provided the circle's posture is `OPEN` at confirmation time."

        Design: Difficulty/cross_entity_state_dependency/place_alert_confirmation_requires_circle_open
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="AlertOpenFam")
        owner_id = circle["owner_member_id"]
        owner = {"id": owner_id}
        place = validate_success(api.create_place(
            circle["id"],
            create_place_payload(label="HomeOk", center_lat=37.7000, center_lng=-122.4000,
                                 radius_m=200, accuracy_floor_m=100, dwell_bucket_seconds=60),
            owner_headers,
        ), 201)
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:00:00Z")
        post_fix(circle, owner, owner_headers, recorded_at="2026-09-01T00:02:00Z", battery_pct=89)
        data, _meta = validate_paginated(
            api.list_place_alerts(circle["id"], place["id"], owner_headers)
        )
        confirmed = [a for a in data if a["alert_status"] == "CONFIRMED"]
        assert confirmed, "posture OPEN and dwell satisfied must confirm the arrival"


class TestComplianceHolds:
    def test_compliance_hold_resolve_clears_restricted_posture(self, api, system_headers):
        """PRD §3.8: "Opening a hold recomputes the circle's posture (typically
        to `RESTRICTED`) and increments the circle's `version`; resolving one
        recomputes posture again and increments `version` again. A circle's
        posture remains `RESTRICTED` until every hold on the circle is
        resolved."
        PRD §3.8: "when resolved it records the `resolved_by_member_id` of the
        `OWNER` who acknowledged it."

        Design: Corner/endpoints/compliance_hold_resolve_clears_restricted_posture
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="HoldFam")
        hold = validate_success(api.open_compliance_hold(
            circle["id"], compliance_hold_payload(), system_headers,
        ), 201)
        assert get_circle_state(circle["id"], owner_headers)["circle_posture"] == "RESTRICTED"
        resolved = validate_success(api.resolve_compliance_hold(
            circle["id"], hold["id"], owner_headers,
        ))
        assert resolved["hold_status"] == "RESOLVED"
        assert resolved["resolved_by_member_id"] == circle["owner_member_id"]
        assert get_circle_state(circle["id"], owner_headers)["circle_posture"] == "OPEN"

    def test_compliance_hold_second_open_hold_keeps_restricted(self, api, system_headers):
        """PRD §3.8: "A circle's posture remains `RESTRICTED` until every hold
        on the circle is resolved."

        Design: Corner/endpoints/compliance_hold_resolve_clears_restricted_posture
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="HoldFam2")
        hold1 = validate_success(api.open_compliance_hold(
            circle["id"],
            compliance_hold_payload(opened_reason="disclosure_version_bump_v2"),
            system_headers,
        ), 201)
        validate_success(api.open_compliance_hold(
            circle["id"],
            compliance_hold_payload(hold_kind="MONETIZATION_OPT_OUT_SWEEP",
                                    opened_reason="opt_out_sweep"),
            system_headers,
        ), 201)
        validate_success(api.resolve_compliance_hold(circle["id"], hold1["id"], owner_headers))
        assert get_circle_state(circle["id"], owner_headers)["circle_posture"] == "RESTRICTED"


class TestSubscriptionOcc:
    def test_stale_version_on_change_tier_rejected(self, api, system_headers):
        """PRD §2.7: "A request to change a circle's subscription tier must
        carry `expected_circle_version` matching the circle's current
        `version`; a request to patch a member's `privacy_mode` must carry
        `expected_member_version` matching the member's current `version`. In
        both cases the field is non-optional. If the supplied value does not
        match the parent's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_version_on_change_tier_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="OccTierFam")
        stale_version = get_circle_state(circle["id"], owner_headers)["version"]
        # An intervening invite bumps the circle's version.
        invite_member(circle, owner_headers, display_name="Bump", email="bump@example.com")
        resp = api.change_tier(
            circle["id"],
            change_tier_payload("PLUS", stale_version),
            owner_headers,
        )
        validate_error(resp, "ERR_STALE_VERSION")

    def test_change_tier_with_current_version_succeeds(self, api, system_headers):
        """PRD §3.1: "An owner may change the circle's tier by naming the
        `to_tier` and presenting the `expected_circle_version` last observed; a
        mismatch against the circle's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412). A successful change appends a
        `SubscriptionEvent` of kind `TIER_CHANGE` recording the `from_tier`,
        the `to_tier`, and the `effective_at` instant, recomputes
        `history_retention_days` for the new tier, sets
        `identity_protection_credits` to 1 if the circle is entering `PROTECT`
        or resets it to 0 if the circle is leaving `PROTECT`, and replenishes
        `assistance_units_balance` only if the tier change happens to cross a
        billing anchor — otherwise the unit balance is unchanged."

        Design: Corner/validations/stale_version_on_change_tier_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="TierOkFam")
        current_version = get_circle_state(circle["id"], owner_headers)["version"]
        updated = validate_success(api.change_tier(
            circle["id"], change_tier_payload("PROTECT", current_version), owner_headers,
        ))
        assert updated["subscription_tier"] == "PROTECT"
        assert updated["history_retention_days"] == 60
        assert updated["identity_protection_credits"] == 1
        # No billing anchor crossed mid-window: FREE's 0 balance is unchanged.
        assert updated["assistance_units_balance"] == 0
        assert updated["version"] == current_version + 1


class TestFiscalLedgers:
    def test_assistance_units_exhausted_on_free_tier(self, api, system_headers):
        """PRD §2.8: "Attempting to consume a unit when the balance is
        exhausted for the tier (0 for `FREE`/`PLUS`, -1 already reached for
        `PROTECT`) is rejected with `ERR_ASSISTANCE_UNITS_EXHAUSTED`
        (HTTP 402)."

        Design: Corner/validations/assistance_units_exhausted_on_free_tier
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="FreeFiscalFam")
        resp = api.consume_roadside_assistance(circle["id"], {"reason": "flat"}, owner_headers)
        validate_error(resp, "ERR_ASSISTANCE_UNITS_EXHAUSTED")
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 0

    def test_identity_credit_zero_on_free_tier(self, api, system_headers):
        """PRD §2.8: "Consumption requires the balance to be strictly positive;
        a request that would drive the balance below zero is rejected with
        `ERR_NO_IDENTITY_CREDIT` (HTTP 402), does not append a
        `SubscriptionEvent`, and leaves the balance unchanged."

        Design: Corner/validations/identity_credit_zero_on_free_tier
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="FreeIdpFam")
        resp = api.consume_identity_protection(circle["id"], {"reason": "alert"}, owner_headers)
        validate_error(resp, "ERR_NO_IDENTITY_CREDIT")
        assert get_circle_state(circle["id"], owner_headers)["identity_protection_credits"] == 0

    def test_identity_credits_conserve_within_billing_window(self, api, system_headers):
        """PRD §2.8: "Consumption requires the balance to be strictly positive;
        a request that would drive the balance below zero is rejected with
        `ERR_NO_IDENTITY_CREDIT` (HTTP 402), does not append a
        `SubscriptionEvent`, and leaves the balance unchanged. Across a single
        billing window the invariant `identity_protection_credits ==
        start_of_window - consumed_this_window` holds at every observable
        point, where `start_of_window` is 1 on `PROTECT` and 0 otherwise and
        `consumed_this_window` counts the `IDENTITY_CREDIT_CONSUME` events
        whose `billing_period_index` matches the current window."

        Design: Difficulty/compensating_invariant/identity_credits_conserve_within_billing_window
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="IdpFam")
        event = validate_success(api.consume_identity_protection(
            circle["id"], {"reason": "dark-web alert"}, owner_headers,
        ), 201)
        assert event["event_kind"] == "IDENTITY_CREDIT_CONSUME"
        assert event["units_delta"] == -1
        assert get_circle_state(circle["id"], owner_headers)["identity_protection_credits"] == 0
        resp = api.consume_identity_protection(
            circle["id"], {"reason": "second alert, no credit"}, owner_headers,
        )
        validate_error(resp, "ERR_NO_IDENTITY_CREDIT")
        assert get_circle_state(circle["id"], owner_headers)["identity_protection_credits"] == 0
        data, meta = validate_paginated(api.list_subscription_events(
            circle["id"], owner_headers, params={"event_kind": "IDENTITY_CREDIT_CONSUME"},
        ))
        assert meta["total_count"] == 1
        assert data[0]["units_delta"] == -1

    def test_identity_credit_rejected_consume_appends_no_event_of_that_kind(self, api, system_headers):
        """PRD §2.8: "a request that would drive the balance below zero is
        rejected with `ERR_NO_IDENTITY_CREDIT` (HTTP 402), does not append a
        `SubscriptionEvent`, and leaves the balance unchanged."

        Design: Difficulty/compensating_invariant/identity_credits_conserve_within_billing_window
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="IdpFam2")
        validate_success(api.consume_identity_protection(
            circle["id"], {"reason": "first"}, owner_headers,
        ), 201)
        data_before, meta_before = validate_paginated(
            api.list_subscription_events(circle["id"], owner_headers)
        )
        resp = api.consume_identity_protection(circle["id"], {"reason": "second"}, owner_headers)
        validate_error(resp, "ERR_NO_IDENTITY_CREDIT")
        data_after, meta_after = validate_paginated(
            api.list_subscription_events(circle["id"], owner_headers)
        )
        assert meta_after["total_count"] == meta_before["total_count"]

    def test_assistance_balance_snapshot_vs_replenished_at_anchor(self, api, system_headers):
        """PRD §2.8: "The `assistance_units_balance` replenishes at each billing
        anchor to a per-window allotment that depends on the tier: 0 units on
        `FREE`, 2 on `PLUS`, and 4 on `PROTECT`."
        PRD §3.9: "Consuming a roadside-assistance unit requires a `reason`,
        consumes 1 from the circle's `assistance_units_balance` (a `PROTECT`
        circle may overdraw to exactly -1 within the current window as a safety
        valve), and appends a `SubscriptionEvent` of kind `ASSISTANCE_CONSUME`
        with `units_delta` -1."

        Design: Difficulty/dual_variant_calc/assistance_balance_snapshot_vs_replenished_at_anchor
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="AnchorFam")
        validate_success(api.consume_roadside_assistance(
            circle["id"], {"reason": "flat tire on I-80"}, owner_headers,
        ), 201)
        pre_anchor = get_circle_state(circle["id"], owner_headers)["assistance_units_balance"]
        assert pre_anchor == 3
        set_clock("2026-10-01T00:00:00Z")
        post_anchor = get_circle_state(circle["id"], owner_headers)["assistance_units_balance"]
        assert post_anchor == 4
        data, meta = validate_paginated(api.list_subscription_events(
            circle["id"], owner_headers, params={"event_kind": "RENEWAL"},
        ))
        assert meta["total_count"] >= 1
        assert any(
            e["billing_period_index"] == 1 and e["units_delta"] == 1 for e in data
        ), f"expected a RENEWAL event with billing_period_index 1 and units_delta +1, got {data}"

    def test_assistance_snapshot_plus_tier_replenishes_to_two(self, api, system_headers):
        """PRD §2.8: "The `assistance_units_balance` replenishes at each billing
        anchor to a per-window allotment that depends on the tier: 0 units on
        `FREE`, 2 on `PLUS`, and 4 on `PROTECT`."

        Design: Difficulty/dual_variant_calc/assistance_balance_snapshot_vs_replenished_at_anchor
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PLUS", name="AnchorPlusFam")
        validate_success(api.consume_roadside_assistance(
            circle["id"], {"reason": "jump start"}, owner_headers,
        ), 201)
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 1
        set_clock("2026-10-01T00:00:00Z")
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 2

    def test_derived_assistance_units_reconciled_after_renewal(self, api, system_headers):
        """PRD §2.8: "The `assistance_units_balance` replenishes at each billing
        anchor to a per-window allotment that depends on the tier: 0 units on
        `FREE`, 2 on `PLUS`, and 4 on `PROTECT`."

        Design: Corner/cross_cutting_complexity_layers/derived_assistance_units_reconciled_after_renewal
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="FreeRenewFam")
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 0
        set_clock("2026-10-01T00:00:00Z")
        assert get_circle_state(circle["id"], owner_headers)["assistance_units_balance"] == 0

    def test_subscription_events_list_filter_by_kind(self, api, system_headers):
        """PRD §3.9: "Consuming a roadside-assistance unit requires a `reason`,
        consumes 1 from the circle's `assistance_units_balance` (a `PROTECT`
        circle may overdraw to exactly -1 within the current window as a safety
        valve), and appends a `SubscriptionEvent` of kind `ASSISTANCE_CONSUME`
        with `units_delta` -1."

        Design: Corner/endpoints/subscription_events_list_filter_by_kind
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="PROTECT", name="LedgerFam")
        validate_success(api.consume_roadside_assistance(
            circle["id"], {"reason": "jump start"}, owner_headers,
        ), 201)
        data, meta = validate_paginated(api.list_subscription_events(
            circle["id"], owner_headers, params={"event_kind": "ASSISTANCE_CONSUME"},
        ))
        assert meta["total_count"] == 1
        assert data[0]["event_kind"] == "ASSISTANCE_CONSUME"
        assert data[0]["units_delta"] == -1
