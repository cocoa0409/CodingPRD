"""Social needs, community resources and the referral closed loop."""
from flask import Blueprint, request

import core
import domain
import http_util as h
import serializers as S
from core import clock, db, trunc_toward_zero
from decimal import Decimal
from errors import ApiError

bp = Blueprint("social", __name__)

ALL_READ = ["ProgramAdmin", "CareManager", "ClinicalReviewer", "UtilizationAnalyst"]
READ_WITH_PARTNER = ALL_READ + ["CommunityPartner"]


# --------------------------------------------------------------------------
# Social needs
# --------------------------------------------------------------------------
@bp.post("/social-needs")
def create_social_need():
    h.authenticate(["CareManager"])
    data = h.body()
    enrollment_id = h.req_str(data, "enrollment_id")
    need_domain = h.req_enum(data, "domain", core.SOCIAL_DOMAINS)
    severity = h.req_enum(data, "severity", core.SEVERITIES)
    enrollment = domain.get_enrollment(enrollment_id)

    rec = domain.base_record()
    rec.update({
        "enrollment_id": enrollment["id"],
        "domain": need_domain,
        "severity": severity,
        "status": "IDENTIFIED",
        "escalation_count": 0,
        "identified_at": clock.now(),
        "resolved_at": None,
    })
    db.social_needs[rec["id"]] = rec
    return h.ok(S.social_need_out(rec), 201)


@bp.get("/social-needs/<need_id>")
def read_social_need(need_id):
    h.authenticate(ALL_READ)
    rec = domain.get_social_need(need_id)
    return h.ok(S.social_need_out(rec))


@bp.get("/social-needs")
def list_social_needs():
    h.authenticate(ALL_READ)
    limit, offset = h.pagination()
    rows = list(db.social_needs.values())
    for field in ("enrollment_id", "domain", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows = domain.sorted_rows(rows)
    page, total = h.paginate(rows, limit, offset)
    return h.ok_list([S.social_need_out(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Community resources
# --------------------------------------------------------------------------
@bp.post("/community-resources")
def create_community_resource():
    h.authenticate(["ProgramAdmin"])
    data = h.body()
    name = h.req_str(data, "name")
    served = h.req_str_array(data, "served_domains", allowed=core.SOCIAL_DOMAINS)
    states = h.req_str_array(data, "service_state_codes", item_check=h.is_state_code)
    capacity = h.req_int(data, "concurrent_slot_capacity", minimum=1)
    contract = h.opt_enum(data, "contract_status", core.CONTRACT_STATUSES,
                          default="CONTRACTED")

    rec = domain.base_record()
    rec.update({
        "name": name,
        "served_domains": served,
        "service_state_codes": states,
        "contract_status": contract,
        "concurrent_slot_capacity": capacity,
        "open_referral_count": 0,
        "closed_loop_count": 0,
    })
    db.community_resources[rec["id"]] = rec
    return h.ok(S.community_resource_out(rec), 201)


@bp.get("/community-resources/<resource_id>")
def read_community_resource(resource_id):
    h.authenticate(READ_WITH_PARTNER)
    rec = domain.get_community_resource(resource_id)
    return h.ok(S.community_resource_out(rec))


# --------------------------------------------------------------------------
# Referrals
# --------------------------------------------------------------------------
def _resource_referrals(resource_id):
    return [r for r in db.referrals.values()
            if r["community_resource_id"] == resource_id]


@bp.post("/referrals")
def create_referral():
    user_id, _role = h.authenticate(["CareManager"])
    data = h.body()
    need_id = h.req_str(data, "social_need_id")
    resource_id = h.req_str(data, "community_resource_id")
    start_at = h.req_instant(data, "service_start_at")
    end_at = h.req_instant(data, "service_end_at")

    # ladder step 6 - body references, in input order
    need = domain.get_social_need(need_id)
    resource = domain.get_community_resource(resource_id)

    # ladder step 9 - source state
    if need["status"] not in ("IDENTIFIED", "UNMET_ESCALATED"):
        raise ApiError("ERR_SOCIAL_NEED_NOT_REFERABLE")

    enrollment = db.enrollments.get(need["enrollment_id"])
    member = db.members.get(enrollment["member_id"]) if enrollment else None

    # ladder step 12 - consent
    if member is None or member["social_data_consent_status"] != "GRANTED":
        raise ApiError("ERR_CONSENT_NOT_GRANTED")

    # ladder step 13 - temporal rules
    if not end_at > start_at:
        raise ApiError("ERR_SERVICE_WINDOW_INVALID")
    if start_at < clock.now():
        raise ApiError("ERR_SERVICE_WINDOW_IN_PAST")

    # ladder step 14 - referential business rules
    if resource["contract_status"] != "CONTRACTED":
        raise ApiError("ERR_RESOURCE_NOT_CONTRACTED")
    if (need["domain"] not in resource["served_domains"]
            or member["state_code"] not in resource["service_state_codes"]):
        raise ApiError("ERR_RESOURCE_DOMAIN_MISMATCH")

    # ladder step 15 - uniqueness then aggregate capacity
    for existing in db.referrals.values():
        if (existing["social_need_id"] == need["id"]
                and existing["status"] in ("SENT", "ACCEPTED")):
            raise ApiError("ERR_DUPLICATE_OPEN_REFERRAL")

    occupants = [r for r in _resource_referrals(resource["id"])
                 if r["status"] in ("SENT", "ACCEPTED")]
    probes = [start_at]
    for occupant in occupants:
        if start_at < occupant["service_start_at"] < end_at:
            probes.append(occupant["service_start_at"])
    for probe in probes:
        concurrent = 1 + sum(
            1 for o in occupants
            if o["service_start_at"] <= probe < o["service_end_at"])
        if concurrent > resource["concurrent_slot_capacity"]:
            raise ApiError("ERR_RESOURCE_CAPACITY_EXCEEDED")

    now = clock.now()
    rec = domain.base_record()
    rec.update({
        "social_need_id": need["id"],
        "community_resource_id": resource["id"],
        "sent_by_care_manager_id": user_id,
        "status": "SENT",
        "service_start_at": start_at,
        "service_end_at": end_at,
        "sent_at": now,
        "decision_at": None,
        "decline_reason": None,
        "outcome_note": None,
        "closed_at": None,
        "loop_closure_hours": None,
    })
    db.referrals[rec["id"]] = rec
    resource["open_referral_count"] += 1
    domain.touch_record(resource)
    need["status"] = "REFERRED"
    domain.touch_record(need)
    return h.ok(S.referral_out(rec), 201)


@bp.get("/referrals/<referral_id>")
def read_referral(referral_id):
    h.authenticate(READ_WITH_PARTNER)
    rec = domain.get_referral(referral_id)
    return h.ok(S.referral_out(rec))


@bp.get("/referrals")
def list_referrals():
    h.authenticate(READ_WITH_PARTNER)
    limit, offset = h.pagination()
    rows = list(db.referrals.values())
    for field in ("social_need_id", "community_resource_id",
                  "sent_by_care_manager_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows = domain.sorted_rows(rows)
    page, total = h.paginate(rows, limit, offset)
    return h.ok_list([S.referral_out(r) for r in page], limit, offset, total)


@bp.post("/referrals/<referral_id>/decision")
def decide_referral(referral_id):
    user_id, _role = h.authenticate(["CommunityPartner"])
    data = h.body()
    decision = h.req_enum(data, "decision", core.DECISIONS)
    decline_reason = h.opt_str(data, "decline_reason")
    if decision == "DECLINE" and (decline_reason is None or not decline_reason.strip()):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'decline_reason' is required on a DECLINE decision.")

    referral = domain.get_referral(referral_id)
    # ladder step 7 - ownership
    if user_id != referral["community_resource_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    # ladder step 9 - source state
    if referral["status"] != "SENT":
        raise ApiError("ERR_REFERRAL_NOT_SENT")

    resource = db.community_resources.get(referral["community_resource_id"])
    referral["decision_at"] = clock.now()
    if decision == "ACCEPT":
        referral["status"] = "ACCEPTED"
    else:
        referral["status"] = "DECLINED"
        referral["decline_reason"] = decline_reason
        if resource is not None:
            resource["open_referral_count"] = max(0, resource["open_referral_count"] - 1)
            domain.touch_record(resource)
    domain.touch_record(referral)
    return h.ok(S.referral_out(referral))


@bp.post("/referrals/<referral_id>/close-loop")
def close_referral_loop(referral_id):
    user_id, role = h.authenticate(["CommunityPartner", "CareManager"])
    data = h.body()
    resolution = h.req_enum(data, "resolution", core.RESOLUTIONS)
    outcome_note = h.req_str(data, "outcome_note")

    referral = domain.get_referral(referral_id)
    # ladder step 7 - ownership (CommunityPartner only)
    if role == "CommunityPartner" and user_id != referral["community_resource_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    # ladder step 9 - source state: only the three declared closures exist
    status = referral["status"]
    closable = (status == "ACCEPTED"
                or (status == "DECLINED" and resolution == "SERVICE_NOT_DELIVERED"))
    if not closable:
        raise ApiError("ERR_REFERRAL_LOOP_NOT_CLOSABLE")

    now = clock.now()
    resource = db.community_resources.get(referral["community_resource_id"])
    referral["closed_at"] = now
    referral["outcome_note"] = outcome_note
    elapsed = (now - referral["sent_at"]).total_seconds()
    referral["loop_closure_hours"] = trunc_toward_zero(
        Decimal(str(elapsed)) / Decimal(3600))

    if resolution == "SERVICE_DELIVERED":
        referral["status"] = "CLOSED_MET"
    else:
        referral["status"] = "CLOSED_UNMET"

    if resource is not None:
        if status == "ACCEPTED":
            resource["open_referral_count"] = max(0, resource["open_referral_count"] - 1)
        resource["closed_loop_count"] += 1
        domain.touch_record(resource)

    need = db.social_needs.get(referral["social_need_id"])
    if need is not None and need["status"] == "REFERRED":
        if resolution == "SERVICE_DELIVERED":
            domain.resolve_social_need(need)
        else:
            domain.escalate_social_need(need)

    domain.touch_record(referral)
    return h.ok(S.referral_out(referral))
