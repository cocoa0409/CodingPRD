"""Shared helpers: id minting, entity factory with common fields, serializers,
derived projections (item.lendable, patron.max_concurrent_loans)."""
import uuid

import db
from response import iso_z


def new_id():
    return str(uuid.uuid4())


def stamp_new(common=True):
    """Common system fields for a new entity."""
    rec = {"id": new_id()}
    if common:
        rec["created_at"] = iso_z(db.now())
        rec["updated_at"] = iso_z(db.now())
        rec["version"] = 1
    else:
        rec["created_at"] = iso_z(db.now())
    return rec


def touch(rec):
    """Bump updated_at and version on mutation (entities with common fields)."""
    rec["updated_at"] = iso_z(db.now())
    rec["version"] = rec.get("version", 1) + 1


# ---- derived projections ----

def patron_has_verified_credential(patron_id):
    return any(
        c["patron_id"] == patron_id and c["status"] == "VERIFIED"
        for c in db.credentials.values()
    )


def patron_max_loans(patron_id):
    return 50 if patron_has_verified_credential(patron_id) else 5


def item_lendable(item):
    if item["status"] != "LENDABLE":
        return False
    work = db.works.get(item["work_id"])
    if work is None or work_availability(work) != "AVAILABLE":
        return False
    lib = db.libraries.get(item["owning_library_id"])
    if lib is None or lib["status"] != "ACTIVE":
        return False
    return True


def work_availability(work):
    """Pure derivation over the work's rights requests (calc
    work_availability_recompute)."""
    rr = [
        r for r in db.rights_requests.values()
        if r["subject_kind"] == "WORK" and r.get("work_id") == work["id"]
    ]
    if any(r["status"] in ("LEGAL_HOLD", "UPHELD_REMOVED") for r in rr):
        return "WITHDRAWN"
    if any(r["status"] == "UNDER_REVIEW" for r in rr):
        return "EMBARGOED"
    return "AVAILABLE"


def grant_counters(grant_id):
    reserved = sum(
        line["budget_reservation_cents"]
        for line in db.budget_lines.values()
        if line["grant_id"] == grant_id and line["status"] == "OPEN"
    )
    spent = sum(
        line["actual_spend_cents"]
        for line in db.budget_lines.values()
        if line["grant_id"] == grant_id and line["status"] == "SETTLED"
    )
    return reserved, spent


def grant_status_from_util(grant, reserved, spent):
    util = reserved + spent
    return "EXHAUSTED" if util >= grant["amount_cents"] else "OPEN"


# ---- serializers ----

def serialize_patron(p):
    return {
        "id": p["id"],
        "email": p["email"],
        "full_name": p["full_name"],
        "status": p["status"],
        "active_loan_count": p["active_loan_count"],
        "strike_count": p["strike_count"],
        "max_concurrent_loans": patron_max_loans(p["id"]),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_credential(c):
    return {
        "id": c["id"],
        "patron_id": c["patron_id"],
        "certifier_reference": c["certifier_reference"],
        "status": c["status"],
        "decided_by": c["decided_by"],
        "decided_at": c["decided_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_library(lib):
    return {
        "id": lib["id"],
        "library_code": lib["library_code"],
        "display_name": lib["display_name"],
        "storage_commitment_years": lib["storage_commitment_years"],
        "status": lib["status"],
        "created_at": lib["created_at"],
        "updated_at": lib["updated_at"],
        "version": lib["version"],
    }


def serialize_work(w):
    return {
        "id": w["id"],
        "title": w["title"],
        "author": w["author"],
        "publication_year": w["publication_year"],
        "availability": work_availability(w),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def serialize_batch(b):
    return {
        "id": b["id"],
        "operator_code": b["operator_code"],
        "status": b["status"],
        "item_count": b["item_count"],
        "page_count": b["page_count"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_item(it):
    return {
        "id": it["id"],
        "batch_id": it["batch_id"],
        "work_id": it["work_id"],
        "owning_library_id": it["owning_library_id"],
        "page_count": it["page_count"],
        "condition_grade": it["condition_grade"],
        "status": it["status"],
        "lendable": item_lendable(it),
        "created_at": it["created_at"],
        "updated_at": it["updated_at"],
        "version": it["version"],
    }


def serialize_loan(loan):
    return {
        "id": loan["id"],
        "item_id": loan["item_id"],
        "patron_id": loan["patron_id"],
        "loan_kind": loan["loan_kind"],
        "status": loan["status"],
        "checked_out_at": loan["checked_out_at"],
        "due_at": loan["due_at"],
        "renewed": loan["renewed"],
        "created_at": loan["created_at"],
        "updated_at": loan["updated_at"],
        "version": loan["version"],
    }


def serialize_waitlist_entry(e):
    return {
        "id": e["id"],
        "work_id": e["work_id"],
        "patron_id": e["patron_id"],
        "status": e["status"],
        "offered_at": e["offered_at"],
        "offer_expires_at": e["offer_expires_at"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_crawl_job(j):
    return {
        "id": j["id"],
        "seed_url": j["seed_url"],
        "at_risk": j["at_risk"],
        "scheduled_at": j["scheduled_at"],
        "requests_per_minute": j["requests_per_minute"],
        "status": j["status"],
        "captures_produced": j["captures_produced"],
        "duplicates_skipped": j["duplicates_skipped"],
        "storage_cost_cents": j["storage_cost_cents"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
    }


def serialize_capture(c):
    # Captures have no updated_at/version (immutable; common_fields: false).
    return {
        "id": c["id"],
        "crawl_job_id": c["crawl_job_id"],
        "url": c["url"],
        "content_hash": c["content_hash"],
        "captured_at": c["captured_at"],
        "has_dynamic_content": c["has_dynamic_content"],
        "playback_status": c["playback_status"],
        "created_at": c["created_at"],
    }


def serialize_directive(d):
    return {
        "id": d["id"],
        "url_prefix": d["url_prefix"],
        "scope": d["scope"],
        "status": d["status"],
        "reason": d["reason"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_rights_request(r):
    return {
        "id": r["id"],
        "subject_kind": r["subject_kind"],
        "work_id": r.get("work_id"),
        "url_prefix": r.get("url_prefix"),
        "claimant_name": r["claimant_name"],
        "filed_by": r["filed_by"],
        "status": r["status"],
        "reviewed_by": r["reviewed_by"],
        "decided_by": r["decided_by"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_grant(g):
    return {
        "id": g["id"],
        "donor_name": g["donor_name"],
        "amount_cents": g["amount_cents"],
        "reserved_cents": g["reserved_cents"],
        "spent_cents": g["spent_cents"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def serialize_budget_line(line):
    return {
        "id": line["id"],
        "grant_id": line["grant_id"],
        "category": line["category"],
        "budget_reservation_cents": line["budget_reservation_cents"],
        "actual_spend_cents": line["actual_spend_cents"],
        "status": line["status"],
        "created_at": line["created_at"],
        "updated_at": line["updated_at"],
        "version": line["version"],
    }
