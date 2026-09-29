"""Step deals: the guaranteed floor, the option ladder and the notes cycle."""

from flask import Blueprint, request

import domain as d
from auth import (ROLE_BUSINESS_AFFAIRS, ROLE_DEV_EXEC, ROLE_FINANCE,
                  ROLE_PLATFORM_ADMIN, authorize)
from errors import ApiError
from responses import object_response, paginated
from store import add_days, new_row, store, touch
from validators import json_body, require_body, v_enum, v_int, v_string

bp = Blueprint("deal", __name__)

DEAL_READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_BUSINESS_AFFAIRS, ROLE_DEV_EXEC,
                   ROLE_FINANCE)


def _validate_steps(body, writer):
    raw = body.get("steps")
    if raw is None:
        raise ApiError("ERR_INVALID_REQUEST", "steps is required.")
    if not isinstance(raw, list):
        raise ApiError("ERR_INVALID_REQUEST", "steps must be an array.")
    if len(raw) < 1 or len(raw) > 6:
        raise ApiError("ERR_INVALID_REQUEST", "steps must hold between 1 and 6 entries.")
    parsed = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each step must be an object.")
        step_type = v_enum(entry, "step_type", d.STEP_TYPES)
        fee_cents = v_int(entry, "fee_cents", minimum=0)
        floor = d.guild_floor_cents(step_type, writer["guild_minimum_tier"])
        parsed.append({
            "step_type": step_type,
            "fee_cents": fee_cents,
            "effective_fee_cents": max(fee_cents, floor),
        })
    return parsed


@bp.post("/script-deals")
@authorize(ROLE_BUSINESS_AFFAIRS)
def create_script_deal(principal):
    body = require_body(json_body())
    writer = d.get_writer(body.get("writer_id"))
    project = d.get_project(body.get("project_id"))

    parsed_steps = _validate_steps(body, writer)
    guaranteed_step_count = v_int(body, "guaranteed_step_count",
                                  minimum=1, maximum=len(parsed_steps))
    option_period_days = v_int(body, "option_period_days", minimum=1, maximum=365)

    # 11 -- the project must still be in script development.
    if project["dev_status"] not in ("ACTIVE_DEVELOPMENT", "SCRIPT_COMPLETE"):
        raise ApiError("ERR_INVALID_PROJECT_STATE")

    slate = d.slate_of_project(project)

    # 25 -- a writer held by another slate may not be attached here.
    for hold in d.active_in_term_holds(writer["id"]):
        if hold["slate_id"] != slate["id"]:
            raise ApiError("ERR_WRITER_EXCLUSIVITY_CONFLICT")

    guaranteed_commitment = sum(
        s["effective_fee_cents"] for i, s in enumerate(parsed_steps, start=1)
        if i <= guaranteed_step_count
    )
    # 45 -- the slate must cover the guaranteed commitment.
    if d.slate_available_dev_cents(slate) < guaranteed_commitment:
        raise ApiError("ERR_SLATE_DEV_BUDGET_EXCEEDED")

    deal = new_row(
        project_id=project["id"],
        writer_id=writer["id"],
        guaranteed_step_count=guaranteed_step_count,
        option_period_days=option_period_days,
        deal_status="EXECUTED",
    )
    store.script_deals[deal["id"]] = deal

    for index, spec in enumerate(parsed_steps, start=1):
        step = new_row(
            script_deal_id=deal["id"],
            step_index=index,
            step_type=spec["step_type"],
            fee_cents=spec["fee_cents"],
            effective_fee_cents=spec["effective_fee_cents"],
            status="PENDING",
            option_expires_at=add_days(deal["created_at"], index * option_period_days),
            notes_round=0,
            exercised_at=None,
            delivered_at=None,
            accepted_at=None,
            notes_summary=None,
        )
        store.deal_steps[step["id"]] = step

    touch(project)
    touch(slate)
    return object_response(d.serialize_script_deal(deal), 201)


@bp.get("/script-deals/<deal_id>")
@authorize(*DEAL_READ_ROLES)
def read_script_deal(principal, deal_id):
    deal = d.get_script_deal(deal_id)
    return object_response(d.serialize_script_deal(deal))


@bp.get("/script-deals")
@authorize(*DEAL_READ_ROLES)
def list_script_deals(principal):
    rows = d.ordered(list(store.script_deals.values()))
    project_id = request.args.get("project_id")
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    writer_id = request.args.get("writer_id")
    if writer_id is not None:
        rows = [r for r in rows if r["writer_id"] == writer_id]
    deal_status = request.args.get("deal_status")
    if deal_status is not None:
        rows = [r for r in rows if r["deal_status"] == deal_status]
    return paginated(rows, d.serialize_script_deal)


@bp.get("/script-deals/<deal_id>/steps")
@authorize(*DEAL_READ_ROLES)
def list_deal_steps(principal, deal_id):
    deal = d.get_script_deal(deal_id)
    return paginated(d.steps_of(deal), d.serialize_deal_step)


# ---------------------------------------------------------------------------
# step transitions
# ---------------------------------------------------------------------------

@bp.post("/script-deals/<deal_id>/steps/<step_id>/exercise")
@authorize(ROLE_BUSINESS_AFFAIRS)
def exercise_step(principal, deal_id, step_id):
    deal = d.get_script_deal(deal_id)
    step = d.get_deal_step(deal, step_id)

    # 12 -- a frozen deal has frozen steps.
    if deal["deal_status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_DEAL_STATE")

    # 13 -- the ladder is climbed in order.
    if step["status"] != "PENDING":
        raise ApiError("ERR_INVALID_DEAL_STEP_STATE")
    for other in d.steps_of(deal):
        if other["step_index"] < step["step_index"] \
                and other["status"] not in ("ACCEPTED", "CUT_OFF"):
            raise ApiError("ERR_INVALID_DEAL_STEP_STATE")

    # 30 -- the option period must still be running.
    if store.now() >= step["option_expires_at"]:
        raise ApiError("ERR_OPTION_PERIOD_EXPIRED")

    writer = store.writers[deal["writer_id"]]
    # 34 -- at most two open steps per writer.
    if d.writer_open_step_count(writer) >= d.MAX_OPEN_STEPS_PER_WRITER:
        raise ApiError("ERR_WRITER_STEP_LOAD_EXCEEDED")

    step["status"] = "EXERCISED"
    step["exercised_at"] = store.now()
    touch(step)

    project = d.project_of_deal(deal)
    if step["step_index"] > deal["guaranteed_step_count"] \
            and project["dev_status"] == "SCRIPT_COMPLETE":
        project["dev_status"] = "ACTIVE_DEVELOPMENT"

    touch(deal)
    touch(project)
    touch(d.slate_of_project(project))
    return object_response(d.serialize_deal_step(step))


@bp.post("/script-deals/<deal_id>/steps/<step_id>/deliver")
@authorize(ROLE_BUSINESS_AFFAIRS, ROLE_DEV_EXEC)
def deliver_step(principal, deal_id, step_id):
    deal = d.get_script_deal(deal_id)
    step = d.get_deal_step(deal, step_id)
    if deal["deal_status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_DEAL_STATE")
    if step["status"] not in ("EXERCISED", "NOTES_ISSUED"):
        raise ApiError("ERR_INVALID_DEAL_STEP_STATE")
    step["status"] = "DELIVERED"
    step["delivered_at"] = store.now()
    touch(step)
    return object_response(d.serialize_deal_step(step))


@bp.post("/script-deals/<deal_id>/steps/<step_id>/review")
@authorize(ROLE_DEV_EXEC)
def review_step(principal, deal_id, step_id):
    deal = d.get_script_deal(deal_id)
    step = d.get_deal_step(deal, step_id)
    body = require_body(json_body())
    outcome = v_enum(body, "outcome", ("NOTES", "ACCEPT"))
    notes_summary = v_string(body, "notes_summary", required=False,
                             max_len=1000, allow_null=True, default=None)

    if deal["deal_status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_DEAL_STATE")
    if step["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_DEAL_STEP_STATE")

    if outcome == "NOTES":
        # 35 -- at most two notes rounds per step.
        if step["notes_round"] >= d.MAX_NOTES_ROUNDS:
            raise ApiError("ERR_NOTES_ROUNDS_EXHAUSTED")
        step["status"] = "NOTES_ISSUED"
        step["notes_round"] = step["notes_round"] + 1
        if notes_summary is not None:
            step["notes_summary"] = notes_summary
        touch(step)
        return object_response(d.serialize_deal_step(step))

    step["status"] = "ACCEPTED"
    step["accepted_at"] = store.now()
    if notes_summary is not None:
        step["notes_summary"] = notes_summary
    touch(step)
    touch(deal)

    project = d.project_of_deal(deal)
    guaranteed_all_accepted = all(
        s["status"] == "ACCEPTED" for s in d.steps_of(deal)
        if s["step_index"] <= deal["guaranteed_step_count"]
    )
    if guaranteed_all_accepted and project["dev_status"] == "ACTIVE_DEVELOPMENT":
        project["dev_status"] = "SCRIPT_COMPLETE"
        touch(project)
    return object_response(d.serialize_deal_step(step))


@bp.post("/script-deals/<deal_id>/cutoff")
@authorize(ROLE_BUSINESS_AFFAIRS)
def cutoff_deal(principal, deal_id):
    deal = d.get_script_deal(deal_id)
    body = require_body(json_body())
    reason = v_string(body, "cutoff_reason", max_len=500)

    if deal["deal_status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_DEAL_STATE")

    # 26 -- a guaranteed step still PENDING blocks the whole operation.
    for step in d.steps_of(deal):
        if step["step_index"] <= deal["guaranteed_step_count"] \
                and step["status"] == "PENDING":
            raise ApiError("ERR_GUARANTEED_STEP_NOT_CUTTABLE")

    for step in d.steps_of(deal):
        if step["status"] == "PENDING":
            step["status"] = "CUT_OFF"
            touch(step)
    deal["deal_status"] = "CUT_OFF"
    deal["cutoff_reason"] = reason
    touch(deal)

    project = d.project_of_deal(deal)
    touch(project)
    touch(d.slate_of_project(project))
    return object_response(d.serialize_script_deal(deal))
