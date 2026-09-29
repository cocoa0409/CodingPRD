"""Subject-matter-expert endpoints (PRD section 3.2)."""

from flask import Blueprint

import envelope
import governance as gov
import listing
import serialize
import validate as v
from auth import (ROLE_LEGAL, ROLE_MANAGING_EDITOR, ROLE_SME, endpoint)
from store import store, touch, new_row

bp = Blueprint("experts", __name__)


@bp.post("/editorial/experts")
@endpoint(ROLE_MANAGING_EDITOR)
def create_expert():
    body = v.body()
    full_name = v.v_str(body, "full_name", minlen=1, maxlen=120)
    tags = v.v_str_list(body, "expertise_tags", min_items=1, max_items=8,
                        item_min=1, item_max=40, lowercase=True)
    hours = v.v_int(body, "weekly_capacity_hours", minimum=1, maximum=60)

    row = new_row("experts", {
        "full_name": full_name,
        "expertise_tags": tags,
        "weekly_capacity_hours": hours,
        "status": "AVAILABLE",
        "committed_hours_total": 0,
    })
    store.experts[row["id"]] = row
    return envelope.created(serialize.expert(row))


@bp.post("/editorial/experts/<eid>/availability")
@endpoint(ROLE_MANAGING_EDITOR)
def set_availability(eid):
    expert = gov.get_expert(eid)
    body = v.body()
    status = v.v_enum(body, "status", v.EXPERT_STATUSES)
    if status == expert["status"]:
        v.fail("expert is already " + status)

    if status == "AVAILABLE":
        # The return leg is deliberately shallow and does nothing else.
        expert["status"] = "AVAILABLE"
        touch(expert)
        return envelope.ok(serialize.expert(expert))

    # Step 1.
    expert["status"] = "ON_LEAVE"
    touch(expert)
    # Step 2 -- release the workload.
    reverted = []
    for brief in sorted(gov.briefs_of_expert(eid),
                        key=lambda r: (r["created_at"], r["id"])):
        if brief["state"] in ("SME_ASSIGNED", "APPROVED"):
            brief["state"] = "DRAFT"
            brief["sme_expert_id"] = None
            touch(brief)
            reverted.append(brief)
    # Step 3 -- recompute the ledger from the surviving briefs.
    gov.recompute_expert_hours(expert)
    # Step 4 -- disturb the content behind those briefs.
    disturbed = []
    for brief in reverted:
        for item in sorted(gov.items_of_brief(brief["id"]),
                           key=lambda r: (r["created_at"], r["id"])):
            if item["workflow_state"] in ("IN_REVIEW", "READY"):
                item["workflow_state"] = "CHANGES_REQUESTED"
                touch(item)
                disturbed.append(item)
    # Step 5 -- void the in-flight review.
    for item in disturbed:
        gov.void_gates(item, only_pending=True)
    # Step 6 -- posture for every campaign that owned a disturbed item.
    seen = []
    for item in disturbed:
        if item["campaign_id"] not in seen:
            seen.append(item["campaign_id"])
    for campaign_id in seen:
        campaign = store.campaigns.get(campaign_id)
        if campaign is not None:
            gov.reconcile_campaign(campaign)
    return envelope.ok(serialize.expert(expert))


@bp.get("/editorial/experts")
@endpoint(ROLE_MANAGING_EDITOR, ROLE_LEGAL)
def list_experts():
    rows = listing.apply_filters(list(store.experts.values()),
                                 [("status", "status")])
    rows = listing.filter_membership(rows, "expertise_tag", "expertise_tags")
    rows = listing.sort_by(rows, ["full_name"])
    window, pagination = envelope.page(rows)
    return envelope.ok_list([serialize.expert(r) for r in window], pagination)


@bp.get("/editorial/experts/<eid>")
@endpoint(ROLE_MANAGING_EDITOR, ROLE_LEGAL, ROLE_SME)
def read_expert(eid):
    return envelope.ok(serialize.expert(gov.get_expert(eid)))
