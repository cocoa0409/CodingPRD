"""Priority-pair validation conflict tests — OCC stale-version beats contraindication,
and raw-capacity beats over-reservation.

PRD §2.6 validation ordering, §2.7 OCC.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_store, create_product, create_protocol, create_patient,
    create_lot, book_appointment,
)


def _mgr():
    return TEST_USERS["store_manager_headers"]


def _co():
    return TEST_USERS["compliance_headers"]


def _tech():
    return TEST_USERS["technician_headers"]


def _pharm():
    return TEST_USERS["pharmacist_headers"]


class TestReviewConsentStaleOccBeatsContraindication:
    """Design: Difficulty/priority_pair_validation_conflict/review_consent_stale_occ_beats_contraindication"""

    def test_stale_version_rejected_before_contraindication(self, api):
        """PRD §2.6: "then — on the two endpoints that declare an optimistic-concurrency field — the stale-version check, which runs before any business-rule validation."
        PRD §2.7: "on both, the version check runs before business-rule validation, so a stale request fails with the 412 even if it would also have failed a later check."

        Design: Difficulty/priority_pair_validation_conflict/review_consent_stale_occ_beats_contraindication
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-900", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Six", date_of_birth="1980-01-01", allergy_flags=["EGG"])
        lot = create_lot(store["id"], product["id"], doses_received=5)

        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z", is_walk_in=True)
        api_client.check_in_appointment(appt["id"], _tech())
        # Pharmacist captures version BEFORE questionnaire
        appt_stale = get_success_data(api_client.get_appointment(appt["id"], _pharm()))
        stale_version = appt_stale["version"]
        # Questionnaire bumps version
        api_client.submit_questionnaire(appt["id"],
            {"answers": {"FEVER_TODAY": False, "PREGNANT": False, "IMMUNOCOMPROMISED": False, "PRIOR_ANAPHYLAXIS": False}},
            _tech())

        err = validate_error(
            api_client.review_consent(appt["id"],
                {"expected_appointment_version": stale_version, "outcome": "CLEAR"},
                _pharm()),
            ApiErrorId.ERR_STALE_APPOINTMENT_VERSION,
        )
        assert err["error_id"] == "ERR_STALE_APPOINTMENT_VERSION"

    def test_appointment_remains_screened_after_stale_rejection(self, api):
        """PRD §2.7: "the review is rejected with `ERR_STALE_APPOINTMENT_VERSION` (HTTP 412), so a pharmacist never clears a screening snapshot they have not seen."

        Design: Difficulty/priority_pair_validation_conflict/review_consent_stale_occ_beats_contraindication
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-900", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Six", date_of_birth="1980-01-01", allergy_flags=["EGG"])
        lot = create_lot(store["id"], product["id"], doses_received=5)

        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z", is_walk_in=True)
        api_client.check_in_appointment(appt["id"], _tech())
        appt_stale = get_success_data(api_client.get_appointment(appt["id"], _pharm()))
        api_client.submit_questionnaire(appt["id"],
            {"answers": {"FEVER_TODAY": False, "PREGNANT": False, "IMMUNOCOMPROMISED": False, "PRIOR_ANAPHYLAXIS": False}},
            _tech())

        validate_error(
            api_client.review_consent(appt["id"],
                {"expected_appointment_version": appt_stale["version"], "outcome": "CLEAR"},
                _pharm()),
            ApiErrorId.ERR_STALE_APPOINTMENT_VERSION,
        )
        appt_after = get_success_data(api_client.get_appointment(appt["id"], _pharm()))
        assert appt_after["status"] == "SCREENED"


class TestClinicEventCreateInsufficientDosesBeatsOverReservation:
    """Design: Difficulty/priority_pair_validation_conflict/clinic_event_create_insufficient_doses_beats_over_reservation"""

    def test_insufficient_doses_returned_when_both_rules_fire(self, api):
        """PRD §3.9: "Capacity is checked in two layers at creation, raw capacity first and overlap second."
        PRD §3.9: "Raw capacity: `doses_reserved` may not exceed the mobile lot's current `doses_available`, or the creation fails with `ERR_INSUFFICIENT_DOSES`."
        PRD §3.9: "the new event's `doses_reserved` must fit within the lot's `doses_available` minus that overlapping reserved sum, or creation fails with `ERR_MOBILE_LOT_OVER_RESERVED`. The overlap check runs only after raw capacity passes."

        Design: Difficulty/priority_pair_validation_conflict/clinic_event_create_insufficient_doses_beats_over_reservation
        """
        store = create_store(store_number="S-1000", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=10)
        create_protocol(vaccine_product_id=product["id"])

        # Existing PLANNED event: window 10:00-12:00, reserved 6
        api_client.create_clinic_event({
            "store_id": store["id"], "employer_name": "Acme Corp",
            "event_start": "2026-09-01T10:00:00Z", "event_end": "2026-09-01T12:00:00Z",
            "mobile_lot_id": lot["id"], "doses_reserved": 6,
        }, _mgr())

        # New event: window 11:00-13:00 (overlaps), reserved 11 — exceeds raw capacity 10 AND 11 > 10-6=4
        err = validate_error(
            api_client.create_clinic_event({
                "store_id": store["id"], "employer_name": "Beta LLC",
                "event_start": "2026-09-01T11:00:00Z", "event_end": "2026-09-01T13:00:00Z",
                "mobile_lot_id": lot["id"], "doses_reserved": 11,
            }, _mgr()),
            ApiErrorId.ERR_INSUFFICIENT_DOSES,
        )
        assert err["error_id"] == "ERR_INSUFFICIENT_DOSES"

    def test_over_reservation_fires_only_after_raw_capacity_passes(self, api):
        """PRD §3.9: "The overlap check runs only after raw capacity passes."

        Design: Difficulty/priority_pair_validation_conflict/clinic_event_create_insufficient_doses_beats_over_reservation
        """
        store = create_store(store_number="S-1000", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=10)
        create_protocol(vaccine_product_id=product["id"])

        # Existing event reserves 6
        api_client.create_clinic_event({
            "store_id": store["id"], "employer_name": "Acme Corp",
            "event_start": "2026-09-01T10:00:00Z", "event_end": "2026-09-01T12:00:00Z",
            "mobile_lot_id": lot["id"], "doses_reserved": 6,
        }, _mgr())

        # New event reserved 5 (raw capacity 5 <= 10 passes) but overlaps and 5 > 10-6=4
        err = validate_error(
            api_client.create_clinic_event({
                "store_id": store["id"], "employer_name": "Beta LLC",
                "event_start": "2026-09-01T11:00:00Z", "event_end": "2026-09-01T13:00:00Z",
                "mobile_lot_id": lot["id"], "doses_reserved": 5,
            }, _mgr()),
            ApiErrorId.ERR_MOBILE_LOT_OVER_RESERVED,
        )
        assert err["error_id"] == "ERR_MOBILE_LOT_OVER_RESERVED"
