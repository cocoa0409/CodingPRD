"""Newsrooms, people, reviewers, the logical clock and the desk-wide reads."""

from decimal import Decimal

from flask import Blueprint

import calc
import serialize as ser
from auth import auth, require_ownership
from envelope import filter_param, paged, respond_object
from errors import ApiError
from helpers import journalist_or_404, newsroom_or_404, reviewer_or_404, rows
from store import base_record, db, fmt_ts, now, ordered, ordered_by, parse_iso, set_clock, touch
from validation import (DISCIPLINES, MODULE_CODES, ROLE_TITLES, e, enum_array, i,
                       read_raw_body, resolve_body_ids, s, validate_body)

bp = Blueprint("setup", __name__)

ALL_ROLES = ["Reporter", "StandardsEditor", "LegalCounsel", "ExecutiveEditor", "PublicEditor"]
DESK_ROLES = ["StandardsEditor", "ExecutiveEditor", "PublicEditor"]
REVIEWER_READ_ROLES = ["StandardsEditor", "LegalCounsel", "ExecutiveEditor"]


# ---------------------------------------------------------------------------
# POST /standards-desk/newsrooms  (bootstrap)
# ---------------------------------------------------------------------------

NEWSROOM_SPEC = {
    "name": s(required=True, min_len=1, max_len=120),
    "correction_response_sla_hours": i(minimum=1, maximum=336, default=72),
    "high_severity_open_threshold": i(minimum=1, maximum=20, default=2),
    "required_module_codes": enum_array(MODULE_CODES, default=["SOURCING"]),
}


@bp.route("/newsrooms", methods=["POST"])
def create_newsroom():
    auth(["ExecutiveEditor"], bootstrap=True)
    body = validate_body(read_raw_body(), NEWSROOM_SPEC)
    newsroom = base_record()
    newsroom.update({
        "name": body["name"],
        "correction_response_sla_hours": body["correction_response_sla_hours"],
        "high_severity_open_threshold": body["high_severity_open_threshold"],
        "required_module_codes": body["required_module_codes"],
        "standards_posture": "OPEN",
        "open_high_severity_count": 0,
        "training_compliance_index": Decimal("0.00"),
    })
    db.newsrooms[newsroom["id"]] = newsroom
    # Both derived figures are established by their own calculations.
    calc.recompute_compliance_index(newsroom)
    calc.recompute_posture(newsroom)
    return respond_object(ser.newsroom_out(newsroom), 201)


# ---------------------------------------------------------------------------
# POST /standards-desk/journalists  (bootstrap)
# ---------------------------------------------------------------------------

JOURNALIST_SPEC = {
    "newsroom_id": s(required=True),
    "full_name": s(required=True, min_len=1, max_len=120),
    "email": s(required=True, min_len=1, max_len=320, contains="@"),
    "role_title": e(ROLE_TITLES, required=True),
}


@bp.route("/journalists", methods=["POST"])
def create_journalist():
    auth(["ExecutiveEditor"], bootstrap=True)
    raw = read_raw_body()
    resolved = resolve_body_ids(raw, ["newsroom_id"])
    body = validate_body(raw, JOURNALIST_SPEC)
    newsroom = resolved["newsroom_id"]
    for other in db.journalists.values():
        if other["newsroom_id"] == newsroom["id"] and other["email"] == body["email"]:
            raise ApiError("ERR_INVALID_REQUEST",
                           "email must be unique within the newsroom.")
    journalist = base_record()
    journalist.update({
        "newsroom_id": newsroom["id"],
        "full_name": body["full_name"],
        "email": body["email"],
        "role_title": body["role_title"],
        "employment_status": "ACTIVE",
        "penalty_points": 0,
        "completed_required_module_count": 0,
        "training_current": False,
        "restricted_beats": [],
    })
    db.journalists[journalist["id"]] = journalist
    calc.recompute_journalist_training(journalist)
    # The cohort grew, so the desk-wide compliance index moves.
    if calc.recompute_compliance_index(newsroom):
        touch(newsroom)
    return respond_object(ser.journalist_out(journalist), 201)


# ---------------------------------------------------------------------------
# POST /standards-desk/reviewers
# ---------------------------------------------------------------------------

REVIEWER_SPEC = {
    "newsroom_id": s(required=True),
    "full_name": s(required=True, min_len=1, max_len=120),
    "discipline": e(DISCIPLINES, required=True),
    "weekly_capacity_minutes": i(minimum=60, maximum=4800, default=600),
}


@bp.route("/reviewers", methods=["POST"])
def create_reviewer():
    auth(["ExecutiveEditor"])
    raw = read_raw_body()
    resolved = resolve_body_ids(raw, ["newsroom_id"])
    body = validate_body(raw, REVIEWER_SPEC)
    reviewer = base_record()
    reviewer.update({
        "newsroom_id": resolved["newsroom_id"]["id"],
        "full_name": body["full_name"],
        "discipline": body["discipline"],
        "weekly_capacity_minutes": body["weekly_capacity_minutes"],
        "reserved_minutes": 0,
        "available_minutes": body["weekly_capacity_minutes"],
    })
    db.reviewers[reviewer["id"]] = reviewer
    return respond_object(ser.reviewer_out(reviewer), 201)


# ---------------------------------------------------------------------------
# POST /standards-desk/_clock/set_current_utc
# ---------------------------------------------------------------------------

CLOCK_SPEC = {"to_iso8601": s(required=True, min_len=1, max_len=64)}


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth(["ExecutiveEditor"])
    body = validate_body(read_raw_body(), CLOCK_SPEC)
    target = parse_iso(body["to_iso8601"])
    if target is None:
        raise ApiError("ERR_INVALID_INTERVAL",
                       "to_iso8601 is not a parseable ISO 8601 UTC instant.")
    set_clock(target)
    # breach_flag is derived on read, so every non-terminal correction request is
    # re-evaluated against the new reading with no further work here.
    return respond_object({"current_utc": fmt_ts(now())})


# ---------------------------------------------------------------------------
# Newsroom reads
# ---------------------------------------------------------------------------


@bp.route("/newsrooms/<newsroom_id>", methods=["GET"])
def read_newsroom(newsroom_id):
    auth(ALL_ROLES)
    return respond_object(ser.newsroom_out(newsroom_or_404(newsroom_id)))


@bp.route("/newsrooms/<newsroom_id>/standards-summary", methods=["GET"])
def standards_summary(newsroom_id):
    auth(DESK_ROLES)
    newsroom = newsroom_or_404(newsroom_id)
    stories = [st for st in db.stories.values() if st["newsroom_id"] == newsroom["id"]]
    story_ids = set(st["id"] for st in stories)
    published = len([st for st in stories if st["publication_status"] == "PUBLISHED"])
    open_requests = sum(st["open_correction_request_count"] for st in stories)
    breached = 0
    for c in db.corrections.values():
        if c["story_id"] in story_ids and calc.breach_flag(c):
            breached += 1
    count = calc.open_high_severity_count(newsroom["id"])
    data = {
        "standards_posture": calc.posture_for(count, newsroom["high_severity_open_threshold"]),
        "open_high_severity_count": count,
        "training_compliance_index": float(calc.training_compliance_index(newsroom)),
        "published_story_count": published,
        "open_correction_request_count": open_requests,
        "breached_correction_count": breached,
    }
    return respond_object(data)


@bp.route("/newsrooms/<newsroom_id>/journalists", methods=["GET"])
def list_newsroom_journalists(newsroom_id):
    auth(ALL_ROLES)
    newsroom = newsroom_or_404(newsroom_id)
    role_title = filter_param("role_title")
    employment_status = filter_param("employment_status")
    records = rows("journalists", lambda j: (
        j["newsroom_id"] == newsroom["id"]
        and (role_title is None or j["role_title"] == role_title)
        and (employment_status is None or j["employment_status"] == employment_status)))
    return paged(records, ser.journalist_out)


@bp.route("/newsrooms/<newsroom_id>/reviewers", methods=["GET"])
def list_newsroom_reviewers(newsroom_id):
    auth(REVIEWER_READ_ROLES)
    newsroom = newsroom_or_404(newsroom_id)
    discipline = filter_param("discipline")
    records = rows("reviewers", lambda r: (
        r["newsroom_id"] == newsroom["id"]
        and (discipline is None or r["discipline"] == discipline)))
    return paged(records, ser.reviewer_out)


@bp.route("/newsrooms/<newsroom_id>/audit-events", methods=["GET"])
def list_audit_events(newsroom_id):
    auth(DESK_ROLES)
    newsroom = newsroom_or_404(newsroom_id)
    event_type = filter_param("event_type")
    subject_type = filter_param("subject_type")
    selected = [ev for ev in db.audit_events.values()
                if ev["newsroom_id"] == newsroom["id"]
                and (event_type is None or ev["event_type"] == event_type)
                and (subject_type is None or ev["subject_type"] == subject_type)]
    # The log is append-only in occurred_at order.
    return paged(ordered_by(selected, "occurred_at"), ser.audit_out)


# ---------------------------------------------------------------------------
# Journalist and reviewer reads
# ---------------------------------------------------------------------------


@bp.route("/journalists/<journalist_id>", methods=["GET"])
def read_journalist(journalist_id):
    auth(ALL_ROLES)
    return respond_object(ser.journalist_out(journalist_or_404(journalist_id)))


@bp.route("/journalists/<journalist_id>/conflict-disclosures", methods=["GET"])
def list_journalist_disclosures(journalist_id):
    auth(["Reporter", "StandardsEditor", "ExecutiveEditor", "PublicEditor"])
    journalist = journalist_or_404(journalist_id)
    status = filter_param("status")
    records = rows("disclosures", lambda d: (
        d["journalist_id"] == journalist["id"]
        and (status is None or d["status"] == status)))
    return paged(records, ser.disclosure_out)


@bp.route("/journalists/<journalist_id>/outside-activity-requests", methods=["GET"])
def list_journalist_activities(journalist_id):
    auth(["Reporter", "StandardsEditor", "ExecutiveEditor", "PublicEditor"])
    journalist = journalist_or_404(journalist_id)
    status = filter_param("status")
    activity_type = filter_param("activity_type")
    records = rows("activities", lambda a: (
        a["journalist_id"] == journalist["id"]
        and (status is None or a["status"] == status)
        and (activity_type is None or a["activity_type"] == activity_type)))
    return paged(records, ser.activity_out)


@bp.route("/journalists/<journalist_id>/training-records", methods=["GET"])
def list_journalist_training(journalist_id):
    auth(["Reporter", "StandardsEditor", "ExecutiveEditor"])
    journalist = journalist_or_404(journalist_id)
    module_code = filter_param("module_code")
    records = rows("training_records", lambda t: (
        t["journalist_id"] == journalist["id"]
        and (module_code is None or t["module_code"] == module_code)))
    return paged(records, ser.training_out)


@bp.route("/reviewers/<reviewer_id>", methods=["GET"])
def read_reviewer(reviewer_id):
    auth(REVIEWER_READ_ROLES)
    return respond_object(ser.reviewer_out(reviewer_or_404(reviewer_id)))
