"""Campaign and calendar-slot endpoints (PRD sections 3.1, 3.4)."""

from flask import Blueprint

import calc
import envelope
import governance as gov
import listing
import serialize
import validate as v
from auth import ALL_REVIEWERS, ALL_REVIEWERS_AND_SME, ROLE_MANAGING_EDITOR, endpoint
from errors import ApiError
from store import store, touch, new_row

bp = Blueprint("campaigns", __name__)


@bp.post("/editorial/campaigns")
@endpoint(ROLE_MANAGING_EDITOR)
def create_campaign():
    body = v.body()
    code = v.v_str(body, "code", minlen=1, maxlen=32, pattern=v.CODE_RE)
    persona = v.v_enum(body, "persona", v.PERSONAS)
    stage = v.v_enum(body, "primary_funnel_stage", v.FUNNEL_STAGES)
    quarter = v.v_str(body, "quarter_code", pattern=v.QUARTER_RE)

    for existing in store.campaigns.values():
        if existing["code"] == code:
            raise ApiError("ERR_CAMPAIGN_CODE_DUPLICATE",
                           "campaign code is already in use")

    row = new_row("campaigns", {
        "code": code,
        "persona": persona,
        "primary_funnel_stage": stage,
        "quarter_code": quarter,
        "status": "PLANNING",
        "governance_posture": "OPEN",
        "breached_gate_count": 0,
        "expired_usage_count": 0,
        "unsubstantiated_published_claim_count": 0,
        "committed_points_total": 0,
    })
    store.campaigns[row["id"]] = row
    return envelope.created(serialize.campaign(row))


@bp.post("/editorial/campaigns/<cid>/activate")
@endpoint(ROLE_MANAGING_EDITOR)
def activate_campaign(cid):
    campaign = gov.get_campaign(cid)
    if campaign["status"] != "PLANNING":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID",
                       "campaign is not in PLANNING")
    campaign["status"] = "ACTIVE"
    touch(campaign)
    gov.reconcile_campaign(campaign)
    return envelope.ok(serialize.campaign(campaign))


@bp.post("/editorial/campaigns/<cid>/close")
@endpoint(ROLE_MANAGING_EDITOR)
def close_campaign(cid):
    campaign = gov.get_campaign(cid)
    if campaign["status"] != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID", "campaign is not ACTIVE")
    for item in gov.items_of_campaign(cid):
        if item["workflow_state"] in gov.OPEN_ITEM_STATES:
            raise ApiError("ERR_CAMPAIGN_HAS_OPEN_ITEMS",
                           "campaign still has unfinished content items")

    # Step 1.
    campaign["status"] = "CLOSED"
    touch(campaign)
    # Step 2 -- lock the calendar.
    for slot in sorted(gov.slots_of_campaign(cid),
                       key=lambda r: (r["week_start_date"], r["funnel_stage"], r["id"])):
        if slot["status"] in ("OPEN", "FULL"):
            slot["status"] = "LOCKED"
            touch(slot)
    # Step 3 -- archive unfinished planning work.
    released = []
    for brief in sorted(gov.briefs_of_campaign(cid),
                        key=lambda r: (r["created_at"], r["id"])):
        if brief["state"] in ("DRAFT", "SME_ASSIGNED"):
            expert_id = brief["sme_expert_id"]
            brief["state"] = "ARCHIVED"
            brief["sme_expert_id"] = None
            touch(brief)
            if expert_id is not None and expert_id not in released:
                released.append(expert_id)
    # Step 4 -- recompute the ledgers of every expert who lost a brief.
    for expert_id in released:
        expert = store.experts.get(expert_id)
        if expert is not None:
            gov.recompute_expert_hours(expert)
    # Step 5.
    gov.reconcile_campaign(campaign)
    return envelope.ok(serialize.campaign(campaign))


@bp.get("/editorial/campaigns")
@endpoint(*ALL_REVIEWERS)
def list_campaigns():
    rows = listing.apply_filters(list(store.campaigns.values()), [
        ("status", "status"),
        ("governance_posture", "governance_posture"),
        ("persona", "persona"),
        ("quarter_code", "quarter_code"),
    ])
    rows = listing.sort_created_desc(rows)
    window, pagination = envelope.page(rows)
    return envelope.ok_list([serialize.campaign(r) for r in window], pagination)


@bp.get("/editorial/campaigns/<cid>")
@endpoint(*ALL_REVIEWERS_AND_SME)
def read_campaign(cid):
    return envelope.ok(serialize.campaign(gov.get_campaign(cid)))


@bp.post("/editorial/campaigns/<cid>/calendar-slots")
@endpoint(ROLE_MANAGING_EDITOR)
def create_slot(cid):
    campaign = gov.get_campaign(cid)
    body = v.body()
    week_start = v.v_date(body, "week_start_date")
    if week_start.weekday() != 0:
        v.fail("week_start_date must be a Monday")
    stage = v.v_enum(body, "funnel_stage", v.FUNNEL_STAGES)
    capacity = v.v_int(body, "capacity_points", minimum=1, maximum=200)

    for slot in store.slots.values():
        if (slot["campaign_id"] == campaign["id"]
                and slot["week_start_date"] == week_start
                and slot["funnel_stage"] == stage):
            raise ApiError("ERR_SLOT_DUPLICATE_WEEK",
                           "a slot already exists for that week and funnel stage")

    row = new_row("slots", {
        "campaign_id": campaign["id"],
        "week_start_date": week_start,
        "funnel_stage": stage,
        "capacity_points": capacity,
        "committed_points": 0,
        "utilization_pct": calc.ZERO2,
        "status": "OPEN",
    })
    store.slots[row["id"]] = row
    return envelope.created(serialize.slot(row))


def _slot_rows(rows, include_campaign_filter):
    pairs = [("funnel_stage", "funnel_stage"), ("status", "status")]
    if include_campaign_filter:
        pairs.append(("campaign_id", "campaign_id"))
    rows = listing.apply_filters(rows, pairs)
    return listing.sort_by(rows, ["week_start_date", "funnel_stage"])


@bp.get("/editorial/campaigns/<cid>/calendar-slots")
@endpoint(*ALL_REVIEWERS)
def list_campaign_slots(cid):
    campaign = gov.get_campaign(cid)
    rows = _slot_rows(gov.slots_of_campaign(campaign["id"]), False)
    window, pagination = envelope.page(rows)
    return envelope.ok_list([serialize.slot(r) for r in window], pagination)


@bp.get("/editorial/calendar-slots")
@endpoint(*ALL_REVIEWERS)
def list_slots():
    rows = _slot_rows(list(store.slots.values()), True)
    window, pagination = envelope.page(rows)
    return envelope.ok_list([serialize.slot(r) for r in window], pagination)


@bp.get("/editorial/calendar-slots/<sid>")
@endpoint(*ALL_REVIEWERS)
def read_slot(sid):
    return envelope.ok(serialize.slot(gov.get_slot(sid)))


@bp.post("/editorial/calendar-slots/<sid>/lock")
@endpoint(ROLE_MANAGING_EDITOR)
def lock_slot(sid):
    slot = gov.get_slot(sid)
    if slot["status"] not in ("OPEN", "FULL"):
        raise ApiError("ERR_SLOT_STATE_INVALID", "slot is not OPEN or FULL")
    slot["status"] = "LOCKED"
    touch(slot)
    return envelope.ok(serialize.slot(slot))
