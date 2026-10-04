import store
from errors import err
from helpers import (
    new_row, touch, d_from_str, date_to_str, whole_months_between,
)
from store import clock_today_date

VALID_CATEGORIES = {
    "OFFICER_CADET", "ENLISTED_ACTIVE", "VETERAN_HONORABLE",
    "FAMILY_SPOUSE", "FAMILY_WIDOW", "FAMILY_CHILD",
}

# ---------------------------------------------------------------------------
# Matrix computation
# ---------------------------------------------------------------------------

def compute_matrix(member):
    offerings = [o for o in store.T["product_offerings"].values() if o["is_active_flag"]]
    per_offering = {}
    group_available = {"BANKING": False, "INSURANCE": False,
                       "INVESTMENT": False, "DEPLOYMENT": False}
    for o in offerings:
        base = member["eligibility_category"] in o["allowed_categories"]
        if member["status"] != "ACTIVE" and o["requires_active_status"]:
            base = False
        per_offering[o["id"]] = base
        if base:
            group_available[o["product_line"]] = True
    # DEPLOYMENT group
    if (member["deployment_posture"] == "DEPLOYED"
            and member["status"] not in ("SUSPENDED", "DECEASED", "REVOKED")):
        for o in offerings:
            if o["deployment_enhanced"] and per_offering.get(o["id"]):
                group_available["DEPLOYMENT"] = True
                break
    count = sum(1 for v in group_available.values() if v) * 6
    return {
        "available_facet_count": count,
        "groups": group_available,
        "offerings": per_offering,
    }


def matrix_response(member):
    m = member.get("product_matrix_cache") or compute_matrix(member)
    member["product_matrix_cache"] = m
    facets = {}
    for group, avail in m["groups"].items():
        facets[group] = ["AVAILABLE" if avail else "UNAVAILABLE"] * 6
    for oid, base in m["offerings"].items():
        facets[oid] = "AVAILABLE" if base else "UNAVAILABLE"
    return {
        "member_id": member["id"],
        "eligibility_category": member["eligibility_category"],
        "status": member["status"],
        "deployment_posture": member["deployment_posture"],
        "available_facet_count": m["available_facet_count"],
        "facets": facets,
    }


def recompute_member_matrix(member):
    member["product_matrix_cache"] = compute_matrix(member)


def recompute_household(household):
    """Recompute aggregate: member matrices first, then sum."""
    members = [
        m for m in store.T["members"].values()
        if m["household_id"] == household["id"] and m["status"] in ("ACTIVE", "SUSPENDED")
    ]
    for m in members:
        recompute_member_matrix(m)
    total = sum(m["product_matrix_cache"]["available_facet_count"] for m in members)
    if household["status"] != "DISSOLVED":
        household["aggregate_product_count"] = total


def recompute_all_households():
    for h in store.T["households"].values():
        if h["status"] != "DISSOLVED":
            recompute_household(h)


# ---------------------------------------------------------------------------
# Posture cascade
# ---------------------------------------------------------------------------

def release_posture_if_no_active_orders(member_id):
    member = store.T["members"][member_id]
    has_active = any(
        o["member_id"] == member_id and o["status"] == "ACTIVE"
        for o in store.T["deployment_orders"].values()
    )
    if not has_active and member["deployment_posture"] == "DEPLOYED":
        member["deployment_posture"] = "NONE"
        recompute_member_matrix(member)
        touch(member)
        if member["household_id"]:
            recompute_household(store.T["households"][member["household_id"]])


# ---------------------------------------------------------------------------
# Loss cascade
# ---------------------------------------------------------------------------

def cascade_entitlements_grandfather(member):
    for e in store.T["entitlements"].values():
        if e["member_id"] == member["id"] and e["status"] == "OPEN":
            e["status"] = "GRANDFATHERED"
            e["grandfathered"] = True
            touch(e)


def cascade_entitlements_close_member_loss(member):
    for e in store.T["entitlements"].values():
        if e["member_id"] == member["id"] and e["status"] in ("OPEN", "GRANDFATHERED"):
            e["status"] = "CLOSED"
            e["closure_reason"] = "MEMBER_LOSS"
            touch(e)


def cascade_descendants_suspend(member):
    for m in store.T["members"].values():
        if m["sponsor_member_id"] == member["id"] and m["status"] == "ACTIVE":
            m["status"] = "SUSPENDED"
            recompute_member_matrix(m)
            touch(m)
            if m["household_id"]:
                recompute_household(store.T["households"][m["household_id"]])


def member_loss_timestamp(member):
    return member.get("_loss_timestamp")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_case(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
        "applicant_legal_name": c["applicant_legal_name"],
        "applicant_dob": c["applicant_dob"],
        "basis_type": c["basis_type"],
        "sponsor_member_id": c["sponsor_member_id"],
        "claimed_relationship": c["claimed_relationship"],
        "eligibility_category": c["eligibility_category"],
        "adoption_or_divorce_flag": c["adoption_or_divorce_flag"],
        "member_id": c["member_id"],
        "verification_officer_id": c["verification_officer_id"],
        "record_reconstruction_officer_id": c["record_reconstruction_officer_id"],
        "denial_reason": c["denial_reason"],
        "decision_note": c["decision_note"],
        "status": c["status"],
    }


def ser_service_record(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
        "case_id": r["case_id"],
        "branch": r["branch"], "component": r["component"],
        "rank_grade": r["rank_grade"],
        "service_start_date": r["service_start_date"],
        "service_end_date": r["service_end_date"],
        "discharge_characterization": r["discharge_characterization"],
        "service_verified": r["service_verified"],
        "service_days": r["service_days"],
    }


def ser_evidence(d):
    return {
        "id": d["id"], "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"],
        "case_id": d["case_id"],
        "doc_type": d["doc_type"],
        "issuing_authority": d["issuing_authority"],
        "issued_on": d["issued_on"],
        "covers_service_record_id": d["covers_service_record_id"],
        "authenticity_channel": d["authenticity_channel"],
        "content_hash": d["content_hash"],
    }


def ser_member(m):
    return {
        "id": m["id"], "created_at": m["created_at"], "updated_at": m["updated_at"],
        "version": m["version"],
        "member_number": m["member_number"],
        "legal_name": m["legal_name"], "dob": m["dob"],
        "case_id": m["case_id"],
        "eligibility_category": m["eligibility_category"],
        "sponsor_member_id": m["sponsor_member_id"],
        "claimed_relationship": m["claimed_relationship"],
        "household_id": m["household_id"],
        "lineage_depth": m["lineage_depth"],
        "status": m["status"],
        "deployment_posture": m["deployment_posture"],
        "product_matrix_cache": matrix_response(m),
    }


def ser_household(h):
    if h["status"] != "DISSOLVED":
        recompute_household(h)
    return {
        "id": h["id"], "created_at": h["created_at"], "updated_at": h["updated_at"],
        "version": h["version"],
        "household_name": h["household_name"],
        "primary_member_id": h["primary_member_id"],
        "aggregate_product_count": h["aggregate_product_count"],
        "status": h["status"],
    }


def ser_address(a):
    return {
        "id": a["id"], "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
        "member_id": a["member_id"],
        "addr_type": a["addr_type"],
        "line1": a["line1"], "city": a["city"],
        "region_code": a["region_code"], "postal_code": a["postal_code"],
        "country_code": a["country_code"],
        "effective_from": a["effective_from"],
        "effective_to": a["effective_to"],
        "is_duty_station": a["is_duty_station"],
    }


def ser_order(o):
    return {
        "id": o["id"], "created_at": o["created_at"], "updated_at": o["updated_at"],
        "version": o["version"],
        "member_id": o["member_id"],
        "orders_number": o["orders_number"],
        "theater": o["theater"],
        "start_date": o["start_date"],
        "end_date": o["end_date"],
        "scra_eligible": o["scra_eligible"],
        "status": o["status"],
    }


def ser_claim(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
        "member_id": c["member_id"],
        "deployment_order_id": c["deployment_order_id"],
        "claim_type": c["claim_type"],
        "obligation_label": c["obligation_label"],
        "base_rate_bps": c["base_rate_bps"],
        "monthly_interest_cents": c["monthly_interest_cents"],
        "periods_granted": c["periods_granted"],
        "total_relief_cents": c["total_relief_cents"],
        "approval_effective_date": c["approval_effective_date"],
        "approved_by_officer_id": c["approved_by_officer_id"],
        "status": c["status"],
    }


def ser_offering(o):
    return {
        "id": o["id"], "created_at": o["created_at"], "updated_at": o["updated_at"],
        "version": o["version"],
        "product_code": o["product_code"],
        "product_line": o["product_line"],
        "product_name": o["product_name"],
        "allowed_categories": list(o["allowed_categories"]),
        "requires_active_status": o["requires_active_status"],
        "deployment_enhanced": o["deployment_enhanced"],
        "is_active_flag": o["is_active_flag"],
    }


def ser_entitlement(e):
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"],
        "member_id": e["member_id"],
        "product_offering_id": e["product_offering_id"],
        "opened_at": e["opened_at"],
        "closure_reason": e["closure_reason"],
        "grandfathered": e["grandfathered"],
        "exposure_cents": e["exposure_cents"],
        "status": e["status"],
    }


def ser_survivor(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
        "member_id": s["member_id"],
        "beneficiary_member_id": s["beneficiary_member_id"],
        "continuance_months": s["continuance_months"],
        "continuance_amount_cents": s["continuance_amount_cents"],
        "transfer_household_id": s["transfer_household_id"],
        "resolution_note": s["resolution_note"],
        "status": s["status"],
    }
