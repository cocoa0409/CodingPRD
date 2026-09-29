"""Reversal events: reporting, assessment and resolution (section 3.8)."""

from flask import Blueprint

import db
import middleware as mw
import response as resp
import validators as v
from services import calc, common, serialize

bp = Blueprint("reversals", __name__)

REVERSAL_TYPES = ("INTENTIONAL", "UNINTENTIONAL")

FILTERS = {
    "enrollment_id": ("enrollment_id", "str"),
    "credit_batch_id": ("credit_batch_id", "str"),
    "reversal_type": ("reversal_type", "str"),
    "status": ("status", "str"),
}

READ_ROLES = (mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER, mw.ROLE_REGISTRY_OFFICER)


@bp.route("/reversal-events", methods=["POST"])
def report_reversal():
    user_id, _role = mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    body = v.json_body()
    credit_batch_id = v.v_str(body, "credit_batch_id")
    reversal_type = v.v_enum(body, "reversal_type", REVERSAL_TYPES)
    affected_acres = v.v_dec(body, "affected_acres", 2, minimum=0, exclusive_min=True)
    detected_crop_year = v.v_crop_year(body, "detected_crop_year")

    batch = common.get_credit_batch(credit_batch_id)
    enrollment = db.enrollments[batch["enrollment_id"]]

    if affected_acres > enrollment["enrolled_acres"]:
        v.bad("Field 'affected_acres' may not exceed the enrollment's enrolled_acres.")
    if detected_crop_year < batch["vintage_year"]:
        v.bad("Field 'detected_crop_year' may not be earlier than the batch's vintage_year.")

    if batch["issuance_status"] != "ISSUED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "A reversal may only be reported against an ISSUED batch.",
        )

    row = db.common_fields()
    row.update({
        "enrollment_id": enrollment["id"],
        "credit_batch_id": batch["id"],
        "reversal_type": reversal_type,
        "affected_acres": affected_acres,
        "detected_crop_year": detected_crop_year,
        "affected_credits": 0,
        "buffer_draw_credits": 0,
        "unbacked_credits": 0,
        "grower_clawback_cents": 0,
        "status": "REPORTED",
        "reported_by_admin_id": user_id,
        "assessed_by_admin_id": None,
        "resolution_note": None,
    })
    db.reversal_events[row["id"]] = row
    return resp.object_response(serialize.reversal_event(row), 201)


@bp.route("/reversal-events", methods=["GET"])
def list_reversals():
    mw.authorize(*READ_ROLES)
    rows = common.apply_filters(db.reversal_events.values(), FILTERS)
    return resp.paginate(rows, serialize.reversal_event)


@bp.route("/reversal-events/<reversal_event_id>", methods=["GET"])
def read_reversal(reversal_event_id):
    mw.authorize(*READ_ROLES)
    row = common.get_reversal_event(reversal_event_id)
    enrollment = db.enrollments.get(row["enrollment_id"])
    if enrollment is not None:
        mw.require_grower_owner(enrollment["grower_id"])
    return resp.object_response(serialize.reversal_event(row))


@bp.route("/reversal-events/<reversal_event_id>/assess", methods=["POST"])
def assess_reversal(reversal_event_id):
    user_id, _role = mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    event = common.get_reversal_event(reversal_event_id)

    if event["status"] != "REPORTED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION", "Only a REPORTED reversal event may be assessed."
        )
    if user_id == event["reported_by_admin_id"]:
        common.fail("ERR_SEGREGATION_OF_DUTIES")

    batch = db.credit_batches[event["credit_batch_id"]]
    enrollment = db.enrollments[event["enrollment_id"]]
    grower = db.growers[enrollment["grower_id"]]
    pool = db.buffer_pool()

    figures = calc.reversal_assessment(
        batch, enrollment, pool["balance_credits"], event["reversal_type"], event["affected_acres"]
    )

    # hop 1 -- the event itself and the grower's reversal history
    event.update(figures)
    event["status"] = "ASSESSED"
    event["assessed_by_admin_id"] = user_id
    db.touch(event)
    grower["reversal_count"] = grower["reversal_count"] + 1
    db.touch(grower)

    suspended = []
    if event["reversal_type"] == "UNINTENTIONAL":
        # hops 2 and 3 -- the pool absorbs what it can and may fall into deficit
        pool["drawn_total"] = pool["drawn_total"] + figures["buffer_draw_credits"]
        pool["balance_credits"] = pool["balance_credits"] - figures["buffer_draw_credits"]
        pool["unbacked_reversal_credits"] = (
            pool["unbacked_reversal_credits"] + figures["unbacked_credits"]
        )
        common.recompute_pool(pool)
        db.touch(pool)
        # hop 4 -- a deficit freezes registry listings programme-wide
        if pool["pool_status"] == "DEFICIT":
            for other in db.sorted_rows(db.credit_batches):
                if other["registry_status"] != "LISTED":
                    continue
                other["registry_status"] = "SUSPENDED"
                db.touch(other)
                suspended.append(other)
    else:
        # the intentional branch never touches the pool, only this batch
        if batch["registry_status"] == "LISTED":
            batch["registry_status"] = "SUSPENDED"
            db.touch(batch)
            suspended.append(batch)

    # hops 5 and 6 -- permanence breach and the clawback of unpaid accruals
    common.breach_enrollments_for_batches(suspended, event)
    grower["outstanding_clawback_cents"] = (
        grower["outstanding_clawback_cents"] + event["grower_clawback_cents"]
    )
    db.touch(grower)

    # hop 7 -- the clawback threshold suspends the grower and cascades downward
    common.maybe_suspend_for_clawback(grower)

    return resp.object_response(serialize.reversal_event(event))


@bp.route("/reversal-events/<reversal_event_id>/resolve", methods=["POST"])
def resolve_reversal(reversal_event_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    event = common.get_reversal_event(reversal_event_id)
    body = v.json_body()
    resolution_note = v.v_str(body, "resolution_note")

    if event["status"] != "ASSESSED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION", "Only an ASSESSED reversal event may be resolved."
        )

    event["resolution_note"] = resolution_note
    event["status"] = "RESOLVED"
    db.touch(event)

    pool = db.buffer_pool()
    if pool["pool_status"] == "HEALTHY":
        restored = []
        for batch in db.sorted_rows(db.credit_batches):
            if batch["registry_status"] != "SUSPENDED":
                continue
            batch["registry_status"] = "LISTED"
            db.touch(batch)
            restored.append(batch)
        seen = []
        for batch in restored:
            enrollment = db.enrollments.get(batch["enrollment_id"])
            if enrollment is None or enrollment["id"] in seen:
                continue
            seen.append(enrollment["id"])
            if enrollment["permanence_status"] != "BREACHED":
                continue
            still_suspended = any(
                other["enrollment_id"] == enrollment["id"]
                and other["registry_status"] == "SUSPENDED"
                for other in db.credit_batches.values()
            )
            if not still_suspended:
                enrollment["permanence_status"] = "IN_COMPLIANCE"
                db.touch(enrollment)

    return resp.object_response(serialize.reversal_event(event))
