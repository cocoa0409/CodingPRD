"""Entity factories, serializers, the universal version/audit bump, and the
accreditation-standing threshold function.

Every resource carries id / created_at / updated_at / version. version starts
at 1 on creation and increments by one on every mutation, including mutations
applied automatically as cascade side effects (PRD section 2.5).
"""

from db import STORE, get_clock, new_id, next_seq
from util import num, render_audit, render_domain

# Standing thresholds (calculation accreditation_standing)
PT_PROBATION_FAIL_COUNT = 2
PT_SUSPENSION_FAIL_COUNT = 3


def bump(rec):
    rec["version"] += 1
    rec["updated_at"] = get_clock()


def _base():
    now = get_clock()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def recompute_standing(customer):
    n = customer["pt_fail_count"]
    if n <= 1:
        customer["accreditation_standing"] = "GOOD_STANDING"
        customer["credit_hold"] = False
    elif n == PT_PROBATION_FAIL_COUNT:
        customer["accreditation_standing"] = "PROBATION"
        customer["credit_hold"] = False
    else:  # n >= 3
        customer["accreditation_standing"] = "SUSPENDED"
        customer["credit_hold"] = True


def units_available(lot):
    return (
        lot["total_units_produced"]
        - lot["qc_units_consumed"]
        - lot["units_reserved"]
        - lot["units_shipped"]
    )


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def make_program(b):
    rec = _base()
    rec.update(
        program_code=b["program_code"],
        name=b["name"],
        material_unit_price_cents=b["material_unit_price_cents"],
        discount_pct_federal=b["discount_pct_federal"],
        discount_pct_accredited_lab=b["discount_pct_accredited_lab"],
        discount_pct_general=b["discount_pct_general"],
        handling_fee_threshold_cents=b["handling_fee_threshold_cents"],
        handling_fee_flat_cents=b["handling_fee_flat_cents"],
        expedite_multiplier_pct=b["expedite_multiplier_pct"],
        daily_lab_capacity_minutes=b["daily_lab_capacity_minutes"],
    )
    return rec


def make_lot(b):
    rec = _base()
    rec.update(
        program_id=b["program_id"],
        material_code=b["material_code"],
        matrix_description=b["matrix_description"],
        total_units_produced=b["total_units_produced"],
        qc_units_consumed=0,
        units_reserved=0,
        units_shipped=0,
        allocation_policy=b.get("allocation_policy") or "FIFO",
        homogeneity_f_ratio=None,
        homogeneity_u_hom=None,
        homogeneity_verdict=None,
        hold_reason=None,
        status="SOURCING",
    )
    return rec


def make_method(b, analyst_user_id):
    rec = _base()
    rec.update(
        lot_id=b["lot_id"],
        method_code=b["method_code"],
        analyst_user_id=analyst_user_id,
        method_mean=b["method_mean"],
        method_std_uncertainty=b["method_std_uncertainty"],
        rejection_reason=None,
        status="DATA_SUBMITTED",
    )
    return rec


def make_certificate(b, numbers):
    rec = _base()
    rec.update(
        lot_id=b["lot_id"],
        certificate_code=b["certificate_code"],
        value_assignment_variant=b["value_assignment_variant"],
        uncertainty_components=b["uncertainty_components"],
        certified_value=numbers["certified_value"],
        characterization_uncertainty=numbers["characterization_uncertainty"],
        combined_standard_uncertainty=numbers["combined_standard_uncertainty"],
        expanded_uncertainty=numbers["expanded_uncertainty"],
        coverage_factor=2,
        validity_days=b["validity_days"],
        published_at=None,
        expiration_date=None,
        publisher_user_id=None,
        supersedes_certificate_id=None,
        status="DRAFT",
    )
    return rec


def make_customer(b):
    rec = _base()
    rec.update(
        name=b["name"],
        tier=b["tier"],
        credit_limit_cents=b["credit_limit_cents"],
        pt_fail_count=0,
        accreditation_standing="GOOD_STANDING",
        credit_hold=False,
    )
    return rec


def make_sales_order(lot_id, customer_id, quantity, quoted_unit_price_cents):
    rec = _base()
    rec.update(
        lot_id=lot_id,
        customer_id=customer_id,
        quantity=quantity,
        allocated_quantity=0,
        quoted_unit_price_cents=quoted_unit_price_cents,
        final_unit_price_cents=None,
        invoice_subtotal_cents=None,
        handling_fee_cents=None,
        invoice_total_cents=None,
        fulfilled_at=None,
        status="PLACED",
    )
    return rec


def make_service(b):
    rec = _base()
    rec.update(
        service_code=b["service_code"],
        measurand=b["measurand"],
        base_fee_cents=b["base_fee_cents"],
        per_point_fee_cents=b["per_point_fee_cents"],
        standard_turnaround_days=b["standard_turnaround_days"],
        status=b.get("status") or "ACTIVE",
    )
    return rec


def make_calibration_order(b, customer_id, quoted_fee_cents):
    rec = _base()
    rec.update(
        service_id=b["service_id"],
        customer_id=customer_id,
        artifact_description=b["artifact_description"],
        measurement_points=b["measurement_points"],
        expedite_requested=bool(b.get("expedite_requested") or False),
        quoted_fee_cents=quoted_fee_cents,
        final_fee_cents=None,
        scheduled_start=None,
        scheduled_end=None,
        duration_minutes=None,
        resolved_traceability_link_id=None,
        result=None,
        measured_correction=None,
        status="RECEIVED",
    )
    return rec


def make_link(b):
    rec = _base()
    rec.update(
        service_id=b["service_id"],
        standard_description=b["standard_description"],
        calibrated_by_lab=b["calibrated_by_lab"],
        calibrated_date=b["calibrated_date"],
        calibration_due_date=b["calibration_due_date"],
        uncertainty_contribution=b["uncertainty_contribution"],
    )
    return rec


def make_round(b):
    rec = _base()
    rec.update(
        lot_id=b["lot_id"],
        round_code=b["round_code"],
        round_type=b["round_type"],
        sample_units_reserved=b["sample_units_reserved"],
        assigned_value=None,
        reference_uncertainty=None,
        chi_squared=None,
        consistency_verdict=None,
        evaluated_count=0,
        status="PLANNING",
    )
    return rec


def make_result(round_id, customer_id, b):
    rec = _base()
    rec.update(
        round_id=round_id,
        customer_id=customer_id,
        lab_code=b["lab_code"],
        measured_value=b["measured_value"],
        measurement_uncertainty=b["measurement_uncertainty"],
        z_score=None,
        degree_of_equivalence=None,
        equivalence_uncertainty=None,
        performance_flag=None,
        status="SUBMITTED",
    )
    return rec


# ---------------------------------------------------------------------------
# Serializers (audit timestamps 3-digit; domain timestamps as the clock reads)
# ---------------------------------------------------------------------------

def _audit(rec, out):
    out["created_at"] = render_audit(rec["created_at"])
    out["updated_at"] = render_audit(rec["updated_at"])
    out["version"] = rec["version"]
    return out


def ser_program(p):
    return _audit(p, {
        "id": p["id"],
        "program_code": p["program_code"],
        "name": p["name"],
        "material_unit_price_cents": p["material_unit_price_cents"],
        "discount_pct_federal": p["discount_pct_federal"],
        "discount_pct_accredited_lab": p["discount_pct_accredited_lab"],
        "discount_pct_general": p["discount_pct_general"],
        "handling_fee_threshold_cents": p["handling_fee_threshold_cents"],
        "handling_fee_flat_cents": p["handling_fee_flat_cents"],
        "expedite_multiplier_pct": p["expedite_multiplier_pct"],
        "daily_lab_capacity_minutes": p["daily_lab_capacity_minutes"],
    })


def ser_lot(lot):
    return _audit(lot, {
        "id": lot["id"],
        "program_id": lot["program_id"],
        "material_code": lot["material_code"],
        "matrix_description": lot["matrix_description"],
        "total_units_produced": lot["total_units_produced"],
        "qc_units_consumed": lot["qc_units_consumed"],
        "units_reserved": lot["units_reserved"],
        "units_shipped": lot["units_shipped"],
        "units_available": units_available(lot),
        "allocation_policy": lot["allocation_policy"],
        "homogeneity_f_ratio": num(lot["homogeneity_f_ratio"]),
        "homogeneity_u_hom": num(lot["homogeneity_u_hom"]),
        "homogeneity_verdict": lot["homogeneity_verdict"],
        "hold_reason": lot["hold_reason"],
        "status": lot["status"],
    })


def ser_method(m):
    return _audit(m, {
        "id": m["id"],
        "lot_id": m["lot_id"],
        "method_code": m["method_code"],
        "analyst_user_id": m["analyst_user_id"],
        "method_mean": m["method_mean"],
        "method_std_uncertainty": m["method_std_uncertainty"],
        "rejection_reason": m["rejection_reason"],
        "status": m["status"],
    })


def ser_certificate(c):
    return _audit(c, {
        "id": c["id"],
        "lot_id": c["lot_id"],
        "certificate_code": c["certificate_code"],
        "value_assignment_variant": c["value_assignment_variant"],
        "uncertainty_components": c["uncertainty_components"],
        "certified_value": num(c["certified_value"]),
        "characterization_uncertainty": num(c["characterization_uncertainty"]),
        "combined_standard_uncertainty": num(c["combined_standard_uncertainty"]),
        "expanded_uncertainty": num(c["expanded_uncertainty"]),
        "coverage_factor": c["coverage_factor"],
        "validity_days": c["validity_days"],
        "published_at": render_domain(c["published_at"]),
        "expiration_date": render_domain(c["expiration_date"]),
        "publisher_user_id": c["publisher_user_id"],
        "supersedes_certificate_id": c["supersedes_certificate_id"],
        "status": c["status"],
    })


def ser_customer(c):
    return _audit(c, {
        "id": c["id"],
        "name": c["name"],
        "tier": c["tier"],
        "credit_limit_cents": c["credit_limit_cents"],
        "pt_fail_count": c["pt_fail_count"],
        "accreditation_standing": c["accreditation_standing"],
        "credit_hold": c["credit_hold"],
    })


def ser_sales_order(o):
    return _audit(o, {
        "id": o["id"],
        "lot_id": o["lot_id"],
        "customer_id": o["customer_id"],
        "quantity": o["quantity"],
        "allocated_quantity": o["allocated_quantity"],
        "quoted_unit_price_cents": o["quoted_unit_price_cents"],
        "final_unit_price_cents": o["final_unit_price_cents"],
        "invoice_subtotal_cents": o["invoice_subtotal_cents"],
        "handling_fee_cents": o["handling_fee_cents"],
        "invoice_total_cents": o["invoice_total_cents"],
        "fulfilled_at": render_domain(o["fulfilled_at"]),
        "status": o["status"],
    })


def ser_service(s):
    return _audit(s, {
        "id": s["id"],
        "service_code": s["service_code"],
        "measurand": s["measurand"],
        "base_fee_cents": s["base_fee_cents"],
        "per_point_fee_cents": s["per_point_fee_cents"],
        "standard_turnaround_days": s["standard_turnaround_days"],
        "status": s["status"],
    })


def ser_calibration_order(o):
    return _audit(o, {
        "id": o["id"],
        "service_id": o["service_id"],
        "customer_id": o["customer_id"],
        "artifact_description": o["artifact_description"],
        "measurement_points": o["measurement_points"],
        "expedite_requested": o["expedite_requested"],
        "quoted_fee_cents": o["quoted_fee_cents"],
        "final_fee_cents": o["final_fee_cents"],
        "scheduled_start": render_domain(o["scheduled_start"]),
        "scheduled_end": render_domain(o["scheduled_end"]),
        "duration_minutes": o["duration_minutes"],
        "resolved_traceability_link_id": o["resolved_traceability_link_id"],
        "result": o["result"],
        "measured_correction": o["measured_correction"],
        "status": o["status"],
    })


def ser_link(link):
    return _audit(link, {
        "id": link["id"],
        "service_id": link["service_id"],
        "standard_description": link["standard_description"],
        "calibrated_by_lab": link["calibrated_by_lab"],
        "calibrated_date": render_domain(link["calibrated_date"]),
        "calibration_due_date": render_domain(link["calibration_due_date"]),
        "uncertainty_contribution": link["uncertainty_contribution"],
    })


def ser_round(r):
    return _audit(r, {
        "id": r["id"],
        "lot_id": r["lot_id"],
        "round_code": r["round_code"],
        "round_type": r["round_type"],
        "sample_units_reserved": r["sample_units_reserved"],
        "assigned_value": num(r["assigned_value"]),
        "reference_uncertainty": num(r["reference_uncertainty"]),
        "chi_squared": num(r["chi_squared"]),
        "consistency_verdict": r["consistency_verdict"],
        "evaluated_count": r["evaluated_count"],
        "status": r["status"],
    })


def ser_result(r):
    return _audit(r, {
        "id": r["id"],
        "round_id": r["round_id"],
        "customer_id": r["customer_id"],
        "lab_code": r["lab_code"],
        "measured_value": r["measured_value"],
        "measurement_uncertainty": r["measurement_uncertainty"],
        "z_score": num(r["z_score"]),
        "degree_of_equivalence": num(r["degree_of_equivalence"]),
        "equivalence_uncertainty": num(r["equivalence_uncertainty"]),
        "performance_flag": r["performance_flag"],
        "status": r["status"],
    })
