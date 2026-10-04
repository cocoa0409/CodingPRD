"""Flat JSON projection of every stored row.

Rows are stored with their identifiers and timestamps as objects; endpoints
serialize through these helpers so the wire shape is the declared field set.
"""

import db


def _base(row):
    out = {"id": row["id"], "created_at": db.iso(row["created_at"]),
           "updated_at": db.iso(row["updated_at"])}
    return out


def _with_version(row):
    out = _base(row)
    out["version"] = row["version"]
    return out


def store(row):
    out = _with_version(row)
    out.update({
        "store_code": row["store_code"],
        "city": row["city"],
        "state_code": row["state_code"],
        "service_bay_count": row["service_bay_count"],
        "hospital_capacity": row["hospital_capacity"],
        "hospital_occupancy": row["hospital_occupancy"],
        "hospital_posture": row["hospital_posture"],
        "pharmacy_hold_until": db.iso(row["pharmacy_hold_until"]),
        "cross_sell_credit_balance_cents": row["cross_sell_credit_balance_cents"],
        "incident_risk_index": row["incident_risk_index"],
        "restricted_training_slots_pending": row["restricted_training_slots_pending"],
        "frozen_vaccination_clinics": row["frozen_vaccination_clinics"],
        "stores_held_total": row["stores_held_total"],
    })
    return out


def member(row):
    out = _with_version(row)
    out.update({
        "full_name": row["full_name"],
        "email": row["email"],
        "state_code": row["state_code"],
        "home_store_id": row["home_store_id"],
        "outstanding_balance_cents": row["outstanding_balance_cents"],
        "status": row["status"],
    })
    return out


def pet(row):
    out = _with_version(row)
    out.update({
        "member_id": row["member_id"],
        "name": row["name"],
        "species": row["species"],
        "breed": row["breed"],
        "weight_kg": row["weight_kg"],
        "rabies_vaccination_expires_at": db.iso(row["rabies_vaccination_expires_at"]),
        "risk_score": row["risk_score"],
        "status": row["status"],
    })
    return out


def breed_rule(row):
    """Reference configuration: id and created_at only (no updated_at, no version)."""
    return {"id": row["id"], "created_at": db.iso(row["created_at"]),
            "breed": row["breed"], "species": row["species"],
            "risk_points": row["risk_points"],
            "handling_tier": row["handling_tier"],
            "allowed_for_grooming": row["allowed_for_grooming"]}


def bay(row):
    out = _with_version(row)
    out.update({
        "store_id": row["store_id"],
        "bay_code": row["bay_code"],
        "is_frozen": row["is_frozen"],
        "status": row["status"],
    })
    return out


def booking(row):
    out = _with_version(row)
    out.update({
        "store_id": row["store_id"],
        "bay_id": row["bay_id"],
        "pet_id": row["pet_id"],
        "service_type": row["service_type"],
        "starts_at": db.iso(row["starts_at"]),
        "ends_at": db.iso(row["ends_at"]),
        "screening_score": row["screening_score"],
        "pet_version": row["pet_version"],
        "handling_level": row["handling_level"],
        "screening_valid_until": db.iso(row["screening_valid_until"]),
        "re_screen_required": row["re_screen_required"],
        "status": row["status"],
    })
    return out


def screening(row):
    """Immutable audit record: id and created_at only."""
    return {"id": row["id"], "created_at": db.iso(row["created_at"]),
            "booking_id": row["booking_id"],
            "risk_total": row["risk_total"],
            "health_condition_points": row["health_condition_points"],
            "handling_level": row["handling_level"],
            "aggression_acknowledged": row["aggression_acknowledged"],
            "recorded_at": db.iso(row["recorded_at"]),
            "valid_until": db.iso(row["valid_until"])}


def encounter(row, retail=False):
    out = _with_version(row)
    out.update({
        "pet_id": row["pet_id"],
        "store_id": row["store_id"],
        "booking_id": row["booking_id"],
        "clinician_name": row["clinician_name"],
        "scheduled_at": db.iso(row["scheduled_at"]),
        "chief_complaint": row["chief_complaint"],
        "exam_date": db.iso(row["exam_date"]),
        # 2.10: the retail projection never surfaces clinical notes.
        "medical_notes": None if retail else row["medical_notes"],
        "charge_total_cents": row["charge_total_cents"],
        "status": row["status"],
    })
    return out


def clinic(row):
    out = _with_version(row)
    out.update({
        "store_id": row["store_id"],
        "clinic_date": db.iso(row["clinic_date"]),
        "open_time": db.iso(row["open_time"]),
        "close_time": db.iso(row["close_time"]),
        "coverage_required": row["coverage_required"],
        "coverage_provider": row["coverage_provider"],
        "clinic_status": row["clinic_status"],
    })
    return out


def visit(row):
    out = _base(row)
    out["version"] = row["version"]
    out.update({
        "clinic_id": row["clinic_id"],
        "pet_id": row["pet_id"],
        "store_id": row["store_id"],
        "walk_in_at": db.iso(row["walk_in_at"]),
        "vaccine_type": row["vaccine_type"],
        "prior_rabies_vaccination_date": db.iso(row["prior_rabies_vaccination_date"]),
        "prior_effective_days": row["prior_effective_days"],
        "prior_is_booster": row["prior_is_booster"],
        "new_effective_days": row["new_effective_days"],
        "certificate_serial": row["certificate_serial"],
        "certificate_issued_at": db.iso(row["certificate_issued_at"]),
        "certificate_expires_at": db.iso(row["certificate_expires_at"]),
        "state_report_status": row["state_report_status"],
        "state_report_due_at": db.iso(row["state_report_due_at"]),
        "status": row["status"],
    })
    return out


def certificate(row):
    """Immutable historical document: id and created_at only."""
    return {"id": row["id"], "created_at": db.iso(row["created_at"]),
            "visit_id": row["visit_id"], "pet_id": row["pet_id"],
            "store_id": row["store_id"], "serial": row["serial"],
            "issued_at": db.iso(row["issued_at"]),
            "expires_at": db.iso(row["expires_at"]),
            "effective_days": row["effective_days"],
            "is_booster": row["is_booster"],
            "is_effective": row["is_effective"]}


def authorization(row):
    out = _with_version(row)
    out.update({
        "pet_id": row["pet_id"],
        "encounter_id": row["encounter_id"],
        "store_id": row["store_id"],
        "item_type": row["item_type"],
        "item_name": row["item_name"],
        "sku": row["sku"],
        "unit_price_cents": row["unit_price_cents"],
        "quantity": row["quantity"],
        "authorized_at": db.iso(row["authorized_at"]),
        "expires_at": db.iso(row["expires_at"]),
        "price_at_authorization_cents": row["price_at_authorization_cents"],
        "retail_facing": row["retail_facing"],
        "status": row["status"],
    })
    return out


def pharmacy_order(row):
    out = _with_version(row)
    out.update({
        "authorization_id": row["authorization_id"],
        "store_id": row["store_id"],
        "requested_quantity": row["requested_quantity"],
        "on_hold": row["on_hold"],
        "status": row["status"],
        "current_retail_price_cents": row["current_retail_price_cents"],
    })
    return out


def incident(row):
    out = _with_version(row)
    out.update({
        "store_id": row["store_id"],
        "booking_id": row["booking_id"],
        "pet_id": row["pet_id"],
        "severity": row["severity"],
        "incident_type": row["incident_type"],
        "risk_points": row["risk_points"],
        "claim_amount_cents": row["claim_amount_cents"],
        "payout_amount_cents": row["payout_amount_cents"],
        "risk_points_lost": row["risk_points_lost"],
        "available_claimable_cents": row["available_claimable_cents"],
        "override_reason": row["override_reason"],
        "claim_status": row["claim_status"],
    })
    return out


def cross_sell(row):
    out = _with_version(row)
    out.update({
        "store_id": row["store_id"],
        "authorization_id": row["authorization_id"],
        "pet_id": row["pet_id"],
        "sku": row["sku"],
        "gross_cents": row["gross_cents"],
        "credit_granted_cents": row["credit_granted_cents"],
        "credit_redeemed_cents": row["credit_redeemed_cents"],
        "status": row["status"],
    })
    return out


def package(row):
    out = _with_version(row)
    out.update({
        "member_id": row["member_id"],
        "member_state_code": row["member_state_code"],
        "tier": row["tier"],
        "state_sales_tax_rate": row["state_sales_tax_rate"],
        "monthly_fee_cents": row["monthly_fee_cents"],
        "monthly_total_cents": row["monthly_total_cents"],
        "total_price_cents": row["total_price_cents"],
        "billing_cycle_count": row["billing_cycle_count"],
        "grooming_visits_included": row["grooming_visits_included"],
        "vet_visits_included": row["vet_visits_included"],
        "vaccine_visits_included": row["vaccine_visits_included"],
        "included_visits_total": row["included_visits_total"],
        "consumed_visits": row["consumed_visits"],
        "cycles_consumed": row["cycles_consumed"],
        "overage_visits": row["overage_visits"],
        "status": row["status"],
    })
    return out


def cycle(row):
    out = _with_version(row)
    out.update({
        "package_id": row["package_id"],
        "cycle_index": row["cycle_index"],
        "cycle_total_cents": row["cycle_total_cents"],
        "overage_credit_cents": row["overage_credit_cents"],
        "tax_cents": row["tax_cents"],
        "status": row["status"],
    })
    return out


def enrollment(row):
    out = _with_version(row)
    out.update({
        "package_id": row["package_id"],
        "store_id": row["store_id"],
        "pet_id": row["pet_id"],
        "class_code": row["class_code"],
        "courses_required": row["courses_required"],
        "courses_completed": row["courses_completed"],
        "courses_needed": row["courses_needed"],
        "status": row["status"],
    })
    return out


# --- derived / computed reads ------------------------------------------------

def pet_finalized(pet_row):
    """§3.7 finalized on-read rabies reconciliation."""
    data = pet(pet_row)
    data["rabies_vaccination_expires_at"] = db.iso(live_rabies_expiry(pet_row))
    return data


def live_rabies_expiry(pet_row):
    candidates = [c for c in db.rows("certificates")
                  if c["pet_id"] == pet_row["id"] and c["is_effective"]
                  and c["expires_at"] >= db.now()]
    if not candidates:
        return None
    return max(c["expires_at"] for c in candidates)