"""Field campaigns: declare, announce (big cascade), execute, close (PRD §3.8)."""
from flask import Blueprint

import calculations
import cascade
import clock
import store
from errors import ApiError
from rbac import auth, ANY
from validators import (
    body, f_str, f_int, f_num, f_enum, get_or_404,
    envelope_ok, new_entity, touch, ser,
)

bp = Blueprint("campaigns", __name__)

CAMPAIGN_TYPES = ("RECALL", "SERVICE_CAMPAIGN")


def _campaign(cid):
    return get_or_404(store.campaigns, cid, "FieldCampaign")


def _recompute_rate(campaign):
    rate = calculations.completion_rate_dec(
        campaign["verified_unit_count"], campaign["notified_unit_count"])
    campaign["completion_rate"] = float(rate)
    return rate


@bp.post("/emissions/field-campaigns")
def create_campaign():
    auth(("RegulatoryOfficer",))
    b = body()
    family_id = f_str(b, "engine_family_id")
    code = f_str(b, "campaign_code")
    ctype = f_enum(b, "campaign_type", CAMPAIGN_TYPES)
    defect = f_str(b, "defect_summary")
    remedy = f_str(b, "remedy_description")
    bay_days = f_int(b, "remedy_bay_days", min_v=1)
    threshold = f_num(b, "completion_threshold", required=False,
                      default=calculations.DEFAULT_COMPLETION_THRESHOLD)
    fam = get_or_404(store.families, family_id, "EngineFamily")
    # state gate (priority 7)
    if fam["certification_status"] not in ("CERTIFIED", "IN_PRODUCTION", "COMPLIANCE_HOLD"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Campaigns declare only against CERTIFIED, IN_PRODUCTION or COMPLIANCE_HOLD families")
    # uniqueness (priority 11): campaign code unique within the family
    for c in store.campaigns.values():
        if c["engine_family_id"] == family_id and c["campaign_code"] == code:
            raise ApiError("ERR_DUPLICATE_CAMPAIGN_CODE", 409,
                           "campaign_code already exists within the family")
    ent = new_entity()
    ent.update({
        "engine_family_id": family_id,
        "campaign_code": code,
        "campaign_type": ctype,
        "defect_summary": defect,
        "remedy_description": remedy,
        "remedy_bay_days": bay_days,
        "completion_threshold": threshold,
        "notified_unit_count": 0,
        "verified_unit_count": 0,
        "completion_rate": 0,
        "status": "DRAFT",
        "announced_at": None,
    })
    store.campaigns[ent["id"]] = ent
    return envelope_ok(ser(ent), 201)


@bp.get("/emissions/field-campaigns/<cid>")
def get_campaign(cid):
    auth(ANY)
    return envelope_ok(ser(_campaign(cid)), 200)


@bp.post("/emissions/field-campaigns/<cid>/announce")
def announce_campaign(cid):
    auth(("RegulatoryOfficer",))
    campaign = _campaign(cid)
    if campaign["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "announce requires DRAFT")
    fam = store.families.get(campaign["engine_family_id"])
    if fam is None or fam["certification_status"] not in ("CERTIFIED", "IN_PRODUCTION"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "announce requires the family CERTIFIED or IN_PRODUCTION")
    # referential (priority 10): RECALL requires NON_CONFORMING latest in-use status
    if (campaign["campaign_type"] == "RECALL"
            and fam["in_use_compliance_status"] != "NON_CONFORMING"):
        raise ApiError("ERR_RECALL_REQUIRES_NON_CONFORMANCE", 409,
                       "A RECALL requires the family's latest in-use status NON_CONFORMING")
    # hop 1: family -> COMPLIANCE_HOLD
    fam["certification_status"] = "COMPLIANCE_HOLD"
    touch(fam)
    # hop 2: fleet notification — in-service units not already open are flagged
    notified = 0
    for u in store.units.values():
        if (u["engine_family_id"] == fam["id"]
                and u["lifecycle"] == "IN_SERVICE"
                and u["campaign_compliance"] != "CAMPAIGN_OPEN"):
            u["campaign_compliance"] = "CAMPAIGN_OPEN"
            touch(u)
            notified += 1
    campaign["notified_unit_count"] = notified
    campaign["announced_at"] = clock.now_dt()
    campaign["status"] = "ANNOUNCED"
    touch(campaign)
    return envelope_ok(ser(campaign), 200)


@bp.post("/emissions/field-campaigns/<cid>/begin-execution")
def begin_execution(cid):
    auth(("RegulatoryOfficer",))
    campaign = _campaign(cid)
    if campaign["status"] != "ANNOUNCED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "begin-execution requires ANNOUNCED")
    if campaign["notified_unit_count"] <= 0:
        raise ApiError("ERR_CAMPAIGN_HAS_NO_UNITS", 409,
                       "The campaign notified no units")
    campaign["status"] = "IN_PROGRESS"
    touch(campaign)
    return envelope_ok(ser(campaign), 200)


@bp.post("/emissions/field-campaigns/<cid>/completion-review")
def completion_review(cid):
    auth(("RegulatoryOfficer",))
    campaign = _campaign(cid)
    if campaign["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "completion-review requires IN_PROGRESS")
    rate = _recompute_rate(campaign)
    campaign["status"] = "COMPLETION_REVIEW"
    touch(campaign)
    # rate at/above threshold (inclusive) closes the campaign in the same request
    if (campaign["notified_unit_count"] > 0
            and rate >= calculations.D(campaign["completion_threshold"])):
        cascade.close_campaign(campaign)
    return envelope_ok(ser(campaign), 200)


@bp.post("/emissions/field-campaigns/<cid>/resume-execution")
def resume_execution(cid):
    auth(("RegulatoryOfficer",))
    campaign = _campaign(cid)
    if campaign["status"] != "COMPLETION_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "resume-execution requires COMPLETION_REVIEW")
    campaign["status"] = "IN_PROGRESS"
    touch(campaign)
    return envelope_ok(ser(campaign), 200)
