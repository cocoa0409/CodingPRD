"""Entity serializers: common fields use 3-fractional-digit ISO (PRD 2.5);
logical-clock-derived domain timestamps use the clock's whole-second form
(PRD 2.4)."""
from db import fmt_clock, fmt_dt


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def wood_batch(b):
    d = _common(b)
    d.update({
        "species": b["species"],
        "moisture_content_pct": b["moisture_content_pct"],
        "status": b["status"],
        "drying_started_at": fmt_clock(b["drying_started_at"]),
        "conditioned_at": fmt_clock(b["conditioned_at"]) if b["conditioned_at"] else None,
    })
    return d


def build_order(o):
    d = _common(o)
    d.update({
        "model": o["model"],
        "wood_batch_id": o["wood_batch_id"],
        "status": o["status"],
        "seasoning_started_at": fmt_clock(o["seasoning_started_at"]) if o["seasoning_started_at"] else None,
        "commissioned_note": o["commissioned_note"],
        "wip_value_cents": o["wip_value_cents"],
    })
    return d


def stage_log(l):
    # Stage logs are immutable append-only: no updated_at, no version.
    return {
        "id": l["id"],
        "created_at": fmt_dt(l["created_at"]),
        "build_order_id": l["build_order_id"],
        "to_stage": l["to_stage"],
        "operation_type": l["operation_type"],
        "hours_applied": l["hours_applied"],
        "actor_role": l["actor_role"],
        "actor_id": l["actor_id"],
        "supervising_craftsman_id": l["supervising_craftsman_id"],
        "logged_at": fmt_clock(l["logged_at"]),
    }


def craftsman(c):
    d = _common(c)
    d.update({"name": c["name"], "specialty": c["specialty"]})
    return d


def apprentice(a):
    d = _common(a)
    d.update({"name": a["name"]})
    return d


def endorsement(t):
    d = _common(t)
    d.update({
        "apprentice_id": t["apprentice_id"],
        "operation_type": t["operation_type"],
        "status": t["status"],
        "logged_hours": t["logged_hours"],
        "effective_hours": t["effective_hours"],
        "supervision_log": [
            {
                "supervising_craftsman_id": e["supervising_craftsman_id"],
                "hours": e["hours"],
                "specialty_match": e["specialty_match"],
                "logged_at": fmt_clock(e["logged_at"]),
            }
            for e in t["supervision_log"]
        ],
        "endorsed_by_craftsman_id": t["endorsed_by_craftsman_id"],
    })
    return d


def instrument(i):
    d = _common(i)
    d.update({
        "build_order_id": i["build_order_id"],
        "model": i["model"],
        "serial_number": i["serial_number"],
        "status": i["status"],
        "condition_grade": i["condition_grade"],
        "certified_authentic": i["certified_authentic"],
    })
    return d


def artist(a):
    from calc import standings

    realized, forward = standings(a)
    d = _common(a)
    d.update({
        "name": a["name"],
        "tier": a["tier"],
        "performance_quota": a["performance_quota"],
        "performances_logged": a["performances_logged"],
        "status": a["status"],
        "next_review_date": fmt_clock(a["next_review_date"]),
        "standing_realized": realized,
        "standing_forward": forward,
    })
    return d


def loan(l):
    d = _common(l)
    d.update({
        "artist_id": l["artist_id"],
        "desired_model": l["desired_model"],
        "tour_start": fmt_dt(l["tour_start"]),
        "tour_end": fmt_dt(l["tour_end"]),
        "instrument_id": l["instrument_id"],
        "technician_id": l["technician_id"],
        "status": l["status"],
        "fee_cents": l["fee_cents"],
    })
    return d


def restoration(c):
    d = _common(c)
    d.update({
        "instrument_id": c["instrument_id"],
        "lead_craftsman_id": c["lead_craftsman_id"],
        "origin": c["origin"],
        "diagnosis": c["diagnosis"],
        "status": c["status"],
        "authentic_parts_value_cents": c["authentic_parts_value_cents"],
        "total_parts_value_cents": c["total_parts_value_cents"],
        "waiver_accepted": c["waiver_accepted"],
        "authenticity_pct": c["authenticity_pct"],
        "final_authentic_value_cents": c["final_authentic_value_cents"],
        "final_total_parts_value_cents": c["final_total_parts_value_cents"],
    })
    return d
