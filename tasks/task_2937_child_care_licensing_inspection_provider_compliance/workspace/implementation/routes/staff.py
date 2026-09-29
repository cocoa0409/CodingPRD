"""People attached to a site and their registry clearances (PRD §3.2, §3.3)."""

from flask import Blueprint, request

import clock
import constants as K
import derive
import envelope
import helpers
import serialize
import store
import validate
from auth import authenticate, require_provider_owner
from errors import ApiError
from validate import F

bp = Blueprint("staff", __name__)

STAFF_ROLES = (
    "AgencyAdmin",
    "Applicant",
    "LicensingSupervisor",
    "LicensingInspector",
    "BackgroundCheckUnit",
)
CHECK_READERS = ("AgencyAdmin", "Applicant", "LicensingSupervisor", "BackgroundCheckUnit")

STAFF_INPUT = [
    F("provider_id", "string", required=True),
    F("full_name", "string", required=True, min_len=1, max_len=120, not_blank=True),
    F("member_type", "enum", required=True, values=K.MEMBER_TYPES),
    F("date_of_birth", "date", required=True),
    F("qualified_age_groups", "enum_array", required=True, values=K.AGE_GROUPS, unique=True),
    F("role_title", "string"),
]


@bp.post("/licensing/staff-members")
def create_staff_member():
    user_id, role = authenticate(("Applicant", "AgencyAdmin"))
    vals = validate.body(STAFF_INPUT)
    provider = helpers.need("provider", vals["provider_id"])
    require_provider_owner(role, user_id, provider["id"])
    record = {
        "provider_id": provider["id"],
        "full_name": vals["full_name"],
        "member_type": vals["member_type"],
        "role_title": vals.get("role_title"),
        "date_of_birth": vals["date_of_birth"],
        "qualified_age_groups": list(vals["qualified_age_groups"]),
    }
    store.create(store.staff_members, record)
    store.touch(provider)
    return envelope.created(serialize.staff_member(record))


@bp.get("/licensing/staff-members")
def list_staff_members():
    authenticate(STAFF_ROLES)
    limit, offset = envelope.pagination(request.args)
    member_type = validate.query_enum("member_type", K.MEMBER_TYPES)
    clearance_status = validate.query_enum("clearance_status", K.CLEARANCE_STATUSES)
    provider_id = validate.query_str("provider_id")
    rows = store.ordered(store.staff_members)
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if member_type is not None:
        rows = [r for r in rows if r["member_type"] == member_type]
    if clearance_status is not None:
        rows = [r for r in rows if derive.clearance_status_of(r) == clearance_status]
    return helpers.listing(rows, serialize.staff_member, limit, offset)


@bp.get("/licensing/staff-members/<staff_member_id>")
def read_staff_member(staff_member_id):
    authenticate(STAFF_ROLES)
    record = helpers.need("staff_member", staff_member_id)
    return envelope.ok(serialize.staff_member(record))


@bp.post("/licensing/background-checks")
def create_background_check():
    user_id, role = authenticate(("BackgroundCheckUnit", "Applicant", "AgencyAdmin"))
    vals = validate.body(
        [
            F("staff_member_id", "string", required=True),
            F("check_type", "enum", required=True, values=K.CHECK_TYPES),
        ]
    )
    staff = helpers.need("staff_member", vals["staff_member_id"])
    require_provider_owner(role, user_id, staff["provider_id"])
    for existing in store.checks_of(staff["id"]):
        if (
            existing["check_type"] == vals["check_type"]
            and existing["status"] in K.LIVE_CHECK_STATUSES
        ):
            raise ApiError(
                "ERR_DUPLICATE_CHECK_TYPE",
                "A live check of this type already exists for this person.",
            )
    record = {
        "staff_member_id": staff["id"],
        "check_type": vals["check_type"],
        "status": "SUBMITTED",
        "disqualifying_offense_tier": None,
        "submitted_at": clock.now(),
        "decided_at": None,
        "expires_at": None,
        "waiver_requested_at": None,
        "waiver_rationale": None,
        "waiver_decided_at": None,
    }
    store.create(store.background_checks, record)
    return envelope.created(serialize.background_check(record))


@bp.get("/licensing/background-checks")
def list_background_checks():
    authenticate(CHECK_READERS)
    limit, offset = envelope.pagination(request.args)
    check_type = validate.query_enum("check_type", K.CHECK_TYPES)
    status = validate.query_enum("status", K.CHECK_STATUSES)
    staff_member_id = validate.query_str("staff_member_id")
    rows = store.ordered(store.background_checks)
    if staff_member_id is not None:
        rows = [r for r in rows if r["staff_member_id"] == staff_member_id]
    if check_type is not None:
        rows = [r for r in rows if r["check_type"] == check_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return helpers.listing(rows, serialize.background_check, limit, offset)


@bp.get("/licensing/background-checks/<background_check_id>")
def read_background_check(background_check_id):
    authenticate(CHECK_READERS)
    record = helpers.need("background_check", background_check_id)
    return envelope.ok(serialize.background_check(record))


@bp.post("/licensing/background-checks/<background_check_id>/result")
def record_check_result(background_check_id):
    authenticate(("BackgroundCheckUnit",))
    vals = validate.body(
        [
            F("result", "enum", required=True, values=K.CHECK_RESULTS),
            F(
                "disqualifying_offense_tier",
                "enum",
                values=K.OFFENSE_TIERS,
            ),
        ]
    )
    check = helpers.need("background_check", background_check_id)
    if check["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CHECK_STATE", "The check is no longer SUBMITTED.")
    tier = vals.get("disqualifying_offense_tier")
    if vals["result"] == "CLEARED":
        if tier is not None and tier != "NONE":
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "A CLEARED result may not carry a disqualifying offense tier.",
            )
    else:
        if tier is None or tier == "NONE":
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "A DISQUALIFIED result requires a disqualifying offense tier.",
            )
    staff, provider = derive.check_context(check)
    before = derive.clearance_snapshot(staff, provider)
    now = clock.now()
    if vals["result"] == "CLEARED":
        check["status"] = "CLEARED"
        check["decided_at"] = now
        check["expires_at"] = clock.fmt(
            clock.add_months(clock.now_dt(), K.CLEARANCE_VALIDITY_MONTHS)
        )
    else:
        check["status"] = "DISQUALIFIED"
        check["decided_at"] = now
        check["disqualifying_offense_tier"] = tier
    store.touch(check)
    derive.propagate_check_change(check, before, always_touch_provider=True)
    return envelope.ok(serialize.background_check(check))


@bp.post("/licensing/background-checks/<background_check_id>/waiver")
def request_waiver(background_check_id):
    user_id, role = authenticate(("Applicant",))
    vals = validate.body(
        [F("waiver_rationale", "string", required=True, min_len=10, max_len=1000)]
    )
    check = helpers.need("background_check", background_check_id)
    staff, provider = derive.check_context(check)
    require_provider_owner(role, user_id, staff["provider_id"])
    if check["status"] != "DISQUALIFIED":
        raise ApiError("ERR_INVALID_CHECK_STATE", "The check is not DISQUALIFIED.")
    if check.get("disqualifying_offense_tier") == "TIER_1_PERMANENT":
        raise ApiError(
            "ERR_PERMANENT_BAR_NOT_WAIVABLE", "A permanent bar can never be waived."
        )
    before = derive.clearance_snapshot(staff, provider)
    check["status"] = "WAIVER_PENDING"
    check["waiver_requested_at"] = clock.now()
    check["waiver_rationale"] = vals["waiver_rationale"]
    store.touch(check)
    derive.propagate_check_change(check, before)
    return envelope.ok(serialize.background_check(check))


@bp.post("/licensing/background-checks/<background_check_id>/waiver-decision")
def decide_waiver(background_check_id):
    authenticate(("LicensingSupervisor",))
    vals = validate.body(
        [F("decision", "enum", required=True, values=K.WAIVER_DECISIONS)]
    )
    check = helpers.need("background_check", background_check_id)
    if check["status"] != "WAIVER_PENDING":
        raise ApiError("ERR_INVALID_CHECK_STATE", "The check is not WAIVER_PENDING.")
    staff, provider = derive.check_context(check)
    before = derive.clearance_snapshot(staff, provider)
    now = clock.now()
    if vals["decision"] == "GRANT":
        check["status"] = "WAIVED"
        check["waiver_decided_at"] = now
        check["expires_at"] = clock.fmt(
            clock.add_months(clock.now_dt(), K.CLEARANCE_VALIDITY_MONTHS)
        )
    else:
        check["status"] = "DISQUALIFIED"
        check["waiver_decided_at"] = now
    store.touch(check)
    derive.propagate_check_change(check, before)
    return envelope.ok(serialize.background_check(check))
