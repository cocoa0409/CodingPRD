"""Benefit cap boundary, waiting-period tier pinning, validation violations,
OCC stale-version guards, and selector policy (PRD §2.7, §3.4-3.6)."""
from test_helpers import (
    ApiErrorId,
    accept_dispatch,
    arrive_dispatch,
    complete_dispatch,
    create_and_complete_call,
    create_and_dispatch_call,
    create_ancillary_product,
    create_ancillary_sale,
    create_club,
    create_membership,
    create_part_stock,
    create_provider,
    create_service_call,
    create_tier,
    dispatch_call,
    get_membership,
    get_success_data,
    set_clock,
    setup_dispatchable_scenario,
    setup_membership_scenario,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAnnualCallCapBoundary:
    def _setup_cap_two(self):
        return setup_dispatchable_scenario(
            "CLASSIC",
            tier_overrides={"annual_call_cap": 2},
            provider_overrides={"max_concurrent_dispatches": 5},
        )

    def test_calls_below_cap_are_benefit_eligible(self, api):
        """PRD §3.5: "The boundary is strict: a call is benefit-eligible when
        `calls_used_current_term` is strictly less than the cap, so the cap-th
        call (when the counter sits at cap minus one) is still eligible and the
        next one is not."

        Design: Difficulty/boundary_precision_check/annual_call_cap_exact_boundary
        """
        base = self._setup_cap_two()
        m_id = base["membership"]["id"]
        p_id = base["primary"]["id"]
        call1 = create_service_call(m_id, p_id, breakdown_location_state="CA", requested_tow_miles=5)
        assert call1["benefit_eligible"] is True, "count 0 < cap 2"
        pair1 = create_and_dispatch_call_pair(api, call1)
        complete_call(api, pair1, actual_tow_miles=5)
        call2 = create_service_call(m_id, p_id, breakdown_location_state="CA", requested_tow_miles=5)
        assert call2["benefit_eligible"] is True, "count 1 == cap - 1 is still eligible"

    def test_call_at_cap_is_member_pay_and_does_not_increment(self, api):
        """PRD §3.5: "A call whose cap is already exhausted is still dispatched —
        but as member-pay, with `benefit_eligible` false." PRD §3.7: "Completing
        a benefit-eligible call increments the membership's
        `calls_used_current_term` by one".

        Design: Difficulty/boundary_precision_check/annual_call_cap_exact_boundary
        """
        base = self._setup_cap_two()
        m_id = base["membership"]["id"]
        p_id = base["primary"]["id"]
        call1 = create_service_call(m_id, p_id, breakdown_location_state="CA", requested_tow_miles=5)
        complete_call(api, create_and_dispatch_call_pair(api, call1), actual_tow_miles=5)
        call2 = create_service_call(m_id, p_id, breakdown_location_state="CA", requested_tow_miles=5)
        complete_call(api, create_and_dispatch_call_pair(api, call2), actual_tow_miles=5)
        assert get_membership(m_id)["calls_used_current_term"] == 2
        call3 = create_service_call(m_id, p_id, breakdown_location_state="CA", requested_tow_miles=40)
        assert call3["benefit_eligible"] is False, "count 2 == cap: strict < boundary"
        done = complete_call(api, create_and_dispatch_call_pair(api, call3), actual_tow_miles=40)
        # member-pay: effective 40-3 = 37 miles x 650 = 24050, no included-mile deduction
        assert done["mileage_charge_cents"] == 24050
        assert get_membership(m_id)["calls_used_current_term"] == 2, "member-pay does not increment"


class TestUpgradeWaitingPeriodPinning:
    def _setup_upgraded_membership(self, api, member_services_rep_headers):
        base = setup_membership_scenario("CLASSIC", with_primary=True, tiers=["CLASSIC", "PLUS"])
        m = base["membership"]
        set_clock("2026-09-01T12:00:00Z")
        upgraded = validate_success(api.upgrade_membership(
            m["id"], {"target_tier_code": "PLUS", "expected_membership_version": m["version"]},
            member_services_rep_headers,
        ))
        base["membership"] = upgraded
        create_provider(base["club"]["id"], name="NCA Fleet 1")
        return base

    def test_call_during_waiting_period_pins_pre_upgrade_tier(self, api, member_services_rep_headers):
        """PRD §3.4: "A pre-existing need is served at the pre-upgrade tier's
        benefits: the call's `benefit_tier_code` pins the old tier, and the old
        tier's cap and included mileage govern it."

        Design: Difficulty/combinatorial_formula/upgrade_at_dispatch_tier_mileage_still_bills_overage
        """
        base = self._setup_upgraded_membership(api, member_services_rep_headers)
        call = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=80,
        )
        assert call["is_pre_existing_need"] is True
        assert call["benefit_tier_code"] == "CLASSIC"

    def test_waiting_period_call_bills_pre_upgrade_mileage(self, api, member_services_rep_headers):
        """PRD §3.4: "the old tier's cap and included mileage govern it."
        PRD §3.7: "the overage miles are the effective miles beyond the tier's
        `included_tow_miles`, floored at zero, and the `mileage_charge_cents` is
        the overage miles times the tier's `overage_rate_cents_per_mile`".

        Design: Difficulty/combinatorial_formula/upgrade_at_dispatch_tier_mileage_still_bills_overage
        """
        base = self._setup_upgraded_membership(api, member_services_rep_headers)
        credit_before = get_membership(base["membership"]["id"])["account_credit_cents"]
        pair = create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=80,
        )
        accept_dispatch(pair["dispatch"]["id"], en_route=True)
        arrive_dispatch(pair["dispatch"]["id"])
        done = complete_dispatch(pair["dispatch"]["id"], actual_tow_miles=80)
        # CLASSIC basis: effective 80-3 = 77; overage 77-5 = 72 x 650 = 46800 (NOT the PLUS 0)
        assert done["mileage_charge_cents"] == 46800
        credit_after = get_membership(base["membership"]["id"])["account_credit_cents"]
        assert credit_after == credit_before - 46800


class TestValidationViolations:
    def test_territory_unmapped_state_rejected(self, api, dispatcher_headers):
        """PRD §3.5: "`breakdown_location_state` must fall in exactly one
        `ACTIVE` club's `territory_state_codes`, else `ERR_TERRITORY_NOT_FOUND`".

        Design: Corner/validations/territory_unmapped_state_rejected
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        resp = api.create_service_call(
            {"membership_id": base["membership"]["id"], "requesting_member_id": base["primary"]["id"],
             "service_type": "TOW", "breakdown_location_state": "ZZ", "requested_tow_miles": 5},
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TERRITORY_NOT_FOUND, expected_status=422)

    def test_reinstatement_window_90_day_boundary(self, api, member_services_rep_headers):
        """PRD §3.3: "A `LAPSED` membership can be brought back within ninety
        days of `lapse_at`; past that window the attempt fails with
        `ERR_REINSTATEMENT_WINDOW_EXPIRED`."

        Design: Corner/validations/reinstatement_window_90_day_boundary
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        m1 = base["membership"]
        m2 = create_membership(base["club"]["id"], "CLASSIC")
        set_clock("2026-10-01T00:00:00Z")
        validate_success(api.lapse_membership(m1["id"], member_services_rep_headers))
        validate_success(api.lapse_membership(m2["id"], member_services_rep_headers))
        set_clock("2026-12-30T00:00:00Z")
        ok = api.reinstate_membership(m1["id"], {"dues_paid": True}, member_services_rep_headers)
        assert validate_success(ok)["status"] == "REINSTATED"
        set_clock("2026-12-30T00:00:01Z")
        resp = api.reinstate_membership(m2["id"], {"dues_paid": True}, member_services_rep_headers)
        validate_error(resp, ApiErrorId.ERR_REINSTATEMENT_WINDOW_EXPIRED, expected_status=422)

    def test_household_capacity_and_child_age_bounds(self, api, member_services_rep_headers):
        """PRD §3.2: "no more than four `ACTIVE` household members per
        membership, and a `CHILD` relationship requires the member to be younger
        than 21 at add time — violations are rejected with
        `ERR_HOUSEHOLD_LIMIT`."

        Design: Corner/validations/household_capacity_and_child_age_bounds
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        m_id = base["membership"]["id"]
        for i, (name, rel, dob) in enumerate([
            ("H Two", "PARENT", "1950-01-01T00:00:00Z"),
            ("H Three", "OTHER", "1975-01-01T00:00:00Z"),
            ("H Four", "OTHER", "1972-01-01T00:00:00Z"),
        ]):
            validate_success(api.add_household_member(
                m_id, {"full_name": name, "relationship": rel, "date_of_birth": dob},
                member_services_rep_headers,
            ), expected_status=201)
        fifth = api.add_household_member(
            m_id, {"full_name": "H Five", "relationship": "OTHER", "date_of_birth": "1970-01-01T00:00:00Z"},
            member_services_rep_headers,
        )
        validate_error(fifth, ApiErrorId.ERR_HOUSEHOLD_LIMIT, expected_status=422)
        m2 = create_membership(base["club"]["id"], "CLASSIC")
        # default clock 2026-09-01: born 2000-01-01 -> age 26, violates CHILD < 21
        child = api.add_household_member(
            m2["id"], {"full_name": "Kid Too Old", "relationship": "CHILD",
                       "date_of_birth": "2000-01-01T00:00:00Z"},
            member_services_rep_headers,
        )
        validate_error(child, ApiErrorId.ERR_HOUSEHOLD_LIMIT, expected_status=422)

    def test_tier_move_invalid_directions(self, api, member_services_rep_headers):
        """PRD §3.4: "The target tier must exist, must differ from the
        membership's current tier, and must move in the direction the action
        implies — an upgrade requires a strictly higher `rank`, a downgrade a
        strictly lower one; violations return `ERR_TIER_MOVE_INVALID`."

        Design: Corner/validations/tier_move_invalid_directions
        """
        base = setup_membership_scenario("PLUS", with_primary=False, tiers=["CLASSIC", "PLUS"])
        m = base["membership"]
        up = api.upgrade_membership(
            m["id"], {"target_tier_code": "CLASSIC", "expected_membership_version": m["version"]},
            member_services_rep_headers,
        )
        validate_error(up, ApiErrorId.ERR_TIER_MOVE_INVALID, expected_status=422)
        down = api.downgrade_membership(
            m["id"], {"target_tier_code": "PLUS", "expected_membership_version": m["version"]},
            member_services_rep_headers,
        )
        validate_error(down, ApiErrorId.ERR_TIER_MOVE_INVALID, expected_status=422)

    def test_call_by_removed_member_rejected(self, api, member_services_rep_headers, dispatcher_headers):
        """PRD §3.5: "the requesting member must be an `ACTIVE` household row
        belonging to that membership, else `ERR_MEMBER_NOT_COVERED`."

        Design: Corner/validations/call_by_removed_member_rejected
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        m = base["membership"]
        extra = validate_success(api.add_household_member(
            m["id"], {"full_name": "Sam Spouse", "relationship": "SPOUSE",
                      "date_of_birth": "1982-01-01T00:00:00Z"},
            member_services_rep_headers,
        ), expected_status=201)
        validate_success(api.remove_household_member(extra["id"], member_services_rep_headers))
        resp = api.create_service_call(
            {"membership_id": m["id"], "requesting_member_id": extra["id"],
             "service_type": "TOW", "breakdown_location_state": "CA", "requested_tow_miles": 5},
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_COVERED, expected_status=422)

    def test_household_removal_blocked_by_open_call(self, api, member_services_rep_headers, dispatcher_headers):
        """PRD §3.2: "Removing a household member mid-term is allowed only while
        that member has no non-terminal service call (one in `REQUESTED`,
        `DISPATCHED`, `EN_ROUTE`, or `ON_SCENE`) as the requesting member —
        otherwise the removal is rejected with `ERR_OPEN_SERVICE_CALLS`."

        Design: Corner/state_machines/household_removal_blocked_by_open_call
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        m = base["membership"]
        extra = validate_success(api.add_household_member(
            m["id"], {"full_name": "Sam Spouse", "relationship": "SPOUSE",
                      "date_of_birth": "1982-01-01T00:00:00Z"},
            member_services_rep_headers,
        ), expected_status=201)
        create_provider(base["club"]["id"], name="NCA Fleet 1")
        call = create_service_call(m["id"], extra["id"], breakdown_location_state="CA", requested_tow_miles=5)
        blocked = api.remove_household_member(extra["id"], member_services_rep_headers)
        validate_error(blocked, ApiErrorId.ERR_OPEN_SERVICE_CALLS, expected_status=422)
        validate_success(api.cancel_service_call(call["id"], dispatcher_headers))
        removed = validate_success(api.remove_household_member(extra["id"], member_services_rep_headers))
        assert removed["status"] == "REMOVED"
        # -2500 full-year charge at add; +2500 proration at 365 remaining days
        assert get_membership(m["id"])["account_credit_cents"] == 0

    def test_enrollment_on_suspended_club_and_provider_reactivation_rejected(self, api, club_admin_headers,
                                                                             member_services_rep_headers):
        """PRD §2.9: "A `SUSPENDED` club cannot own new memberships (enrollment
        naming it as home club is rejected with `ERR_CLUB_SUSPENDED`)" and "a
        suspended provider can only be reactivated while its servicing club is
        `ACTIVE` (otherwise `ERR_CLUB_SUSPENDED`)."

        Design: Corner/validations/enrollment_on_suspended_club_rejected
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        club = base["club"]
        provider = create_provider(club["id"], name="NCA Fleet 1", max_concurrent_dispatches=1)
        validate_success(api.update_provider(provider["id"], {"status": "SUSPENDED"}, club_admin_headers))
        validate_success(api.update_club(club["id"], {"status": "SUSPENDED"}, club_admin_headers))
        enroll = api.create_membership(
            {"home_club_id": club["id"], "primary_member_name": "Pat Primary",
             "primary_member_email": unique_email(), "tier_code": "CLASSIC"},
            member_services_rep_headers,
        )
        validate_error(enroll, ApiErrorId.ERR_CLUB_SUSPENDED, expected_status=422)
        reactivate = api.update_provider(provider["id"], {"status": "ACTIVE"}, club_admin_headers)
        validate_error(reactivate, ApiErrorId.ERR_CLUB_SUSPENDED, expected_status=422)


class TestOccStaleVersion:
    def test_membership_upgrade_stale_version_rejected(self, api, member_services_rep_headers):
        """PRD §2.7: "Membership upgrade requires the request to carry
        `expected_membership_version`". PRD §2.7: "the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False, tiers=["CLASSIC", "PLUS", "PREMIER"])
        m = base["membership"]
        upgraded = validate_success(api.upgrade_membership(
            m["id"], {"target_tier_code": "PLUS", "expected_membership_version": m["version"]},
            member_services_rep_headers,
        ))
        assert upgraded["tier_code"] == "PLUS"
        assert upgraded["version"] == m["version"] + 1
        stale = api.upgrade_membership(
            m["id"], {"target_tier_code": "PREMIER", "expected_membership_version": m["version"]},
            member_services_rep_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        assert get_membership(m["id"])["tier_code"] == "PLUS"

    def test_dispatch_stale_version_rejected_after_fail_cycle(self, api, dispatcher_headers):
        """PRD §2.7: "Service-call dispatch requires
        `expected_service_call_version` matching the call's current `version`."
        PRD §2.7: "so a mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_dispatch_stale_version_rejected
        """
        base = setup_dispatchable_scenario("CLASSIC")
        pair = create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        validate_success(api.fail_dispatch(pair["dispatch"]["id"], {"failure_reason": "PROVIDER_DECLINED"},
                                           TEST_USERS_PROVIDER_OPS))
        stale = api.dispatch_service_call(
            pair["call"]["id"], {"expected_service_call_version": pair["call"]["version"]}, dispatcher_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        dispatches, _meta = validate_paginated(
            api.list_dispatches_for_call(pair["call"]["id"], dispatcher_headers)
        )
        assert len([d for d in dispatches if d["status"] == "FAILED"]) == 1


class TestDowngradeProration:
    def test_downgrade_credit_and_term_unchanged(self, api, member_services_rep_headers):
        """PRD §3.4: "The prorated value of the new tier is its
        `annual_dues_cents` times the remaining days, divided by 365, rounded
        half-up; the prorated value of the old tier is computed the same way
        from its own dues, with each factor rounded individually before any
        subtraction" and "a downgrade credits the mirror-image difference".
        PRD §3.4: "A tier change never resets term dates".

        Design: Corner/cross_cutting_layers/downgrade_proration_credit_computed
        """
        base = setup_membership_scenario("PLUS", with_primary=False, tiers=["CLASSIC", "PLUS"])
        m = base["membership"]
        original_term_start = m["term_start_date"]
        original_term_end = m["term_end_date"]
        set_clock("2027-03-20T00:00:00Z")  # elapsed exactly 200 days
        resp = api.downgrade_membership(
            m["id"], {"target_tier_code": "CLASSIC", "expected_membership_version": m["version"]},
            member_services_rep_headers,
        )
        downgraded = validate_success(resp)
        # round_half_up(9000 x 165/365) - round_half_up(5000 x 165/365) = 4068 - 2260
        assert downgraded["account_credit_cents"] == 1808
        assert downgraded["tier_code"] == "CLASSIC"
        assert downgraded["term_start_date"] == original_term_start
        assert downgraded["term_end_date"] == original_term_end

    def test_downgrade_appends_event_with_tier_bracket(self, api, member_services_rep_headers):
        """PRD §3.4: "An `UPGRADE` or `DOWNGRADE` event (with `from_tier` and
        `to_tier` populated) is appended".

        Design: Corner/cross_cutting_layers/downgrade_proration_credit_computed
        """
        base = setup_membership_scenario("PLUS", with_primary=False, tiers=["CLASSIC", "PLUS"])
        m = base["membership"]
        set_clock("2027-03-20T00:00:00Z")
        validate_success(api.downgrade_membership(
            m["id"], {"target_tier_code": "CLASSIC", "expected_membership_version": m["version"]},
            member_services_rep_headers,
        ))
        events, _meta = validate_paginated(
            api.list_membership_events_for(m["id"], member_services_rep_headers)
        )
        downgrades = [e for e in events if e["event_type"] == "DOWNGRADE"]
        assert len(downgrades) == 1
        assert downgrades[0]["from_tier"] == "PLUS"
        assert downgrades[0]["to_tier"] == "CLASSIC"


class TestDispatchSelectorPolicy:
    def test_owned_preferred_over_contracted(self, api):
        """PRD §3.6: "ranking is total and deterministic: club-`OWNED` fleets
        are preferred over `CONTRACTED` third parties; then the provider with
        the smaller current non-terminal dispatch count wins; then the earlier
        `created_at` breaks remaining ties."

        Design: Corner/cross_cutting_layers/dispatch_selector_owned_preference_and_created_at_tiebreak
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        create_provider(base["club"]["id"], name="Contract Tow Co", provider_kind="CONTRACTED")
        owned = create_provider(base["club"]["id"], name="Club Fleet", provider_kind="OWNED")
        call = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        dispatch = dispatch_call(call["id"], call["version"])
        assert dispatch["provider_id"] == owned["id"], "OWNED outranks CONTRACTED even when created later"

    def test_capability_filter_empty_pool_auto_cancels(self, api, dispatcher_headers):
        """PRD §3.6: "the call's `service_type` appears in the provider's
        `capabilities`" and "When no candidate survives, no `Dispatch` row is
        created at all; the call transitions straight from `REQUESTED` to
        `CANCELLED` with `cancel_reason` set to `NO_PROVIDER`".

        Design: Corner/cross_cutting_layers/dispatch_selector_capability_filter
        """
        base = setup_membership_scenario("CLASSIC", with_primary=True)
        create_provider(base["club"]["id"], name="Locksmith Only", provider_kind="CONTRACTED",
                        capabilities=["LOCKOUT"])
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


# --- local helpers ---

from test_helpers import TEST_USERS as _TEST_USERS  # noqa: E402

TEST_USERS_PROVIDER_OPS = _TEST_USERS["provider_ops_headers"]


def create_and_dispatch_call_pair(api, call):
    dispatch = dispatch_call(call["id"], call["version"])
    return {"call": call, "dispatch": dispatch}


def complete_call(api, pair, actual_tow_miles):
    accept_dispatch(pair["dispatch"]["id"], en_route=True)
    arrive_dispatch(pair["dispatch"]["id"])
    return complete_dispatch(pair["dispatch"]["id"], actual_tow_miles=actual_tow_miles)
