"""Request-payload factories.

Every money field is emitted as a JSON integer number of cents and every
instant as a full ISO-8601 UTC instant -- never a bare date and never a
stringified number.
"""

from typing import Any, Dict, Optional

from .constants import (
    FB_CAR_TYPE,
    HR_CAR_TYPE,
    XM_CAR_TYPE,
)


def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def railroad_payload(reporting_mark: str, name: Optional[str] = None,
                     status: Optional[str] = None,
                     per_diem_credit_limit_cents: Optional[int] = None,
                     **extra) -> Dict[str, Any]:
    payload = {
        "reporting_mark": reporting_mark,
        "name": name if name is not None else f"{reporting_mark} Railway Company",
        "status": status,
        "per_diem_credit_limit_cents": per_diem_credit_limit_cents,
    }
    payload = _clean(payload)
    payload.update(extra)
    if per_diem_credit_limit_cents is not None:
        assert isinstance(payload["per_diem_credit_limit_cents"], int)
    return payload


def car_type_payload(**overrides) -> Dict[str, Any]:
    """A PER_DIEM box car rate book, overridable field by field."""
    payload = dict(XM_CAR_TYPE)
    payload.update(overrides)
    return _clean(payload)


def hourly_car_type_payload(**overrides) -> Dict[str, Any]:
    """An HOURLY refrigerator car rate book."""
    payload = dict(HR_CAR_TYPE)
    payload.update(overrides)
    return _clean(payload)


def flat_car_type_payload(**overrides) -> Dict[str, Any]:
    """A second PER_DIEM rate book with zero free time."""
    payload = dict(FB_CAR_TYPE)
    payload.update(overrides)
    return _clean(payload)


def junction_payload(junction_code: str, road_a_id: str, road_b_id: str,
                     name: Optional[str] = None, status: Optional[str] = None,
                     **extra) -> Dict[str, Any]:
    payload = _clean({
        "junction_code": junction_code,
        "name": name if name is not None else f"{junction_code} Interchange",
        "road_a_id": road_a_id,
        "road_b_id": road_b_id,
        "status": status,
    })
    payload.update(extra)
    return payload


def car_payload(car_mark: str, car_type_id: str, owner_road_id: str,
                initial_handling_road_id: Optional[str] = None,
                initial_odometer_miles: Optional[int] = None, **extra) -> Dict[str, Any]:
    payload = _clean({
        "car_mark": car_mark,
        "car_type_id": car_type_id,
        "owner_road_id": owner_road_id,
        "initial_handling_road_id": initial_handling_road_id,
        "initial_odometer_miles": initial_odometer_miles,
    })
    payload.update(extra)
    return payload


def delivery_event_payload(car_id: str, junction_id: str, delivering_road_id: str,
                           receiving_road_id: str, interchange_at: str,
                           odometer_miles: int, load_status: str = "LOADED",
                           **extra) -> Dict[str, Any]:
    assert isinstance(odometer_miles, int), "odometer_miles must be a JSON integer"
    payload = {
        "car_id": car_id,
        "junction_id": junction_id,
        "event_type": "INTERCHANGE_DELIVERY",
        "delivering_road_id": delivering_road_id,
        "receiving_road_id": receiving_road_id,
        "interchange_at": interchange_at,
        "odometer_miles": odometer_miles,
        "load_status": load_status,
    }
    payload.update(extra)
    return payload


def rejection_event_payload(car_id: str, junction_id: str, delivering_road_id: str,
                            receiving_road_id: str, interchange_at: str,
                            odometer_miles: int, load_status: str = "LOADED",
                            **extra) -> Dict[str, Any]:
    payload = delivery_event_payload(
        car_id, junction_id, delivering_road_id, receiving_road_id,
        interchange_at, odometer_miles, load_status,
    )
    payload["event_type"] = "INTERCHANGE_REJECTION"
    payload.update(extra)
    return payload


def bad_order_payload(reported_at: str, defect_code: str = "R-114",
                      defect_note: Optional[str] = None, **extra) -> Dict[str, Any]:
    payload = _clean({
        "reported_at": reported_at,
        "defect_code": defect_code,
        "defect_note": defect_note,
    })
    payload.update(extra)
    return payload


def release_payload(released_at: str, **extra) -> Dict[str, Any]:
    payload = {"released_at": released_at}
    payload.update(extra)
    return payload


def routing_obligation_payload(prescribed_return_junction_id: str, issued_at: str,
                               due_at: str, **extra) -> Dict[str, Any]:
    payload = {
        "prescribed_return_junction_id": prescribed_return_junction_id,
        "issued_at": issued_at,
        "due_at": due_at,
    }
    payload.update(extra)
    return payload


def reclaim_payload(movement_id: str, reason: str, window_from: str, window_to: str,
                    expected_movement_version: int,
                    detention_notified_at: Optional[str] = None,
                    supporting_embargo_id: Optional[str] = None,
                    filing_note: Optional[str] = None, **extra) -> Dict[str, Any]:
    assert isinstance(expected_movement_version, int), (
        "expected_movement_version must be a JSON integer"
    )
    payload = _clean({
        "movement_id": movement_id,
        "reason": reason,
        "window_from": window_from,
        "window_to": window_to,
        "expected_movement_version": expected_movement_version,
        "detention_notified_at": detention_notified_at,
        "supporting_embargo_id": supporting_embargo_id,
        "filing_note": filing_note,
    })
    payload.update(extra)
    return payload


def embargo_payload(issuing_road_id: str, junction_id: str, effective_from: str,
                    effective_to: str, reason: str = "Track outage",
                    car_type_id: Optional[str] = None, **extra) -> Dict[str, Any]:
    payload = _clean({
        "issuing_road_id": issuing_road_id,
        "junction_id": junction_id,
        "car_type_id": car_type_id,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "reason": reason,
    })
    payload.update(extra)
    return payload


def repair_bill_payload(car_id: str, billing_road_id: str, defect_code: str,
                        defect_class: str, defect_occurred_at: str,
                        labor_hours: float, material_cents: int,
                        repair_note: Optional[str] = None, **extra) -> Dict[str, Any]:
    assert isinstance(material_cents, int), "material_cents must be a JSON integer"
    payload = _clean({
        "car_id": car_id,
        "billing_road_id": billing_road_id,
        "defect_code": defect_code,
        "defect_class": defect_class,
        "defect_occurred_at": defect_occurred_at,
        "labor_hours": labor_hours,
        "material_cents": material_cents,
        "repair_note": repair_note,
    })
    payload.update(extra)
    return payload


def settlement_cycle_payload(payer_road_id: str, payee_road_id: str,
                             period_month: str, **extra) -> Dict[str, Any]:
    payload = {
        "payer_road_id": payer_road_id,
        "payee_road_id": payee_road_id,
        "period_month": period_month,
    }
    payload.update(extra)
    return payload


def dispute_payload(settlement_cycle_id: str, dispute_reason: str,
                    disputed_amount_cents: int, expected_cycle_version: int,
                    movement_id: Optional[str] = None,
                    repair_bill_id: Optional[str] = None,
                    filing_note: Optional[str] = None, **extra) -> Dict[str, Any]:
    assert isinstance(disputed_amount_cents, int), (
        "disputed_amount_cents must be a JSON integer"
    )
    assert isinstance(expected_cycle_version, int), (
        "expected_cycle_version must be a JSON integer"
    )
    payload = _clean({
        "settlement_cycle_id": settlement_cycle_id,
        "dispute_reason": dispute_reason,
        "disputed_amount_cents": disputed_amount_cents,
        "expected_cycle_version": expected_cycle_version,
        "movement_id": movement_id,
        "repair_bill_id": repair_bill_id,
        "filing_note": filing_note,
    })
    payload.update(extra)
    return payload


def correction_payload(correction_type: str, car_id: str, junction_id: str,
                       counterparty_road_id: str,
                       target_event_id: Optional[str] = None,
                       direction: Optional[str] = None,
                       proposed_interchange_at: Optional[str] = None,
                       proposed_odometer_miles: Optional[int] = None,
                       proposed_load_status: Optional[str] = None,
                       filing_note: Optional[str] = None, **extra) -> Dict[str, Any]:
    if proposed_odometer_miles is not None:
        assert isinstance(proposed_odometer_miles, int), (
            "proposed_odometer_miles must be a JSON integer"
        )
    payload = _clean({
        "car_id": car_id,
        "junction_id": junction_id,
        "counterparty_road_id": counterparty_road_id,
        "correction_type": correction_type,
        "target_event_id": target_event_id,
        "direction": direction,
        "proposed_interchange_at": proposed_interchange_at,
        "proposed_odometer_miles": proposed_odometer_miles,
        "proposed_load_status": proposed_load_status,
        "filing_note": filing_note,
    })
    payload.update(extra)
    return payload


def timestamp_amend_payload(car_id: str, junction_id: str, counterparty_road_id: str,
                            target_event_id: str, proposed_interchange_at: str,
                            **extra) -> Dict[str, Any]:
    return correction_payload(
        "TIMESTAMP_AMEND", car_id, junction_id, counterparty_road_id,
        target_event_id=target_event_id,
        proposed_interchange_at=proposed_interchange_at, **extra
    )


def erroneous_void_payload(car_id: str, junction_id: str, counterparty_road_id: str,
                           target_event_id: str, **extra) -> Dict[str, Any]:
    return correction_payload(
        "ERRONEOUS_EVENT_VOID", car_id, junction_id, counterparty_road_id,
        target_event_id=target_event_id, **extra
    )


def missed_event_payload(car_id: str, junction_id: str, counterparty_road_id: str,
                         direction: str, proposed_interchange_at: str,
                         proposed_odometer_miles: int,
                         proposed_load_status: str = "LOADED", **extra) -> Dict[str, Any]:
    return correction_payload(
        "MISSED_EVENT_INSERT", car_id, junction_id, counterparty_road_id,
        direction=direction, proposed_interchange_at=proposed_interchange_at,
        proposed_odometer_miles=proposed_odometer_miles,
        proposed_load_status=proposed_load_status, **extra
    )
