"""Routes: clinical referrals and partner sites."""
from flask import Blueprint, request

import db
import services
from constants import SPECIALTIES
from errors import ApiError
from middleware import authenticate, require_role
from response import ok_object, ok_list
from validation import (
    get_body, req_str, req_enum, req_int, opt_bool, req_dt, opt_enum_list,
    pagination_params,
)

bp = Blueprint("referrals", __name__)


@bp.post("/veteran-services/referrals")
def create_referral():
    uid, role = authenticate()
    body = get_body()
    member_id = req_str(body, "member_id")
    region = req_str(body, "region")
    required_specialty = req_enum(body, "required_specialty", SPECIALTIES)
    treatment_start = req_dt(body, "treatment_start")
    treatment_end = req_dt(body, "treatment_end")
    if not treatment_end > treatment_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "treatment_end must be strictly after treatment_start", 400)
    coordination_consent = opt_bool(body, "coordination_consent", False)
    expected = req_int(body, "expected_member_version")
    require_role(role, ["IntakeCoordinator"])
    member = db.STORE["members"].get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "member does not exist", 404)
    # Priority 6: OCC on the parent member
    if expected != member["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_member_version does not match the member's current version", 412)
    # Priority 7: member must be VERIFIED
    if member["verification_status"] != "VERIFIED":
        raise ApiError("ERR_MEMBER_NOT_VERIFIED", "member is not VERIFIED", 409)
    # Priority 10: INTENSIVE MENTAL_HEALTH enrollment gate
    intensive_ok = False
    for e in db.STORE["enrollments"].values():
        if e["member_id"] != member_id or e["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if e["intensity_tier"] != "INTENSIVE":
            continue
        track = db.STORE["program_tracks"].get(e["program_track_id"])
        if track is not None and track["track_code"] == "MENTAL_HEALTH":
            intensive_ok = True
            break
    if not intensive_ok:
        raise ApiError("ERR_INTENSITY_TIER_INSUFFICIENT",
                       "no MENTAL_HEALTH enrollment in ACTIVE/SUSPENDED with INTENSIVE tier", 409)
    # Priority 10: duplication avoidance on the MENTAL_HEALTH category
    if not coordination_consent and services.has_active_external_record(member_id, "MENTAL_HEALTH"):
        raise ApiError("ERR_EXTERNAL_SERVICE_CONFLICT",
                       "an ACTIVE MENTAL_HEALTH external service record exists", 409)
    # Priority 12: buffered closed-interval treatment-window conflict
    if services.treatment_window_conflict(member_id, treatment_start, treatment_end):
        raise ApiError("ERR_TREATMENT_WINDOW_CONFLICT",
                       "the treatment window overlaps another non-terminal referral", 409)
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "member_id": member_id, "partner_site_id": None, "region": region,
        "required_specialty": required_specialty,
        "treatment_start": treatment_start, "treatment_end": treatment_end,
        "coordination_consent": coordination_consent,
        "request_seq": db.next_referral_seq(),
        "status": "PENDING_MATCH",
        "matched_at": None, "admitted_at": None, "discharged_at": None,
    }
    services.stamp_new(rec)
    db.STORE["referrals"][rec["id"]] = rec
    # Cascade: supersede the member's existing PENDING_MATCH referral(s)
    for r in db.STORE["referrals"].values():
        if (r["id"] != rec["id"] and r["member_id"] == member_id
                and r["status"] == "PENDING_MATCH"):
            r["status"] = "SUPERSEDED"
            services.bump(r)
    services.bump(member)
    # Selector runs at creation
    site = services.select_site(rec)
    if site is not None:
        services.apply_match(rec, site)
        services.bump(site)
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/referrals")
def list_referrals():
    uid, role = authenticate()
    limit, offset = pagination_params()
    require_role(role, ["IntakeCoordinator", "ClinicalPartner"])
    member_id = request.args.get("member_id")
    partner_site_id = request.args.get("partner_site_id")
    status = request.args.get("status")
    items = [r for r in db.STORE["referrals"].values()
             if (member_id is None or r["member_id"] == member_id)
             and (partner_site_id is None or r["partner_site_id"] == partner_site_id)
             and (status is None or r["status"] == status)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([services.serialize(r) for r in page], limit, offset, total)


@bp.get("/veteran-services/referrals/<referral_id>")
def get_referral(referral_id):
    uid, role = authenticate()
    require_role(role, ["IntakeCoordinator", "ClinicalPartner"])
    rec = db.STORE["referrals"].get(referral_id)
    if rec is None:
        raise ApiError("ERR_REFERRAL_NOT_FOUND", "referral does not exist", 404)
    return ok_object(services.serialize(rec))


@bp.post("/veteran-services/referrals/<referral_id>/transition")
def transition_referral(referral_id):
    uid, role = authenticate()
    body = get_body()
    action = req_enum(body, "action", ("ADMIT", "DISCHARGE"))
    require_role(role, ["ClinicalPartner"])
    ref = db.STORE["referrals"].get(referral_id)
    if ref is None:
        raise ApiError("ERR_REFERRAL_NOT_FOUND", "referral does not exist", 404)
    # Priority 5: entity-backed ownership; a null partner_site_id falls through
    # to the state checks below.
    if ref["partner_site_id"] is not None and ref["partner_site_id"] != uid:
        raise ApiError("ERR_RESOURCE_NOT_OWNED",
                       "the referral is matched to a different partner site", 403)
    if action == "ADMIT":
        if ref["status"] != "MATCHED":
            raise ApiError("ERR_INVALID_STATE", "referral is not MATCHED", 409)
        ref["status"] = "IN_TREATMENT"
        ref["admitted_at"] = db.now()
        services.bump(ref)
        return ok_object(services.serialize(ref))
    # DISCHARGE
    if ref["status"] != "IN_TREATMENT":
        raise ApiError("ERR_INVALID_STATE", "referral is not IN_TREATMENT", 409)
    ref["status"] = "DISCHARGED"
    ref["discharged_at"] = db.now()
    services.bump(ref)
    site = db.STORE["partner_sites"].get(ref["partner_site_id"])
    if site is not None:
        site["current_census"] -= 1
        # The freed slot is offered to the eligible PENDING_MATCH referral with
        # the smallest request_seq for this site's region and specialties.
        eligible = [r for r in db.STORE["referrals"].values()
                    if r["status"] == "PENDING_MATCH"
                    and r["region"] == site["region"]
                    and r["required_specialty"] in site["specialties"]]
        eligible.sort(key=lambda r: r["request_seq"])
        if eligible:
            target = eligible[0]
            services.apply_match(target, site)
            services.bump(target)
        services.bump(site)
    return ok_object(services.serialize(ref))


# ---------------------------------------------------------------------------
# Partner sites
# ---------------------------------------------------------------------------

@bp.post("/veteran-services/partner-sites")
def create_partner_site():
    uid, role = authenticate()
    body = get_body()
    name = req_str(body, "name")
    region = req_str(body, "region")
    specialties = opt_enum_list(body, "specialties", SPECIALTIES)
    if not specialties:
        raise ApiError("ERR_INVALID_REQUEST",
                       "specialties must be a non-empty subset of the declared values", 400)
    capacity = req_int(body, "capacity", minimum=1)
    require_role(role, ["PlatformAdmin"])
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "name": name, "region": region, "specialties": specialties,
        "capacity": capacity, "current_census": 0,
    }
    services.stamp_new(rec)
    db.STORE["partner_sites"][rec["id"]] = rec
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/partner-sites")
def list_partner_sites():
    uid, role = authenticate()
    limit, offset = pagination_params()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "ClinicalPartner"])
    region = request.args.get("region")
    specialty = request.args.get("specialty")
    items = [s for s in db.STORE["partner_sites"].values()
             if (region is None or s["region"] == region)
             and (specialty is None or specialty in s["specialties"])]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([services.serialize(s) for s in page], limit, offset, total)
