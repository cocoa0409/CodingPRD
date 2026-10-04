"""Serializers: convert stored records to API payloads with derived fields."""
import store


def hospital_view(h):
    return {
        "id": h["id"],
        "name": h["name"],
        "city": h["city"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def house_derived(house_id):
    """Compute occupied/reserved/available counts and posture for a house."""
    rooms = [r for r in store.db["rooms"].values() if r["house_id"] == house_id]
    occupied = sum(1 for r in rooms if r["occupied"])
    reserved_ids = {
        req["offered_room_id"]
        for req in store.db["stay_requests"].values()
        if req["assignment_status"] == "OFFERED" and req["offered_room_id"]
    }
    reserved = sum(1 for r in rooms if r["id"] in reserved_ids)
    available = sum(
        1
        for r in rooms
        if r["status"] == "AVAILABLE" and not r["occupied"] and r["id"] not in reserved_ids
    )
    denominator = sum(1 for r in rooms if r["status"] == "AVAILABLE")
    if denominator == 0:
        posture = "FULL"
    else:
        ratio = occupied / denominator
        if ratio == 1.0:
            posture = "FULL"
        elif ratio >= 0.9:
            posture = "NEAR_CAPACITY"
        else:
            posture = "OPEN"
    return occupied, reserved, available, posture


def house_view(h):
    occupied, reserved, available, posture = house_derived(h["id"])
    return {
        "id": h["id"],
        "name": h["name"],
        "city": h["city"],
        "associated_hospital_id": h["associated_hospital_id"],
        "posture": posture,
        "occupied_room_count": occupied,
        "available_room_count": available,
        "reserved_room_count": reserved,
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def room_view(r):
    return {
        "id": r["id"],
        "house_id": r["house_id"],
        "room_number": r["room_number"],
        "bed_count": r["bed_count"],
        "occupancy_limit": r["occupancy_limit"],
        "status": r["status"],
        "occupied": r["occupied"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def family_view(f):
    return {
        "id": f["id"],
        "family_name": f["family_name"],
        "primary_contact_name": f["primary_contact_name"],
        "home_city": f["home_city"],
        "distance_miles": f["distance_miles"],
        "child_patient_name": f["child_patient_name"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def referral_view(r):
    return {
        "id": r["id"],
        "family_id": r["family_id"],
        "hospital_id": r["hospital_id"],
        "treating_unit": r["treating_unit"],
        "care_type": r["care_type"],
        "acuity_level": r["acuity_level"],
        "attending_clinician": r["attending_clinician"],
        "status": r["status"],
        "created_by_user_id": r["created_by_user_id"],
        "verified_by_user_id": r["verified_by_user_id"],
        "verified_at": r["verified_at"],
        "valid_until": r["valid_until"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def stay_request_view(req):
    return {
        "id": req["id"],
        "family_id": req["family_id"],
        "house_id": req["house_id"],
        "referral_id": req["referral_id"],
        "expected_nights": req["expected_nights"],
        "self_reported_acuity": req["self_reported_acuity"],
        "verification_status": req["verification_status"],
        "assignment_status": req["assignment_status"],
        "provisional_score": req["provisional_score"],
        "verified_score": req["verified_score"],
        "offered_room_id": req["offered_room_id"],
        "offer_expires_at": req["offer_expires_at"],
        "waitlisted_since": req["waitlisted_since"],
        "superseded_by_request_id": req["superseded_by_request_id"],
        "created_at": req["created_at"],
        "updated_at": req["updated_at"],
        "version": req["version"],
    }


def stay_view(s):
    return {
        "id": s["id"],
        "stay_request_id": s["stay_request_id"],
        "family_id": s["family_id"],
        "room_id": s["room_id"],
        "check_in_date": s["check_in_date"],
        "expected_check_out_date": s["expected_check_out_date"],
        "actual_check_out_date": s["actual_check_out_date"],
        "status": s["status"],
        "approved_extension_count": s["approved_extension_count"],
        "pending_extension_nights": s["pending_extension_nights"],
        "transition_plan_notes": s["transition_plan_notes"],
        "review_reason": s["review_reason"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def guest_view(g):
    return {
        "id": g["id"],
        "stay_id": g["stay_id"],
        "guest_name": g["guest_name"],
        "relationship": g["relationship"],
        "is_overnight": g["is_overnight"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def screening_view(sc):
    # IllnessScreening is immutable: id + created_at only (no updated_at/version).
    return {
        "id": sc["id"],
        "stay_id": sc["stay_id"],
        "temperature_tenths_c": sc["temperature_tenths_c"],
        "symptom_count": sc["symptom_count"],
        "notes": sc["notes"],
        "result": sc["result"],
        "screened_at": sc["screened_at"],
        "created_at": sc["created_at"],
    }


def contribution_view(c):
    return {
        "id": c["id"],
        "stay_id": c["stay_id"],
        "nightly_rate_cents": c["nightly_rate_cents"],
        "planned_nights": c["planned_nights"],
        "hardship_tier": c["hardship_tier"],
        "per_night_cents": c["per_night_cents"],
        "requested_amount_cents": c["requested_amount_cents"],
        "settled_amount_cents": c["settled_amount_cents"],
        "paid_cents": c["paid_cents"],
        "waived_cents": c["waived_cents"],
        "forgiven_cents": c["forgiven_cents"],
        "outstanding_cents": c["outstanding_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def volunteer_group_view(g):
    cert_until = g["certified_until"]
    if cert_until is None:
        cert_status = "UNCERTIFIED"
    elif cert_until >= store.today().isoformat():
        cert_status = "CERTIFIED"
    else:
        cert_status = "EXPIRED"
    return {
        "id": g["id"],
        "group_name": g["group_name"],
        "contact_email": g["contact_email"],
        "certified_until": cert_until,
        "certification_status": cert_status,
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def meal_shift_view(m):
    return {
        "id": m["id"],
        "house_id": m["house_id"],
        "shift_date": m["shift_date"],
        "meal_type": m["meal_type"],
        "servings_planned": m["servings_planned"],
        "status": m["status"],
        "claimed_by_group_id": m["claimed_by_group_id"],
        "servings_served": m["servings_served"],
        "food_safety_attested": m["food_safety_attested"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def care_space_view(cs):
    return {
        "id": cs["id"],
        "hospital_id": cs["hospital_id"],
        "space_name": cs["space_name"],
        "space_type": cs["space_type"],
        "capacity": cs["capacity"],
        "created_at": cs["created_at"],
        "updated_at": cs["updated_at"],
        "version": cs["version"],
    }


def booking_view(b):
    return {
        "id": b["id"],
        "care_space_id": b["care_space_id"],
        "family_id": b["family_id"],
        "start_at": b["start_at"],
        "end_at": b["end_at"],
        "party_size": b["party_size"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def donation_view(d):
    return {
        "id": d["id"],
        "house_id": d["house_id"],
        "donor_name": d["donor_name"],
        "supply_category": d["supply_category"],
        "quantity_received": d["quantity_received"],
        "quantity_distributed": d["quantity_distributed"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }
