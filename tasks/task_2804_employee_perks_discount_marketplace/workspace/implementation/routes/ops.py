"""Control plane: the logical clock and the five-pass epoch sweep (PRD 2.4)."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import db
import response
import validate

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    # The scaffold scopes the identity and role rules to "every /perks endpoint",
    # and all five roles are authorised here, so the control plane is open.
    body = validate.json_body()
    parsed = validate.fields(body, [
        {"name": "to_iso8601", "type": "datetime", "required": True},
    ])
    clock.set_now(parsed["to_iso8601"])
    return response.ok({"current_utc": clock.fmt(clock.now())})


@bp.post("/_ops/run-epoch")
def run_epoch():
    auth.require(auth.PLATFORM_ADMIN)
    now = clock.now()

    expired_offer_count = 0
    for offer in db.sorted_rows(db.offers.values()):
        if offer["status"] in ("ACTIVE", "PAUSED") and offer["window_end"] <= now:
            offer["status"] = "EXPIRED"
            offer["expired_at"] = now
            db.touch(offer)
            expired_offer_count += 1

    completed_slot_count = 0
    for slot in db.sorted_rows(db.placement_slots.values()):
        if slot["status"] == "CONFIRMED" and slot["slot_window_end"] < now:
            slot["status"] = "COMPLETED"
            db.touch(slot)
            completed_slot_count += 1

    voided_redemption_count = 0
    for redemption in db.sorted_rows(db.redemptions.values()):
        if (redemption["verification_status"] == "PENDING"
                and redemption["verification_expires_at"] is not None
                and redemption["verification_expires_at"] <= now):
            if cascade.void_redemption(redemption, "VERIFICATION_TTL_EXPIRED"):
                voided_redemption_count += 1

    stale_employer_count = 0
    for employer in db.sorted_rows(db.employers.values()):
        if employer["integration_status"] != "SYNCED":
            continue
        last_sync = employer.get("last_sync_at")
        if last_sync is None:
            continue
        if clock.plus_days(last_sync, calc.INTEGRATION_STALE_DAYS) <= now:
            employer["integration_status"] = "STALE"
            db.touch(employer)
            stale_employer_count += 1

    default_judged_dispute_count = 0
    for dispute in db.sorted_rows(db.disputes.values()):
        if dispute["status"] != "OPEN":
            continue
        if dispute["response_deadline_at"] is None or dispute["response_deadline_at"] > now:
            continue
        if dispute["response_note"] is not None:
            continue
        redemption = db.redemptions.get(dispute["redemption_id"])
        dispute["status"] = "RESOLVED_MERCHANT_FAULT"
        dispute["default_judged"] = True
        dispute["outcome_credit_cents"] = 0
        dispute["resolved_at"] = now
        db.touch(dispute)
        if redemption is not None:
            cascade.merchant_fault_cascade(dispute, redemption, 0)
        default_judged_dispute_count += 1

    return response.ok({
        "expired_offer_count": expired_offer_count,
        "completed_slot_count": completed_slot_count,
        "voided_redemption_count": voided_redemption_count,
        "stale_employer_count": stale_employer_count,
        "default_judged_dispute_count": default_judged_dispute_count,
    })
