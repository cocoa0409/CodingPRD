"""Enrolment incentive accrual, payment and clawback (PRD 3.9)."""
from flask import Blueprint

import calc
import derive
import shape
from authz import PROGRAM_ADMIN, require_roles
from db import base_record, sort_key, store, touch
from errors import conflict, invalid_state, unprocessable
from respond import success
from routes._common import award_or_404, producer_or_404
from serialize import public

bp = Blueprint("awards", __name__)


@bp.post("/incentive-awards")
def accrue_award():
    require_roles(PROGRAM_ADMIN)
    body = shape.body()
    producer_id = shape.s_str(body, "producer_id")
    period_start = shape.s_date(body, "period_start")
    period_end = shape.s_date(body, "period_end")
    producer = producer_or_404(producer_id)
    # Band 11 - accrual requires an enrolled producer.
    if producer["enrollment_status"] != "ENROLLED":
        raise conflict("ERR_PRODUCER_NOT_ENROLLED", "The producer is not ENROLLED")
    # Band 13 - the period must be non-degenerate.
    if period_end < period_start:
        raise unprocessable("ERR_INVALID_WINDOW", "period_end may not precede period_start")
    # Band 15 - one live award per producer period.
    for award in store.awards.values():
        if (award["producer_id"] == producer["id"]
                and award["period_start"] == period_start
                and award["period_end"] == period_end
                and award["status"] in ("ACCRUED", "PAID")):
            raise conflict("ERR_AWARD_PERIOD_DUPLICATE",
                           "An award already covers this producer and period")

    head_count = producer["enrolled_head_count"]
    tier, tier_factor = calc.tier_for_head_count(head_count)
    compliance = calc.compliance_multiplier(producer["on_time_movement_pct"])
    lines = []
    for premises in sorted(derive.producer_premises(producer["id"]), key=sort_key):
        if premises["registration_status"] != "ACTIVE":
            continue
        lines.append({
            "premises_id": premises["id"],
            "animal_count": premises["animal_count"],
            "line_cents": calc.award_line_cents(premises["animal_count"], tier_factor,
                                                compliance),
        })
    rec = base_record()
    rec.update({
        "producer_id": producer["id"],
        "period_start": period_start,
        "period_end": period_end,
        "head_count_snapshot": head_count,
        "tier_factor": calc.to_dec(tier_factor, 2),
        "compliance_multiplier": calc.to_dec(compliance, 2),
        "line_items": lines,
        "awarded_cents": sum(l["line_cents"] for l in lines),
        "clawback_cents": 0,
        "status": "ACCRUED",
    })
    store.awards[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.post("/incentive-awards/<award_id>/pay")
def pay_award(award_id):
    require_roles(PROGRAM_ADMIN)
    award = award_or_404(award_id)
    # Band 10 - own-state gate.
    if award["status"] != "ACCRUED":
        raise invalid_state("Only an ACCRUED award may be paid")
    producer = store.producers.get(award["producer_id"])
    # Band 11 - payment requires an enrolled producer.
    if producer is None or producer["enrollment_status"] != "ENROLLED":
        raise conflict("ERR_PRODUCER_NOT_ENROLLED", "The producer is not ENROLLED")
    award["status"] = "PAID"
    touch(award)
    producer["incentive_balance_cents"] += award["awarded_cents"]
    touch(producer)
    return success(public(award))


@bp.post("/incentive-awards/<award_id>/clawback")
def clawback_award(award_id):
    require_roles(PROGRAM_ADMIN)
    award = award_or_404(award_id)
    if award["status"] != "PAID":
        raise invalid_state("Only a PAID award may be clawed back")
    amount = award["awarded_cents"]
    award["status"] = "CLAWED_BACK"
    award["clawback_cents"] = amount
    touch(award)
    producer = store.producers.get(award["producer_id"])
    if producer is not None:
        producer["incentive_balance_cents"] -= amount
        producer["lifetime_clawback_cents"] += amount
        touch(producer)
    return success(public(award))
