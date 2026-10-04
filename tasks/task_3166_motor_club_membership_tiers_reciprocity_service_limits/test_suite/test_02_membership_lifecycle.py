"""Membership lifecycle corner + difficulty coverage: terminal lockdown,
invalid transitions, grace/lapse clock sweeps, the lapse-reinstate cycle,
cancel cascades, and validation-priority pairs (PRD §2.4, §2.8, §3.3)."""
from test_helpers import (
    ApiErrorId,
    complete_dispatch,
    create_ancillary_product,
    create_ancillary_sale,
    create_and_complete_call,
    get_membership,
    get_success_data,
    set_clock,
    setup_dispatchable_scenario,
    setup_membership_scenario,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestMembershipTerminalLockdown:
    def test_renew_from_cancelled_rejected(self, api, member_services_rep_headers):
        """PRD §3.3: "`CANCELLED` terminal." PRD §3.3: "Renewal from any other
        state is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/membership_terminal_cancelled_lockdown
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        m = base["membership"]
        validate_success(api.cancel_membership(m["id"], member_services_rep_headers))
        resp = api.renew_membership(m["id"], member_services_rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_upgrade_from_cancelled_rejected(self, api, member_services_rep_headers):
        """PRD §3.3: "`CANCELLED` terminal." PRD §2.8 step 6: "the target
        resource is in a state that permits the operation ... Violations return
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/membership_terminal_cancelled_lockdown
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False, tiers=["CLASSIC", "PLUS"])
        m = base["membership"]
        validate_success(api.cancel_membership(m["id"], member_services_rep_headers))
        resp = api.upgrade_membership(
            m["id"], {"target_tier_code": "PLUS", "expected_membership_version": m["version"] + 1},
            member_services_rep_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestInvalidLifecycleTransitions:
    def test_renew_from_active_rejected(self, api, member_services_rep_headers):
        """PRD §3.3: "Renewal from any other state is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/renew_from_active_rejected
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        resp = api.renew_membership(base["membership"]["id"], member_services_rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_reinstate_from_active_rejected(self, api, member_services_rep_headers):
        """PRD §3.3: "A `LAPSED` membership can be brought back within ninety
        days of `lapse_at`" — reinstatement presupposes LAPSED. PRD §2.8 step 6:
        "reinstate only from `LAPSED` ... Violations return `ERR_INVALID_STATE`."

        Design: Corner/state_machines/reinstate_from_active_rejected
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        resp = api.reinstate_membership(base["membership"]["id"], {"dues_paid": True}, member_services_rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestGraceAndRenewViaClock:
    def test_grace_entry_and_renew_rolls_term_and_resets_counter(self, api, member_services_rep_headers):
        """PRD §2.4: "Any `ACTIVE` membership whose `term_end_date` now lies in
        the past transitions to `GRACE` (a thirty-day grace window opens)."
        PRD §3.3: "it rolls the term forward: the new `term_start_date` is the
        old `term_end_date`, the new `term_end_date` falls exactly 365 days after
        that, `calls_used_current_term` resets to 0, and a `RENEWAL` event is
        appended."

        Design: Corner/state_machines/grace_entry_and_renew_via_clock
        """
        base = setup_dispatchable_scenario("CLASSIC")
        m = base["membership"]
        primary = base["primary"]
        create_and_complete_call(
            m["id"], primary["id"], complete_payload={"actual_tow_miles": 5},
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        assert get_membership(m["id"])["calls_used_current_term"] == 1
        set_clock("2027-09-02T00:00:00Z")
        grace = get_membership(m["id"])
        assert grace["status"] == "GRACE", f"expected GRACE after term end, got {grace['status']}"
        resp = api.renew_membership(m["id"], member_services_rep_headers)
        renewed = validate_success(resp)
        assert renewed["status"] == "ACTIVE"
        assert renewed["term_start_date"] == "2027-09-01T00:00:00.000Z"
        assert renewed["term_end_date"] == "2028-08-31T00:00:00.000Z"
        assert renewed["calls_used_current_term"] == 0


class TestGraceToLapsed:
    def test_clock_past_grace_deadline_lapses_and_renew_rejected(self, api, member_services_rep_headers):
        """PRD §2.4: "Any membership already in `GRACE` whose grace deadline —
        `term_end_date` plus thirty days — now lies in the past transitions to
        `LAPSED`, with `lapse_at` stamped at the new logical now." PRD §3.3:
        "Renewal from any other state is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/grace_to_lapsed_after_30_days
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        m = base["membership"]
        set_clock("2027-10-02T00:00:00Z")
        lapsed = get_membership(m["id"])
        assert lapsed["status"] == "LAPSED"
        assert lapsed["lapse_at"] is not None
        resp = api.renew_membership(m["id"], member_services_rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestLapseReinstateCycle:
    def test_reinstate_resets_term_and_counter(self, api, member_services_rep_headers):
        """PRD §3.3: "Reinstatement starts a fresh term at the logical now (new
        `term_start_date`, `term_end_date` 365 days later), resets
        `calls_used_current_term` to 0, increments `reinstatement_count` by one,
        nulls `lapse_at` again, lands the membership in `REINSTATED`, and appends
        a `REINSTATEMENT` event."

        Design: Difficulty/non_linear_state_machine/membership_lapse_reinstate_cycle
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        m = base["membership"]
        set_clock("2026-10-01T00:00:00Z")
        validate_success(api.lapse_membership(m["id"], member_services_rep_headers))
        resp = api.reinstate_membership(m["id"], {"dues_paid": True}, member_services_rep_headers)
        reinstated = validate_success(resp)
        assert reinstated["status"] == "REINSTATED"
        assert reinstated["reinstatement_count"] == 1
        assert reinstated["calls_used_current_term"] == 0
        assert reinstated["term_start_date"] == "2026-10-01T00:00:00.000Z"
        assert reinstated["lapse_at"] is None

    def test_renew_from_reinstated_returns_active_and_event_sequence(self, api, member_services_rep_headers):
        """PRD §3.3: "A membership in `REINSTATED` may also renew, and here
        renewing early is expressly allowed — the logical now need not have
        passed `term_end_date` — but the new term still starts at the old
        `term_end_date` rather than at the moment of renewal, the call counter
        resets, and the status becomes `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/membership_lapse_reinstate_cycle
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        m = base["membership"]
        set_clock("2026-10-01T00:00:00Z")
        validate_success(api.lapse_membership(m["id"], member_services_rep_headers))
        validate_success(api.reinstate_membership(m["id"], {"dues_paid": True}, member_services_rep_headers))
        resp = api.renew_membership(m["id"], member_services_rep_headers)
        renewed = validate_success(resp)
        assert renewed["status"] == "ACTIVE"
        assert renewed["term_start_date"] == "2027-10-01T00:00:00.000Z"
        assert renewed["term_end_date"] == "2028-09-30T00:00:00.000Z"
        events_resp = api.list_membership_events_for(m["id"], member_services_rep_headers)
        events, _meta = validate_paginated(events_resp)
        types = [e["event_type"] for e in events]
        for expected in ("ENROLLMENT", "LAPSE", "REINSTATEMENT", "RENEWAL"):
            assert expected in types, f"expected {expected} in event trail, got {types}"
        assert types.index("ENROLLMENT") < types.index("LAPSE") < types.index("REINSTATEMENT") < types.index("RENEWAL")


class TestCancelCascades:
    def test_cancel_cascades_household_removed_and_credit_invariant(self, api, member_services_rep_headers):
        """PRD §3.3: "The cascade is total: every `ACTIVE` household row
        transitions to `REMOVED`, and every `ACTIVE` `AncillarySale` on the
        membership transitions to `REFUNDED` with the commission reversal and
        full refund credit of §3.9 applied to each."

        Design: Difficulty/transitive_cascade/membership_cancel_cascades_household_and_ancillary
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        m = base["membership"]
        extra = validate_success(
            api.add_household_member(
                m["id"],
                {"full_name": "Sam Spouse", "relationship": "SPOUSE", "date_of_birth": "1982-01-01T00:00:00Z"},
                member_services_rep_headers,
            ),
            expected_status=201,
        )
        product = create_ancillary_product()
        sale = create_ancillary_sale(m["id"], product["id"])
        resp = api.cancel_membership(m["id"], member_services_rep_headers)
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"
        hm = get_success_data(api.get_household_member(extra["id"], member_services_rep_headers))
        assert hm["status"] == "REMOVED"
        sale_after = get_success_data(api.get_ancillary_sale(sale["id"], member_services_rep_headers))
        assert sale_after["status"] == "REFUNDED"
        # Cascade applies the §3.9 full refund credit to the sale: the 12000
        # sale debit is reversed (+12000), so the credit must be at least
        # -2500 (the spouse's full-year add charge, which the §3.3 cascade
        # sentence does not state is prorated back on cascade removal).
        assert cancelled["account_credit_cents"] >= -2500

    def test_cancel_appends_cancellation_event(self, api, member_services_rep_headers):
        """PRD §3.3: "A `CANCELLATION` event closes the audit trail."

        Design: Difficulty/transitive_cascade/membership_cancel_cascades_household_and_ancillary
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        m = base["membership"]
        validate_success(api.add_household_member(
            m["id"],
            {"full_name": "Sam Spouse", "relationship": "SPOUSE", "date_of_birth": "1982-01-01T00:00:00Z"},
            member_services_rep_headers,
        ), expected_status=201)
        product = create_ancillary_product()
        create_ancillary_sale(m["id"], product["id"])
        validate_success(api.cancel_membership(m["id"], member_services_rep_headers))
        events, _meta = validate_paginated(api.list_membership_events_for(m["id"], member_services_rep_headers))
        types = [e["event_type"] for e in events]
        assert types[-1] == "CANCELLATION", f"CANCELLATION must close the trail, got {types}"


class TestCancelValidationPriorityPair:
    def test_cancel_blocked_by_open_call_then_terminal_state_error(self, api, member_services_rep_headers,
                                                                   dispatcher_headers):
        """PRD §3.3: "Cancellation is available from `ACTIVE`, `GRACE`, and
        `REINSTATED`, and is blocked whenever the membership holds any
        non-terminal service call (`ERR_OPEN_SERVICE_CALLS`)." PRD §2.8 step 6:
        state preconditions return `ERR_INVALID_STATE`.

        Design: Difficulty/priority_pair_validation_conflict/cancel_with_open_call_and_terminal_state_conflict
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        m = base["membership"]
        primary = base["primary"]
        call = validate_success(
            api.create_service_call(
                {"membership_id": m["id"], "requesting_member_id": primary["id"],
                 "service_type": "TOW", "breakdown_location_state": "CA", "requested_tow_miles": 10},
                dispatcher_headers,
            ),
            expected_status=201,
        )
        first = api.cancel_membership(m["id"], member_services_rep_headers)
        validate_error(first, ApiErrorId.ERR_OPEN_SERVICE_CALLS, expected_status=422)
        validate_success(api.cancel_service_call(call["id"], dispatcher_headers))
        ok = api.cancel_membership(m["id"], member_services_rep_headers)
        assert validate_success(ok)["status"] == "CANCELLED"
        second = api.cancel_membership(m["id"], member_services_rep_headers)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_cancel_from_terminal_state_rejected_isolated(self, api, member_services_rep_headers):
        """PRD §2.8 step 6: "the target resource is in a state that permits the
        operation ... Violations return `ERR_INVALID_STATE`." PRD §3.3:
        "`CANCELLED` terminal."

        Design: Difficulty/priority_pair_validation_conflict/cancel_with_open_call_and_terminal_state_conflict
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        m = base["membership"]
        validate_success(api.cancel_membership(m["id"], member_services_rep_headers))
        resp = api.cancel_membership(m["id"], member_services_rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestLapsedMembershipVersusCoveragePriority:
    def test_lapsed_membership_and_removed_member_surfaces_serviceability(self, api, member_services_rep_headers,
                                                                          dispatcher_headers):
        """PRD §3.5: "then membership serviceability
        (`ERR_MEMBERSHIP_NOT_SERVICEABLE`), then household coverage
        (`ERR_MEMBER_NOT_COVERED`)".

        Design: Difficulty/priority_pair_validation_conflict/service_call_lapsed_membership_and_uncovered_member_conflict
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        m = base["membership"]
        extra = validate_success(
            api.add_household_member(
                m["id"],
                {"full_name": "Sam Spouse", "relationship": "SPOUSE", "date_of_birth": "1982-01-01T00:00:00Z"},
                member_services_rep_headers,
            ),
            expected_status=201,
        )
        validate_success(api.remove_household_member(extra["id"], member_services_rep_headers))
        validate_success(api.lapse_membership(m["id"], member_services_rep_headers))
        resp = api.create_service_call(
            {"membership_id": m["id"], "requesting_member_id": extra["id"],
             "service_type": "TOW", "breakdown_location_state": "CA", "requested_tow_miles": 10},
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_SERVICEABLE, expected_status=422)
        calls, meta = validate_paginated(
            api.list_service_calls(dispatcher_headers, params={"membership_id": m["id"]})
        )
        assert calls == [], f"no ServiceCall should be created, got {calls}"

    def test_lapsed_membership_with_active_member_still_not_serviceable(self, api, member_services_rep_headers,
                                                                        dispatcher_headers):
        """PRD §3.5: "the membership's `status` must be `ACTIVE`, `REINSTATED`,
        or `GRACE` — calls on `LAPSED` or `CANCELLED` memberships are rejected
        with `ERR_MEMBERSHIP_NOT_SERVICEABLE`".

        Design: Difficulty/priority_pair_validation_conflict/service_call_lapsed_membership_and_uncovered_member_conflict
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        m = base["membership"]
        primary = base["primary"]
        validate_success(api.lapse_membership(m["id"], member_services_rep_headers))
        resp = api.create_service_call(
            {"membership_id": m["id"], "requesting_member_id": primary["id"],
             "service_type": "TOW", "breakdown_location_state": "CA", "requested_tow_miles": 10},
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_SERVICEABLE, expected_status=422)
