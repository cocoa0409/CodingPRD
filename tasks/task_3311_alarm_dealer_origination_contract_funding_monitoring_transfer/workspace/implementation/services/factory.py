"""Row constructors. Every row is minted here and inserted into the store.

PRD §2.5 — id is a server-minted UUID; created_at is set once, at creation;
version begins at its initial value (1) and is incremented on every mutation.
"""

import db
from util import fmt_ts, mint_id


def _base():
    now = db.now()
    return {
        "id": mint_id(),
        "created_at": fmt_ts(now),
        "updated_at": fmt_ts(now),
        "version": 1,
    }


def make_dealer(dealer_code, legal_name, holdback_rate, quality_tier):
    row = _base()
    row.update({
        "dealer_code": dealer_code,
        "legal_name": legal_name,
        "holdback_rate": holdback_rate,
        "quality_tier": quality_tier,
        "standing": "ACTIVE",
        "chargeback_balance_due_cents": 0,
        "holdback_reserve_cents": 0,
        "funded_package_count": 0,
        "chargeback_rate_12mo_sum": 0,
        "funding_package_count_12mo": 0,
        "chargeback_rate_percent": 0.0,
    })
    return db.state.insert("dealers", row)


def make_customer(full_name, email, phone):
    row = _base()
    row.update({"full_name": full_name, "email": email, "phone": phone,
                "status": "PENDING_ACTIVATION"})
    return db.state.insert("customers", row)


def make_dealer_package(dealer_id, package_reference):
    row = _base()
    row.update({
        "dealer_id": dealer_id,
        "package_reference": package_reference,
        "submitted_at": None,
        "package_status": "DRAFT",
        "package_capex_cents": 0,
        "package_holdback_cents": 0,
        "package_funding_amount_cents": 0,
        "funded_count": 0,
        "declined_count": 0,
        "submitted_contract_count": 0,
        "expires_at": None,
        "closed_at": None,
        "package_posture": None,
        "allowed_holdback_rate_ceiling_cents": 0,
        "approved_holdback_cents": 0,
    })
    return db.state.insert("dealer_packages", row)


def make_contract(customer_id, source_channel, equipment_config_code, credit_score,
                  contract_term_months, monthly_monitoring_cents,
                  dealer_id=None, dealer_package_id=None,
                  financed_charge_at_apr_cents=0):
    row = _base()
    row.update({
        "contract_number": None,
        "source_channel": source_channel,
        "dealer_id": dealer_id,
        "customer_id": customer_id,
        "dealer_package_id": dealer_package_id,
        "equipment_config_code": equipment_config_code,
        "credit_score": credit_score,
        "contract_term_months": contract_term_months,
        "monthly_monitoring_cents": monthly_monitoring_cents,
        "capex_cents": 0,
        "funding_amount_cents": 0,
        "holdback_cents": 0,
        "holdback_remaining_cents": 0,
        "dealer_holdback_sweep_cents": 0,
        "contract_status": "PENDING_VALIDATION",
        "equipment_financed_cents": 0,
        "financed_charge_at_apr_cents": financed_charge_at_apr_cents,
        "equipment_payment_cents": 0,
        "post_warranty_cents": 0,
        "warranty_months": 6,
        "assumption_count": 0,
        "funding_points": 0,
        "attrition_checked_at": None,
        "activated_at": None,
        "cancelled_at": None,
        "cancelled_from_status": None,
        "chargeback_exempt": False,
        "equipment_financing_disclosed": None,
        "validation_failure_code": None,
        "monitoring_hold_until": None,
        "funded_at": None,
        "chargeback_adjudicated": False,
    })
    return db.state.insert("contracts", row)


def make_site(contract_id, address_line, city, state_code, postal_code):
    row = _base()
    row.update({"contract_id": contract_id, "address_line": address_line, "city": city,
                "state_code": state_code, "postal_code": postal_code,
                "occupancy_status": "OCCUPIED"})
    return db.state.insert("sites", row)


def make_monitoring_account(contract_id, site_id=None):
    row = _base()
    row.update({
        "contract_id": contract_id,
        "central_station_host": None,
        "monitoring_account_number": None,
        "provision_state": "UNPROVISIONED",
        "activation_gate_met": False,
        "site_id": site_id,
    })
    return db.state.insert("monitoring_accounts", row)


def make_installation(contract_id, scheduled_at, installation_engineer_id,
                      duration_minutes=180):
    row = _base()
    row.update({
        "contract_id": contract_id,
        "scheduled_at": fmt_ts(scheduled_at),
        "duration_minutes": duration_minutes,
        "installation_engineer_id": installation_engineer_id,
        "install_status": "SCHEDULED",
        "equipment_config_code": None,
        "activation_committed": False,
        "reason": None,
    })
    return db.state.insert("installations", row)


def make_alarm_event(account_id, signal_source, occurred_at, entered_at_utc):
    row = _base()
    row.update({
        "monitoring_account_id": account_id,
        "signal_source": signal_source,
        "occurred_at": fmt_ts(occurred_at),
        "entered_at_utc": fmt_ts(entered_at_utc),
        "verification_outcome": "PENDING",
        "verified_at": None,
        "counted_for_false_alarm": False,
        "counted_for_window_total": False,
        "legal_hold": False,
    })
    return db.state.insert("alarm_events", row)


def make_dispatch_request(alarm_event_id):
    row = _base()
    row.update({
        "alarm_event_id": alarm_event_id,
        "dispatch_status": "REQUESTED",
        "requested_at": fmt_ts(db.now()),
        "dispatched_at": None,
        "abort_reason": "",
    })
    return db.state.insert("dispatch_requests", row)


def make_reduction_action(account_id, action_type):
    row = _base()
    row.update({
        "monitoring_account_id": account_id,
        "action_type": action_type,
        "triggered_at": fmt_ts(db.now()),
        "resolved_at": None,
        "action_status": "OPEN",
    })
    return db.state.insert("alarm_reduction_actions", row)


def make_attrition_sweep(sweep_month):
    row = _base()
    row.update({
        "sweep_month": sweep_month,
        "ran_at": None,
        "evaluated_count": 0,
        "delinquent_count": 0,
        "resumed_count": 0,
        "flagged_contract_ids": [],
    })
    return db.state.insert("attrition_sweeps", row)


def make_attrition_flag(sweep_id, contract_id, cohort_month):
    row = _base()
    row.update({
        "attrition_sweep_id": sweep_id,
        "contract_id": contract_id,
        "cohort_month": cohort_month,
        "flagged_at": fmt_ts(db.now()),
    })
    return db.state.insert("attrition_flags", row)


def make_service_visit(contract_id, scheduled_at, work_type, technician_id,
                       duration_minutes=120, allowed_duration_minutes=60):
    row = _base()
    row.update({
        "contract_id": contract_id,
        "scheduled_at": fmt_ts(scheduled_at) if scheduled_at is not None else None,
        "duration_minutes": duration_minutes,
        "work_type": work_type,
        "technician_id": technician_id,
        "warranty_status_at_visit": None,
        "billing_route": None,
        "billed_cents": 0,
        "dealer_sweep_cents": 0,
        "allowed_duration_minutes": allowed_duration_minutes,
        "visit_status": "REQUESTED",
        "performed_at": None,
    })
    return db.state.insert("service_visits", row)


def make_contract_owner(contract_id, customer_id, assumption_request_id=None):
    row = _base()
    row.update({
        "contract_id": contract_id,
        "customer_id": customer_id,
        "ownership_status": "CURRENT",
        "started_at": fmt_ts(db.now()),
        "ended_at": None,
        "assumption_request_id": assumption_request_id,
    })
    return db.state.insert("contract_owners", row)


def make_assumption_request(contract_id, incoming_customer_id, incoming_credit_score,
                            residence_state_code):
    row = _base()
    row.update({
        "contract_id": contract_id,
        "incoming_customer_id": incoming_customer_id,
        "incoming_credit_score": incoming_credit_score,
        "residence_state_code": residence_state_code,
        "request_status": "PENDING_NEGOTIATION",
        "rejection_count": 0,
        "accepted_at": None,
        "completed_at": None,
    })
    return db.state.insert("assumption_requests", row)


def make_rescission_request(contract_id, operator_id, days_since_funding):
    row = _base()
    row.update({
        "contract_id": contract_id,
        "operator_id": operator_id,
        "days_since_funding": days_since_funding,
        "request_status": "REQUESTED",
        "approved_by": None,
        "approved_at": None,
        "decided_at": None,
    })
    return db.state.insert("rescission_requests", row)