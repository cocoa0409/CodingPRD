"""Enrollment campaign endpoints."""
from flask import Blueprint, request

import clock
import db
import errors as E
import services
from middleware import require_role
from response import success_object
from serializers import enrollment_campaign, policy as policy_ser
from util import get_body, get_or_404, list_response, parse_iso

bp = Blueprint("enrollment_campaigns", __name__)

STORE = db.STORES["enrollment_campaigns"]


@bp.route("/enrollment-campaigns", methods=["POST"])
def create(role, user_id):
    require_role(role, {"CarrierAdmin", "BenefitCounselor"})
    body = get_body(["employer_group_id", "counselor_id", "window_start", "window_end"])
    group = db.STORES["employer_groups"].get(body["employer_group_id"])
    if group is None:
        raise E.err(E.ERR_REFERENTIAL_INTEGRITY, "employer_group_id does not exist")
    counselor = db.STORES["benefit_counselors"].get(body["counselor_id"])
    if counselor is None:
        raise E.err(E.ERR_REFERENTIAL_INTEGRITY, "counselor_id does not exist")
    ws = parse_iso(body["window_start"], "window_start")
    we = parse_iso(body["window_end"], "window_end")
    if we <= ws:
        raise E.err(E.ERR_INVALID_REQUEST, "window_end must be strictly after window_start")
    if counselor["status"] != "ACTIVE":
        raise E.err(E.ERR_COUNSELOR_INACTIVE, "Counselor is not ACTIVE")
    rec = db.stamp_created({
        "employer_group_id": body["employer_group_id"],
        "counselor_id": body["counselor_id"],
        "window_start": db.format_ts(ws),
        "window_end": db.format_ts(we),
        "guaranteed_issue": bool(body.get("guaranteed_issue", False)),
        "status": "DRAFT",
        "required_enrollments": None,
        "participation_met": None,
    })
    STORE[rec["id"]] = rec
    return success_object(enrollment_campaign(rec), status=201)


@bp.route("/enrollment-campaigns/<rid>", methods=["GET"])
def get_one(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "GroupAdmin", "BenefitCounselor"})
    rec = get_or_404(STORE, rid)
    return success_object(enrollment_campaign(rec))


@bp.route("/enrollment-campaigns", methods=["GET"])
def list_all(role, user_id):
    require_role(role, {"CarrierAdmin", "GroupAdmin", "BenefitCounselor"})
    filters = {
        "employer_group_id": request.args.get("employer_group_id"),
        "counselor_id": request.args.get("counselor_id"),
        "status": request.args.get("status"),
    }
    return list_response(STORE, filters, enrollment_campaign)


def _windows_overlap_halfopen(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap."""
    return a_start < b_end and b_start < a_end


def _windows_overlap_closed(a_start, a_end, b_start, b_end):
    """Closed [start, end] overlap."""
    return a_start <= b_end and b_start <= a_end


@bp.route("/enrollment-campaigns/<rid>/open", methods=["POST"])
def open_campaign(role, user_id, rid):
    require_role(role, {"BenefitCounselor"})
    rec = get_or_404(STORE, rid)
    if rec["status"] != "DRAFT":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot open from {rec['status']}")
    counselor = db.STORES["benefit_counselors"][rec["counselor_id"]]
    group = db.STORES["employer_groups"][rec["employer_group_id"]]
    if counselor["status"] != "ACTIVE":
        raise E.err(E.ERR_COUNSELOR_INACTIVE, "Counselor is not ACTIVE")
    if group["status"] != "ACTIVE":
        raise E.err(E.ERR_GROUP_INACTIVE, "Employer group is not ACTIVE")
    now = clock.now()
    ws = parse_iso(rec["window_start"])
    we = parse_iso(rec["window_end"])
    if now >= we:
        raise E.err(E.ERR_WINDOW_EXPIRED, "Enrollment window has expired")
    # group-level half-open overlap among OPEN campaigns
    for c in STORE.values():
        if c["id"] == rec["id"] or c["employer_group_id"] != rec["employer_group_id"]:
            continue
        if c["status"] != "OPEN":
            continue
        cs = parse_iso(c["window_start"])
        ce = parse_iso(c["window_end"])
        if _windows_overlap_halfopen(ws, we, cs, ce):
            raise E.err(E.ERR_CAMPAIGN_WINDOW_OVERLAP, "Overlaps an OPEN campaign of the group")
    # counselor double-booking under closed-interval semantics
    for c in STORE.values():
        if c["id"] == rec["id"] or c["counselor_id"] != rec["counselor_id"]:
            continue
        if c["status"] != "OPEN":
            continue
        cs = parse_iso(c["window_start"])
        ce = parse_iso(c["window_end"])
        if _windows_overlap_closed(ws, we, cs, ce):
            raise E.err(E.ERR_COUNSELOR_DOUBLE_BOOKED, "Counselor already leads an overlapping OPEN campaign")
    rec["status"] = "OPEN"
    db.touch(rec)
    return success_object(enrollment_campaign(rec))


@bp.route("/enrollment-campaigns/<rid>/lock", methods=["POST"])
def lock_campaign(role, user_id, rid):
    require_role(role, {"BenefitCounselor"})
    rec = get_or_404(STORE, rid)
    if rec["status"] != "OPEN":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot lock from {rec['status']}")
    now = clock.now()
    we = parse_iso(rec["window_end"])
    if now < we:
        raise E.err(E.ERR_WINDOW_NOT_CLOSED, "Window has not closed")
    rec["status"] = "LOCKED"
    db.touch(rec)
    return success_object(enrollment_campaign(rec))


@bp.route("/enrollment-campaigns/<rid>/close", methods=["POST"])
def close_campaign(role, user_id, rid):
    require_role(role, {"BenefitCounselor"})
    rec = get_or_404(STORE, rid)
    if rec["status"] in ("LOCKED",):
        pass
    elif rec["status"] in ("MET", "FAILED"):
        rec["status"] = "CLOSED"
        db.touch(rec)
        return success_object(enrollment_campaign(rec))
    else:
        raise E.err(E.ERR_INVALID_STATE, f"Cannot close from {rec['status']}")

    # OCC: expected_group_version (checked when provided)
    body = request.get_json(silent=True) or {}
    group = db.STORES["employer_groups"][rec["employer_group_id"]]
    expected = body.get("expected_group_version")
    if expected is not None and expected != group["version"]:
        raise E.err(E.ERR_STALE_VERSION, "expected_group_version does not match")

    # participation branch (deterministic)
    required = services.required_enrollments(group)
    enrolled = services.enrolled_count(group["id"])
    rec["required_enrollments"] = required
    if enrolled >= required:
        rec["participation_met"] = True
        rec["status"] = "MET"
        db.touch(rec)
        series_without_schedule = False
        # bulk issuance of APPLIED policies
        for p in list(db.STORES["policies"].values()):
            if p["campaign_id"] != rec["id"] or p["status"] != "APPLIED":
                continue
            series = db.STORES["policy_series"][p["policy_series_id"]]
            current_id = series.get("current_schedule_id")
            has_pub = bool(
                current_id
                and db.STORES["benefit_schedules"].get(current_id, {}).get("status") == "PUBLISHED"
            )
            if not has_pub:
                services.decline_policy(p)
                series_without_schedule = True
                continue
            result = services.issue_policy(p)
            if result and result[0] == "DECLINED":
                services.decline_policy(p)
        resp = enrollment_campaign(rec)
        if series_without_schedule:
            resp = dict(resp)
            resp["series_without_schedule"] = True
        return success_object(resp)
    else:
        rec["participation_met"] = False
        rec["status"] = "FAILED"
        db.touch(rec)
        for p in list(db.STORES["policies"].values()):
            if p["campaign_id"] == rec["id"] and p["status"] == "APPLIED":
                services.decline_policy(p)
        return success_object(enrollment_campaign(rec))


@bp.route("/enrollment-campaigns/<rid>/reopen", methods=["POST"])
def reopen_campaign(role, user_id, rid):
    require_role(role, {"BenefitCounselor"})
    rec = get_or_404(STORE, rid)
    if rec["status"] != "FAILED":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot reopen from {rec['status']}")
    body = request.get_json(silent=True) or {}
    new_end_raw = body.get("new_window_end")
    if new_end_raw is None:
        raise E.err(E.ERR_INVALID_REQUEST, "Missing required field: new_window_end")
    new_end = parse_iso(new_end_raw, "new_window_end")
    group = db.STORES["employer_groups"][rec["employer_group_id"]]
    if group["status"] != "ACTIVE":
        raise E.err(E.ERR_GROUP_INACTIVE, "Employer group is not ACTIVE")
    now = clock.now()
    old_end = parse_iso(rec["window_end"])
    if new_end <= now or new_end <= old_end:
        raise E.err(E.ERR_WINDOW_EXPIRED, "new_window_end must be strictly after now and old window_end")
    ws = parse_iso(rec["window_start"])
    for c in STORE.values():
        if c["id"] == rec["id"] or c["employer_group_id"] != rec["employer_group_id"]:
            continue
        if c["status"] != "OPEN":
            continue
        cs = parse_iso(c["window_start"])
        ce = parse_iso(c["window_end"])
        if _windows_overlap_halfopen(ws, new_end, cs, ce):
            raise E.err(E.ERR_CAMPAIGN_WINDOW_OVERLAP, "Extended window overlaps an OPEN campaign of the group")
    rec["window_end"] = db.format_ts(new_end)
    rec["participation_met"] = None
    rec["required_enrollments"] = None
    rec["status"] = "OPEN"
    db.touch(rec)
    for p in list(db.STORES["policies"].values()):
        if p["campaign_id"] == rec["id"] and p["status"] == "DECLINED":
            p["status"] = "APPLIED"
            db.touch(p)
    return success_object(enrollment_campaign(rec))


@bp.route("/enrollment-campaigns/<rid>/policies", methods=["GET"])
def list_policies(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "GroupAdmin", "BenefitCounselor"})
    get_or_404(STORE, rid)
    store = db.STORES["policies"]
    filters = {
        "campaign_id": rid,
        "status": request.args.get("status"),
    }
    return list_response(store, filters, policy_ser)
