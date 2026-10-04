"""Combinatorial formula tests — charge waterfall pinned channel order, and
excursion severity nested rounding order.

PRD §3.6 waterfall order, §3.2 rounding before tier comparison.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
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


class TestAdjudicatedChargeWaterfallPinnedChannelOrderBothPlan:
    """Design: Difficulty/combinatorial_formula/adjudicated_charge_waterfall_pinned_channel_order_both_plan"""

    def test_both_plan_resolves_to_pharmacy_benefit(self, api):
        """PRD §3.6: "A plan with `benefit_type` of `BOTH` always resolves to the `PHARMACY_BENEFIT` channel when the CVX is covered, even if the medical channel would yield a lower charge."

        Design: Difficulty/combinatorial_formula/adjudicated_charge_waterfall_pinned_channel_order_both_plan
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-300", state_code="CA")
        product = create_product(cvx_code="999", name="Product P1", min_patient_age_years=50, cash_price_cents=4000)
        create_protocol(vaccine_product_id=product["id"], min_patient_age_years=50,
                        registry_format="STATE_API_JSON", registry_deadline_hours=24,
                        max_doses_per_patient_per_day=2)
        plan = create_insurance_plan(
            plan_name="BOTHP", benefit_type="BOTH", copay_cents=1800,
            coinsurance_pct=10, deductible_remaining_cents=5000, covered_cvx_codes=["999"],
        )
        patient = create_patient(full_name="Pat Two", date_of_birth="1970-01-01", insurance_plan_id=plan["id"])
        lot = create_lot(store["id"], product["id"], doses_received=5)
        appt = walk_appointment_to_consented(store, patient, product,
                                             slot_start="2026-09-01T10:00:00Z",
                                             tech_user_id="user-tech-1", pharm_user_id="user-pharm-1")
        record = administer_appointment(appt["id"], lot, immunizer_user_id="user-imm-1")
        assert record["billing_channel"] == "PHARMACY_BENEFIT"
        # charge = min(copay 1800, price 4000) = 1800
        assert record["charge_cents"] == 1800

    def test_medical_channel_would_have_charged_4000_but_pinned_order_wins(self, api):
        """PRD §3.6: "evaluating channels in pinned order — pharmacy benefit first, then medical benefit, then cash — with the first applicable channel winning."

        Design: Difficulty/combinatorial_formula/adjudicated_charge_waterfall_pinned_channel_order_both_plan
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-300", state_code="CA")
        product = create_product(cvx_code="999", name="Product P1", min_patient_age_years=50, cash_price_cents=4000)
        create_protocol(vaccine_product_id=product["id"], min_patient_age_years=50,
                        registry_format="STATE_API_JSON", registry_deadline_hours=24,
                        max_doses_per_patient_per_day=2)
        plan = create_insurance_plan(
            plan_name="BOTHP", benefit_type="BOTH", copay_cents=1800,
            coinsurance_pct=10, deductible_remaining_cents=5000, covered_cvx_codes=["999"],
        )
        patient = create_patient(full_name="Pat Two", date_of_birth="1970-01-01", insurance_plan_id=plan["id"])
        lot = create_lot(store["id"], product["id"], doses_received=5)
        appt = walk_appointment_to_consented(store, patient, product,
                                             slot_start="2026-09-01T10:00:00Z",
                                             tech_user_id="user-tech-1", pharm_user_id="user-pharm-1")
        record = administer_appointment(appt["id"], lot, immunizer_user_id="user-imm-1")
        # Medical channel would have been: min(5000,4000) + floor(0 * 10/100) = 4000
        # Pharmacy wins because it is evaluated first
        assert record["charge_cents"] == 1800
        assert record["billing_channel"] == "PHARMACY_BENEFIT"


class TestExcursionSeverityNestedRoundingOrderMatters:
    """Design: Difficulty/combinatorial_formula/excursion_severity_nested_rounding_order_matters"""

    def test_rounding_before_tier_comparison_produces_minor(self, api):
        """PRD §3.2: "That raw delta is first rounded half-up to 2 decimal places, and only the rounded value is compared against the tier boundaries — the order is pinned because the two orders genuinely diverge (a raw delta of 2.004 rounds to 2.00 and tiers MINOR, whereas comparing the unrounded value would tier it MODERATE)."

        Design: Difficulty/combinatorial_formula/excursion_severity_nested_rounding_order_matters
        """
        store = create_store(store_number="S-400", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=10)

        resp = api_client.create_temperature_reading(lot["id"],
            {"recorded_at": "2026-09-01T10:00:00Z", "temperature_c": 10.004}, _mgr())
        reading = validate_success(resp, expected_status=201)
        # delta_raw = 10.004 - 8.0 = 2.004; round_half_up(2.004, 2) = 2.00 → MINOR
        assert reading["is_excursion"] is True
        assert reading["excursion_severity_tier"] == "MINOR"

    def test_lot_auto_quarantines_regardless_of_tier(self, api):
        """PRD §3.2: "Any excursion at all — however slight — auto-quarantines the lot: the lot's status moves from RELEASED to QUARANTINED with quarantine_reason set to EXCURSION, and the severity of the excursion is graded and stored."

        Design: Difficulty/combinatorial_formula/excursion_severity_nested_rounding_order_matters
        """
        store = create_store(store_number="S-400", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=10)

        api_client.create_temperature_reading(lot["id"],
            {"recorded_at": "2026-09-01T10:00:00Z", "temperature_c": 10.004}, _mgr())
        lot_now = get_success_data(api_client.get_lot(lot["id"], _mgr()))
        assert lot_now["status"] == "QUARANTINED"
        assert lot_now["quarantine_reason"] == "EXCURSION"
        assert lot_now["last_excursion_severity_tier"] == "MINOR"
