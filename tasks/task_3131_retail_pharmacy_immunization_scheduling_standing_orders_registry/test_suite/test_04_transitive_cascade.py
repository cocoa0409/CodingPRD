"""Transitive cascade tests — administer fan-out chain and excursion cascade to
review-consent eligible-lot precondition.

PRD §3.5 administration fan-out, §3.2 excursion auto-quarantine, §3.4 review gate.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_store, create_product, create_protocol, create_patient,
    create_lot, book_appointment, walk_appointment_to_consented,
    administer_appointment, create_clinic_event_for_lot,
    get_submission_for_record, get_observation_session_for_record,
)


def _mgr():
    return TEST_USERS["store_manager_headers"]


def _co():
    return TEST_USERS["compliance_headers"]


def _tech():
    return TEST_USERS["technician_headers"]


def _pharm():
    return TEST_USERS["pharmacist_headers"]


def _imm():
    return TEST_USERS["immunizer_headers"]


def _obs():
    return TEST_USERS["observer_headers"]


class TestAdministerFaninChain:
    """Design: Difficulty/transitive_cascade/administer_fanin_chain_appointment_record_lot_registry_observation_event"""

    def test_administer_spawns_record_submission_observation_and_event_counter(self, api):
        """PRD §3.5: "A successful administration commits five effects atomically in one request. First, an `ImmunizationRecord` is created in `COMPLETED` status: its `appointment_id` ties it to the appointment, `patient_id` is copied from the appointment, `lot_id` records the source lot, `administered_by` captures the immunizer's opaque identifier, `administered_at` is stamped from the logical clock, `dose_number` is copied from the appointment, and `charge_cents` with its `billing_channel` is computed by the adjudication waterfall of §3.6. Second, the lot's `doses_available` decrements by one and the lot's `version` bumps. Third, a `RegistrySubmission` springs into existence in `PENDING` status with its payload rendered per the governing protocol's format and its deadline computed from the administration instant. Fourth, an `ObservationSession` is created in `IN_PROGRESS` status. Fifth, the counters roll up: if the appointment is attached to a clinic event, the event's `doses_administered` increments by one"

        Design: Difficulty/transitive_cascade/administer_fanin_chain_appointment_record_lot_registry_observation_event
        """
        set_clock("2026-09-01T09:00:00Z")
        store = create_store(store_number="S-700", state_code="CA")
        product = create_product(cash_price_cents=5000)
        create_protocol(vaccine_product_id=product["id"], registry_format="FLAT_FILE_CSV",
                        registry_deadline_hours=24, max_doses_per_patient_per_day=2)
        patient = create_patient(full_name="Pat Four", date_of_birth="1980-01-01", high_risk_flag=True)
        lot = create_lot(store["id"], product["id"], doses_received=10)

        event = create_clinic_event_for_lot(store["id"], lot["id"], doses_reserved=4)
        # Advance into event window to activate
        set_clock("2026-09-01T10:30:00Z")
        event_now = get_success_data(api_client.get_clinic_event(event["id"], _mgr()))
        assert event_now["status"] == "ACTIVE"
        lot_after_checkout = get_success_data(api_client.get_lot(lot["id"], _mgr()))
        assert lot_after_checkout["doses_available"] == 6

        appt = walk_appointment_to_consented(store, patient, product,
                                             slot_start="2026-09-01T11:00:00Z",
                                             tech_user_id="user-tech-1", pharm_user_id="user-pharm-1")
        record = administer_appointment(appt["id"], lot, immunizer_user_id="user-imm-1",
                                        clinic_event_id=event["id"])
        assert record["charge_cents"] == 5000
        assert record["billing_channel"] == "CASH"

        sub = get_submission_for_record(record["id"])
        assert sub["status"] == "PENDING"
        assert sub["due_at"] == "2026-09-02T10:30:00Z"

        obs = get_observation_session_for_record(record["id"])
        assert obs["status"] == "IN_PROGRESS"
        assert obs["required_minutes"] == 30

        event_final = get_success_data(api_client.get_clinic_event(event["id"], _mgr()))
        assert event_final["doses_administered"] == 1

        lot_final = get_success_data(api_client.get_lot(lot["id"], _mgr()))
        assert lot_final["doses_available"] == 5

    def test_high_risk_patient_gets_thirty_minute_observation(self, api):
        """PRD §3.7: "The session's `required_minutes` is 30 when the patient's `high_risk_flag` is true, and otherwise the product's `observation_minutes`"

        Design: Difficulty/transitive_cascade/administer_fanin_chain_appointment_record_lot_registry_observation_event
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-700", state_code="CA")
        product = create_product(observation_minutes=15)
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Four", date_of_birth="1980-01-01", high_risk_flag=True)
        lot = create_lot(store["id"], product["id"], doses_received=5)

        appt = walk_appointment_to_consented(store, patient, product,
                                             slot_start="2026-09-01T10:00:00Z")
        record = administer_appointment(appt["id"], lot)
        obs = get_observation_session_for_record(record["id"])
        assert obs["required_minutes"] == 30


class TestExcursionQuarantineCascadeToReviewConsent:
    """Design: Difficulty/transitive_cascade/excursion_quarantine_cascade_to_release_and_cumulative_regrade"""

    def test_excursion_quarantine_blocks_review_consent_with_no_eligible_lot(self, api):
        """PRD §3.4: "there must exist at least one `RELEASED`, unexpired lot of the product at the store with `doses_available` above zero, or the appointment must be attached to an `ACTIVE` clinic event with reserved doses remaining (`ERR_NO_ELIGIBLE_LOT`)"
        PRD §3.2: "Any excursion at all — however slight — auto-quarantines the lot"

        Design: Difficulty/transitive_cascade/excursion_quarantine_cascade_to_release_and_cumulative_regrade
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-800", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"], registry_deadline_hours=24)
        patient = create_patient(full_name="Pat Five", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)

        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z", is_walk_in=True)
        api_client.check_in_appointment(appt["id"], _tech())
        api_client.submit_questionnaire(appt["id"],
            {"answers": {"FEVER_TODAY": False, "PREGNANT": False, "IMMUNOCOMPROMISED": False, "PRIOR_ANAPHYLAXIS": False}},
            _tech())
        appt_now = get_success_data(api_client.get_appointment(appt["id"], _pharm()))

        # Post excursion reading — auto-quarantines the only lot
        api_client.create_temperature_reading(lot["id"],
            {"recorded_at": "2026-09-01T09:58:00Z", "temperature_c": 12.0}, _mgr())
        lot_now = get_success_data(api_client.get_lot(lot["id"], _mgr()))
        assert lot_now["status"] == "QUARANTINED"
        assert lot_now["quarantine_reason"] == "EXCURSION"

        # Review-consent fails with ERR_NO_ELIGIBLE_LOT
        err = validate_error(
            api_client.review_consent(appt["id"],
                {"expected_appointment_version": appt_now["version"], "outcome": "CLEAR"},
                _pharm()),
            ApiErrorId.ERR_NO_ELIGIBLE_LOT,
        )
        assert err["error_id"] == "ERR_NO_ELIGIBLE_LOT"

        # Appointment stays SCREENED
        appt_after = get_success_data(api_client.get_appointment(appt["id"], _pharm()))
        assert appt_after["status"] == "SCREENED"

    def test_excursion_severity_tier_moderate_for_delta_4(self, api):
        """PRD §3.2: "greater than 2.0 and at most 5.0 degrees is MODERATE"

        Design: Difficulty/transitive_cascade/excursion_quarantine_cascade_to_release_and_cumulative_regrade
        """
        store = create_store(store_number="S-800", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=5)
        resp = api_client.create_temperature_reading(lot["id"],
            {"recorded_at": "2026-09-01T09:58:00Z", "temperature_c": 12.0}, _mgr())
        reading = validate_success(resp, expected_status=201)
        assert reading["excursion_severity_tier"] == "MODERATE"
