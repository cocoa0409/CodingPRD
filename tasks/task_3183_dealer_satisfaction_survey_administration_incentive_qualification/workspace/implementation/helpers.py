"""Shared helpers: ID/timestamp generation, entity serialization."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import clock


def num(v):
    """Convert a Decimal to a JSON-safe number; pass through None and ints."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return v


def new_id():
    return str(uuid.uuid4())


def wall_now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def base_fields(record, skip_version=False):
    out = {"id": record["id"], "created_at": record["created_at"]}
    if not skip_version:
        out["updated_at"] = record["updated_at"]
        out["version"] = record["version"]
    return out


def make_record(common=True):
    now = wall_now_iso()
    rec = {"id": new_id(), "created_at": now}
    if common:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = wall_now_iso()
    rec["version"] += 1


# ---- Serializers ----


def ser_region(r):
    out = base_fields(r)
    out.update({"code": r["code"], "name": r["name"]})
    return out


def ser_dealer(d):
    out = base_fields(d)
    out.update(
        {
            "region_id": d["region_id"],
            "name": d["name"],
            "dealer_code": d["dealer_code"],
            "posture": d["posture"],
            "current_score_adjusted": num(d["current_score_adjusted"]),
            "current_response_rate": num(d["current_response_rate"]),
            "confirmed_flag_count": d["confirmed_flag_count"],
        }
    )
    return out


def ser_department(d):
    out = base_fields(d)
    out.update({"dealer_id": d["dealer_id"], "kind": d["kind"], "name": d["name"]})
    return out


def ser_advisor(a):
    out = base_fields(a)
    out.update(
        {
            "department_id": a["department_id"],
            "name": a["name"],
            "employee_ref": a["employee_ref"],
        }
    )
    return out


def ser_customer(c):
    out = base_fields(c)
    out.update(
        {
            "full_name": c["full_name"],
            "email": c["email"],
            "phone": c["phone"],
            "do_not_contact": c["do_not_contact"],
        }
    )
    return out


def ser_question_set(q):
    out = base_fields(q)
    out.update(
        {
            "code": q["code"],
            "questions": q["questions"],
            "comparability_factor": q["comparability_factor"],
            "status": q["status"],
        }
    )
    return out


def ser_wave(w):
    out = base_fields(w)
    out.update(
        {
            "period_start": clock.iso(w["period_start"]),
            "period_end": clock.iso(w["period_end"]),
            "question_set_id": w["question_set_id"],
            "status": w["status"],
            "closed_at": clock.iso(w["closed_at"]) if w["closed_at"] else None,
            "invitations_total": w["invitations_total"],
            "queued_count": w["queued_count"],
            "sent_count": w["sent_count"],
            "responded_count": w["responded_count"],
            "expired_count": w["expired_count"],
            "opted_out_count": w["opted_out_count"],
            "suppressed_count": w["suppressed_count"],
        }
    )
    return out


def ser_transaction(t):
    # Transaction is immutable: id + created_at only, no updated_at/version.
    out = base_fields(t, skip_version=True)
    out.update(
        {
            "dealer_id": t["dealer_id"],
            "department_id": t["department_id"],
            "advisor_id": t["advisor_id"],
            "customer_id": t["customer_id"],
            "kind": t["kind"],
            "completed_at": clock.iso(t["completed_at"]),
            "margin_cents": t["margin_cents"],
        }
    )
    return out


def ser_invitation(i):
    out = base_fields(i)
    out.update(
        {
            "transaction_id": i["transaction_id"],
            "customer_id": i["customer_id"],
            "wave_id": i["wave_id"],
            "question_set_id": i["question_set_id"],
            "status": i["status"],
            "sent_at": clock.iso(i["sent_at"]) if i["sent_at"] else None,
            "window_closes_at": clock.iso(i["window_closes_at"])
            if i["window_closes_at"]
            else None,
        }
    )
    return out


def ser_response(r):
    out = base_fields(r)
    out.update(
        {
            "invitation_id": r["invitation_id"],
            "answers": r["answers"],
            "score": num(r["score"]),
            "status": r["status"],
            "excluded_reason": r["excluded_reason"],
            "submitted_at": clock.iso(r["submitted_at"]),
        }
    )
    return out


def ser_appeal(a):
    out = base_fields(a)
    out.update(
        {
            "response_id": a["response_id"],
            "dealer_id": a["dealer_id"],
            "reason": a["reason"],
            "status": a["status"],
            "decision_rationale": a["decision_rationale"],
            "prior_response_status": a["prior_response_status"],
        }
    )
    return out


def ser_flag(f):
    out = base_fields(f)
    out.update(
        {
            "dealer_id": f["dealer_id"],
            "response_id": f["response_id"],
            "kind": f["kind"],
            "evidence": f["evidence"],
            "status": f["status"],
        }
    )
    return out


def ser_statement(s):
    out = base_fields(s)
    out.update(
        {
            "dealer_id": s["dealer_id"],
            "wave_id": s["wave_id"],
            "status": s["status"],
            "supersedes_id": s["supersedes_id"],
            "score_used": num(s["score_used"]),
            "response_rate_used": num(s["response_rate_used"]),
            "tier": s["tier"],
            "eligible_margin_cents": s["eligible_margin_cents"],
            "payout_cents": s["payout_cents"],
        }
    )
    return out


def ser_action_plan(p):
    out = base_fields(p)
    out.update(
        {
            "dealer_id": p["dealer_id"],
            "wave_id": p["wave_id"],
            "title": p["title"],
            "items": p["items"],
            "due_date": clock.iso(p["due_date"]),
            "status": p["status"],
            "review_note": p["review_note"],
        }
    )
    return out
