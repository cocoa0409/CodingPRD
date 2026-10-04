"""Corner tests — calculations section: charge waterfall channels, age boundary,
dose series rules, excursion tier boundaries, registry payload format.

PRD §3.6 waterfall, §3.3 age/series, §3.2 excursion tiers, §3.8 registry.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_store, create_product, create_protocol, create_patient,
    create_lot, create_insurance_plan, book_appointment,
    walk_appointment_to_consented, administer_appointment, full_administration,
    get_submission_for_record,
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


class TestAdjudicatedChargePharmacyChannelMinAndMedicalChannelFloor:
    """Design: Corner/calculations/adjudicated_charge_pharmacy_channel_min_and_medical_channel_floor"""

    def test_pharmacy_channel_min_copay_price(self, api):
        """PRD §3.6: "The pharmacy benefit channel applies when a plan exists, its `benefit_type` is `PHARMACY` or `BOTH`, and the product's `cvx_code` appears in the plan's `covered_cvx_codes`. The charge is then the lesser of the plan's `copay_cents` and the price."

        Design: Corner/calculations/adjudicated_charge_pharmacy_channel_min_and_medical_channel_floor
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-13", state_code="CA")
        product = create_product(cash_price_cents=5000)
        create_protocol(vaccine_product_id=product["id"])
        plan = create_insurance_plan(plan_name="PH1", benefit_type="PHARMACY",
                                     copay_cents=2500, covered_cvx_codes=["141"])
        patient = create_patient(full_name="Pat A", date_of_birth="1980-01-01",
                                 insurance_plan_id=plan["id"])
        lot = create_lot(store["id"], product["id"], doses_received=10)
        appt = walk_appointment_to_consented(store, patient, product,
                                             slot_start="2026-09-01T10:00:00Z")
        record = administer_appointment(appt["id"], lot)
        assert record["charge_cents"] == 2500
        assert record["billing_channel"] == "PHARMACY_BENEFIT"

    def test_medical_channel_deductible_plus_floored_coinsurance(self, api):
        """PRD §3.6: "Under the medical channel, the deductible applied is the lesser of `deductible_remaining_cents` and the price; the remainder is the price minus that deductible; the coinsurance is the remainder multiplied by `coinsurance_pct` and divided by 100, floored to whole cents after the full multiplication — the percentage is never rounded first; and the charge is the deductible applied plus the floored coinsurance."

        Design: Corner/calculations/adjudicated_charge_pharmacy_channel_min_and_medical_channel_floor
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-13", state_code="CA")
        product = create_product(cvx_code="045", name="Hepatitis B", cash_price_cents=10000,
                                 doses_per_series=3)
        create_protocol(vaccine_product_id=product["id"])
        plan = create_insurance_plan(plan_name="ME1", benefit_type="MEDICAL",
                                     copay_cents=0, coinsurance_pct=25,
                                     deductible_remaining_cents=1500,
                                     covered_cvx_codes=["045"])
        patient = create_patient(full_name="Pat B", date_of_birth="1981-01-01",
                                 insurance_plan_id=plan["id"])
        lot = create_lot(store["id"], product["id"], doses_received=10)
        appt = walk_appointment_to_consented(store, patient, product,
                                             slot_start="2026-09-01T10:05:00Z")
        record = administer_appointment(appt["id"], lot)
        # deductible 1500 + floor(8500 * 25/100) = 1500 + 2125 = 3625
        assert record["charge_cents"] == 3625
        assert record["billing_channel"] == "MEDICAL_BENEFIT"


class TestAdjudicatedChargeCashFallbackUncoveredCvxAndNoPlan:
    """Design: Corner/calculations/adjudicated_charge_cash_fallback_uncovered_cvx_and_no_plan"""

    def test_uncovered_cvx_falls_to_cash(self, api):
        """PRD §3.6: "The cash channel applies when no plan exists, when the CVX is not covered, or when both benefit channels are otherwise inapplicable, and the charge is simply the full price with no discount."

        Design: Corner/calculations/adjudicated_charge_cash_fallback_uncovered_cvx_and_no_plan
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-14", state_code="CA")
        product = create_product(cash_price_cents=5000)
        create_protocol(vaccine_product_id=product["id"])
        plan = create_insurance_plan(plan_name="PH9", benefit_type="PHARMACY",
                                     copay_cents=100, covered_cvx_codes=["999"])
        patient = create_patient(full_name="Pat C", date_of_birth="1980-01-01",
                                 insurance_plan_id=plan["id"])
        lot = create_lot(store["id"], product["id"], doses_received=10)
        appt = walk_appointment_to_consented(store, patient, product,
                                             slot_start="2026-09-01T10:00:00Z")
        record = administer_appointment(appt["id"], lot)
        assert record["charge_cents"] == 5000
        assert record["billing_channel"] == "CASH"

    def test_no_plan_falls_to_cash(self, api):
        """PRD §3.6: "The cash channel applies when no plan exists, when the CVX is not covered, or when both benefit channels are otherwise inapplicable, and the charge is simply the full price with no discount."

        Design: Corner/calculations/adjudicated_charge_cash_fallback_uncovered_cvx_and_no_plan
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-14", state_code="CA")
        product = create_product(cash_price_cents=5000)
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat D", date_of_birth="1981-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=10)
        appt = walk_appointment_to_consented(store, patient, product,
                                             slot_start="2026-09-01T10:05:00Z")
        record = administer_appointment(appt["id"], lot)
        assert record["charge_cents"] == 5000
        assert record["billing_channel"] == "CASH"


class TestPatientAgeBoundaryBirthdayAndSlotDateEvaluation:
    """Design: Corner/calculations/patient_age_boundary_birthday_and_slot_date_evaluation"""

    def test_slot_one_day_before_birthday_rejected(self, api):
        """PRD §3.3: "Eligibility requires the age at the slot date to be at least the greater of the protocol's `min_patient_age_years` and the product's `min_patient_age_years`; the comparison is inclusive, so a patient exactly at the minimum age on their birthday is eligible. Falling short is rejected with `ERR_PATIENT_UNDER_MIN_AGE`."

        Design: Corner/calculations/patient_age_boundary_birthday_and_slot_date_evaluation
        """
        store = create_store(store_number="S-15", state_code="CA")
        product = create_product(cvx_code="207", name="Product P18", min_patient_age_years=18)
        create_protocol(vaccine_product_id=product["id"], min_patient_age_years=18)
        patient = create_patient(full_name="Pat Age", date_of_birth="2008-06-15")

        err = validate_error(
            api_client.create_appointment({
                "store_id": store["id"], "patient_id": patient["id"],
                "vaccine_product_id": product["id"], "slot_start": "2026-06-14T10:00:00Z",
            }, _tech()),
            ApiErrorId.ERR_PATIENT_UNDER_MIN_AGE,
        )
        assert err["error_id"] == "ERR_PATIENT_UNDER_MIN_AGE"

    def test_slot_on_birthday_succeeds(self, api):
        """PRD §3.3: "the comparison is inclusive, so a patient exactly at the minimum age on their birthday is eligible."
        PRD §3.3: "eligibility is evaluated at the administration date (the calendar day of `slot_start`), not the booking date"

        Design: Corner/calculations/patient_age_boundary_birthday_and_slot_date_evaluation
        """
        store = create_store(store_number="S-15", state_code="CA")
        product = create_product(cvx_code="207", name="Product P18", min_patient_age_years=18)
        create_protocol(vaccine_product_id=product["id"], min_patient_age_years=18)
        patient = create_patient(full_name="Pat Age", date_of_birth="2008-06-15")

        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-06-15T10:00:00Z")
        assert appt["status"] == "SCHEDULED"


class TestDoseSeriesCompletionAndMinIntervalEnforcement:
    """Design: Corner/calculations/dose_series_completion_and_min_interval_enforcement"""

    def test_min_interval_not_met_rejected(self, api):
        """PRD §3.3: "For a second or later dose, the most recent prior `COMPLETED` record's `administered_at` must be at least `min_interval_days` before `slot_start`; a gap of exactly the minimum interval is allowed, and a shorter gap is rejected with `ERR_MIN_INTERVAL_NOT_MET`."

        Design: Corner/calculations/dose_series_completion_and_min_interval_enforcement
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-16", state_code="CA")
        product = create_product(cvx_code="999", name="Shingles-like", doses_per_series=2,
                                 min_interval_days=28)
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Ser", date_of_birth="1970-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=10,
                         expiration_date="2027-06-01")

        # Dose 1 administered 2026-09-01
        full_administration(store, patient, product, lot,
                            tech_user_id="user-tech-1", pharm_user_id="user-pharm-1",
                            imm_user_id="user-imm-1")

        # Dose 2 at +27 days fails
        err = validate_error(
            api_client.create_appointment({
                "store_id": store["id"], "patient_id": patient["id"],
                "vaccine_product_id": product["id"], "slot_start": "2026-09-28T10:00:00Z",
            }, _tech()),
            ApiErrorId.ERR_MIN_INTERVAL_NOT_MET,
        )
        assert err["error_id"] == "ERR_MIN_INTERVAL_NOT_MET"

    def test_exact_min_interval_and_series_completion(self, api):
        """PRD §3.3: "a gap of exactly the minimum interval is allowed"
        PRD §3.3: "If that computed `dose_number` exceeds the product's `doses_per_series`, the series is already complete and booking is rejected with `ERR_SERIES_ALREADY_COMPLETE`."

        Design: Corner/calculations/dose_series_completion_and_min_interval_enforcement
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-16", state_code="CA")
        product = create_product(cvx_code="999", name="Shingles-like", doses_per_series=2,
                                 min_interval_days=28)
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Ser", date_of_birth="1970-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=10,
                         expiration_date="2027-06-01")

        # Dose 1
        full_administration(store, patient, product, lot)

        # Dose 2 at exactly +28 days
        appt2 = book_appointment(store["id"], patient["id"], product["id"],
                                 slot_start="2026-09-29T10:00:00Z")
        assert appt2["dose_number"] == 2

        # Administer dose 2 via the already-booked appointment
        set_clock("2026-09-29T10:00:00Z")
        api_client.check_in_appointment(appt2["id"], _tech())
        api_client.submit_questionnaire(appt2["id"], {"answers": {"FEVER_TODAY": False}}, _tech())
        appt2_now = get_success_data(api_client.get_appointment(appt2["id"], _pharm()))
        validate_success(api_client.review_consent(appt2["id"],
            {"expected_appointment_version": appt2_now["version"], "outcome": "CLEAR"},
            _pharm()))
        administer_appointment(appt2["id"], lot, immunizer_user_id="user-imm-1")

        # Third booking fails
        err = validate_error(
            api_client.create_appointment({
                "store_id": store["id"], "patient_id": patient["id"],
                "vaccine_product_id": product["id"], "slot_start": "2026-12-01T10:00:00Z",
            }, _tech()),
            ApiErrorId.ERR_SERIES_ALREADY_COMPLETE,
        )
        assert err["error_id"] == "ERR_SERIES_ALREADY_COMPLETE"


class TestExcursionTierBoundariesMinorModerateSevere:
    """Design: Corner/calculations/excursion_tier_boundaries_minor_moderate_severe"""

    def test_exactly_2_00_is_minor(self, api):
        """PRD §3.2: "The boundary is exclusive at the top of `MINOR` — a rounded delta of exactly 2.00 is `MINOR`, while 2.01 is `MODERATE`."

        Design: Corner/calculations/excursion_tier_boundaries_minor_moderate_severe
        """
        store = create_store(store_number="S-17", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], lot_number="LA", doses_received=5)
        reading = validate_success(api_client.create_temperature_reading(lot["id"],
            {"recorded_at": "2026-09-01T10:00:00Z", "temperature_c": 10.0}, _mgr()),
            expected_status=201)
        assert reading["excursion_severity_tier"] == "MINOR"

    def test_2_01_is_moderate(self, api):
        """PRD §3.2: "a rounded delta of exactly 2.00 is `MINOR`, while 2.01 is `MODERATE`."

        Design: Corner/calculations/excursion_tier_boundaries_minor_moderate_severe
        """
        store = create_store(store_number="S-17", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], lot_number="LB", doses_received=5)
        reading = validate_success(api_client.create_temperature_reading(lot["id"],
            {"recorded_at": "2026-09-01T10:01:00Z", "temperature_c": 10.01}, _mgr()),
            expected_status=201)
        assert reading["excursion_severity_tier"] == "MODERATE"

    def test_over_5_0_is_severe(self, api):
        """PRD §3.2: "greater than 5.0 degrees is `SEVERE`"

        Design: Corner/calculations/excursion_tier_boundaries_minor_moderate_severe
        """
        store = create_store(store_number="S-17", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], lot_number="LC", doses_received=5)
        reading = validate_success(api_client.create_temperature_reading(lot["id"],
            {"recorded_at": "2026-09-01T10:02:00Z", "temperature_c": 13.01}, _mgr()),
            expected_status=201)
        assert reading["excursion_severity_tier"] == "SEVERE"

    def test_all_excursions_auto_quarantine(self, api):
        """PRD §3.2: "Any excursion at all — however slight — auto-quarantines the lot"

        Design: Corner/calculations/excursion_tier_boundaries_minor_moderate_severe
        """
        store = create_store(store_number="S-17", state_code="CA")
        product = create_product()
        for ln, temp in [("LA", 10.0), ("LB", 10.01), ("LC", 13.01)]:
            lot = create_lot(store["id"], product["id"], lot_number=ln, doses_received=5)
            api_client.create_temperature_reading(lot["id"],
                {"recorded_at": "2026-09-01T10:00:00Z", "temperature_c": temp}, _mgr())
            lot_now = get_success_data(api_client.get_lot(lot["id"], _mgr()))
            assert lot_now["status"] == "QUARANTINED"
            assert lot_now["quarantine_reason"] == "EXCURSION"


class TestRegistrySubmissionCreatedWithPolymorphicPayloadFormat:
    """Design: Corner/calculations/registry_submission_created_with_polymorphic_payload_format"""

    def test_payload_format_copied_from_protocol_and_due_at_computed(self, api):
        """PRD §3.8: "The `RegistrySubmission` created at administration copies its `payload_format` from the governing protocol's `registry_format` — `HL7_VXU`, `FLAT_FILE_CSV`, or `STATE_API_JSON` — renders its `payload` as the jurisdiction-specific message body, and computes its `due_at` as the record's `administered_at` plus the protocol's `registry_deadline_hours`, with exact hour arithmetic."

        Design: Corner/calculations/registry_submission_created_with_polymorphic_payload_format
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-18", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"], registry_format="STATE_API_JSON",
                        registry_deadline_hours=6)
        patient = create_patient(full_name="Pat Reg", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)

        set_clock("2026-09-01T10:00:00Z")
        record = full_administration(store, patient, product, lot)
        sub = get_submission_for_record(record["id"])
        assert sub["payload_format"] == "STATE_API_JSON"
        assert sub["due_at"] == "2026-09-01T16:00:00Z"
        assert sub["status"] == "PENDING"
        assert sub["is_late"] is False
