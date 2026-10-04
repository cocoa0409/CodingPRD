"""Row -> wire serialisation for every resource.

Field order mirrors the entity declarations in SCAFFOLD section 1.1. Computed
fields are re-derived here so that GETs always report a value consistent with the
logical clock, whether or not some earlier write cached it on the row.
"""

import db
import rules
from db import parse_dt


def _dec(value):
    return rules.dec(value)


def _num(value):
    return rules.num(value)


# ---------------------------------------------------------------------------
# ClientLaboratory
# ---------------------------------------------------------------------------

def client_laboratory(row):
    rules.recompute_client_derived(row)
    return {
        "id": row["id"],
        "name": row.get("name"),
        "clia_number": row.get("clia_number"),
        "client_type": row.get("client_type"),
        "state_code": row.get("state_code"),
        "billing_arrangement": row.get("billing_arrangement"),
        "credit_limit_cents": row.get("credit_limit_cents"),
        "status": row.get("status"),
        "onboarding_status": row.get("onboarding_status"),
        "interface_status": row.get("interface_status"),
        "requirement_notes_published_at": db.iso(row.get("requirement_notes_published_at")),
        "outstanding_balance_cents": _num(row.get("outstanding_balance_cents") or 0),
        "billable_line_count": row.get("billable_line_count") or 0,
        "forward_utilization_score": row.get("forward_utilization_score") or 0,
        "settled_utilization_score": row.get("settled_utilization_score") or 0,
        "utilization_flag": bool(row.get("utilization_flag")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "version": row.get("version"),
    }


# ---------------------------------------------------------------------------
# CourierRun
# ---------------------------------------------------------------------------

def courier_run(row):
    row["specimen_count"] = sum(
        1 for s in db.all_rows("specimens") if s.get("courier_run_id") == row["id"]
    )
    return {
        "id": row["id"],
        "client_laboratory_id": row.get("client_laboratory_id"),
        "route_code": row.get("route_code"),
        "origin_city": row.get("origin_city"),
        "destination_city": row.get("destination_city"),
        "vehicle_id": row.get("vehicle_id"),
        "scheduled_departure_at": db.iso(row.get("scheduled_departure_at")),
        "scheduled_arrival_at": db.iso(row.get("scheduled_arrival_at")),
        "scheduled_pickup_at": db.iso(row.get("scheduled_pickup_at")),
        "scheduled_delivery_at": db.iso(row.get("scheduled_delivery_at")),
        "temperature_control_mode": row.get("temperature_control_mode"),
        "specimen_count": row.get("specimen_count") or 0,
        "transit_allowance_minutes": _num(row.get("transit_allowance_minutes") or 0),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "version": row.get("version"),
    }


# ---------------------------------------------------------------------------
# TestCatalogEntry
# ---------------------------------------------------------------------------

def test_catalog_entry(row):
    return {
        "id": row["id"],
        "test_code": row.get("test_code"),
        "test_name": row.get("test_name"),
        "test_category": row.get("test_category"),
        "method": row.get("method"),
        "required_specimen_type": row.get("required_specimen_type"),
        "container_type": row.get("container_type"),
        "min_volume_ml": _num(row.get("min_volume_ml")),
        "transport_temperature": row.get("transport_temperature"),
        "stability_hours_ambient": _num(row.get("stability_hours_ambient")),
        "stability_hours_refrigerated": _num(row.get("stability_hours_refrigerated")),
        "stability_hours_frozen": _num(row.get("stability_hours_frozen")),
        "base_tat_hours": _num(row.get("base_tat_hours")),
        "list_price_cents": row.get("list_price_cents"),
        "client_price_cents": row.get("client_price_cents"),
        "floor_price_cents": row.get("floor_price_cents"),
        "reference_low": _num(row.get("reference_low")),
        "reference_high": _num(row.get("reference_high")),
        "critical_value_low": _num(row.get("critical_value_low")),
        "critical_value_high": _num(row.get("critical_value_high")),
        "reflex_test_code": row.get("reflex_test_code"),
        "reflex_condition": row.get("reflex_condition"),
        "reflex_within_hours": _num(row.get("reflex_within_hours")),
        "reflex_min_remaining_hours": _num(row.get("reflex_min_remaining_hours")),
        "is_utilization_managed": bool(row.get("is_utilization_managed")),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "version": row.get("version"),
    }


# ---------------------------------------------------------------------------
# Specimen
# ---------------------------------------------------------------------------

def specimen(row):
    remaining = rules.remaining_stability_hours(row)
    row["remaining_stability_hours"] = _num(remaining) if remaining is not None else None
    row["total_aliquot_volume_ml"] = _num(rules.total_aliquot_volume_ml(row))
    return {
        "id": row["id"],
        "client_laboratory_id": row.get("client_laboratory_id"),
        "courier_run_id": row.get("courier_run_id"),
        "aliquot_parent_id": row.get("aliquot_parent_id"),
        "accession_number": row.get("accession_number"),
        "patient_mrn": row.get("patient_mrn"),
        "specimen_type": row.get("specimen_type"),
        "container_type": row.get("container_type"),
        "volume_ml": _num(row.get("volume_ml")),
        "aliquot_volume_ml": _num(row.get("aliquot_volume_ml")),
        "collection_at": db.iso(row.get("collection_at")),
        "received_at": db.iso(row.get("received_at")),
        "transport_temperature": row.get("transport_temperature"),
        "condition": row.get("condition"),
        "condition_reason_code": row.get("condition_reason_code"),
        "rejection_reason_code": row.get("rejection_reason_code"),
        "remaining_stability_hours": row.get("remaining_stability_hours"),
        "total_aliquot_volume_ml": row.get("total_aliquot_volume_ml"),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "version": row.get("version"),
    }


# ---------------------------------------------------------------------------
# SendOutOrder
# ---------------------------------------------------------------------------

def send_out_order(row):
    row["stability_deadline_at"] = rules.stability_deadline(row)
    # The order's test lines are carried alongside the order in ascending
    # line_sequence, which is the traversal order the per-line pricing and
    # late-credit rules of PRD section 3.10 require.
    lines = [
        l for l in db.all_rows("order_test_lines")
        if l.get("send_out_order_id") == row["id"]
    ]
    lines.sort(key=lambda l: (l.get("line_sequence") is None, l.get("line_sequence")))
    return {
        "id": row["id"],
        "client_laboratory_id": row.get("client_laboratory_id"),
        "specimen_id": row.get("specimen_id"),
        "reflex_source_order_id": row.get("reflex_source_order_id"),
        "order_number": row.get("order_number"),
        "patient_mrn": row.get("patient_mrn"),
        "client_requested_at": db.iso(row.get("client_requested_at")),
        "priority": row.get("priority"),
        "rush_tier": row.get("rush_tier"),
        "base_tat_hours": _num(row.get("base_tat_hours")),
        "effective_tat_hours": _num(row.get("effective_tat_hours")),
        "expected_result_at": db.iso(row.get("expected_result_at")),
        "stability_deadline_at": db.iso(row.get("stability_deadline_at")),
        "provisional_charge_cents": _num(row.get("provisional_charge_cents")),
        "order_final_charge_cents": _num(row.get("order_final_charge_cents")),
        "charge_variance_cents": _num(row.get("charge_variance_cents")),
        "tat_credit_cents": _num(row.get("tat_credit_cents")),
        "interpretive_comment": row.get("interpretive_comment"),
        "override_utilization_guard": bool(row.get("override_utilization_guard")),
        "test_lines": [order_test_line(l) for l in lines],
        "order_status": row.get("order_status"),
        "billing_status": row.get("billing_status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "version": row.get("version"),
    }


# ---------------------------------------------------------------------------
# OrderTestLine
# ---------------------------------------------------------------------------

def order_test_line(row):
    return {
        "id": row["id"],
        "send_out_order_id": row.get("send_out_order_id"),
        "test_catalog_entry_id": row.get("test_catalog_entry_id"),
        "line_sequence": row.get("line_sequence"),
        "is_add_on": bool(row.get("is_add_on")),
        "add_on_at": db.iso(row.get("add_on_at")),
        "result_value": _num(row.get("result_value")),
        "result_units": row.get("result_units"),
        "result_flag": rules.compute_result_flag(row),
        "critical_value_notified_to": row.get("critical_value_notified_to"),
        "critical_value_notified_at": db.iso(row.get("critical_value_notified_at")),
        "entered_by_user_id": row.get("entered_by_user_id"),
        "billed_cents": _num(row.get("billed_cents")),
        "tat_credit_cents": _num(row.get("tat_credit_cents")),
        "result_released_at": db.iso(row.get("result_released_at")),
        "line_status": row.get("line_status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "version": row.get("version"),
    }


# ---------------------------------------------------------------------------
# InstrumentRun
# ---------------------------------------------------------------------------

def instrument_run(row):
    return {
        "id": row["id"],
        "test_catalog_entry_id": row.get("test_catalog_entry_id"),
        "instrument_code": row.get("instrument_code"),
        "section": row.get("section"),
        "decontamination_buffer_minutes": row.get("decontamination_buffer_minutes"),
        "reserved_start_at": db.iso(row.get("reserved_start_at")),
        "reserved_end_at": db.iso(row.get("reserved_end_at")),
        "occupied_until_at": db.iso(row.get("occupied_until_at")),
        "run_status": row.get("run_status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "version": row.get("version"),
    }


# ---------------------------------------------------------------------------
# InterfaceBuild
# ---------------------------------------------------------------------------

def interface_build(row):
    return {
        "id": row["id"],
        "client_laboratory_id": row.get("client_laboratory_id"),
        "build_version_label": row.get("build_version_label"),
        "format": row.get("format"),
        "order_interface_enabled": bool(row.get("order_interface_enabled")),
        "result_interface_enabled": bool(row.get("result_interface_enabled")),
        "certified_at": db.iso(row.get("certified_at")),
        "superseded_at": db.iso(row.get("superseded_at")),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "version": row.get("version"),
    }


# ---------------------------------------------------------------------------
# ResultInterfaceMessage
# ---------------------------------------------------------------------------

def result_interface_message(row):
    order = db.get("send_out_orders", row.get("send_out_order_id"))
    if row.get("discrete_field_count") is None and order is not None:
        row["discrete_field_count"] = sum(
            1
            for l in db.all_rows("order_test_lines")
            if l.get("send_out_order_id") == order["id"]
            and l.get("line_status") in ("INTERIM", "FINAL")
        )
    return {
        "id": row["id"],
        "send_out_order_id": row.get("send_out_order_id"),
        "interface_build_id": row.get("interface_build_id"),
        "message_type": row.get("message_type"),
        "control_id": row.get("control_id"),
        "interpreted_comment_included": bool(row.get("interpreted_comment_included")),
        "discrete_field_count": row.get("discrete_field_count") or 0,
        "queued_at": db.iso(row.get("queued_at")),
        "transmitted_at": db.iso(row.get("transmitted_at")),
        "retry_count": row.get("retry_count") or 0,
        "next_retry_offset_minutes": _num(row.get("next_retry_offset_minutes")),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "version": row.get("version"),
    }


# ---------------------------------------------------------------------------
# BillingLedger
# ---------------------------------------------------------------------------

def billing_ledger(row):
    return {
        "id": row["id"],
        "client_laboratory_id": row.get("client_laboratory_id"),
        "billed_cents": _num(row.get("billed_cents") or 0),
        "voided_cents": _num(row.get("voided_cents") or 0),
        "net_billed_cents": _num(row.get("net_billed_cents") or 0),
        "charge_entry_count": row.get("charge_entry_count") or 0,
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "version": row.get("version"),
    }


# ---------------------------------------------------------------------------
# UtilizationAdvisory
# ---------------------------------------------------------------------------

def utilization_advisory(row):
    return {
        "id": row["id"],
        "client_laboratory_id": row.get("client_laboratory_id"),
        "test_catalog_entry_id": row.get("test_catalog_entry_id"),
        "source_order_id": row.get("source_order_id"),
        "advisory_type": row.get("advisory_type"),
        "message": row.get("message"),
        "send_count": row.get("send_count") or 0,
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "version": row.get("version"),
    }


SERIALIZERS = {
    "client_laboratories": client_laboratory,
    "courier_runs": courier_run,
    "test_catalog_entries": test_catalog_entry,
    "specimens": specimen,
    "send_out_orders": send_out_order,
    "order_test_lines": order_test_line,
    "instrument_runs": instrument_run,
    "interface_builds": interface_build,
    "result_interface_messages": result_interface_message,
    "billing_ledgers": billing_ledger,
    "utilization_advisories": utilization_advisory,
}


def render(kind, row):
    return SERIALIZERS[kind](row)