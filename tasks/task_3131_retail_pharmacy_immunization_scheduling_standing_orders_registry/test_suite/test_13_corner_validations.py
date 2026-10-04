"""Corner tests — validations section: contraindication, retired protocol, daily
dose cap, segregation of duties, lot referential failures, expired lot,
suspended store, walk-in slot bypass, clinic event timing, observation rules.

PRD §3.4 review gate, §3.5 administer rules, §3.7 observation, §3.9 events.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, build_user_headers,
)
from test_helpers.fixtures import (
    set_clock, create_store, create_product, create_protocol, create_patient,
    create_lot, book_appointment, walk_appointment_to_screened,
    walk_appointment_to_consented, administer_appointment, full_administration,
    get_observation_session_for_record,
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


class TestContraindicationBlocksClearAtReview:
    """Design: Corner/validations/contraindication_blocks_clear_at_review"""

    def test_contraindication_detected_blocks_clear(self, api):
        """PRD §3.4: "the questionnaire's `contraindication_detected` must be false (`ERR_CONTRAINDICATION_DETECTED`)"
        PRD §3.4: "On submission the system computes `contraindication_detected` — true when any answer, or any entry in the patient's `allergy_flags`, is a hard contraindication for the appointment's vaccine"

        Design: Corner/validations/contraindication_blocks_clear_at_review
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-19", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat CI2", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z", is_walk_in=True)
        api_client.check_in_appointment(appt["id"], _tech())
        q = validate_success(api_client.submit_questionnaire(appt["id"],
            {"answers": {"FEVER_TODAY": False, "PRIOR_ANAPHYLAXIS": True}}, _tech()),
            expected_status=201)
        assert q["contraindication_detected"] is True

        appt_now = get_success_data(api_client.get_appointment(appt["id"], _pharm()))
        err = validate_error(
            api_client.review_consent(appt["id"],
                {"expected_appointment_version": appt_now["version"], "outcome": "CLEAR"},
                _pharm()),
            ApiErrorId.ERR_CONTRAINDICATION_DETECTED,
        )
        assert err["error_id"] == "ERR_CONTRAINDICATION_DETECTED"

        appt_after = get_success_data(api_client.get_appointment(appt["id"], _pharm()))
        assert appt_after["status"] == "SCREENED"


class TestRetiredProtocolBlocksReviewConsent:
    """Design: Corner/validations/retired_protocol_blocks_review_consent"""

    def test_retired_protocol_blocks_review(self, api):
        """PRD §3.1: "a `RETIRED` protocol authorizes nothing new — review against a retired protocol fails with `ERR_PROTOCOL_NOT_ACTIVE`."

        Design: Corner/validations/retired_protocol_blocks_review_consent
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-20", state_code="CA")
        product = create_product()
        protocol = create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat PR", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z", is_walk_in=True)
        api_client.check_in_appointment(appt["id"], _tech())
        api_client.submit_questionnaire(appt["id"], {"answers": {"FEVER_TODAY": False}}, _tech())

        api_client.update_state_protocol(protocol["id"], {"status": "RETIRED"}, _co())
        appt_now = get_success_data(api_client.get_appointment(appt["id"], _pharm()))

        err = validate_error(
            api_client.review_consent(appt["id"],
                {"expected_appointment_version": appt_now["version"], "outcome": "CLEAR"},
                _pharm()),
            ApiErrorId.ERR_PROTOCOL_NOT_ACTIVE,
        )
        assert err["error_id"] == "ERR_PROTOCOL_NOT_ACTIVE"


class TestDailyDoseCapBlocksThirdReview:
    """Design: Corner/validations/daily_dose_cap_blocks_third_review"""

    def test_third_dose_same_day_rejected(self, api):
        """PRD §3.4: "the patient's `scheduled_dose_count_today` must be below the protocol's `max_doses_per_patient_per_day` (`ERR_DAILY_DOSE_LIMIT_REACHED`)"
        PRD §3.1: "The `max_doses_per_patient_per_day` field caps how many distinct vaccine administrations one patient may receive in a single calendar day at a store and defaults to 2 when omitted."

        Design: Corner/validations/daily_dose_cap_blocks_third_review
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-21", state_code="CA")
        product_flu = create_product(cvx_code="141", name="Influenza Quadrivalent", cash_price_cents=5000)
        product_cov = create_product(cvx_code="207", name="COVID-like", cash_price_cents=6000)
        product_hbv = create_product(cvx_code="045", name="Hepatitis B", cash_price_cents=7000, doses_per_series=3)
        create_protocol(vaccine_product_id=product_flu["id"], max_doses_per_patient_per_day=2)
        create_protocol(vaccine_product_id=product_cov["id"], max_doses_per_patient_per_day=2)
        create_protocol(vaccine_product_id=product_hbv["id"], max_doses_per_patient_per_day=2)
        patient = create_patient(full_name="Pat Cap", date_of_birth="1980-01-01")
        lot_flu = create_lot(store["id"], product_flu["id"], lot_number="L1", doses_received=10)
        lot_cov = create_lot(store["id"], product_cov["id"], lot_number="L2", doses_received=10)
        lot_hbv = create_lot(store["id"], product_hbv["id"], lot_number="L3", doses_received=10)

        # Dose 1: FLU
        full_administration(store, patient, product_flu, lot_flu,
                            tech_user_id="user-tech-1", pharm_user_id="user-pharm-1",
                            imm_user_id="user-imm-1")
        # Dose 2: COV
        full_administration(store, patient, product_cov, lot_cov,
                            slot_start="2026-09-01T10:30:00Z",
                            tech_user_id="user-tech-1", pharm_user_id="user-pharm-1",
                            imm_user_id="user-imm-1")

        # Third: HBV, walk to SCREENED
        appt3 = book_appointment(store["id"], patient["id"], product_hbv["id"],
                                 slot_start="2026-09-01T11:00:00Z", is_walk_in=True)
        api_client.check_in_appointment(appt3["id"], _tech())
        api_client.submit_questionnaire(appt3["id"], {"answers": {"FEVER_TODAY": False}}, _tech())
        appt3_now = get_success_data(api_client.get_appointment(appt3["id"], _pharm()))

        err = validate_error(
            api_client.review_consent(appt3["id"],
                {"expected_appointment_version": appt3_now["version"], "outcome": "CLEAR"},
                _pharm()),
            ApiErrorId.ERR_DAILY_DOSE_LIMIT_REACHED,
        )
        assert err["error_id"] == "ERR_DAILY_DOSE_LIMIT_REACHED"

        appt3_after = get_success_data(api_client.get_appointment(appt3["id"], _pharm()))
        assert appt3_after["status"] == "SCREENED"


class TestSegregationOfDutiesSameActorBlockedAtReviewAndAdminister:
    """Design: Corner/validations/segregation_of_duties_same_actor_blocked_at_review_and_administer"""

    def test_checkin_actor_cannot_review(self, api):
        """PRD §2.9: "On any single appointment, the operator who performed check-in may not be the pharmacist who completes contraindication review, and the pharmacist who completed review may not be the immunizer who administers the dose. Either collision is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

        Design: Corner/validations/segregation_of_duties_same_actor_blocked_at_review_and_administer
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-22", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat SOD", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z", is_walk_in=True)
        # Check-in by user-same-1
        api_client.check_in_appointment(appt["id"], build_user_headers("user-same-1", "PharmacyTechnician"))
        api_client.submit_questionnaire(appt["id"], {"answers": {"FEVER_TODAY": False}}, _tech())
        appt_now = get_success_data(api_client.get_appointment(appt["id"], _pharm()))

        # Review by same user fails
        err = validate_error(
            api_client.review_consent(appt["id"],
                {"expected_appointment_version": appt_now["version"], "outcome": "CLEAR"},
                build_user_headers("user-same-1", "Pharmacist")),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
        )
        assert err["error_id"] == "ERR_SEGREGATION_OF_DUTIES_VIOLATION"

    def test_reviewer_cannot_administer(self, api):
        """PRD §2.9: "the pharmacist who completed review may not be the immunizer who administers the dose. Either collision is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

        Design: Corner/validations/segregation_of_duties_same_actor_blocked_at_review_and_administer
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-22", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat SOD", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        appt = walk_appointment_to_consented(store, patient, product,
                                             slot_start="2026-09-01T10:00:00Z",
                                             tech_user_id="user-tech-1", pharm_user_id="user-pharm-1")
        # Administer by the reviewing pharmacist fails
        err = validate_error(
            api_client.administer(appt["id"],
                {"lot_id": lot["id"], "expected_lot_version": 1},
                build_user_headers("user-pharm-1", "Immunizer")),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
        )
        assert err["error_id"] == "ERR_SEGREGATION_OF_DUTIES_VIOLATION"


class TestAdministerLotReferentialFailures:
    """Design: Corner/validations/administer_lot_referential_failures"""

    def test_quarantined_lot_rejected(self, api):
        """PRD §3.5: "The target lot must be `RELEASED` and unexpired — a quarantined, retired, expired, or otherwise unfit lot is rejected with `ERR_LOT_NOT_ADMINISTERABLE`"

        Design: Corner/validations/administer_lot_referential_failures
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-23", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat L1", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        appt = walk_appointment_to_consented(store, patient, product,
                                             slot_start="2026-09-01T10:00:00Z")
        # Quarantine only after review — a quarantined only-lot would otherwise
        # fail review's ERR_NO_ELIGIBLE_LOT gate (PRD §3.4) before administer.
        api_client.quarantine_lot(lot["id"], _mgr())
        err = validate_error(
            api_client.administer(appt["id"], {"lot_id": lot["id"], "expected_lot_version": 2}, _imm()),
            ApiErrorId.ERR_LOT_NOT_ADMINISTERABLE,
        )
        assert err["error_id"] == "ERR_LOT_NOT_ADMINISTERABLE"

    def test_product_mismatch_rejected(self, api):
        """PRD §3.5: "must be a lot of the appointment's product (`ERR_LOT_PRODUCT_MISMATCH`)"

        Design: Corner/validations/administer_lot_referential_failures
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-23", state_code="CA")
        product_flu = create_product(cvx_code="141", name="Flu")
        product_cov = create_product(cvx_code="207", name="COVID")
        create_protocol(vaccine_product_id=product_flu["id"])
        create_protocol(vaccine_product_id=product_cov["id"])
        patient = create_patient(full_name="Pat L2", date_of_birth="1981-01-01")
        lot_flu = create_lot(store["id"], product_flu["id"], lot_number="LF", doses_received=5)
        lot_cov = create_lot(store["id"], product_cov["id"], lot_number="LC", doses_received=5)
        appt = walk_appointment_to_consented(store, patient, product_flu,
                                             slot_start="2026-09-01T10:00:00Z")
        err = validate_error(
            api_client.administer(appt["id"], {"lot_id": lot_cov["id"], "expected_lot_version": 1}, _imm()),
            ApiErrorId.ERR_LOT_PRODUCT_MISMATCH,
        )
        assert err["error_id"] == "ERR_LOT_PRODUCT_MISMATCH"

    def test_depleted_lot_rejected(self, api):
        """PRD §3.5: "must have `doses_available` above zero (`ERR_LOT_DEPLETED`)"

        Design: Corner/validations/administer_lot_referential_failures
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-23", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient_drain = create_patient(full_name="Pat Drain", date_of_birth="1982-01-01")
        patient = create_patient(full_name="Pat L3", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], lot_number="LD", doses_received=1)
        # A second eligible lot of the same product keeps review's
        # ERR_NO_ELIGIBLE_LOT gate (PRD §3.4) satisfied once LD is drained,
        # so the administer attempt below reaches the per-lot depleted check.
        create_lot(store["id"], product["id"], lot_number="LB", doses_received=5)

        # Drain the lot
        appt_d = walk_appointment_to_consented(store, patient_drain, product,
                                               slot_start="2026-09-01T09:56:00Z",
                                               tech_user_id="user-tech-1", pharm_user_id="user-pharm-1")
        administer_appointment(appt_d["id"], lot, immunizer_user_id="user-imm-1")

        # Now try to administer from the depleted lot
        appt = walk_appointment_to_consented(store, patient, product,
                                             slot_start="2026-09-01T10:00:00Z",
                                             tech_user_id="user-tech-1", pharm_user_id="user-pharm-1")
        lot_now = get_success_data(api_client.get_lot(lot["id"], _mgr()))
        err = validate_error(
            api_client.administer(appt["id"], {"lot_id": lot["id"], "expected_lot_version": lot_now["version"]}, _imm()),
            ApiErrorId.ERR_LOT_DEPLETED,
        )
        assert err["error_id"] == "ERR_LOT_DEPLETED"


class TestExpiredLotAndBookingOnSuspendedStore:
    """Design: Corner/validations/expired_lot_and_booking_on_suspended_store"""

    def test_administer_at_suspended_store_rejected(self, api):
        """PRD §3.1: "A `SUSPENDED` store cannot accept bookings, check-ins, or administrations — attempts against one fail with `ERR_STORE_SUSPENDED`"

        Design: Corner/validations/expired_lot_and_booking_on_suspended_store
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-24B", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Exp", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        appt = walk_appointment_to_consented(store, patient, product,
                                             slot_start="2026-09-01T10:00:00Z")
        api_client.update_store(store["id"], {"status": "SUSPENDED"}, _mgr())

        err = validate_error(
            api_client.administer(appt["id"], {"lot_id": lot["id"], "expected_lot_version": 1}, _imm()),
            ApiErrorId.ERR_STORE_SUSPENDED,
        )
        assert err["error_id"] == "ERR_STORE_SUSPENDED"

    def test_booking_at_suspended_store_rejected(self, api):
        """PRD §3.1: "A `SUSPENDED` store cannot accept bookings, check-ins, or administrations — attempts against one fail with `ERR_STORE_SUSPENDED`"

        Design: Corner/validations/expired_lot_and_booking_on_suspended_store
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-24B", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Exp", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        api_client.update_store(store["id"], {"status": "SUSPENDED"}, _mgr())

        err = validate_error(
            api_client.create_appointment({
                "store_id": store["id"], "patient_id": patient["id"],
                "vaccine_product_id": product["id"], "slot_start": "2026-09-01T11:00:00Z",
                "is_walk_in": True,
            }, _tech()),
            ApiErrorId.ERR_STORE_SUSPENDED,
        )
        assert err["error_id"] == "ERR_STORE_SUSPENDED"


class TestWalkInBypassesSlotConflictButNotEligibility:
    """Design: Corner/validations/walk_in_bypasses_slot_conflict_but_not_eligibility"""

    def test_walkin_bypasses_slot_conflict(self, api):
        """PRD §3.3: "is_walk_in may be set true to indicate a walk-in, in which case slot_start is set equal to the creation time and slot-availability checks are bypassed — but eligibility and inventory checks are not."

        Design: Corner/validations/walk_in_bypasses_slot_conflict_but_not_eligibility
        """
        store = create_store(store_number="S-25", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient1 = create_patient(full_name="Pat W1", date_of_birth="1980-01-01")
        patient2 = create_patient(full_name="Pat W2", date_of_birth="1981-01-01")

        book_appointment(store["id"], patient1["id"], product["id"],
                         slot_start="2026-09-02T10:00:00Z")
        # Non-walk-in at 10:05 conflicts
        err = validate_error(
            api_client.create_appointment({
                "store_id": store["id"], "patient_id": patient2["id"],
                "vaccine_product_id": product["id"], "slot_start": "2026-09-02T10:05:00Z",
            }, _tech()),
            ApiErrorId.ERR_SLOT_CONFLICT,
        )
        assert err["error_id"] == "ERR_SLOT_CONFLICT"

    def test_walkin_at_same_instant_succeeds(self, api):
        """PRD §3.3: "slot-availability checks are bypassed"

        Design: Corner/validations/walk_in_bypasses_slot_conflict_but_not_eligibility
        """
        store = create_store(store_number="S-25", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient1 = create_patient(full_name="Pat W1", date_of_birth="1980-01-01")
        patient3 = create_patient(full_name="Pat W3", date_of_birth="1982-01-01")

        book_appointment(store["id"], patient1["id"], product["id"],
                         slot_start="2026-09-02T10:00:00Z")
        appt = book_appointment(store["id"], patient3["id"], product["id"],
                                slot_start="2026-09-02T10:05:00Z", is_walk_in=True)
        assert appt["status"] == "SCHEDULED"


class TestClinicEventWindowMalformedAndCloseBeforeEnd:
    """Design: Corner/validations/clinic_event_window_malformed_and_close_before_end"""

    def test_event_end_equal_start_rejected(self, api):
        """PRD §3.9: "The event window must be well-formed: `event_end` strictly after `event_start` and within the same calendar day — a malformed window fails with `ERR_EVENT_STILL_RUNNING`"

        Design: Corner/validations/clinic_event_window_malformed_and_close_before_end
        """
        set_clock("2026-09-01T09:00:00Z")
        store = create_store(store_number="S-26", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=10)
        err = validate_error(
            api_client.create_clinic_event({
                "store_id": store["id"], "employer_name": "Bad Window",
                "event_start": "2026-09-02T12:00:00Z", "event_end": "2026-09-02T12:00:00Z",
                "mobile_lot_id": lot["id"], "doses_reserved": 1,
            }, _mgr()),
            ApiErrorId.ERR_EVENT_STILL_RUNNING,
        )
        assert err["error_id"] == "ERR_EVENT_STILL_RUNNING"

    def test_close_before_event_end_rejected(self, api):
        """PRD §3.9: "Closing an event is a `StoreManager` act requiring the event to be `ACTIVE` (`ERR_EVENT_NOT_ACTIVE`) and the logical clock to be at or past `event_end` (`ERR_EVENT_STILL_RUNNING`)."

        Design: Corner/validations/clinic_event_window_malformed_and_close_before_end
        """
        set_clock("2026-09-01T09:00:00Z")
        store = create_store(store_number="S-26", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=10)
        event = validate_success(api_client.create_clinic_event({
            "store_id": store["id"], "employer_name": "Acme Corp",
            "event_start": "2026-09-01T10:00:00Z", "event_end": "2026-09-01T12:00:00Z",
            "mobile_lot_id": lot["id"], "doses_reserved": 4,
        }, _mgr()), expected_status=201)
        set_clock("2026-09-01T11:00:00Z")
        err = validate_error(
            api_client.close_clinic_event(event["id"], _mgr()),
            ApiErrorId.ERR_EVENT_STILL_RUNNING,
        )
        assert err["error_id"] == "ERR_EVENT_STILL_RUNNING"


class TestObservationReactionRequiresEscalationAndNotes:
    """Design: Corner/validations/observation_reaction_requires_escalation_and_notes"""

    def test_escalate_with_empty_notes_rejected(self, api):
        """PRD §3.7: "It requires the session to be `IN_PROGRESS` and requires `adverse_reaction` true together with non-empty `reaction_notes`; escalation with a reaction but no notes is rejected with `ERR_REACTION_NOTES_REQUIRED`."

        Design: Corner/validations/observation_reaction_requires_escalation_and_notes
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-27", state_code="CA")
        product = create_product(observation_minutes=15)
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Obs", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        record = full_administration(store, patient, product, lot)
        obs = get_observation_session_for_record(record["id"])

        err = validate_error(
            api_client.escalate_observation_session(obs["id"],
                {"adverse_reaction": True, "reaction_notes": ""}, _obs()),
            ApiErrorId.ERR_REACTION_NOTES_REQUIRED,
        )
        assert err["error_id"] == "ERR_REACTION_NOTES_REQUIRED"

    def test_escalation_writes_audit_flag_and_blocks_complete(self, api):
        """PRD §3.7: "Escalation records the reaction on the session, moves it to `ESCALATED`, and writes an adverse-event audit flag onto the parent immunization record — the record itself stays `COMPLETED` and its registry submission is unaffected."
        PRD §3.7: "completing a session requires the session to be `IN_PROGRESS` (`ERR_SESSION_NOT_IN_PROGRESS`)"

        Design: Corner/validations/observation_reaction_requires_escalation_and_notes
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-27", state_code="CA")
        product = create_product(observation_minutes=15)
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Obs", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        record = full_administration(store, patient, product, lot)
        obs = get_observation_session_for_record(record["id"])

        escalated = validate_success(api_client.escalate_observation_session(obs["id"],
            {"adverse_reaction": True, "reaction_notes": "urticaria on left arm"}, _obs()))
        assert escalated["status"] == "ESCALATED"
        assert escalated["adverse_reaction"] is True

        # Record stays COMPLETED
        record_after = get_success_data(api_client.get_immunization_record(record["id"], _pharm()))
        assert record_after["status"] == "COMPLETED"

        # Complete after escalation fails
        err = validate_error(
            api_client.complete_observation_session(obs["id"], _obs()),
            ApiErrorId.ERR_SESSION_NOT_IN_PROGRESS,
        )
        assert err["error_id"] == "ERR_SESSION_NOT_IN_PROGRESS"

    def test_complete_by_different_observer_rejected(self, api):
        """PRD §3.7: "requires the caller's `X-User-ID` to equal the session's `observer_id` (`ERR_NOT_ASSIGNED_OBSERVER`)"

        Design: Corner/validations/observation_reaction_requires_escalation_and_notes
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-27", state_code="CA")
        product = create_product(observation_minutes=15)
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Obs", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        record = full_administration(store, patient, product, lot)
        obs = get_observation_session_for_record(record["id"])

        # Move past the observation window so only the observer-identity rule
        # can fail (PRD §3.7 evaluates the temporal floor before identity).
        set_clock("2026-09-01T11:00:00Z")
        # Complete by a different observer than the session's recorded one
        other_id = "user-obs-2" if obs["observer_id"] != "user-obs-2" else "user-obs-3"
        other_obs = build_user_headers(other_id, "ObservationMonitor")
        err = validate_error(
            api_client.complete_observation_session(obs["id"], other_obs),
            ApiErrorId.ERR_NOT_ASSIGNED_OBSERVER,
        )
        assert err["error_id"] == "ERR_NOT_ASSIGNED_OBSERVER"
