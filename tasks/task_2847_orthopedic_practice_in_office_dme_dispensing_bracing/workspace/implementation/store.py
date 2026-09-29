"""In-memory store. Starts completely empty on every boot; nothing is seeded."""
from common import fail, fmt_date, fmt_instant, new_id, now

db = {
    "clinics": {},
    "physicians": {},
    "fitters": {},
    "suppliers": {},
    "products": {},
    "par_levels": {},
    "patients": {},
    "encounters": {},
    "verifications": {},
    "prior_auths": {},
    "abn_notices": {},
    "fitting_records": {},
    "fab_orders": {},
    "returns": {},
    "_seq": [0],
}

# --------------------------------------------------------------------- enums

ACCREDITATION_BODIES = ("ABC", "BOC", "ACHC", "NONE")
SUPERVISION_LEVELS = ("DIRECT", "GENERAL")
SPECIALTIES = ("SPORTS_MEDICINE", "SPINE", "FOOT_ANKLE", "HAND", "TOTAL_JOINT")
DISPENSING_STATUSES = ("ACTIVE", "RESTRICTED", "SUSPENDED")
CREDENTIALS = ("CO", "CPO", "CFO", "CFm", "NONE")
PRIVILEGE_SCOPES = ("OFF_SHELF_ONLY", "CUSTOM_AND_OFF_SHELF")
PRODUCT_CATEGORIES = ("OFF_SHELF_PREFAB", "CUSTOM_FITTED_PREFAB", "CUSTOM_FABRICATED")
STOCK_POSTURES = ("OK", "BELOW_PAR", "CRITICAL", "STOCKOUT")
PAYER_TYPES = ("MEDICARE", "MEDICAID", "COMMERCIAL", "SELF_PAY")
CLINICAL_STATUSES = (
    "DRAFT", "DOCUMENTED", "AWAITING_DEVICE", "RESERVED", "FITTED",
    "DELIVERED", "RETURN_PENDING", "RETURNED", "VOIDED",
)
FINANCIAL_STATUSES = (
    "UNVERIFIED", "VERIFIED", "NON_COVERED", "AUTH_PENDING", "AUTH_APPROVED",
    "AUTH_DENIED", "ABN_ISSUED", "SELF_PAY", "BILLED", "REFUNDED", "WRITTEN_OFF",
)
HOLD_REASONS = ("CLINIC_SUSPENDED", "SUPPLIER_QUALITY_HOLD")
SIGNATURE_ROLES = ("PATIENT", "CAREGIVER", "REFUSED")
RESPONSIBILITY_VARIANTS = ("INSURANCE_ASSIGNED", "ABN_CASH_SELFPAY")
PRIOR_AUTH_STATUSES = ("SUBMITTED", "APPROVED", "DENIED", "PENDED", "EXPIRED")
ABN_REASONS = (
    "NOT_MEDICALLY_NECESSARY", "SAME_OR_SIMILAR_IN_LIFETIME", "NON_COVERED_ITEM",
    "AUTH_DENIED", "UNITS_EXCEED_AUTH",
)
ABN_STATUSES = ("ISSUED", "SIGNED", "DECLINED", "VOIDED")
ABN_OPTIONS = ("OPTION_1", "OPTION_2", "OPTION_3")
ABN_SIGNERS = ("PATIENT", "CAREGIVER")
FIT_OUTCOMES = ("ACCEPTABLE", "ADJUST_NEEDED", "REJECTED")
FAB_STATUSES = (
    "SUBMITTED", "IN_FABRICATION", "READY_FOR_FITTING", "ADJUSTMENT_REQUESTED",
    "ACCEPTED", "SUPPLIER_HOLD", "CANCELLED",
)
FAB_EVENTS = ("ACCEPT_ORDER", "DELIVER_TO_CLINIC")
FITTING_CHECK_OUTCOMES = ("ACCEPT", "REQUEST_ADJUSTMENT", "CANCEL")
RETURN_REASONS = ("POOR_FIT", "DEFECT", "WRONG_ITEM", "PATIENT_REFUSED")
RETURN_STATUSES = ("REQUESTED", "RESTOCKED", "DESTROYED", "REFIT_ISSUED")
RETURN_CONDITIONS = ("SELLABLE", "SOILED", "DAMAGED")
DECISIONS = ("APPROVED", "DENIED", "PENDED")


def next_seq():
    db["_seq"][0] += 1
    return db["_seq"][0]


def stamp(row):
    """Attach the standard identity/version block to a brand new row."""
    instant = now()
    row["id"] = new_id()
    row["created_at"] = instant
    row["updated_at"] = instant
    row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    row["updated_at"] = now()
    row["version"] = row.get("version", 0) + 1
    return row


def insert(collection, row):
    db[collection][row["id"]] = row
    return row


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def lookup(collection, row_id, error_id):
    if not isinstance(row_id, str):
        fail(error_id)
    row = db[collection].get(row_id)
    if row is None:
        fail(error_id)
    return row


def find_par_level(clinic_id, product_id):
    for row in db["par_levels"].values():
        if row["clinic_id"] == clinic_id and row["product_id"] == product_id:
            return row
    return None


def encounter_verifications(encounter_id):
    rows = [r for r in db["verifications"].values() if r["encounter_id"] == encounter_id]
    return sorted(rows, key=lambda r: r["verification_seq"])


def effective_verification(encounter_id):
    rows = encounter_verifications(encounter_id)
    return rows[-1] if rows else None


def encounter_prior_auth(encounter_id):
    rows = [r for r in db["prior_auths"].values() if r["encounter_id"] == encounter_id]
    return sort_created(rows)[-1] if rows else None


def encounter_notices(encounter_id):
    rows = [r for r in db["abn_notices"].values() if r["encounter_id"] == encounter_id]
    return sorted(rows, key=lambda r: r["notice_seq"])


def greatest_notice(encounter_id):
    rows = encounter_notices(encounter_id)
    return rows[-1] if rows else None


def encounter_fitting_records(encounter_id):
    rows = [r for r in db["fitting_records"].values()
            if r["encounter_id"] == encounter_id]
    return sort_created(rows)


def encounter_fab_order(encounter_id):
    rows = [r for r in db["fab_orders"].values() if r["encounter_id"] == encounter_id]
    return sort_created(rows)[-1] if rows else None


def encounter_return(encounter_id):
    rows = [r for r in db["returns"].values() if r["encounter_id"] == encounter_id]
    return sort_created(rows)[-1] if rows else None


def encounter_returns(encounter_id):
    return sort_created([r for r in db["returns"].values()
                         if r["encounter_id"] == encounter_id])


# --------------------------------------------------------------- serializers

def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_instant(row["created_at"]),
        "updated_at": fmt_instant(row["updated_at"]),
        "version": row["version"],
    }


def clinic_json(row):
    out = {
        "name": row["name"],
        "state_code": row["state_code"],
        "accreditation_body": row["accreditation_body"],
        "accreditation_expires_on": fmt_date(row["accreditation_expires_on"]),
        "ioas_supervision_level": row["ioas_supervision_level"],
        "dispensing_specialties": list(row["dispensing_specialties"]),
        "dispensing_status": row["dispensing_status"],
        "stockout_par_level_count": row["stockout_par_level_count"],
    }
    out.update(_common(row))
    return out


def physician_json(row):
    out = {
        "clinic_id": row["clinic_id"],
        "full_name": row["full_name"],
        "npi": row["npi"],
        "specialty": row["specialty"],
        "group_member": row["group_member"],
        "stark_disclosure_on_file": row["stark_disclosure_on_file"],
    }
    out.update(_common(row))
    return out


def fitter_json(row):
    out = {
        "clinic_id": row["clinic_id"],
        "full_name": row["full_name"],
        "credential": row["credential"],
        "credential_expires_on": fmt_date(row["credential_expires_on"]),
        "privilege_scope": row["privilege_scope"],
        "fitting_minutes_booked": row["fitting_minutes_booked"],
    }
    out.update(_common(row))
    return out


def supplier_json(row):
    out = {
        "name": row["name"],
        "accreditation_body": row["accreditation_body"],
        "accreditation_expires_on": fmt_date(row["accreditation_expires_on"]),
        "dmepos_standards_attested": row["dmepos_standards_attested"],
        "custom_fab_capable": row["custom_fab_capable"],
        "quality_hold": row["quality_hold"],
        "promised_turnaround_days": row["promised_turnaround_days"],
        "turnaround_score": row["turnaround_score"],
        "accepted_fab_order_count": row["accepted_fab_order_count"],
    }
    out.update(_common(row))
    return out


def product_json(row):
    out = {
        "supplier_id": row["supplier_id"],
        "hcpcs_code": row["hcpcs_code"],
        "description": row["description"],
        "category": row["category"],
        "specialty": row["specialty"],
        "same_or_similar_group": row["same_or_similar_group"],
        "reasonable_useful_lifetime_months": row["reasonable_useful_lifetime_months"],
        "allowed_amount_cents": row["allowed_amount_cents"],
        "cash_price_cents": row["cash_price_cents"],
        "unit_cost_cents": row["unit_cost_cents"],
        "requires_prior_auth": row["requires_prior_auth"],
        "ioas_supervision_required": row["ioas_supervision_required"],
    }
    out.update(_common(row))
    return out


def par_level_json(row):
    out = {
        "clinic_id": row["clinic_id"],
        "product_id": row["product_id"],
        "par_min_qty": row["par_min_qty"],
        "par_max_qty": row["par_max_qty"],
        "on_hand_qty": row["on_hand_qty"],
        "reserved_qty": row["reserved_qty"],
        "available_qty": row["on_hand_qty"] - row["reserved_qty"],
        "stock_posture": row["stock_posture"],
        "lifetime_received_qty": row["lifetime_received_qty"],
    }
    out.update(_common(row))
    return out


def patient_json(row):
    out = {
        "clinic_id": row["clinic_id"],
        "full_name": row["full_name"],
        "dob": fmt_date(row["dob"]),
        "payer_type": row["payer_type"],
        "member_id": row["member_id"],
        "medicare_beneficiary": row["medicare_beneficiary"],
    }
    out.update(_common(row))
    return out


def encounter_json(row):
    out = {
        "clinic_id": row["clinic_id"],
        "patient_id": row["patient_id"],
        "product_id": row["product_id"],
        "ordering_physician_id": row["ordering_physician_id"],
        "mn_physician_id": row["mn_physician_id"],
        "ioas_attesting_physician_id": row["ioas_attesting_physician_id"],
        "fitter_id": row["fitter_id"],
        "refit_of_encounter_id": row["refit_of_encounter_id"],
        "quantity": row["quantity"],
        "service_date": fmt_date(row["service_date"]),
        "clinical_status": row["clinical_status"],
        "financial_status": row["financial_status"],
        "compliance_hold": row["compliance_hold"],
        "hold_reason": row["hold_reason"],
        "mn_diagnosis_code": row["mn_diagnosis_code"],
        "mn_functional_deficit": row["mn_functional_deficit"],
        "mn_expected_duration_months": row["mn_expected_duration_months"],
        "mn_signed_at": fmt_instant(row["mn_signed_at"]),
        "ioas_attested_at": fmt_instant(row["ioas_attested_at"]),
        "ioas_supervision_level_observed": row["ioas_supervision_level_observed"],
        "delivered_at": fmt_instant(row["delivered_at"]),
        "delivery_signature_role": row["delivery_signature_role"],
        "covered_units": row["covered_units"],
        "patient_responsibility_cents": row["patient_responsibility_cents"],
        "billable_amount_cents": row["billable_amount_cents"],
        "responsibility_variant": row["responsibility_variant"],
    }
    out.update(_common(row))
    return out


def verification_json(row):
    return {
        "id": row["id"],
        "encounter_id": row["encounter_id"],
        "verification_seq": row["verification_seq"],
        "covered": row["covered"],
        "deductible_remaining_cents": row["deductible_remaining_cents"],
        "coinsurance_pct": row["coinsurance_pct"],
        "valid_for_days": row["valid_for_days"],
        "allowed_amount_cents_snapshot": row["allowed_amount_cents_snapshot"],
        "same_or_similar_conflict": row["same_or_similar_conflict"],
        "prior_delivered_encounter_id": row["prior_delivered_encounter_id"],
        "prior_delivered_on": fmt_date(row["prior_delivered_on"]),
        "months_since_prior_delivery": row["months_since_prior_delivery"],
        "verified_at": fmt_instant(row["verified_at"]),
        "expires_at": fmt_instant(row["expires_at"]),
        "created_at": fmt_instant(row["created_at"]),
    }


def prior_auth_json(row):
    out = {
        "encounter_id": row["encounter_id"],
        "requested_units": row["requested_units"],
        "status": row["status"],
        "approved_units": row["approved_units"],
        "auth_number": row["auth_number"],
        "appeal_round": row["appeal_round"],
        "decision_at": fmt_instant(row["decision_at"]),
        "expires_at": fmt_instant(row["expires_at"]),
    }
    out.update(_common(row))
    return out


def abn_notice_json(row):
    out = {
        "encounter_id": row["encounter_id"],
        "notice_seq": row["notice_seq"],
        "reason_non_covered": row["reason_non_covered"],
        "status": row["status"],
        "option_selected": row["option_selected"],
        "signed_by": row["signed_by"],
        "patient_signed_at": fmt_instant(row["patient_signed_at"]),
        "witness_user_id": row["witness_user_id"],
        "unit_net_price_cents": row["unit_net_price_cents"],
        "estimated_subtotal_cents": row["estimated_subtotal_cents"],
        "dispensing_fee_cents": row["dispensing_fee_cents"],
        "estimated_cost_cents": row["estimated_cost_cents"],
    }
    out.update(_common(row))
    return out


def fitting_record_json(row):
    out = {
        "encounter_id": row["encounter_id"],
        "fitter_id": row["fitter_id"],
        "fitting_start_at": fmt_instant(row["fitting_start_at"]),
        "fitting_end_at": fmt_instant(row["fitting_end_at"]),
        "fitting_minutes": row["fitting_minutes"],
        "measurement_set": row["measurement_set"],
        "fit_outcome": row["fit_outcome"],
        "delivery_signature_role": row["delivery_signature_role"],
        "delivery_signed_at": fmt_instant(row["delivery_signed_at"]),
    }
    out.update(_common(row))
    return out


def fab_order_json(row):
    out = {
        "encounter_id": row["encounter_id"],
        "supplier_id": row["supplier_id"],
        "status": row["status"],
        "submitted_at": fmt_instant(row["submitted_at"]),
        "promised_delivery_on": fmt_date(row["promised_delivery_on"]),
        "promised_turnaround_days_snapshot": row["promised_turnaround_days_snapshot"],
        "first_delivered_at": fmt_instant(row["first_delivered_at"]),
        "accepted_at": fmt_instant(row["accepted_at"]),
        "adjustment_rounds": row["adjustment_rounds"],
        "first_delivery_days": row["first_delivery_days"],
        "total_elapsed_days": row["total_elapsed_days"],
        "projected_turnaround_score": row["projected_turnaround_score"],
        "final_turnaround_score": row["final_turnaround_score"],
    }
    out.update(_common(row))
    return out


def product_return_json(row):
    out = {
        "encounter_id": row["encounter_id"],
        "reason": row["reason"],
        "return_note": row["return_note"],
        "status": row["status"],
        "quantity_returned": row["quantity_returned"],
        "condition": row["condition"],
        "days_since_delivery": row["days_since_delivery"],
        "restock_eligible": row["restock_eligible"],
        "restock_fee_pct": row["restock_fee_pct"],
        "device_component_cents": row["device_component_cents"],
        "fitting_component_cents": row["fitting_component_cents"],
        "device_refund_cents": row["device_refund_cents"],
        "fitting_refund_cents": row["fitting_refund_cents"],
        "refund_cents": row["refund_cents"],
        "restock_fee_cents": row["restock_fee_cents"],
        "inspected_at": fmt_instant(row["inspected_at"]),
        "refit_encounter_id": row["refit_encounter_id"],
    }
    out.update(_common(row))
    return out
