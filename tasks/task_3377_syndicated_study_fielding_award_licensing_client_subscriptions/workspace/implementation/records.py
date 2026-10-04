"""Record construction, mutation stamping, and serializers.

Common fields (PRD 2.4): id (UUID, no prefix), created_at, updated_at (ISO
8601 UTC, three fractional digits), version starting at 1 and incremented on
every mutation. Factor records carry only id and created_at.
"""
from db import clock, store
from timeutil import iso, iso3, new_id


def new_record(common=True):
    now = clock.now()
    rec = {"id": new_id(), "_seq": store.next_seq(), "created_at": now}
    if common:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 0) + 1


def _common(rec):
    return {
        "created_at": iso3(rec["created_at"]),
        "updated_at": iso3(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_study(s):
    out = {
        "id": s["id"],
        "code": s["code"],
        "name": s["name"],
        "industry_code": s["industry_code"],
        "cycle_year": s["cycle_year"],
        "prior_study_id": s["prior_study_id"],
        "min_sample_per_brand": s["min_sample_per_brand"],
        "significance_alpha": s["significance_alpha"],
        "embargo_lift_at": iso(s["embargo_lift_at"]),
        "status": s["status"],
        "active_methodology_id": s["active_methodology_id"],
        "published_at": iso(s["published_at"]),
    }
    out.update(_common(s))
    return out


def ser_methodology(m):
    out = {
        "id": m["id"],
        "study_id": m["study_id"],
        "change_class": m["change_class"],
        "change_notes": m["change_notes"],
        "min_duration_seconds": m["min_duration_seconds"],
        "straightline_min_items": m["straightline_min_items"],
        "pooled_sd_1000": m["pooled_sd_1000"],
        "z_value": m["z_value"],
        "tie_epsilon": m["tie_epsilon"],
        "version_no": m["version_no"],
        "status": m["status"],
        "pinned_by_user_id": m["pinned_by_user_id"],
    }
    out.update(_common(m))
    return out


def ser_factor(f):
    return {
        "id": f["id"],
        "methodology_version_id": f["methodology_version_id"],
        "code": f["code"],
        "name": f["name"],
        "weight_bp": f["weight_bp"],
        "ordinal": f["ordinal"],
        "created_at": iso3(f["created_at"]),
    }


def ser_frame(f):
    out = {
        "id": f["id"],
        "study_id": f["study_id"],
        "brand_id": f["brand_id"],
        "source_type": f["source_type"],
        "target_completes": f["target_completes"],
        "status": f["status"],
    }
    out.update(_common(f))
    return out


def ser_response(r):
    out = {
        "id": r["id"],
        "frame_id": r["frame_id"],
        "respondent_token": r["respondent_token"],
        "duration_seconds": r["duration_seconds"],
        "item_count": r["item_count"],
        "distinct_values": r["distinct_values"],
        "factor_scores": r["factor_scores"],
        "study_id": r["study_id"],
        "brand_id": r["brand_id"],
        "submitted_at": iso(r["submitted_at"]),
        "quality_status": r["quality_status"],
        "reject_reason": r["reject_reason"],
    }
    out.update(_common(r))
    return out


def ser_brand_result(b):
    out = {
        "id": b["id"],
        "study_id": b["study_id"],
        "brand_id": b["brand_id"],
        "provisional_accepted_n": b["provisional_accepted_n"],
        "accepted_n": b["accepted_n"],
        "provisional_index": b["provisional_index"],
        "final_index": b["final_index"],
        "eligible": b["eligible"],
        "significance_group": b["significance_group"],
        "rank_position": b["rank_position"],
        "status": b["status"],
    }
    out.update(_common(b))
    return out


def ser_award(a):
    out = {
        "id": a["id"],
        "study_id": a["study_id"],
        "brand_id": a["brand_id"],
        "rank_position": a["rank_position"],
        "significance_group": a["significance_group"],
        "status": a["status"],
        "published_at": iso(a["published_at"]),
    }
    out.update(_common(a))
    return out


def ser_license(l):
    out = {
        "id": l["id"],
        "award_id": l["award_id"],
        "client_id": l["client_id"],
        "tier": l["tier"],
        "term_months": l["term_months"],
        "markets_count": l["markets_count"],
        "fee_quote_cents": l["fee_quote_cents"],
        "fee_final_cents": l["fee_final_cents"],
        "status": l["status"],
        "activated_at": iso(l["activated_at"]),
        "expires_at": iso(l["expires_at"]),
        "suspension_count": l["suspension_count"],
    }
    out.update(_common(l))
    return out


def ser_audit(a):
    out = {
        "id": a["id"],
        "license_id": a["license_id"],
        "severity": a["severity"],
        "note": a["note"],
        "status": a["status"],
        "resolution": a["resolution"],
    }
    out.update(_common(a))
    return out


def ser_client(c):
    out = {
        "id": c["id"],
        "name": c["name"],
        "client_type": c["client_type"],
        "country": c["country"],
        "brand_id": c["brand_id"],
    }
    out.update(_common(c))
    return out


def ser_brand(b):
    out = {
        "id": b["id"],
        "name": b["name"],
        "industry_code": b["industry_code"],
    }
    out.update(_common(b))
    return out


def ser_subscription(s):
    out = {
        "id": s["id"],
        "client_id": s["client_id"],
        "study_id": s["study_id"],
        "tier": s["tier"],
        "starts_at": iso(s["starts_at"]),
        "ends_at": iso(s["ends_at"]),
        "status": s["status"],
    }
    out.update(_common(s))
    return out
