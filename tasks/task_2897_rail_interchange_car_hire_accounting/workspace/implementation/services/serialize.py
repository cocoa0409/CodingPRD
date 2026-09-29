"""Row -> JSON projection.  Field lists follow the PRD section 3 entity tables."""
from datetime import datetime
from decimal import Decimal

import db

RAILROAD_FIELDS = [
    "id", "reporting_mark", "name", "status", "per_diem_credit_limit_cents",
    "foreign_car_balance", "per_diem_exposure_cents", "owned_car_count",
    "created_at", "updated_at", "version",
]

JUNCTION_FIELDS = [
    "id", "junction_code", "name", "road_a_id", "road_b_id", "status",
    "created_at", "updated_at", "version",
]

CAR_TYPE_FIELDS = [
    "id", "car_type_code", "description", "time_component_mode", "free_time_hours",
    "per_diem_rate_cents", "tier2_threshold_days", "tier2_per_diem_rate_cents",
    "hourly_rate_cents", "mileage_rate_millicents_per_mile", "loaded_mileage_only",
    "created_at",
]

CAR_FIELDS = [
    "id", "car_mark", "car_type_id", "owner_road_id", "current_handling_road_id",
    "custody_status", "mechanical_status", "routing_status",
    "prescribed_return_junction_id", "obligation_issued_at", "obligation_due_at",
    "bad_order_since", "bad_order_cleared_at", "cumulative_mileage",
    "created_at", "updated_at", "version",
]

EVENT_FIELDS = [
    "id", "car_id", "junction_id", "event_type", "delivering_road_id",
    "receiving_road_id", "interchange_at", "odometer_miles", "load_status",
    "corrects_event_id", "recorded_by_road_id", "status", "source", "created_at",
]

MOVEMENT_FIELDS = [
    "id", "car_id", "handling_road_id", "owner_road_id", "received_event_id",
    "delivered_event_id", "settlement_cycle_id", "start_at", "end_at", "load_status",
    "start_odometer_miles", "end_odometer_miles", "hire_liable", "chargeable_hours",
    "chargeable_days", "time_component_cents", "mileage_component_cents",
    "gross_hire_cents", "reclaim_credit_cents", "reverse_route_penalty_cents",
    "net_hire_cents", "adjusted_net_hire_cents", "bad_order_from", "bad_order_to",
    "reclaim_locked", "recompute_count", "status", "created_at", "updated_at", "version",
]

CLAIM_FIELDS = [
    "id", "movement_id", "filed_by_road_id", "against_road_id", "supporting_embargo_id",
    "reason", "window_from", "window_to", "detention_notified_at", "claimed_hours",
    "allowed_hours", "split_pct_applied", "credit_cents", "status", "filing_note",
    "decision_note", "disallow_reason", "withdraw_reason", "decided_at",
    "created_at", "updated_at", "version",
]

EMBARGO_FIELDS = [
    "id", "issuing_road_id", "junction_id", "car_type_id", "effective_from",
    "effective_to", "reason", "status", "lifted_at", "created_at", "updated_at", "version",
]

BILL_FIELDS = [
    "id", "car_id", "discovery_event_id", "billing_road_id", "responsible_road_id",
    "settlement_cycle_id", "defect_code", "defect_class", "defect_occurred_at",
    "labor_hours", "material_cents", "pre_authorization_reference", "labor_cents",
    "subtotal_cents", "handling_fee_cents", "total_cents", "responsibility_rule_applied",
    "counter_bill_round", "status", "submitted_at", "accepted_at", "rejected_at",
    "settled_at", "last_counter_at", "created_at", "updated_at", "version",
]

CYCLE_FIELDS = [
    "id", "payer_road_id", "payee_road_id", "period_month", "period_start_at",
    "period_end_at", "status", "variant_applied", "movement_line_count",
    "gross_hire_cents", "reclaim_credit_cents", "penalty_cents", "repair_charge_cents",
    "dispute_adjustment_cents", "pre_fee_net_cents", "clearinghouse_fee_cents",
    "net_settlement_cents", "as_reported_net_cents", "reconciled_net_cents",
    "computed_at", "exchanged_at", "dispute_deadline_at", "settled_at",
    "reopen_deadline_at", "reopened_at", "archived_at", "reopen_count", "reopen_reason",
    "created_at", "updated_at", "version",
]

DISPUTE_FIELDS = [
    "id", "settlement_cycle_id", "movement_id", "repair_bill_id", "filed_by_road_id",
    "respondent_road_id", "dispute_reason", "subject_net_at_filing_cents",
    "disputed_amount_cents", "counter_amount_cents", "resolution_amount_cents",
    "round_number", "status", "filing_note", "counter_note", "withdraw_reason",
    "last_action_at", "resolved_at", "created_at", "updated_at", "version",
]

CORRECTION_FIELDS = [
    "id", "car_id", "junction_id", "filed_by_road_id", "counterparty_road_id",
    "target_event_id", "resulting_event_id", "correction_type", "direction",
    "proposed_interchange_at", "proposed_odometer_miles", "proposed_load_status",
    "filing_note", "rejection_reason", "status", "confirm_deadline_at", "confirmed_at",
    "rejected_at", "applied_at", "expired_at", "created_at", "updated_at", "version",
]

LEDGER_FIELDS = [
    "id", "settlement_cycle_id", "movement_id", "repair_bill_id", "reclaim_claim_id",
    "dispute_id", "entry_type", "amount_cents", "debit_road_id", "credit_road_id",
    "effective_at", "memo", "created_at",
]


def _value(raw):
    if isinstance(raw, datetime):
        return db.iso(raw)
    if isinstance(raw, Decimal):
        return float(raw)
    return raw


def project(row, fields):
    return {name: _value(row.get(name)) for name in fields}


# --------------------------------------------------------------------------
# derived railroad figures (PRD sections 3.1 and 3.9)
# --------------------------------------------------------------------------


def owned_car_count(road_id):
    return sum(1 for c in db.cars.values() if c["owner_road_id"] == road_id)


def foreign_car_balance(road_id):
    return sum(
        1
        for m in db.movements.values()
        if m["status"] == "OPEN"
        and m["handling_road_id"] == road_id
        and m["owner_road_id"] != road_id
    )


def railroad(row):
    from services import exposure

    out = project(row, RAILROAD_FIELDS)
    out["owned_car_count"] = owned_car_count(row["id"])
    out["foreign_car_balance"] = foreign_car_balance(row["id"])
    out["per_diem_exposure_cents"] = exposure.exposure_figures(row, "SNAPSHOT")["exposure_cents"]
    return out


def junction(row):
    return project(row, JUNCTION_FIELDS)


def car_type(row):
    return project(row, CAR_TYPE_FIELDS)


def car(row):
    out = project(row, CAR_FIELDS)
    out["custody_status"] = derive_custody(row)
    out["cumulative_mileage"] = cumulative_mileage(row)
    return out


def derive_custody(car_row):
    """ON_HOME_ROAD when the owner holds it, ON_FOREIGN_ROAD otherwise."""
    if car_row["current_handling_road_id"] == car_row["owner_road_id"]:
        return "ON_HOME_ROAD"
    return "ON_FOREIGN_ROAD"


def cumulative_mileage(car_row):
    total = 0
    for m in db.movements.values():
        if m["car_id"] != car_row["id"] or m["status"] != "CLOSED":
            continue
        if m["end_odometer_miles"] is None:
            continue
        delta = int(m["end_odometer_miles"]) - int(m["start_odometer_miles"] or 0)
        if delta > 0:
            total += delta
    return total


def event(row):
    return project(row, EVENT_FIELDS)


def movement(row):
    return project(row, MOVEMENT_FIELDS)


def claim(row):
    return project(row, CLAIM_FIELDS)


def embargo(row):
    return project(row, EMBARGO_FIELDS)


def bill(row):
    return project(row, BILL_FIELDS)


def cycle(row):
    return project(row, CYCLE_FIELDS)


def dispute(row):
    return project(row, DISPUTE_FIELDS)


def correction(row):
    return project(row, CORRECTION_FIELDS)


def ledger_entry(row):
    return project(row, LEDGER_FIELDS)
