"""Licence applications: filing, revision, submission, review and withdrawal."""

from flask import Blueprint

import access
import calc
import db
import serializers
from core import (
    APPLICATION_DISPOSITIONS,
    APPLICATION_STATUSES,
    DECLINE_REASONS,
    LICENSE_TYPES,
    MAX_REVISION_ROUNDS,
    MUSIC_USE_PROFILES,
    RETURN_REASONS,
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLE_OPERATOR,
    TERM_DAYS,
    Ladder,
    P_AUDIT_HOLD,
    P_AUTHORISATION,
    P_BODY_REFERENCE,
    P_DEPARTURE_STATE,
    P_EFFECTIVE_SCHEDULE,
    P_EXEMPTION_ANALYSED,
    P_REQUEST_SHAPE,
    P_STALE_PARENT,
    P_UNIQUENESS,
    P_VENUE_OPERATING,
    authenticate,
    conflict,
    fk_candidate,
    forbidden,
    invalid_request,
    not_found,
    paginate,
    plus_days,
    precondition,
    query_enum,
    query_str,
    read_body,
    read_pagination,
    respond_list,
    respond_object,
    validate_fields,
)

bp = Blueprint("applications", __name__)

APPLICATION_CREATE_SPEC = [
    ("venue_id", "str", {"required": True}),
    ("society_id", "str", {"required": True}),
    ("requested_license_type", "enum", {"required": True, "values": LICENSE_TYPES}),
    ("declared_seating", "int", {"required": True, "min": 0}),
    ("declared_standing", "int", {"required": True, "min": 0}),
    ("declared_cover_revenue_cents", "int", {"required": True, "min": 0}),
    ("declared_live_nights", "int", {"required": True, "min": 0, "max": 7}),
    ("declared_music_use_profile", "enum", {"required": True, "values": MUSIC_USE_PROFILES}),
    ("requested_term_start", "instant", {"required": True}),
    ("expected_venue_version", "int", {"required": True, "min": 0}),
]

APPLICATION_PATCH_SPEC = [
    ("requested_license_type", "enum", {"values": LICENSE_TYPES}),
    ("declared_seating", "int", {"min": 0}),
    ("declared_standing", "int", {"min": 0}),
    ("declared_cover_revenue_cents", "int", {"min": 0}),
    ("declared_live_nights", "int", {"min": 0, "max": 7}),
    ("declared_music_use_profile", "enum", {"values": MUSIC_USE_PROFILES}),
    ("requested_term_start", "instant", {}),
]

REVIEW_SPEC = [
    ("disposition", "enum", {"required": True, "values": APPLICATION_DISPOSITIONS}),
    ("return_reason", "enum", {"nullable": True, "values": RETURN_REASONS}),
    ("decline_reason", "enum", {"nullable": True, "values": DECLINE_REASONS}),
]

LIVE_APPLICATION_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "RETURNED_FOR_REVISION")


@bp.post("/licensing/license-applications")
def create_application():
    user_id, role = authenticate([ROLE_OPERATOR, ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    body = read_body()
    state = {}

    @ladder.check(P_AUTHORISATION)
    def _ownership():
        if role != ROLE_OPERATOR:
            return
        declared = fk_candidate(body, "venue_id")
        if declared is not None and declared != user_id:
            raise forbidden("A VenueOperator may only file for its own venue.")

    @ladder.check(P_BODY_REFERENCE)
    def _body_refs():
        venue_id = fk_candidate(body, "venue_id")
        if venue_id is not None and db.venue(venue_id) is None:
            raise not_found(access.ERR_VENUE)
        society_id = fk_candidate(body, "society_id")
        if society_id is not None and db.society(society_id) is None:
            raise not_found(access.ERR_SOCIETY)

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body, APPLICATION_CREATE_SPEC)

    @ladder.check(P_STALE_PARENT)
    def _stale():
        venue = db.venue(state["fields"]["venue_id"])
        if state["fields"]["expected_venue_version"] != venue["version"]:
            raise precondition(
                "ERR_STALE_VENUE_VERSION", "The venue has been revised since it was last read."
            )

    ladder.run()
    fields = state["fields"]
    venue = db.venue(fields["venue_id"])
    row = db.new_row(
        "applications",
        {
            "venue_id": fields["venue_id"],
            "society_id": fields["society_id"],
            "requested_license_type": fields["requested_license_type"],
            "assigned_license_type": None,
            "declared_seating": fields["declared_seating"],
            "declared_standing": fields["declared_standing"],
            "declared_cover_revenue_cents": fields["declared_cover_revenue_cents"],
            "declared_live_nights": fields["declared_live_nights"],
            "declared_music_use_profile": fields["declared_music_use_profile"],
            "requested_term_start": fields["requested_term_start"],
            "provisional_annual_fee_cents": None,
            "status": "DRAFT",
            "revision_round": 0,
            "return_reason": None,
            "decline_reason": None,
        },
    )
    # PRD 3.4: the named venue's version increments by 1.
    db.touch(venue)
    # PRD 3.4: every other live application for the pair is superseded.
    for other in db.where("applications", venue_id=row["venue_id"], society_id=row["society_id"]):
        if other["id"] == row["id"] or other["status"] not in LIVE_APPLICATION_STATUSES:
            continue
        other["status"] = "WITHDRAWN"
        db.touch(other)
    return respond_object(serializers.application_json(row), 201)


@bp.patch("/licensing/license-applications/<application_id>")
def update_application(application_id):
    user_id, role = authenticate([ROLE_OPERATOR, ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    application = access.fetch("applications", application_id, access.ERR_APPLICATION)
    body = read_body()
    state = {}

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body if body is not None else {}, APPLICATION_PATCH_SPEC)

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if application["status"] != "DRAFT":
            raise conflict(
                "ERR_APPLICATION_STATE_INVALID", "Only a DRAFT application may be revised."
            )

    ladder.run()
    application.update(state["fields"])
    db.touch(application)
    return respond_object(serializers.application_json(application))


@bp.post("/licensing/license-applications/<application_id>/submit")
def submit_application(application_id):
    user_id, role = authenticate([ROLE_OPERATOR, ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    application = access.fetch("applications", application_id, access.ERR_APPLICATION)
    venue = db.venue(application["venue_id"])

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if application["status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
            raise conflict(
                "ERR_APPLICATION_STATE_INVALID",
                "Only a DRAFT or RETURNED_FOR_REVISION application may be submitted.",
            )

    @ladder.check(P_VENUE_OPERATING)
    def _operating():
        if venue["status"] != "OPERATING":
            raise conflict(
                "ERR_APPLICATION_STATE_INVALID", "A closed establishment cannot submit."
            )

    @ladder.check(P_AUDIT_HOLD)
    def _hold():
        if venue["audit_hold"]:
            raise conflict("ERR_AUDIT_HOLD_ACTIVE", "The venue is under an audit hold.")

    ladder.run()
    application["status"] = "SUBMITTED"
    application["return_reason"] = None
    db.touch(application)
    return respond_object(serializers.application_json(application))


@bp.post("/licensing/license-applications/<application_id>/withdraw")
def withdraw_application(application_id):
    user_id, role = authenticate([ROLE_OPERATOR, ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    application = access.fetch("applications", application_id, access.ERR_APPLICATION)

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if application["status"] not in ("DRAFT", "SUBMITTED", "RETURNED_FOR_REVISION"):
            raise conflict(
                "ERR_APPLICATION_STATE_INVALID", "This application has already been decided."
            )

    ladder.run()
    application["status"] = "WITHDRAWN"
    db.touch(application)
    return respond_object(serializers.application_json(application))


@bp.get("/licensing/license-applications")
def list_applications():
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
    limit, offset = read_pagination()
    venue_id = query_str("venue_id")
    society_id = query_str("society_id")
    status = query_enum("status", APPLICATION_STATUSES)
    rows = []
    for row in access.narrow_rows("applications", db.ordered("applications")):
        if venue_id is not None and row["venue_id"] != venue_id:
            continue
        if society_id is not None and row["society_id"] != society_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return respond_list([serializers.application_json(row) for row in page], limit, offset, total)


@bp.get("/licensing/license-applications/<application_id>")
def read_application(application_id):
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
    row = access.fetch("applications", application_id, access.ERR_APPLICATION)
    return respond_object(serializers.application_json(row))


def terms_overlap(start_a, end_a, start_b, end_b):
    """Half-open overlap (PRD 2.8): adjacency is not overlap."""
    return start_a < end_b and start_b < end_a


def duplicate_active_license(venue_id, society_id, term_start, term_end, exclude_id=None):
    for lic in db.licenses_of_venue(venue_id):
        if lic["society_id"] != society_id or lic["id"] == exclude_id:
            continue
        if lic["coverage_status"] not in ("PENDING_ACTIVATION", "ACTIVE", "SUSPENDED"):
            continue
        if terms_overlap(term_start, term_end, lic["term_start"], lic["term_end"]):
            return lic
    return None


@bp.post("/licensing/license-applications/<application_id>/review")
def review_application(application_id):
    user_id, role = authenticate([ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    application = access.fetch("applications", application_id, access.ERR_APPLICATION)
    venue = db.venue(application["venue_id"])
    body = read_body()
    state = {}

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        fields = validate_fields(body, REVIEW_SPEC)
        disposition = fields["disposition"]
        if disposition == "RETURN_FOR_REVISION" and fields.get("return_reason") is None:
            raise invalid_request("RETURN_FOR_REVISION requires a return_reason.")
        if disposition == "DECLINE" and fields.get("decline_reason") is None:
            raise invalid_request("DECLINE requires a decline_reason.")
        state["fields"] = fields

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        disposition = state["fields"]["disposition"]
        required = "SUBMITTED" if disposition == "ACCEPT_FOR_REVIEW" else "UNDER_REVIEW"
        if application["status"] != required:
            raise conflict(
                "ERR_APPLICATION_STATE_INVALID",
                "This disposition may not depart from %s." % application["status"],
            )

    @ladder.check(P_AUDIT_HOLD)
    def _hold():
        if state["fields"]["disposition"] == "APPROVE" and venue["audit_hold"]:
            raise conflict("ERR_AUDIT_HOLD_ACTIVE", "The venue is under an audit hold.")

    @ladder.check(P_UNIQUENESS)
    def _unique():
        if state["fields"]["disposition"] != "APPROVE":
            return
        term_start = application["requested_term_start"]
        term_end = plus_days(term_start, TERM_DAYS)
        if duplicate_active_license(
            application["venue_id"], application["society_id"], term_start, term_end
        ):
            raise conflict(
                "ERR_DUPLICATE_ACTIVE_LICENSE",
                "An overlapping licence already exists for this venue and society.",
            )

    @ladder.check(P_EXEMPTION_ANALYSED)
    def _analysed():
        if state["fields"]["disposition"] != "APPROVE":
            return
        if (
            application["requested_license_type"] == "BGM_EXEMPT"
            and venue["bgm_exemption_status"] == "NOT_ANALYZED"
        ):
            raise conflict(
                "ERR_APPLICATION_STATE_INVALID",
                "An unanalysed venue cannot be approved onto an exemption-based licence.",
            )

    @ladder.check(P_EFFECTIVE_SCHEDULE)
    def _schedule():
        if state["fields"]["disposition"] != "APPROVE":
            return
        schedule = calc.select_schedule(application["society_id"], venue["venue_category"])
        if schedule is None:
            raise conflict(
                "ERR_NO_EFFECTIVE_RATE_SCHEDULE",
                "No EFFECTIVE rate schedule covers this society and venue category.",
            )
        state["schedule"] = schedule

    ladder.run()
    fields = state["fields"]
    disposition = fields["disposition"]

    if disposition == "ACCEPT_FOR_REVIEW":
        application["status"] = "UNDER_REVIEW"
        db.touch(application)
        return respond_object(serializers.application_json(application))

    if disposition == "RETURN_FOR_REVISION":
        if application["revision_round"] >= MAX_REVISION_ROUNDS:
            application["status"] = "DECLINED"
            application["decline_reason"] = "REVISION_LIMIT_EXCEEDED"
        else:
            application["status"] = "RETURNED_FOR_REVISION"
            application["revision_round"] += 1
            application["return_reason"] = fields["return_reason"]
        db.touch(application)
        return respond_object(serializers.application_json(application))

    if disposition == "DECLINE":
        application["status"] = "DECLINED"
        application["decline_reason"] = fields["decline_reason"]
        db.touch(application)
        return respond_object(serializers.application_json(application))

    # APPROVE
    schedule = state["schedule"]
    society = db.society(application["society_id"])
    assigned = calc.assign_license_type(venue, application["requested_license_type"])
    provisional = calc.provisional_fee(schedule, society, application, assigned)
    application["assigned_license_type"] = assigned
    application["provisional_annual_fee_cents"] = provisional
    application["status"] = "APPROVED"
    db.touch(application)

    term_start = application["requested_term_start"]
    db.new_row(
        "licenses",
        {
            "venue_id": application["venue_id"],
            "society_id": application["society_id"],
            "application_id": application["id"],
            "rate_schedule_id": schedule["id"],
            "renewal_of_license_id": None,
            "pinned_schedule_version": schedule["schedule_version"],
            "license_type": assigned,
            "term_start": term_start,
            "term_end": plus_days(term_start, TERM_DAYS),
            "provisional_annual_fee_cents": provisional,
            "annual_fee_cents": provisional,
            "verified_fee_delta_cents": 0,
            "coverage_status": "PENDING_ACTIVATION",
            "billing_status": "UNBILLED",
            "suspension_reason": None,
            "reporting_required": calc.reporting_required(assigned, venue),
            "accepted_report_count": 0,
            "renewal_issued_at": None,
        },
    )
    return respond_object(serializers.application_json(application))
