"""JSON shapes for every entity (SCAFFOLD 1.1 field lists, PRD section 2.4).

Mutable records carry id / created_at / updated_at / version.  The three
append-only logs -- PayComponent, EscrowTransaction and SettlementLine -- carry
only id and created_at; updated_at and version are absent from them entirely.

Derived fields are computed here, at read time, so a response can never show a
stale derived value (PRD section 2.11).
"""
import clock
import queries


def _common(record):
    return {
        "id": record["id"],
        "created_at": clock.iso(record["created_at"]),
        "updated_at": clock.iso(record["updated_at"]),
        "version": record["version"],
    }


def _log_common(record):
    return {
        "id": record["id"],
        "created_at": clock.iso(record["created_at"]),
    }


def pay_package(record):
    out = _common(record)
    out.update(
        {
            "name": record["name"],
            "driver_type": record["driver_type"],
            "mileage_guide": record["mileage_guide"],
            "per_diem_method": record["per_diem_method"],
            "escrow_required": record["escrow_required"],
            "escrow_target_cents": record["escrow_target_cents"],
            "escrow_monthly_deduction_cents": record["escrow_monthly_deduction_cents"],
            "status": record["status"],
            "supersedes_pay_package_id": record["supersedes_pay_package_id"],
            "has_pending_revision": record["has_pending_revision"],
            "activated_at": clock.iso(record["activated_at"]),
            "retired_at": clock.iso(record["retired_at"]),
            "component_count": queries.component_count(record["id"]),
        }
    )
    return out


def pay_component(record):
    out = _log_common(record)
    out.update(
        {
            "pay_package_id": record["pay_package_id"],
            "component_type": record["component_type"],
            "unit": record["unit"],
            "rate_value": record["rate_value"],
            "taxable": record["taxable"],
            "sequence": record["sequence"],
        }
    )
    return out


def driver(record):
    ytd_gross, ytd_taxable, ytd_per_diem = queries.ytd_totals(record["id"])
    out = _common(record)
    out.update(
        {
            "legal_name": record["legal_name"],
            "driver_type": record["driver_type"],
            "pay_package_id": record["pay_package_id"],
            "home_state": record["home_state"],
            "per_diem_elected": record["per_diem_elected"],
            "employment_status": record["employment_status"],
            "terminated_at": clock.iso(record["terminated_at"]),
            "escrow_status": record["escrow_status"],
            "escrow_target_cents": record["escrow_target_cents"],
            "escrow_monthly_deduction_cents": record["escrow_monthly_deduction_cents"],
            "escrow_balance_cents": queries.escrow_balance(record["id"]),
            "escrow_funded_at": clock.iso(record["escrow_funded_at"]),
            "escrow_return_due_at": clock.iso(record["escrow_return_due_at"]),
            "escrow_returned_at": clock.iso(record["escrow_returned_at"]),
            "pending_retro_correction_cents": queries.pending_retro_correction_cents(record["id"]),
            "settlement_hold": queries.settlement_hold(record["id"]),
            "ytd_gross_pay_cents": ytd_gross,
            "ytd_taxable_wages_cents": ytd_taxable,
            "ytd_per_diem_non_taxable_cents": ytd_per_diem,
            "advance_outstanding_cents": queries.driver_advance_outstanding_cents(record["id"]),
        }
    )
    return out


def escrow_transaction(record):
    out = _log_common(record)
    out.update(
        {
            "driver_id": record["driver_id"],
            "settlement_id": record["settlement_id"],
            "reverses_transaction_id": record["reverses_transaction_id"],
            "txn_type": record["txn_type"],
            "amount_cents": record["amount_cents"],
            "reason_code": record["reason_code"],
            "document_ref": record["document_ref"],
            "recorded_by_user_id": record["recorded_by_user_id"],
            "balance_after_cents": record["balance_after_cents"],
        }
    )
    return out


def load(record):
    out = _common(record)
    out.update(
        {
            "driver_id": record["driver_id"],
            "settlement_id": record["settlement_id"],
            "pay_package_id_snapshot": record["pay_package_id_snapshot"],
            "origin_zip": record["origin_zip"],
            "dest_zip": record["dest_zip"],
            "linehaul_revenue_cents": record["linehaul_revenue_cents"],
            "practical_miles": record["practical_miles"],
            "hhg_miles": record["hhg_miles"],
            "stop_count": record["stop_count"],
            "hours_worked_minutes": record["hours_worked_minutes"],
            "tarp_required": record["tarp_required"],
            "dispatched_at": clock.iso(record["dispatched_at"]),
            "delivered_at": clock.iso(record["delivered_at"]),
            "movement_status": record["movement_status"],
            "pay_status": record["pay_status"],
            "applied_mileage_guide": record["applied_mileage_guide"],
            "base_guide_miles": record["base_guide_miles"],
            "paid_miles": record["paid_miles"],
            "short_haul_floor_applied": record["short_haul_floor_applied"],
            "linehaul_pay_cents": record["linehaul_pay_cents"],
            "linehaul_line_type": record["linehaul_line_type"],
        }
    )
    return out


def accessorial_claim(record):
    out = _common(record)
    out.update(
        {
            "load_id": record["load_id"],
            "driver_id": record["driver_id"],
            "settlement_id": record["settlement_id"],
            "accessorial_type": record["accessorial_type"],
            "start_at": clock.iso(record["start_at"]),
            "end_at": clock.iso(record["end_at"]),
            "document_ref": record["document_ref"],
            "documentation_required": record["documentation_required"],
            "billable_units": record["billable_units"],
            "amount_cents": record["amount_cents"],
            "status": record["status"],
            "reject_reason_code": record["reject_reason_code"],
            "submitted_by_user_id": record["submitted_by_user_id"],
            "approved_by_user_id": record["approved_by_user_id"],
        }
    )
    return out


def advance(record):
    recovered = queries.advance_recovered_cents(record["id"])
    outstanding = 0 if record["status"] == "CANCELLED" else record["amount_cents"] - recovered
    out = _common(record)
    out.update(
        {
            "driver_id": record["driver_id"],
            "advance_type": record["advance_type"],
            "amount_cents": record["amount_cents"],
            "installment_cents": record["installment_cents"],
            "recovered_cents": recovered,
            "outstanding_cents": outstanding,
            "status": record["status"],
            "issued_at": clock.iso(record["issued_at"]),
        }
    )
    return out


def settlement(record):
    out = _common(record)
    out.update(
        {
            "driver_id": record["driver_id"],
            "period_start": clock.iso(record["period_start"]),
            "period_end": clock.iso(record["period_end"]),
            "status": record["status"],
            "prepared_by_user_id": record["prepared_by_user_id"],
            "approved_by_user_id": record["approved_by_user_id"],
            "prepared_at": clock.iso(record["prepared_at"]),
            "approved_at": clock.iso(record["approved_at"]),
            "paid_at": clock.iso(record["paid_at"]),
            "voided_at": clock.iso(record["voided_at"]),
            "payment_reference": record["payment_reference"],
            "void_reason_code": record["void_reason_code"],
            "itemization_required": record["itemization_required"],
            "line_count": len(queries.lines_of(record["id"])),
            "linehaul_total_cents": record["linehaul_total_cents"],
            "accessorial_total_cents": record["accessorial_total_cents"],
            "retro_correction_total_cents": record["retro_correction_total_cents"],
            "gross_pay_cents": record["gross_pay_cents"],
            "days_out_count": record["days_out_count"],
            "per_diem_non_taxable_cents": record["per_diem_non_taxable_cents"],
            "per_diem_excess_taxable_cents": record["per_diem_excess_taxable_cents"],
            "taxable_wages_cents": record["taxable_wages_cents"],
            "escrow_deduction_cents": record["escrow_deduction_cents"],
            "advance_recovery_cents": record["advance_recovery_cents"],
            "deduction_total_cents": record["deduction_total_cents"],
            "net_pay_cents": record["net_pay_cents"],
        }
    )
    return out


def settlement_line(record):
    out = _log_common(record)
    out.update(
        {
            "settlement_id": record["settlement_id"],
            "line_type": record["line_type"],
            "reference_type": record["reference_type"],
            "reference_id": record["reference_id"],
            "quantity": record["quantity"],
            "rate_value": record["rate_value"],
            "amount_cents": record["amount_cents"],
            "taxable": record["taxable"],
            "sequence": record["sequence"],
        }
    )
    return out


def dispute(record):
    out = _common(record)
    out.update(
        {
            "dispute_kind": record["dispute_kind"],
            "driver_id": record["driver_id"],
            "load_id": record["load_id"],
            "settlement_id": record["settlement_id"],
            "claimed_guide": record["claimed_guide"],
            "claimed_miles": record["claimed_miles"],
            "claimed_amount_cents": record["claimed_amount_cents"],
            "disputed_line_type": record["disputed_line_type"],
            "evidence_doc_ref": record["evidence_doc_ref"],
            "narrative": record["narrative"],
            "status": record["status"],
            "reopen_count": record["reopen_count"],
            "resolution_note": record["resolution_note"],
            "resolution_correction_id": record["resolution_correction_id"],
            "adjustment_cents": record["adjustment_cents"],
            "submitted_by_user_id": record["submitted_by_user_id"],
            "reviewed_by_user_id": record["reviewed_by_user_id"],
            "resolved_by_user_id": record["resolved_by_user_id"],
        }
    )
    return out


def retro_correction(record):
    out = _common(record)
    out.update(
        {
            "driver_id": record["driver_id"],
            "origin_settlement_id": record["origin_settlement_id"],
            "applied_settlement_id": record["applied_settlement_id"],
            "source_load_id": record["source_load_id"],
            "source_dispute_id": record["source_dispute_id"],
            "correction_type": record["correction_type"],
            "delta_gross_cents": record["delta_gross_cents"],
            "delta_taxable_cents": record["delta_taxable_cents"],
            "reason_code": record["reason_code"],
            "status": record["status"],
            "applied_at": clock.iso(record["applied_at"]),
            "cancelled_at": clock.iso(record["cancelled_at"]),
            "cancelled_by_user_id": record["cancelled_by_user_id"],
        }
    )
    return out
