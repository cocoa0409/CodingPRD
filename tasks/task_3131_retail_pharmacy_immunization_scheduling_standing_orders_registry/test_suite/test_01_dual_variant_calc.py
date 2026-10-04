"""Dual-variant calculations — adjudicated charge provisional quote vs administered,
and excursion severity peak-delta vs cumulative variants.

PRD §3.6 charge waterfall, §3.2 excursion grading variants.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    build_user_headers,
)
from test_helpers.fixtures import (
    set_clock, create_store, create_product, create_protocol, create_patient,
    create_lot, create_insurance_plan, book_appointment, walk_appointment_to_consented,
    administer_appointment,
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


class TestAdjudicatedChargeProvisionalQuoteVsAdministered:
    """Design: Difficulty/dual_variant_calc/adjudicated_charge_provisional_quote_vs_administered_divergence"""

    def test_provisional_quote_uses_deductible_readonly(self, api):
        """PRD §3.3: "it does not consume the deductible, treating deductible_remaining_cents as read-only."
        PRD §3.6: "Under the medical channel, the deductible applied is the lesser of deductible_remaining_cents and the price; the remainder is the price minus that deductible; the coinsurance is the remainder multiplied by coinsurance_pct and divided by 100, floored to whole cents after the full multiplication"

        Design: Difficulty/dual_variant_calc/adjudicated_charge_provisional_quote_vs_administered_divergence
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-100", state_code="CA")
        product = create_product(cash_price_cents=10000)
        create_protocol(vaccine_product_id=product["id"], registry_deadline_hours=24, max_doses_per_patient_per_day=2)
        plan = create_insurance_plan(
            plan_name="MEDP", benefit_type="MEDICAL", copay_cents=0,
            coinsurance_pct=20, deductible_remaining_cents=2000, covered_cvx_codes=["141"],
        )
        patient = create_patient(full_name="Pat One", date_of_birth="1980-01-01", insurance_plan_id=plan["id"])
        lot = create_lot(store["id"], product["id"], doses_received=10)
        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z", is_walk_in=True)

        quote_resp = api_client.get_price_quote(appt["id"], _tech())
        quote = validate_success(quote_resp)
        # Quote: deductible_applied=min(2000,10000)=2000; remainder 8000; floor(8000*20/100)=1600; 2000+1600=3600
        assert quote["quoted_charge_cents"] == 3600, f"expected 3600, got {quote['quoted_charge_cents']}"
        assert quote["billing_channel"] == "MEDICAL_BENEFIT"

    def test_administered_charge_rereads_plan_after_deductible_change(self, api):
        """PRD §3.3: "the administered charge re-reads the plan row at administration time, so a plan whose deductible changed between quote and administration produces a different charge than quoted."

        Design: Difficulty/dual_variant_calc/adjudicated_charge_provisional_quote_vs_administered_divergence
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-100", state_code="CA")
        product = create_product(cash_price_cents=10000)
        create_protocol(vaccine_product_id=product["id"], registry_deadline_hours=24, max_doses_per_patient_per_day=2)
        plan = create_insurance_plan(
            plan_name="MEDP", benefit_type="MEDICAL", copay_cents=0,
            coinsurance_pct=20, deductible_remaining_cents=2000, covered_cvx_codes=["141"],
        )
        patient = create_patient(full_name="Pat One", date_of_birth="1980-01-01", insurance_plan_id=plan["id"])
        lot = create_lot(store["id"], product["id"], doses_received=10)
        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z", is_walk_in=True)

        # Take quote first (deductible 2000): expect 3600
        quote_resp = api_client.get_price_quote(appt["id"], _tech())
        quote = validate_success(quote_resp)
        assert quote["quoted_charge_cents"] == 3600

        # Change plan deductible to 500
        api_client.update_insurance_plan(plan["id"], {"deductible_remaining_cents": 500}, _co())

        # Walk the SAME quoted appointment to CONSENTED
        api_client.check_in_appointment(appt["id"], _tech())
        api_client.submit_questionnaire(appt["id"],
            {"answers": {"FEVER_TODAY": False, "PREGNANT": False, "IMMUNOCOMPROMISED": False, "PRIOR_ANAPHYLAXIS": False}},
            _tech())
        appt_now = get_success_data(api_client.get_appointment(appt["id"], _pharm()))
        validate_success(api_client.review_consent(appt["id"],
            {"expected_appointment_version": appt_now["version"], "outcome": "CLEAR"},
            _pharm()))
        # Administer
        record = administer_appointment(appt["id"], lot, immunizer_user_id="user-imm-1")

        # Administered: deductible re-read as 500; remainder 9500; floor(9500*20/100)=1900; 500+1900=2400
        assert record["charge_cents"] == 2400, f"expected 2400, got {record['charge_cents']}"
        assert record["billing_channel"] == "MEDICAL_BENEFIT"
        # The two variants diverge on identical product and patient
        assert quote["quoted_charge_cents"] != record["charge_cents"]


class TestExcursionPeakDeltaVsCumulative:
    """Design: Difficulty/dual_variant_calc/excursion_severity_peak_delta_vs_cumulative_minutes_divergence"""

    def test_release_with_cumulative_disposition_recomputes_tier(self, api):
        """PRD §3.2: "Under RELEASE_OK_CUMULATIVE — used in jurisdictions that grade severity by total time outside the band rather than peak deviation — the lot's last_excursion_severity_tier is recomputed by the cumulative variant: sum, over each run of consecutive out-of-band readings, the elapsed minutes between each reading and the next, and tier the total as at most 30 minutes MINOR, greater than 30 and at most 120 minutes MODERATE, and greater than 120 minutes SEVERE."

        Design: Difficulty/dual_variant_calc/excursion_severity_peak_delta_vs_cumulative_minutes_divergence
        """
        store = create_store(store_number="S-200", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=10)

        # Three readings: 10:00 at 9.0C, 10:45 at 9.0C, 11:15 at 7.0C
        api_client.create_temperature_reading(lot["id"],
            {"recorded_at": "2026-09-01T10:00:00Z", "temperature_c": 9.0}, _mgr())
        api_client.create_temperature_reading(lot["id"],
            {"recorded_at": "2026-09-01T10:45:00Z", "temperature_c": 9.0}, _mgr())
        api_client.create_temperature_reading(lot["id"],
            {"recorded_at": "2026-09-01T11:15:00Z", "temperature_c": 7.0}, _mgr())

        # Lot should be QUARANTINED
        lot_now = get_success_data(api_client.get_lot(lot["id"], _mgr()))
        assert lot_now["status"] == "QUARANTINED"

        # Release with RELEASE_OK_CUMULATIVE
        release_resp = api_client.release_lot(lot["id"],
            {"excursion_disposition": "RELEASE_OK_CUMULATIVE"}, _mgr())
        released = validate_success(release_resp)
        assert released["status"] == "RELEASED"
        # Cumulative: 45 + 30 = 75 minutes out-of-band; 30 < 75 <= 120 → MODERATE
        assert released["last_excursion_severity_tier"] == "MODERATE"

    def test_peak_delta_base_variant_would_tier_minor_on_same_data(self, api):
        """PRD §3.2: "greater than zero and at most 2.0 degrees is MINOR"
        PRD §3.2: "For identical temperature data this can produce a different tier than the peak-delta base variant whenever a shallow-but-long excursion occurs."

        Design: Difficulty/dual_variant_calc/excursion_severity_peak_delta_vs_cumulative_minutes_divergence
        """
        store = create_store(store_number="S-200", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=10)

        # Readings with peak delta 1.0 (9.0 - 8.0)
        r1 = validate_success(api_client.create_temperature_reading(lot["id"],
            {"recorded_at": "2026-09-01T10:00:00Z", "temperature_c": 9.0}, _mgr()),
            expected_status=201)
        # The reading's own peak-delta tier is MINOR
        assert r1["is_excursion"] is True
        assert r1["excursion_severity_tier"] == "MINOR"
        # Lot tier after first excursion is also MINOR (peak-delta base variant)
        lot_now = get_success_data(api_client.get_lot(lot["id"], _mgr()))
        assert lot_now["last_excursion_severity_tier"] == "MINOR"
