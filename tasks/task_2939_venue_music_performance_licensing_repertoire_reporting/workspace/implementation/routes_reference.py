"""Clock, societies, rate schedules, venues and registered repertoire."""

from flask import Blueprint

import access
import calc
import db
import serializers
from core import (
    MUSIC_USE_PROFILES,
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLE_OFFICER,
    ROLE_OPERATOR,
    SCHEDULE_STATUSES,
    SOCIETY_CODES,
    VENUE_CATEGORIES,
    VENUE_STATUSES,
    COVERAGE_POSTURES,
    Ladder,
    P_DEPARTURE_STATE,
    P_REQUEST_SHAPE,
    P_SCHEDULE_PUBLISHABLE,
    P_UNIQUENESS,
    authenticate,
    body_or_empty,
    conflict,
    invalid_interval,
    invalid_request,
    iso,
    not_found,
    paginate,
    parse_instant,
    query_enum,
    query_flag,
    query_str,
    read_body,
    read_pagination,
    respond_list,
    respond_object,
    validate_fields,
)

bp = Blueprint("reference", __name__)

ALL_FOUR = [ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR, ROLE_OFFICER]


# ---------------------------------------------------------------------------
# PRD 2.4 -- the logical clock (the one unauthenticated endpoint)
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    body = read_body()
    if not isinstance(body, dict) or "current_utc" not in body:
        raise invalid_request("current_utc is required.")
    instant = parse_instant(body["current_utc"])
    if instant is None:
        raise invalid_request("current_utc must be an RFC 3339 UTC instant ending in Z.")
    db.set_now(instant)
    return respond_object({}, 200)


# ---------------------------------------------------------------------------
# Societies (PRD 3.1)
# ---------------------------------------------------------------------------

SOCIETY_SPEC = [
    ("society_code", "enum", {"required": True, "values": SOCIETY_CODES}),
    ("display_name", "str", {"required": True, "min": 1, "max": 120}),
    ("repertoire_share_bp", "int", {"required": True, "min": 0, "max": 10000}),
    ("rate_court_supervised", "bool", {"default": False}),
]


@bp.post("/licensing/societies")
def create_society():
    user_id, role = authenticate([ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    body = read_body()
    state = {}

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body, SOCIETY_SPEC)

    @ladder.check(P_UNIQUENESS)
    def _unique():
        code = state["fields"]["society_code"]
        for row in db.ordered("societies"):
            if row["society_code"] == code:
                raise conflict(
                    "ERR_DUPLICATE_SOCIETY_CODE", "That society_code is already registered."
                )

    ladder.run()
    fields = state["fields"]
    row = db.new_row("societies", dict(fields))
    return respond_object(serializers.society_json(row), 201)


@bp.get("/licensing/societies")
def list_societies():
    authenticate(ALL_FOUR)
    limit, offset = read_pagination()
    society_code = query_enum("society_code", SOCIETY_CODES)
    rows = [
        row
        for row in db.ordered("societies")
        if society_code is None or row["society_code"] == society_code
    ]
    page, total = paginate(rows, limit, offset)
    return respond_list([serializers.society_json(row) for row in page], limit, offset, total)


@bp.get("/licensing/societies/<society_id>")
def read_society(society_id):
    authenticate(ALL_FOUR)
    row = access.fetch("societies", society_id, access.ERR_SOCIETY, narrow=False)
    return respond_object(serializers.society_json(row))


# ---------------------------------------------------------------------------
# Rate schedules (PRD 3.2)
# ---------------------------------------------------------------------------

SCHEDULE_SPEC = [
    ("society_id", "str", {"required": True}),
    ("venue_category", "enum", {"required": True, "values": VENUE_CATEGORIES}),
    ("effective_from", "instant", {"required": True}),
    ("rate_court_order_ref", "str", {"nullable": True, "default": None}),
    ("adjustment_bp", "int", {"min": 5000, "max": 20000, "default": 10000}),
    ("min_annual_fee_cents", "int", {"min": 0, "default": 30000}),
    ("max_annual_fee_cents", "int", {"min": 0, "default": 4500000}),
]


@bp.post("/licensing/rate-schedules")
def create_schedule():
    user_id, role = authenticate([ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    body = read_body()
    state = {}

    @ladder.check(4)
    def _body_refs():
        from core import fk_candidate

        society_id = fk_candidate(body, "society_id")
        if society_id is not None and db.society(society_id) is None:
            raise not_found(access.ERR_SOCIETY)

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        if isinstance(body, dict) and "effective_from" in body and body["effective_from"] is None:
            # PRD 2.12 rule 11 names this exact clause as an interval failure.
            raise invalid_interval("effective_from must not be null.")
        fields = validate_fields(body, SCHEDULE_SPEC)
        if fields["max_annual_fee_cents"] <= fields["min_annual_fee_cents"]:
            raise invalid_request(
                "max_annual_fee_cents must be strictly greater than min_annual_fee_cents."
            )
        state["fields"] = fields

    ladder.run()
    fields = state["fields"]
    highest = 0
    for row in db.ordered("rate_schedules"):
        if (
            row["society_id"] == fields["society_id"]
            and row["venue_category"] == fields["venue_category"]
            and row["schedule_version"] > highest
        ):
            highest = row["schedule_version"]
    row = db.new_row(
        "rate_schedules",
        {
            "society_id": fields["society_id"],
            "venue_category": fields["venue_category"],
            "schedule_version": highest + 1,
            "effective_from": fields["effective_from"],
            "rate_court_order_ref": fields["rate_court_order_ref"],
            "adjustment_bp": fields["adjustment_bp"],
            "min_annual_fee_cents": fields["min_annual_fee_cents"],
            "max_annual_fee_cents": fields["max_annual_fee_cents"],
            "status": "DRAFT",
        },
    )
    return respond_object(serializers.schedule_json(row), 201)


@bp.post("/licensing/rate-schedules/<rate_schedule_id>/publish")
def publish_schedule(rate_schedule_id):
    user_id, role = authenticate([ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    schedule = access.fetch("rate_schedules", rate_schedule_id, access.ERR_SCHEDULE, narrow=False)

    @ladder.check(P_DEPARTURE_STATE)
    def _draft():
        if schedule["status"] != "DRAFT":
            raise conflict("ERR_RATE_SCHEDULE_NOT_DRAFT", "Only a DRAFT schedule may be published.")

    @ladder.check(P_SCHEDULE_PUBLISHABLE)
    def _reached():
        if schedule["effective_from"] > db.now():
            raise conflict(
                "ERR_RATE_SCHEDULE_NOT_DRAFT",
                "The logical clock has not yet reached effective_from.",
            )

    ladder.run()
    import services

    services.publish_schedule(schedule)
    return respond_object(serializers.schedule_json(schedule))


@bp.get("/licensing/rate-schedules")
def list_schedules():
    authenticate([ROLE_ADMIN, ROLE_AUDITOR, ROLE_OFFICER])
    limit, offset = read_pagination()
    society_id = query_str("society_id")
    venue_category = query_enum("venue_category", VENUE_CATEGORIES)
    status = query_enum("status", SCHEDULE_STATUSES)
    rows = []
    for row in db.ordered("rate_schedules"):
        if society_id is not None and row["society_id"] != society_id:
            continue
        if venue_category is not None and row["venue_category"] != venue_category:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return respond_list([serializers.schedule_json(row) for row in page], limit, offset, total)


@bp.get("/licensing/rate-schedules/<rate_schedule_id>")
def read_schedule(rate_schedule_id):
    authenticate([ROLE_ADMIN, ROLE_AUDITOR, ROLE_OFFICER])
    row = access.fetch("rate_schedules", rate_schedule_id, access.ERR_SCHEDULE, narrow=False)
    return respond_object(serializers.schedule_json(row))


# ---------------------------------------------------------------------------
# Venues (PRD 3.3)
# ---------------------------------------------------------------------------

VENUE_CREATE_SPEC = [
    ("legal_name", "str", {"required": True, "min": 1, "max": 160}),
    ("venue_category", "enum", {"required": True, "values": VENUE_CATEGORIES}),
    ("seating_capacity", "int", {"required": True, "min": 0}),
    ("standing_capacity", "int", {"required": True, "min": 0}),
    ("occupancy_limit", "int", {"required": True, "min": 1}),
    ("music_use_profile", "enum", {"required": True, "values": MUSIC_USE_PROFILES}),
    ("weekly_live_performance_nights", "int", {"required": True, "min": 0, "max": 7}),
    ("annual_cover_revenue_cents", "int", {"required": True, "min": 0}),
    ("gross_square_feet", "int", {"min": 0, "nullable": True, "default": None}),
    ("speaker_count", "int", {"min": 0, "nullable": True, "default": None}),
    ("max_speakers_per_room", "int", {"min": 0, "nullable": True, "default": None}),
    ("has_cover_charge", "bool", {"default": False}),
    ("retransmission_only", "bool", {"default": False}),
    ("uses_licensed_bgm_service", "bool", {"default": False}),
    ("bgm_service_provider", "str", {"nullable": True, "default": None}),
    ("status", "enum", {"values": VENUE_STATUSES, "default": "OPERATING"}),
]

# PRD 3.3: every field above except legal_name is revisable.
VENUE_PATCH_SPEC = [
    (name, kind, {key: value for key, value in opts.items() if key != "required"})
    for name, kind, opts in VENUE_CREATE_SPEC
    if name != "legal_name"
]
VENUE_PATCH_SPEC = [
    (name, kind, {key: value for key, value in opts.items() if key != "default"})
    for name, kind, opts in VENUE_PATCH_SPEC
]


@bp.post("/licensing/venues")
def create_venue():
    user_id, role = authenticate([ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    body = read_body()
    state = {}

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body, VENUE_CREATE_SPEC)

    ladder.run()
    fields = state["fields"]
    if not fields["uses_licensed_bgm_service"]:
        fields["bgm_service_provider"] = None
    fields.update(
        {
            "bgm_exemption_status": "NOT_ANALYZED",
            "bgm_exemption_reason": None,
            "covered_share_bp": 0,
            "coverage_posture": "UNCOVERED",
            "gap_risk_score_h": 0,
            "audit_hold": False,
            "lifetime_assessed_cents": 0,
            "outstanding_balance_cents": 0,
            "settled_amount_cents": 0,
            "voided_amount_cents": 0,
        }
    )
    row = db.new_row("venues", fields)
    return respond_object(serializers.venue_json(row), 201)


@bp.patch("/licensing/venues/<venue_id>")
def update_venue(venue_id):
    user_id, role = authenticate([ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    venue = access.fetch("venues", venue_id, access.ERR_VENUE, narrow=False)
    body = read_body()
    state = {}

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body if body is not None else {}, VENUE_PATCH_SPEC)

    ladder.run()
    venue.update(state["fields"])
    if not venue["uses_licensed_bgm_service"]:
        venue["bgm_service_provider"] = None
    # PRD 3.3: a survey revision discards the exemption verdict.
    venue["bgm_exemption_status"] = "NOT_ANALYZED"
    venue["bgm_exemption_reason"] = None
    db.touch(venue)
    return respond_object(serializers.venue_json(venue))


@bp.post("/licensing/venues/<venue_id>/exemption-analysis")
def analyse_exemption(venue_id):
    authenticate([ROLE_ADMIN])
    venue = access.fetch("venues", venue_id, access.ERR_VENUE, narrow=False)
    status, reason = calc.bgm_exemption(venue)
    venue["bgm_exemption_status"] = status
    venue["bgm_exemption_reason"] = reason
    db.touch(venue)
    return respond_object(serializers.venue_json(venue))


@bp.get("/licensing/venues")
def list_venues():
    authenticate([ROLE_ADMIN, ROLE_AUDITOR, ROLE_OFFICER])
    limit, offset = read_pagination()
    venue_category = query_enum("venue_category", VENUE_CATEGORIES)
    coverage_posture = query_enum("coverage_posture", COVERAGE_POSTURES)
    audit_hold = query_flag("audit_hold")
    status = query_enum("status", VENUE_STATUSES)
    rows = []
    for row in db.ordered("venues"):
        if venue_category is not None and row["venue_category"] != venue_category:
            continue
        if coverage_posture is not None and row["coverage_posture"] != coverage_posture:
            continue
        if audit_hold is not None and row["audit_hold"] != audit_hold:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return respond_list([serializers.venue_json(row) for row in page], limit, offset, total)


@bp.get("/licensing/venues/<venue_id>")
def read_venue(venue_id):
    authenticate(ALL_FOUR)
    row = access.fetch("venues", venue_id, access.ERR_VENUE)
    return respond_object(serializers.venue_json(row))


# ---------------------------------------------------------------------------
# Registered repertoire (PRD 3.1)
# ---------------------------------------------------------------------------

WORK_SPEC = [
    ("society_id", "str", {"required": True}),
    ("title", "str", {"required": True, "min": 1, "max": 200}),
    ("writer_name", "str", {"required": True, "min": 1, "max": 120}),
    ("iswc", "str", {"nullable": True, "default": None}),
]


@bp.post("/licensing/repertoire-works")
def create_work():
    user_id, role = authenticate([ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    body = read_body()
    state = {}

    @ladder.check(4)
    def _body_refs():
        from core import fk_candidate

        society_id = fk_candidate(body, "society_id")
        if society_id is not None and db.society(society_id) is None:
            raise not_found(access.ERR_SOCIETY)

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body, WORK_SPEC)

    ladder.run()
    row = db.new_thin_row("works", dict(state["fields"]))
    return respond_object(serializers.work_json(row), 201)


@bp.get("/licensing/repertoire-works")
def list_works():
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
    limit, offset = read_pagination()
    society_id = query_str("society_id")
    title = query_str("title")
    rows = []
    for row in db.ordered("works"):
        if society_id is not None and row["society_id"] != society_id:
            continue
        if title is not None and row["title"] != title:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return respond_list([serializers.work_json(row) for row in page], limit, offset, total)


@bp.get("/licensing/repertoire-works/<repertoire_work_id>")
def read_work(repertoire_work_id):
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
    row = access.fetch("works", repertoire_work_id, access.ERR_WORK, narrow=False)
    return respond_object(serializers.work_json(row))
