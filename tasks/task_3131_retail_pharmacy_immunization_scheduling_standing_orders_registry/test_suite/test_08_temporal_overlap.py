"""Resource temporal overlap tests — appointment slot half-open intervals and
clinic event mobile-lot aggregate capacity across overlapping windows.

PRD §3.3 slot overlap, §3.9 overlap reservation capacity.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    create_store, create_product, create_protocol, create_patient,
    create_lot, book_appointment, create_clinic_event_for_lot,
)


def _mgr():
    return TEST_USERS["store_manager_headers"]


def _co():
    return TEST_USERS["compliance_headers"]


def _tech():
    return TEST_USERS["technician_headers"]


class TestAppointmentSlotOverlapHalfOpenFixed15Min:
    """Design: Difficulty/resource_temporal_overlap/appointment_slot_overlap_half_open_fixed_15min"""

    def test_overlapping_slot_rejected(self, api):
        """PRD §3.3: "For non-walk-in appointments, slot overlap is enforced per store: the new appointment's interval — half-open, from `slot_start` through the fifteen minutes following it — must not overlap the corresponding interval of any existing `SCHEDULED` or `CHECKED_IN` appointment at the same store."

        Design: Difficulty/resource_temporal_overlap/appointment_slot_overlap_half_open_fixed_15min
        """
        store = create_store(store_number="S-1500", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient_a = create_patient(full_name="Pat Ten A", date_of_birth="1980-01-01")
        patient_b = create_patient(full_name="Pat Ten B", date_of_birth="1981-01-01")

        book_appointment(store["id"], patient_a["id"], product["id"], slot_start="2026-09-02T10:00:00Z")
        err = validate_error(
            api_client.create_appointment({
                "store_id": store["id"], "patient_id": patient_b["id"],
                "vaccine_product_id": product["id"], "slot_start": "2026-09-02T10:14:00Z",
            }, _tech()),
            ApiErrorId.ERR_SLOT_CONFLICT,
        )
        assert err["error_id"] == "ERR_SLOT_CONFLICT"

    def test_back_to_back_adjacency_allowed(self, api):
        """PRD §3.3: "Because the intervals are half-open, back-to-back adjacency is allowed: a 10:15 slot may follow a 10:00 slot."

        Design: Difficulty/resource_temporal_overlap/appointment_slot_overlap_half_open_fixed_15min
        """
        store = create_store(store_number="S-1500", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient_a = create_patient(full_name="Pat Ten A", date_of_birth="1980-01-01")
        patient_c = create_patient(full_name="Pat Ten C", date_of_birth="1982-01-01")

        book_appointment(store["id"], patient_a["id"], product["id"], slot_start="2026-09-02T10:00:00Z")
        appt = book_appointment(store["id"], patient_c["id"], product["id"], slot_start="2026-09-02T10:15:00Z")
        assert appt["status"] == "SCHEDULED"


class TestClinicEventMobileLotAggregateCapacityOverlappingWindows:
    """Design: Difficulty/resource_temporal_overlap/clinic_event_mobile_lot_aggregate_capacity_overlapping_windows"""

    def test_touching_endpoints_do_not_overlap(self, api):
        """PRD §3.9: "for the same mobile lot, consider every other `PLANNED` or `ACTIVE` event whose window overlaps the new event's window — intervals being closed at the start and open at the end, so two events that merely touch endpoints do not overlap"

        Design: Difficulty/resource_temporal_overlap/clinic_event_mobile_lot_aggregate_capacity_overlapping_windows
        """
        store = create_store(store_number="S-1600", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=10)
        create_protocol(vaccine_product_id=product["id"])

        # E1: 10:00-12:00, reserved 6
        e1 = create_clinic_event_for_lot(store["id"], lot["id"],
            event_start="2026-09-01T10:00:00Z", event_end="2026-09-01T12:00:00Z",
            doses_reserved=6, employer_name="Acme Corp")
        # E2: 12:00-14:00, reserved 9 — touching endpoint, no overlap
        e2 = create_clinic_event_for_lot(store["id"], lot["id"],
            event_start="2026-09-01T12:00:00Z", event_end="2026-09-01T14:00:00Z",
            doses_reserved=9, employer_name="Beta LLC")
        assert e2["status"] == "PLANNED"

    def test_overlapping_window_aggregate_rejected(self, api):
        """PRD §3.9: "the new event's `doses_reserved` must fit within the lot's `doses_available` minus that overlapping reserved sum, or creation fails with `ERR_MOBILE_LOT_OVER_RESERVED`."

        Design: Difficulty/resource_temporal_overlap/clinic_event_mobile_lot_aggregate_capacity_overlapping_windows
        """
        store = create_store(store_number="S-1600", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=10)
        create_protocol(vaccine_product_id=product["id"])

        # E1: 10:00-12:00 reserved 6; E2: 12:00-14:00 reserved 9 (touching, allowed)
        create_clinic_event_for_lot(store["id"], lot["id"],
            event_start="2026-09-01T10:00:00Z", event_end="2026-09-01T12:00:00Z",
            doses_reserved=6, employer_name="Acme Corp")
        create_clinic_event_for_lot(store["id"], lot["id"],
            event_start="2026-09-01T12:00:00Z", event_end="2026-09-01T14:00:00Z",
            doses_reserved=9, employer_name="Beta LLC")

        # E3: 11:00-13:00 reserved 5 — overlaps E1; raw capacity 5<=10 passes but 5 > 10-6=4 fails
        err = validate_error(
            api_client.create_clinic_event({
                "store_id": store["id"], "employer_name": "Gamma Inc",
                "event_start": "2026-09-01T11:00:00Z", "event_end": "2026-09-01T13:00:00Z",
                "mobile_lot_id": lot["id"], "doses_reserved": 5,
            }, _mgr()),
            ApiErrorId.ERR_MOBILE_LOT_OVER_RESERVED,
        )
        assert err["error_id"] == "ERR_MOBILE_LOT_OVER_RESERVED"
