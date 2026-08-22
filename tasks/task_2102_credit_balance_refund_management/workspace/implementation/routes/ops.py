"""Logical clock and the nightly operations checkpoint (PRD 2.5, 3.14)."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import db
import derive
import response
import validation as v

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
@auth.require(auth.SYSTEM_ADMIN)
def set_clock():
    data = v.body()
    target = v.req_dt(data, "to_iso8601")
    clock.set_now(target)
    return response.ok({"current_utc": clock.iso(clock.now())})


@bp.post("/ops/run-aging-sweep")
@auth.require(auth.SYSTEM_ADMIN, auth.COMPLIANCE_OFFICER)
def run_aging_sweep():
    now = clock.now()

    staled_check_count = 0
    for chk in db.ordered(list(db.check_disbursements.values())):
        if chk["state"] == "ISSUED" and chk["stale_at"] is not None and now >= chk["stale_at"]:
            chk["state"] = "STALE"
            db.touch(chk)
            staled_check_count += 1

    late_obligation_count = 0
    for ob in db.ordered(list(db.medicare_obligations.values())):
        if ob["state"] == "OPEN" and now > ob["due_at"]:
            ob["state"] = "LATE"
            derive.refresh_obligation(ob)
            db.touch(ob)
            late_obligation_count += 1

    closed_batch_count = 0
    for batch in db.ordered(list(db.refund_batches.values())):
        if batch["state"] != "ISSUED":
            continue
        live = [c for c in db.checks_for_batch(batch["id"])
                if c["state"] in ("PENDING", "ISSUED")]
        if not live:
            batch["state"] = "CLOSED"
            db.touch(batch)
            closed_batch_count += 1

    withdrawn_notice_count = 0
    for notice in db.ordered(list(db.take_back_notices.values())):
        if notice["state"] != "DISPUTED":
            continue
        expiry = clock.add_days(notice["dispute_deadline_at"], calc.DISPUTE_RESOLUTION_GRACE_DAYS)
        if now <= expiry:
            continue
        for offset in db.offsets_for_notice(notice["id"]):
            if offset["state"] == "APPLIED":
                cascade.reverse_offset(offset, remark="Dispute resolution grace expired")
        notice["state"] = "WITHDRAWN"
        db.touch(notice)
        withdrawn_notice_count += 1

    return response.ok({
        "staled_check_count": staled_check_count,
        "late_obligation_count": late_obligation_count,
        "closed_batch_count": closed_batch_count,
        "withdrawn_notice_count": withdrawn_notice_count,
    })
