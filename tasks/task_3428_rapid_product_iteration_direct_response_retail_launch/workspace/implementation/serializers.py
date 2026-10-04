"""Entity serializers. Computed fields (research_momentum, allocated_units) are
evaluated against the current logical clock at read time; Decimal fields are
emitted as JSON numbers via float()."""

from services import allocated_units
from state import now
from util import fmt_iso, momentum_score


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def _num(x):
    return float(x) if x is not None else None


def ser_season(s):
    d = _common(s)
    d.update({
        "season_code": s["season_code"],
        "posture": s["posture"],
        "review_index": s["review_index"],
        "frozen_at_review_index": s["frozen_at_review_index"],
        "guarded_since_review_index": s["guarded_since_review_index"],
        "last_review_at": s["last_review_at"],
        "penalty_accrual_cents": s["penalty_accrual_cents"],
    })
    return d


def ser_category(c):
    d = _common(c)
    d.update({
        "season_id": c["season_id"],
        "name": c["name"],
        "crowding_base": c["crowding_base"],
        "exposure_index": c["exposure_index"],
        "exposure_level": c["exposure_level"],
        "active_reserve_cents": c["active_reserve_cents"],
    })
    return d


def ser_concept(c):
    d = _common(c)
    d.update({
        "category_id": c["category_id"],
        "title": c["title"],
        "status": c["status"],
        "research_insights": [
            {"points": i["points"], "observed_at": fmt_iso(i["observed_dt"])}
            for i in c["research_insights"]
        ],
        # momentum is re-evaluated against the current logical clock on every read
        "research_momentum": float(momentum_score(c["research_insights"], now())),
        "rounds_used": c["rounds_used"],
        "killed_reason": c["killed_reason"],
    })
    return d


def ser_round(r):
    d = _common(r)
    d.update({
        "concept_id": r["concept_id"],
        "round_number": r["round_number"],
        "status": r["status"],
        "opened_at": r["opened_at"],
        "score": r["score"],
        "feedback": r["feedback"],
    })
    return d


def ser_partner(p):
    d = _common(p)
    d.update({
        "name": p["name"],
        "capacity_units_total": p["capacity_units_total"],
        "allocated_units": allocated_units(p["id"]),
        "status": p["status"],
    })
    return d


def ser_variant(v):
    d = _common(v)
    d.update({
        "concept_id": v["concept_id"],
        "factory_partner_id": v["factory_partner_id"],
        "model_number": v["model_number"],
        "channel": v["channel"],
        "lifecycle": v["lifecycle"],
        "claim_clearance": v["claim_clearance"],
        "tooled_at": v["tooled_at"],
        "retail_live_at": v["retail_live_at"],
        "refresh_candidate_at": v["refresh_candidate_at"],
        "retired_at": v["retired_at"],
    })
    return d


def ser_study(s):
    d = _common(s)
    d.update({
        "variant_id": s["variant_id"],
        "claim_text": s["claim_text"],
        "conducted_by_user_id": s["conducted_by_user_id"],
        "status": s["status"],
        "our_metric": s["our_metric"],
        "baseline_metric": s["baseline_metric"],
        "sample_size": s["sample_size"],
        "margin": _num(s["margin"]),
        "substantiated_by_user_id": s["substantiated_by_user_id"],
        "challenge_reason": s["challenge_reason"],
    })
    return d


def ser_media(m):
    d = _common(m)
    d.update({
        "variant_id": m["variant_id"],
        "title": m["title"],
        "media_spend_cents": m["media_spend_cents"],
        "status": m["status"],
        "projected_gross_cents": m["projected_gross_cents"],
        "provisional_mer": _num(m["provisional_mer"]),
        "order_lines": m["order_lines"],
        "settled_mer": _num(m["settled_mer"]),
        "aired_at": m["aired_at"],
        "decided_at": m["decided_at"],
    })
    return d


def ser_agreement(a):
    d = _common(a)
    d.update({
        "category_id": a["category_id"],
        "retailer_name": a["retailer_name"],
        "exclusive": a["exclusive"],
        "window_start": a["window_start"],
        "window_end": a["window_end"],
        "min_launch_units": a["min_launch_units"],
        "status": a["status"],
        "signed_at": a["signed_at"],
    })
    return d


def ser_commitment(c):
    d = _common(c)
    d.update({
        "agreement_id": c["agreement_id"],
        "variant_id": c["variant_id"],
        "committed_units": c["committed_units"],
        "need_by_date": c["need_by_date"],
        "status": c["status"],
        "penalty_cents": c["penalty_cents"],
    })
    return d


def ser_replenishment(r):
    d = _common(r)
    d.update({
        "variant_id": r["variant_id"],
        "weekly_velocity": r["weekly_velocity"],
        "on_hand_units": r["on_hand_units"],
        "in_transit_units": r["in_transit_units"],
        "case_pack_units": r["case_pack_units"],
        "quantity_units": r["quantity_units"],
        "status": r["status"],
        "superseded_by_id": r["superseded_by_id"],
    })
    return d


def ser_case(c):
    d = _common(c)
    d.update({
        "category_id": c["category_id"],
        "case_number": c["case_number"],
        "claim_cents": c["claim_cents"],
        "severity": c["severity"],
        "filed_by_user_id": c["filed_by_user_id"],
        "status": c["status"],
        "provisional_reserve_cents": c["provisional_reserve_cents"],
        "final_amount_cents": c["final_amount_cents"],
    })
    return d
