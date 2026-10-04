"""Complaint score filtering and reconciliation, sell-through rounding,
allocation void invariants, pallet stranding, chargeback appeals, and the
vendor compliance cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    allocate_many,
    allocate_pallet,
    assert_club_invariants,
    book_appointment,
    check_in_appointment,
    confirm_chargeback,
    create_active_item,
    create_club,
    create_depot,
    create_member,
    create_open_run,
    create_region,
    create_vendor,
    file_complaint,
    make_vendor_rep_headers,
    receive_pallet,
    record_purchase,
    setup_received_pallets,
    setup_run_with_allocations,
    setup_vendor_with_confirmed_no_shows,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CM, DM, DP, MD, RO


class TestComplaintReconciliation:
    def test_score_recomputes_on_create_and_resolve(self, api):
        """PRD §3.7: "Each complaint's `weight` is computed once at creation and frozen: a category multiplier
        — 4.0 for `SAFETY`, 2.0 for `QUALITY`, 1.5 for `AVAILABILITY`, 1.0 for `PRICING`
        — times the member's `household_size` at that moment."
        PRD §3.7: "Both figures recompute whenever a complaint is created, whenever a complaint
        is resolved — a resolved complaint is excluded — and when deletion review opens."

        Design: Corner/cross_cutting_layers/derived_fields_reconcile_on_mutation
        """
        region = create_region()
        vendor = create_vendor()
        club = create_club(region["id"])
        item = create_active_item(vendor["id"])
        member = create_member(club["id"], household_size=2)
        complaint = file_complaint(member["id"], item["id"], "SAFETY")
        assert complaint["weight"] == pytest.approx(8.0, abs=1e-2), "SAFETY 4.0 * household 2"
        after_create = validate_success(api.get_item(item["id"], CM))
        assert after_create["complaint_weighted_score"] == pytest.approx(8.0, abs=1e-2)
        validate_success(api.resolve_complaint(complaint["id"], MD))
        after_resolve = validate_success(api.get_item(item["id"], CM))
        assert after_resolve["complaint_weighted_score"] == pytest.approx(0.0, abs=1e-2), (
            "resolved complaints are excluded on recompute"
        )

    def test_complaint_weight_frozen_at_creation(self, api):
        """PRD §3.7: "Each complaint's `weight` is computed once at creation and frozen: a category multiplier
        — 4.0 for `SAFETY`, 2.0 for `QUALITY`, 1.5 for `AVAILABILITY`, 1.0 for `PRICING`
        — times the member's `household_size` at that moment."

        Design: Corner/cross_cutting_layers/derived_fields_reconcile_on_mutation
        """
        region = create_region()
        vendor = create_vendor()
        club = create_club(region["id"])
        item = create_active_item(vendor["id"])
        member = create_member(club["id"], household_size=2)
        complaint = file_complaint(member["id"], item["id"], "SAFETY")
        fetched = validate_success(api.get_complaint(complaint["id"], MD))
        assert fetched["weight"] == pytest.approx(8.0, abs=1e-2)


class TestSellThroughRounding:
    def _setup_treasure_hunt_sell_through(self, api, regional_ops_headers, sold):
        """TREASURE_HUNT item (pallet_qty 40, target 80, exit 2026-09-30) with one received
        pallet and `sold` units purchased; clock stays at 2026-09-02 (before the exit window)."""
        ctx = setup_received_pallets(
            delivery_date="2026-09-02", num_pallets=1,
            item_overrides={"case_pack_qty": 10, "pallet_length_in": 40, "pallet_width_in": 40,
                            "cases_per_layer": 2, "max_layers": 2, "item_type": "TREASURE_HUNT",
                            "exit_window_date": "2026-09-30", "sell_through_target_pct": 80},
        )
        member = create_member(ctx["club"]["id"])
        record_purchase(member["id"], ctx["club"]["id"], ctx["item"]["id"], sold)
        item = validate_success(api.get_item(ctx["item"]["id"], CM))
        return item

    def test_sell_through_rounds_half_up(self, api, regional_ops_headers):
        """PRD §3.8: "The `sell_through_pct` stamped onto the decision is one hundred times the units sold —
        the sum of `unit_qty` over the item's `COMPLETED` purchases — divided by the
        units received, the sum of `unit_qty` over the item's pallets in `RECEIVED`,
        `ALLOCATED`, or `SHIPPED`, with the denominator floored at 1 to avoid division
        by zero; the quotient is rounded half-up to an integer percent."
        PRD §2.6: "Sell-through percentage is an integer percent rounded half-up."

        Design: Corner/calculations/sell_through_rounding_half_up
        """
        item = self._setup_treasure_hunt_sell_through(api, regional_ops_headers, sold=29)
        decision = validate_success(
            api.create_markdown_decision(
                item["id"],
                {"decision": "SELL_THROUGH", "expected_item_version": item["version"]},
                CM,
            ), 201,
        )
        assert decision["sell_through_pct"] == 73, (
            f"100 * 29 / 40 = 72.5 rounds half-up to 73, got {decision['sell_through_pct']}"
        )

    def test_sell_through_before_exit_window_allowed(self, api, regional_ops_headers):
        """PRD §3.8: "When the current logical date is on or after the item's `exit_window_date` and the
        recomputed `sell_through_pct` is below the item's `sell_through_target_pct`, the
        only lawful decision is `MARKDOWN`; a `SELL_THROUGH` decision in that situation
        is rejected with `ERR_MARKDOWN_RULE_VIOLATION`."

        Design: Corner/calculations/sell_through_rounding_half_up
        """
        # Current date 2026-09-02 is before the 2026-09-30 exit window: the
        # mandatory-markdown rule is not engaged and SELL_THROUGH is lawful even
        # below target (29/40 = 73 < 80).
        item = self._setup_treasure_hunt_sell_through(api, regional_ops_headers, sold=29)
        decision = validate_success(
            api.create_markdown_decision(
                item["id"],
                {"decision": "SELL_THROUGH", "expected_item_version": item["version"]},
                CM,
            ), 201,
        )
        assert decision["decision"] == "SELL_THROUGH"


class TestAllocationVoidInvariant:
    def test_void_restores_slots_and_frees_pallet(self, api):
        """PRD §3.3: "Voiding moves the allocation to `VOIDED`, decrements the club's `allocated_slot_count`
        by `floor_slots_reserved`, recomputes the club's posture, returns the pallet
        from `ALLOCATED` to `RECEIVED`, and increments the parent run's `version` by 1."

        Design: Difficulty/compensating_invariant/allocation_void_restores_club_slot_invariant
        """
        ctx = setup_run_with_allocations(delivery_date="2026-09-02", num_pallets=1)
        club = validate_success(api.get_club(ctx["club"]["id"], DP))
        assert club["allocated_slot_count"] == 1
        validate_success(
            api.void_allocation(ctx["allocations"][0]["id"], DP, payload={"void_reason": "plan changed"})
        )
        club = validate_success(api.get_club(ctx["club"]["id"], DP))
        assert club["allocated_slot_count"] == 0, "invariant restored by the compensating void"
        assert club["posture"] == "NORMAL"
        pallet = validate_success(api.get_pallet(ctx["pallets"][0]["id"], DP))
        assert pallet["status"] == "RECEIVED", "freed for re-allocation"
        assert_club_invariants(club)

    def test_voided_allocation_pallet_can_be_reallocated(self, api):
        """PRD §3.3: "Voiding moves the allocation to `VOIDED`, decrements the club's `allocated_slot_count`
        by `floor_slots_reserved`, recomputes the club's posture, returns the pallet
        from `ALLOCATED` to `RECEIVED`, and increments the parent run's `version` by 1."

        Design: Difficulty/compensating_invariant/allocation_void_restores_club_slot_invariant
        """
        ctx = setup_run_with_allocations(delivery_date="2026-09-02", num_pallets=1)
        alloc = ctx["allocations"][0]
        validate_success(api.void_allocation(alloc["id"], DP, payload={"void_reason": "redo"}))
        # The freed pallet can be proposed again on the same run (same-day rule still holds).
        run = validate_success(api.get_cross_dock_run(ctx["run"]["id"], DP))
        realloc = allocate_pallet(run["id"], ctx["pallets"][0]["id"], ctx["club"]["id"],
                                  run["version"])
        assert realloc["status"] == "PROPOSED"
        club = validate_success(api.get_club(ctx["club"]["id"], DP))
        assert club["allocated_slot_count"] == 1


class TestPalletStranding:
    def test_rollover_strands_and_reconcile_closes(self, api, regional_ops_headers):
        """PRD §3.3: "When the logical clock advances past a pallet's `received_date` while the pallet is
        still `RECEIVED`, it auto-transitions to `STRANDED`. A `DepotManager` may
        reconcile a `STRANDED` pallet, moving it to `RECONCILED`; reconciliation is
        audit-only and restores no inventory. Pallets in `SHIPPED` or `RECONCILED` are
        terminal."

        Design: Corner/state_machines/pallet_stranded_after_day_rollover_and_reconciled
        """
        ctx = setup_received_pallets(delivery_date="2026-09-02", num_pallets=1)
        api.set_clock("2026-09-03T00:00:01Z", regional_ops_headers)
        pallet = validate_success(api.get_pallet(ctx["pallets"][0]["id"], DM))
        assert pallet["status"] == "STRANDED", "day rollover auto-transition"
        reconciled = validate_success(api.reconcile_pallet(ctx["pallets"][0]["id"], DM))
        assert reconciled["status"] == "RECONCILED"


class TestChargebackAppealOwnership:
    def _setup_late_chargeback(self, api, regional_ops_headers):
        """Vendor with one ASSESSED LATE_CHECKIN chargeback (check-in 20 minutes after window
        start, beyond the 15-minute grace)."""
        region = create_region()
        vendor = create_vendor()
        other = create_vendor()
        depot = create_depot(region["id"])
        appt = book_appointment(depot["id"], vendor["id"], "2026-09-01",
                                start_time="09:00", end_time="09:30")
        api.set_clock("2026-09-01T09:20:00Z", regional_ops_headers)
        checked = validate_success(api.check_in_appointment(appt["id"], DM))
        assert checked["chargeback_cents"] == 15000, "LATE_CHECKIN base, first offense"
        cbs, _ = validate_paginated(
            api.list_chargebacks(DM, params={"appointment_id": appt["id"]})
        )
        assert len(cbs) == 1
        return vendor, other, cbs[0]

    def test_appeal_requires_owning_vendor_rep(self, api, regional_ops_headers):
        """PRD §2.1: "ownership checks on any resource that references a vendor — most importantly appointment
        booking, appointment cancellation, and chargeback appeal — compare the
        resource's `vendor_id` field to `X-User-ID`, and a mismatch is rejected with
        `ERR_FORBIDDEN`."
        PRD §3.6: "A `VendorRep` may appeal an `ASSESSED` chargeback on their own vendor (identity mismatch
        is `ERR_FORBIDDEN`), moving it to `APPEALED`."

        Design: Difficulty/cross_entity_state_dependency/chargeback_appeal_requires_owning_vendor_rep
        """
        vendor, other, cb = self._setup_late_chargeback(api, regional_ops_headers)
        validate_error(
            api.appeal_chargeback(cb["id"], make_vendor_rep_headers(other["id"])),
            ApiErrorId.ERR_FORBIDDEN,
        )
        appealed = validate_success(
            api.appeal_chargeback(cb["id"], make_vendor_rep_headers(vendor["id"]))
        )
        assert appealed["status"] == "APPEALED"

    def test_appeal_moves_chargeback_to_appealed(self, api, regional_ops_headers):
        """PRD §3.6: "A `VendorRep` may appeal an `ASSESSED` chargeback on their own vendor (identity mismatch
        is `ERR_FORBIDDEN`), moving it to `APPEALED`."

        Design: Difficulty/cross_entity_state_dependency/chargeback_appeal_requires_owning_vendor_rep
        """
        vendor, other, cb = self._setup_late_chargeback(api, regional_ops_headers)
        appealed = validate_success(
            api.appeal_chargeback(cb["id"], make_vendor_rep_headers(vendor["id"]))
        )
        assert appealed["status"] == "APPEALED"
        fetched = validate_success(api.get_chargeback(cb["id"], DM))
        assert fetched["status"] == "APPEALED"
        assert fetched["amount_cents"] == 15000


class TestAutoConfirm:
    def test_chargeback_auto_confirms_after_appeal_window(self, api, regional_ops_headers):
        """PRD §3.6: "If the clock advances more than seven days past the `assessed_at` date while the
        chargeback is still `ASSESSED` and never appealed, it auto-confirms to
        `CONFIRMED`."
        PRD §3.6: "Confirming a chargeback — by resolution or by auto-confirm — adds its `amount_cents` to
        the vendor's `total_chargeback_cents` and recomputes the vendor's
        `compliance_score_bp`."
        PRD §3.6: "Each chargeback's raw penalty is 250 for `LATE_CHECKIN`, 600 for `NO_SHOW`, and 400 for
        `OVER_PALLET_COUNT`."

        Design: Corner/errors/chargeback_auto_confirm_after_appeal_window
        """
        region = create_region()
        vendor = create_vendor()
        depot = create_depot(region["id"])
        appt = book_appointment(depot["id"], vendor["id"], "2026-09-01",
                                start_time="09:00", end_time="09:30")
        api.set_clock("2026-09-01T09:20:00Z", regional_ops_headers)
        validate_success(api.check_in_appointment(appt["id"], DM))  # LATE_CHECKIN assessed
        # 2026-09-09 is more than seven days past the 2026-09-01 assessment date.
        api.set_clock("2026-09-09T00:00:01Z", regional_ops_headers)
        cbs, _ = validate_paginated(
            api.list_chargebacks(DM, params={"appointment_id": appt["id"]})
        )
        assert cbs[0]["status"] == "CONFIRMED"
        vendor_after = validate_success(api.get_vendor(vendor["id"], DM))
        assert vendor_after["total_chargeback_cents"] == 15000
        assert vendor_after["compliance_score_bp"] == 9750, (
            "10000 - 250 for one CONFIRMED LATE_CHECKIN inside the first 30-day bucket"
        )


class TestVendorComplianceCascade:
    def test_third_confirm_suspends_vendor(self, api, regional_ops_headers):
        """PRD §3.6: "The score is 10000 minus the sum of decayed penalties, floored at zero. If the
        recomputed score falls below 8500 basis points while the vendor is `ACTIVE`, the
        vendor cascades to `SUSPENDED`, and a suspended vendor can no longer book new
        appointments — attempts are rejected with `ERR_INACTIVE_REFERENCE`."
        PRD §3.6: "Each chargeback's raw penalty is 250 for `LATE_CHECKIN`, 600 for `NO_SHOW`, and 400 for
        `OVER_PALLET_COUNT`."

        Design: Difficulty/transitive_cascade/chargeback_confirm_cascades_vendor_score_and_suspension
        """
        # Two NO_SHOW confirms: 10000 - 2*600 = 8800 >= 8500 → still ACTIVE.
        region, vendor, depot, confirmed = setup_vendor_with_confirmed_no_shows(
            2, delivery_date="2026-09-01", rollover_to="2026-09-02T00:00:01Z"
        )
        before = validate_success(api.get_vendor(vendor["id"], DM))
        assert before["compliance_score_bp"] == 8800
        assert before["status"] == "ACTIVE"
        # A third NO_SHOW assessed on 2026-09-02, appealed and confirmed.
        appt3 = book_appointment(depot["id"], vendor["id"], "2026-09-02",
                                 start_time="08:00", end_time="08:30")
        api.set_clock("2026-09-03T00:00:01Z", regional_ops_headers)
        cbs, _ = validate_paginated(
            api.list_chargebacks(DM, params={"appointment_id": appt3["id"]})
        )
        assert len(cbs) == 1 and cbs[0]["reason"] == "NO_SHOW"
        confirm_chargeback(cbs[0]["id"], vendor["id"])
        after = validate_success(api.get_vendor(vendor["id"], DM))
        assert after["compliance_score_bp"] == 8200, "10000 - 3*600, all at bucket 0"
        assert after["status"] == "SUSPENDED", "8200 < 8500 cascades the vendor to SUSPENDED"
        resp = api.create_appointment(
            {"depot_id": depot["id"], "vendor_id": vendor["id"],
             "delivery_date": "2026-09-03", "start_time": "09:00", "end_time": "09:30",
             "pallet_count": 1},
            make_vendor_rep_headers(vendor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INACTIVE_REFERENCE)

    def test_suspension_blocks_booking_and_recompute_is_per_confirm(self, api, regional_ops_headers):
        """PRD §3.6: "Confirming a chargeback — by resolution or by auto-confirm — adds its `amount_cents` to
        the vendor's `total_chargeback_cents` and recomputes the vendor's
        `compliance_score_bp`."
        PRD §3.6: "If the recomputed score falls below 8500 basis points while the vendor is `ACTIVE`, the
        vendor cascades to `SUSPENDED`, and a suspended vendor can no longer book new
        appointments — attempts are rejected with `ERR_INACTIVE_REFERENCE`."

        Design: Difficulty/transitive_cascade/chargeback_confirm_cascades_vendor_score_and_suspension
        """
        # Two NO_SHOW confirms keep the vendor ACTIVE; the third confirm crosses 8500.
        region, vendor, depot, confirmed = setup_vendor_with_confirmed_no_shows(
            2, delivery_date="2026-09-01", rollover_to="2026-09-02T00:00:01Z"
        )
        after_two = validate_success(api.get_vendor(vendor["id"], DM))
        assert after_two["total_chargeback_cents"] == 150000  # 2 * 75000
        assert after_two["compliance_score_bp"] == 8800
        assert after_two["status"] == "ACTIVE"
        appt3 = book_appointment(depot["id"], vendor["id"], "2026-09-02",
                                 start_time="08:00", end_time="08:30")
        api.set_clock("2026-09-03T00:00:01Z", regional_ops_headers)
        cbs, _ = validate_paginated(
            api.list_chargebacks(DM, params={"appointment_id": appt3["id"]})
        )
        confirm_chargeback(cbs[0]["id"], vendor["id"])
        after_three = validate_success(api.get_vendor(vendor["id"], DM))
        # Third NO_SHOW was assessed with 2 prior CONFIRMED → repeat multiplier 1.5 → 112500.
        assert after_three["total_chargeback_cents"] == 262500  # 150000 + 112500
        assert after_three["status"] == "SUSPENDED"


class TestVendorDeactivateGuard:
    def _setup_suspended_vendor_with_future_booking(self, api, regional_ops_headers):
        """Vendor suspended via 4 confirmed NO_SHOWs on 2026-09-01, holding one BOOKED
        appointment for 2026-09-10."""
        region = create_region()
        vendor = create_vendor()
        depot = create_depot(region["id"], dock_hours_open="08:00", dock_hours_close="18:00")
        for i in range(4):
            book_appointment(depot["id"], vendor["id"], "2026-09-01",
                             start_time=f"{8 + i:02d}:00", end_time=f"{8 + i:02d}:30")
        future = book_appointment(depot["id"], vendor["id"], "2026-09-10",
                                  start_time="08:00", end_time="08:30")
        api.set_clock("2026-09-02T00:00:01Z", regional_ops_headers)
        cbs, _ = validate_paginated(
            api.list_chargebacks(DM, params={"vendor_id": vendor["id"], "reason": "NO_SHOW"})
        )
        assert len(cbs) == 4
        for cb in cbs:
            confirm_chargeback(cb["id"], vendor["id"])
        vendor_now = validate_success(api.get_vendor(vendor["id"], DM))
        assert vendor_now["status"] == "SUSPENDED"
        return vendor, future

    def test_deactivate_blocked_by_open_appointment(self, api, regional_ops_headers):
        """PRD §3.6: "Deactivation is guarded: if any appointment for the vendor is still `BOOKED` or
        `CHECKED_IN`, the request fails with `ERR_REFERENTIAL_GUARD` (HTTP 409)."
        PRD §3.6: "A `DepotManager` may reinstate a `SUSPENDED` vendor back to `ACTIVE`, or deactivate a
        `SUSPENDED` vendor to the terminal `DEACTIVATED`."

        Design: Corner/validations/vendor_deactivate_blocked_by_open_appointment
        """
        vendor, future = self._setup_suspended_vendor_with_future_booking(api, regional_ops_headers)
        validate_error(api.deactivate_vendor(vendor["id"], DM), ApiErrorId.ERR_REFERENTIAL_GUARD)
        cancelled = validate_success(
            api.cancel_appointment(future["id"], make_vendor_rep_headers(vendor["id"]))
        )
        assert cancelled["status"] == "CANCELLED"
        final = validate_success(api.deactivate_vendor(vendor["id"], DM))
        assert final["status"] == "DEACTIVATED"
