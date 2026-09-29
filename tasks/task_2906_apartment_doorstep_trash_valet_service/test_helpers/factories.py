"""Request payload builders.

Every builder emits the field names the PRD declares for that endpoint and
nothing else: `property_id`, `contract_id`, `service_night_id` and the like are
taken from the path by the API and are never sent in a body. Money is always
an integer count of cents; service windows are always full ISO 8601 instants
with three fractional digits, never bare dates.
"""

from .constants import TEST_DEFAULTS

_counter = {"n": 0}


def _next(prefix):
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']:04d}"


# --------------------------------------------------------------------- clock
def clock_payload(to_iso8601):
    return {"to_iso8601": to_iso8601}


# ---------------------------------------------------------------- properties
def property_payload(name=None, unit_count=None, market_code=None,
                     compactor_capacity_lbs=None, **overrides):
    payload = {
        "name": name if name is not None else _next("Maple Court"),
        "unit_count": unit_count if unit_count is not None
        else TEST_DEFAULTS["UNIT_COUNT"],
        "market_code": market_code if market_code is not None
        else TEST_DEFAULTS["MARKET_CODE"],
    }
    if compactor_capacity_lbs is not None:
        payload["compactor_capacity_lbs"] = compactor_capacity_lbs
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------- contracts
def contract_payload(per_unit_monthly_fee_cents=None, property_revenue_share_bps=None,
                     service_night_days=None, effective_from=None, effective_to=None,
                     sla_missed_threshold_bps=None, **overrides):
    payload = {
        "per_unit_monthly_fee_cents": per_unit_monthly_fee_cents
        if per_unit_monthly_fee_cents is not None
        else TEST_DEFAULTS["PER_UNIT_MONTHLY_FEE_CENTS"],
        "property_revenue_share_bps": property_revenue_share_bps
        if property_revenue_share_bps is not None
        else TEST_DEFAULTS["PROPERTY_REVENUE_SHARE_BPS"],
        "service_night_days": list(service_night_days) if service_night_days is not None
        else list(TEST_DEFAULTS["SERVICE_NIGHT_DAYS"]),
        "effective_from": effective_from if effective_from is not None
        else TEST_DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": effective_to if effective_to is not None
        else TEST_DEFAULTS["EFFECTIVE_TO"],
        "sla_missed_threshold_bps": sla_missed_threshold_bps
        if sla_missed_threshold_bps is not None
        else TEST_DEFAULTS["SLA_MISSED_THRESHOLD_BPS"],
    }
    payload.update(overrides)
    return payload


def terminate_contract_payload(reason=None):
    return {} if reason is None else {"reason": reason}


# ----------------------------------------------------------------- residents
def resident_payload(unit_number, full_name=None, move_in_date=None,
                     fee_passthrough_enabled=None, **overrides):
    payload = {
        "unit_number": unit_number,
        "full_name": full_name if full_name is not None else _next("Resident"),
        "move_in_date": move_in_date if move_in_date is not None
        else TEST_DEFAULTS["EFFECTIVE_FROM"],
    }
    if fee_passthrough_enabled is not None:
        payload["fee_passthrough_enabled"] = fee_passthrough_enabled
    payload.update(overrides)
    return payload


def move_out_payload(move_out_date):
    return {"move_out_date": move_out_date}


# --------------------------------------------------------------- contractors
def contractor_payload(legal_name=None, equipment_provided_by_company=True,
                       sets_own_schedule=True, works_exclusively=False,
                       weekly_committed_hours=20, **overrides):
    payload = {
        "legal_name": legal_name if legal_name is not None else _next("Valet"),
        "equipment_provided_by_company": equipment_provided_by_company,
        "sets_own_schedule": sets_own_schedule,
        "works_exclusively": works_exclusively,
        "weekly_committed_hours": weekly_committed_hours,
    }
    payload.update(overrides)
    return payload


def contractor_documents_payload(tax_form_type="W9", direct_deposit_on_file=True):
    return {
        "tax_form_type": tax_form_type,
        "direct_deposit_on_file": direct_deposit_on_file,
    }


def background_check_payload(result="CLEAR"):
    return {"result": result}


def classification_payload(basis="DECLARED"):
    return {"basis": basis}


def deactivate_contractor_payload(reason="Left the network"):
    return {"reason": reason}


# ------------------------------------------------------------ service nights
def service_night_payload(service_date, service_window_start=None,
                          service_window_end=None, seasonal_volume_index=None,
                          holiday_flag=None, **overrides):
    payload = {
        "service_date": service_date,
        "service_window_start": service_window_start
        if service_window_start is not None
        else f"{service_date}{TEST_DEFAULTS['WINDOW_START_SUFFIX']}",
        "service_window_end": service_window_end
        if service_window_end is not None
        else f"{service_date}{TEST_DEFAULTS['WINDOW_END_SUFFIX']}",
    }
    if seasonal_volume_index is not None:
        payload["seasonal_volume_index"] = seasonal_volume_index
    if holiday_flag is not None:
        payload["holiday_flag"] = holiday_flag
    payload.update(overrides)
    return payload


def reschedule_payload(action, makeup_service_date=None, reason=None):
    payload = {"action": action}
    if makeup_service_date is not None:
        payload["makeup_service_date"] = makeup_service_date
    if reason is not None:
        payload["reason"] = reason
    return payload


# --------------------------------------------------------- route assignments
def route_payload(contractor_id, unit_from, unit_to, expected_service_night_version,
                  **overrides):
    payload = {
        "contractor_id": contractor_id,
        "unit_from": unit_from,
        "unit_to": unit_to,
        "expected_service_night_version": expected_service_night_version,
    }
    payload.update(overrides)
    return payload


def abandon_route_payload(reason="Van broke down"):
    return {"reason": reason}


# --------------------------------------------------------------------- scans
def scan_payload(resident_id, scan_result="SERVICED", container_type="TRASH_BIN",
                 non_compliance_type=None, **overrides):
    payload = {
        "resident_id": resident_id,
        "scan_result": scan_result,
        "container_type": container_type,
    }
    if non_compliance_type is not None:
        payload["non_compliance_type"] = non_compliance_type
    payload.update(overrides)
    return payload


def manual_fine_payload(note=None):
    return {} if note is None else {"note": note}


def void_tag_payload(reason="Tagged the wrong door"):
    return {"reason": reason}


# --------------------------------------------------------------------- fines
def dispute_payload(reason="The bin was not mine"):
    return {"reason": reason}


def adjudicate_payload(outcome, note=None):
    payload = {"outcome": outcome}
    if note is not None:
        payload["note"] = note
    return payload


# ---------------------------------------------------------------- incidents
def incident_payload(incident_type="JAM", description=None):
    payload = {"incident_type": incident_type}
    if description is not None:
        payload["description"] = description
    return payload


def resolve_incident_payload(resolution_note="Compactor cleared by the vendor"):
    return {"resolution_note": resolution_note}


# --------------------------------------------------------------- statements
def statement_payload(billing_period, expected_contract_version, **overrides):
    payload = {
        "billing_period": billing_period,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def void_statement_payload(reason="Cut against the wrong terms"):
    return {"reason": reason}
