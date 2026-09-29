"""Content-brief endpoints (PRD section 3.3)."""

from flask import Blueprint, g

import calc
import envelope
import governance as gov
import listing
import serialize
import timeutil
import validate as v
from auth import ALL_REVIEWERS_AND_SME, ROLE_MANAGING_EDITOR, ROLE_SME, endpoint
from errors import ApiError
from store import store, touch, new_row

bp = Blueprint("briefs", __name__)


def _require_assigned_expert(brief):
    """Ladder rule 10 -- the caller must be the brief's assigned expert."""
    if brief["sme_expert_id"] is None or brief["sme_expert_id"] != g.user_id:
        raise ApiError("ERR_SME_NOT_ASSIGNED_TO_BRIEF",
                       "caller is not the expert assigned to this brief")


@bp.post("/editorial/briefs")
@endpoint(ROLE_MANAGING_EDITOR)
def create_brief():
    body = v.body()
    campaign_id = v.v_str(body, "campaign_id")
    stage = v.v_enum(body, "funnel_stage", v.FUNNEL_STAGES)
    intent = v.v_enum(body, "search_intent", v.SEARCH_INTENTS)
    keyword = v.v_str(body, "primary_keyword", minlen=1, maxlen=80, lowercase=True)
    word_count = v.v_int(body, "target_word_count", minimum=100, maximum=9000)
    tag = v.v_str(body, "required_expertise_tag", minlen=1, maxlen=40, lowercase=True)
    window_start = v.v_instant(body, "review_window_start")
    window_end = v.v_instant(body, "review_window_end")
    secondary = v.v_str_list(body, "secondary_keywords", required=False,
                             min_items=0, max_items=10, item_min=1, item_max=80,
                             lowercase=True, default=[])
    regulated = v.v_bool(body, "requires_regulated_review", default=False)

    effort = calc.brief_effort_points(intent, word_count, stage, regulated)
    reserved = calc.sme_reserved_hours(effort)

    if window_end <= window_start:
        v.fail("review_window_end must be strictly after review_window_start")
    if timeutil.week_anchor(window_start) != timeutil.week_anchor(window_end):
        v.fail("the review window must sit inside a single ISO week")
    seconds = (window_end - window_start).total_seconds()
    if seconds % 3600 != 0:
        v.fail("the review window must be a whole number of hours")
    if seconds / 3600 < reserved:
        v.fail("the review window must be at least sme_reserved_hours long")

    campaign = gov.get_campaign(campaign_id)
    if campaign["status"] != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID", "campaign is not ACTIVE")

    row = new_row("briefs", {
        "campaign_id": campaign["id"],
        "funnel_stage": stage,
        "search_intent": intent,
        "primary_keyword": keyword,
        "secondary_keywords": secondary,
        "target_word_count": word_count,
        "required_expertise_tag": tag,
        "requires_regulated_review": regulated,
        "review_window_start": window_start,
        "review_window_end": window_end,
        "sme_expert_id": None,
        "effort_points": effort,
        "sme_reserved_hours": reserved,
        "state": "DRAFT",
    })
    store.briefs[row["id"]] = row
    return envelope.created(serialize.brief(row))


@bp.post("/editorial/briefs/<bid>/assign-sme")
@endpoint(ROLE_MANAGING_EDITOR)
def assign_sme(bid):
    brief = gov.get_brief(bid)
    body = v.body()
    expert_id = v.v_str(body, "sme_expert_id")
    expected = v.v_int(body, "expected_expert_version")

    expert = gov.get_expert(expert_id)
    if expected != expert["version"]:
        raise ApiError("ERR_STALE_EXPERT_VERSION",
                       "expected_expert_version does not match the expert")

    if brief["state"] != "DRAFT":
        raise ApiError("ERR_BRIEF_STATE_INVALID", "brief is not in DRAFT")
    campaign = store.campaigns[brief["campaign_id"]]
    if campaign["status"] != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID", "campaign is not ACTIVE")
    gov.require_not_frozen(campaign)

    if expert["status"] != "AVAILABLE":
        raise ApiError("ERR_EXPERT_UNAVAILABLE", "expert is not AVAILABLE")
    if brief["required_expertise_tag"] not in expert["expertise_tags"]:
        raise ApiError("ERR_EXPERTISE_TAG_MISMATCH",
                       "expert does not hold the required expertise tag")
    for other in gov.briefs_of_expert(expert["id"]):
        if other["id"] == brief["id"]:
            continue
        if other["state"] not in calc.BRIEF_COUNTED_STATES:
            continue
        if timeutil.overlaps(brief["review_window_start"], brief["review_window_end"],
                             other["review_window_start"], other["review_window_end"]):
            raise ApiError("ERR_EXPERT_WINDOW_OVERLAP",
                           "the reserved window overlaps another brief of this expert")
    anchor = timeutil.week_anchor(brief["review_window_start"])
    committed = gov.expert_week_committed_hours(expert["id"], anchor,
                                               exclude_brief_id=brief["id"])
    if committed + brief["sme_reserved_hours"] > expert["weekly_capacity_hours"]:
        raise ApiError("ERR_EXPERT_CAPACITY_EXCEEDED",
                       "the expert has no weekly capacity left for this brief")

    brief["sme_expert_id"] = expert["id"]
    brief["state"] = "SME_ASSIGNED"
    touch(brief)
    gov.recompute_expert_hours(expert)
    touch(expert)
    return envelope.ok(serialize.brief(brief))


@bp.post("/editorial/briefs/<bid>/approve")
@endpoint(ROLE_SME)
def approve_brief(bid):
    brief = gov.get_brief(bid)
    _require_assigned_expert(brief)
    if brief["state"] != "SME_ASSIGNED":
        raise ApiError("ERR_BRIEF_STATE_INVALID", "brief is not in SME_ASSIGNED")
    expert = store.experts.get(brief["sme_expert_id"])
    if expert is None or expert["status"] != "AVAILABLE":
        raise ApiError("ERR_EXPERT_UNAVAILABLE", "expert is not AVAILABLE")
    brief["state"] = "APPROVED"
    touch(brief)
    gov.recompute_expert_hours(expert)
    return envelope.ok(serialize.brief(brief))


@bp.post("/editorial/briefs/<bid>/request-changes")
@endpoint(ROLE_SME)
def request_brief_changes(bid):
    brief = gov.get_brief(bid)
    body = v.body()
    v.v_str(body, "notes", required=False, minlen=0, maxlen=2000)
    _require_assigned_expert(brief)
    if brief["state"] not in ("SME_ASSIGNED", "APPROVED"):
        raise ApiError("ERR_BRIEF_STATE_INVALID",
                       "brief is in neither SME_ASSIGNED nor APPROVED")

    # Step 1.
    expert_id = brief["sme_expert_id"]
    brief["state"] = "DRAFT"
    brief["sme_expert_id"] = None
    touch(brief)
    # Step 2 -- recompute the detached expert's ledger.
    expert = store.experts.get(expert_id)
    if expert is not None:
        gov.recompute_expert_hours(expert)
    # Step 3 -- push the content back.
    disturbed = []
    for item in sorted(gov.items_of_brief(brief["id"]),
                       key=lambda r: (r["created_at"], r["id"])):
        if item["workflow_state"] in ("IN_REVIEW", "READY"):
            item["workflow_state"] = "CHANGES_REQUESTED"
            touch(item)
            disturbed.append(item)
    # Step 4 -- void the pending gates of those items.
    for item in disturbed:
        gov.void_gates(item, only_pending=True)
    # Step 5.
    gov.reconcile_campaign(store.campaigns[brief["campaign_id"]])
    return envelope.ok(serialize.brief(brief))


@bp.get("/editorial/briefs")
@endpoint(*ALL_REVIEWERS_AND_SME)
def list_briefs():
    rows = listing.apply_filters(list(store.briefs.values()), [
        ("campaign_id", "campaign_id"),
        ("sme_expert_id", "sme_expert_id"),
        ("state", "state"),
        ("funnel_stage", "funnel_stage"),
    ])
    rows = listing.sort_default(rows)
    window, pagination = envelope.page(rows)
    return envelope.ok_list([serialize.brief(r) for r in window], pagination)


@bp.get("/editorial/briefs/<bid>")
@endpoint(*ALL_REVIEWERS_AND_SME)
def read_brief(bid):
    return envelope.ok(serialize.brief(gov.get_brief(bid)))
