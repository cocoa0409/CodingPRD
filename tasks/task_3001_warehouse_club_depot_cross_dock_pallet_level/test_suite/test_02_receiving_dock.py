"""Receiving dock: appointment windows, check-in, completion, unload fees,
chargeback amounts, no-show rollover, and pallet receipt."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_pallet,
    book_appointment,
    check_in_appointment,
    create_active_item,
    create_depot,
    create_region,
    create_vendor,
    make_vendor_rep_headers,
    receive_pallet,
    setup_received_pallets,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DM, RO


def _dock(vendor_count=1, dock_count=1):
    """Region + N vendors + depot (09:00-17:00, 30-min slots)."""
    region = create_region()
    vendors = [create_vendor() for _ in range(vendor_count)]
    depot = create_depot(region["id"], dock_count=dock_count)
    return region, vendors, depot


class TestAppointmentWindows:
    def test_overlapping_window_rejected_adjacent_allowed(self, api, depot_manager_headers):
        """PRD §3.2: "end_time` must be strictly after `start_time`, and the window is half-open — it occupies
        `[start_time, end_time)`."
        PRD §3.2: "two appointments whose half-open windows intersect on the same depot and door conflict;
        a booking that cannot be placed without overlap is rejected with
        `ERR_APPOINTMENT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/appointment_half_open_window_adjacency_vs_overlap
        """
        region, (v1, v2), depot = _dock(vendor_count=2)
        book_appointment(depot["id"], v1["id"], "2026-09-02", start_time="09:00", end_time="09:30")
        overlap = api.create_appointment(
            {"depot_id": depot["id"], "vendor_id": v2["id"], "delivery_date": "2026-09-02",
             "start_time": "09:15", "end_time": "09:45", "pallet_count": 1},
            make_vendor_rep_headers(v2["id"]),
        )
        validate_error(overlap, ApiErrorId.ERR_APPOINTMENT_CONFLICT)
        adjacent = api.create_appointment(
            {"depot_id": depot["id"], "vendor_id": v2["id"], "delivery_date": "2026-09-02",
             "start_time": "09:30", "end_time": "10:00", "pallet_count": 1},
            make_vendor_rep_headers(v2["id"]),
        )
        appt2 = validate_success(adjacent, 201)
        assert appt2["status"] == "BOOKED"

    def test_adjacent_windows_share_no_overlap(self, api, depot_manager_headers):
        """PRD §3.2: "the window is half-open — it occupies `[start_time, end_time)`."
        PRD §3.2: "two appointments whose half-open windows intersect on the same depot and door conflict;
        a booking that cannot be placed without overlap is rejected with
        `ERR_APPOINTMENT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/appointment_half_open_window_adjacency_vs_overlap
        """
        region, (v1, v2), depot = _dock(vendor_count=2)
        book_appointment(depot["id"], v1["id"], "2026-09-02", start_time="09:00", end_time="09:30")
        book_appointment(depot["id"], v2["id"], "2026-09-02", start_time="09:30", end_time="10:00")
        appts, meta = __import__("test_helpers").validate_paginated(
            api.list_depot_appointments(depot["id"], depot_manager_headers,
                                        params={"delivery_date": "2026-09-02"})
        )
        assert len(appts) == 2
        assert all(a["status"] == "BOOKED" for a in appts)

    def test_window_outside_dock_hours_rejected(self, api):
        """PRD §3.2: "The window must lie within the depot's dock hours and both endpoints must
        align to the depot's `slot_length_minutes` grid measured from `dock_hours_open`"
        PRD §3.2: "A window outside dock hours, misaligned to the slot grid, or violating these
        ordering rules is rejected with `ERR_APPOINTMENT_CONFLICT` (HTTP 409)."

        Design: Corner/validations/appointment_window_outside_dock_hours_rejected
        """
        region, (vendor,), depot = _dock()
        resp = api.create_appointment(
            {"depot_id": depot["id"], "vendor_id": vendor["id"], "delivery_date": "2026-09-02",
             "start_time": "07:00", "end_time": "07:30", "pallet_count": 1},
            make_vendor_rep_headers(vendor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_CONFLICT)


class TestCheckIn:
    def test_checkin_after_end_time_rejected(self, api, regional_ops_headers):
        """PRD §3.2: "Check-in requires the appointment to be `BOOKED`, requires the current logical date to
        equal the appointment's `delivery_date`, and requires the current logical time
        to be at or before the appointment's `end_time`; a check-in after the window
        closes is rejected with `ERR_APPOINTMENT_CONFLICT`."

        Design: Corner/validations/checkin_after_end_time_rejected
        """
        region, (vendor,), depot = _dock()
        appt = book_appointment(depot["id"], vendor["id"], "2026-09-02",
                                start_time="09:00", end_time="09:30")
        api.set_clock("2026-09-02T09:31:00Z", regional_ops_headers)
        validate_error(api.check_in_appointment(appt["id"], DM), ApiErrorId.ERR_APPOINTMENT_CONFLICT)

    def test_checkin_exactly_at_grace_limit_no_chargeback(self, api, regional_ops_headers):
        """PRD §3.2: "If the check-in time is later than `start_time` plus a fifteen-minute grace period, the
        system immediately assesses a `LATE_CHECKIN` chargeback (status `ASSESSED`) and
        adds its amount to the appointment's `chargeback_cents`."

        Design: Corner/calculations/late_checkin_within_grace_no_chargeback
        """
        region, (vendor,), depot = _dock()
        appt = book_appointment(depot["id"], vendor["id"], "2026-09-02",
                                start_time="09:00", end_time="09:30")
        api.set_clock("2026-09-02T09:15:00Z", regional_ops_headers)
        checked = validate_success(api.check_in_appointment(appt["id"], DM))
        assert checked["status"] == "CHECKED_IN"
        assert checked["chargeback_cents"] == 0, (
            "09:15 is exactly start + 15 minutes; later-than means no late chargeback"
        )

    def test_checkin_beyond_grace_assesses_late_chargeback(self, api, regional_ops_headers):
        """PRD §3.2: "If the check-in time is later than `start_time` plus a fifteen-minute grace period, the
        system immediately assesses a `LATE_CHECKIN` chargeback (status `ASSESSED`) and
        adds its amount to the appointment's `chargeback_cents`."
        PRD §3.6: "The base is 15000 cents for `LATE_CHECKIN`, 75000 cents for `NO_SHOW`, and 25000 cents
        for `OVER_PALLET_COUNT`."

        Design: Corner/calculations/late_checkin_within_grace_no_chargeback
        """
        region, (vendor,), depot = _dock()
        appt = book_appointment(depot["id"], vendor["id"], "2026-09-02",
                                start_time="09:00", end_time="09:30")
        api.set_clock("2026-09-02T09:16:00Z", regional_ops_headers)
        checked = validate_success(api.check_in_appointment(appt["id"], DM))
        assert checked["status"] == "CHECKED_IN"
        assert checked["chargeback_cents"] == 15000

    def test_checkin_from_completed_rejected(self, api, regional_ops_headers):
        """PRD §3.2: "Check-in requires the appointment to be `BOOKED`, requires the current logical date to
        equal the appointment's `delivery_date`, and requires the current logical time
        to be at or before the appointment's `end_time`; a check-in after the window
        closes is rejected with `ERR_APPOINTMENT_CONFLICT`."
        PRD §2.9: "then state-machine admissibility (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/appointment_checkin_from_completed_returns_invalid_state
        """
        ctx = setup_received_pallets(delivery_date="2026-09-02", num_pallets=1)
        completed = validate_success(api.complete_appointment(ctx["appointment"]["id"], DM))
        assert completed["status"] == "COMPLETED"
        validate_error(
            api.check_in_appointment(ctx["appointment"]["id"], DM), ApiErrorId.ERR_INVALID_STATE
        )


class TestUnloadFee:
    @pytest.mark.parametrize(
        "pallet_count,expected_fee",
        [(10, 45000), (11, 56925), (25, 129375), (26, 152100)],
        ids=["tier1_at_10", "tier2_at_11", "tier2_at_25", "tier3_at_26"],
    )
    def test_unload_fee_tier_boundaries(self, api, regional_ops_headers, pallet_count, expected_fee):
        """PRD §3.2: "the base fee is the booked `pallet_count` multiplied by a per-pallet fee of 4500 cents,
        then scaled by a tier multiplier — 1.00 when the booked count is at most 10
        pallets, 1.15 when it is more than 10 and at most 25, and 1.30 when it exceeds
        25 — with the product rounded half-up to whole cents."

        Design: Corner/calculations/unload_fee_tier_boundaries
        """
        region = create_region()
        vendor = create_vendor()
        depot = create_depot(region["id"], dock_count=4, dock_hours_open="08:00",
                             dock_hours_close="18:00")
        item = create_active_item(vendor["id"], case_pack_qty=1, cases_per_layer=1, max_layers=1)
        appt = book_appointment(depot["id"], vendor["id"], "2026-09-02",
                                start_time="08:00", end_time="08:30", pallet_count=pallet_count)
        api.set_clock("2026-09-02T08:05:00Z", regional_ops_headers)
        check_in_appointment(appt["id"])
        for _ in range(pallet_count):
            receive_pallet(appt["id"], item["id"], 1)
        completed = validate_success(api.complete_appointment(appt["id"], DM))
        assert completed["status"] == "COMPLETED"
        assert completed["unload_fee_cents"] == expected_fee, (
            f"{pallet_count} pallets: expected fee {expected_fee}, got {completed['unload_fee_cents']}"
        )


class TestCompletionGuards:
    def test_complete_requires_exact_pallet_count(self, api, regional_ops_headers):
        """PRD §3.2: "Completion requires the appointment to be `CHECKED_IN`, and it requires the count of
        pallet rows received under the appointment to exactly equal the booked
        `pallet_count` — otherwise the request fails with `ERR_INVALID_STATE` (HTTP
        409)."

        Design: Corner/validations/complete_requires_exact_pallet_count
        """
        region, (vendor,), depot = _dock()
        item = create_active_item(vendor["id"])
        appt = book_appointment(depot["id"], vendor["id"], "2026-09-02",
                                start_time="09:00", end_time="09:30", pallet_count=1)
        api.set_clock("2026-09-02T09:05:00Z", regional_ops_headers)
        check_in_appointment(appt["id"])
        validate_error(api.complete_appointment(appt["id"], DM), ApiErrorId.ERR_INVALID_STATE)

class TestNoShowRollover:
    def test_no_show_auto_transition_assesses_chargeback(self, api, regional_ops_headers):
        """PRD §3.2: "If the logical clock advances past the end of the `delivery_date` with no check-in
        recorded, the appointment auto-transitions from `BOOKED` to `NO_SHOW`, and a
        `NO_SHOW` chargeback is assessed and added to `chargeback_cents` in the same
        pass."
        PRD §3.6: "The base is 15000 cents for `LATE_CHECKIN`, 75000 cents for `NO_SHOW`, and 25000 cents
        for `OVER_PALLET_COUNT`."

        Design: Corner/errors/no_show_chargeback_auto_assessed_on_rollover
        """
        region, (vendor,), depot = _dock()
        appt = book_appointment(depot["id"], vendor["id"], "2026-09-01",
                                start_time="09:00", end_time="09:30")
        api.set_clock("2026-09-02T00:00:01Z", regional_ops_headers)
        after = validate_success(api.get_appointment(appt["id"], DM))
        assert after["status"] == "NO_SHOW"
        assert after["chargeback_cents"] == 75000, (
            f"NO_SHOW base 75000 with first-offense multiplier, got {after['chargeback_cents']}"
        )


class TestPalletReceipt:
    def test_pallet_unit_qty_must_match_pallet_qty_units(self, api, regional_ops_headers):
        """PRD §3.3: "Receipt supplies the `appointment_id`, the `item_id`, and the physical `unit_qty` on the
        pallet, which must equal the item's `pallet_qty_units` exactly — a mismatch is a
        consistency failure rejected with `ERR_CONSTRAINT_VIOLATION` (HTTP 422)."

        Design: Corner/validations/pallet_unit_qty_must_match_pallet_qty_units
        """
        region, (vendor,), depot = _dock()
        item = create_active_item(vendor["id"])
        appt = book_appointment(depot["id"], vendor["id"], "2026-09-02",
                                start_time="09:00", end_time="09:30", pallet_count=1)
        api.set_clock("2026-09-02T09:05:00Z", regional_ops_headers)
        check_in_appointment(appt["id"])
        resp = api.create_pallet(
            {"appointment_id": appt["id"], "item_id": item["id"], "unit_qty": 479}, DM
        )
        validate_error(resp, ApiErrorId.ERR_CONSTRAINT_VIOLATION)
