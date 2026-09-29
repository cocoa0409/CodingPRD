"""Content-item endpoints (PRD sections 3.4-3.10)."""

from datetime import timedelta

from flask import Blueprint, g

import calc
import envelope
import governance as gov
import listing
import serialize
import timeutil
import validate as v
from auth import (ALL_REVIEWERS, ALL_REVIEWERS_AND_SME, EVERY_ROLE, ROLE_ANALYTICS,
                  ROLE_LEGAL, ROLE_MANAGING_EDITOR, endpoint)
from errors import ApiError
from store import store, touch, new_row

bp = Blueprint("items", __name__)


def slot_week_bounds(slot):
    start = timeutil.day_start(slot["week_start_date"])
    return start, start + timedelta(days=7)


def promotion_window(item):
    start = item["planned_publish_at"]
    return start, start + timedelta(days=item["promotion_window_days"])


@bp.post("/editorial/content-items")
@endpoint(ROLE_MANAGING_EDITOR)
def create_item():
    body = v.body()
    brief_id = v.v_str(body, "brief_id")
    slot_id = v.v_str(body, "slot_id")
    title = v.v_str(body, "title", minlen=1, maxlen=160)
    planned_publish_at = v.v_instant(body, "planned_publish_at")
    expected = v.v_int(body, "expected_campaign_version")
    window_days = v.v_int(body, "promotion_window_days", required=False,
                          minimum=1, maximum=7, default=3)
    meta_description = v.v_str(body, "meta_description", required=False,
                               minlen=1, maxlen=200)
    url_slug = v.v_str(body, "url_slug", required=False, minlen=1, maxlen=80,
                       pattern=v.SLUG_RE)
    tags = v.v_str_list(body, "tags", required=False, min_items=0,
                        item_min=1, item_max=40, lowercase=True, default=[])

    # Ladder rule 8 -- one content item per brief.
    for other in store.items.values():
        if other["brief_id"] == brief_id and other["workflow_state"] != "PRUNED":
            raise ApiError("ERR_BRIEF_ALREADY_HAS_ITEM",
                           "the brief already carries a content item")

    brief = gov.get_brief(brief_id)
    slot = gov.get_slot(slot_id)
    campaign = store.campaigns[brief["campaign_id"]]

    if expected != campaign["version"]:
        raise ApiError("ERR_STALE_CAMPAIGN_VERSION",
                       "expected_campaign_version does not match the campaign")

    if brief["state"] != "APPROVED":
        raise ApiError("ERR_BRIEF_NOT_APPROVED", "brief is not APPROVED")
    if campaign["status"] != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID", "campaign is not ACTIVE")
    if slot["status"] == "LOCKED":
        raise ApiError("ERR_SLOT_LOCKED", "calendar slot is LOCKED")
    if (slot["campaign_id"] != brief["campaign_id"]
            or slot["funnel_stage"] != brief["funnel_stage"]):
        raise ApiError("ERR_SLOT_CAMPAIGN_MISMATCH",
                       "slot does not match the brief's campaign and funnel stage")
    gov.require_not_frozen(campaign)

    week_start, week_end = slot_week_bounds(slot)
    if not (week_start <= planned_publish_at < week_end):
        raise ApiError("ERR_PUBLISH_OUTSIDE_SLOT_WEEK",
                       "planned_publish_at falls outside the slot week")
    if slot["status"] == "FULL":
        raise ApiError("ERR_SLOT_CAPACITY_EXCEEDED", "calendar slot is FULL")

    # The pinned seven-step capacity commitment.
    pre_utilization = calc.utilization_pct(slot["committed_points"],
                                           slot["capacity_points"])
    tier = calc.capacity_tier(pre_utilization)
    surcharge = calc.TIER_SURCHARGE[tier]
    commit_points = brief["effort_points"] + surcharge
    projected = slot["committed_points"] + commit_points
    if projected > slot["capacity_points"]:
        raise ApiError("ERR_SLOT_CAPACITY_EXCEEDED",
                       "the slot cannot absorb this commitment")

    slot["committed_points"] = projected
    slot["utilization_pct"] = calc.utilization_pct(projected, slot["capacity_points"])
    slot["status"] = "FULL" if projected == slot["capacity_points"] else "OPEN"
    touch(slot)

    row = new_row("items", {
        "brief_id": brief["id"],
        "slot_id": slot["id"],
        "campaign_id": brief["campaign_id"],
        "title": title,
        "planned_publish_at": planned_publish_at,
        "promotion_window_days": window_days,
        "effort_points": brief["effort_points"],
        "commit_points": commit_points,
        "capacity_tier_at_commit": tier,
        "workflow_state": "DRAFT",
        "revision_number": 1,
        "created_by_user_id": g.user_id,
        "published_by_user_id": None,
        "published_at": None,
        "retracted_at": None,
        "meta_description": meta_description,
        "url_slug": url_slug,
        "tags": tags,
        "accuracy_status": "UNVERIFIED",
        "last_audit_type": None,
        "last_audit_verdict": None,
        "last_audit_at": None,
        "engaged_sessions_total": 0,
        "conversions_total": 0,
        "last_touch_pipeline_cents": 0,
        "assisted_pipeline_cents": 0,
        "decay_pct": calc.ZERO2,
        "refresh_required": False,
    })
    store.items[row["id"]] = row
    gov.reconcile_campaign(campaign)
    return envelope.created(serialize.item(row))


@bp.post("/editorial/content-items/<iid>/submit-for-review")
@endpoint(ROLE_MANAGING_EDITOR)
def submit_for_review(iid):
    item = gov.get_item(iid)
    if item["workflow_state"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_ITEM_STATE_INVALID",
                       "item is in neither DRAFT nor CHANGES_REQUESTED")
    brief = gov.brief_of_item(item)
    if brief["state"] != "APPROVED":
        raise ApiError("ERR_BRIEF_NOT_APPROVED", "brief is not APPROVED")
    campaign = gov.campaign_of_item(item)
    gov.require_not_frozen(campaign)

    first_pass = item["workflow_state"] == "DRAFT"
    has_claims = len(gov.claims_of_item(item["id"])) > 0
    item["workflow_state"] = "IN_REVIEW"
    touch(item)

    if first_pass:
        for gate_type in gov.GATE_ORDER:
            if gate_type == "LEGAL" and not has_claims:
                continue
            gov.open_gate(item, gate_type)
    else:
        existing = gov.sort_gates(gov.gates_of_item(item["id"]))
        for gate in existing:
            if gate["state"] in ("CHANGES_REQUESTED", "VOIDED"):
                gov.reopen_gate(item, gate)
        if has_claims and not any(gt["gate_type"] == "LEGAL" for gt in existing):
            gov.open_gate(item, "LEGAL")

    gov.reconcile_campaign(campaign)
    return envelope.ok(serialize.item(item))


@bp.post("/editorial/content-items/<iid>/claims")
@endpoint(ROLE_MANAGING_EDITOR)
def attach_claim(iid):
    item = gov.get_item(iid)
    body = v.body()
    claim_text = v.v_str(body, "claim_text", minlen=10, maxlen=400)
    claim_type = v.v_enum(body, "claim_type", v.CLAIM_TYPES)

    brief = gov.brief_of_item(item)
    if claim_type == "REGULATED" and not brief["requires_regulated_review"]:
        raise ApiError("ERR_REGULATED_REVIEW_REQUIRED",
                       "the brief behind this item does not carry regulated review")

    row = new_row("claims", {
        "content_item_id": item["id"],
        "claim_text": claim_text,
        "claim_type": claim_type,
        "substantiation_state": "DRAFT",
        "scoring_variant": "STRICT_REGULATED" if claim_type == "REGULATED" else "STANDARD",
        "required_score": calc.REQUIRED_SCORE[claim_type],
        "evidence_score": calc.ZERO2,
        "evidence_valid_until": None,
        "decided_by_user_id": None,
        "decided_at": None,
    })
    store.claims[row["id"]] = row
    gov.reconcile_campaign(gov.campaign_of_item(item))
    return envelope.created(serialize.claim(row))


@bp.post("/editorial/content-items/<iid>/publish")
@endpoint(ROLE_MANAGING_EDITOR)
def publish_item(iid):
    item = gov.get_item(iid)
    body = v.body()
    scheduled_at = v.v_instant(body, "scheduled_at")
    channels = v.v_enum_list(body, "channels", v.CHANNELS, min_items=1, max_items=3)
    meta_description = v.v_str(body, "meta_description", required=False,
                               minlen=1, maxlen=200)
    url_slug = v.v_str(body, "url_slug", required=False, minlen=1, maxlen=80,
                       pattern=v.SLUG_RE)
    tags = v.v_str_list(body, "tags", required=False, min_items=0,
                        item_min=1, item_max=40, lowercase=True)

    if meta_description is None:
        meta_description = item["meta_description"]
    if url_slug is None:
        url_slug = item["url_slug"]
    if tags is None:
        tags = list(item["tags"])

    # Ladder rule 7 -- slug uniqueness across items that are not PRUNED.
    if url_slug is not None:
        for other in store.items.values():
            if other["id"] == item["id"] or other["workflow_state"] == "PRUNED":
                continue
            if other["url_slug"] == url_slug:
                raise ApiError("ERR_URL_SLUG_DUPLICATE",
                               "another content item already holds that url_slug")
    # Ladder rule 13 -- publication segregation of duties.
    if g.user_id == item["created_by_user_id"]:
        raise ApiError("ERR_SOD_PUBLISH_CONFLICT",
                       "the creator of a piece may not publish it")
    # Ladder rule 15.
    if item["workflow_state"] != "READY":
        raise ApiError("ERR_ITEM_STATE_INVALID", "item is not READY")
    campaign = gov.campaign_of_item(item)
    # Ladder rule 22 -- a RESTRICTED campaign may still publish.
    gov.require_not_frozen(campaign)
    # Ladder rule 24.
    for claim in gov.claims_of_item(item["id"]):
        if claim["substantiation_state"] != "SUBSTANTIATED" \
                or claim["evidence_valid_until"] is None \
                or claim["evidence_valid_until"] <= store.clock:
            raise ApiError("ERR_CLAIM_NOT_SUBSTANTIATED",
                           "every claim must be substantiated with live evidence")
    # Ladder rule 27 -- the accessibility floor.
    if (meta_description is None
            or len(meta_description) < calc.MIN_META_DESCRIPTION_CHARS
            or url_slug is None
            or len(tags) < calc.MIN_PUBLISH_TAGS):
        raise ApiError("ERR_ACCESSIBILITY_METADATA_MISSING",
                       "publication metadata does not meet the accessibility floor")
    # Ladder rule 33.
    active_usages = [u for u in gov.usages_of_item(item["id"])
                     if u["usage_state"] == "ACTIVE"]
    for usage in active_usages:
        asset = store.assets[usage["asset_id"]]
        if asset["license_end"] <= store.clock:
            raise ApiError("ERR_ASSET_RIGHTS_EXPIRED",
                           "an asset behind an active usage has lapsed")
    # Ladder rule 35.
    slot = store.slots[item["slot_id"]]
    week_start, week_end = slot_week_bounds(slot)
    if not (week_start <= scheduled_at < week_end):
        raise ApiError("ERR_PUBLISH_OUTSIDE_SLOT_WEEK",
                       "scheduled_at falls outside the slot week")
    # Ladder rule 37.
    for channel in channels:
        for usage in active_usages:
            asset = store.assets[usage["asset_id"]]
            if channel not in asset["licensed_channels"]:
                raise ApiError("ERR_ASSET_CHANNEL_NOT_LICENSED",
                               "an asset behind an active usage does not license "
                               + channel)

    item["workflow_state"] = "PUBLISHED"
    item["published_at"] = store.clock
    item["published_by_user_id"] = g.user_id
    item["meta_description"] = meta_description
    item["url_slug"] = url_slug
    item["tags"] = list(tags)
    touch(item)

    for channel in gov.CHANNEL_ORDER:
        if channel not in channels:
            continue
        live = scheduled_at <= store.clock
        row = new_row("distributions", {
            "content_item_id": item["id"],
            "channel": channel,
            "scheduled_at": scheduled_at,
            "state": "LIVE" if live else "SCHEDULED",
            "went_live_at": store.clock if live else None,
            "suppression_reason": None,
            "suppressed_at": None,
        })
        store.distributions[row["id"]] = row

    gov.reconcile_campaign(campaign)
    return envelope.ok(serialize.item(item))


@bp.post("/editorial/content-items/<iid>/retract")
@endpoint(ROLE_MANAGING_EDITOR)
def retract_item(iid):
    item = gov.get_item(iid)
    body = v.body()
    v.v_str(body, "reason", required=False, minlen=0, maxlen=2000)
    if item["workflow_state"] not in calc.PUBLISHED_LIKE:
        raise ApiError("ERR_ITEM_STATE_INVALID",
                       "item is in neither PUBLISHED nor NEEDS_REFRESH")

    # Step 1.
    item["workflow_state"] = "RETRACTED"
    item["retracted_at"] = store.clock
    touch(item)
    # Step 2.
    gov.retract_item_distributions(item)
    # Steps 3 and 4.
    gov.release_item_usages(item)
    # Step 5.  Retraction pointedly does not return the calendar commitment.
    gov.reconcile_campaign(gov.campaign_of_item(item))
    return envelope.ok(serialize.item(item))


@bp.post("/editorial/content-items/<iid>/audit")
@endpoint(ROLE_MANAGING_EDITOR)
def audit_item(iid):
    item = gov.get_item(iid)
    body = v.body()
    audit_type = v.v_enum(body, "audit_type", v.AUDIT_TYPES)
    finding = v.v_enum(body, "accuracy_finding", v.ACCURACY_FINDINGS,
                       required=(audit_type == "ACCURACY"))

    item["last_audit_type"] = audit_type
    item["last_audit_at"] = store.clock
    if audit_type == "DECAY":
        gov.recompute_decay(item)
        if item["decay_pct"] >= calc.PRUNE_DECAY_PCT:
            verdict = "PRUNE"
        elif item["refresh_required"]:
            verdict = "REFRESH"
        else:
            verdict = "KEEP"
    else:
        item["accuracy_status"] = finding
        gov.recompute_refresh_flag(item)
        verdict = "REFRESH" if finding == "INACCURATE" else "KEEP"
    item["last_audit_verdict"] = verdict
    if item["workflow_state"] == "PUBLISHED" and verdict in ("REFRESH", "PRUNE"):
        item["workflow_state"] = "NEEDS_REFRESH"
    touch(item)
    gov.reconcile_campaign(gov.campaign_of_item(item))
    return envelope.ok(serialize.item(item))


@bp.post("/editorial/content-items/<iid>/refresh")
@endpoint(ROLE_MANAGING_EDITOR)
def refresh_item(iid):
    item = gov.get_item(iid)
    if item["workflow_state"] not in calc.PUBLISHED_LIKE:
        raise ApiError("ERR_ITEM_STATE_INVALID",
                       "item is in neither PUBLISHED nor NEEDS_REFRESH")
    campaign = gov.campaign_of_item(item)
    if campaign["status"] != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID", "campaign is not ACTIVE")
    eligible = (item["workflow_state"] == "NEEDS_REFRESH"
                or (item["workflow_state"] == "PUBLISHED" and item["refresh_required"]))
    if not eligible:
        raise ApiError("ERR_REFRESH_NOT_REQUIRED", "this item does not need a refresh")
    gov.require_not_frozen(campaign)

    # Step 1.
    item["workflow_state"] = "DRAFT"
    item["revision_number"] = item["revision_number"] + 1
    item["published_at"] = None
    item["published_by_user_id"] = None
    item["retracted_at"] = None
    item["accuracy_status"] = "UNVERIFIED"
    item["last_audit_verdict"] = None
    item["refresh_required"] = False
    touch(item)
    # Step 2 -- a refresh voids every gate regardless of state.
    gov.void_gates(item, only_pending=False)
    # Step 3.
    gov.retract_item_distributions(item)
    # Step 4.
    gov.release_item_usages(item)
    # Step 5.  Refresh keeps the calendar commitment.
    gov.reconcile_campaign(campaign)
    return envelope.ok(serialize.item(item))


@bp.post("/editorial/content-items/<iid>/prune")
@endpoint(ROLE_MANAGING_EDITOR)
def prune_item(iid):
    item = gov.get_item(iid)
    if item["workflow_state"] not in ("PUBLISHED", "NEEDS_REFRESH", "RETRACTED"):
        raise ApiError("ERR_ITEM_STATE_INVALID",
                       "item cannot be pruned from its current state")
    if item["last_audit_verdict"] != "PRUNE":
        raise ApiError("ERR_PRUNE_NOT_ELIGIBLE",
                       "the last audit did not recommend a prune")

    # Step 1.
    item["workflow_state"] = "PRUNED"
    touch(item)
    # Step 2 -- return the capacity.
    slot = store.slots[item["slot_id"]]
    slot["committed_points"] = slot["committed_points"] - item["commit_points"]
    if slot["committed_points"] < 0:
        slot["committed_points"] = 0
    slot["utilization_pct"] = calc.utilization_pct(slot["committed_points"],
                                                   slot["capacity_points"])
    if slot["status"] == "FULL" and slot["committed_points"] < slot["capacity_points"]:
        slot["status"] = "OPEN"
    touch(slot)
    # Step 4.
    gov.retract_item_distributions(item)
    gov.release_item_usages(item)
    # Steps 3 and 5.
    gov.reconcile_campaign(gov.campaign_of_item(item))
    return envelope.ok(serialize.item(item))


def _separation(window_a, window_b):
    if window_a[1] <= window_b[0]:
        return window_b[0] - window_a[1]
    if window_b[1] <= window_a[0]:
        return window_a[0] - window_b[1]
    return timedelta(seconds=-1)


@bp.post("/editorial/content-items/<iid>/asset-usages")
@endpoint(ROLE_MANAGING_EDITOR)
def attach_usage(iid):
    item = gov.get_item(iid)
    body = v.body()
    asset_id = v.v_str(body, "asset_id")
    channel = v.v_enum(body, "channel", v.CHANNELS)

    asset = gov.get_asset(asset_id)
    mine = promotion_window(item)
    rivals = []
    for usage in gov.usages_of_asset(asset["id"]):
        if usage["usage_state"] != "ACTIVE" or usage["channel"] != channel:
            continue
        if usage["content_item_id"] == item["id"]:
            continue
        other = store.items.get(usage["content_item_id"])
        if other is not None:
            rivals.append(other)

    # Ladder rule 31 -- STOCK and ORIGINAL windows may touch but not overlap.
    if asset["asset_type"] in ("STOCK", "ORIGINAL"):
        for other in rivals:
            if timeutil.overlaps(mine[0], mine[1], *promotion_window(other)):
                raise ApiError("ERR_ASSET_USAGE_WINDOW_OVERLAP",
                               "the promotion window overlaps another usage of "
                               "this asset on this channel")
    # Ladder rule 32 -- TALENT demands at least 7 whole days of separation.
    if asset["asset_type"] == "TALENT":
        for other in rivals:
            if _separation(mine, promotion_window(other)) < timedelta(
                    days=calc.TALENT_EXCLUSIVITY_BUFFER_DAYS):
                raise ApiError("ERR_TALENT_EXCLUSIVITY_BUFFER",
                               "talent usages must be separated by at least "
                               "7 whole days")
    # Ladder rule 33.
    if asset["license_end"] <= store.clock:
        raise ApiError("ERR_ASSET_RIGHTS_EXPIRED", "the asset licence has lapsed")
    # Ladder rule 37.
    if channel not in asset["licensed_channels"]:
        raise ApiError("ERR_ASSET_CHANNEL_NOT_LICENSED",
                       "the asset does not license " + channel)
    # Ladder rule 39.
    if asset["remaining_licensed_uses"] < 1:
        raise ApiError("ERR_ASSET_USES_EXHAUSTED",
                       "the asset has no licensed uses left")

    row = new_row("usages", {
        "content_item_id": item["id"],
        "asset_id": asset["id"],
        "channel": channel,
        "usage_state": "ACTIVE",
        "attached_at": store.clock,
        "released_at": None,
    })
    store.usages[row["id"]] = row
    gov.refresh_asset_counts(asset)
    gov.reconcile_campaign(gov.campaign_of_item(item))
    return envelope.created(serialize.usage(row))


@bp.post("/editorial/content-items/<iid>/performance-snapshots")
@endpoint(ROLE_ANALYTICS)
def record_snapshot(iid):
    item = gov.get_item(iid)
    body = v.body()
    period_start = v.v_instant(body, "period_start")
    period_end = v.v_instant(body, "period_end")
    sessions = v.v_int(body, "engaged_sessions", minimum=0)
    conversions = v.v_int(body, "conversions", minimum=0)
    amount = v.v_int(body, "influenced_opportunity_amount_cents", minimum=0)
    touch_position = v.v_enum(body, "touch_position", v.TOUCH_POSITIONS)

    if period_end <= period_start:
        raise ApiError("ERR_SNAPSHOT_PERIOD_INVALID",
                       "period_end must be strictly after period_start")
    if period_end > store.clock:
        raise ApiError("ERR_SNAPSHOT_PERIOD_INVALID",
                       "period_end may not report the future")
    for other in gov.snapshots_of_item(item["id"]):
        if timeutil.overlaps(period_start, period_end,
                             other["period_start"], other["period_end"]):
            raise ApiError("ERR_SNAPSHOT_PERIOD_INVALID",
                           "the period overlaps another period on this item")

    row = new_row("snapshots", {
        "content_item_id": item["id"],
        "period_start": period_start,
        "period_end": period_end,
        "engaged_sessions": sessions,
        "conversions": conversions,
        "influenced_opportunity_amount_cents": amount,
        "touch_position": touch_position,
    })
    store.snapshots[row["id"]] = row
    gov.recompute_attribution(item)
    touch(item)
    return envelope.created(serialize.snapshot(row))


@bp.get("/editorial/content-items")
@endpoint(*EVERY_ROLE)
def list_items():
    rows = listing.apply_filters(list(store.items.values()), [
        ("campaign_id", "campaign_id"),
        ("brief_id", "brief_id"),
        ("slot_id", "slot_id"),
        ("workflow_state", "workflow_state"),
    ])
    rows = listing.sort_default(rows)
    window, pagination = envelope.page(rows)
    return envelope.ok_list([serialize.item(r) for r in window], pagination)


@bp.get("/editorial/content-items/<iid>")
@endpoint(*EVERY_ROLE)
def read_item(iid):
    return envelope.ok(serialize.item(gov.get_item(iid)))


@bp.get("/editorial/content-items/<iid>/review-gates")
@endpoint(*ALL_REVIEWERS_AND_SME)
def list_item_gates(iid):
    item = gov.get_item(iid)
    rows = listing.apply_filters(gov.gates_of_item(item["id"]),
                                 [("gate_type", "gate_type"), ("state", "state")])
    rows = gov.sort_gates(rows)
    window, pagination = envelope.page(rows)
    return envelope.ok_list([serialize.gate(r) for r in window], pagination)


@bp.get("/editorial/content-items/<iid>/claims")
@endpoint(*ALL_REVIEWERS_AND_SME)
def list_item_claims(iid):
    item = gov.get_item(iid)
    rows = listing.apply_filters(gov.claims_of_item(item["id"]), [
        ("claim_type", "claim_type"),
        ("substantiation_state", "substantiation_state"),
    ])
    rows = listing.sort_default(rows)
    window, pagination = envelope.page(rows)
    return envelope.ok_list([serialize.claim(r) for r in window], pagination)


@bp.get("/editorial/content-items/<iid>/distributions")
@endpoint(*ALL_REVIEWERS)
def list_item_distributions(iid):
    item = gov.get_item(iid)
    rows = listing.apply_filters(gov.distributions_of_item(item["id"]),
                                 [("channel", "channel"), ("state", "state")])
    rows = gov.sort_distributions(rows)
    window, pagination = envelope.page(rows)
    return envelope.ok_list([serialize.distribution(r) for r in window], pagination)


@bp.get("/editorial/content-items/<iid>/asset-usages")
@endpoint(*ALL_REVIEWERS)
def list_item_usages(iid):
    item = gov.get_item(iid)
    rows = listing.apply_filters(gov.usages_of_item(item["id"]),
                                 [("usage_state", "usage_state"),
                                  ("channel", "channel")])
    rows = listing.sort_by(rows, ["attached_at"])
    window, pagination = envelope.page(rows)
    return envelope.ok_list([serialize.usage(r) for r in window], pagination)


@bp.get("/editorial/content-items/<iid>/performance-snapshots")
@endpoint(ROLE_MANAGING_EDITOR, ROLE_ANALYTICS, ROLE_LEGAL)
def list_item_snapshots(iid):
    item = gov.get_item(iid)
    rows = listing.apply_filters(gov.snapshots_of_item(item["id"]),
                                 [("touch_position", "touch_position")])
    rows = listing.sort_by(rows, ["period_start"])
    window, pagination = envelope.page(rows)
    return envelope.ok_list([serialize.snapshot(r) for r in window], pagination)
