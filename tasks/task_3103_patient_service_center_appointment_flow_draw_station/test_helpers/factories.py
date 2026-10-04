"""Payload factories — one per entity, input fields only."""
from .constants import REFERENCE_PLAN, TEST_DEFAULTS, CENTER_DEFAULTS


def create_service_center_payload(**overrides) -> dict:
    defaults = {
        "name": CENTER_DEFAULTS["name"],
        "state_code": CENTER_DEFAULTS["state_code"],
        "timezone_offset_minutes": CENTER_DEFAULTS["timezone_offset_minutes"],
        "station_count": CENTER_DEFAULTS["station_count"],
        "slot_minutes": CENTER_DEFAULTS["slot_minutes"],
        "open_local_minutes": CENTER_DEFAULTS["open_local_minutes"],
        "close_local_minutes": CENTER_DEFAULTS["close_local_minutes"],
        "pediatric_capable": CENTER_DEFAULTS["pediatric_capable"],
        "draw_hold_minutes": CENTER_DEFAULTS["draw_hold_minutes"],
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(full_name="Ada Nguyen", birth_date="1990-04-02T00:00:00Z",
                           mrn="MRN-3103-DEFAULT", **overrides) -> dict:
    payload = {"full_name": full_name, "birth_date": birth_date, "mrn": mrn}
    payload.update(overrides)
    return payload


def create_phlebotomist_payload(service_center_id, full_name="Hana Reed",
                                credential="RN", **overrides) -> dict:
    payload = {
        "service_center_id": service_center_id,
        "full_name": full_name,
        "credential": credential,
        "shift_start_local_minutes": TEST_DEFAULTS["shift_start_local_minutes"],
        "shift_end_local_minutes": TEST_DEFAULTS["shift_end_local_minutes"],
    }
    payload.update(overrides)
    return payload


def create_insurance_plan_payload(**overrides) -> dict:
    payload = {
        "payer_name": REFERENCE_PLAN["payer_name"],
        "plan_type": REFERENCE_PLAN["plan_type"],
        "copay_cents": REFERENCE_PLAN["copay_cents"],
        "coinsurance_pct": REFERENCE_PLAN["coinsurance_pct"],
        "deductible_remaining_cents": REFERENCE_PLAN["deductible_remaining_cents"],
        "allowed_amount_cents": REFERENCE_PLAN["allowed_amount_cents"],
        "prior_paid_pct": REFERENCE_PLAN["prior_paid_pct"],
    }
    payload.update(overrides)
    return payload


def create_necessity_rule_payload(test_panel, icd10_code, is_covered=True, **overrides) -> dict:
    payload = {"test_panel": test_panel, "icd10_code": icd10_code, "is_covered": is_covered}
    payload.update(overrides)
    return payload


def create_tube_requirement_payload(test_panel, tube_code, required_volume_ml=4.0,
                                    min_volume_ml=1.0, order_of_draw=1,
                                    stability_minutes=240, max_urgency_hours=24,
                                    special_handling_codes=None,
                                    is_recollection_eligible=True, **overrides) -> dict:
    payload = {
        "test_panel": test_panel,
        "tube_code": tube_code,
        "required_volume_ml": required_volume_ml,
        "min_volume_ml": min_volume_ml,
        "order_of_draw": order_of_draw,
        "stability_minutes": stability_minutes,
        "max_urgency_hours": max_urgency_hours,
        "special_handling_codes": special_handling_codes if special_handling_codes is not None else [],
        "is_recollection_eligible": is_recollection_eligible,
    }
    payload.update(overrides)
    return payload


def create_test_order_payload(service_center_id, patient_id, insurance_plan_id,
                              test_panel="CMP", collection_mode="STANDARD",
                              ordering_provider_npi="1700111222",
                              is_fasting_required=False, fasting_hours_required=0,
                              patient_last_food_utc="2026-09-01T12:00:00Z",
                              icd10_codes=None, **overrides) -> dict:
    payload = {
        "service_center_id": service_center_id,
        "patient_id": patient_id,
        "ordering_provider_npi": ordering_provider_npi,
        "test_panel": test_panel,
        "collection_mode": collection_mode,
        "list_price_cents": TEST_DEFAULTS["list_price_cents"],
        "is_fasting_required": is_fasting_required,
        "fasting_hours_required": fasting_hours_required,
        "patient_last_food_utc": patient_last_food_utc,
        "icd10_codes": icd10_codes if icd10_codes is not None else [],
        "insurance_plan_id": insurance_plan_id,
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(service_center_id, test_order_id, scheduled_start_utc,
                               expected_test_order_version, slot_span=1,
                               source="BOOKED", **overrides) -> dict:
    payload = {
        "service_center_id": service_center_id,
        "test_order_id": test_order_id,
        "scheduled_start_utc": scheduled_start_utc,
        "slot_span": slot_span,
        "source": source,
        "expected_test_order_version": expected_test_order_version,
    }
    payload.update(overrides)
    return payload


def create_walk_in_payload(service_center_id, test_order_id,
                           expected_test_order_version, **overrides) -> dict:
    payload = {
        "service_center_id": service_center_id,
        "test_order_id": test_order_id,
        "expected_test_order_version": expected_test_order_version,
    }
    payload.update(overrides)
    return payload


def create_estimate_payload(variant, expected_test_order_version,
                            supersedes_estimate_id=None, **overrides) -> dict:
    payload = {
        "variant": variant,
        "supersedes_estimate_id": supersedes_estimate_id,
        "expected_test_order_version": expected_test_order_version,
    }
    payload.update(overrides)
    return payload


def create_specimen_payload(test_order_id, tube_code="EDTA_LAVENDER",
                            volume_ml=4.0, order_of_draw=1,
                            special_handling_codes=None, **overrides) -> dict:
    payload = {
        "test_order_id": test_order_id,
        "tube_code": tube_code,
        "volume_ml": volume_ml,
        "order_of_draw": order_of_draw,
        "special_handling_codes": special_handling_codes if special_handling_codes is not None else [],
    }
    payload.update(overrides)
    return payload


def create_courier_run_payload(service_center_id, dispatch_utc, direction="OUTBOUND", **overrides) -> dict:
    payload = {
        "service_center_id": service_center_id,
        "direction": direction,
        "dispatch_utc": dispatch_utc,
    }
    payload.update(overrides)
    return payload