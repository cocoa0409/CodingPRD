"""Advocacy campaigns and member mobilization events."""

from flask import Blueprint, request

from auth import require_roles
from db import locked, mint, store
from serializers import campaign_view, mobilization_view
from services import (
    ALLOWED_AUDIENCE_KEYS,
    RESTRICTED_AUDIENCE_KEYS,
    audience_count,
    campaign_status,
)
from util import err, get_body, is_int, paginate, parse_date_strict, require_str, success_object

bp = Blueprint("campaigns", __name__)

CAMPAIGN_LEVELS = {"FEDERAL", "STATE"}
MOBILIZATION_CHANNELS = {"EMAIL", "PHONE", "MAIL"}
CAMPAIGN_ROLES = ("AdvocacyDirector", "PlatformAdmin")


@bp.post("/api/campaigns")
@locked
def create_campaign():
    require_roles("AdvocacyDirector")
    body = get_body()
    title = require_str(body, "title")
    level = body.get("level")
    if level is None or level not in CAMPAIGN_LEVELS:
        err("ERR_INVALID_REQUEST", 400, "level must be FEDERAL or STATE")
    issue_area = require_str(body, "issue_area")
    start_raw = body.get("start_date")
    end_raw = body.get("end_date")
    start = parse_date_strict(start_raw)
    end = parse_date_strict(end_raw)
    if start is None or end is None:
        err("ERR_INVALID_REQUEST", 400, "start_date and end_date are required ISO dates")
    if end < start:
        err("ERR_INVALID_REQUEST", 400, "end_date must be on or after start_date")
    state_code = body.get("state_code")
    if level == "STATE" and state_code is None:
        err("ERR_INVALID_REQUEST", 400, "state_code is required for STATE campaigns")
    if level == "FEDERAL" and state_code is not None:
        err("ERR_INVALID_REQUEST", 400, "state_code must be absent for FEDERAL campaigns")
    if state_code is not None and not isinstance(state_code, str):
        err("ERR_INVALID_REQUEST", 400, "state_code must be a string")
    sponsor_entity_id = body.get("sponsor_entity_id")
    if not isinstance(sponsor_entity_id, str):
        err("ERR_INVALID_REQUEST", 400, "sponsor_entity_id is required and must be a string")
    # Rung 6: sponsor existence.
    sponsor = store.entities.get(sponsor_entity_id)
    if sponsor is None:
        err("ERR_NOT_FOUND", 404, "Sponsor entity not found")
    # Rung 10: advocacy is a lobbying-arm activity.
    if sponsor["kind"] != "LOBBY_ARM":
        err("ERR_SPONSOR_KIND_INVALID", 422, "Campaign sponsor must be the LOBBY_ARM entity")
    campaign = mint(store.campaigns)
    campaign.update(
        {
            "title": title,
            "level": level,
            "state_code": state_code,
            "issue_area": issue_area,
            "start_date": start_raw,
            "end_date": end_raw,
            "sponsor_entity_id": sponsor_entity_id,
        }
    )
    return success_object(campaign_view(campaign), status=201)


@bp.get("/api/campaigns/<campaign_id>")
@locked
def get_campaign(campaign_id):
    require_roles(*CAMPAIGN_ROLES)
    campaign = store.campaigns.get(campaign_id)
    if campaign is None:
        err("ERR_NOT_FOUND", 404, "Campaign not found")
    return success_object(campaign_view(campaign))


@bp.get("/api/campaigns")
@locked
def list_campaigns():
    require_roles(*CAMPAIGN_ROLES)
    sponsor_filter = request.args.get("sponsor_entity_id")
    level_filter = request.args.get("level")
    status_filter = request.args.get("status")
    campaigns = sorted(store.campaigns.values(), key=lambda r: r["_seq"])
    if sponsor_filter is not None:
        campaigns = [c for c in campaigns if c["sponsor_entity_id"] == sponsor_filter]
    if level_filter is not None:
        campaigns = [c for c in campaigns if c["level"] == level_filter]
    if status_filter is not None:
        campaigns = [c for c in campaigns if campaign_status(c) == status_filter]
    return paginate([campaign_view(c) for c in campaigns])


@bp.post("/api/campaigns/<campaign_id>/mobilizations")
@locked
def create_mobilization(campaign_id):
    require_roles("AdvocacyDirector")
    body = get_body()
    channel = body.get("channel")
    if channel is None or channel not in MOBILIZATION_CHANNELS:
        err("ERR_INVALID_REQUEST", 400, "channel must be EMAIL, PHONE, or MAIL")
    spec = body.get("audience_spec")
    if spec is None or not isinstance(spec, dict):
        err("ERR_INVALID_REQUEST", 400, "audience_spec is required and must be an object")
    # Rung 5: unknown keys (that are not restricted benefit keys) are malformed.
    for key in spec:
        if key in RESTRICTED_AUDIENCE_KEYS:
            continue
        if key not in ALLOWED_AUDIENCE_KEYS:
            err("ERR_INVALID_REQUEST", 400, "Unknown audience_spec key: %s" % key)
    if "state_code" in spec and not isinstance(spec["state_code"], str):
        err("ERR_INVALID_REQUEST", 400, "audience_spec.state_code must be a string")
    if "min_age" in spec and not is_int(spec["min_age"]):
        err("ERR_INVALID_REQUEST", 400, "audience_spec.min_age must be an integer")
    # Rung 6: campaign existence.
    campaign = store.campaigns.get(campaign_id)
    if campaign is None:
        err("ERR_NOT_FOUND", 404, "Campaign not found")
    # Rung 9: the activity check precedes data-use screening.
    if campaign_status(campaign) != "ACTIVE":
        err("ERR_CAMPAIGN_NOT_ACTIVE", 409, "Campaign is not ACTIVE")
    # Rung 10: benefit-marketing keys are forbidden outright.
    for key in spec:
        if key in RESTRICTED_AUDIENCE_KEYS:
            err("ERR_DATA_USE_RESTRICTED", 422, "audience_spec key '%s' is forbidden benefit-marketing targeting" % key)
    count = audience_count(spec)
    mobilization = mint(store.mobilizations)
    mobilization.update(
        {
            "campaign_id": campaign_id,
            "channel": channel,
            "audience_spec": spec,
            "audience_count": count,
        }
    )
    return success_object(mobilization_view(mobilization), status=201)


@bp.get("/api/campaigns/<campaign_id>/mobilizations")
@locked
def list_mobilizations(campaign_id):
    require_roles(*CAMPAIGN_ROLES)
    if campaign_id not in store.campaigns:
        err("ERR_NOT_FOUND", 404, "Campaign not found")
    events = [
        m
        for m in sorted(store.mobilizations.values(), key=lambda r: r["_seq"])
        if m["campaign_id"] == campaign_id
    ]
    return paginate([mobilization_view(m) for m in events])
