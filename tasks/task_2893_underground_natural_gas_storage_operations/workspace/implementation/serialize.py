"""Entity serializers: exact scaffold field names, PRD 2.5 precision, numbers never strings."""
from utils import iso, q2, q3, q4, q6, to_number


def _num(value):
    if value is None:
        return None
    return to_number(value)


def _n2(value):
    return None if value is None else to_number(q2(value))


def _n3(value):
    return None if value is None else to_number(q3(value))


def _n4(value):
    return None if value is None else to_number(q4(value))


def _n6(value):
    return None if value is None else to_number(q6(value))


def _int(value):
    return None if value is None else int(value)


def _dt(value):
    return None if value is None else iso(value)


def _common(record):
    return {
        "id": record["id"],
        "created_at": iso(record["created_at"]),
        "updated_at": iso(record["updated_at"]),
        "version": record["version"],
    }


def storage_field(record):
    out = _common(record)
    out.update({
        "name": record["name"],
        "field_code": record["field_code"],
        "season": record["season"],
        "total_capacity_dth": _num(record["total_capacity_dth"]),
        "cushion_gas_dth": _num(record["cushion_gas_dth"]),
        "max_working_gas_dth": _num(record["max_working_gas_dth"]),
        "working_gas_inventory_dth": _n3(record["working_gas_inventory_dth"]),
        "opening_working_gas_dth": _num(record["opening_working_gas_dth"]),
        "fuel_gas_used_dth": _n2(record["fuel_gas_used_dth"]),
        "retained_fuel_pool_dth": _n3(record["retained_fuel_pool_dth"]),
        "inventory_pct": _n2(record["inventory_pct"]),
        "base_pressure_psig": _int(record["base_pressure_psig"]),
        "pressure_span_psig": _int(record["pressure_span_psig"]),
        "max_pressure_psig": _int(record["max_pressure_psig"]),
        "current_pressure_psig": _int(record["current_pressure_psig"]),
        "deliverability_curve": [
            {
                "inventory_pct": _num(point["inventory_pct"]),
                "withdrawal_dth_per_day": _int(point["withdrawal_dth_per_day"]),
                "injection_dth_per_day": _int(point["injection_dth_per_day"]),
            }
            for point in record["deliverability_curve"]
        ],
        "deliverability_method": record["deliverability_method"],
        "deliverability_tier": record["deliverability_tier"],
        "max_withdrawal_rate_dth_per_day": _int(record["max_withdrawal_rate_dth_per_day"]),
        "max_injection_rate_dth_per_day": _int(record["max_injection_rate_dth_per_day"]),
        "wells_in_service_count": _int(record["wells_in_service_count"]),
        "field_posture": record["field_posture"],
    })
    return out


def well(record):
    out = _common(record)
    out.update({
        "storage_field_id": record["storage_field_id"],
        "well_name": record["well_name"],
        "well_type": record["well_type"],
        "rated_rate_dth_per_day": _int(record["rated_rate_dth_per_day"]),
        "casing_pressure_psig": _int(record["casing_pressure_psig"]),
        "last_mit_passed_at": _dt(record["last_mit_passed_at"]),
        "mit_due_at": _dt(record["mit_due_at"]),
        "operational_state": record["operational_state"],
        "integrity_state": record["integrity_state"],
        "shut_in_reason": record["shut_in_reason"],
        "service_change_count": _int(record["service_change_count"]),
    })
    return out


def mit(record):
    out = _common(record)
    out.update({
        "well_id": record["well_id"],
        "test_type": record["test_type"],
        "scheduled_start_at": _dt(record["scheduled_start_at"]),
        "scheduled_end_at": _dt(record["scheduled_end_at"]),
        "status": record["status"],
        "outcome": record["outcome"],
        "result_pressure_psig": _int(record["result_pressure_psig"]),
        "recorded_by_user_id": record["recorded_by_user_id"],
        "recorded_at": _dt(record["recorded_at"]),
    })
    return out


def remediation_program(record):
    out = _common(record)
    out.update({
        "well_id": record["well_id"],
        "triggering_mit_id": record["triggering_mit_id"],
        "status": record["status"],
        "opened_at": _dt(record["opened_at"]),
        "due_at": _dt(record["due_at"]),
        "verification_notes": record["verification_notes"],
        "completed_by_user_id": record["completed_by_user_id"],
        "completed_at": _dt(record["completed_at"]),
    })
    return out


def compressor_unit(record):
    out = _common(record)
    out.update({
        "storage_field_id": record["storage_field_id"],
        "unit_code": record["unit_code"],
        "rated_horsepower": _int(record["rated_horsepower"]),
        "derate_factor": _n2(record["derate_factor"]),
        "status": record["status"],
        "lifetime_fuel_dth": _n2(record["lifetime_fuel_dth"]),
        "scheduled_run_count": _int(record["scheduled_run_count"]),
    })
    return out


def compressor_run(record):
    out = _common(record)
    out.update({
        "compressor_unit_id": record["compressor_unit_id"],
        "window_start_at": _dt(record["window_start_at"]),
        "window_end_at": _dt(record["window_end_at"]),
        "allocated_horsepower": _int(record["allocated_horsepower"]),
        "mode": record["mode"],
        "duration_hours": _n4(record["duration_hours"]),
        "effective_horsepower": _n2(record["effective_horsepower"]),
        "utilization_ratio": _n6(record["utilization_ratio"]),
        "utilization_band": record["utilization_band"],
        "fuel_consumed_dth": _n2(record["fuel_consumed_dth"]),
        "status": record["status"],
    })
    return out


def shipper(record):
    out = _common(record)
    out.update({
        "legal_name": record["legal_name"],
        "duns_number": record["duns_number"],
        "penalty_threshold_usd": _n2(record["penalty_threshold_usd"]),
        "outstanding_penalty_usd": _n2(record["outstanding_penalty_usd"]),
        "credit_status": record["credit_status"],
    })
    return out


def contract(record):
    out = _common(record)
    out.update({
        "shipper_id": record["shipper_id"],
        "storage_field_id": record["storage_field_id"],
        "contract_code": record["contract_code"],
        "service_class": record["service_class"],
        "max_storage_quantity_dth": _num(record["max_storage_quantity_dth"]),
        "max_daily_injection_dth": _num(record["max_daily_injection_dth"]),
        "max_daily_withdrawal_dth": _num(record["max_daily_withdrawal_dth"]),
        "term_start_date": record["term_start_date"],
        "term_end_date": record["term_end_date"],
        "commodity_rate_usd_per_dth": _n4(record["commodity_rate_usd_per_dth"]),
        "index_price_usd_per_dth": _n4(record["index_price_usd_per_dth"]),
        "cash_out_method": record["cash_out_method"],
        "status": record["status"],
        "inventory_balance_dth": _n3(record["inventory_balance_dth"]),
        "scheduled_injection_dth": _int(record["scheduled_injection_dth"]),
        "scheduled_withdrawal_dth": _int(record["scheduled_withdrawal_dth"]),
        "imbalance_dth": _n3(record["imbalance_dth"]),
        "cash_out_amount_usd": _n2(record["cash_out_amount_usd"]),
        "cash_out_through_date": record["cash_out_through_date"],
        "activated_at": _dt(record["activated_at"]),
    })
    return out


def nomination(record):
    out = _common(record)
    out.update({
        "contract_id": record["contract_id"],
        "gas_day": record["gas_day"],
        "direction": record["direction"],
        "nominated_volume_dth": _int(record["nominated_volume_dth"]),
        "confirmed_volume_dth": _int(record["confirmed_volume_dth"]),
        "curtailed_volume_dth": _int(record["curtailed_volume_dth"]),
        "status": record["status"],
        "revision_round": _int(record["revision_round"]),
        "superseded_by_nomination_id": record["superseded_by_nomination_id"],
        "submitted_at": _dt(record["submitted_at"]),
        "confirmed_at": _dt(record["confirmed_at"]),
    })
    return out


def ticket(record):
    out = _common(record)
    out.update({
        "nomination_id": record["nomination_id"],
        "well_id": record["well_id"],
        "actual_volume_dth": _int(record["actual_volume_dth"]),
        "fuel_retention_dth": _n3(record["fuel_retention_dth"]),
        "net_volume_dth": _n3(record["net_volume_dth"]),
        "commodity_charge_usd": _n2(record["commodity_charge_usd"]),
        "volume_discount_usd": _n2(record["volume_discount_usd"]),
        "fuel_charge_usd": _n2(record["fuel_charge_usd"]),
        "total_charge_usd": _n2(record["total_charge_usd"]),
        "status": record["status"],
        "reversal_reason": record["reversal_reason"],
        "confirmed_at": _dt(record["confirmed_at"]),
    })
    return out


def ledger_entry(record):
    # common_fields: false -- only id and created_at, no updated_at and no version key.
    return {
        "id": record["id"],
        "created_at": iso(record["created_at"]),
        "contract_id": record["contract_id"],
        "entry_type": record["entry_type"],
        "gas_day": record["gas_day"],
        "volume_dth": _n3(record["volume_dth"]),
        "amount_usd": _n2(record["amount_usd"]),
        "origin_note": record["origin_note"],
    }


def emergency_event(record):
    out = _common(record)
    out.update({
        "storage_field_id": record["storage_field_id"],
        "well_id": record["well_id"],
        "event_type": record["event_type"],
        "severity": record["severity"],
        "detected_at": _dt(record["detected_at"]),
        "status": record["status"],
        "evacuation_radius_m": _int(record["evacuation_radius_m"]),
        "responder_notes": record["responder_notes"],
        "contained_at": _dt(record["contained_at"]),
        "closed_at": _dt(record["closed_at"]),
    })
    return out


def report(record):
    out = _common(record)
    out.update({
        "storage_field_id": record["storage_field_id"],
        "report_type": record["report_type"],
        "period_start_date": record["period_start_date"],
        "period_end_date": record["period_end_date"],
        "measured_inventory_dth": _num(record["measured_inventory_dth"]),
        "book_inventory_dth": _n3(record["book_inventory_dth"]),
        "variance_dth": _n3(record["variance_dth"]),
        "variance_pct": _n4(record["variance_pct"]),
        "open_finding_count": _int(record["open_finding_count"]),
        "status": record["status"],
        "prepared_by_user_id": record["prepared_by_user_id"],
        "submitted_by_user_id": record["submitted_by_user_id"],
        "agency_outcome": record["agency_outcome"],
        "agency_response_note": record["agency_response_note"],
    })
    return out


SERIALIZERS = {
    "StorageField": storage_field,
    "Well": well,
    "MechanicalIntegrityTest": mit,
    "RemediationProgram": remediation_program,
    "CompressorUnit": compressor_unit,
    "CompressorRun": compressor_run,
    "Shipper": shipper,
    "StorageContract": contract,
    "Nomination": nomination,
    "GasMovementTicket": ticket,
    "ImbalanceLedgerEntry": ledger_entry,
    "EmergencyEvent": emergency_event,
    "RegulatoryReport": report,
}


def many(serializer, rows):
    return [serializer(row) for row in rows]
