"""Row serialisation — exact scaffold field names, plus the common block.

Every persisted resource carries the common block of PRD §2.5: id, created_at,
updated_at, version. Field names below are copied from SCAFFOLD §1.1 entities.
"""

import db

COMMON = ["id", "created_at", "updated_at", "version"]


def present(row, defaults):
    """Return a JSON-safe copy of `row`, filling any declared field that is absent."""
    out = {}
    for key in COMMON:
        out[key] = row.get(key)
    for key in defaults:
        out[key] = row.get(key, defaults[key])
    return out


DEALER_FIELDS = {
    "dealer_code": None, "legal_name": None, "holdback_rate": None,
    "quality_tier": None, "standing": "ACTIVE", "chargeback_balance_due_cents": 0,
    "holdback_reserve_cents": 0, "funded_package_count": 0,
    "chargeback_rate_12mo_sum": 0, "funding_package_count_12mo": 0,
    "chargeback_rate_percent": 0.0,
}

DEALER_PACKAGE_FIELDS = {
    "dealer_id": None, "package_reference": None, "submitted_at": None,
    "package_status": "DRAFT", "package_capex_cents": 0,
    "package_holdback_cents": 0, "package_funding_amount_cents": 0,
    "funded_count": 0, "declined_count": 0, "submitted_contract_count": 0,
    "expires_at": None, "closed_at": None, "package_posture": None,
    "allowed_holdback_rate_ceiling_cents": 0, "approved_holdback_cents": 0,
}

CONTRACT_FIELDS = {
    "contract_number": None, "source_channel": None, "dealer_id": None,
    "customer_id": None, "dealer_package_id": None, "equipment_config_code": None,
    "credit_score": None, "contract_term_months": None,
    "monthly_monitoring_cents": None, "capex_cents": 0, "funding_amount_cents": 0,
    "holdback_cents": 0, "holdback_remaining_cents": 0,
    "dealer_holdback_sweep_cents": 0, "contract_status": "PENDING_VALIDATION",
    "equipment_financed_cents": 0, "financed_charge_at_apr_cents": 0,
    "equipment_payment_cents": 0, "post_warranty_cents": 0, "warranty_months": 6,
    "assumption_count": 0, "funding_points": 0, "attrition_checked_at": None,
    "activated_at": None, "cancelled_at": None, "cancelled_from_status": None,
    "chargeback_exempt": False, "equipment_financing_disclosed": None,
    "validation_failure_code": None, "monitoring_hold_until": None,
    "funded_at": None, "chargeback_adjudicated": False,
}

CUSTOMER_FIELDS = {
    "full_name": None, "email": None, "phone": None, "status": "PENDING_ACTIVATION",
}

SITE_FIELDS = {
    "contract_id": None, "address_line": None, "city": None, "state_code": None,
    "postal_code": None, "occupancy_status": "OCCUPIED",
}

INSTALLATION_FIELDS = {
    "contract_id": None, "scheduled_at": None, "duration_minutes": 180,
    "installation_engineer_id": None, "install_status": "SCHEDULED",
    "equipment_config_code": None, "activation_committed": False,
    "reason": None,
}

MONITORING_ACCOUNT_FIELDS = {
    "contract_id": None, "central_station_host": None,
    "monitoring_account_number": None, "provision_state": "UNPROVISIONED",
    "activation_gate_met": False, "site_id": None,
}

ALARM_EVENT_FIELDS = {
    "monitoring_account_id": None, "signal_source": None, "occurred_at": None,
    "entered_at_utc": None, "verification_outcome": "PENDING", "verified_at": None,
    "counted_for_false_alarm": False, "counted_for_window_total": False,
    "legal_hold": False,
}

DISPATCH_FIELDS = {
    "alarm_event_id": None, "dispatch_status": "REQUESTED", "requested_at": None,
    "dispatched_at": None, "abort_reason": "",
}

REDUCTION_FIELDS = {
    "monitoring_account_id": None, "action_type": None, "triggered_at": None,
    "resolved_at": None, "action_status": "OPEN",
}

SWEEP_FIELDS = {
    "sweep_month": None, "ran_at": None, "evaluated_count": 0,
    "delinquent_count": 0, "resumed_count": 0, "flagged_contract_ids": [],
}

FLAG_FIELDS = {
    "attrition_sweep_id": None, "contract_id": None, "cohort_month": None,
    "flagged_at": None,
}

VISIT_FIELDS = {
    "contract_id": None, "scheduled_at": None, "duration_minutes": 120,
    "work_type": None, "technician_id": None, "warranty_status_at_visit": None,
    "billing_route": None, "billed_cents": 0, "dealer_sweep_cents": 0,
    "allowed_duration_minutes": 60, "visit_status": "REQUESTED",
    "performed_at": None,
}

OWNER_FIELDS = {
    "contract_id": None, "customer_id": None, "ownership_status": "CURRENT",
    "started_at": None, "ended_at": None, "assumption_request_id": None,
}

ASSUMPTION_FIELDS = {
    "contract_id": None, "incoming_customer_id": None, "incoming_credit_score": None,
    "residence_state_code": None, "request_status": "PENDING_NEGOTIATION",
    "rejection_count": 0, "accepted_at": None, "completed_at": None,
}

RESCISSION_FIELDS = {
    "contract_id": None, "operator_id": None, "days_since_funding": 0,
    "request_status": "REQUESTED", "approved_by": None, "approved_at": None,
    "decided_at": None,
}


FIELDS = {
    "dealer": DEALER_FIELDS, "dealers": DEALER_FIELDS,
    "dealer_package": DEALER_PACKAGE_FIELDS, "dealer_packages": DEALER_PACKAGE_FIELDS,
    "contract": CONTRACT_FIELDS, "contracts": CONTRACT_FIELDS,
    "customer": CUSTOMER_FIELDS, "customers": CUSTOMER_FIELDS,
    "site": SITE_FIELDS, "sites": SITE_FIELDS,
    "installation": INSTALLATION_FIELDS, "installations": INSTALLATION_FIELDS,
    "monitoring_account": MONITORING_ACCOUNT_FIELDS,
    "monitoring_accounts": MONITORING_ACCOUNT_FIELDS,
    "alarm_event": ALARM_EVENT_FIELDS, "alarm_events": ALARM_EVENT_FIELDS,
    "dispatch_request": DISPATCH_FIELDS, "dispatch_requests": DISPATCH_FIELDS,
    "alarm_reduction_action": REDUCTION_FIELDS,
    "alarm_reduction_actions": REDUCTION_FIELDS,
    "attrition_sweep": SWEEP_FIELDS, "attrition_sweeps": SWEEP_FIELDS,
    "attrition_flag": FLAG_FIELDS, "attrition_flags": FLAG_FIELDS,
    "service_visit": VISIT_FIELDS, "service_visits": VISIT_FIELDS,
    "contract_owner": OWNER_FIELDS, "contract_owners": OWNER_FIELDS,
    "assumption_request": ASSUMPTION_FIELDS,
    "assumption_requests": ASSUMPTION_FIELDS,
    "rescission_request": RESCISSION_FIELDS,
    "rescission_requests": RESCISSION_FIELDS,
}


def serialize(kind, row):
    return present(row, FIELDS[kind])


def serialize_many(kind, rows):
    return [serialize(kind, row) for row in rows]


def serialize_current(kind, row):
    """Serialise from the store so callers always see the latest row state."""
    if row is None:
        return None
    return serialize(kind, row)