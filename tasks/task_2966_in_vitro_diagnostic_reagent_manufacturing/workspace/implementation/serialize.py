"""Wire representations of the fourteen aggregates.

Twelve aggregates carry id, created_at, updated_at and version.  A monitoring
sample and a test result are immutable event records and carry only id and
created_at — updated_at and version are absent from the payload entirely
(PRD 2.4).
"""

from decimal import Decimal

from store import fmt_ts


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row, payload):
    payload["created_at"] = fmt_ts(row["created_at"])
    payload["updated_at"] = fmt_ts(row["updated_at"])
    payload["version"] = row["version"]
    return payload


def material_specification(row):
    return _common(row, {
        "id": row["id"],
        "material_code": row["material_code"],
        "material_type": row["material_type"],
        "is_critical": row["is_critical"],
        "potency_min_pct": _num(row["potency_min_pct"]),
        "potency_max_pct": _num(row["potency_max_pct"]),
        "endotoxin_max_eu_per_ml": _num(row["endotoxin_max_eu_per_ml"]),
        "purity_min_pct": _num(row["purity_min_pct"]),
        "required_test_codes": list(row["required_test_codes"]),
        "acceptance_mode": row["acceptance_mode"],
        "max_retests": row["max_retests"],
        "retest_window_days": row["retest_window_days"],
    })


def material_lot(row):
    return _common(row, {
        "id": row["id"],
        "material_specification_id": row["material_specification_id"],
        "vendor_lot_code": row["vendor_lot_code"],
        "received_quantity_units": _num(row["received_quantity_units"]),
        "available_quantity_units": _num(row["available_quantity_units"]),
        "consumed_quantity_units": _num(row["consumed_quantity_units"]),
        "expiry_date": fmt_ts(row["expiry_date"]),
        "qualification_status": row["qualification_status"],
        "retest_count": row["retest_count"],
        "first_oos_at": fmt_ts(row["first_oos_at"]),
        "acceptance_score": _num(row["acceptance_score"]),
        "dispositioned_by_user_id": row["dispositioned_by_user_id"],
        "dispositioned_at": fmt_ts(row["dispositioned_at"]),
        "quarantine_reason": row["quarantine_reason"],
    })


def product_specification(row):
    return _common(row, {
        "id": row["id"],
        "product_code": row["product_code"],
        "reference_material_code": row["reference_material_code"],
        "required_material_codes": list(row["required_material_codes"]),
        "release_test_codes": list(row["release_test_codes"]),
        "max_reference_bias_pct": _num(row["max_reference_bias_pct"]),
        "shelf_life_months_claim": row["shelf_life_months_claim"],
        "storage_condition": row["storage_condition"],
        "min_shelf_life_days_at_ship": row["min_shelf_life_days_at_ship"],
        "clearance_status": row["clearance_status"],
        "submission_ref": row["submission_ref"],
        "cleared_at": fmt_ts(row["cleared_at"]),
        "design_trace_complete": row["design_trace_complete"],
    })


def design_control_record(row):
    return _common(row, {
        "id": row["id"],
        "product_specification_id": row["product_specification_id"],
        "record_type": row["record_type"],
        "document_ref": row["document_ref"],
        "traces_to_record_id": row["traces_to_record_id"],
        "trace_depth": row["trace_depth"],
        "status": row["status"],
        "authored_by_user_id": row["authored_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "approved_at": fmt_ts(row["approved_at"]),
    })


def reagent_lot(row):
    return _common(row, {
        "id": row["id"],
        "product_specification_id": row["product_specification_id"],
        "lot_code": row["lot_code"],
        "planned_units": row["planned_units"],
        "filled_units": row["filled_units"],
        "available_units": row["available_units"],
        "allocated_units": row["allocated_units"],
        "shipped_units": row["shipped_units"],
        "quarantined_units": row["quarantined_units"],
        "disposition_status": row["disposition_status"],
        "distribution_status": row["distribution_status"],
        "fill_completed_at": fmt_ts(row["fill_completed_at"]),
        "assigned_shelf_life_months": row["assigned_shelf_life_months"],
        "shelf_life_basis": row["shelf_life_basis"],
        "shelf_life_basis_study_id": row["shelf_life_basis_study_id"],
        "expiry_date": fmt_ts(row["expiry_date"]),
        "release_bias_max_pct": _num(row["release_bias_max_pct"]),
        "release_bias_sum_pct": _num(row["release_bias_sum_pct"]),
        "em_excursion_count": row["em_excursion_count"],
        "bioburden_cfu_per_ml": _num(row["bioburden_cfu_per_ml"]),
        "bridging_required": row["bridging_required"],
        "released_by_user_id": row["released_by_user_id"],
        "released_at": fmt_ts(row["released_at"]),
    })


def lot_component(row):
    return _common(row, {
        "id": row["id"],
        "reagent_lot_id": row["reagent_lot_id"],
        "material_lot_id": row["material_lot_id"],
        "component_role": row["component_role"],
        "quantity_used": _num(row["quantity_used"]),
        "status": row["status"],
        "material_code_snapshot": row["material_code_snapshot"],
        "vendor_lot_code_snapshot": row["vendor_lot_code_snapshot"],
    })


def fill_run(row):
    return _common(row, {
        "id": row["id"],
        "reagent_lot_id": row["reagent_lot_id"],
        "line_code": row["line_code"],
        "formulation_batch_code": row["formulation_batch_code"],
        "scheduled_start": fmt_ts(row["scheduled_start"]),
        "scheduled_end": fmt_ts(row["scheduled_end"]),
        "planned_fill_units": row["planned_fill_units"],
        "filled_units": row["filled_units"],
        "status": row["status"],
        "started_at": fmt_ts(row["started_at"]),
        "ended_at": fmt_ts(row["ended_at"]),
        "minor_excursion_count": row["minor_excursion_count"],
        "major_excursion_count": row["major_excursion_count"],
        "bioburden_cfu_per_ml": _num(row["bioburden_cfu_per_ml"]),
        "environmental_state": row["environmental_state"],
        "abort_reason": row["abort_reason"],
    })


def monitoring_sample(row):
    return {
        "id": row["id"],
        "fill_run_id": row["fill_run_id"],
        "sample_type": row["sample_type"],
        "location_code": row["location_code"],
        "result_value": _num(row["result_value"]),
        "sampled_at": fmt_ts(row["sampled_at"]),
        "limit_value": _num(row["limit_value"]),
        "excursion": row["excursion"],
        "excursion_grade": row["excursion_grade"],
        "created_at": fmt_ts(row["created_at"]),
    }


def test_result(row):
    return {
        "id": row["id"],
        "subject_type": row["subject_type"],
        "material_lot_id": row["material_lot_id"],
        "reagent_lot_id": row["reagent_lot_id"],
        "stability_study_id": row["stability_study_id"],
        "month_index": row["month_index"],
        "test_code": row["test_code"],
        "measured_value": _num(row["measured_value"]),
        "reference_measured_value": _num(row["reference_measured_value"]),
        "is_retest": row["is_retest"],
        "outcome": row["outcome"],
        "bias_pct": _num(row["bias_pct"]),
        "recovery_pct": _num(row["recovery_pct"]),
        "performed_by_user_id": row["performed_by_user_id"],
        "performed_at": fmt_ts(row["performed_at"]),
        "created_at": fmt_ts(row["created_at"]),
    }


def stability_study(row):
    return _common(row, {
        "id": row["id"],
        "product_specification_id": row["product_specification_id"],
        "reagent_lot_id": row["reagent_lot_id"],
        "study_type": row["study_type"],
        "chamber_code": row["chamber_code"],
        "storage_temp_c": _num(row["storage_temp_c"]),
        "protocol_start": fmt_ts(row["protocol_start"]),
        "protocol_end": fmt_ts(row["protocol_end"]),
        "planned_timepoints_months": list(row["planned_timepoints_months"]),
        "baseline_value": _num(row["baseline_value"]),
        "status": row["status"],
        "timepoint_count": row["timepoint_count"],
        "last_conforming_month": row["last_conforming_month"],
        "established_shelf_life_months": row["established_shelf_life_months"],
        "shelf_life_method": row["shelf_life_method"],
        "protocol_approved_by_user_id": row["protocol_approved_by_user_id"],
    })


def bridging_study(row):
    return _common(row, {
        "id": row["id"],
        "predicate_lot_id": row["predicate_lot_id"],
        "candidate_lot_id": row["candidate_lot_id"],
        "changed_material_lot_id": row["changed_material_lot_id"],
        "paired_test_codes": list(row["paired_test_codes"]),
        "status": row["status"],
        "mean_bias_pct": _num(row["mean_bias_pct"]),
        "max_bias_pct": _num(row["max_bias_pct"]),
        "equivalence_verdict": row["equivalence_verdict"],
        "decided_by_user_id": row["decided_by_user_id"],
        "decided_at": fmt_ts(row["decided_at"]),
    })


def complaint(row):
    return _common(row, {
        "id": row["id"],
        "reagent_lot_id": row["reagent_lot_id"],
        "complaint_code": row["complaint_code"],
        "narrative": row["narrative"],
        "device_related_death_or_injury": row["device_related_death_or_injury"],
        "received_at": fmt_ts(row["received_at"]),
        "severity": row["severity"],
        "malfunction_suspected": row["malfunction_suspected"],
        "reportable": row["reportable"],
        "report_due_at": fmt_ts(row["report_due_at"]),
        "report_ref": row["report_ref"],
        "reported_at": fmt_ts(row["reported_at"]),
        "report_late": row["report_late"],
        "field_action": row["field_action"],
        "field_action_decided_by_user_id": row["field_action_decided_by_user_id"],
        "field_action_decided_at": fmt_ts(row["field_action_decided_at"]),
        "triaged_by_user_id": row["triaged_by_user_id"],
        "status": row["status"],
    })


def distribution_order(row):
    return _common(row, {
        "id": row["id"],
        "product_specification_id": row["product_specification_id"],
        "customer_code": row["customer_code"],
        "requested_units": row["requested_units"],
        "required_min_shelf_life_days": row["required_min_shelf_life_days"],
        "ship_by": fmt_ts(row["ship_by"]),
        "allocation_policy": row["allocation_policy"],
        "allocated_units": row["allocated_units"],
        "shortfall_units": row["shortfall_units"],
        "status": row["status"],
        "planner_user_id": row["planner_user_id"],
    })


def allocation(row):
    return _common(row, {
        "id": row["id"],
        "distribution_order_id": row["distribution_order_id"],
        "reagent_lot_id": row["reagent_lot_id"],
        "allocated_units": row["allocated_units"],
        "sequence_index": row["sequence_index"],
        "status": row["status"],
        "shipped_at": fmt_ts(row["shipped_at"]),
        "cumulative_excursion_minutes": _num(row["cumulative_excursion_minutes"]),
        "max_excursion_temp_c": _num(row["max_excursion_temp_c"]),
        "cold_chain_status": row["cold_chain_status"],
        "quarantine_reason": row["quarantine_reason"],
    })
